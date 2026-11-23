"""Prepare reusable caption and embedding caches from completed MinerU batches.

This worker is deliberately bounded to ``stm32-rm0008``. It never publishes a
collection or writes the parser's canonical ``segments.json``. Dry-run is the
default; ``--execute`` is required before any progressive artifacts or paid
provider calls can be created.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Sequence

import fitz

from scripts.caption import (
    CAPTION_CACHE_FILENAME,
    CAPTION_WORKER_CHOICES,
    caption_segments_file,
)
from scripts.embed_and_index import (
    DEFAULT_CHUNK_TOKENS,
    EMBEDDING_CACHE_FILENAME,
    collect_records,
    embed_records,
)
from scripts.parse import FIGURE_TYPES, TEXT_LIKE_TYPES, normalize_segments
from scripts.usage_budget import api_budget
from scripts.file_io import replace_with_retry


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOC_NAME = "stm32-rm0008"
PDF_PATH = PROJECT_ROOT / "data" / "raw" / "stm32" / f"{DOC_NAME}.pdf"
DOC_DIR = PROJECT_ROOT / "data" / "parsed" / "stm32" / DOC_NAME
FINGERPRINT_PATH = DOC_DIR / "source_sha256.txt"
INDEX_DIR = PROJECT_ROOT / "index" / "stm32"
LEDGER_PATH = PROJECT_ROOT / "output" / "stm32" / "azure_usage.json"
PROGRESSIVE_DIRNAME = "progressive"
PROGRESSIVE_CONTENT_LIST = "completed_content_list.json"
PROGRESSIVE_SEGMENTS = "segments.json"
_BATCH_NAME = re.compile(r"^pages_(\d{4})_(\d{4})$")


class PreparationError(RuntimeError):
    """Raised when progressive preparation cannot safely continue."""


class _BatchRootMoved(RuntimeError):
    """Internal signal that the parser completed its directory handoff."""


@dataclass(frozen=True)
class CompletedBatch:
    """A stable, fully covered MinerU page batch."""

    start_page: int
    end_page: int
    content_list_path: Path
    items: tuple[dict[str, Any], ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_source_fingerprint(pdf_path: Path, fingerprint_path: Path) -> str:
    """Require the source PDF to match the parser's recorded fingerprint."""
    if not pdf_path.is_file():
        raise PreparationError(f"Source PDF not found: {pdf_path}")
    if not fingerprint_path.is_file():
        raise PreparationError(f"Source fingerprint not found: {fingerprint_path}")
    expected = fingerprint_path.read_text(encoding="utf-8").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise PreparationError(f"Invalid source fingerprint: {fingerprint_path}")
    actual = _sha256(pdf_path)
    if actual != expected:
        raise PreparationError(
            f"Source checksum mismatch for {pdf_path}; refusing stale batch/cache reuse."
        )
    return actual


def _read_stable_json(path: Path) -> Any | None:
    try:
        before = path.stat()
        raw = path.read_bytes()
        after = path.stat()
    except OSError:
        return None
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _read_stable_content_list(batch_dir: Path) -> tuple[Path, list[dict[str, Any]]] | None:
    """Read one completed content list without trusting paths inside its JSON."""
    try:
        candidates = sorted(
            path
            for path in batch_dir.rglob("*_content_list.json")
            if not path.name.endswith("_content_list_v2.json")
        )
    except OSError:
        return None
    if not candidates:
        return None
    if len(candidates) != 1:
        raise PreparationError(
            f"Ambiguous MinerU content lists beneath completed batch {batch_dir}."
        )

    path = candidates[0]
    try:
        path.resolve().relative_to(batch_dir.resolve())
    except ValueError:
        return None
    payload = _read_stable_json(path)
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        return None
    return path, payload


