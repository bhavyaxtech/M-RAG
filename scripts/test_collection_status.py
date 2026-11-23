import json
from contextlib import redirect_stdout
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import scripts._test_env  # noqa: F401  pins providers; must precede project imports
from scripts.collection_status import _embedding_cache_count, _human_summary, _partial_pages, collect_status, main


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def make_manifest(root: Path, documents) -> None:
    write_json(root / "data/raw/stm32/manifest.json", {"documents": documents})


def make_batch(root: Path, doc_id: str, start: int, end: int, pages: list[int], *, nested: bool = False) -> None:
    base = root / "data/parsed/stm32" / doc_id
    if nested:
        base = base / "mineru"
    path = base / "page_batches_pipeline" / f"pages_{start:04d}_{end:04d}" / doc_id / "auto" / f"{doc_id}_content_list.json"
    write_json(path, [{"page_idx": page - start} for page in pages])


class CollectionStatusTests(unittest.TestCase):
    def test_blank_fixture_has_no_artifacts(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_manifest(root, [{"doc_id": "a", "title": "A", "pages": 10}])
            report = collect_status(root)
            self.assertEqual((report["finalized_documents"], report["finalized_pages"]), (0, 0))
            self.assertFalse(report["indexed"])
            self.assertFalse(report["published"])

    def test_partial_pages_are_contiguous_and_trailing_batch_is_ignored(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_manifest(root, [{"doc_id": "a", "title": "A", "pages": 20}])
            make_batch(root, "a", 1, 10, list(range(1, 11)))
            make_batch(root, "a", 11, 20, [11, 12, 13])
            report = collect_status(root)
            self.assertEqual(report["partial_documents"][0]["pages"], 10)

    def test_middle_json_page_proof_counts_blank_pages_in_completed_batch(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_manifest(root, [{"doc_id": "a", "title": "A", "pages": 3}])
            make_batch(root, "a", 1, 3, [1, 3])
            middle = root / "data/parsed/stm32/a/page_batches_pipeline/pages_0001_0003/a/auto/a_middle.json"
            write_json(middle, {"pdf_info": [{"page_idx": 0}, {"page_idx": 1}, {"page_idx": 2}]})
            report = collect_status(root)
            self.assertEqual(report["partial_documents"][0]["pages"], 3)

    def test_invalid_middle_page_sequence_cannot_prove_blank_page_completion(self):
        for indices in ([0, 2], [0, 1, 1, 2], [0, True, 2], [1, 2, 3]):
            with self.subTest(indices=indices), TemporaryDirectory() as temporary:
                root = Path(temporary)
                make_manifest(root, [{"doc_id": "a", "pages": 3}])
                make_batch(root, "a", 1, 3, [1, 3])
                middle = root / "data/parsed/stm32/a/page_batches_pipeline/pages_0001_0003/a/auto/a_middle.json"
                write_json(middle, {"pdf_info": [{"page_idx": index} for index in indices]})
                self.assertEqual(collect_status(root)["partial_documents"][0]["pages"], 0)

    def test_progressive_captions_are_reported_without_double_counting(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_manifest(root, [{"doc_id": "a", "pages": 3}])
            parsed = root / "data/parsed/stm32/a"
            segments = [{"segment_id": "fig", "type": "figure", "page": 1}]
            for directory in (parsed, parsed / "progressive"):
                write_json(directory / "segments.json", segments)
                write_json(directory / "caption_cache.json", {"fig": {"luna": "caption"}})
            report = collect_status(root)
            self.assertEqual(report["cached_visual_captions"], 1)
            self.assertEqual(report["progressive_documents"], [{
                "doc_id": "a", "cached_visual_captions": 1, "visual_segments": 1,
            }])
            self.assertIn("may overlap finalized counts", _human_summary(report))

    def test_finalized_document_does_not_double_count_partial_work(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_manifest(root, [{"doc_id": "a", "title": "A", "pages": 20}, {"doc_id": "b", "title": "B", "pages": 5}])
            parsed = root / "data/parsed/stm32/a"
            write_json(parsed / "segments.json", [{"segment_id": "fig", "type": "figure", "page": 1}])
            write_json(parsed / "caption_cache.json", {"fig": {"luna": "caption"}})
            make_batch(root, "a", 1, 10, list(range(1, 11)))
            report = collect_status(root)
            self.assertEqual(report["finalized_pages"], 20)
            self.assertEqual(report["partial_documents"], [])
            self.assertEqual((report["cached_visual_captions"], report["finalized_visual_segments"]), (1, 1))

    def test_published_requires_registry_entry_and_faiss_files(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_manifest(root, [])
            write_json(root / "corpora.json", {"corpora": [{"corpus_id": "stm32"}]})
            report = collect_status(root)
            self.assertTrue(report["published"])
            self.assertFalse(report["indexed"])

    def test_largest_remaining_includes_not_started_documents(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_manifest(root, [
                {"doc_id": "started", "title": "Started", "pages": 10},
                {"doc_id": "not-started", "title": "Not started", "pages": 100},
            ])
            make_batch(root, "started", 1, 10, list(range(1, 6)))
            report = collect_status(root)
            self.assertEqual(report["largest_remaining_pdf"]["doc_id"], "not-started")
            self.assertEqual(report["largest_remaining_pdf"]["remaining_pages"], 100)

    def test_missing_caption_cache_is_zero_progress_not_uncertainty(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_manifest(root, [{"doc_id": "a", "title": "A", "pages": 2}])
            write_json(root / "data/parsed/stm32/a/segments.json", [{"segment_id": "fig", "type": "figure"}])
            report = collect_status(root)
            self.assertEqual((report["cached_visual_captions"], report["finalized_visual_segments"]), (0, 1))
            self.assertEqual(report["uncertainties"], [])

    def test_filesystem_race_is_reported_without_crashing(self):
        with TemporaryDirectory() as temporary:
            with patch.object(Path, "rglob", side_effect=OSError("directory replaced")):
                pages, uncertain = _partial_pages(Path(temporary))
            self.assertEqual(pages, 0)
            self.assertTrue(uncertain)

    def test_embedding_cache_keeps_prior_valid_entries_and_rejects_bad_keys_and_bools(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "embedding_cache.jsonl"
            path.write_text(
                json.dumps({"cache_key": "ok", "embedding": [0.1, 0.2]}) + "\n"
                + json.dumps({"cache_key": [], "embedding": [0.1]}) + "\n"
                + json.dumps({"cache_key": "bool", "embedding": [True]}) + "\n"
                + '{"cache_key": "unfinished"',
                encoding="utf-8",
            )
            count, warning = _embedding_cache_count(path)
            self.assertEqual(count, 1)
            self.assertIn("incomplete", warning)

    def test_human_warning_keeps_checked_at_and_counts(self):
        text = _human_summary({
            "checked_at": "2026-09-08T00:00:00+00:00",
            "status": "uncertain",
            "finalized_documents": 1,
            "target_documents": 2,
            "finalized_pages": 3,
            "total_pages": 10,
            "cached_visual_captions": 0,
            "finalized_visual_segments": 2,
            "embedding_cache_entries": 1,
            "indexed": False,
            "published": False,
            "partial_documents": [],
            "largest_remaining_pdf": None,
            "uncertainties": ["transient read"],
        })
        self.assertIn("Checked at: 2026-09-08T00:00:00+00:00.", text)
        self.assertIn("1/2 documents", text)
        self.assertIn("3/10 finalized", text)
        self.assertIn("Uncertainty: transient read", text)

    def test_main_with_missing_manifest_reports_timestamp_and_uncertainty(self):
        with TemporaryDirectory() as temporary:
            output = io.StringIO()
            with redirect_stdout(output):
                result = main(["--root", temporary])
            text = output.getvalue()
            self.assertEqual(result, 0)
            self.assertIn("Checked at:", text)
            self.assertIn("Status uncertain:", text)
            self.assertIn("manifest.json", text)


if __name__ == "__main__":
    unittest.main()
