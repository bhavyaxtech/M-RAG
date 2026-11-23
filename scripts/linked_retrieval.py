"""Collection retrieval that keeps a long manual from monopolizing the context.

Uses the same embedding and exact FAISS index as document retrieval. This is
evidence selection, not a claim that semantic similarity proves applicability.
"""

from collections import Counter
import json
from pathlib import Path
import re
from typing import Any

from scripts.query import _load_index, _load_metadata, _normalized_query_vector
from scripts.embed_and_index import METADATA_FILENAME


def is_navigation_text(text: str) -> bool:
    """Recognize contents and change logs, not technical evidence sections."""
    heading = text[:160].strip().lstrip("#* ")
    if re.match(
        r"(?:(?:table\s+\d+\.?)\s*)?(?:document\s+)?revision history\b"
        r"|(?:\d+\s+)?(?:contents|list of (?:tables|figures))\b",
        heading, re.IGNORECASE,
    ):
        return True
    # Long manuals split their contents across pages/chunks without repeating
    # the heading. Require predominantly numbered section + page-number lines
    # so a normal paragraph mentioning a section is not discarded.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    entries = sum(bool(re.match(r"\d+\.\d+(?:\.\d+)*\s+.+?\s+[. ]*\d+$", line)) for line in lines)
    return len(lines) >= 5 and entries / len(lines) >= 0.6


def filter_navigation_hits(hits: list[dict], question: str) -> list[dict]:
    # Navigation remains searchable when it is itself the user's subject.
    if re.search(r"\b(?:contents|list of (?:tables|figures)|revision history|change\s*log)\b", question, re.IGNORECASE):
        return hits
    return [hit for hit in hits if not is_navigation_text(hit.get("text_or_caption", ""))]


def select_diverse_hits(
    hits: list[dict], k: int, named_docs: set[str], linked_docs: set[str] | None = None,
) -> list[dict]:
    """Give named documents enough detail before adding related documents."""
    selected: list[dict] = []
    used: set[str] = set()
    counts: Counter = Counter()

    def add(hit: dict) -> None:
        selected.append(dict(hit))
        used.add(hit["segment_id"])
        counts[hit["doc"]] += 1

    for document in sorted(named_docs):
        candidate = next((hit for hit in hits if hit["doc"] == document), None)
        if candidate is not None and len(selected) < k:
            add(candidate)
    # One introduction per named PDF is not enough to answer a comparison.
    # Reserve up to two slots for other sources, rather than allowing diversity
    # across 20 PDFs to crowd out the requested documents' detailed sections.
    detail_limit = max(1, (k - 2) // max(1, len(named_docs)))
    for limit in range(2, detail_limit + 1):
        for hit in hits:
            if len(selected) == k:
                break
            if (
                hit["doc"] in named_docs and hit["segment_id"] not in used
                and counts[hit["doc"]] < limit and hit["score"] >= 0.42
            ):
                add(hit)
    for document in sorted((linked_docs or set()) - named_docs):
        candidate = next((hit for hit in hits if hit["doc"] == document), None)
        if candidate is not None and len(selected) < k:
            add(candidate)
    # Never force unrelated documents just to claim multi-document retrieval.
    for limit in (1, 2, k):
        for hit in hits:
            if len(selected) == k:
                break
            if hit["segment_id"] in used or counts[hit["doc"]] >= limit:
                continue
            if limit == 1 and hit["score"] < 0.42:
                continue
            add(hit)
    for rank, hit in enumerate(selected, start=1):
        hit["rank"] = rank
    return selected


def retrieve_collection(
    query: str, mode: str, k: int, index_dir: Path, reference_query: str | None = None,
) -> list[dict[str, Any]]:
    if not query.strip() or mode not in {"mrag", "text_only"} or not 1 <= k <= 20:
        raise ValueError("Invalid collection retrieval request")
    metadata = _load_metadata(index_dir / METADATA_FILENAME)
    index = _load_index(mode, index_dir)
    if int(index.ntotal) == 0:
        raise ValueError("Collection index is empty; finish ingestion first")
    vector = _normalized_query_vector(query, int(index.d))
    scores, ids = index.search(vector, int(index.ntotal))
    manifest_path = index_dir / "document_manifest.json"
    documents = {}
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        documents = {document["doc_id"]: document for document in manifest["documents"]}
    named_docs = {
        doc_id for doc_id, document in documents.items()
        if re.search(
            rf"\b{re.escape(document['document_id'])}\b",
            query + "\n" + (reference_query or ""),
            re.IGNORECASE,
        )
    }
    hits = []
    for score, vector_id in zip(scores[0], ids[0]):
        if int(vector_id) < 0:
            continue
        hit = dict(metadata[int(vector_id)])
        if mode == "text_only" and hit["type"] != "text":
            raise ValueError("Text-only index contains a visual segment")
        hit["score"] = float(score)
        document = documents.get(hit["doc"], {})
        hit["document_title"] = document.get("title", hit["doc"])
        hit["applicability"] = document.get("applicability", "Verify device applicability")
        hit["document_revision"] = document.get("revision", "See original source page")
        hits.append(hit)
    hits = filter_navigation_hits(hits, query + "\n" + (reference_query or ""))
    # Follow only references on actually retrieved pages, not every reference
    # anywhere in the manual. Similarity alone does not establish this link.
    ids_by_identity = {d["document_id"]: doc_id for doc_id, d in documents.items()}
    linked_docs = set()
    for hit in hits[:3]:
        if hit["score"] < 0.42:
            continue
        for identity, pages in documents.get(hit["doc"], {}).get("references", {}).items():
            target = ids_by_identity.get(identity)
            if target and hit["page"] in pages:
                candidate = next((h for h in hits if h["doc"] == target), None)
                if candidate is not None and candidate["score"] >= 0.42:
                    linked_docs.add(target)
    # Explicit user references take priority; link expansion is deliberately
    # bounded so one bibliography cannot consume the entire evidence window.
    available_link_slots = max(0, min(3, k) - len(named_docs))
    linked_docs = set(sorted(linked_docs - named_docs)[:available_link_slots])
    return select_diverse_hits(hits, k, named_docs, linked_docs)
