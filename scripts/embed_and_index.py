"""Embed parsed segments and build fair multimodal and text-only FAISS indexes."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

import faiss
import numpy as np
import tiktoken

from scripts.azure_client import embed_text
from scripts.config import (
    active_index_dir,
    embedding_deployment_name,
    embedding_model_name,
    generation_deployment_name,
    get_settings,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARSED_HARDWARE_DIR = PROJECT_ROOT / "data" / "parsed" / "hardware"
INDEX_DIR = active_index_dir(PROJECT_ROOT / "index")
MRAG_INDEX_FILENAME = "mrag_index.faiss"
TEXT_ONLY_INDEX_FILENAME = "text_only_index.faiss"
METADATA_FILENAME = "metadata.jsonl"
EMBEDDING_CACHE_FILENAME = "embedding_cache.jsonl"
RUN_METADATA_FILENAME = "run_metadata.json"
EMBEDDING_MODEL = embedding_model_name()
VISUAL_TYPES = {"figure", "table"}
DEFAULT_CHUNK_TOKENS = 400
MAX_EMBEDDING_TOKENS = 8000
_TOKEN_PATTERN = re.compile(r"\S+(?:\s+|$)")


class IndexingError(RuntimeError):
    """Raised when parsed input or cached embeddings cannot build valid indexes."""


@dataclass(frozen=True)
class IndexRecord:
    """One text chunk or visual caption and its retrieval metadata."""

    cache_key: str
    segment_id: str
    doc: str
    page: int
    type: str
    text_or_caption: str
    image_path: str | None = None
    caption_model: str | None = None
    source_segment_id: str | None = None

    def metadata(self, vector_id: int) -> dict[str, Any]:
        result: dict[str, Any] = {
            "vector_id": vector_id,
            "segment_id": self.segment_id,
            "doc": self.doc,
            "page": self.page,
            "type": self.type,
            "text_or_caption": self.text_or_caption,
        }
        if self.image_path is not None:
            result["image_path"] = self.image_path
        if self.caption_model is not None:
            result["caption_model"] = self.caption_model
        if self.source_segment_id is not None:
            result["source_segment_id"] = self.source_segment_id
        return result


@dataclass(frozen=True)
class CacheEntry:
    content_hash: str
    model: str
    embedding: list[float]


def split_embedding_text(text: str) -> list[str]:
    """Preserve all content while staying below the embedding input limit.

    Ordinary page chunks and captions remain unchanged, including cache keys.
    Whitespace estimates alone do not bound dense numeric tables or code.
    """
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(text, disallowed_special=())
    if len(tokens) <= MAX_EMBEDDING_TOKENS:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(start + MAX_EMBEDDING_TOKENS, len(tokens))
        while end > start:
            try:
                chunk = encoding.decode(tokens[start:end], errors="strict")
                break
            except UnicodeDecodeError:
                # A token boundary can split a multi-byte Unicode character.
                end -= 1
        else:
            raise IndexingError("Could not split embedding text without losing Unicode content")
        chunks.append(chunk)
        start = end
    return chunks


def chunk_text(text: str, target_tokens: int = DEFAULT_CHUNK_TOKENS) -> list[str]:
    """Split text into balanced chunks using a whitespace-token estimate."""
    if target_tokens <= 0:
        raise ValueError("target_tokens must be positive")

    pieces = _TOKEN_PATTERN.findall(text.strip())
    token_count = len(pieces)
    if token_count == 0:
        return []

    # At the default target, this selects balanced 300-500-token chunks and
    # avoids a tiny final remainder. Short source segments remain intact because
    # manufacturing context across segment boundaries is not merged.
    minimum_tokens = max(1, round(target_tokens * 0.75))
    maximum_tokens = max(minimum_tokens, round(target_tokens * 1.25))
    maximum_candidates = max(1, math.ceil(token_count / minimum_tokens) + 1)

    def chunk_count_score(count: int) -> tuple[float, float]:
        average = token_count / count
        range_violation = max(
            0.0,
            minimum_tokens - average,
            average - maximum_tokens,
        )
        return range_violation, abs(average - target_tokens)

    chunk_count = min(
        range(1, maximum_candidates + 1),
        key=chunk_count_score,
    )
    base_size, larger_chunk_count = divmod(token_count, chunk_count)
    chunks: list[str] = []
    start = 0
    for index in range(chunk_count):
        size = base_size + (1 if index < larger_chunk_count else 0)
        chunks.append("".join(pieces[start : start + size]).strip())
        start += size
    return chunks


def _read_segments(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IndexingError(f"Could not read parsed segments {path}: {exc}") from exc

    if not isinstance(payload, list) or not all(
        isinstance(segment, dict) for segment in payload
    ):
        raise IndexingError(f"Expected {path} to contain a list of segment objects.")
    return payload


def discover_segment_files(inputs: Iterable[Path], parsed_root: Path) -> list[Path]:
    """Resolve explicit segment files/document directories or discover all docs."""
    candidates: list[Path] = []
    for raw_path in inputs:
        path = raw_path.expanduser()
        if path.is_dir():
            path = path / "segments.json"
        candidates.append(path.resolve())

    if not candidates:
        root = parsed_root.expanduser().resolve()
        if not root.is_dir():
            return []
        candidates = sorted(root.glob("*/segments.json"))

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        if path not in seen:
            unique.append(path)
            seen.add(path)
    return unique


def _required_string(
    segment: dict[str, Any],
    field: str,
    segments_path: Path,
) -> str:
    value = segment.get(field)
    if not isinstance(value, str) or not value.strip():
        raise IndexingError(
            f"Segment in {segments_path} has no non-empty {field!r} field."
        )
    return value.strip()


def _segment_page(segment: dict[str, Any], segments_path: Path) -> int:
    page = segment.get("page")
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise IndexingError(f"Segment in {segments_path} has an invalid page: {page!r}")
    return page


def collect_records(
    segment_files: Sequence[Path],
    target_tokens: int = DEFAULT_CHUNK_TOKENS,
) -> tuple[list[IndexRecord], int]:
    """Create one ordered corpus with all text records before visual records."""
    text_records: list[IndexRecord] = []
    visual_records: list[IndexRecord] = []
    page_texts: dict[tuple[str, int], list[str]] = {}
    seen_segment_ids: set[str] = set()

    for segments_path in segment_files:
        segments_path = segments_path.resolve()
        if not segments_path.is_file():
            raise IndexingError(f"Segments file not found: {segments_path}")

        for segment in _read_segments(segments_path):
            segment_type = segment.get("type")
            if segment_type not in {"text", *VISUAL_TYPES}:
                continue

            segment_id = _required_string(segment, "segment_id", segments_path)
            if segment_id in seen_segment_ids:
                raise IndexingError(f"Duplicate segment_id across inputs: {segment_id}")
            seen_segment_ids.add(segment_id)
            doc = _required_string(segment, "doc", segments_path)
            page = _segment_page(segment, segments_path)

            if segment_type == "text":
                text = _required_string(segment, "text", segments_path)
                page_texts.setdefault((doc, page), []).append(text)
                continue

            caption = _required_string(segment, "caption", segments_path)
            caption_model = _required_string(segment, "caption_model", segments_path)
            if caption_model not in {"luna", "terra"}:
                raise IndexingError(
                    f"Visual segment {segment_id!r} has unsupported caption_model "
                    f"{caption_model!r}."
                )
            image_path = _required_string(segment, "image_path", segments_path)
            caption_parts = split_embedding_text(caption)
            for part_number, caption_part in enumerate(caption_parts):
                part_id = (
                    segment_id if len(caption_parts) == 1
                    else f"{segment_id}-caption-part-{part_number:03d}"
                )
                visual_records.append(
                    IndexRecord(
                        cache_key=f"{part_id}:caption",
                        segment_id=part_id,
                        doc=doc,
                        page=page,
                        type=str(segment_type),
                        text_or_caption=caption_part,
                        image_path=image_path,
                        caption_model=caption_model,
                        source_segment_id=segment_id if len(caption_parts) > 1 else None,
                    )
                )

    for (doc, page), text_blocks in page_texts.items():
        page_text = "\n\n".join(text_blocks)
        page_chunks = [
            part
            for chunk in chunk_text(page_text, target_tokens=target_tokens)
            for part in split_embedding_text(chunk)
        ]
        for chunk_index, chunk in enumerate(page_chunks):
            chunk_id = f"{doc}-p{page:04d}-text-chunk-{chunk_index:03d}"
            text_records.append(
                IndexRecord(
                    cache_key=chunk_id,
                    segment_id=chunk_id,
                    doc=doc,
                    page=page,
                    type="text",
                    text_or_caption=chunk,
                )
            )

    if not text_records:
        raise IndexingError("No non-empty text segments were found; baseline index is empty.")

    # Keeping text first makes its vector IDs identical in both indexes. The
    # baseline below is a filtered view of this corpus, never a second pass.
    return text_records + visual_records, len(text_records)


def _content_hash(text: str) -> str:
    payload = f"{EMBEDDING_MODEL}\0{text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _parse_cache_entry(payload: Any, line_number: int, path: Path) -> tuple[str, CacheEntry]:
    if not isinstance(payload, dict):
        raise IndexingError(f"Invalid embedding cache object at {path}:{line_number}.")

    cache_key = payload.get("cache_key")
    content_hash = payload.get("content_hash")
    model = payload.get("model")
    embedding = payload.get("embedding")
    if (
        not isinstance(cache_key, str)
        or not isinstance(content_hash, str)
        or not isinstance(model, str)
        or not isinstance(embedding, list)
        or not embedding
        or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in embedding
        )
    ):
        raise IndexingError(f"Invalid embedding cache entry at {path}:{line_number}.")

    vector = [float(value) for value in embedding]
    if not all(math.isfinite(value) for value in vector):
        raise IndexingError(f"Non-finite cached embedding at {path}:{line_number}.")
    return cache_key, CacheEntry(content_hash, model, vector)


def load_embedding_cache(path: Path) -> dict[str, CacheEntry]:
    """Load the newest JSONL cache entry for each stable record key."""
    if not path.exists():
        return {}

    cache: dict[str, CacheEntry] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise IndexingError(f"Could not read embedding cache {path}: {exc}") from exc

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise IndexingError(
                f"Invalid JSON in embedding cache {path}:{line_number}: {exc}"
            ) from exc
        cache_key, entry = _parse_cache_entry(payload, line_number, path)
        cache[cache_key] = entry
    return cache


def _append_cache_entry(path: Path, cache_key: str, entry: CacheEntry) -> None:
    """Durably append one embedding before advancing to the next API call."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cache_key": cache_key,
        "content_hash": entry.content_hash,
        "model": entry.model,
        "embedding": entry.embedding,
    }
    with path.open("a", encoding="utf-8", newline="\n") as cache_file:
        cache_file.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        cache_file.write("\n")
        cache_file.flush()


