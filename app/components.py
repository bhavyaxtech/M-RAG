"""Presentation helpers for the M-RAG demo.

Everything here turns agent output into markup. No module in this file talks
to Azure or FAISS, so the pipeline can be exercised without Streamlit and the
UI can be restyled without touching retrieval.
"""

from __future__ import annotations

from html import escape
from pathlib import Path
import re
from typing import Any, Sequence

import streamlit as st

from scripts.agent import CITATION_PATTERN, RELEVANCE_FLOOR, Evidence, RouterDecision


PROJECT_ROOT = Path(__file__).resolve().parents[1]

BADGE_TEXT = {
    "grounded": "From datasheets",
    "general": "General knowledge",
    "uncovered": "Not in these datasheets",
    "unsupported": "Retrieved, uncited",
}

STAGE_LABELS = {
    "route": ("Reading the question", "Read the question"),
    "retrieve": ("Searching the datasheets", "Searched the datasheets"),
    "read": ("Reading the evidence", "Read the evidence"),
    "answer": ("Writing the answer", "Answered"),
}


def _esc(value: object) -> str:
    return escape(str(value), quote=True)


# MinerU keeps inline markup such as <sup> in extracted prose. It belongs in
# the indexed text, but rendering it verbatim in a card is noise.
_INLINE_MARKUP = re.compile(r"</?(?:sup|sub|b|i|em|strong|br|span|u)\b[^>]*>")


