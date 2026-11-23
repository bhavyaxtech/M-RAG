"""Resume RM0008 using one MinerU process instead of reloading per page batch."""

import argparse
import json
import time

import pymupdf

from scripts.ingest_collection import PARSED, RAW, parse_document, validated_documents
from scripts.parse import MinerUError, _read_content_list, _reset_directory, find_content_list


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    document = next(d for d in validated_documents() if d["doc_id"] == "stm32-rm0008")
    pdf_path = RAW / f"{document['doc_id']}.pdf"
    directory = PARSED / document["doc_id"]
    fingerprint = directory / "source_sha256.txt"
    if fingerprint.read_text(encoding="utf-8").strip() != document["sha256"]:
        raise ValueError("Source fingerprint mismatch")
    if (directory / "segments.json").exists():
        print("RM0008 is already finalized; nothing to parse.")
        return
    with pymupdf.open(pdf_path) as pdf:
        page_count = pdf.page_count
    batch_root = directory / "_mineru_work/page_batches_pipeline"
    pending = []
    for start in range(0, page_count, 10):
        end = min(start + 10, page_count) - 1
        batch = batch_root / f"pages_{start + 1:04d}_{end + 1:04d}"
        try:
            content = find_content_list(batch, pdf_path.stem)
            items = _read_content_list(content)
            if any(not isinstance(item.get("page_idx"), int) or not 0 <= item["page_idx"] <= end - start for item in items):
                raise MinerUError("Incomplete/invalid batch content")
        except MinerUError:
            pending.append((start, end, batch))
    print(json.dumps({"completed_batches": 114 - len(pending), "remaining_batches": len(pending), "backend": "MinerU full pipeline; models reused in one process"}), flush=True)
    if not args.execute:
        return

    # This is the same public MinerU API used by its CLI, with identical OCR,
    # formula, table, language, and page-range options. It retains model caches
    # between calls while still processing just ten pages at a time.
    from mineru.cli.common import do_parse
    pdf_bytes = pdf_path.read_bytes()
    for start, end, batch in pending:
        _reset_directory(batch)
        started = time.perf_counter()
        print(f"Parsing RM0008 pages {start + 1}-{end + 1} (persistent models)", flush=True)
        do_parse(
            str(batch), [pdf_path.stem], [pdf_bytes], ["en"],
            backend="pipeline", parse_method="auto", formula_enable=True,
            table_enable=True, start_page_id=start, end_page_id=end,
        )
        _read_content_list(find_content_list(batch, pdf_path.stem))
        print(f"Completed pages {start + 1}-{end + 1} in {time.perf_counter() - started:.1f}s", flush=True)
    # Reuse the existing merge/normalization/publication contract. Every batch
    # above is already cached, so this performs no additional model inference.
    parse_document(document, 10)


if __name__ == "__main__":
    main()