def embed_records(
    records: Sequence[IndexRecord],
    cache_path: Path,
) -> tuple[np.ndarray, int, int]:
    """Embed the shared corpus once, reusing unchanged cached vectors."""
    cache = load_embedding_cache(cache_path)
    vectors: list[list[float]] = []
    generated_count = 0
    cached_count = 0
    dimension: int | None = None

    # Amortize network latency for large manuals while keeping one shared
    # embedding pass for M-RAG and its text-only baseline.
    pending = [
        record for record in records
        if record.cache_key not in cache
        or cache[record.cache_key].content_hash != _content_hash(record.text_or_caption)
        or cache[record.cache_key].model != EMBEDDING_MODEL
    ]
    for start in range(0, len(pending), 32):
        batch = pending[start:start + 32]
        embedded = embed_text([record.text_or_caption for record in batch])
        if len(embedded) != len(batch):
            raise IndexingError("Embedding response does not match the batch length")
        for record, vector in zip(batch, embedded):
            if not vector or not all(math.isfinite(value) for value in vector):
                raise IndexingError(f"Invalid embedding for {record.cache_key}")
            entry = CacheEntry(_content_hash(record.text_or_caption), EMBEDDING_MODEL, vector)
            _append_cache_entry(cache_path, record.cache_key, entry)
            cache[record.cache_key] = entry
        print(f"  Embedded {min(start + 32, len(pending))}/{len(pending)} new records", flush=True)
    generated_count = len(pending)
    cached_count = len(records) - generated_count

    for record in records:
        vector = cache[record.cache_key].embedding

        if dimension is None:
            dimension = len(vector)
        elif len(vector) != dimension:
            raise IndexingError(
                f"Embedding dimension mismatch for {record.cache_key}: "
                f"expected {dimension}, got {len(vector)}."
            )
        vectors.append(vector)

    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1)
    if not np.all(np.isfinite(norms)) or np.any(norms == 0):
        raise IndexingError("Embedding corpus contains a zero-length or non-finite vector.")
    matrix /= norms[:, np.newaxis]
    return matrix, generated_count, cached_count


