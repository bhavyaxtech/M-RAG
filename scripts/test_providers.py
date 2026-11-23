"""Offline tests for the local-embedding and Codex provider branches.

Run with: python -m unittest scripts.test_providers -v
"""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import scripts._test_env  # noqa: F401  pins providers; must precede project imports
from scripts import agent, azure_client, config


def _completed(events: list[dict], returncode: int = 0, stderr: bytes = b"") -> subprocess.CompletedProcess:
    stdout = "\n".join(json.dumps(event) for event in events).encode("utf-8")
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _message(text: str) -> dict:
    return {"type": "item.completed", "item": {"type": "agent_message", "text": text}}


class CodexAnswerTests(unittest.TestCase):
    def test_returns_last_agent_message(self):
        result = _completed([
            {"type": "thread.started"},
            _message("Checking."),
            _message("Final answer [S1]"),
            {"type": "turn.completed"},
        ])
        self.assertEqual(azure_client._codex_answer(result), "Final answer [S1]")

    def test_metadata_warning_items_are_not_failures(self):
        result = _completed([
            {"type": "item.completed", "item": {"type": "error", "message": "Model metadata not found"}},
            _message("ok"),
        ])
        self.assertEqual(azure_client._codex_answer(result), "ok")

    def test_error_event_raises_with_its_message(self):
        result = _completed([{"type": "error", "message": "model not supported"}], returncode=1)
        with self.assertRaisesRegex(RuntimeError, "model not supported"):
            azure_client._codex_answer(result)

    def test_nonzero_exit_without_events_surfaces_stderr(self):
        result = _completed([], returncode=2, stderr=b"not logged in")
        with self.assertRaisesRegex(RuntimeError, "not logged in"):
            azure_client._codex_answer(result)

    def test_empty_response_raises(self):
        with self.assertRaisesRegex(RuntimeError, "empty response"):
            azure_client._codex_answer(_completed([{"type": "turn.completed"}]))


