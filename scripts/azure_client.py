"""Deployment-agnostic embedding and generation boundary.

This is the only module that talks to a model. Pipeline code must use
``embed_text``, ``generate``, or ``generate_stream``. Providers are chosen in
``.env``: ``EMBED_PROVIDER`` (azure | local) and ``LLM_PROVIDER`` (azure | codex).
"""

import base64
from collections.abc import Iterator
from functools import lru_cache
import json
import mimetypes
from pathlib import Path
import subprocess
import tempfile
import threading
from typing import Any, Literal, overload

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    InternalServerError,
    RateLimitError,
)
from openai.types.chat import (
    ChatCompletionContentPartParam,
    ChatCompletionMessageParam,
)
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from scripts.config import (
    codex_capabilities,
    codex_command,
    embed_provider,
    get_settings,
    llm_provider,
    local_embedding_model,
    resolved_codex_model,
)
from scripts.usage_budget import CURRENT_BUDGET, MAX_OUTPUT_TOKENS


_TRANSIENT_STATUS_CODES = {408, 409, 429}
GenerationModel = Literal["sol", "luna", "terra"]


def _is_transient_error(error: BaseException) -> bool:
    if isinstance(
        error,
        (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError),
    ):
        return True
    return isinstance(error, APIStatusError) and (
        error.status_code in _TRANSIENT_STATUS_CODES or error.status_code >= 500
    )


_retry_transient = retry(
    retry=retry_if_exception(_is_transient_error),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    stop=stop_after_attempt(4),
    reraise=True,
)


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    settings = get_settings()
    return OpenAI(
        api_key=settings.api_key,
        base_url=f"{settings.endpoint}/openai/v1",
    )


def _image_url(image: str) -> str:
    if image.startswith(("https://", "http://", "data:")):
        return image

    path = Path(image).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Image not found: {path}")

    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def _check_request(prompt: str, model: GenerationModel) -> None:
    if not prompt.strip():
        raise ValueError("prompt must not be empty")
    if model not in {"sol", "luna", "terra"}:
        raise ValueError(f"Unsupported generation model: {model!r}")


_ENCODER_LOCK = threading.Lock()


def _local_encoder() -> Any:
    # The server warms this up on a thread; without the lock a first request
    # racing it would load a second 2 GB copy.
    with _ENCODER_LOCK:
        return _load_local_encoder()


@lru_cache(maxsize=1)
def _load_local_encoder() -> Any:
    # Imported lazily so the Azure-only demo bundle never needs torch.
    import torch
    from sentence_transformers import SentenceTransformer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model_kwargs = {"dtype": torch.float16} if device == "cuda" else {}
    return SentenceTransformer(local_embedding_model(), device=device, model_kwargs=model_kwargs)


