"""Offline regression tests for collection ingestion and cross-document retrieval."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import pymupdf
import tiktoken

import scripts._test_env  # noqa: F401  pins providers; must precede project imports
from api.models import ChatRequest
from api import server
from scripts import agent, linked_retrieval, query
from scripts.collect_stm32 import inspect_pdf
from scripts.embed_and_index import IndexRecord, write_indexes
from scripts import embed_and_index, ingest_collection, parse, smoke_collection
from scripts.usage_budget import BudgetExceeded, UsageBudget, api_budget


class CollectionSelectionTests(unittest.TestCase):
    def setUp(self):
        self.hits = [
            {"doc": doc, "segment_id": str(index), "score": score}
            for index, (doc, score) in enumerate([
                ("manual", .9), ("manual", .89), ("manual", .88),
                ("datasheet", .8), ("errata", .7), ("unrelated", .1),
            ])
        ]

    def test_long_manual_does_not_take_every_slot(self):
        selected = linked_retrieval.select_diverse_hits(self.hits, 3, set())
        self.assertEqual([hit["doc"] for hit in selected], ["manual", "datasheet", "errata"])

    def test_named_document_is_not_crowded_out(self):
        selected = linked_retrieval.select_diverse_hits(self.hits, 2, {"errata"})
        self.assertEqual(selected[0]["doc"], "errata")
        self.assertEqual(len({h["segment_id"] for h in selected}), 2)

    def test_does_not_force_low_relevance_document(self):
        selected = linked_retrieval.select_diverse_hits(self.hits, 4, set())
        self.assertNotIn("unrelated", [hit["doc"] for hit in selected])

    def test_named_comparisons_keep_detail_not_only_introductions(self):
        hits = [
            {"doc": doc, "segment_id": f"{doc}-{part}", "score": score}
            for part, score in [("intro", .8), ("detail", .7), ("extra", .6)]
            for doc in ["manual", "emulation", "updater", "other-a", "other-b", "other-c"]
        ]
        selected = linked_retrieval.select_diverse_hits(hits, 8, {"manual", "emulation", "updater"})
        selected_ids = {hit["segment_id"] for hit in selected}
        for doc in ("manual", "emulation", "updater"):
            self.assertIn(f"{doc}-intro", selected_ids)
            self.assertIn(f"{doc}-detail", selected_ids)
        self.assertEqual(len(selected), 8)

    def test_discovered_reference_does_not_get_explicit_document_detail_priority(self):
        selected = linked_retrieval.select_diverse_hits(self.hits, 3, set(), {"manual"})
        self.assertEqual({hit["doc"] for hit in selected}, {"manual", "datasheet", "errata"})

    def test_small_and_empty_corpora(self):
        self.assertEqual(linked_retrieval.select_diverse_hits([], 5, set()), [])
        self.assertEqual(len(linked_retrieval.select_diverse_hits(self.hits[:1], 5, set())), 1)

    def test_navigation_does_not_displace_technical_sources(self):
        hits = [
            {"text_or_caption": "Contents\n1.1 Timer configuration 8"},
            {"text_or_caption": "**Table 5. Document revision history**\nI2C issue added"},
            {"text_or_caption": "Timer configuration\nUse the update event as TRGO."},
        ]
        self.assertEqual(linked_retrieval.filter_navigation_hits(hits, "Configure timers"), hits[2:])
        self.assertEqual(linked_retrieval.filter_navigation_hits(hits, "Show revision history"), hits)

    def test_continued_contents_without_heading_is_detected(self):
        contents = "\n".join(f"15.4.{i} Timer register {i + 400}" for i in range(1, 8))
        self.assertTrue(linked_retrieval.is_navigation_text(contents))
        self.assertFalse(linked_retrieval.is_navigation_text("See Section 15.4.1 for details.\nTimer clock = 72 MHz"))

    def test_technical_table_is_not_navigation(self):
        self.assertFalse(linked_retrieval.is_navigation_text("## Table 22. HSE oscillator characteristics\n| Frequency | 4 | 16 | MHz |"))
        self.assertEqual(linked_retrieval.filter_navigation_hits([], "timer"), [])

    def test_real_faiss_filters_visuals_in_baseline(self):
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            records = [
                IndexRecord("a", "a", "manual", 1, "text", "ADC reference manual"),
                IndexRecord("b", "b", "datasheet", 2, "text", "ADC electrical limits"),
                IndexRecord("c", "c", "manual", 3, "figure", "ADC diagram", "unused.png", "luna"),
            ]
            vectors = np.array([[1, 0], [.8, .6], [.9, .4358899]], dtype="float32")
            write_indexes(records, vectors, 2, folder)
            with patch.object(query, "embed_text", return_value=[1, 0]):
                text_hits = linked_retrieval.retrieve_collection("ADC", "text_only", 5, folder)
                visual_hits = linked_retrieval.retrieve_collection("ADC", "mrag", 5, folder)
            self.assertEqual({h["type"] for h in text_hits}, {"text"})
            self.assertEqual(len(text_hits), 2)
            self.assertEqual(len(visual_hits), 3)
            self.assertEqual({h["doc"] for h in text_hits}, {"manual", "datasheet"})
            query._load_metadata.cache_clear()

    def test_named_document_survives_router_rewriting(self):
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            records = [
                IndexRecord("a", "a", "manual", 1, "text", "Flash manual"),
                IndexRecord("b", "b", "note", 2, "text", "EEPROM emulation"),
            ]
            write_indexes(records, np.array([[1, 0], [.5, .8660254]], dtype="float32"), 2, folder)
            (folder / "document_manifest.json").write_text(json.dumps({"documents": [
                {"doc_id": "manual", "document_id": "PM0075"},
                {"doc_id": "note", "document_id": "AN2594"},
            ]}), encoding="utf-8")
            with patch.object(query, "embed_text", return_value=[1, 0]) as embed:
                hits = linked_retrieval.retrieve_collection(
                    "Flash storage", "text_only", 1, folder, reference_query="Explain AN2594"
                )
            self.assertEqual(hits[0]["doc"], "note")
            embed.assert_called_once_with("Flash storage")
            query._load_metadata.cache_clear()


class CollectionRoutingTests(unittest.TestCase):
    def test_page_count_includes_blank_final_pdf_pages(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "manual"
            directory.mkdir()
            (directory / "segments.json").write_text(json.dumps([
                {"type": "text", "page": 1, "text": "Manual"},
            ]), encoding="utf-8")
            pdf_path = root / "manual.pdf"
            with pymupdf.open() as pdf:
                pdf.new_page()
                pdf.new_page()
                pdf.save(pdf_path)
            with patch.object(server, "_safe_raw_pdf_path", return_value=pdf_path):
                stats = server._document_stats(
                    SimpleNamespace(doc_id="manual", title="Manual"),
                    SimpleNamespace(parsed_dir=root), {},
                )
            self.assertEqual(stats["pages"], 2)

    def test_router_only_sees_selected_collection(self):
        with patch.object(agent, "generate", return_value='{"route":"datasheet","search_query":"ADC"}') as generation:
            agent.route_question("ADC", available_document_titles=["RM0008", "DS5319"])
        prompt = generation.call_args.args[0]
        self.assertIn("RM0008", prompt)
        self.assertNotIn("ESP32", prompt)

    def test_collection_scope_does_not_filter_to_anchor_document(self):
        corpus = SimpleNamespace(
            index_dir=Path("collection-index"),
            documents=[SimpleNamespace(title="manual"), SimpleNamespace(title="errata")],
        )
        state = SimpleNamespace(bboxes={}, models=server.ModelNames("embedding", "answer", "router"))
        decision = agent.RouterDecision("datasheet", "ADC", 1, "test")
        with patch.object(server, "corpus_for_document", return_value=corpus), \
             patch.object(server, "route_question", return_value=decision) as route, \
             patch.object(server, "gather_evidence", return_value=agent.Evidence()) as retrieve, \
             patch.object(server, "answer_stream", return_value=iter(["Not verified"])):
            frames = list(server._chat_events(ChatRequest(message="ADC", mode="mrag", doc="manual", scope="collection"), state))
        self.assertIsNone(route.call_args.kwargs["document"])
        self.assertIsNone(retrieve.call_args.kwargs["docs"])
        self.assertTrue(retrieve.call_args.kwargs["collection"])
        self.assertEqual(retrieve.call_args.kwargs["index_dir"], corpus.index_dir)
        self.assertEqual(retrieve.call_args.kwargs["reference_query"], "ADC")
        self.assertIn('"type":"done"', frames[-1])

    def test_request_defaults_preserve_document_mode(self):
        self.assertEqual(ChatRequest(message="ADC", mode="mrag").scope, "document")
        with self.assertRaises(ValueError):
            ChatRequest(message="ADC", mode="mrag", k=1000)


class DownloadValidationTests(unittest.TestCase):
    def test_pdf_with_temporary_extension_is_validated(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "manual.pdf.part"
            pdf = pymupdf.open()
            page = pdf.new_page()
            page.insert_text((40, 40), "RM0008 Rev 21\nSee AN2586")
            path.write_bytes(pdf.tobytes())
            pdf.close()
            result = inspect_pdf(path, "RM0008")
            self.assertEqual(result["pages"], 1)
            self.assertEqual(result["revision"], "21")
            self.assertEqual(result["references"], {"AN2586": [1]})
            with self.assertRaises(ValueError):
                inspect_pdf(path, "ES096")


class ParseHandoffTests(unittest.TestCase):
    def test_transient_windows_lock_retries_handoff_not_mineru(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "data/raw/stm32"
            raw.mkdir(parents=True)
            source = raw / "manual.pdf"
            source.write_bytes(b"test input; MinerU is mocked")
            output = root / "data/parsed/stm32"
            original_replace = Path.replace
            handoffs = []

            def temporary_lock(path, destination):
                handoffs.append((path, destination))
                if len(handoffs) == 1:
                    raise PermissionError("Temporary Windows file handle")
                return original_replace(path, destination)

            with patch.object(parse, "PROJECT_ROOT", root), \
                 patch.object(parse, "mineru_version", return_value="3.4.5"), \
                 patch.object(parse, "run_mineru") as mineru, \
                 patch.object(parse, "_finalize_parse", return_value=([], "pipeline")), \
                 patch.object(parse.time, "sleep") as sleep, \
                 patch.object(Path, "replace", temporary_lock):
                parse.parse_pdf(source, output_root=output, raw_root=raw, try_vlm=False)
            mineru.assert_called_once()
            sleep.assert_called_once_with(1)
            self.assertEqual(len(handoffs), 2)
            self.assertTrue((output / "manual/mineru").is_dir())

    def test_reset_rejects_paths_outside_parsed_artifacts(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "keep.txt").write_text("not a parsed artifact")
            with self.assertRaises(ValueError):
                parse._reset_directory(directory)
            self.assertTrue((directory / "keep.txt").exists())


class BatchedEmbeddingTests(unittest.TestCase):
    def test_long_inputs_are_lossless_and_token_bounded(self):
        encoding = tiktoken.get_encoding("cl100k_base")
        for text in ("1234567890," * 10000, "GPIO\U0001f9ea\u4f60\u597d\u2192\u00b5A " * 3500):
            parts = embed_and_index.split_embedding_text(text)
            self.assertGreater(len(parts), 1)
            self.assertEqual("".join(parts), text)
            for part in parts:
                self.assertLessEqual(len(encoding.encode(part)), embed_and_index.MAX_EMBEDDING_TOKENS)

    def test_normal_captions_keep_cache_identity_and_long_captions_keep_source(self):
        long_caption = "pin 123 output 456 input 789; " * 1500
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "segments.json"
            path.write_text(json.dumps([
                {"segment_id": "text", "doc": "manual", "page": 1, "type": "text", "text": "Flash memory"},
                {"segment_id": "short", "doc": "manual", "page": 2, "type": "figure", "caption": "Pinout", "caption_model": "luna", "image_path": "short.png"},
                {"segment_id": "long", "doc": "manual", "page": 3, "type": "table", "caption": long_caption, "caption_model": "luna", "image_path": "long.png"},
            ]), encoding="utf-8")
            records, text_count = embed_and_index.collect_records([path])
        self.assertEqual(text_count, 1)
        self.assertEqual(records[1].cache_key, "short:caption")
        self.assertIsNone(records[1].source_segment_id)
        self.assertEqual("".join(record.text_or_caption for record in records[2:]), long_caption.strip())
        self.assertGreater(len(records[2:]), 1)
        self.assertEqual(len({record.segment_id for record in records}), len(records))
        for record in records[2:]:
            self.assertEqual(record.metadata(0)["source_segment_id"], "long")
            self.assertEqual((record.doc, record.page, record.image_path), ("manual", 3, "long.png"))

    def test_split_caption_uses_original_source_bbox(self):
        evidence = agent.Evidence(segments=[{
            "segment_id": "table-caption-part-001", "source_segment_id": "table",
            "doc": "manual", "page": 3, "type": "table", "text_or_caption": "Flash timing",
        }])
        result = server._evidence_payload(evidence, {"table": {"page": 3, "bbox": [.1, .2, .8, .9]}})
        self.assertEqual(result["segments"][0]["bbox"], [.1, .2, .8, .9])

    def test_cache_reuse_does_not_call_provider_and_preserves_order(self):
        records = [IndexRecord(str(i), str(i), "doc", 1, "text", f"text {i}") for i in range(35)]
        with TemporaryDirectory() as temporary:
            cache = Path(temporary) / "cache.jsonl"
            with patch.object(embed_and_index, "embed_text", side_effect=lambda texts: [[1.0, .5] for _ in texts]) as embed:
                first, generated, cached = embed_and_index.embed_records(records, cache)
                second, generated_again, cached_again = embed_and_index.embed_records(records, cache)
            self.assertEqual(embed.call_count, 2)
            self.assertEqual((generated, cached), (35, 0))
            self.assertEqual((generated_again, cached_again), (0, 35))
            np.testing.assert_equal(first, second)


class UsagePersistenceTests(unittest.TestCase):
    def test_unreported_calls_remain_reserved_on_restart(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "usage.json"
            budget = UsageBudget(path, .3)
            row = budget.reserve("luna", "deployment", "caption", 1)
            reopened = UsageBudget(path, .3)
            self.assertGreater(reopened.spent, .2)
            with self.assertRaises(BudgetExceeded):
                reopened.reserve("luna", "deployment", "caption", 1)
            budget.settle(row, SimpleNamespace(prompt_tokens=100, completion_tokens=100), "model-snapshot")
            self.assertAlmostEqual(UsageBudget(path, .3).spent, .00014)

    def test_nested_writer_cannot_open_same_ledger(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "usage.json"
            with api_budget(path):
                with self.assertRaises(OSError):
                    with api_budget(path):
                        pass


class CollectionPublicationTests(unittest.TestCase):
    def test_publish_requires_complete_aligned_indexes_and_preserves_other_corpora(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            index = root / "index"
            documents = [{"doc_id": f"doc-{i}", "document_id": f"AN{i}", "title": f"Note {i}"} for i in range(20)]
            original_registry = {"corpora": [{"corpus_id": "hardware", "preserve": "unchanged"}]}
            registry = root / "corpora.json"
            registry.write_text(json.dumps(original_registry), encoding="utf-8")
            records = [IndexRecord(d["doc_id"], d["doc_id"], d["doc_id"], 1, "text", "Content") for d in documents]
            with patch.object(ingest_collection, "ROOT", root), patch.object(ingest_collection, "INDEX", index):
                with self.assertRaises(OSError):
                    ingest_collection.register_collection(documents)
                write_indexes(records[:-1], np.tile([1., 0.], (19, 1)).astype("float32"), 19, index)
                with self.assertRaisesRegex(ValueError, "every selected document"):
                    ingest_collection.register_collection(documents)
                self.assertEqual(json.loads(registry.read_text(encoding="utf-8")), original_registry)
                write_indexes(records, np.tile([1., 0.], (20, 1)).astype("float32"), 20, index)
                ingest_collection.register_collection(documents)
                result = json.loads(registry.read_text(encoding="utf-8"))
                self.assertEqual(result["corpora"][0], original_registry["corpora"][0])
                self.assertEqual(len(result["corpora"][1]["documents"]), 20)
                self.assertEqual(len(smoke_collection.validate_index(index)), 20)
                with self.assertRaisesRegex(ValueError, "already registered"):
                    ingest_collection.register_collection(documents)


if __name__ == "__main__":
    unittest.main()