class CodexGenerateTests(unittest.TestCase):
    def setUp(self):
        self.capabilities = (
            frozenset({"--ephemeral", "--ignore-user-config"}),
            frozenset({"apps", "memories"}),
        )
        for name, value in (
            ("llm_provider", "codex"),
            ("resolved_codex_model", "test-model"),
            ("codex_command", ["codex"]),
        ):
            patcher = patch.object(azure_client, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        capabilities = patch.object(azure_client, "codex_capabilities", side_effect=lambda: self.capabilities)
        capabilities.start()
        self.addCleanup(capabilities.stop)

    def _run(self, **kwargs):
        captured = {}

        def fake_run(command, **run_kwargs):
            workdir = Path(command[command.index("-C") + 1])
            captured["instructions"] = (workdir / "instructions.md").read_text(encoding="utf-8")
            captured["command"] = command
            captured["input"] = run_kwargs["input"]
            return _completed([_message("answer")])

        with patch.object(azure_client.subprocess, "run", side_effect=fake_run):
            chunks = list(azure_client.generate_stream("Question?", **kwargs))
        return chunks, captured

    def test_stream_yields_one_chunk_and_passes_instructions_as_system_prompt(self):
        chunks, captured = self._run(instructions="Cite [S1].", model="sol")
        self.assertEqual(chunks, ["answer"])
        self.assertEqual(captured["instructions"], "Cite [S1].")
        self.assertEqual(captured["input"], b"Question?")
        command = captured["command"]
        self.assertIn("--ignore-user-config", command)
        self.assertEqual(command[command.index("-s") + 1], "read-only")
        self.assertEqual(command[command.index("-m") + 1], "test-model")
        self.assertIn("model_reasoning_effort=medium", command)
        self.assertEqual(command[-1], "-")

    def test_router_tier_uses_low_effort_and_images_become_file_flags(self):
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
            image = handle.name
        self.addCleanup(Path(image).unlink)
        _, captured = self._run(model="luna", images=[image])
        command = captured["command"]
        self.assertIn("model_reasoning_effort=low", command)
        self.assertEqual(command[command.index("-i") + 1], str(Path(image).resolve()))

    def test_only_flags_and_features_this_cli_supports_are_passed(self):
        _, captured = self._run()
        command = captured["command"]
        self.assertIn("--ignore-user-config", command)
        self.assertNotIn("--ignore-rules", command)
        disabled = {command[i + 1] for i, part in enumerate(command) if part == "--disable"}
        self.assertEqual(disabled, {"apps", "memories"})

    def test_unresolved_model_lets_codex_pick_the_account_default(self):
        with patch.object(azure_client, "resolved_codex_model", return_value=None):
            _, captured = self._run()
        self.assertNotIn("-m", captured["command"])

    def test_missing_image_fails_before_spawning(self):
        with patch.object(azure_client.subprocess, "run") as run:
            with self.assertRaises(FileNotFoundError):
                azure_client.generate("Q", images=["does-not-exist.png"])
        run.assert_not_called()


class LocalEmbeddingTests(unittest.TestCase):
    def test_local_provider_skips_azure_and_keeps_batch_shape(self):
        with patch.object(azure_client, "embed_provider", return_value="local"), \
             patch.object(azure_client, "_local_embed", return_value=[[1.0, 0.0], [0.0, 1.0]]) as local, \
             patch.object(azure_client, "_client") as client:
            self.assertEqual(azure_client.embed_text(["a", "b"]), [[1.0, 0.0], [0.0, 1.0]])
            local.return_value = [[0.5, 0.5]]
            self.assertEqual(azure_client.embed_text("a"), [0.5, 0.5])
        client.assert_not_called()


class ConfigTests(unittest.TestCase):
    def test_local_embeddings_use_a_separate_index_dir(self):
        with patch.object(config, "embed_provider", return_value="local"):
            self.assertEqual(config.active_index_dir(Path("index")), Path("index") / "local")
        with patch.object(config, "embed_provider", return_value="azure"):
            self.assertEqual(config.active_index_dir(Path("index")), Path("index"))

    def test_codex_label_does_not_need_azure_settings(self):
        with patch.object(config, "llm_provider", return_value="codex"), \
             patch.object(config, "resolved_codex_model", return_value="m"), \
             patch.object(config, "get_settings", side_effect=RuntimeError("no azure")):
            self.assertEqual(config.generation_deployment_name("luna"), "codex:m")

    def test_model_comes_from_the_account_catalog_when_not_configured(self):
        catalog = json.dumps({"models": [
            {"slug": "hidden", "visibility": "hide", "priority": 0},
            {"slug": "second", "visibility": "list", "priority": 2},
            {"slug": "first", "visibility": "list", "priority": 1},
        ]})
        config.resolved_codex_model.cache_clear()
        self.addCleanup(config.resolved_codex_model.cache_clear)
        with patch.dict(config.os.environ, {"CODEX_MODEL": ""}), \
             patch.object(config, "_codex_output", return_value=catalog):
            self.assertEqual(config.resolved_codex_model(), "first")
        config.resolved_codex_model.cache_clear()
        with patch.dict(config.os.environ, {"CODEX_MODEL": ""}), \
             patch.object(config, "_codex_output", return_value="not json"):
            self.assertIsNone(config.resolved_codex_model())

    def test_capabilities_parse_help_and_feature_list(self):
        outputs = {
            ("exec", "--help"): "  --ephemeral  Run without persisting\n  --json\n",
            ("features", "list"): "apps  stable  true\nmemories  stable  true\n",
        }
        config.codex_capabilities.cache_clear()
        self.addCleanup(config.codex_capabilities.cache_clear)
        with patch.object(config, "_codex_output", side_effect=lambda *args: outputs[args]):
            flags, features = config.codex_capabilities()
        self.assertEqual(flags, frozenset({"--ephemeral"}))
        self.assertEqual(features, frozenset({"apps", "memories"}))

    def test_uncalibrated_embedder_has_no_relevance_floor(self):
        with patch.object(agent, "embedding_model_name", return_value="unknown/model"):
            with self.assertRaisesRegex(RuntimeError, "No calibrated relevance floor"):
                agent._relevance_floor()


if __name__ == "__main__":
    unittest.main()