def _write_metadata(path: Path, records: Sequence[IndexRecord]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as metadata_file:
        for vector_id, record in enumerate(records):
            metadata_file.write(
                json.dumps(record.metadata(vector_id), ensure_ascii=False) + "\n"
            )


def write_indexes(
    records: Sequence[IndexRecord],
    embeddings: np.ndarray,
    text_record_count: int,
    output_dir: Path,
) -> tuple[Path, Path, Path]:
    """Build both exact indexes from the same normalized embedding matrix."""
    if embeddings.ndim != 2 or embeddings.shape[0] != len(records):
        raise IndexingError("Embedding matrix does not align with index metadata records.")
    if text_record_count < 1 or text_record_count > len(records):
        raise IndexingError("Invalid text record count for baseline index construction.")
    if any(record.type != "text" for record in records[:text_record_count]):
        raise IndexingError("Text-only rows are not the leading rows of the shared corpus.")
    if any(record.type == "text" for record in records[text_record_count:]):
        raise IndexingError("Visual rows are not cleanly separated in the shared corpus.")

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    mrag_path = output_dir / MRAG_INDEX_FILENAME
    text_only_path = output_dir / TEXT_ONLY_INDEX_FILENAME
    metadata_path = output_dir / METADATA_FILENAME
    mrag_temp = mrag_path.with_suffix(mrag_path.suffix + ".tmp")
    text_only_temp = text_only_path.with_suffix(text_only_path.suffix + ".tmp")
    metadata_temp = metadata_path.with_suffix(metadata_path.suffix + ".tmp")

    dimension = int(embeddings.shape[1])
    mrag_index = faiss.IndexFlatIP(dimension)
    mrag_add = getattr(mrag_index, "add")
    mrag_add(np.ascontiguousarray(embeddings, dtype=np.float32))

    # Defense-critical fairness: these are the exact leading rows already added
    # to mrag_index, not embeddings produced by a separate baseline code path.
    text_only_embeddings = np.ascontiguousarray(
        embeddings[:text_record_count], dtype=np.float32
    )
    text_only_index = faiss.IndexFlatIP(dimension)
    text_only_add = getattr(text_only_index, "add")
    text_only_add(text_only_embeddings)

    faiss.write_index(mrag_index, str(mrag_temp))
    faiss.write_index(text_only_index, str(text_only_temp))
    _write_metadata(metadata_temp, records)
    mrag_temp.replace(mrag_path)
    text_only_temp.replace(text_only_path)
    metadata_temp.replace(metadata_path)
    return mrag_path, text_only_path, metadata_path


def _write_run_metadata(
    output_dir: Path,
    records: Sequence[IndexRecord],
    text_record_count: int,
) -> None:
    observed_caption_models = sorted(
        {
            record.caption_model
            for record in records
            if record.caption_model is not None
        }
    )
    # Captions in segments.json were always produced on Azure, whichever
    # embedder or generator this index is built for.
    try:
        settings = get_settings()
        caption_deployments = {"luna": settings.luna_deployment, "terra": settings.terra_deployment}
    except RuntimeError:
        caption_deployments = {"luna": "unconfigured", "terra": "unconfigured"}
    payload = {
        "embedding_model": EMBEDDING_MODEL,
        "embedding_deployment": embedding_deployment_name(),
        "caption_deployments": caption_deployments,
        "caption_models_in_index": observed_caption_models,
        "generation_deployment": generation_deployment_name("sol"),
        "vector_store": "faiss.IndexFlatIP",
        "embeddings_normalized": True,
        "mrag_vector_count": len(records),
        "text_only_vector_count": text_record_count,
    }
    path = output_dir / RUN_METADATA_FILENAME
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def build_indexes(
    segment_files: Sequence[Path],
    output_dir: Path = INDEX_DIR,
    target_tokens: int = DEFAULT_CHUNK_TOKENS,
) -> tuple[int, int, int, int]:
    """Collect, embed, and write indexes; return corpus and cache statistics."""
    records, text_record_count = collect_records(segment_files, target_tokens)
    output_dir = output_dir.resolve()
    embeddings, generated_count, cached_count = embed_records(
        records,
        output_dir / EMBEDDING_CACHE_FILENAME,
    )
    write_indexes(records, embeddings, text_record_count, output_dir)
    _write_run_metadata(output_dir, records, text_record_count)
    visual_count = len(records) - text_record_count
    return text_record_count, visual_count, generated_count, cached_count


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Embed parsed text chunks and visual captions once, then build a "
            "multimodal index and a text-only baseline from that shared matrix."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help=(
            "segments.json file(s) or parsed document directories; defaults to "
            "all documents under data/parsed/hardware"
        ),
    )
    parser.add_argument(
        "--parsed-root",
        type=Path,
        default=PARSED_HARDWARE_DIR,
        help="parsed document root used when no inputs are given",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=INDEX_DIR,
        help="FAISS, metadata, and embedding-cache output directory",
    )
    parser.add_argument(
        "--chunk-tokens",
        type=int,
        default=DEFAULT_CHUNK_TOKENS,
        help="approximate whitespace-token chunk size (default: 400)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    if args.chunk_tokens <= 0:
        print("--chunk-tokens must be positive.", file=sys.stderr)
        return 2

    segment_files = discover_segment_files(args.inputs, args.parsed_root)
    if not segment_files:
        print(
            "No segments.json files found. Run scripts/parse.py and "
            "scripts/caption.py first, or pass parsed document directories.",
            file=sys.stderr,
        )
        return 2

    print(
        f"Building indexes from {len(segment_files)} parsed document(s) with "
        f"{EMBEDDING_MODEL}.",
        flush=True,
    )
    try:
        text_count, visual_count, generated, cached = build_indexes(
            segment_files,
            output_dir=args.output_dir,
            target_tokens=args.chunk_tokens,
        )
    except (IndexingError, OSError, ValueError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr, flush=True)
        return 1

    print(
        f"Embedded {generated} new record(s); reused {cached} cached record(s)."
    )
    print(
        f"Wrote {MRAG_INDEX_FILENAME} with {text_count + visual_count} vectors "
        f"and {TEXT_ONLY_INDEX_FILENAME} with the same {text_count} text vectors."
    )
    print(f"Metadata: {args.output_dir.resolve() / METADATA_FILENAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
