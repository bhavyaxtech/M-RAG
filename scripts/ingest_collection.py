"""Resumable STM32 ingestion. Dry-run by default; paid stages require --execute.

All stages retain the original MinerU -> caption -> shared-embedding code path.
Only a completely built collection is registered in the demo.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import faiss

from scripts.caption import CAPTION_WORKER_CHOICES, caption_segments_file
from scripts.collect_stm32 import CATALOG, RAW, ROOT, inspect_pdf
from scripts.embed_and_index import build_indexes
from scripts.extract_bboxes import extract_document_directory
from scripts.parse import parse_pdf
from scripts.usage_budget import api_budget
from scripts.file_io import replace_with_retry


PARSED = ROOT / "data" / "parsed" / "stm32"
INDEX = ROOT / "index" / "stm32"
LEDGER = ROOT / "output" / "stm32" / "azure_usage.json"


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    replace_with_retry(temporary, path)


def validated_documents() -> list[dict]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    manifest_path = RAW / "manifest.json"
    if not manifest_path.exists():
        raise ValueError("Run python -m scripts.collect_stm32 first")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results = {document["doc_id"]: document for document in manifest["documents"]}
    documents = []
    for entry in catalog["documents"]:
        document = results.get(entry["doc_id"], {})
        if document.get("status") != "downloaded":
            continue
        path = RAW / f"{entry['doc_id']}.pdf"
        inspected = inspect_pdf(path, entry["document_id"])
        if inspected["sha256"] != document["sha256"]:
            raise ValueError(f"Source changed: {path}; recollect deliberately before parsing")
        documents.append(document)
    return documents


def preflight(documents: list[dict]) -> dict:
    completed = []
    partial_pages = 0
    visual_segments = 0
    cached_captions = 0
    for document in documents:
        directory = PARSED / document["doc_id"]
        segments_path = directory / "segments.json"
        if not segments_path.exists():
            for batch in (directory / "_mineru_work" / "page_batches_pipeline").glob("pages_*"):
                if any(batch.rglob("*_content_list.json")):
                    _, start, end = batch.name.split("_")
                    partial_pages += int(end) - int(start) + 1
            continue
        completed.append(document)
        segments = json.loads(segments_path.read_text(encoding="utf-8"))
        cache_path = directory / "caption_cache.json"
        cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
        for segment in segments:
            if segment["type"] in {"figure", "table"}:
                visual_segments += 1
                cached_captions += bool(cache.get(segment["segment_id"], {}).get("luna"))
    published = any(
        corpus["corpus_id"] == "stm32"
        for corpus in json.loads((ROOT / "corpora.json").read_text(encoding="utf-8"))["corpora"]
    )
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "downloaded_documents": len(documents),
        "target_documents": len(json.loads(CATALOG.read_text())["documents"]),
        "pages": sum(document["pages"] for document in documents),
        "parsed_documents": len(completed),
        "parsed_pages": sum(document["pages"] for document in completed),
        "additional_completed_batch_pages": partial_pages,
        "visual_segments_in_completed_documents": visual_segments,
        "cached_captions_in_completed_documents": cached_captions,
        "published": published,
        "paid_calls_started_by_preflight": 0,
        "status": "published" if published else (
            "not_ready" if len(documents) < 20 else (
                "parsed_ready_for_build" if len(completed) == len(documents) else "parsing_incomplete"
            )
        ),
    }


def parse_document(document: dict, pages_per_batch: int) -> None:
    directory = PARSED / document["doc_id"]
    fingerprint_path = directory / "source_sha256.txt"
    if fingerprint_path.exists() and fingerprint_path.read_text().strip() != document["sha256"]:
        raise ValueError(f"Source PDF changed for {document['doc_id']}; refusing stale cache reuse")
    if (directory / "segments.json").exists():
        if not fingerprint_path.exists():
            raise ValueError(f"Existing parse has no source fingerprint: {directory}")
        print(f"Reusing parse: {document['doc_id']}", flush=True)
        return
    directory.mkdir(parents=True, exist_ok=True)
    fingerprint_path.write_text(document["sha256"] + "\n")
    parse_pdf(
        RAW / f"{document['doc_id']}.pdf", output_root=PARSED, raw_root=RAW,
        try_vlm=False, pages_per_batch=pages_per_batch, timeout=1800,
    )


def register_collection(documents: list[dict]) -> None:
    """Publish only complete artifacts, preserving existing corpus entries."""
    if len(documents) < 20:
        raise ValueError("Refusing to publish an incomplete 20-document collection")
    expected_docs = {document["doc_id"] for document in documents}
    metadata = [
        json.loads(line)
        for line in (INDEX / "metadata.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    text_rows = [row for row in metadata if row["type"] == "text"]
    if {row["doc"] for row in metadata} != expected_docs or {row["doc"] for row in text_rows} != expected_docs:
        raise ValueError("Built indexes do not cover every selected document in both retrieval modes")
    mrag_index = faiss.read_index(str(INDEX / "mrag_index.faiss"))
    text_index = faiss.read_index(str(INDEX / "text_only_index.faiss"))
    if (
        mrag_index.ntotal != len(metadata)
        or text_index.ntotal != len(text_rows)
        or mrag_index.d != text_index.d
        or [row["vector_id"] for row in metadata] != list(range(len(metadata)))
        or metadata[:len(text_rows)] != text_rows
    ):
        raise ValueError("Built FAISS indexes and source metadata do not align")
    registry_path = ROOT / "corpora.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if any(corpus["corpus_id"] == "stm32" for corpus in registry["corpora"]):
        raise ValueError("STM32 is already registered; do not overwrite a live index")
    manifest = {"documents": documents}
    save_json(INDEX / "document_manifest.json", manifest)
    registry["corpora"].append({
        "corpus_id": "stm32", "title": "STM32F103 connected technical library",
        "blurb": "Manuals, datasheet, errata, and application notes. Cross-document pilot; not yet evaluated.",
        "evaluated": False, "index_dir": "index/stm32", "parsed_dir": "data/parsed/stm32",
        "raw_dir": "data/raw/stm32",
        "documents": [{"doc_id": d["doc_id"], "title": f"{d['document_id']} (rev {d.get('revision', '?')}) — {d['title']}"} for d in documents],
    })
    save_json(registry_path, registry)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--stage", choices=["parse", "pilot", "caption", "build", "all"], default="parse")
    parser.add_argument("--pages-per-batch", type=int, default=10)
    parser.add_argument(
        "--caption-workers",
        type=int,
        choices=CAPTION_WORKER_CHOICES,
        default=1,
        help="parallel caption requests, from 1 through 4 (default: 1)",
    )
    args = parser.parse_args()
    if args.pages_per_batch < 1:
        parser.error("--pages-per-batch must be positive")
    documents = validated_documents()
    report = preflight(documents)
    print(json.dumps(report, indent=2), flush=True)
    save_json(ROOT / "output" / "stm32" / "preflight.json", report)
    if not args.execute:
        return 0
    if len(documents) < report["target_documents"]:
        raise ValueError("Collection incomplete. No paid calls started; resolve source downloads first.")
    if args.stage in {"parse", "all"}:
        for document in sorted(documents, key=lambda d: d["pages"]):
            print(f"Parsing {document['document_id']} ({document['pages']} pages)", flush=True)
            parse_document(document, args.pages_per_batch)
        if args.stage == "parse":
            return 0
    segment_files = [PARSED / d["doc_id"] / "segments.json" for d in documents]
    if args.stage in {"build", "all"} and not all(path.exists() for path in segment_files):
        raise ValueError("Parse all documents first. No paid calls started.")
    segment_files = [path for path in segment_files if path.exists()]
    if not segment_files:
        raise ValueError("No completed parses are available for a caption pilot")
    for document in documents:
        if (PARSED / document["doc_id"] / "segments.json").exists():
            parse_document(document, args.pages_per_batch)  # Verify completed fingerprints only.
    registry = json.loads((ROOT / "corpora.json").read_text())
    if args.stage in {"caption", "build", "all"} and any(c["corpus_id"] == "stm32" for c in registry["corpora"]):
        raise ValueError("STM32 is already published; refusing to rewrite a live collection")
    with api_budget(LEDGER, 30) as budget:
        if args.stage == "pilot":
            # Three existing crops, not synthetic images or an entire batch.
            remaining = 3
            for path in segment_files:
                visuals = [s for s in json.loads(path.read_text(encoding="utf-8")) if s["type"] in {"figure", "table"}]
                ids = {s["segment_id"] for s in visuals[:remaining]}
                if ids:
                    caption_segments_file(
                        path,
                        segment_ids=ids,
                        workers=args.caption_workers,
                    )
                    remaining -= len(ids)
                if remaining == 0:
                    break
            save_json(ROOT / "output" / "stm32" / "pilot.json", {
                "captions_selected": 3 - remaining, "estimated_spent_usd": budget.spent,
                "status": "captions_need_quality_review_before_build",
            })
        else:
            pilot = ROOT / "output" / "stm32" / "pilot.json"
            if not pilot.exists():
                raise ValueError("Run and inspect the three-caption pilot before --stage build")
            for path in segment_files:
                print(f"Captioning {path.parent.name}", flush=True)
                generated, cached, _ = caption_segments_file(
                    path,
                    workers=args.caption_workers,
                )
                print(f"  {generated} generated, {cached} cached", flush=True)
            if args.stage != "caption":
                for path in segment_files:
                    extract_document_directory(path.parent.name, path.parent)
                build_indexes(segment_files, output_dir=INDEX)
                register_collection(documents)
        print(f"Persistent Azure estimate including unknown-call reservations: ${budget.spent:.4f}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Stopped safely: {exc}", file=sys.stderr)
        raise SystemExit(1)
