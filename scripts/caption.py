"""Generate and cache dense captions for parsed figure and table segments."""

from __future__ import annotations

import argparse
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
import json
from pathlib import Path
from queue import SimpleQueue
import sys
from threading import Event
from typing import Any, Iterable, Literal, Sequence, cast

from scripts.azure_client import generate
from scripts.file_io import replace_with_retry


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARSED_HARDWARE_DIR = PROJECT_ROOT / "data" / "parsed" / "hardware"
VISUAL_TYPES = {"figure", "table"}
CAPTION_CACHE_FILENAME = "caption_cache.json"
CAPTION_WORKER_CHOICES = range(1, 5)
CaptionModel = Literal["luna", "terra"]

CAPTION_PROMPT = """You are creating retrieval text for a cropped visual from a hardware datasheet.

Produce a dense, factual transcription and description of the visible content. Capture every legible technical detail that could answer a question: titles, labels, identifiers, symbols, notes, conditions, units, and numeric values. Preserve exact wording and numbers; do not infer values that are not visible.

For a pinout, package, block, or wiring diagram:
- Enumerate every legible pin/pad number and its exact label or function.
- State orientation markers, package views, grouped signals, alternate functions, and meaningful connections.

For an electrical-characteristics, timing, or specification table:
- State the table title and section, column headings, test conditions, and units.
- Transcribe each legible parameter or symbol with its minimum, typical, and maximum values as shown.
- Preserve footnote markers and include any legible footnotes or qualifications.

For other figures, identify the figure's purpose and transcribe all axes, legends, callouts, labels, and quantitative values. Do not respond with a vague one-line summary. If text is genuinely unreadable, say which part is unreadable rather than guessing.

Segment type: {segment_type}
Source document: {doc}
Page: {page}
{nearby_caption}"""


class CaptioningError(RuntimeError):
    """Raised when parsed segments or their caption cache are invalid."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaptioningError(f"Could not read JSON file {path}: {exc}") from exc


def _write_json(path: Path, payload: Any) -> None:
    """Atomically persist JSON so an interrupted run cannot corrupt the cache."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    replace_with_retry(temporary_path, path)


def _load_segments(path: Path) -> list[dict[str, Any]]:
    payload = _read_json(path)
    if not isinstance(payload, list) or not all(
        isinstance(segment, dict) for segment in payload
    ):
        raise CaptioningError(f"Expected {path} to contain a list of segment objects.")
    return payload


def _load_cache(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}

    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise CaptioningError(f"Expected {path} to contain an object keyed by segment ID.")

    cache: dict[str, dict[str, str]] = {}
    for segment_id, variants in payload.items():
        if not isinstance(segment_id, str) or not isinstance(variants, dict):
            raise CaptioningError(f"Caption cache {path} has an invalid entry.")
        if not all(
            isinstance(model, str) and isinstance(caption, str)
            for model, caption in variants.items()
        ):
            raise CaptioningError(
                f"Caption cache entry {segment_id!r} in {path} is invalid."
            )
        cache[segment_id] = dict(variants)
    return cache


def _image_path(segment: dict[str, Any]) -> Path:
    value = segment.get("image_path")
    if not isinstance(value, str) or not value.strip():
        raise CaptioningError(
            f"Visual segment {segment.get('segment_id')!r} has no image_path."
        )

    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()
    if not path.is_file():
        raise CaptioningError(
            f"Image for segment {segment.get('segment_id')!r} was not found: {path}"
        )
    return path


def _caption_prompt(segment: dict[str, Any]) -> str:
    source_caption = segment.get("mineru_caption")
    if source_caption is None and segment.get("caption_model") is None:
        source_caption = segment.get("caption")

    nearby_caption = ""
    if isinstance(source_caption, str) and source_caption.strip():
        nearby_caption = (
            "MinerU nearby caption (use only as context; verify against the image): "
            + source_caption.strip()
        )

    return CAPTION_PROMPT.format(
        segment_type=segment.get("type", "visual"),
        doc=segment.get("doc", "unknown"),
        page=segment.get("page", "unknown"),
        nearby_caption=nearby_caption,
    )


