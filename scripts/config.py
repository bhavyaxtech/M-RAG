"""Environment-backed provider configuration.

Azure settings are only required when a provider is set to ``azure``.
"""

from dataclasses import dataclass
from functools import lru_cache
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Literal, cast

from dotenv import load_dotenv


_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {name}. "
            + "Copy .env.example to .env and fill in the Azure deployment settings."
        )
    return value


@dataclass(frozen=True)
class AzureOpenAISettings:
    api_key: str
    endpoint: str
    api_version: str
    sol_deployment: str
    luna_deployment: str
    terra_deployment: str
    embedding_deployment: str


AZURE_EMBEDDING_MODEL = "text-embedding-3-large"
DEFAULT_LOCAL_EMBEDDING_MODEL = "BAAI/bge-m3"
_OPTIONAL_CODEX_FLAGS = ("--ephemeral", "--ignore-user-config", "--ignore-rules")
EmbedProvider = Literal["azure", "local"]
LLMProvider = Literal["azure", "codex"]


_PROCESS_WINS = ("EMBED_PROVIDER", "LLM_PROVIDER")


@lru_cache(maxsize=1)
def _load_env() -> None:
    # Project-local credentials must win over stale machine-level variables.
    # Provider switches are the exception, so a one-off run or a test can pin them.
    explicit = {name: os.environ[name] for name in _PROCESS_WINS if name in os.environ}
    _ = load_dotenv(_ENV_FILE, override=True)
    os.environ.update(explicit)


def _choice(name: str, allowed: tuple[str, ...]) -> str:
    _load_env()
    value = os.getenv(name, allowed[0]).strip().lower() or allowed[0]
    if value not in allowed:
        raise RuntimeError(f"{name}={value!r} is not one of {', '.join(allowed)}.")
    return value


def embed_provider() -> EmbedProvider:
    return cast(EmbedProvider, _choice("EMBED_PROVIDER", ("azure", "local")))


def llm_provider() -> LLMProvider:
    return cast(LLMProvider, _choice("LLM_PROVIDER", ("azure", "codex")))


def local_embedding_model() -> str:
    _load_env()
    return os.getenv("LOCAL_EMBEDDING_MODEL", "").strip() or DEFAULT_LOCAL_EMBEDDING_MODEL


def codex_command() -> list[str]:
    """argv prefix that launches the installed Codex CLI."""
    _load_env()
    configured = os.getenv("CODEX_BIN", "").strip()
    if configured:
        return [configured]
    shim = shutil.which("codex")
    if shim is None:
        raise RuntimeError("LLM_PROVIDER=codex but the codex CLI is not on PATH. Install it or set CODEX_BIN.")
    if not shim.lower().endswith((".cmd", ".bat")):
        return [shim]
    # The npm shim is a batch file; going through cmd.exe would re-parse the
    # quoted -c values, so run its node entry point directly.
    script = Path(shim).parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
    node = shutil.which("node")
    if node is None or not script.is_file():
        raise RuntimeError(f"Cannot resolve the codex entry point behind {shim}. Set CODEX_BIN.")
    return [node, str(script)]


def _codex_output(*args: str) -> str:
    try:
        completed = subprocess.run(
            [*codex_command(), *args], capture_output=True, timeout=60, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.decode("utf-8", "replace") if completed.returncode == 0 else ""


@lru_cache(maxsize=1)
def resolved_codex_model() -> str | None:
    """CODEX_MODEL, else the account's default from the Codex catalog, else None.

    Accounts differ in which models they can use, so nothing is hardcoded. None
    means the catalog was unreadable and Codex picks its own default.
    """
    _load_env()
    configured = os.getenv("CODEX_MODEL", "").strip()
    if configured:
        return configured
    try:
        models = json.loads(_codex_output("debug", "models"))["models"]
    except (ValueError, KeyError, TypeError):
        return None
    listed = [m for m in models if isinstance(m, dict) and m.get("slug") and m.get("visibility") == "list"]
    if not listed:
        return None
    return str(min(listed, key=lambda m: m.get("priority", float("inf")))["slug"])


@lru_cache(maxsize=1)
def codex_capabilities() -> tuple[frozenset[str], frozenset[str]]:
    """Optional exec flags and feature names this Codex build accepts.

    Codex rejects unknown --disable features and unknown flags outright, so
    other versions only get what they actually support.
    """
    help_text = _codex_output("exec", "--help")
    flags = frozenset(flag for flag in _OPTIONAL_CODEX_FLAGS if flag in help_text)
    features = frozenset(
        line.split()[0] for line in _codex_output("features", "list").splitlines() if line.strip()
    )
    return flags, features


def embedding_model_name() -> str:
    """The model whose vector space the active indexes and queries live in."""
    return AZURE_EMBEDDING_MODEL if embed_provider() == "azure" else local_embedding_model()


def embedding_deployment_name() -> str:
    if embed_provider() == "local":
        return f"local:{local_embedding_model()}"
    return get_settings().embedding_deployment


def generation_deployment_name(model: Literal["sol", "luna", "terra"]) -> str:
    if llm_provider() == "codex":
        return f"codex:{resolved_codex_model() or 'account-default'}"
    settings = get_settings()
    return {
        "sol": settings.sol_deployment,
        "luna": settings.luna_deployment,
        "terra": settings.terra_deployment,
    }[model]


def active_index_dir(base: Path) -> Path:
    """Local-embedding indexes live beside the Azure ones and never overwrite them."""
    return base if embed_provider() == "azure" else base / "local"


@lru_cache(maxsize=1)
def get_settings() -> AzureOpenAISettings:
    """Load and validate Azure OpenAI settings from the project .env file."""
    _load_env()
    return AzureOpenAISettings(
        api_key=_required_env("AZURE_OPENAI_API_KEY"),
        endpoint=_required_env("AZURE_OPENAI_ENDPOINT").rstrip("/"),
        api_version=_required_env("AZURE_OPENAI_API_VERSION"),
        sol_deployment=_required_env("AZURE_OPENAI_SOL_DEPLOYMENT"),
        luna_deployment=_required_env("AZURE_OPENAI_LUNA_DEPLOYMENT"),
        terra_deployment=_required_env("AZURE_OPENAI_TERRA_DEPLOYMENT"),
        embedding_deployment=_required_env("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"),
    )
