"""Offline HTTP regressions for explicitly selected 20-PDF collection sessions.

Run with: python -B -m unittest scripts.test_collection_session_api -v
Temporary PDFs, a two-corpus registry, and real FAISS indexes exercise retrieval
and source serialization. Provider calls and startup configuration are mocked;
TestClient calls the ASGI app in-process without touching a running server.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import numpy as np
import pymupdf

import scripts._test_env  # noqa: F401  pins providers; must precede project imports
from api import server
from api.models import ChatRequest
from scripts import agent, corpus, query
from scripts.embed_and_index import IndexRecord, write_indexes


class CollectionSessionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.stm32_docs = [f"stm32-{number:02d}" for number in range(1, 21)]
        self.source_pages: dict[str, int] = {}
        registry = []
        for corpus_id, doc_ids in (
            ("hardware", ["hardware-source"]),
            ("stm32", self.stm32_docs),
        ):
            directory = self.root / corpus_id
            raw_dir = directory / "raw"
            parsed_dir = directory / "parsed"
            index_dir = directory / "index"
            raw_dir.mkdir(parents=True)
            parsed_dir.mkdir()
            records = []
            vectors = []
            documents = []
            for number, doc_id in enumerate(doc_ids):
                title = f"{corpus_id.upper()} source {number + 1:02d}"
                documents.append({"doc_id": doc_id, "title": title})
                page = number % 3 + 1
                self.source_pages[doc_id] = page
                with pymupdf.open() as pdf:
                    for page_number in range(1, 4):
                        pdf.new_page().insert_text((30, 30), f"{title} page {page_number}")
                    pdf.save(raw_dir / f"{doc_id}.pdf")
                    if corpus_id == "stm32" and number == 0:
                        self.crop = parsed_dir / "table.png"
                        pdf[1].get_pixmap().save(self.crop)
                records.append(IndexRecord(
                    f"{doc_id}-text", f"{doc_id}-text", doc_id, page,
                    "text", f"Electrical limits for {title}.",
                ))
                score = 0.99 - number * 0.01
                vectors.append([score, (1 - score ** 2) ** 0.5])
            if corpus_id == "stm32":
                self.stm32_titles = tuple(document["title"] for document in documents)
                records.append(IndexRecord(
                    "table-caption-part-000", "table-caption-part-000",
                    self.stm32_docs[0], 2, "table", "Electrical characteristics table.",
                    str(self.crop), "offline-caption", "table-source",
                ))
                vectors.append([1.0, 0.0])
            write_indexes(
                records, np.array(vectors, dtype="float32"), len(doc_ids), index_dir,
            )
            registry.append({
                "corpus_id": corpus_id,
                "title": f"{corpus_id.upper()} collection",
                "blurb": "Offline fixture",
                "evaluated": False,
                "index_dir": str(index_dir),
                "parsed_dir": str(parsed_dir),
                "raw_dir": str(raw_dir),
                "documents": documents,
            })
        registry_path = self.root / "corpora.json"
        registry_path.write_text(json.dumps({"corpora": registry}), encoding="utf-8")
        self._patch(corpus, "REGISTRY_PATH", registry_path)
        corpus.load_registry.cache_clear()
        self.addCleanup(corpus.load_registry.cache_clear)
        self.addCleanup(query._load_metadata.cache_clear)
        state = server.StartupState(
            meta={}, image_paths={"table-caption-part-000": self.crop},
            bboxes={"table-source": {"page": 2, "bbox": [0.1, 0.2, 0.8, 0.9]}},
            indexes_ready=True, models=server.ModelNames("embedding", "answer", "router"),
        )
        self.startup = self._patch(server, "_startup", return_value=state)
        self.embedding = self._patch(query, "embed_text", return_value=[1.0, 0.0])
        self.routing = self._patch(agent, "generate", return_value=json.dumps({
            "route": "datasheet", "search_query": "electrical limits",
            "confidence": 1.0, "reason": "offline fixture",
        }))
        self.generation = self._patch(
            agent, "generate_stream",
            side_effect=lambda *args, **kwargs: iter(["Limits [S1]", " and [S2]."]),
        )
        self.client = TestClient(server.app)
        self.addCleanup(self.client.close)

    def _patch(self, target, attribute, *args, **kwargs):
        patcher = patch.object(target, attribute, *args, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def _post(self, **selection):
        response = self.client.post("/api/chat", json={
            "message": "Compare electrical limits", "mode": "mrag", "k": 8,
            **selection,
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        events = [
            json.loads(frame.removeprefix("data: "))
            for frame in response.text.strip().split("\n\n")
        ]
        self.assertEqual(events[-1]["type"], "done", events)
        return events

    @staticmethod
    def _segments(events):
        return next(event["segments"] for event in events if event["type"] == "evidence")

    def test_request_corpus_id_is_optional(self) -> None:
        request = ChatRequest(message="Limits", mode="mrag")
        self.assertIsNone(request.corpus_id)
        self.assertEqual(request.scope, "document")
        self.assertEqual(
            ChatRequest(message="Limits", mode="mrag", corpus_id="stm32").corpus_id,
            "stm32",
        )

    def test_anchorless_collection_routes_all_titles_and_preserves_sources(self) -> None:
        history = [{"role": "user", "content": "Compare these STM32 documents."}]
        with patch.object(server, "route_question", wraps=agent.route_question) as route, \
             patch.object(server, "gather_evidence", wraps=agent.gather_evidence) as retrieve, \
             patch.object(server, "answer_stream", wraps=agent.answer_stream) as answer:
            events = self._post(doc=None, corpus_id="stm32", scope="collection", history=history)

        route.assert_called_once_with(
            "Compare electrical limits", history, document=None,
            available_document_titles=self.stm32_titles,
        )
        retrieve.assert_called_once_with(
            "electrical limits", "mrag", k=8, index_dir=self.root / "stm32" / "index",
            docs=None, page=None, collection=True, reference_query="Compare electrical limits",
        )
        self.assertIsNone(answer.call_args.kwargs["document"])
        self.assertEqual(answer.call_args.kwargs["available_document_titles"], self.stm32_titles)
        self.assertEqual(answer.call_args.args[4], history)
        for title in self.stm32_titles:
            self.assertIn(title, self.routing.call_args.args[0])
        self.assertNotIn("HARDWARE source", self.routing.call_args.args[0])
        segments = self._segments(events)
        self.assertEqual(len(segments), 8)
        self.assertEqual(len({segment["doc"] for segment in segments}), 8)
        self.assertLessEqual({segment["doc"] for segment in segments}, set(self.stm32_docs))
        for segment in segments:
            doc_id = segment["doc"]
            expected_page = 2 if segment["type"] == "table" else self.source_pages[doc_id]
            self.assertEqual(segment["page"], expected_page)
            self.assertEqual(segment["page_url"], f"/api/page/{doc_id}/{expected_page}")
            self.assertEqual(segment["doc_title"], corpus.get_document(doc_id).title)
            self.assertIn(f"{doc_id} page {expected_page}", self.generation.call_args.args[0])
        table = segments[0]
        self.assertEqual(table["type"], "table")
        self.assertEqual(table["image_url"], "/api/image/table-caption-part-000")
        self.assertEqual(table["bbox"], [0.1, 0.2, 0.8, 0.9])
        self.assertEqual(self.generation.call_args.kwargs["images"], [str(self.crop.resolve())])
        self.assertEqual(events[-1]["cited"], ["S1", "S2"])
        self.assertEqual(events[-1]["answer"], "Limits [S1] and [S2].")

    def test_anchorless_text_only_searches_all_twenty_documents(self) -> None:
        events = self._post(corpus_id="stm32", scope="collection", mode="text_only", k=20)
        segments = self._segments(events)
        self.assertEqual({segment["doc"] for segment in segments}, set(self.stm32_docs))
        self.assertEqual({segment["type"] for segment in segments}, {"text"})
        self.assertTrue(all(segment["image_url"] is None for segment in segments))
        self.assertIsNone(self.generation.call_args.kwargs["images"])

    def test_legacy_and_explicit_anchors_have_identical_collection_results(self) -> None:
        legacy = self._post(doc=self.stm32_docs[-1], scope="collection")
        explicit = self._post(doc=self.stm32_docs[-1], corpus_id="stm32", scope="collection")
        anchorless = self._post(corpus_id="stm32", scope="collection")
        self.assertEqual(self._segments(legacy), self._segments(explicit))
        self.assertEqual(self._segments(legacy), self._segments(anchorless))

    def test_document_requests_keep_the_anchor_filter(self) -> None:
        for mode in ("mrag", "text_only"):
            for corpus_id in (None, "stm32"):
                with self.subTest(mode=mode, corpus_id=corpus_id), \
                     patch.object(server, "gather_evidence", wraps=agent.gather_evidence) as retrieve, \
                     patch.object(server, "route_question", wraps=agent.route_question) as route:
                    events = self._post(doc=self.stm32_docs[-1], corpus_id=corpus_id, mode=mode)
                    self.assertEqual(
                        {segment["doc"] for segment in self._segments(events)}, {self.stm32_docs[-1]},
                    )
                    self.assertEqual(retrieve.call_args.kwargs["docs"], (self.stm32_docs[-1],))
                    self.assertFalse(retrieve.call_args.kwargs["collection"])
                    self.assertEqual(route.call_args.kwargs["document"], self.stm32_docs[-1])

    def test_legacy_without_selectors_keeps_the_default_corpus(self) -> None:
        for selection in ({}, {"doc": None, "corpus_id": None, "scope": "document"}):
            with self.subTest(selection=selection):
                events = self._post(**selection)
                self.assertEqual({segment["doc"] for segment in self._segments(events)}, {"hardware-source"})

    def test_invalid_selections_are_json_errors_before_streaming(self) -> None:
        cases = [
            ({"corpus_id": "missing", "scope": "collection"}, 404, "unknown corpus_id"),
            ({"corpus_id": "missing", "doc": "hardware-source"}, 404, "unknown corpus_id"),
            ({"corpus_id": "stm32", "doc": "missing"}, 404, "unknown doc"),
            ({"doc": "missing"}, 404, "unknown doc"),
            ({"corpus_id": "stm32", "doc": "hardware-source"}, 422, "doc does not belong"),
            ({"corpus_id": "hardware", "doc": self.stm32_docs[0], "scope": "collection"}, 422, "doc does not belong"),
            ({"corpus_id": "stm32"}, 422, "doc is required"),
            ({"corpus_id": "stm32", "doc": None, "scope": "document"}, 422, "doc is required"),
            ({"scope": "collection"}, 422, "corpus_id or doc is required"),
            ({"corpus_id": None, "doc": None, "scope": "collection"}, 422, "corpus_id or doc is required"),
        ]
        for invalid_id in ("", " ", " stm32", "STM32", "../stm32"):
            cases.append(({"corpus_id": invalid_id, "scope": "collection"}, 404, "unknown corpus_id"))
        for malformed in (42, True, [], {}):
            cases.append(({"corpus_id": malformed, "scope": "collection"}, 422, None))
        with patch.object(server, "_chat_events") as stream:
            for mode in ("mrag", "text_only", "plain"):
                for selection, status_code, detail in cases:
                    with self.subTest(mode=mode, selection=selection):
                        response = self.client.post("/api/chat", json={
                            "message": "Limits", "mode": mode, **selection,
                        })
                        self.assertEqual(response.status_code, status_code, response.text)
                        self.assertEqual(response.headers["content-type"], "application/json")
                        if detail is not None:
                            self.assertIn(detail, response.json()["detail"])
            stream.assert_not_called()
        self.startup.assert_not_called()
        self.routing.assert_not_called()
        self.embedding.assert_not_called()
        self.generation.assert_not_called()

    def test_plain_mode_still_skips_retrieval(self) -> None:
        for selection in ({}, {"corpus_id": "stm32", "scope": "collection"}):
            with self.subTest(selection=selection):
                events = self._post(mode="plain", **selection)
                self.assertNotIn("evidence", {event["type"] for event in events})
                self.assertEqual(events[-1]["provenance"], "plain")
        self.routing.assert_not_called()
        self.embedding.assert_not_called()


if __name__ == "__main__":
    unittest.main()
