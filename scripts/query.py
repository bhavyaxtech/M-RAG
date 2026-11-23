"""Retrieve indexed datasheet segments and generate grounded answers."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from functools import lru_cache
import json
import math
from pathlib import Path
import sys
from typing import Any, Literal, cast

import faiss
import numpy as np

from scripts.azure_client import embed_text, generate
from scripts.config import generation_deployment_name
from scripts.embed_and_index import (
    INDEX_DIR,
    METADATA_FILENAME,
    MRAG_INDEX_FILENAME,
    TEXT_ONLY_INDEX_FILENAME,
    VISUAL_TYPES,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
QueryMode = Literal["mrag", "text_only"]


class QueryError(RuntimeError):
    """Raised when retrieval inputs or index artifacts are invalid."""


@lru_cache(maxsize=None)
def _load_metadata(path: Path) -> dict[int, dict[str, Any]]:
    if not path.is_file():
        raise QueryError(f"Metadata file not found: {path}. Build the indexes first.")

    metadata: dict[int, dict[str, Any]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise QueryError(f"Could not read metadata {path}: {exc}") from exc

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise QueryError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
        if not isinstance(payload, dict):
            raise QueryError(f"Metadata at {path}:{line_number} is not an object.")

        vector_id = payload.get("vector_id")
        segment_id = payload.get("segment_id")
        doc = payload.get("doc")
        page = payload.get("page")
        segment_type = payload.get("type")
        text = payload.get("text_or_caption")
        if (
            not isinstance(vector_id, int)
            or isinstance(vector_id, bool)
            or vector_id < 0
            or not isinstance(segment_id, str)
            or not segment_id.strip()
            or not isinstance(doc, str)
            or not doc.strip()
            or not isinstance(page, int)
            or isinstance(page, bool)
            or page < 1
            or segment_type not in {"text", *VISUAL_TYPES}
            or not isinstance(text, str)
            or not text.strip()
        ):
            raise QueryError(
                f"Metadata at {path}:{line_number} is missing required fields. "
                "Rebuild indexes with scripts/embed_and_index.py."
            )
        if vector_id in metadata:
            raise QueryError(f"Duplicate vector_id {vector_id} in {path}.")
        if segment_type in VISUAL_TYPES:
            image_path = payload.get("image_path")
            if not isinstance(image_path, str) or not image_path.strip():
                raise QueryError(
                    f"Visual metadata at {path}:{line_number} has no image_path."
                )

        metadata[vector_id] = dict(payload)

    if not metadata:
        raise QueryError(f"Metadata file is empty: {path}")
    return metadata


def _load_index(mode: QueryMode, index_dir: Path) -> Any:
    filename = MRAG_INDEX_FILENAME if mode == "mrag" else TEXT_ONLY_INDEX_FILENAME
    index_path = index_dir / filename
    if not index_path.is_file():
        raise QueryError(f"FAISS index not found: {index_path}. Build the indexes first.")
    try:
        return faiss.read_index(str(index_path))
    except RuntimeError as exc:
        raise QueryError(f"Could not load FAISS index {index_path}: {exc}") from exc


def _normalized_query_vector(query_text: str, dimension: int) -> np.ndarray:
    vector = np.asarray(embed_text(query_text), dtype=np.float32)
    if vector.ndim != 1 or vector.shape[0] != dimension:
        raise QueryError(
            f"Query embedding dimension mismatch: index expects {dimension}, "
            f"got {vector.shape}."
        )
    norm = float(np.linalg.norm(vector))
    if not math.isfinite(norm) or norm == 0:
        raise QueryError("Query embedding is zero-length or non-finite.")
    return np.ascontiguousarray((vector / norm).reshape(1, -1), dtype=np.float32)


def retrieve(
    query_text: str,
    mode: QueryMode,
    k: int = 5,
    index_dir: Path = INDEX_DIR,
    docs: Sequence[str] | None = None,
    pages: Sequence[int] | None = None,
) -> list[dict[str, Any]]:
    """Return ranked metadata records for the selected exact FAISS index."""
    if not query_text.strip():
        raise ValueError("query_text must not be empty")
    if mode not in {"mrag", "text_only"}:
        raise ValueError("mode must be 'mrag' or 'text_only'")
    if not isinstance(k, int) or isinstance(k, bool) or k <= 0:
        raise ValueError("k must be a positive integer")

    index_dir = index_dir.expanduser().resolve()
    metadata = _load_metadata(index_dir / METADATA_FILENAME)
    index = _load_index(mode, index_dir)
    index_size = int(index.ntotal)
    if index_size == 0:
        raise QueryError(f"The {mode} index is empty.")

    if docs is None and pages is None:
        query_vector = _normalized_query_vector(query_text.strip(), int(index.d))
        search = getattr(index, "search")
        scores, vector_ids = search(query_vector, min(k, index_size))
    else:
        requested_docs = set(docs) if docs is not None else None
        if requested_docs is not None:
            available_docs = {str(record["doc"]) for record in metadata.values()}
            missing_docs = requested_docs - available_docs
            if missing_docs:
                missing = ", ".join(sorted(missing_docs))
                raise QueryError(f"Document(s) not present in metadata: {missing}")

        requested_pages = set(pages) if pages is not None else None
        if requested_pages is not None and any(
            not isinstance(page, int) or isinstance(page, bool) or page < 1
            for page in requested_pages
        ):
            raise ValueError("pages must contain only positive integers")

        vector_ids_for_scope = [
            vector_id
            for vector_id, record in metadata.items()
            if (requested_docs is None or record["doc"] in requested_docs)
            and (requested_pages is None or record["page"] in requested_pages)
            and (mode != "text_only" or record["type"] == "text")
        ]
        if not vector_ids_for_scope and pages is not None:
            return []
        if not vector_ids_for_scope:
            raise QueryError("No indexed vectors matched the requested document scope.")
        query_vector = _normalized_query_vector(query_text.strip(), int(index.d))
        search = getattr(index, "search")
        selector_ids = np.array(vector_ids_for_scope, dtype="int64")
        params = faiss.SearchParameters(sel=faiss.IDSelectorBatch(selector_ids))
        scores, vector_ids = search(
            query_vector,
            min(k, len(vector_ids_for_scope)),
            params=params,
        )

    retrieved: list[dict[str, Any]] = []
    for rank, (vector_id_value, score_value) in enumerate(
        zip(vector_ids[0], scores[0]),
        start=1,
    ):
        vector_id = int(vector_id_value)
        if vector_id < 0:
            continue
        record = metadata.get(vector_id)
        if record is None:
            raise QueryError(
                f"Index returned vector_id {vector_id}, but metadata has no matching row."
            )
        if mode == "text_only" and record.get("type") != "text":
            raise QueryError(
                "Text-only index resolved to visual metadata; rebuild both indexes "
                "to restore baseline alignment."
            )

        hit = dict(record)
        hit["rank"] = rank
        hit["score"] = float(score_value)
        retrieved.append(hit)

    if not retrieved:
        raise QueryError(f"The {mode} index returned no usable hits.")
    return retrieved


def _resolve_image_path(image_path: str, segment_id: str) -> str:
    path = Path(image_path).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()
    if not path.is_file():
        raise QueryError(f"Cropped image for segment {segment_id!r} not found: {path}")
    return str(path)


def _generation_inputs(
    query_text: str,
    mode: QueryMode,
    retrieved_segments: Sequence[dict[str, Any]],
) -> tuple[str, list[str] | None]:
    context_blocks: list[str] = []
    images: list[str] = []

    for result_number, segment in enumerate(retrieved_segments, start=1):
        segment_id = str(segment["segment_id"])
        segment_type = str(segment["type"])
        source = f"{segment['doc']}, page {segment['page']}"
        text = str(segment["text_or_caption"])

        if segment_type == "text":
            context_blocks.append(
                f"[{result_number}] TEXT — {source} — segment {segment_id}\n{text}"
            )
            continue

        if mode == "text_only":
            raise QueryError("Text-only generation cannot include a visual segment.")
        image_number = len(images) + 1
        images.append(_resolve_image_path(str(segment["image_path"]), segment_id))
        context_blocks.append(
            f"[{result_number}] {segment_type.upper()} — {source} — segment "
            f"{segment_id} — attached image {image_number}\n"
            f"Retrieval caption: {text}"
        )

    prompt = """Answer the hardware-datasheet question using only the retrieved context below. Use all relevant retrieved segments together rather than relying only on the top-ranked hit. Preserve exact pin labels, units, conditions, and numeric minimum/typical/maximum values. If the retrieved evidence is insufficient, say so instead of guessing. Cite the source document and page in the answer.

