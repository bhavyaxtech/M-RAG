"""Conversational M-RAG demo over five hardware datasheets.

The UI orchestrates the agent stage by stage so the on-screen progress tracks
real work: routing, retrieval, and a streamed answer. Retrieval and generation
themselves live in ``scripts/``; nothing in this file touches Azure or FAISS
directly.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, cast

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import components  # noqa: E402
import styles  # noqa: E402
from scripts.agent import (  # noqa: E402
    Evidence,
    RouterDecision,
    answer_stream,
    cited_labels,
    gather_evidence,
    generation_deployment,
    provenance,
    route_question,
    router_deployment,
)
from scripts.embed_and_index import (  # noqa: E402
    INDEX_DIR,
    METADATA_FILENAME,
    MRAG_INDEX_FILENAME,
)
from scripts.query import QueryMode  # noqa: E402


RETRIEVAL_DEPTH = 5
EVIDENCE_PLACEHOLDER = (
    "Retrieved figures, tables, and text will appear here, with the ones the "
    "answer cites highlighted."
)
EXAMPLES = (
    "Which module pin is TXD0 on the ESP32-WROOM-32E?",
    "What is the maximum output current of the LM317?",
    "How many GPIO pins does the RP2040 expose, and what alternate functions do they carry?",
)

st.set_page_config(
    page_title="M-RAG Hardware Datasheets",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="collapsed",
)
styles.inject()


def _history(limit: int | None = None) -> list[dict[str, str]]:
    """Flatten stored turns into role/content messages for prompt context."""
    messages: list[dict[str, str]] = []
    turns = st.session_state.get("turns", [])
    for turn in turns if limit is None else turns[-limit:]:
        messages.append({"role": "user", "content": turn["message"]})
        messages.append({"role": "assistant", "content": turn["answer"]})
    return messages


def _render_past_turn(turn: dict[str, Any]) -> None:
    with st.chat_message("user"):
        st.markdown(turn["message"])

    with st.chat_message("assistant"):
        st.markdown('<div class="mrag-agent-anchor"></div>', unsafe_allow_html=True)
        st.markdown(
            components.trace_html(turn["decision"], turn["evidence"], turn["mode"]),
            unsafe_allow_html=True,
        )
        st.markdown(components.badge_html(turn["provenance"]), unsafe_allow_html=True)
        st.markdown(
            components.answer_markdown(turn["answer"], turn["labels"]),
            unsafe_allow_html=True,
        )
        with st.expander("Why this answer"):
            st.markdown(
                components.why_html(
                    turn["decision"],
                    turn["evidence"],
                    turn["cited"],
                    turn["mode"],
                ),
                unsafe_allow_html=True,
            )
        st.markdown(
            components.footer_html(
                turn["generation_deployment"],
                turn["router_deployment"],
                turn["evidence"],
                turn["cited"],
                turn["used_history"],
            ),
            unsafe_allow_html=True,
        )


def _run_turn(message: str, mode: QueryMode, evidence_slot: Any) -> dict[str, Any]:
    """Drive one agent turn, updating the UI as each stage actually completes."""
    history = _history()
    used_history = bool(history)

    # Seed the rail before routing. Without this the column is blank for the
    # whole turn on a general question, which never reaches retrieval.
    with evidence_slot.container():
        components.evidence_panel(None, [], EVIDENCE_PLACEHOLDER)

    with st.chat_message("assistant"):
        st.markdown('<div class="mrag-agent-anchor"></div>', unsafe_allow_html=True)
        status = st.empty()
        badge = st.empty()
        body = st.empty()

        completed: list[str] = []
        status.markdown(components.stages_html(completed, "route"), unsafe_allow_html=True)
        decision = route_question(message, history)
        completed.append("route")

        evidence = Evidence()
        if decision.route == "datasheet":
            status.markdown(
                components.stages_html(completed, "retrieve"), unsafe_allow_html=True
            )
            evidence = gather_evidence(
                decision.search_query, mode, k=RETRIEVAL_DEPTH
            )
            completed.append("retrieve")
            with evidence_slot.container():
                components.evidence_panel(evidence, [], "")
            if mode == "mrag" and evidence.grounded and evidence.visual_count:
                status.markdown(
                    components.stages_html(completed, "read"), unsafe_allow_html=True
                )
                completed.append("read")

        status.markdown(components.stages_html(completed, "answer"), unsafe_allow_html=True)

        labels = [str(segment.get("label")) for segment in evidence.segments]
        answer = ""
        for delta in answer_stream(message, decision, evidence, mode, history):
            answer += delta
            body.markdown(
                components.answer_markdown(answer, labels)
                + '<span class="mrag-cursor"></span>',
                unsafe_allow_html=True,
            )

        answer = answer.strip()
        cited = cited_labels(answer, evidence.segments)
        kind = provenance(decision, evidence, cited)

        status.markdown(
            components.trace_html(decision, evidence, mode), unsafe_allow_html=True
        )
        badge.markdown(components.badge_html(kind), unsafe_allow_html=True)
        body.markdown(
            components.answer_markdown(answer, labels), unsafe_allow_html=True
        )

        with st.expander("Why this answer"):
            st.markdown(
                components.why_html(decision, evidence, cited, mode),
                unsafe_allow_html=True,
            )
        st.markdown(
            components.footer_html(
                generation_deployment(),
                router_deployment(),
                evidence,
                cited,
                used_history,
            ),
            unsafe_allow_html=True,
        )

    if decision.route == "datasheet":
        with evidence_slot.container():
            components.evidence_panel(evidence, cited, "")

    return {
        "message": message,
        "answer": answer,
        "mode": mode,
        "decision": decision,
        "evidence": evidence,
        "cited": cited,
        "labels": labels,
        "provenance": kind,
        "used_history": used_history,
        "generation_deployment": generation_deployment(),
        "router_deployment": router_deployment(),
    }


def _indexes_ready() -> bool:
    return (INDEX_DIR / MRAG_INDEX_FILENAME).is_file() and (
        INDEX_DIR / METADATA_FILENAME
    ).is_file()


st.session_state.setdefault("turns", [])

submitted = st.chat_input("Ask about a pin, a rating, a timing value, or anything else")
pending = st.session_state.pop("pending", None)
message = (submitted or pending or "").strip()

components.header()

mode_column, action_column = st.columns([0.72, 0.28], gap="small")
with mode_column:
    mode_choice = st.segmented_control(
        "Retrieval mode",
        options=["M-RAG", "Text-only baseline"],
        default="M-RAG",
        label_visibility="collapsed",
        key="mode_choice",
    )
    mode = cast(QueryMode, "mrag" if mode_choice != "Text-only baseline" else "text_only")
    st.markdown(
        '<p class="mrag-mode-note">'
        + (
            "Figures and tables are retrieved as evidence and their crops are read directly."
            if mode == "mrag"
            else "Same vectors, same code path, every visual excluded. This is the paper baseline."
        )
        + "</p>",
        unsafe_allow_html=True,
    )
with action_column:
    if st.session_state["turns"] and st.button("Clear conversation", use_container_width=True):
        st.session_state["turns"] = []
        st.rerun()

components.rule()

conversation_column, evidence_column = st.columns([1.55, 1], gap="large")
with evidence_column:
    evidence_slot = st.empty()

with conversation_column:
    components.section_label("Conversation")

    if not _indexes_ready():
        st.error(
            f"No index found in {INDEX_DIR}. Run scripts/parse.py, scripts/caption.py, "
            "and scripts/embed_and_index.py before starting the demo."
        )
        st.stop()

    for turn in st.session_state["turns"]:
        _render_past_turn(turn)

    if not st.session_state["turns"] and not message:
        st.markdown(
            '<div class="mrag-empty">Ask a question to start. The agent decides on its own '
            "whether to search the datasheets.</div>",
            unsafe_allow_html=True,
        )
        for index, example in enumerate(EXAMPLES):
            if st.button(example, key=f"example_{index}", use_container_width=True):
                st.session_state["pending"] = example
                st.rerun()

    if message:
        with st.chat_message("user"):
            st.markdown(message)
        try:
            st.session_state["turns"].append(_run_turn(message, mode, evidence_slot))
        except Exception as exc:
            st.error(f"That turn could not be completed: {type(exc).__name__}: {exc}")

if not message:
    last_turn = st.session_state["turns"][-1] if st.session_state["turns"] else None
    with evidence_slot.container():
        components.evidence_panel(
            last_turn["evidence"] if last_turn else None,
            last_turn["cited"] if last_turn else [],
            EVIDENCE_PLACEHOLDER,
        )
