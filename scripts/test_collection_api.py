"""Offline API regressions for collection-scoped, cross-document retrieval.

Run with: python -m unittest scripts.test_collection_api -v

The fixtures deliberately use real registry parsing, FAISS indexes, PDF files,
and the API's SSE event generator. Azure embedding, routing, and generation
are replaced only at their provider boundaries.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import pymupdf

import scripts._test_env  # noqa: F401  pins providers; must precede project imports
from api import server
from api.models import ChatRequest
from scripts import agent, corpus, query
from scripts.embed_and_index import IndexRecord, write_indexes


class CollectionApiIntegrationTests(unittest.TestCase):
    """Exercise the API transport through the real collection retrieval path."""

    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(query._load_metadata.cache_clear)
        self.addCleanup(corpus.load_registry.cache_clear)

        self.hardware_raw = self.root / "raw" / "hardware"
        self.hardware_parsed = self.root / "parsed" / "hardware"
        self.hardware_index = self.root / "index" / "hardware"
        self.other_raw = self.root / "raw" / "other"
        self.other_parsed = self.root / "parsed" / "other"
        self.other_index = self.root / "index" / "other"
        for directory in (
            self.hardware_raw,
            self.hardware_parsed,
            self.other_raw,
            self.other_parsed,
        ):
            directory.mkdir(parents=True)

        self.anchor_pdf = self.hardware_raw / "anchor.pdf"
        self.sibling_pdf = self.hardware_raw / "sibling.pdf"
        self.unrelated_pdf = self.other_raw / "unrelated.pdf"
        self._write_pdf(self.anchor_pdf, "Anchor source", blank_trailing_page=True)
        self._write_pdf(self.sibling_pdf, "Sibling source")
        self._write_pdf(self.unrelated_pdf, "Unrelated source")

        self.sibling_crop = self.hardware_parsed / "sibling" / "images" / "table.png"
        self._write_crop(self.sibling_crop)
        self._write_parsed_artifacts()
        self._write_indexes()
        self._write_registry()

        self.registry_patch = patch.object(corpus, "REGISTRY_PATH", self.root / "corpora.json")
        self.registry_patch.start()
        self.addCleanup(self.registry_patch.stop)
        corpus.load_registry.cache_clear()

    @staticmethod
    def _write_pdf(path: Path, text: str, blank_trailing_page: bool = False) -> None:
        pdf = pymupdf.open()
        page = pdf.new_page()
        page.insert_text((72, 72), text)
        if blank_trailing_page:
            pdf.new_page()
        pdf.save(path)
        pdf.close()

    @staticmethod
    def _write_crop(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        pdf = pymupdf.open()
        page = pdf.new_page()
        page.insert_text((20, 20), "Sibling table crop")
        page.get_pixmap().save(path)
        pdf.close()

    def _write_parsed_artifacts(self) -> None:
        for doc_id, parsed_root, segments in (
            (
                "anchor",
                self.hardware_parsed,
                [{"segment_id": "anchor-text", "doc": "anchor", "page": 1, "type": "text", "text": "Anchor-only evidence."}],
            ),
            (
                "sibling",
                self.hardware_parsed,
                [
                    {"segment_id": "sibling-text", "doc": "sibling", "page": 1, "type": "text", "text": "Shared collection evidence."},
                    {
                        "segment_id": "sibling-table",
                        "doc": "sibling",
                        "page": 1,
                        "type": "table",
                        "caption": "A table in the sibling source.",
                        "caption_model": "luna",
                        "image_path": str(self.sibling_crop),
                    },
                ],
            ),
            (
                "unrelated",
                self.other_parsed,
                [{"segment_id": "unrelated-text", "doc": "unrelated", "page": 1, "type": "text", "text": "Must never leak into hardware."}],
            ),
        ):
            document_dir = parsed_root / doc_id
            document_dir.mkdir(parents=True, exist_ok=True)
            (document_dir / "segments.json").write_text(json.dumps(segments), encoding="utf-8")

        (self.hardware_parsed / "sibling" / "bboxes.json").write_text(
            json.dumps({"sibling-table": {"page": 1, "bbox": [0.1, 0.2, 0.7, 0.8]}}),
            encoding="utf-8",
        )

    def _write_indexes(self) -> None:
        hardware_records = [
            IndexRecord("anchor-text", "anchor-text", "anchor", 1, "text", "Anchor-only evidence."),
            IndexRecord("sibling-text", "sibling-text", "sibling", 1, "text", "Shared collection evidence."),
            IndexRecord(
                "sibling-table-caption-part-000",
                "sibling-table-caption-part-000",
                "sibling",
                1,
                "table",
                "A table in the sibling source.",
                str(self.sibling_crop),
                "luna",
                "sibling-table",
            ),
        ]
        write_indexes(
            hardware_records,
            np.array([[0.0, 1.0], [1.0, 0.0], [0.98, 0.2]], dtype="float32"),
            text_record_count=2,
            output_dir=self.hardware_index,
        )
        write_indexes(
            [IndexRecord("unrelated-text", "unrelated-text", "unrelated", 1, "text", "Must never leak into hardware.")],
            np.array([[1.0, 0.0]], dtype="float32"),
            text_record_count=1,
            output_dir=self.other_index,
        )

    def _write_registry(self) -> None:
        payload = {
            "corpora": [
                {
                    "corpus_id": "hardware",
                    "title": "Hardware collection",
                    "blurb": "Two related PDFs",
                    "evaluated": True,
                    "index_dir": str(self.hardware_index),
                    "parsed_dir": str(self.hardware_parsed),
                    "raw_dir": str(self.hardware_raw),
                    "documents": [
                        {"doc_id": "anchor", "title": "Anchor Manual"},
                        {"doc_id": "sibling", "title": "Sibling Datasheet"},
                    ],
                },
                {
                    "corpus_id": "other",
                    "title": "Unrelated collection",
                    "blurb": "Must not be searched",
                    "evaluated": False,
                    "index_dir": str(self.other_index),
                    "parsed_dir": str(self.other_parsed),
                    "raw_dir": str(self.other_raw),
                    "documents": [{"doc_id": "unrelated", "title": "Unrelated PDF"}],
                },
            ]
        }
        (self.root / "corpora.json").write_text(json.dumps(payload), encoding="utf-8")

    @staticmethod
    def _events(frames: list[str]) -> list[dict[str, object]]:
        return [json.loads(frame.removeprefix("data: ").strip()) for frame in frames]

    def _startup_state(self) -> server.StartupState:
        return server._load_startup_state()

    def test_collection_scope_retrieves_sibling_evidence_and_uses_sibling_assets(self) -> None:
        decision = agent.RouterDecision("datasheet", "shared source", 1.0, "fixture")
        with patch.object(query, "embed_text", return_value=[1.0, 0.0]), \
             patch.object(server, "route_question", return_value=decision), \
             patch.object(agent, "generate_stream", return_value=iter(["Sibling answer [S1]"])):
            state = self._startup_state()
            events = self._events(list(server._chat_events(
                ChatRequest(message="Show the shared table", mode="mrag", doc="anchor", scope="collection", k=3),
                state,
            )))

        evidence = next(event for event in events if event["type"] == "evidence")
        segments = evidence["segments"]
        self.assertTrue(any(segment["doc"] == "sibling" for segment in segments))
        self.assertNotIn("unrelated", {segment["doc"] for segment in segments})
        table = next(segment for segment in segments if segment["type"] == "table")
        self.assertEqual(table["page_url"], "/api/page/sibling/1")
        self.assertEqual(table["image_url"], "/api/image/sibling-table-caption-part-000")
        self.assertEqual(table["bbox"], [0.1, 0.2, 0.7, 0.8])

        image_response = server.image(
            str(table["segment_id"]),
            SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(startup=state))),
        )
        self.assertEqual(Path(image_response.path).resolve(), self.sibling_crop.resolve())
        self.assertEqual(server._safe_raw_pdf_path("sibling"), self.sibling_pdf.resolve())

        hardware_meta = next(corpus_meta for corpus_meta in state.meta["corpora"] if corpus_meta["corpus_id"] == "hardware")
        anchor_meta = next(document for document in hardware_meta["documents"] if document["doc_id"] == "anchor")
        self.assertEqual(anchor_meta["pages"], 2, "the blank physical trailing page must be counted")
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["answer"], "Sibling answer [S1]")

    def test_document_scope_stays_on_anchor_and_stream_failures_emit_error_not_done(self) -> None:
        decision = agent.RouterDecision("datasheet", "shared source", 1.0, "fixture")
        with patch.object(query, "embed_text", return_value=[1.0, 0.0]), \
             patch.object(server, "route_question", return_value=decision), \
             patch.object(agent, "generate_stream", side_effect=RuntimeError("offline generation failure")):
            events = self._events(list(server._chat_events(
                ChatRequest(message="Show the shared table", mode="mrag", doc="anchor", scope="document", k=3),
                self._startup_state(),
            )))

        evidence = next(event for event in events if event["type"] == "evidence")
        self.assertEqual({segment["doc"] for segment in evidence["segments"]}, {"anchor"})
        self.assertEqual(events[-1], {"type": "error", "message": "offline generation failure"})
        self.assertNotIn("done", {event["type"] for event in events})


if __name__ == "__main__":
    unittest.main()
