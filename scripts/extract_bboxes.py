"""Extract normalized visual-segment bounding boxes from MinerU content lists."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
from typing import Any, Sequence

from scripts.corpus import Document, corpus_for_document, get_document, load_registry
from scripts.parse import (
    FIGURE_TYPES,
    _read_content_list,
    _write_json,
    find_content_list,
)


SEGMENT_VISUAL_TYPES = {"figure", "table"}
_BATCH_DIRECTORY = re.compile(r"^pages_(\d+)_(\d+)$")


class BoundingBoxError(RuntimeError):
    """Raised when parsed inputs cannot produce a trustworthy bbox map."""


def _parse_metadata(document_dir: Path) -> dict[str, Any]:
    metadata_path = document_dir / "parse_metadata.json"
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BoundingBoxError(f"Could not read {metadata_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise BoundingBoxError(f"Expected an object in {metadata_path}.")
    return payload


def _batch_page_offset(batch_dir: Path) -> int:
    match = _BATCH_DIRECTORY.fullmatch(batch_dir.name)
    if match is None:
        raise BoundingBoxError(
            f"MinerU batch directory has an unexpected name: {batch_dir}"
        )
    return int(match.group(1)) - 1


def _contains_content_list(batch_dir: Path) -> bool:
    return any(
        path.is_file() and not path.name.endswith("_content_list_v2.json")
        for path in batch_dir.rglob("*_content_list.json")
    )


def _content_list_sources(
    document_dir: Path,
    doc_name: str,
) -> list[tuple[Path, int]]:
    """Discover content lists in the same order used by parse.py."""
    mineru_dir = document_dir / "mineru"
    metadata = _parse_metadata(document_dir)
    backend = metadata.get("backend")
    batch_roots = sorted(
        path for path in mineru_dir.glob("page_batches_*") if path.is_dir()
    )

    if isinstance(backend, str) and backend.strip():
        selected_batch_root = mineru_dir / f"page_batches_{backend}"
        if selected_batch_root.is_dir():
            batch_roots = [selected_batch_root]

    if batch_roots:
        if len(batch_roots) != 1:
            names = ", ".join(path.name for path in batch_roots)
            raise BoundingBoxError(
                f"Multiple MinerU batch roots found for {doc_name}: {names}"
            )
        batch_dirs = sorted(
            (
                path
                for path in batch_roots[0].glob("pages_*")
                if (
                    path.is_dir()
                    and _BATCH_DIRECTORY.fullmatch(path.name)
                    and _contains_content_list(path)
                )
            ),
            key=lambda path: _batch_page_offset(path),
        )
        if not batch_dirs:
            raise BoundingBoxError(
                f"No page batch directories found beneath {batch_roots[0]}."
            )
        return [
            (find_content_list(batch_dir, doc_name), _batch_page_offset(batch_dir))
            for batch_dir in batch_dirs
        ]

    return [(find_content_list(mineru_dir, doc_name), 0)]


def _normalized_bbox(raw_bbox: Any, context: str) -> list[float]:
    if (
        not isinstance(raw_bbox, list)
        or len(raw_bbox) != 4
        or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in raw_bbox
        )
    ):
        raise BoundingBoxError(f"Visual item {context} has an invalid bbox: {raw_bbox!r}")

    values = [max(0.0, min(1.0, float(value) / 1000.0)) for value in raw_bbox]
    x0, x1 = sorted((values[0], values[2]))
    y0, y1 = sorted((values[1], values[3]))
    if x0 >= x1 or y0 >= y1:
        raise BoundingBoxError(f"Visual item {context} has a degenerate bbox: {raw_bbox!r}")
    return [x0, y0, x1, y1]


def _visual_segments(document_dir: Path) -> dict[str, dict[str, Any]]:
    segments_path = document_dir / "segments.json"
    try:
        payload = json.loads(segments_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BoundingBoxError(f"Could not read {segments_path}: {exc}") from exc
    if not isinstance(payload, list):
        raise BoundingBoxError(f"Expected a segment list in {segments_path}.")

    visual_segments: dict[str, dict[str, Any]] = {}
    for segment in payload:
        if not isinstance(segment, dict) or segment.get("type") not in SEGMENT_VISUAL_TYPES:
            continue
        segment_id = segment.get("segment_id")
        page = segment.get("page")
        if (
            not isinstance(segment_id, str)
            or not segment_id.strip()
            or not isinstance(page, int)
            or isinstance(page, bool)
            or page < 1
        ):
            raise BoundingBoxError(
                f"Invalid visual segment in {segments_path}: {segment!r}"
            )
        if segment_id in visual_segments:
            raise BoundingBoxError(f"Duplicate visual segment ID in {segments_path}: {segment_id}")
        visual_segments[segment_id] = segment
    return visual_segments


def _validate_bboxes(
    bboxes: dict[str, dict[str, Any]],
    visual_segments: dict[str, dict[str, Any]],
    segments_path: Path,
) -> None:
    unknown_ids = sorted(set(bboxes) - set(visual_segments))
    if unknown_ids:
        raise BoundingBoxError(
            f"Bbox IDs not present as figure/table segments in {segments_path}: "
            + ", ".join(unknown_ids)
        )

    page_mismatches = [
        segment_id
        for segment_id, bbox_payload in bboxes.items()
        if bbox_payload.get("page") != visual_segments[segment_id].get("page")
    ]
    if page_mismatches:
        raise BoundingBoxError(
            f"Bbox page mismatches in {segments_path}: "
            + ", ".join(sorted(page_mismatches))
        )

    missing_ids = sorted(set(visual_segments) - set(bboxes))
    if missing_ids:
        raise BoundingBoxError(
            f"Missing bboxes for {len(missing_ids)} figure/table segments in "
            f"{segments_path}: "
            + ", ".join(missing_ids[:10])
            + (" ..." if len(missing_ids) > 10 else "")
        )


def extract_document(document: Document) -> tuple[int, int, Path]:
    """Write one document's bbox map and return matched, missed, and output path."""
    corpus = corpus_for_document(document.doc_id)
    return extract_document_directory(document.doc_id, corpus.parsed_dir / document.doc_id)


