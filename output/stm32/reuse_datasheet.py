"""Reuse the byte-identical, already parsed DS5319 without touching hardware."""

import hashlib
import json
from pathlib import Path
import shutil

from scripts.caption import caption_segments_file
from scripts.extract_bboxes import extract_document_directory
from scripts.parse import _finalize_parse


root = Path(__file__).resolve().parents[2]
old_id = "stm32f103c8"
new_id = "stm32-ds5319"
source_pdf = root / "data/raw/hardware" / f"{old_id}.pdf"
target_pdf = root / "data/raw/stm32" / f"{new_id}.pdf"
source = root / "data/parsed/hardware" / old_id
target = root / "data/parsed/stm32" / new_id

checksum = hashlib.sha256(source_pdf.read_bytes()).hexdigest()
assert checksum == hashlib.sha256(target_pdf.read_bytes()).hexdigest(), "Different PDFs"
assert not target.exists(), "Refusing to replace existing or in-progress parse"
metadata = json.loads((source / "parse_metadata.json").read_text(encoding="utf-8"))
assert metadata["backend"] == "pipeline", "Expected full MinerU pipeline artifacts"

# These source crops use paths relative to the content-list directory. Copying
# its tree keeps every image inside the new corpus's parsed-artifact boundary.
raw_items = json.loads((root / metadata["content_list"]).read_text(encoding="utf-8"))
assert not any(Path(item["img_path"]).is_absolute() for item in raw_items if item.get("img_path"))
shutil.copytree(source / "mineru", target / "mineru")
segments, _ = _finalize_parse(
    target_pdf, target.parent, target / "mineru", metadata["mineru_version"], metadata["backend"]
)
old_segments = {s["segment_id"]: s for s in json.loads((source / "segments.json").read_text(encoding="utf-8"))}
old_cache = json.loads((source / "caption_cache.json").read_text(encoding="utf-8"))
new_cache = {}
for segment in segments:
    old_segment_id = old_id + segment["segment_id"][len(new_id):]
    old_segment = old_segments[old_segment_id]
    assert (segment["page"], segment["type"]) == (old_segment["page"], old_segment["type"])
    if segment["type"] == "text":
        assert segment["text"] == old_segment["text"]
        continue
    old_image = root / old_segment["image_path"]
    new_image = root / segment["image_path"]
    assert old_image.read_bytes() == new_image.read_bytes(), "Crop differs"
    new_image.resolve().relative_to(target.resolve())
    assert old_segment_id in old_cache and "luna" in old_cache[old_segment_id]
    new_cache[segment["segment_id"]] = old_cache[old_segment_id]

(target / "caption_cache.json").write_text(json.dumps(new_cache, indent=2), encoding="utf-8")
generated, cached, _ = caption_segments_file(target / "segments.json")
assert generated == 0
matched, missed, _ = extract_document_directory(new_id, target)
assert missed == 0
(target / "reuse_receipt.json").write_text(json.dumps({
    "reused_from": str(source.relative_to(root)),
    "source_pdf_sha256": checksum,
    "verified_identical_crops": cached,
    "reused_caption_aliases": ["luna"],
    "caption_model_snapshots": "Inherited cache; exact historical snapshot not recorded",
    "mineru_version": metadata["mineru_version"],
    "backend": metadata["backend"],
}, indent=2), encoding="utf-8")
# Fingerprint is written last; an interrupted reuse cannot pass ingest checks.
(target / "source_sha256.txt").write_text(checksum + "\n", encoding="utf-8")
print(f"Reused {len(segments)} segments, {cached} captions, {matched} bboxes; no API calls.")
