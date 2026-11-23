"""Offline tests for bounded parallel captioning and its shared budget."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, BrokenBarrierError, Event, Lock
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import scripts._test_env  # noqa: F401  pins providers; must precede project imports
from scripts import caption
from scripts.usage_budget import BudgetExceeded, CURRENT_BUDGET, UsageBudget


class CaptionConcurrencyTests(unittest.TestCase):
    def _segments_file(
        self,
        temporary: str,
        count: int,
    ) -> tuple[Path, list[str]]:
        document_dir = Path(temporary) / "parsed" / "test-doc"
        document_dir.mkdir(parents=True)
        segments = []
        segment_ids = []
        for index in range(count):
            segment_id = f"test-doc-p{index + 1:04d}-figure-00001"
            image_path = document_dir / f"visual-{index:03d}.png"
            image_path.write_bytes(b"not-read-by-mocked-azure")
            segment_ids.append(segment_id)
            segments.append(
                {
                    "segment_id": segment_id,
                    "doc": "test-doc",
                    "page": index + 1,
                    "type": "figure",
                    "image_path": str(image_path),
                }
            )
        segments_path = document_dir / "segments.json"
        segments_path.write_text(json.dumps(segments), encoding="utf-8")
        return segments_path, segment_ids

    def test_caption_requests_run_in_parallel_and_remain_bounded(self):
        with TemporaryDirectory() as temporary:
            segments_path, _ = self._segments_file(temporary, 6)
            rendezvous = Barrier(3, timeout=1)
            state_lock = Lock()
            active = 0
            peak_active = 0

            def fake_generate(prompt, images=None, model="sol", **kwargs):
                nonlocal active, peak_active
                with state_lock:
                    active += 1
                    peak_active = max(peak_active, active)
                try:
                    try:
                        rendezvous.wait()
                    except BrokenBarrierError:
                        pass
                    time.sleep(0.02)
                    return f"caption for {Path(images[0]).stem}"
                finally:
                    with state_lock:
                        active -= 1

            with patch.object(caption, "generate", side_effect=fake_generate):
                generated, cached, _ = caption.caption_segments_file(
                    segments_path,
                    workers=3,
                )

            self.assertEqual((generated, cached), (6, 0))
            self.assertEqual(peak_active, 3)

    def test_each_future_receives_the_current_budget_context(self):
        with TemporaryDirectory() as temporary:
            segments_path, _ = self._segments_file(temporary, 4)
            sentinel_budget = object()
            observed_budgets = []
            observed_lock = Lock()

            def fake_generate(prompt, images=None, model="sol", **kwargs):
                with observed_lock:
                    observed_budgets.append(CURRENT_BUDGET.get())
                return f"caption for {Path(images[0]).stem}"

            token = CURRENT_BUDGET.set(sentinel_budget)
            try:
                with patch.object(caption, "generate", side_effect=fake_generate):
                    caption.caption_segments_file(segments_path, workers=2)
            finally:
                CURRENT_BUDGET.reset(token)

            self.assertEqual(len(observed_budgets), 4)
            self.assertTrue(
                all(budget is sentinel_budget for budget in observed_budgets)
            )

    def test_rerun_reuses_cache_without_azure_calls_and_preserves_order(self):
        with TemporaryDirectory() as temporary:
            segments_path, segment_ids = self._segments_file(temporary, 5)

            def fake_generate(prompt, images=None, model="sol", **kwargs):
                return f"caption for {Path(images[0]).stem}"

            with patch.object(caption, "generate", side_effect=fake_generate) as generate:
                first = caption.caption_segments_file(segments_path, workers=4)
            with patch.object(
                caption,
                "generate",
                side_effect=AssertionError("cached captions must not call Azure"),
            ) as generate_again:
                second = caption.caption_segments_file(segments_path, workers=4)

            self.assertEqual(first[:2], (5, 0))
            self.assertEqual(second[:2], (0, 5))
            self.assertEqual(generate.call_count, 5)
            self.assertEqual(generate_again.call_count, 0)
            saved_segments = json.loads(segments_path.read_text(encoding="utf-8"))
            self.assertEqual(
                [segment["segment_id"] for segment in saved_segments],
                segment_ids,
            )
            self.assertTrue(all(segment.get("caption_model") == "luna" for segment in saved_segments))

    def test_first_failure_stops_scheduling_and_successes_are_checkpointed(self):
        class ExpectedCaptionFailure(RuntimeError):
            pass

        with TemporaryDirectory() as temporary:
            segments_path, segment_ids = self._segments_file(temporary, 5)
            first_started = Event()
            failure_started = Event()
            calls = []
            calls_lock = Lock()

            def fake_generate(prompt, images=None, model="sol", **kwargs):
                image_name = Path(images[0]).stem
                with calls_lock:
                    calls.append(image_name)
                if image_name == "visual-000":
                    first_started.set()
                    failure_started.wait(timeout=2)
                    time.sleep(0.1)
                    return "first caption completed after the failure"
                if image_name == "visual-001":
                    first_started.wait(timeout=2)
                    failure_started.set()
                    raise ExpectedCaptionFailure("intentional caption failure")
                raise AssertionError("new work was scheduled after the first failure")

            with patch.object(caption, "generate", side_effect=fake_generate):
                with self.assertRaisesRegex(
                    ExpectedCaptionFailure,
                    "intentional caption failure",
                ):
                    caption.caption_segments_file(segments_path, workers=2)

            self.assertCountEqual(calls, ["visual-000", "visual-001"])
            cache = json.loads(
                (segments_path.parent / caption.CAPTION_CACHE_FILENAME).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(set(cache), {segment_ids[0]})
            saved_segments = json.loads(segments_path.read_text(encoding="utf-8"))
            self.assertEqual(
                saved_segments[0]["caption"],
                "first caption completed after the failure",
            )
            self.assertTrue(
                all("caption" not in segment for segment in saved_segments[1:])
            )

    def test_worker_count_must_be_an_integer_from_one_through_four(self):
        with TemporaryDirectory() as temporary:
            segments_path, _ = self._segments_file(temporary, 1)
            for workers in (0, 5, True, 1.0):
                with self.subTest(workers=workers):
                    with self.assertRaisesRegex(ValueError, "1 through 4"):
                        caption.caption_segments_file(segments_path, workers=workers)


class UsageBudgetConcurrencyTests(unittest.TestCase):
    def test_concurrent_reservations_cannot_exceed_the_budget(self):
        with TemporaryDirectory() as temporary:
            ledger_path = Path(temporary) / "usage.json"
            budget = UsageBudget(ledger_path, 0.30)
            start = Barrier(8, timeout=2)

            def reserve_once(_):
                start.wait()
                try:
                    budget.reserve("luna", "deployment", "caption", image_count=1)
                    return "reserved"
                except BudgetExceeded:
                    return "blocked"

            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(reserve_once, range(8)))

            self.assertEqual(results.count("reserved"), 1)
            self.assertEqual(results.count("blocked"), 7)
            saved = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["calls"]), 1)
            self.assertLessEqual(saved["estimated_spent_usd"], budget.limit)
            self.assertEqual(saved["estimated_spent_usd"], budget.spent)

    def test_concurrent_reserve_and_settle_persists_complete_ledger(self):
        with TemporaryDirectory() as temporary:
            ledger_path = Path(temporary) / "usage.json"
            budget = UsageBudget(ledger_path, 30)
            settle_start = Barrier(8, timeout=2)

            def reserve_and_settle(index):
                row = budget.reserve(
                    "luna",
                    "deployment",
                    f"caption {index}",
                    image_count=1,
                )
                settle_start.wait()
                budget.settle(
                    row,
                    SimpleNamespace(
                        prompt_tokens=100 + index,
                        completion_tokens=20 + index,
                    ),
                    f"snapshot-{index}",
                )

            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(reserve_and_settle, range(8)))

            saved = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["calls"]), 8)
            self.assertTrue(
                all(row["status"] == "usage_reported" for row in saved["calls"])
            )
            self.assertEqual(
                {row["response_model"] for row in saved["calls"]},
                {f"snapshot-{index}" for index in range(8)},
            )
            expected_spent = sum(
                row["charged_estimate_usd"] for row in saved["calls"]
            )
            self.assertAlmostEqual(saved["estimated_spent_usd"], expected_spent)
            self.assertAlmostEqual(budget.spent, expected_spent)


if __name__ == "__main__":
    unittest.main()