def _middle_proves_pages_processed(
    content_list_path: Path,
    expected_local_pages: Sequence[int],
) -> bool:
    """Use MinerU's per-page middle schema to distinguish blanks from partial work."""
    suffix = "_content_list.json"
    if not content_list_path.name.endswith(suffix):
        return False
    middle_path = content_list_path.with_name(
        content_list_path.name[: -len(suffix)] + "_middle.json"
    )
    payload = _read_stable_json(middle_path)
    if not isinstance(payload, dict):
        return False
    pdf_info = payload.get("pdf_info")
    if not isinstance(pdf_info, list) or not all(isinstance(page, dict) for page in pdf_info):
        return False
    page_indices = [page.get("page_idx") for page in pdf_info]
    if not all(isinstance(page_idx, int) and not isinstance(page_idx, bool) for page_idx in page_indices):
        return False
    return page_indices == list(expected_local_pages)


def _batch_roots(doc_dir: Path) -> list[Path]:
    return [
        doc_dir / "_mineru_work" / "page_batches_pipeline",
        doc_dir / "mineru" / "page_batches_pipeline",
    ]


def discover_completed_batches(
    doc_dir: Path,
    pdf_page_count: int,
) -> tuple[list[CompletedBatch], list[str]]:
    """Return the contiguous, fully covered prefix beginning at physical page 1."""
    for _ in range(3):
        batch_root = next((root for root in _batch_roots(doc_dir) if root.is_dir()), None)
        if batch_root is None:
            raise PreparationError(f"No MinerU page-batch directory found beneath {doc_dir}.")
        try:
            return _discover_completed_batches_from_root(batch_root, pdf_page_count)
        except _BatchRootMoved:
            continue
    raise PreparationError("MinerU batch root kept moving while it was being inspected.")


def _discover_completed_batches_from_root(
    batch_root: Path,
    pdf_page_count: int,
) -> tuple[list[CompletedBatch], list[str]]:
    try:
        directories = sorted(
            (path for path in batch_root.iterdir() if path.is_dir()),
            key=lambda path: path.name,
        )
    except OSError as exc:
        raise _BatchRootMoved from exc

    parsed_directories: list[tuple[int, int, Path]] = []
    for directory in directories:
        match = _BATCH_NAME.fullmatch(directory.name)
        if not match:
            continue
        start_page, end_page = (int(value) for value in match.groups())
        if start_page < 1 or end_page < start_page or end_page > pdf_page_count:
            raise PreparationError(f"Invalid MinerU batch range: {directory.name}")
        parsed_directories.append((start_page, end_page, directory))
    parsed_directories.sort(key=lambda value: (value[0], value[1]))

    completed: list[CompletedBatch] = []
    rejected: list[str] = []
    expected_start = 1
    for start_page, end_page, directory in parsed_directories:
        if start_page != expected_start:
            rejected.append(directory.name)
            break
        loaded = _read_stable_content_list(directory)
        if loaded is None:
            if not batch_root.is_dir():
                raise _BatchRootMoved
            rejected.append(directory.name)
            break
        content_list_path, items = loaded
        expected_page_sequence = list(range(end_page - start_page + 1))
        expected_local_pages = set(expected_page_sequence)
        observed_local_pages: set[int] = set()
        valid = True
        for item in items:
            page_idx = item.get("page_idx")
            if (
                not isinstance(page_idx, int)
                or isinstance(page_idx, bool)
                or page_idx not in expected_local_pages
            ):
                valid = False
                break
            observed_local_pages.add(page_idx)
        missing_content_pages = observed_local_pages != expected_local_pages
        middle_proves_completion = not missing_content_pages or _middle_proves_pages_processed(
            content_list_path,
            expected_page_sequence,
        )
        if not valid or not middle_proves_completion:
            if not batch_root.is_dir():
                raise _BatchRootMoved
            rejected.append(directory.name)
            break
        completed.append(
            CompletedBatch(
                start_page=start_page,
                end_page=end_page,
                content_list_path=content_list_path,
                items=tuple(dict(item) for item in items),
            )
        )
        expected_start = end_page + 1
    return completed, rejected


