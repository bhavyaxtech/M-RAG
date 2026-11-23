"""Offline tests for progressive preparation of completed MinerU batches."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import fitz

import scripts._test_env  # noqa: F401  pins providers; must precede project imports
from scripts import caption, embed_and_index, parse, prepare_batches


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class PrepareBatchesTests(unittest.TestCase):
    def _workspace(
        self,
        temporary: str,
        page_count: int = 4,
        blank_pages: set[int] | None = None,
    ):
        root = Path(temporary)
        pdf_path = root / "data/raw/stm32/stm32-rm0008.pdf"
        pdf_path.parent.mkdir(parents=True)
        with fitz.open() as document:
            for page_number in range(page_count):
                page = document.new_page(width=200, height=200)
                if page_number + 1 not in (blank_pages or set()):
                    page.insert_text((20, 20), f"Page {page_number + 1}")
            document.save(pdf_path)
        doc_dir = root / "data/parsed/stm32/stm32-rm0008"
        doc_dir.mkdir(parents=True)
        fingerprint = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        fingerprint_path = doc_dir / "source_sha256.txt"
        fingerprint_path.write_text(fingerprint + "\n", encoding="utf-8")
        return root, pdf_path, doc_dir, fingerprint_path

    def _batch(self, doc_dir: Path, start: int, end: int, items) -> Path:
        path = (
            doc_dir
            / "_mineru_work/page_batches_pipeline"
            / f"pages_{start:04d}_{end:04d}"
            / "stm32-rm0008/auto/stm32-rm0008_content_list.json"
        )
        _write_json(path, items)
        return path

    def _middle(self, content_list_path: Path, page_indices: list[int]) -> Path:
        middle_path = content_list_path.with_name("stm32-rm0008_middle.json")
        _write_json(
            middle_path,
            {
                "pdf_info": [
                    {
                        "page_idx": page_idx,
                        "page_size": [200, 200],
                        "para_blocks": [],
                        "discarded_blocks": [],
                    }
                    for page_idx in page_indices
                ],
                "_backend": "pipeline",
                "_version_name": "test",
            },
        )
        return middle_path

    def test_page_offsets_and_ids_match_final_normalization(self):
        with TemporaryDirectory() as temporary:
            root, pdf_path, doc_dir, _ = self._workspace(temporary)
            self._batch(doc_dir, 1, 2, [
                {"type": "text", "text": "first", "page_idx": 0},
                {"type": "image", "bbox": [100, 100, 500, 500], "page_idx": 1},
            ])
            self._batch(doc_dir, 3, 4, [
                {"type": "text", "text": "third", "page_idx": 0},
                {"type": "table", "bbox": [200, 200, 800, 800], "page_idx": 1},
            ])
            batches, rejected = prepare_batches.discover_completed_batches(doc_dir, 4)
            self.assertEqual(rejected, [])
            merged = prepare_batches.merge_batch_items(batches)
            final_content = root / "data/parsed/stm32/stm32-rm0008/mineru/final.json"
            _write_json(final_content, merged)
            with patch.object(parse, "PROJECT_ROOT", root):
                progressive_path, progressive = prepare_batches.prepare_progressive_segments(
                    batches, pdf_path, "stm32-rm0008", doc_dir / "progressive"
                )
                final = parse.normalize_segments(final_content, "stm32-rm0008", pdf_path)
            self.assertTrue(progressive_path.is_file())
            self.assertEqual(
                [(row["segment_id"], row["page"], row["type"]) for row in progressive],
                [(row["segment_id"], row["page"], row["type"]) for row in final],
            )
            self.assertEqual(
                [row["segment_id"] for row in progressive],
                [
                    "stm32-rm0008-p0001-text-00001",
                    "stm32-rm0008-p0002-figure-00001",
                    "stm32-rm0008-p0003-text-00002",
                    "stm32-rm0008-p0004-table-00001",
                ],
            )

    def test_progressive_crop_is_byte_identical_to_final_bbox_crop(self):
        with TemporaryDirectory() as temporary:
            root, pdf_path, doc_dir, _ = self._workspace(temporary, page_count=1)
            item = {"type": "image", "bbox": [100, 100, 900, 900], "page_idx": 0}
            self._batch(doc_dir, 1, 1, [item])
            batches, _ = prepare_batches.discover_completed_batches(doc_dir, 1)
            final_content = root / "data/parsed/stm32/stm32-rm0008/mineru/final.json"
            _write_json(final_content, [item])
            with patch.object(parse, "PROJECT_ROOT", root):
                _, progressive = prepare_batches.prepare_progressive_segments(
                    batches, pdf_path, "stm32-rm0008", doc_dir / "progressive"
                )
                final = parse.normalize_segments(final_content, "stm32-rm0008", pdf_path)
            progressive_crop = root / progressive[0]["image_path"]
            final_crop = root / final[0]["image_path"]
            self.assertEqual(progressive_crop.read_bytes(), final_crop.read_bytes())

    def test_partial_batch_is_not_included_in_contiguous_prefix(self):
        with TemporaryDirectory() as temporary:
            _, _, doc_dir, _ = self._workspace(temporary)
            self._batch(doc_dir, 1, 2, [
                {"type": "text", "text": "page one", "page_idx": 0},
                {"type": "text", "text": "page two", "page_idx": 1},
            ])
            self._batch(doc_dir, 3, 4, [
                {"type": "text", "text": "only page three", "page_idx": 0},
            ])
            batches, rejected = prepare_batches.discover_completed_batches(doc_dir, 4)
            self.assertEqual([(batch.start_page, batch.end_page) for batch in batches], [(1, 2)])
            self.assertEqual(rejected, ["pages_0003_0004"])

    def test_blank_page_is_accepted_when_middle_proves_full_batch(self):
        with TemporaryDirectory() as temporary:
            _, _, doc_dir, _ = self._workspace(
                temporary,
                page_count=3,
                blank_pages={2},
            )
            content_list = self._batch(doc_dir, 1, 3, [
                {"type": "text", "text": "page one", "page_idx": 0},
                {"type": "text", "text": "page three", "page_idx": 2},
            ])
            self._middle(content_list, [0, 1, 2])
            batches, rejected = prepare_batches.discover_completed_batches(doc_dir, 3)
            self.assertEqual(rejected, [])
            self.assertEqual([(batch.start_page, batch.end_page) for batch in batches], [(1, 3)])

    def test_missing_content_page_is_rejected_when_middle_is_incomplete(self):
        with TemporaryDirectory() as temporary:
            _, _, doc_dir, _ = self._workspace(temporary, page_count=3)
            content_list = self._batch(doc_dir, 1, 3, [
                {"type": "text", "text": "page one", "page_idx": 0},
                {"type": "text", "text": "page three", "page_idx": 2},
            ])
            self._middle(content_list, [0, 2])
            batches, rejected = prepare_batches.discover_completed_batches(doc_dir, 3)
            self.assertEqual(batches, [])
            self.assertEqual(rejected, ["pages_0001_0003"])

    def test_batch_discovery_retries_after_parser_handoff(self):
        with TemporaryDirectory() as temporary:
            _, _, doc_dir, _ = self._workspace(temporary, page_count=1)
            self._batch(doc_dir, 1, 1, [
                {"type": "text", "text": "complete", "page_idx": 0},
            ])
            original_read = prepare_batches._read_stable_content_list
            calls = 0

            def handoff_during_read(batch_dir):
                nonlocal calls
                calls += 1
                if calls == 1:
                    (doc_dir / "_mineru_work").replace(doc_dir / "mineru")
                    return None
                return original_read(batch_dir)

            with patch.object(
                prepare_batches,
                "_read_stable_content_list",
                side_effect=handoff_during_read,
            ):
                batches, rejected = prepare_batches.discover_completed_batches(doc_dir, 1)
            self.assertEqual(rejected, [])
            self.assertEqual([(batch.start_page, batch.end_page) for batch in batches], [(1, 1)])
            self.assertEqual(calls, 2)

    def test_resume_reuses_caption_and_embedding_caches_without_provider_calls(self):
        with TemporaryDirectory() as temporary:
            root, pdf_path, doc_dir, fingerprint_path = self._workspace(
                temporary, page_count=1
            )
            self._batch(doc_dir, 1, 1, [
                {"type": "text", "text": "ADC configuration register", "page_idx": 0},
                {"type": "table", "bbox": [100, 100, 900, 900], "page_idx": 0},
            ])
            index_dir = root / "index/stm32"
            ledger = root / "output/stm32/azure_usage.json"
            with patch.object(parse, "PROJECT_ROOT", root), \
                 patch.object(caption, "PROJECT_ROOT", root), \
                 patch.object(caption, "generate", return_value="ADC table caption") as generate, \
                 patch.object(
                     embed_and_index,
                     "embed_text",
                     side_effect=lambda texts: [[1.0, 0.5] for _ in texts],
                 ) as embed:
                first = prepare_batches.execute_preparation(
                    pdf_path=pdf_path,
                    doc_dir=doc_dir,
                    fingerprint_path=fingerprint_path,
                    index_dir=index_dir,
                    ledger_path=ledger,
                )
                second = prepare_batches.execute_preparation(
                    pdf_path=pdf_path,
                    doc_dir=doc_dir,
                    fingerprint_path=fingerprint_path,
                    index_dir=index_dir,
                    ledger_path=ledger,
                )
            self.assertEqual(generate.call_count, 1)
            self.assertEqual(embed.call_count, 1)
            self.assertEqual((first["generated_captions"], first["generated_embeddings"]), (1, 2))
            self.assertEqual((second["generated_captions"], second["generated_embeddings"]), (0, 0))
            canonical_cache = json.loads(
                (doc_dir / "caption_cache.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                canonical_cache["stm32-rm0008-p0001-table-00001"]["luna"],
                "ADC table caption",
            )

    def test_ledger_lock_is_acquired_before_progressive_writes(self):
        with TemporaryDirectory() as temporary:
            root, pdf_path, doc_dir, fingerprint_path = self._workspace(
                temporary, page_count=1
            )
            self._batch(doc_dir, 1, 1, [
                {"type": "text", "text": "complete", "page_idx": 0},
            ])
            progressive_segments = doc_dir / "progressive/segments.json"
            progressive_segments.parent.mkdir(parents=True)
            sentinel = b'{"owned_by":"first worker"}\n'
            progressive_segments.write_bytes(sentinel)
            ledger = root / "output/stm32/azure_usage.json"

            with prepare_batches.api_budget(ledger):
                with self.assertRaises(OSError):
                    prepare_batches.execute_preparation(
                        pdf_path=pdf_path,
                        doc_dir=doc_dir,
                        fingerprint_path=fingerprint_path,
                        index_dir=root / "index/stm32",
                        ledger_path=ledger,
                    )

            self.assertEqual(progressive_segments.read_bytes(), sentinel)
            self.assertFalse((doc_dir / "caption_cache.json").exists())
            self.assertFalse((root / "index/stm32/embedding_cache.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
