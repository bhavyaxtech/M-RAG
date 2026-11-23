"""Read-only progress report for the STM32 collection."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
from typing import Any


BATCH_RE = re.compile(r"^pages_(\d+)_(\d+)$")


def _read_json(path: Path) -> tuple[Any | None, str | None]:
    try:
        # Close the file before parsing: a Windows reader handle can otherwise
        # prevent the caption worker from atomically replacing its checkpoint.
        return json.loads(path.read_text(encoding="utf-8")), None
    except (FileNotFoundError, PermissionError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f"could not read {path}: {exc.__class__.__name__}"


def _valid_embedding(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(
            isinstance(item, (int, float))
            and not isinstance(item, bool)
            and math.isfinite(item)
            for item in value
        )
    )


def _batch_pages(batch: Path, start: int, end: int) -> set[int] | None:
    try:
        content_files = sorted(batch.rglob("*_content_list.json"))
    except OSError:
        return None
    if not content_files:
        return set()
    if len(content_files) != 1:
        return None
    path = content_files[0]
    payload, error = _read_json(path)
    if error or not isinstance(payload, list):
        return None
    expected_indices = list(range(end - start + 1))
    pages = set()
    for item in payload:
        page_index = item.get("page_idx") if isinstance(item, dict) else None
        if (
            not isinstance(page_index, int)
            or isinstance(page_index, bool)
            or page_index not in expected_indices
        ):
            return None
        pages.add(start + page_index)
    expected = set(range(start, end + 1))
    if pages == expected:
        return pages
    # Blank pages have no content items. Only the matching MinerU per-page
    # output can prove their completion; never guess local/global offsets.
    middle_path = path.with_name(path.name.removesuffix("_content_list.json") + "_middle.json")
    middle, error = _read_json(middle_path)
    if error:
        return pages if not middle_path.exists() else None
    pdf_info = middle.get("pdf_info") if isinstance(middle, dict) else None
    if isinstance(pdf_info, list) and all(isinstance(page, dict) for page in pdf_info):
        indices = [page.get("page_idx") for page in pdf_info]
        if all(isinstance(index, int) and not isinstance(index, bool) for index in indices) and indices == expected_indices:
            return expected
    return pages


def _partial_pages(document_dir: Path) -> tuple[int, bool]:
    """Return contiguous pages from partial batches and whether a read was uncertain."""
    page_numbers: set[int] = set()
    uncertain = False
    try:
        pipelines = document_dir.rglob("page_batches_pipeline")
        for pipeline in pipelines:
            if not pipeline.is_dir():
                continue
            for batch in pipeline.iterdir():
                if not batch.is_dir():
                    continue
                match = BATCH_RE.match(batch.name)
                if not match:
                    continue
                start, end = (int(match.group(1)), int(match.group(2)))
                pages = _batch_pages(batch, start, end)
                if pages is None:
                    uncertain = True
                elif len(pages) == end - start + 1:
                    page_numbers.update(pages)
    except OSError:
        uncertain = True
    count = 0
    while count + 1 in page_numbers:
        count += 1
    return count, uncertain


def _caption_count(document_dir: Path, segments_path: Path) -> tuple[int, int, bool]:
    segments, error = _read_json(segments_path)
    if error or not isinstance(segments, list):
        return 0, 0, True
    visual_ids = {
        segment.get("segment_id")
        for segment in segments
        if isinstance(segment, dict)
        and segment.get("type") in {"figure", "table"}
        and segment.get("segment_id")
    }
    cache_path = document_dir / "caption_cache.json"
    cache, cache_error = _read_json(cache_path)
    if cache_error or not isinstance(cache, dict):
        try:
            missing_cache_is_normal = cache_error and not cache_path.exists()
        except OSError:
            missing_cache_is_normal = False
        return 0, len(visual_ids), bool(cache_error) and not missing_cache_is_normal
    cached = 0
    for segment_id in visual_ids:
        entry = cache.get(segment_id)
        if isinstance(entry, dict):
            variants = entry.get("generated_captions", entry)
            if isinstance(variants, dict) and isinstance(variants.get("luna"), str) and variants["luna"].strip():
                cached += 1
    return cached, len(visual_ids), False


def _embedding_cache_count(path: Path) -> tuple[int | None, str | None]:
    count = 0
    seen: set[str] = set()
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    return count, f"could not read {path}: incomplete or invalid JSON on line {line_number}"
                key = row.get("cache_key") if isinstance(row, dict) else None
                if not isinstance(key, str) or not key:
                    continue
                if key not in seen and _valid_embedding(row.get("embedding")):
                    seen.add(key)
                    count += 1
    except FileNotFoundError:
        return 0, None
    except (PermissionError, OSError, UnicodeError) as exc:
        return None, f"could not read {path}: {exc.__class__.__name__}"
    return count, None


def collect_status(root: Path) -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc).isoformat()
    raw_dir = root / "data" / "raw" / "stm32"
    parsed_dir = root / "data" / "parsed" / "stm32"
    index_dir = root / "index" / "stm32"
    uncertainties: list[str] = []

    manifest, error = _read_json(raw_dir / "manifest.json")
    if error or not isinstance(manifest, dict) or not isinstance(manifest.get("documents"), list):
        return {
            "checked_at": checked_at,
            "status": "uncertain",
            "uncertainties": [error or "manifest has no documents list"],
        }
    documents = [document for document in manifest["documents"] if isinstance(document, dict) and document.get("doc_id")]
    finalized: list[dict[str, Any]] = []
    partial: list[dict[str, Any]] = []
    unfinished: list[dict[str, Any]] = []
    for document in documents:
        doc_id = document["doc_id"]
        document_dir = parsed_dir / doc_id
        segments_path = document_dir / "segments.json"
        try:
            finalized_exists = segments_path.is_file()
        except OSError:
            finalized_exists = False
            uncertainties.append(f"parse artifacts changed while reading: {doc_id}")
        if finalized_exists:
            finalized.append(document)
            continue
        pages, uncertain = _partial_pages(document_dir)
        if uncertain:
            uncertainties.append(f"partial parse changed while reading: {doc_id}")
        progress = {"doc_id": doc_id, "title": document.get("title", doc_id), "pages": pages, "total_pages": document.get("pages")}
        unfinished.append(progress)
        try:
            has_directory = document_dir.exists()
        except OSError:
            has_directory = False
            uncertainties.append(f"parse directory changed while reading: {doc_id}")
        if pages or has_directory:
            partial.append(progress)

    finalized_visuals = finalized_cached = 0
    for document in finalized:
        cached, total, uncertain = _caption_count(parsed_dir / document["doc_id"], parsed_dir / document["doc_id"] / "segments.json")
        finalized_cached += cached
        finalized_visuals += total
        if uncertain:
            uncertainties.append(f"caption cache changed or is unavailable: {document['doc_id']}")

    progressive_documents = []
    for document in documents:
        progressive_dir = parsed_dir / document["doc_id"] / "progressive"
        segments_path = progressive_dir / "segments.json"
        if not segments_path.is_file():
            continue
        cached, total, uncertain = _caption_count(progressive_dir, segments_path)
        progressive_documents.append({
            "doc_id": document["doc_id"],
            "cached_visual_captions": cached,
            "visual_segments": total,
        })
        if uncertain:
            uncertainties.append(f"progressive caption snapshot changed while reading: {document['doc_id']}")

    embedding_entries, error = _embedding_cache_count(index_dir / "embedding_cache.jsonl")
    if error:
        uncertainties.append(error)
    index_files = [index_dir / "mrag_index.faiss", index_dir / "text_only_index.faiss", index_dir / "metadata.jsonl"]
    indexes_present = all(path.is_file() for path in index_files)

    registry_path = root / "corpora.json"
    registry, error = _read_json(registry_path)
    if error:
        try:
            registry_present = registry_path.exists()
        except OSError:
            registry_present = True
        if registry_present:
            uncertainties.append(error)
    registry_corpora = registry.get("corpora", []) if isinstance(registry, dict) else []
    published = isinstance(registry_corpora, list) and any(
        isinstance(corpus, dict) and corpus.get("corpus_id") == "stm32"
        for corpus in registry_corpora
    )

    total_pages = sum(document.get("pages", 0) for document in documents if isinstance(document.get("pages"), int))
    finalized_pages = sum(document.get("pages", 0) for document in finalized if isinstance(document.get("pages"), int))
    largest_remaining = max(unfinished, key=lambda item: item.get("total_pages") or 0, default=None)
    if largest_remaining:
        largest_remaining = dict(largest_remaining)
        largest_remaining["remaining_pages"] = max(
            0, (largest_remaining.get("total_pages") or 0) - (largest_remaining.get("pages") or 0)
        )
    return {
        "checked_at": checked_at,
        "status": "published" if published else ("uncertain" if uncertainties else "in_progress"),
        "target_documents": len(documents),
        "finalized_documents": len(finalized),
        "finalized_pages": finalized_pages,
        "total_pages": total_pages,
        "partial_documents": partial,
        "unfinished_documents": unfinished,
        "largest_remaining_pdf": largest_remaining,
        "cached_visual_captions": finalized_cached,
        "finalized_visual_segments": finalized_visuals,
        "progressive_documents": progressive_documents,
        "embedding_cache_entries": embedding_entries,
        "indexes_present": indexes_present,
        "indexed": indexes_present,
        "published": published,
        "uncertainties": uncertainties,
    }


def _human_summary(report: dict[str, Any]) -> str:
    if "finalized_documents" not in report:
        uncertainty = "; ".join(report.get("uncertainties", [])) or "required status input is unavailable"
        return f"Checked at: {report.get('checked_at', 'unknown')}.\nStatus uncertain: {uncertainty}"
    lines = [
        f"Checked at: {report.get('checked_at', 'unknown')}.",
        f"STM32 collection: {report['finalized_documents']}/{report['target_documents']} documents finalized.",
        f"Pages: {report['finalized_pages']}/{report['total_pages']} finalized (document and page progress are reported separately).",
        f"Visual captions: {report['cached_visual_captions']}/{report['finalized_visual_segments']} cached for finalized documents.",
        f"Embeddings: {report['embedding_cache_entries'] if report['embedding_cache_entries'] is not None else 'uncertain'} valid cache entries; indexed={'yes' if report['indexed'] else 'no'}.",
        f"Published: {'yes' if report['published'] else 'no'}.",
    ]
    partial = report.get("partial_documents", [])
    if partial:
        lines.append("Partial progress: " + ", ".join(f"{item['doc_id']} {item['pages']}/{item['total_pages']} pages" for item in partial))
    progressive = report.get("progressive_documents", [])
    if progressive:
        lines.append("Progressive caption snapshots (may overlap finalized counts): " + ", ".join(
            f"{item['doc_id']} {item['cached_visual_captions']}/{item['visual_segments']} captions"
            for item in progressive
        ))
    largest = report.get("largest_remaining_pdf")
    if largest:
        lines.append(
            f"Largest remaining PDF: {largest['doc_id']} ({largest['remaining_pages']} pages remain of {largest['total_pages']})."
        )
    if report.get("uncertainties"):
        lines.append("Uncertainty: " + "; ".join(report["uncertainties"]))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit machine-readable JSON")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="project root")
    args = parser.parse_args(argv)
    report = collect_status(args.root.resolve())
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_human_summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