def _store_caption(
    segment: dict[str, Any],
    caption: str,
    model: CaptionModel,
) -> None:
    existing_caption = segment.get("caption")
    existing_model = segment.get("caption_model")
    if (
        "mineru_caption" not in segment
        and isinstance(existing_caption, str)
        and existing_caption.strip()
        and existing_model is None
    ):
        segment["mineru_caption"] = existing_caption

    variants = segment.get("generated_captions")
    if not isinstance(variants, dict):
        variants = {}
        segment["generated_captions"] = variants
    variants[model] = caption
    segment["caption"] = caption
    segment["caption_model"] = model


def _generate_caption(segment: dict[str, Any], model: CaptionModel) -> str:
    image_path = _image_path(segment)
    caption = generate(
        _caption_prompt(segment),
        images=[str(image_path)],
        model=model,
    ).strip()
    if not caption:
        raise CaptioningError(
            f"Model {model!r} returned an empty caption for "
            f"{segment.get('segment_id')}."
        )
    return caption


def caption_segments_file(
    segments_path: Path,
    model: CaptionModel = "luna",
    segment_ids: set[str] | None = None,
    workers: int = 1,
) -> tuple[int, int, set[str]]:
    """Caption visuals, returning generated/cached counts and matched IDs."""
    if (
        not isinstance(workers, int)
        or isinstance(workers, bool)
        or workers not in CAPTION_WORKER_CHOICES
    ):
        raise ValueError("workers must be an integer from 1 through 4")

    segments_path = segments_path.resolve()
    if not segments_path.is_file():
        raise CaptioningError(f"Segments file not found: {segments_path}")

    segments = _load_segments(segments_path)
    cache_path = segments_path.parent / CAPTION_CACHE_FILENAME
    cache = _load_cache(cache_path)
    generated_count = 0
    cached_count = 0
    completed_count = 0
    matched_ids: set[str] = set()
    segment_iterator = iter(segments)
    completed_futures: SimpleQueue[Future[str]] = SimpleQueue()
    in_flight: dict[Future[str], tuple[str, dict[str, Any]]] = {}
    segments_exhausted = False
    first_error: Exception | None = None
    failed_future_ready = Event()

    def record_completion(*, checkpoint: bool) -> None:
        nonlocal completed_count
        completed_count += 1
        if checkpoint or completed_count % 25 == 0:
            _write_json(segments_path, segments)
        if completed_count % 25 == 0:
            print(
                f"  Checkpoint: {completed_count} visual segment(s) complete.",
                flush=True,
            )

    def next_uncached_segment() -> tuple[str, dict[str, Any]] | None:
        nonlocal cached_count
        for segment in segment_iterator:
            if segment.get("type") not in VISUAL_TYPES:
                continue

            segment_id = segment.get("segment_id")
            if not isinstance(segment_id, str) or not segment_id:
                raise CaptioningError(
                    f"Visual segment in {segments_path} has no segment_id."
                )
            if segment_ids is not None and segment_id not in segment_ids:
                continue
            matched_ids.add(segment_id)

            caption = cache.get(segment_id, {}).get(model)
            if caption is None:
                return segment_id, segment

            cached_count += 1
            _store_caption(segment, caption, model)
            record_completion(checkpoint=False)
        return None

    def generate_caption(segment: dict[str, Any]) -> str:
        try:
            return _generate_caption(segment, model)
        except Exception:
            failed_future_ready.set()
            raise

    def submit_next(executor: ThreadPoolExecutor) -> bool:
        nonlocal first_error, segments_exhausted
        if (
            segments_exhausted
            or first_error is not None
            or failed_future_ready.is_set()
        ):
            return False
        try:
            job = next_uncached_segment()
            if job is None:
                segments_exhausted = True
                return False
            segment_id, segment = job
            context = copy_context()
            if failed_future_ready.is_set():
                return False
            future = executor.submit(context.run, generate_caption, segment)
            in_flight[future] = (segment_id, segment)
            future.add_done_callback(completed_futures.put)
            return True
        except Exception as exc:
            first_error = exc
            return False

    with ThreadPoolExecutor(max_workers=workers) as executor:
        while len(in_flight) < workers and submit_next(executor):
            pass

        while in_flight:
            future = completed_futures.get()
            segment_id, segment = in_flight.pop(future)
            try:
                caption = future.result()
                cache.setdefault(segment_id, {})[model] = caption
                _store_caption(segment, caption, model)
                generated_count += 1
                _write_json(cache_path, cache)
                record_completion(checkpoint=True)
            except Exception as exc:
                if first_error is None:
                    first_error = exc

            if first_error is None:
                while len(in_flight) < workers and submit_next(executor):
                    pass

    if first_error is not None:
        raise first_error

    if completed_count:
        _write_json(segments_path, segments)
    return generated_count, cached_count, matched_ids


