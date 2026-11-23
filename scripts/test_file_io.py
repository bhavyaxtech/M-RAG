"""Offline regressions for progress-reader/checkpoint-writer contention."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import scripts._test_env  # noqa: F401  pins providers; must precede project imports
from scripts import caption, file_io


class AtomicReplaceTests(unittest.TestCase):
    def test_temporary_lock_retries_only_publication(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "prepared.tmp", root / "saved.json"
            source.write_text('"new"', encoding="utf-8")
            destination.write_text('"old"', encoding="utf-8")
            original_replace = Path.replace
            attempts = 0

            def briefly_locked(path, target):
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    self.assertEqual(destination.read_text(), '"old"')
                    raise PermissionError("reader owns destination")
                return original_replace(path, target)

            with patch.object(Path, "replace", briefly_locked), patch.object(file_io.time, "sleep") as sleep:
                file_io.replace_with_retry(source, destination)
            self.assertEqual(attempts, 3)
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(destination.read_text(), '"new"')
            self.assertFalse(source.exists())

    def test_persistent_failure_is_bounded_and_other_errors_do_not_retry(self):
        for failure, expected_attempts in ((PermissionError("locked"), 8), (FileNotFoundError("missing"), 1)):
            with self.subTest(failure=type(failure).__name__):
                with patch.object(Path, "replace", side_effect=failure) as replace, patch.object(file_io.time, "sleep") as sleep:
                    with self.assertRaises(type(failure)):
                        file_io.replace_with_retry(Path("prepared.tmp"), Path("saved.json"))
                self.assertEqual(replace.call_count, expected_attempts)
                self.assertEqual(sleep.call_count, expected_attempts - 1)

    def test_caption_checkpoint_lock_does_not_regenerate_caption(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "figure.png"
            image.write_bytes(b"image is mocked")
            segments_path = root / "segments.json"
            segments_path.write_text(json.dumps([{
                "segment_id": "figure-1", "type": "figure", "doc": "test",
                "page": 1, "image_path": str(image),
            }]), encoding="utf-8")
            original_replace = Path.replace
            blocked_destinations = set()

            def briefly_locked(path, target):
                if target not in blocked_destinations:
                    blocked_destinations.add(target)
                    raise PermissionError("brief reader lock")
                return original_replace(path, target)

            with patch.object(Path, "replace", briefly_locked), patch.object(file_io.time, "sleep"), patch.object(caption, "generate", return_value="verified caption") as generate:
                result = caption.caption_segments_file(segments_path, workers=4)
            self.assertEqual(result[:2], (1, 0))
            self.assertEqual(generate.call_count, 1)
            self.assertEqual(json.loads(segments_path.read_text())[0]["caption"], "verified caption")


if __name__ == "__main__":
    unittest.main()
