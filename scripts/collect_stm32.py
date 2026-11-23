"""Download and audit a fixed, provenance-tracked STM32 reading collection.

This does not parse with MinerU, call Azure, or register unfinished indexes.
Mirrors are explicit in the catalog and never described as manufacturer hosts.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from urllib.parse import urlparse

import httpx
import pymupdf


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "collections" / "stm32.json"
RAW = ROOT / "data" / "raw" / "stm32"
MAX_BYTES = 100 * 1024 * 1024


def inspect_pdf(path: Path, identity: str) -> dict:
    """Require a readable ST document with the expected identifier on its cover."""
    with pymupdf.open(path, filetype="pdf") as pdf:
        if pdf.needs_pass or not len(pdf):
            raise ValueError("Empty or encrypted PDF")
        cover = pdf[0].get_text()
        if not re.search(rf"\b{re.escape(identity)}\b", cover, re.IGNORECASE):
            raise ValueError(f"Cover does not identify {identity}")
        references: dict[str, list[int]] = {}
        for number, page in enumerate(pdf, start=1):
            for referenced_id in set(re.findall(r"\b(?:AN|RM|PM|ES|DS)\d{3,6}\b", page.get_text())):
                if referenced_id != identity:
                    references.setdefault(referenced_id, []).append(number)
        return {
            "pages": len(pdf),
            "revision": (re.search(r"\bRev(?:ision)?\.?\s*(\d+)", cover, re.IGNORECASE).group(1)
                         if re.search(r"\bRev(?:ision)?\.?\s*(\d+)", cover, re.IGNORECASE) else "not extracted"),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "cover_text": cover,
            "references": references,
        }


def collect_one(document: dict, output_root: Path = RAW) -> dict:
    doc_id = document["doc_id"]
    if not re.fullmatch(r"[a-z0-9-]+", doc_id):
        raise ValueError(f"Invalid document ID: {doc_id}")
    destination = output_root / f"{doc_id}.pdf"
    receipt = output_root / f"{doc_id}.source.json"
    result = dict(document)
    errors = []
    if destination.exists():
        # Unreceipted or changed files must not acquire invented provenance.
        if not receipt.exists():
            return {**result, "status": "blocked", "errors": ["Existing PDF has no source receipt"]}
        try:
            saved = json.loads(receipt.read_text(encoding="utf-8"))
            inspected = inspect_pdf(destination, document["document_id"])
            if saved["sha256"] != inspected["sha256"]:
                raise ValueError("PDF checksum differs from its source receipt")
            return {**saved, **result, **inspected, "status": "downloaded"}
        except (OSError, ValueError, KeyError) as exc:
            return {**result, "status": "blocked", "errors": [str(exc)]}

    output_root.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".pdf.part")
    sources = document.get("download_urls", [])
    if document.get("existing_path"):
        sources = [document["existing_path"], *sources]
    for source in sources:
        try:
            if not source.startswith("https://"):
                local = (ROOT / source).resolve()
                local.relative_to(ROOT / "data" / "raw")
                shutil.copyfile(local, temporary)
                host_kind = "existing_repository_file"
            else:
                with httpx.stream("GET", source, follow_redirects=True, timeout=20) as response:
                    response.raise_for_status()
                    size = 0
                    with temporary.open("wb") as output:
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > MAX_BYTES:
                                raise ValueError("PDF exceeds the 100 MiB collection limit")
                            output.write(chunk)
                hostname = urlparse(source).hostname or ""
                host_kind = "manufacturer" if hostname in {"www.st.com", "www.st.com.cn"} else "mirror"
            inspection = inspect_pdf(temporary, document["document_id"])
            result.update(inspection)
            result.update(
                status="downloaded", retrieved_from=source, source_kind=host_kind,
                retrieved_at=datetime.now(timezone.utc).isoformat(),
                path=destination.relative_to(ROOT).as_posix(),
            )
            temporary.replace(destination)
            receipt.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(f"{document['document_id']}: {inspection['pages']} pages ({host_kind})", flush=True)
            return result
        except (OSError, ValueError, httpx.HTTPError, RuntimeError) as exc:
            errors.append(f"{source}: {type(exc).__name__}: {exc}")
        finally:
            temporary.unlink(missing_ok=True)
    return {**result, "status": "unavailable", "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=4)
    args = parser.parse_args()
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    documents = catalog["documents"]
    if len({d["doc_id"] for d in documents}) != len(documents):
        raise ValueError("Duplicate catalog document IDs")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(collect_one, documents))
    report = {"corpus_id": "stm32", "documents": results}
    downloaded = [d for d in results if d["status"] == "downloaded"]
    if len({d["sha256"] for d in downloaded}) != len(downloaded):
        raise ValueError("Collection contains duplicate PDF contents")
    report["downloaded"] = len(downloaded)
    report["total_pages"] = sum(d["pages"] for d in downloaded)
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Collected {len(downloaded)}/{len(documents)} documents, {report['total_pages']} pages.")
    return 0 if len(downloaded) == len(documents) else 1


if __name__ == "__main__":
    raise SystemExit(main())