def extract_document_directory(doc_id: str, document_dir: Path) -> tuple[int, int, Path]:
    """Build bboxes before an ingested document is published in the registry."""
    segments_path = document_dir / "segments.json"
    visual_segments = _visual_segments(document_dir)
    sources = _content_list_sources(document_dir, doc_id)
    type_counts: Counter[str] = Counter()
    bboxes: dict[str, dict[str, Any]] = {}

    for content_list_path, page_offset in sources:
        for item in _read_content_list(content_list_path):
            item_type = str(item.get("type", ""))
            if item_type not in FIGURE_TYPES and item_type != "table":
                continue

            normalized_type = "figure" if item_type in FIGURE_TYPES else "table"
            type_counts[normalized_type] += 1
            page_idx = item.get("page_idx")
            if not isinstance(page_idx, int) or isinstance(page_idx, bool) or page_idx < 0:
                raise BoundingBoxError(
                    f"Visual item in {content_list_path} has invalid page_idx: {page_idx!r}"
                )
            page_number = page_offset + page_idx + 1
            segment_id = (
                f"{doc_id}-p{page_number:04d}-{normalized_type}-"
                f"{type_counts[normalized_type]:05d}"
            )
            if segment_id in bboxes:
                raise BoundingBoxError(f"Duplicate emitted bbox ID: {segment_id}")
            bboxes[segment_id] = {
                "page": page_number,
                "bbox": _normalized_bbox(
                    item.get("bbox"),
                    f"{segment_id} in {content_list_path}",
                ),
            }

    _validate_bboxes(bboxes, visual_segments, segments_path)
    output_path = document_dir / "bboxes.json"
    _write_json(output_path, bboxes)
    missed = len(visual_segments) - len(bboxes)
    return len(bboxes), missed, output_path


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract MinerU figure/table bboxes from content_list.json."
    )
    parser.add_argument(
        "--doc",
        help="only process this registered document ID (default: every document)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
        if args.doc is not None:
            documents = [get_document(args.doc)]
        else:
            documents = [
                document
                for corpus in load_registry()
                for document in corpus.documents
            ]

        total_matched = 0
        total_missed = 0
        for document in documents:
            matched, missed, output_path = extract_document(document)
            total_matched += matched
            total_missed += missed
            print(
                f"{document.doc_id}: {matched} matched, {missed} missed -> "
                f"{output_path}"
            )
    except (BoundingBoxError, KeyError, OSError, ValueError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    print(f"Total: {total_matched} matched, {total_missed} missed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
