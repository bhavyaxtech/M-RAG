"""Check the published collection's real local HTTP assets without model calls."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

from scripts.corpus import get_corpus


ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "http://127.0.0.1:8012"
REPORT = ROOT / "output/stm32/app_verification.json"


def fetch(path):
    with urlopen(BASE_URL + path, timeout=60) as response:
        if response.status != 200:
            raise RuntimeError(f"Unexpected HTTP status for {path}: {response.status}")
        return response.read(), response.headers.get_content_type()


def main():
    corpus = get_corpus("stm32")
    manifest = json.loads((corpus.index_dir / "document_manifest.json").read_text(encoding="utf-8"))
    expected = {document["doc_id"]: document["pages"] for document in manifest["documents"]}
    if len(expected) != 20:
        raise RuntimeError("Only the complete 20-document collection may be verified")
    metadata, _ = fetch("/api/meta")
    remote = next(item for item in json.loads(metadata)["corpora"] if item["corpus_id"] == "stm32")
    actual = {document["doc_id"]: document["pages"] for document in remote["documents"]}
    if actual != expected:
        raise RuntimeError("The running API has stale or mismatched documents/page counts")
    if any(document["text_vectors"] <= 0 for document in remote["documents"]):
        raise RuntimeError("An API document has no text vectors")
    health, _ = fetch("/api/health")
    if not json.loads(health)["indexes_ready"]:
        raise RuntimeError("The running API reports indexes unavailable")
    html, content_type = fetch("/")
    if content_type != "text/html" or b"<html" not in html.lower():
        raise RuntimeError("The built frontend was not served")

    checked_pages = []
    for doc_id, page_count in expected.items():
        for page in sorted({1, page_count}):
            path = f"/api/page/{quote(doc_id, safe='')}/{page}"
            data, content_type = fetch(path)
            if content_type != "image/png" or not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise RuntimeError(f"Page viewer returned an invalid PNG: {path}")
            checked_pages.append(path)

    rows = [json.loads(line) for line in (corpus.index_dir / "metadata.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    visual_samples = {}
    visual_count = 0
    for row in rows:
        if row["type"] not in {"figure", "table"}:
            continue
        image_path = Path(row["image_path"])
        image_path = (ROOT / image_path).resolve() if not image_path.is_absolute() else image_path.resolve()
        image_path.relative_to(corpus.parsed_dir.resolve())
        if not image_path.is_file():
            raise RuntimeError(f"Missing indexed crop: {image_path}")
        visual_count += 1
        visual_samples.setdefault(row["doc"], (row["segment_id"], image_path))
    checked_crops = []
    for doc_id, (segment_id, image_path) in visual_samples.items():
        data, _ = fetch(f"/api/image/{quote(segment_id, safe='')}")
        if hashlib.sha256(data).digest() != hashlib.sha256(image_path.read_bytes()).digest():
            raise RuntimeError(f"The API served the wrong source crop: {segment_id}")
        checked_crops.append({"doc": doc_id, "segment_id": segment_id})
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "base_url": BASE_URL,
        "documents": len(expected),
        "physical_pages": sum(expected.values()),
        "frontend_served": True,
        "checked_page_urls": checked_pages,
        "indexed_visual_rows_with_existing_crops": visual_count,
        "byte_verified_http_crops": checked_crops,
        "model_calls": 0,
        "verification_scope": "HTTP transport and source-asset integrity; not visual QA or answer accuracy",
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"API verified: {len(expected)} documents, {len(checked_pages)} page URLs, {len(checked_crops)} exact crops.")


if __name__ == "__main__":
    main()