Question:
{query}

Retrieved context:
{context}
""".format(
        query=query_text.strip(),
        context="\n\n".join(context_blocks),
    )
    return prompt, images or None


def query(
    query_text: str,
    mode: QueryMode,
    k: int = 5,
    index_dir: Path = INDEX_DIR,
) -> dict[str, Any]:
    """Retrieve top-k segments and generate one grounded Sol answer."""
    retrieved_segments = retrieve(query_text, mode, k=k, index_dir=index_dir)
    prompt, images = _generation_inputs(query_text, mode, retrieved_segments)
    answer = generate(prompt, images=images, model="sol")
    deployment = generation_deployment_name("sol")
    return {
        "mode": mode,
        "retrieved_segments": retrieved_segments,
        "retrieved_segment_ids": [
            str(segment["segment_id"]) for segment in retrieved_segments
        ],
        "answer": answer,
        "deployment": deployment,
    }


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Retrieve datasheet evidence and generate a grounded answer."
    )
    parser.add_argument("query_text", help="hardware datasheet question")
    parser.add_argument(
        "--mode",
        choices=("mrag", "text_only"),
        default="mrag",
        help="retrieval/generation mode (default: mrag)",
    )
    parser.add_argument("-k", type=int, default=5, help="retrieval depth (default: 5)")
    parser.add_argument(
        "--index-dir",
        type=Path,
        default=INDEX_DIR,
        help="directory containing FAISS indexes and metadata",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
        result = query(
            args.query_text,
            cast(QueryMode, args.mode),
            k=args.k,
            index_dir=args.index_dir,
        )
    except (QueryError, OSError, RuntimeError, ValueError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