def discover_segment_files(inputs: Iterable[Path], parsed_root: Path) -> list[Path]:
    """Resolve explicit segment files/document directories or discover all docs."""
    candidates: list[Path] = []
    for raw_path in inputs:
        path = raw_path.expanduser()
        if path.is_dir():
            path = path / "segments.json"
        candidates.append(path.resolve())

    if not candidates:
        root = parsed_root.expanduser().resolve()
        if not root.is_dir():
            return []
        candidates = sorted(root.glob("*/segments.json"))

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        if path not in seen:
            unique.append(path)
            seen.add(path)
    return unique


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Caption parsed hardware figures and tables with Luna by default. "
            "Completed captions are reused from each document's caption cache."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help=(
            "segments.json file(s) or parsed document directories; defaults to "
            "all documents under data/parsed/hardware"
        ),
    )
    parser.add_argument(
        "--model",
        choices=("luna", "terra"),
        default="luna",
        help="captioning deployment alias (default: luna)",
    )
    parser.add_argument(
        "--segment-id",
        action="append",
        dest="segment_ids",
        help="caption only this segment ID; repeat to select a handful",
    )
    parser.add_argument(
        "--workers",
        type=int,
        choices=CAPTION_WORKER_CHOICES,
        default=1,
        help="parallel caption requests, from 1 through 4 (default: 1)",
    )
    parser.add_argument(
        "--parsed-root",
        type=Path,
        default=PARSED_HARDWARE_DIR,
        help="parsed document root used when no inputs are given",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    model = cast(CaptionModel, args.model)
    requested_ids = set(args.segment_ids) if args.segment_ids else None
    segment_files = discover_segment_files(args.inputs, args.parsed_root)
    if not segment_files:
        print(
            "No segments.json files found. Run scripts/parse.py first or pass "
            "parsed document directories explicitly.",
            file=sys.stderr,
        )
        return 2

    generated_total = 0
    cached_total = 0
    matched_ids: set[str] = set()
    try:
        for index, segments_path in enumerate(segment_files, start=1):
            print(
                f"[{index}/{len(segment_files)}] {segments_path.parent.name}",
                flush=True,
            )
            generated, cached, matched = caption_segments_file(
                segments_path,
                model=model,
                segment_ids=requested_ids,
                workers=args.workers,
            )
            generated_total += generated
            cached_total += cached
            matched_ids.update(matched)
            print(
                f"  {generated} generated, {cached} loaded from cache ({model}).",
                flush=True,
            )
    except (CaptioningError, OSError, ValueError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr, flush=True)
        return 1

    missing_ids = (requested_ids or set()) - matched_ids
    if missing_ids:
        print(
            "Requested visual segment ID(s) not found: " + ", ".join(sorted(missing_ids)),
            file=sys.stderr,
        )
        return 2

    print(
        f"Captioning complete: {generated_total} generated, "
        f"{cached_total} loaded from cache ({model})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