def merge_batch_items(batches: Sequence[CompletedBatch]) -> list[dict[str, Any]]:
    """Convert batch-local page indices to global zero-based PDF indices."""
    merged: list[dict[str, Any]] = []
    for batch in batches:
        offset = batch.start_page - 1
        for item in batch.items:
            merged_item = dict(item)
            merged_item["page_idx"] = int(item["page_idx"]) + offset
            # Final normalization falls back to bbox crops after _mineru_work is
            # renamed. Force that same path now, outside the parser work tree.
            merged_item.pop("img_path", None)
            merged.append(merged_item)
    return merged


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    replace_with_retry(temporary, path)


def prepare_progressive_segments(
    batches: Sequence[CompletedBatch],
    pdf_path: Path,
    doc_name: str,
    progressive_dir: Path,
) -> tuple[Path, list[dict[str, Any]]]:
    """Normalize a completed prefix without touching canonical parser outputs."""
    if not batches:
        raise PreparationError("No contiguous completed MinerU batches are available.")
    content_list_path = progressive_dir / PROGRESSIVE_CONTENT_LIST
    segments_path = progressive_dir / PROGRESSIVE_SEGMENTS
    _write_json(content_list_path, merge_batch_items(batches))
    segments = normalize_segments(content_list_path, doc_name, pdf_path)
    _write_json(segments_path, segments)
    return segments_path, segments


