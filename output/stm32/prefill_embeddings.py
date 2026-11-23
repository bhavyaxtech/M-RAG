"""Prepare embeddings for finished documents while the large manuals parse."""

import json

from scripts.embed_and_index import (
    EMBEDDING_CACHE_FILENAME, EMBEDDING_MODEL, _append_cache_entry, _content_hash,
    _parse_cache_entry, collect_records, embed_records, load_embedding_cache,
)
from scripts.ingest_collection import INDEX, LEDGER, PARSED, ROOT
from scripts.usage_budget import api_budget


segment_files = []
for path in sorted(PARSED.glob("*/segments.json")):
    segments = json.loads(path.read_text(encoding="utf-8"))
    if all(segment["type"] == "text" or segment.get("caption_model") for segment in segments):
        segment_files.append(path)

records, text_count = collect_records(segment_files)
records_by_key = {record.cache_key: record for record in records}
cache_path = INDEX / EMBEDDING_CACHE_FILENAME

with api_budget(LEDGER, 30):
    cache = load_embedding_cache(cache_path)
    # Source text and model hashes must still match after renaming the identical
    # datasheet. Unmatched records are embedded normally; no vectors are guessed.
    inherited = 0
    sources = [
        (ROOT / "index" / EMBEDDING_CACHE_FILENAME, "stm32f103c8", "stm32-ds5319"),
        (ROOT / "output/stm32/pilot-index" / EMBEDDING_CACHE_FILENAME, "", ""),
    ]
    for source_path, old_prefix, new_prefix in sources:
        if not source_path.exists():
            continue
        with source_path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    continue
                payload = json.loads(line)
                source_key = payload.get("cache_key", "")
                if old_prefix and not source_key.startswith(old_prefix + "-"):
                    continue
                target_key = new_prefix + source_key[len(old_prefix):]
                record = records_by_key.get(target_key)
                if record is None or target_key in cache:
                    continue
                if payload.get("model") != EMBEDDING_MODEL or payload.get("content_hash") != _content_hash(record.text_or_caption):
                    continue
                _, entry = _parse_cache_entry(payload, line_number, source_path)
                _append_cache_entry(cache_path, target_key, entry)
                cache[target_key] = entry
                inherited += 1
    matrix, generated, cached = embed_records(records, cache_path)
    print(f"Prepared {len(records)} records from {len(segment_files)} documents: {generated} new, {cached} cached ({inherited} inherited).")
    print("Only the embedding cache was written; no partial collection was published.")
