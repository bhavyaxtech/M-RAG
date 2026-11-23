"""Exercise real three-document answers against the 18-document prepared subset."""

from datetime import datetime, timezone
import json
import time

from scripts.agent import answer_stream, cited_labels, gather_evidence, route_question
from scripts.embed_and_index import collect_records, embed_records, write_indexes
from scripts.ingest_collection import INDEX, LEDGER, PARSED, ROOT, save_json
from scripts.usage_budget import api_budget


question = (
    "How should an STM32F103 application separate persistent settings stored with "
    "AN2594 EEPROM emulation from a firmware updater based on AN2557, and what "
    "Flash programming constraints does PM0075 add? Cite all three sources and "
    "distinguish medium-density devices from other variants."
)
expected_docs = {"stm32-an2594", "stm32-an2557", "stm32-pm0075"}
paths = []
for path in sorted(PARSED.glob("*/segments.json")):
    segments = json.loads(path.read_text(encoding="utf-8"))
    if all(segment["type"] == "text" or segment.get("caption_model") for segment in segments):
        paths.append(path)
ready_ids = {path.parent.name for path in paths}
documents = [
    document for document in json.loads((ROOT / "data/raw/stm32/manifest.json").read_text(encoding="utf-8"))["documents"]
    if document["doc_id"] in ready_ids
]
preview = ROOT / "output/stm32/preview-index"
report = {
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "indexed_documents": len(documents),
    "indexed_pages": sum(document["pages"] for document in documents),
    "status": "partial_collection_smoke_not_full_evaluation",
    "question": question,
    "results": [],
}
with api_budget(LEDGER, 30):
    records, text_count = collect_records(paths)
    embeddings, generated, cached = embed_records(records, INDEX / "embedding_cache.jsonl")
    assert generated == 0, "Prepared subset should already be cached"
    write_indexes(records, embeddings, text_count, preview)
    save_json(preview / "document_manifest.json", {"documents": documents})
    titles = [f"{document['document_id']} {document['title']}" for document in documents]
    decision = route_question(question, available_document_titles=titles)
    assert decision.route == "datasheet", decision
    for mode in ("mrag", "text_only"):
        started = time.perf_counter()
        evidence = gather_evidence(decision.search_query, mode, k=8, index_dir=preview, collection=True, reference_query=question)
        retrieval_seconds = time.perf_counter() - started
        answer = "".join(answer_stream(question, decision, evidence, mode, available_document_titles=titles))
        labels = set(cited_labels(answer, evidence.segments))
        cited_docs = {segment["doc"] for segment in evidence.segments if segment["label"] in labels}
        result = {
            "mode": mode, "answer": answer, "answer_score": None,
            "retrieval_seconds": round(retrieval_seconds, 3),
            "total_seconds_excluding_router": round(time.perf_counter() - started, 3),
            "all_requested_documents_retrieved": expected_docs <= {segment["doc"] for segment in evidence.segments},
            "all_requested_documents_cited": expected_docs <= cited_docs,
            "cited_documents": sorted(cited_docs),
            "retrieved": evidence.segments,
        }
        report["results"].append(result)
        save_json(ROOT / "output/stm32/preview_smoke.json", report)
        print(json.dumps({key: value for key, value in result.items() if key not in {"answer", "retrieved"}}, indent=2), flush=True)