def _snippet(text: str, limit: int = 460) -> str:
    normalized = " ".join(_INLINE_MARKUP.sub("", text).split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _image_path(image_path: str) -> Path:
    path = Path(image_path).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def header() -> None:
    st.markdown(
        """
        <div class="mrag-header">
            <h1 class="mrag-wordmark">M-RAG</h1>
            <p class="mrag-sub">
                A multimodal retrieval agent over five hardware datasheets. It decides
                when to search, answers from the pages it retrieves, and shows the
                figures and tables it used.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def rule() -> None:
    st.markdown('<div class="mrag-rule"></div>', unsafe_allow_html=True)


def section_label(text: str, count: str | None = None) -> None:
    suffix = f'<span class="mrag-count">{_esc(count)}</span>' if count else ""
    st.markdown(
        f'<div class="mrag-section-label">{_esc(text)}{suffix}</div>',
        unsafe_allow_html=True,
    )


def stages_html(completed: Sequence[str], active: str | None) -> str:
    """Render the staged progress list. Completed stages keep their tick."""
    rows = []
    for stage in completed:
        _, done_text = STAGE_LABELS[stage]
        rows.append(
            f'<div class="mrag-stage done"><span class="mrag-tick">&#10003;</span>'
            f"<span>{_esc(done_text)}</span></div>"
        )
    if active is not None:
        active_text, _ = STAGE_LABELS[active]
        rows.append(
            '<div class="mrag-stage active">'
            f'<span class="mrag-stage-text">{_esc(active_text)}</span>'
            '<span class="mrag-dots"><i></i><i></i><i></i></span></div>'
        )
    return f'<div class="mrag-status">{"".join(rows)}</div>'


def trace_html(decision: RouterDecision, evidence: Evidence, mode: str) -> str:
    """One collapsed line summarising the work behind the finished answer."""
    parts = [
        "searched the index" if decision.route == "datasheet" else "answered directly",
    ]
    if decision.route == "datasheet":
        parts.append(f"{len(evidence.segments)} segments retrieved")
        if evidence.visual_count and mode == "mrag":
            parts.append(f"{evidence.visual_count} visual crops read")
    return f'<div class="mrag-trace">{_esc(" · ".join(parts))}</div>'


def badge_html(kind: str) -> str:
    text = BADGE_TEXT.get(kind, kind)
    return f'<div class="mrag-badge {_esc(kind)}">{_esc(text)}</div>'


def answer_markdown(text: str, valid_labels: Sequence[str]) -> str:
    """Turn valid [S1] markers into pills and drop markers with no segment."""
    allowed = set(valid_labels)

    def replace(match: "Any") -> str:
        label = f"S{int(match.group(1))}"
        if label not in allowed:
            return ""
        return f'<span class="mrag-cite">{label}</span>'

    return CITATION_PATTERN.sub(replace, text)


def evidence_card(segment: dict[str, Any], cited: bool, position: int) -> None:
    segment_type = str(segment.get("type", "text")).lower()
    type_class = segment_type if segment_type in {"table", "figure"} else "text"
    state = "cited" if cited else "uncited"
    score = segment.get("score")
    score_text = f"{float(score):.3f}" if isinstance(score, (int, float)) else "—"

    with st.container(border=True):
        st.markdown(
            f"""
            <div class="mrag-card {state} d{min(position, 5)}">
                <div class="mrag-card-meta">
                    <span class="mrag-label">{_esc(segment.get("label", "S?"))}</span>
                    <span class="mrag-type {type_class}">{_esc(type_class)}</span>
                    <span>{_esc(segment.get("doc", "unknown"))}</span>
                    <span>·</span>
                    <span>p{_esc(segment.get("page", "?"))}</span>
                    <span class="mrag-score">{_esc(score_text)}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if type_class in {"figure", "table"}:
            raw_path = segment.get("image_path")
            if isinstance(raw_path, str) and raw_path.strip():
                path = _image_path(raw_path)
                if path.is_file():
                    st.image(str(path), use_container_width=True)
                else:
                    st.error(f"Cropped image not found: {path}")
            else:
                st.error("This visual segment has no cropped image path.")
            return

        st.markdown(
            f'<div class="mrag-snippet">{_esc(_snippet(str(segment.get("text_or_caption", ""))))}</div>',
            unsafe_allow_html=True,
        )


def evidence_panel(
    evidence: Evidence | None,
    cited: Sequence[str],
    empty_message: str,
) -> None:
    """Render every retrieved segment, cited ones highlighted."""
    segments = list(evidence.segments) if evidence else []
    count = f"{len(segments)} shown" if segments else None
    section_label("Evidence", count)

    if not segments:
        st.markdown(
            f'<div class="mrag-empty">{_esc(empty_message)}</div>',
            unsafe_allow_html=True,
        )
        return

    cited_set = set(cited)
    for position, segment in enumerate(segments, start=1):
        evidence_card(segment, str(segment.get("label")) in cited_set, position)


def why_html(
    decision: RouterDecision,
    evidence: Evidence,
    cited: Sequence[str],
    mode: str,
) -> str:
    """The self-justification panel: route, relevance, and what was used."""
    rows: list[tuple[str, str]] = []

    route_text = (
        "datasheet question" if decision.route == "datasheet" else "general conversation"
    )
    if decision.fallback:
        route_text += ", router fell back to searching"
    else:
        route_text += f" (confidence {decision.confidence:.2f})"
    rows.append(("Route", route_text))

    if decision.route == "datasheet":
        if decision.search_query.strip().lower() != "":
            rows.append(("Searched for", decision.search_query))
        verdict = "above" if evidence.grounded else "below"
        rows.append(
            (
                "Relevance",
                f"top match {evidence.top_score:.3f}, {verdict} the "
                f"{RELEVANCE_FLOOR:.2f} floor",
            )
        )

        by_label = {str(segment.get("label")): segment for segment in evidence.segments}
        if cited:
            used = ", ".join(
                f"{label} {by_label[label].get('doc')} p{by_label[label].get('page')} "
                f"{by_label[label].get('type')}"
                for label in cited
                if label in by_label
            )
            rows.append(("Used", used))
        elif evidence.grounded:
            rows.append(("Used", "nothing cited, treat this answer as unsupported"))

        unused = [
            label for label in by_label if label not in set(cited)
        ]
        if unused:
            rows.append(
                ("Retrieved, unused", ", ".join(unused) + ", still listed on the right")
            )
    else:
        rows.append(("Retrieval", "skipped, this was not a datasheet question"))

    rows.append(
        ("Index", "multimodal" if mode == "mrag" else "text-only baseline, no visuals")
    )

    body = "".join(
        f"<dt>{_esc(name)}</dt><dd>{_esc(value)}</dd>" for name, value in rows
    )
    return f'<dl class="mrag-why">{body}</dl>'


def footer_html(
    generation_deployment: str,
    router_deployment: str,
    evidence: Evidence | None,
    cited: Sequence[str],
    used_history: bool,
) -> str:
    parts = [f"{generation_deployment} · routed by {router_deployment}"]
    if evidence and evidence.segments:
        parts.append(f"{len(evidence.segments)} retrieved, {len(cited)} cited")
    if used_history:
        parts.append("earlier turns included in the prompt")
    return f'<div class="mrag-foot">{_esc(" · ".join(parts))}</div>'