def _local_embed(texts: list[str]) -> list[list[float]]:
    vectors = _local_encoder().encode(
        texts,
        batch_size=8,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return [[float(value) for value in vector] for vector in vectors]


# Codex is an agent; these keep it to a single sandboxed model turn. The
# code-mode host stays enabled because disabling it makes codex exec error.
_CODEX_DISABLED_FEATURES = (
    "apps", "plugins", "remote_plugin", "goals", "image_generation", "multi_agent",
    "memories", "hooks", "skill_search", "tool_suggest", "browser_use",
    "browser_use_external", "computer_use", "in_app_browser",
)
_CODEX_REASONING_EFFORT: dict[GenerationModel, str] = {"sol": "medium", "terra": "medium", "luna": "low"}
_CODEX_DEFAULT_INSTRUCTIONS = "You are a helpful assistant."
_CODEX_TIMEOUT_SECONDS = 300


def _codex_image_path(image: str) -> str:
    path = Path(image).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Image not found (codex needs a local file): {image}")
    return str(path.resolve())


def _codex_answer(completed: subprocess.CompletedProcess[bytes]) -> str:
    messages: list[str] = []
    errors: list[str] = []
    for line in completed.stdout.decode("utf-8", "replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind == "item.completed":
            item = event.get("item") or {}
            if item.get("type") == "agent_message" and item.get("text"):
                messages.append(item["text"])
        elif kind in {"error", "turn.failed"}:
            errors.append(str(event.get("message") or event.get("error")))
    if errors or completed.returncode != 0:
        detail = "; ".join(errors) or completed.stderr.decode("utf-8", "replace").strip()[-800:]
        raise RuntimeError(f"codex exec failed (exit {completed.returncode}): {detail}")
    if not messages:
        raise RuntimeError("codex exec returned an empty response")
    return messages[-1]


def _codex_generate(
    prompt: str,
    images: list[str] | None,
    model: GenerationModel,
    instructions: str | None,
) -> str:
    _check_request(prompt, model)
    image_paths = [_codex_image_path(image) for image in images or []]
    with tempfile.TemporaryDirectory(prefix="mrag-codex-") as workdir:
        instructions_path = Path(workdir) / "instructions.md"
        instructions_path.write_text(instructions or _CODEX_DEFAULT_INSTRUCTIONS, encoding="utf-8")
        flags, features = codex_capabilities()
        command = [
            *codex_command(), "exec", *sorted(flags), "--skip-git-repo-check",
            "--json", "-s", "read-only", "-C", workdir,
            "-c", f"model_reasoning_effort={_CODEX_REASONING_EFFORT[model]}",
            "-c", f"model_instructions_file={json.dumps(instructions_path.as_posix())}",
            "-c", 'web_search="disabled"',
        ]
        codex_model = resolved_codex_model()
        if codex_model:
            command += ["-m", codex_model]
        for feature in _CODEX_DISABLED_FEATURES:
            if feature in features:
                command += ["--disable", feature]
        for image_path in image_paths:
            command += ["-i", image_path]
        command.append("-")
        completed = subprocess.run(
            command,
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=_CODEX_TIMEOUT_SECONDS,
            check=False,
        )
    return _codex_answer(completed)


def warm_up() -> None:
    """Load what the first request would otherwise wait for. Safe to call twice."""
    if embed_provider() == "local":
        _local_encoder()
    if llm_provider() == "codex":
        codex_capabilities()
        resolved_codex_model()


def _validated_request(
    prompt: str,
    images: list[str] | None,
    model: GenerationModel,
    instructions: str | None = None,
) -> tuple[list[ChatCompletionMessageParam], str]:
    """Validate generation inputs and resolve the target deployment."""
    _check_request(prompt, model)

    content: str | list[ChatCompletionContentPartParam]
    if images:
        content = [{"type": "text", "text": prompt}]
        content.extend(
            {"type": "image_url", "image_url": {"url": _image_url(image)}}
            for image in images
        )
    else:
        content = prompt

    messages: list[ChatCompletionMessageParam] = []
    if instructions:
        messages.append({"role": "system", "content": instructions})
    messages.append({"role": "user", "content": content})
    settings = get_settings()
    deployment = {
        "sol": settings.sol_deployment,
        "luna": settings.luna_deployment,
        "terra": settings.terra_deployment,
    }[model]
    return messages, deployment


@overload
def embed_text(text: str) -> list[float]: ...


@overload
def embed_text(text: list[str]) -> list[list[float]]: ...


@_retry_transient
def embed_text(text: str | list[str]) -> list[float] | list[list[float]]:
    """Embed text or an ordered batch through the same provider boundary."""
    texts = [text] if isinstance(text, str) else text
    if not texts or len(texts) > 32 or any(not isinstance(item, str) or not item.strip() for item in texts):
        raise ValueError("Expected 1 to 32 non-empty texts")

    if embed_provider() == "local":
        local_vectors = _local_embed(texts)
        return local_vectors[0] if isinstance(text, str) else local_vectors

    settings = get_settings()
    budget = CURRENT_BUDGET.get()
    reservation = budget.reserve("embedding", settings.embedding_deployment, "\n".join(texts)) if budget else None
    client = _client().with_options(max_retries=0, timeout=120) if budget else _client()
    response = client.embeddings.create(
        model=settings.embedding_deployment,
        input=text,
    )
    if budget:
        budget.settle(reservation, response.usage, response.model)
    ordered = sorted(response.data, key=lambda item: item.index)
    if [item.index for item in ordered] != list(range(len(texts))):
        raise RuntimeError("Embedding response did not align with the input batch")
    vectors = [list(item.embedding) for item in ordered]
    return vectors[0] if isinstance(text, str) else vectors


@_retry_transient
def generate(
    prompt: str,
    images: list[str] | None = None,
    model: GenerationModel = "sol",
    *,
    instructions: str | None = None,
) -> str:
    """Generate text with a configured deployment, optionally attaching images."""
    if llm_provider() == "codex":
        return _codex_generate(prompt, images, model, instructions)
    messages, deployment = _validated_request(prompt, images, model, instructions)
    budget = CURRENT_BUDGET.get()
    reservation = budget.reserve(model, deployment, prompt + (instructions or ""), len(images or [])) if budget else None
    options = {"max_completion_tokens": MAX_OUTPUT_TOKENS} if budget else {}
    client = _client().with_options(max_retries=0, timeout=120) if budget else _client()
    response = client.chat.completions.create(
        model=deployment,
        messages=messages,
        **options,
    )
    if budget:
        budget.settle(reservation, response.usage, response.model)
        if response.choices[0].finish_reason == "length":
            raise RuntimeError("Caption/answer exceeded output limit; not caching truncated text")
    result = response.choices[0].message.content
    if not result:
        raise RuntimeError("Azure OpenAI returned an empty response")
    return result


@_retry_transient
def _open_stream(
    prompt: str,
    images: list[str] | None,
    model: GenerationModel,
    instructions: str | None = None,
) -> Any:
    """Open one streamed completion, retrying only the connection attempt."""
    messages, deployment = _validated_request(prompt, images, model, instructions)
    budget = CURRENT_BUDGET.get()
    reservation = budget.reserve(model, deployment, prompt + (instructions or ""), len(images or [])) if budget else None
    options = {"max_completion_tokens": MAX_OUTPUT_TOKENS, "stream_options": {"include_usage": True}} if budget else {}
    client = _client().with_options(max_retries=0, timeout=120) if budget else _client()
    stream = client.chat.completions.create(
        model=deployment,
        messages=messages,
        stream=True,
        # Explicit reasoning for all streamed answers, including the baseline.
        # Routing/captioning calls retain their existing non-streamed settings.
        reasoning_effort="medium",
        **options,
    )
    return _metered_stream(stream, budget, reservation) if budget else stream


def _metered_stream(stream, budget, reservation):
    try:
        for chunk in stream:
            if getattr(chunk, "usage", None) is not None:
                budget.settle(reservation, chunk.usage, chunk.model)
            yield chunk
    finally:
        stream.close()


def generate_stream(
    prompt: str,
    images: list[str] | None = None,
    model: GenerationModel = "sol",
    *,
    instructions: str | None = None,
) -> Iterator[str]:
    """Yield generated text deltas as they arrive.

    Only the initial connection is retried. A stream that fails midway is not
    restarted, because replaying it would duplicate already-yielded text.
    ``codex exec`` emits no token deltas, so under codex this yields one chunk.
    """
    if llm_provider() == "codex":
        yield _codex_generate(prompt, images, model, instructions)
        return
    stream = _open_stream(prompt, images, model, instructions)
    produced_any = False
    for chunk in stream:
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        text = getattr(delta, "content", None)
        if text:
            produced_any = True
            yield text
    if not produced_any:
        raise RuntimeError("Azure OpenAI returned an empty response")