def _load_caption_cache(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreparationError(f"Could not read caption cache {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PreparationError(f"Caption cache is not an object: {path}")
    result: dict[str, dict[str, str]] = {}
    for segment_id, variants in payload.items():
        if (
            not isinstance(segment_id, str)
            or not isinstance(variants, dict)
            or not all(isinstance(model, str) and isinstance(text, str) for model, text in variants.items())
        ):
            raise PreparationError(f"Invalid caption cache entry in {path}.")
        result[segment_id] = dict(variants)
    return result


def _merge_caption_caches(
    first: dict[str, dict[str, str]],
    second: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    merged = {segment_id: dict(variants) for segment_id, variants in first.items()}
    for segment_id, variants in second.items():
        destination = merged.setdefault(segment_id, {})
        for model, caption in variants.items():
            existing = destination.get(model)
            if existing is not None and existing != caption:
                raise PreparationError(
                    f"Conflicting cached caption for {segment_id!r} using {model!r}."
                )
            destination[model] = caption
    return merged


def _sync_caption_caches(progressive_dir: Path, canonical_path: Path) -> None:
    progressive_path = progressive_dir / CAPTION_CACHE_FILENAME
    merged = _merge_caption_caches(
        _load_caption_cache(canonical_path),
        _load_caption_cache(progressive_path),
    )
    _write_json(progressive_path, merged)
    _write_json(canonical_path, merged)


def execute_preparation(
    *,
    pdf_path: Path = PDF_PATH,
    doc_dir: Path = DOC_DIR,
    fingerprint_path: Path = FINGERPRINT_PATH,
    index_dir: Path = INDEX_DIR,
    ledger_path: Path = LEDGER_PATH,
    model: str = "luna",
    chunk_tokens: int = DEFAULT_CHUNK_TOKENS,
    budget_usd: float = 30,
    workers: int = 1,
) -> dict[str, Any]:
    """Prepare the current completed prefix and persist only reusable caches."""
    if (
        not isinstance(workers, int)
        or isinstance(workers, bool)
        or workers not in CAPTION_WORKER_CHOICES
    ):
        raise ValueError("workers must be an integer from 1 through 4")
    source_hash = verify_source_fingerprint(pdf_path, fingerprint_path)
    with fitz.open(pdf_path) as document:
        page_count = document.page_count
    progressive_dir = doc_dir / PROGRESSIVE_DIRNAME
    canonical_caption_cache = doc_dir / CAPTION_CACHE_FILENAME
    embedding_cache = index_dir / EMBEDDING_CACHE_FILENAME
    generated_captions = cached_captions = 0
    with api_budget(ledger_path, budget_usd) as budget:
        # The ledger lock is also the single-writer lock for every progressive
        # artifact and reusable cache touched by this worker.
        if verify_source_fingerprint(pdf_path, fingerprint_path) != source_hash:
            raise PreparationError("Source PDF changed before progressive preparation.")
        batches, rejected = discover_completed_batches(doc_dir, page_count)
        segments_path, segments = prepare_progressive_segments(
            batches, pdf_path, pdf_path.stem, progressive_dir
        )

        # Recheck after rendering: source changes must never be mixed with caches.
        if verify_source_fingerprint(pdf_path, fingerprint_path) != source_hash:
            raise PreparationError("Source PDF changed during progressive preparation.")

        _sync_caption_caches(progressive_dir, canonical_caption_cache)
        try:
            generated_captions, cached_captions, _ = caption_segments_file(
                segments_path,
                model=model,
                workers=workers,
            )
        finally:
            # caption_segments_file checkpoints after every generated caption;
            # preserve those checkpoints canonically even if a later call fails.
            _sync_caption_caches(progressive_dir, canonical_caption_cache)

        records, text_record_count = collect_records(
            [segments_path], target_tokens=chunk_tokens
        )
        _, generated_embeddings, cached_embeddings = embed_records(
            records, embedding_cache
        )
        spent = budget.spent

    return {
        "doc": pdf_path.stem,
        "completed_batches": len(batches),
        "completed_through_page": batches[-1].end_page,
        "rejected_or_incomplete_batch": rejected[0] if rejected else None,
        "segments": len(segments),
        "visual_segments": sum(
            segment.get("type") in {"figure", "table"} for segment in segments
        ),
        "text_records": text_record_count,
        "visual_records": len(records) - text_record_count,
        "generated_captions": generated_captions,
        "cached_captions": cached_captions,
        "generated_embeddings": generated_embeddings,
        "cached_embeddings": cached_embeddings,
        "estimated_spent_usd": spent,
        "progressive_segments": str(segments_path),
        "caption_cache": str(canonical_caption_cache),
        "embedding_cache": str(embedding_cache),
    }


def inspect_current_prefix(
    pdf_path: Path = PDF_PATH,
    doc_dir: Path = DOC_DIR,
    fingerprint_path: Path = FINGERPRINT_PATH,
) -> dict[str, Any]:
    """Read-only status used by the default dry-run."""
    verify_source_fingerprint(pdf_path, fingerprint_path)
    with fitz.open(pdf_path) as document:
        page_count = document.page_count
    batches, rejected = discover_completed_batches(doc_dir, page_count)
    merged = merge_batch_items(batches)
    usable_items = sum(
        str(item.get("type", "")) in TEXT_LIKE_TYPES
        or str(item.get("type", "")) in FIGURE_TYPES
        or item.get("type") == "table"
        for item in merged
    )
    return {
        "mode": "dry-run",
        "doc": pdf_path.stem,
        "pdf_pages": page_count,
        "completed_batches": len(batches),
        "completed_through_page": batches[-1].end_page if batches else 0,
        "rejected_or_incomplete_batch": rejected[0] if rejected else None,
        "mineru_items": len(merged),
        "usable_items": usable_items,
        "writes": 0,
        "paid_calls": 0,
    }


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="prepare captions and embeddings; otherwise perform a read-only dry-run",
    )
    parser.add_argument("--model", choices=("luna", "terra"), default="luna")
    parser.add_argument(
        "--workers",
        type=int,
        choices=CAPTION_WORKER_CHOICES,
        default=1,
        help="parallel caption requests, from 1 through 4 (default: 1)",
    )
    parser.add_argument("--chunk-tokens", type=int, default=DEFAULT_CHUNK_TOKENS)
    parser.add_argument("--budget-usd", type=float, default=30)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    if args.chunk_tokens <= 0:
        print("--chunk-tokens must be positive.", file=sys.stderr)
        return 2
    try:
        report = (
            execute_preparation(
                model=args.model,
                chunk_tokens=args.chunk_tokens,
                budget_usd=args.budget_usd,
                workers=args.workers,
            )
            if args.execute
            else inspect_current_prefix()
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Stopped safely: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
