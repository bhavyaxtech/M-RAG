"""Run a real, unscored cross-PDF check against the completed STM32 collection."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import faiss
import numpy as np

from scripts.agent import CITATION_PATTERN, answer_stream, cited_labels, gather_evidence, route_question
from scripts.ingest_collection import INDEX, LEDGER, ROOT, save_json
from scripts.usage_budget import api_budget


QUESTION = (
    "Compare AN2594 EEPROM emulation with AN2557 USART in-application programming: "
    "what does each persist or update, and why aren't they interchangeable? "
    "Cite both documents and distinguish any device-density qualifications."
)
EXPECTED_DOCS = {"stm32-an2594", "stm32-an2557"}


def validate_index(index_dir: Path) -> list[dict]:
    documents = json.loads((index_dir / "document_manifest.json").read_text(encoding="utf-8"))["documents"]
    metadata = [json.loads(line) for line in (index_dir / "metadata.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(documents) != 20 or {row["doc"] for row in metadata} != {doc["doc_id"] for doc in documents}:
        raise ValueError("This smoke test requires all 20 documents to be indexed")
    mrag_index = faiss.read_index(str(index_dir / "mrag_index.faiss"))
    baseline = faiss.read_index(str(index_dir / "text_only_index.faiss"))
    if not np.array_equal(
        mrag_index.reconstruct_n(0, baseline.ntotal), baseline.reconstruct_n(0, baseline.ntotal)
    ):
        raise ValueError("Baseline embeddings differ from the shared multimodal text rows")
    return documents


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="call the configured Azure deployments")
    args = parser.parse_args()
    try:
        documents = validate_index(INDEX)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Collection is not ready for the smoke test: {exc}", file=sys.stderr)
        return 2
    if not args.execute:
        print("All 20 documents indexed; baseline vectors match. No API calls made.")
        return 0

    output = ROOT / "output/stm32/full_collection_smoke.json"
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "indexed_documents": len(documents),
        "indexed_pages": sum(doc["pages"] for doc in documents),
        "question": QUESTION,
        "answer_score": None,
        "evaluation_status": "structural_checks_only_human_answer_review_required",
        "results": [],
    }
    titles = [f"{doc['document_id']} {doc['title']}" for doc in documents]
    with api_budget(LEDGER, 30):
        decision = route_question(QUESTION, available_document_titles=titles)
        if decision.route != "datasheet":
            raise ValueError(f"Cross-document question incorrectly routed as {decision.route}")
        for mode in ("mrag", "text_only"):
            evidence = gather_evidence(
                decision.search_query, mode, k=8, index_dir=INDEX,
                collection=True, reference_query=QUESTION,
            )
            answer = "".join(answer_stream(
                QUESTION, decision, evidence, mode, available_document_titles=titles,
            ))
            labels = set(cited_labels(answer, evidence.segments))
            cited_docs = {hit["doc"] for hit in evidence.segments if hit["label"] in labels}
            unknown_labels = {f"S{number}" for number in CITATION_PATTERN.findall(answer)} - labels
            checks = {
                "requested_documents_retrieved": EXPECTED_DOCS <= {hit["doc"] for hit in evidence.segments},
                "requested_documents_cited": EXPECTED_DOCS <= cited_docs,
                "no_unknown_citation_labels": not unknown_labels,
                "text_only_has_no_visual_evidence": mode != "text_only" or all(hit["type"] == "text" for hit in evidence.segments),
            }
            report["results"].append({
                "mode": mode, "answer": answer, "checks": checks,
                "retrieved": evidence.segments, "cited_documents": sorted(cited_docs),
                "unknown_citation_labels": sorted(unknown_labels), "answer_score": None,
            })
            save_json(output, report)
            print(f"{mode}: {json.dumps(checks)}", flush=True)
    return 0 if all(all(result["checks"].values()) for result in report["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
