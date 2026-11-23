"""Check that the configured providers actually work on this machine.

run.bat calls this before starting the server. Messages are written for a
non-technical reader. Exit code 0 means ready, 1 means a step failed.

    python -m scripts.preflight            # everything the .env selects
    python -m scripts.preflight --skip-embed
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid

import faiss

from scripts.azure_client import embed_text, generate
from scripts.config import (
    codex_capabilities,
    codex_command,
    embed_provider,
    llm_provider,
    local_embedding_model,
    resolved_codex_model,
)
from scripts.corpus import PROJECT_ROOT, load_registry
from scripts.embed_and_index import METADATA_FILENAME, MRAG_INDEX_FILENAME

CANARY_TOKEN = "MRAG-CANARY-OK"
CANARY_SEGMENT = "esp32-wroom-32e-32ue-p0010-figure-00005"
CANARY_EXPECTED = "TXD0"
CODEX_FIX = (
    "  Install or update it from a Command Prompt:\n"
    "    npm install -g @openai/codex@latest\n"
    "  (needs Node.js LTS from https://nodejs.org first)"
)


class PreflightError(RuntimeError):
    pass


def _say(message: str) -> None:
    print(f"  {message}", flush=True)


def check_files() -> None:
    """Crops sit up to 169 characters deep, so a long folder path makes ZIP
    extraction and git silently skip them on Windows (260-character limit)."""
    missing = 0
    for corpus in load_registry():
        metadata_path = corpus.index_dir / METADATA_FILENAME
        if not metadata_path.is_file():
            raise PreflightError(f"The search index is missing: {metadata_path}")
        for line in metadata_path.read_text(encoding="utf-8").splitlines():
            image_path = json.loads(line).get("image_path")
            if image_path and not (PROJECT_ROOT / image_path).is_file():
                missing += 1
    if missing:
        raise PreflightError(
            f"{missing} image files from the download are missing. This almost always means "
            f"the folder path is too long for Windows ({len(str(PROJECT_ROOT))} characters):\n"
            f"    {PROJECT_ROOT}\n"
            "  Move the project to a short folder such as C:\\Multimodal-Rag, extract or clone it\n"
            "  again there, and run run.bat from the new folder."
        )
    _say("Project files OK.")


def check_embedding() -> None:
    _say(f"Embedding model: {local_embedding_model()}")
    _say("Loading it. The first run downloads about 2.3 GB, so this can take a while...")
    vector = embed_text("warm-up")
    for corpus in load_registry():
        index_path = corpus.index_dir / MRAG_INDEX_FILENAME
        if not index_path.is_file():
            raise PreflightError(f"The search index is missing: {index_path}")
        if faiss.read_index(str(index_path)).d != len(vector):
            raise PreflightError(
                f"{index_path} was built with a different embedding model than {local_embedding_model()}."
            )
    _say("Embedding model OK.")


def _codex_run(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([*codex_command(), *args], capture_output=True, timeout=60, check=False)


def _canary_image() -> str:
    path = PROJECT_ROOT / "index" / METADATA_FILENAME
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("segment_id") == CANARY_SEGMENT:
            return str(PROJECT_ROOT / record["image_path"])
    raise PreflightError(f"Test image {CANARY_SEGMENT} not found in {path}")


def check_codex() -> None:
    try:
        command = codex_command()
    except RuntimeError as exc:
        raise PreflightError(f"Codex CLI not found.\n{CODEX_FIX}") from exc
    version = _codex_run("--version")
    if version.returncode != 0:
        raise PreflightError(f"Codex CLI did not start ({' '.join(command)}).\n{CODEX_FIX}")
    _say(f"Codex CLI: {version.stdout.decode('utf-8', 'replace').strip()}")

    status = _codex_run("login", "status")
    status_text = (status.stdout + status.stderr).decode("utf-8", "replace")
    if status.returncode != 0 or "logged in" not in status_text.lower():
        raise PreflightError(
            "Codex is not signed in. In a Command Prompt run:\n    codex login\n"
            "  and sign in with a ChatGPT account, then start the demo again."
        )
    _say(status_text.strip().splitlines()[0])

    exec_help = _codex_run("exec", "--help").stdout.decode("utf-8", "replace")
    missing = [flag for flag in ("--json", "--image", "--skip-git-repo-check") if flag not in exec_help]
    if missing:
        raise PreflightError(f"This Codex CLI is too old (no {', '.join(missing)}).\n{CODEX_FIX}")
    flags, features = codex_capabilities()
    _say(f"Codex options in use: {', '.join(sorted(flags)) or 'none'}; {len(features)} features known")
    _say(f"Model: {resolved_codex_model() or 'account default (catalog unreadable)'}")

    _say("Sending one test question with an image. This takes 10-30 seconds...")
    # The token appears only in the instructions and changes every run, so it
    # can only show up in the reply if the system prompt reached the model.
    token = f"{CANARY_TOKEN}-{uuid.uuid4().hex[:8].upper()}"
    reply = generate(
        "What label is printed next to module pin 35 in the attached image? Give the label.",
        images=[_canary_image()],
        model="sol",
        instructions=f"Begin every reply with the exact token {token}, then answer.",
    )
    if token not in reply:
        raise PreflightError(
            "Codex answered but ignored the demo's instructions, so this Codex version "
            f"is not compatible.\n{CODEX_FIX}\n  Reply was: {reply[:200]!r}"
        )
    if CANARY_EXPECTED not in reply.upper():
        raise PreflightError(
            f"Codex did not read the test image (expected {CANARY_EXPECTED}).\n{CODEX_FIX}\n"
            f"  Reply was: {reply[:200]!r}"
        )
    _say("Codex OK: instructions and images both reach the model.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-embed", action="store_true", help="skip loading the local embedding model")
    args = parser.parse_args(argv)

    try:
        check_files()
        if embed_provider() == "local" and not args.skip_embed:
            check_embedding()
        if llm_provider() == "codex":
            check_codex()
    except PreflightError as exc:
        print(f"\n  PROBLEM: {exc}\n", flush=True)
        return 1
    except Exception as exc:  # noqa: BLE001 - shown to a non-technical user, then exit
        print(f"\n  PROBLEM: {type(exc).__name__}: {exc}\n", flush=True)
        return 1
    _say("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
