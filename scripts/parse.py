"""Parse hardware datasheets into normalized multimodal segments with MinerU.

The parser tries MinerU's VLM backend first and retries the same document with
MinerU's CPU-compatible pipeline backend if VLM inference or setup fails.
MinerU's raw artifacts are retained beside the normalized ``segments.json`` so
layout and crop quality can be inspected before captioning.
"""

from __future__ import annotations

import argparse
from collections import Counter
import importlib.metadata
import json

import fitz
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_HARDWARE_DIR = PROJECT_ROOT / "data" / "raw" / "hardware"
PARSED_HARDWARE_DIR = PROJECT_ROOT / "data" / "parsed" / "hardware"

TEXT_LIKE_TYPES = {"text", "equation", "code", "list"}
FIGURE_TYPES = {"image", "chart"}
IGNORED_TYPES = {
    "header",
    "footer",
    "page_number",
    "aside_text",
    "page_footnote",
}


class MinerUError(RuntimeError):
    """Raised when MinerU cannot produce a usable content list."""


def mineru_version() -> str:
    """Return the installed MinerU package version."""
    try:
        return importlib.metadata.version("mineru")
    except importlib.metadata.PackageNotFoundError as exc:
        raise MinerUError(
            "MinerU is not installed. Install project dependencies with "
            "`python -m pip install -r requirements.txt`."
        ) from exc


def vlm_backend_for(version: str) -> str:
    """Select the VLM backend spelling used by the installed MinerU release."""
    try:
        major = int(version.split(".", maxsplit=1)[0])
    except ValueError:
        major = 2
    return "vlm-engine" if major >= 3 else "vlm-auto-engine"


def mineru_command() -> list[str]:
    """Find MinerU beside the active interpreter before searching ``PATH``."""
    script_name = "mineru.exe" if sys.platform == "win32" else "mineru"
    environment_executable = Path(sys.executable).parent / script_name
    if environment_executable.is_file():
        return [str(environment_executable)]

    executable = shutil.which("mineru")
    if executable:
        return [executable]
    return [sys.executable, "-m", "mineru.cli.client"]


def run_mineru(
    pdf_path: Path,
    output_dir: Path,
    backend: str,
    timeout: float | None = None,
    start_page: int | None = None,
    end_page: int | None = None,
) -> None:
    """Run one MinerU backend and require a generated content list."""
    command = [
        *mineru_command(),
        "--path",
        str(pdf_path),
        "--output",
        str(output_dir),
        "--backend",
        backend,
        "--method",
        "auto",
        "--lang",
        "en",
        "--formula",
        "true",
        "--table",
        "true",
    ]
    if start_page is not None:
        command.extend(["--start", str(start_page)])
    if end_page is not None:
        command.extend(["--end", str(end_page)])

    page_range = (
        f" (pages {start_page + 1}-{end_page + 1})"
        if start_page is not None and end_page is not None
        else ""
    )
    print(f"  Running MinerU backend: {backend}{page_range}", flush=True)

    try:
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise MinerUError(
            "The MinerU command is unavailable even though the package was found."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise MinerUError(
            f"MinerU backend {backend!r} exceeded the {timeout:g}-second timeout."
        ) from exc

    if result.returncode != 0:
        details = _command_output_tail(result.stdout, result.stderr)
        raise MinerUError(
            f"MinerU backend {backend!r} exited with code {result.returncode}."
            + (f"\n{details}" if details else "")
        )

    try:
        find_content_list(output_dir, pdf_path.stem)
    except MinerUError as exc:
        details = _command_output_tail(result.stdout, result.stderr)
        raise MinerUError(
            f"MinerU backend {backend!r} completed without a usable content list."
            + (f"\n{details}" if details else "")
        ) from exc


def _command_output_tail(stdout: str, stderr: str, line_count: int = 30) -> str:
    lines = [line for line in (stdout + "\n" + stderr).splitlines() if line.strip()]
    return "\n".join(lines[-line_count:])


def find_content_list(output_dir: Path, doc_stem: str) -> Path:
    """Locate MinerU's legacy flat content list across version-specific layouts."""
    preferred_name = f"{doc_stem}_content_list.json"
    direct_path = output_dir / preferred_name
    if direct_path.is_file():
        return direct_path

    candidates = sorted(
        path
        for path in output_dir.rglob("*_content_list.json")
        if not path.name.endswith("_content_list_v2.json")
    )
    if not candidates:
        raise MinerUError(f"No *_content_list.json found beneath {output_dir}.")

    preferred = [path for path in candidates if path.name == preferred_name]
    if len(preferred) == 1:
        return preferred[0]
    if len(candidates) == 1:
        return candidates[0]
    raise MinerUError(
        "MinerU produced multiple ambiguous content lists: "
        + ", ".join(str(path) for path in candidates)
    )


def run_mineru_batched(
    pdf_path: Path,
    output_dir: Path,
    backend: str,
    pages_per_batch: int,
    timeout: float | None = None,
) -> None:
    """Run MinerU over bounded page ranges and merge its normalized raw items."""
    if pages_per_batch <= 0:
        raise ValueError("pages_per_batch must be positive")

    with fitz.open(pdf_path) as document:
        page_count = document.page_count
    merged_items: list[dict[str, Any]] = []
    batch_root = output_dir / f"page_batches_{backend}"
    batch_root.mkdir(parents=True, exist_ok=True)

    for start_page in range(0, page_count, pages_per_batch):
        end_page = min(start_page + pages_per_batch, page_count) - 1
        batch_dir = batch_root / f"pages_{start_page + 1:04d}_{end_page + 1:04d}"
        try:
            content_list_path = find_content_list(batch_dir, pdf_path.stem)
            print(
                f"  Reusing MinerU pages {start_page + 1}-{end_page + 1}.",
                flush=True,
            )
        except MinerUError:
            _reset_directory(batch_dir)
            run_mineru(
                pdf_path,
                batch_dir,
                backend,
                timeout,
                start_page=start_page,
                end_page=end_page,
            )
            content_list_path = find_content_list(batch_dir, pdf_path.stem)

        batch_items = _read_content_list(content_list_path)
        for item in batch_items:
            local_page_idx = item.get("page_idx")
            if not isinstance(local_page_idx, int) or not (
                0 <= local_page_idx <= end_page - start_page
            ):
                raise MinerUError(
                    f"MinerU batch {batch_dir.name} emitted invalid page_idx "
                    f"{local_page_idx!r}."
                )
            merged_item = dict(item)
            merged_item["page_idx"] = local_page_idx + start_page
            raw_image_path = merged_item.get("img_path")
            if isinstance(raw_image_path, str) and raw_image_path:
                image_path = Path(raw_image_path)
                if not image_path.is_absolute():
                    image_path = content_list_path.parent / image_path
                merged_item["img_path"] = str(image_path.resolve())
            merged_items.append(merged_item)

    if not merged_items:
        raise MinerUError(f"Batched MinerU run produced no content for {pdf_path}.")
    _write_json(output_dir / f"{pdf_path.stem}_content_list.json", merged_items)


def _read_content_list(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MinerUError(f"Could not read MinerU content list {path}: {exc}") from exc

    if not isinstance(payload, list) or not all(
        isinstance(item, dict) for item in payload
    ):
        raise MinerUError(f"MinerU content list {path} is not a list of objects.")
    return payload


def _joined_strings(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    return ""


def _text_from_item(item: dict[str, Any]) -> str:
    item_type = item.get("type")
    if item_type in {"text", "equation"}:
        return _joined_strings(item.get("text"))
    if item_type == "list":
        return _joined_strings(item.get("list_items"))
    if item_type == "code":
        caption = _joined_strings(item.get("code_caption"))
        body = _joined_strings(item.get("code_body"))
        return "\n".join(part for part in (caption, body) if part)
    return ""


def _relative_project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError as exc:
        raise MinerUError(f"MinerU image is outside the project: {path}") from exc


def _render_mineru_bbox_crop(
    pdf_path: Path,
    item: dict[str, Any],
    destination: Path,
) -> Path:
    """Render a crop using only MinerU's detected page and bounding box."""
    page_idx = item.get("page_idx")
    bbox = item.get("bbox")
    if (
        not isinstance(page_idx, int)
        or not isinstance(bbox, list)
        or len(bbox) != 4
        or not all(isinstance(value, (int, float)) for value in bbox)
    ):
        raise MinerUError(
            "MinerU visual item has no usable img_path or normalized bbox."
        )

    with fitz.open(pdf_path) as document:
        if page_idx < 0 or page_idx >= document.page_count:
            raise MinerUError(f"MinerU page_idx {page_idx} is outside {pdf_path}.")
        page: Any = document[page_idx]
        x0, y0, x1, y1 = (float(value) for value in bbox)
        clip = fitz.Rect(
            x0 * page.rect.width / 1000,
            y0 * page.rect.height / 1000,
            x1 * page.rect.width / 1000,
            y1 * page.rect.height / 1000,
        ) & page.rect
        if clip.is_empty or clip.is_infinite:
            raise MinerUError(f"MinerU bbox {bbox!r} is invalid on page {page_idx + 1}.")
        pixmap = page.get_pixmap(
            matrix=fitz.Matrix(2, 2),
            clip=clip,
            alpha=False,
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(destination)
    return destination


def normalize_segments(
    content_list_path: Path,
    doc_name: str,
    pdf_path: Path,
) -> list[dict[str, Any]]:
    """Convert a MinerU flat content list to the project's segment schema."""
    items = _read_content_list(content_list_path)
    segments: list[dict[str, Any]] = []
    type_counts: Counter[str] = Counter()

    for item in items:
        item_type = str(item.get("type", ""))
        page_idx = item.get("page_idx")
        if not isinstance(page_idx, int) or page_idx < 0:
            raise MinerUError(
                f"MinerU item has an invalid zero-based page_idx: {page_idx!r}"
            )
        page_number = page_idx + 1

        if item_type in TEXT_LIKE_TYPES:
            text = _text_from_item(item)
            if not text:
                continue
            normalized_type = "text"
            type_counts[normalized_type] += 1
            segments.append(
                {
                    "segment_id": (
                        f"{doc_name}-p{page_number:04d}-text-"
                        f"{type_counts[normalized_type]:05d}"
                    ),
                    "type": normalized_type,
                    "doc": doc_name,
                    "page": page_number,
                    "text": text,
                }
            )
            continue

        if item_type in FIGURE_TYPES or item_type == "table":
            normalized_type = "figure" if item_type in FIGURE_TYPES else "table"
            raw_image_path = item.get("img_path")
            crop_source = "mineru"
            image_path = Path(raw_image_path) if isinstance(raw_image_path, str) else Path()
            if raw_image_path and not image_path.is_absolute():
                image_path = content_list_path.parent / image_path
            if not raw_image_path or not image_path.is_file():
                fallback_number = type_counts[normalized_type] + 1
                image_path = _render_mineru_bbox_crop(
                    pdf_path,
                    item,
                    content_list_path.parent
                    / "images"
                    / (
                        f"bbox_fallback_{normalized_type}_p{page_number:04d}_"
                        f"{fallback_number:05d}.png"
                    ),
                )
                crop_source = "mineru_bbox_fallback"

            caption_key = "table_caption" if normalized_type == "table" else (
                "chart_caption" if item_type == "chart" else "image_caption"
            )
            caption = _joined_strings(item.get(caption_key))
            type_counts[normalized_type] += 1
            segments.append(
                {
                    "segment_id": (
                        f"{doc_name}-p{page_number:04d}-{normalized_type}-"
                        f"{type_counts[normalized_type]:05d}"
                    ),
                    "type": normalized_type,
                    "doc": doc_name,
                    "page": page_number,
                    "image_path": _relative_project_path(image_path),
                    "caption": caption,
                    "crop_source": crop_source,
                }
            )
            continue

        if item_type not in IGNORED_TYPES:
            print(f"  Warning: ignoring unsupported MinerU item type {item_type!r}.")

    if not segments:
        raise MinerUError(f"MinerU content list {content_list_path} had no usable segments.")
    return segments


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _reset_directory(path: Path) -> None:
    path.resolve().relative_to((PROJECT_ROOT / "data" / "parsed").resolve())
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def _finalize_parse(
    pdf_path: Path,
    output_root: Path,
    raw_output_dir: Path,
    version: str,
    selected_backend: str,
) -> tuple[list[dict[str, Any]], str]:
    doc_name = pdf_path.stem
    doc_dir = output_root.resolve() / doc_name
    content_list_path = find_content_list(raw_output_dir, doc_name)
    segments = normalize_segments(content_list_path, doc_name, pdf_path)
    counts = Counter(segment["type"] for segment in segments)
    _write_json(doc_dir / "segments.json", segments)
    _write_json(
        doc_dir / "parse_metadata.json",
        {
            "doc": doc_name,
            "source_pdf": _relative_project_path(pdf_path),
            "mineru_version": version,
            "backend": selected_backend,
            "content_list": _relative_project_path(content_list_path),
            "segment_counts": {
                "text": counts["text"],
                "figure": counts["figure"],
                "table": counts["table"],
            },
        },
    )
    return segments, selected_backend


def normalize_existing_parse(
    pdf_path: Path,
    output_root: Path = PARSED_HARDWARE_DIR,
) -> tuple[list[dict[str, Any]], str]:
    """Normalize an existing raw MinerU run without repeating inference."""
    pdf_path = pdf_path.resolve()
    raw_output_dir = output_root.resolve() / pdf_path.stem / "mineru"
    content_list_path = find_content_list(raw_output_dir, pdf_path.stem)
    middle_path = content_list_path.with_name(f"{pdf_path.stem}_middle.json")
    backend = "unknown"
    version = mineru_version()
    if middle_path.is_file():
        try:
            middle = json.loads(middle_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            middle = {}
        if isinstance(middle, dict):
            backend = str(middle.get("_backend", backend))
            version = str(middle.get("_version_name", version))
    return _finalize_parse(
        pdf_path,
        output_root,
        raw_output_dir,
        version,
        backend,
    )


def parse_pdf(
    pdf_path: Path,
    output_root: Path = PARSED_HARDWARE_DIR,
    timeout: float | None = None,
    allow_pipeline_fallback: bool = True,
    try_vlm: bool = True,
    pages_per_batch: int | None = None,
    raw_root: Path = RAW_HARDWARE_DIR,
) -> tuple[list[dict[str, Any]], str]:
    """Parse one PDF, returning normalized segments and the backend used."""
    pdf_path = pdf_path.resolve()
    if not pdf_path.is_file() or pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected an existing PDF file, got {pdf_path}.")
    try:
        pdf_path.relative_to(raw_root.resolve())
    except ValueError as exc:
        raise ValueError(
            f"PDF must be located beneath {raw_root}, got {pdf_path}."
        ) from exc

    # MinerU resets its work directories recursively. Never allow those writes
    # outside the project's parsed-artifact tree, including through symlinks.
    output_root.resolve().relative_to((PROJECT_ROOT / "data" / "parsed").resolve())

    version = mineru_version()
    doc_name = pdf_path.stem
    doc_dir = output_root.resolve() / doc_name
    work_dir = doc_dir / "_mineru_work"
    raw_output_dir = doc_dir / "mineru"
    for directory in (work_dir, raw_output_dir):
        directory.resolve().relative_to((PROJECT_ROOT / "data" / "parsed").resolve())
    doc_dir.mkdir(parents=True, exist_ok=True)

    backends = [vlm_backend_for(version)] if try_vlm else ["pipeline"]
    if try_vlm and allow_pipeline_fallback:
        backends.append("pipeline")

    failures: list[str] = []
    selected_backend = ""
    for backend in backends:
        if pages_per_batch is None:
            _reset_directory(work_dir)
        else:
            work_dir.mkdir(parents=True, exist_ok=True)
        try:
            if pages_per_batch is None:
                run_mineru(pdf_path, work_dir, backend, timeout)
            else:
                run_mineru_batched(
                    pdf_path,
                    work_dir,
                    backend,
                    pages_per_batch,
                    timeout,
                )
            selected_backend = backend
            break
        except MinerUError as exc:
            failures.append(str(exc))
            print(f"  {backend} failed: {exc}", file=sys.stderr, flush=True)
            if backend != backends[-1]:
                print("  Falling back to MinerU pipeline backend.", flush=True)

    if not selected_backend:
        if pages_per_batch is None:
            shutil.rmtree(work_dir, ignore_errors=True)
        raise MinerUError("\n\n".join(failures))

    if raw_output_dir.exists():
        shutil.rmtree(raw_output_dir)
    for attempt in range(5):
        try:
            work_dir.replace(raw_output_dir)
            break
        except PermissionError:
            # Windows scanners can briefly retain a handle after MinerU exits.
            # Keep the completed batches and retry only the directory handoff.
            if attempt == 4:
                raise
            time.sleep(1)

    return _finalize_parse(
        pdf_path,
        output_root,
        raw_output_dir,
        version,
        selected_backend,
    )


def discover_pdfs(paths: Iterable[Path]) -> list[Path]:
    """Resolve explicit PDF paths, or all PDFs in the hardware dataset."""
    resolved = [path.resolve() for path in paths]
    if resolved:
        return resolved
    return sorted(
        path.resolve()
        for path in RAW_HARDWARE_DIR.iterdir()
        if path.is_file() and path.suffix.lower() == ".pdf"
    )


def _format_counts(segments: Sequence[dict[str, Any]]) -> str:
    counts = Counter(segment["type"] for segment in segments)
    return (
        f"text={counts['text']}, figure={counts['figure']}, "
        f"table={counts['table']} (total={len(segments)})"
    )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Parse hardware datasheet PDFs with MinerU VLM, falling back to "
            "MinerU pipeline mode when VLM cannot run. With no PDF arguments, "
            "all PDFs in data/raw/hardware are parsed."
        )
    )
    parser.add_argument("pdfs", nargs="*", type=Path, help="PDF path(s) to parse")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PARSED_HARDWARE_DIR,
        help="normalized output root (default: data/parsed/hardware)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="optional per-backend timeout in seconds",
    )
    parser.add_argument(
        "--no-pipeline-fallback",
        action="store_true",
        help="fail instead of retrying with MinerU's pipeline backend",
    )
    parser.add_argument(
        "--pipeline-only",
        action="store_true",
        help="skip VLM and use MinerU's lighter pipeline backend directly",
    )
    parser.add_argument(
        "--normalize-only",
        action="store_true",
        help="normalize an existing raw MinerU run without rerunning inference",
    )
    parser.add_argument(
        "--pages-per-batch",
        type=int,
        default=None,
        help=(
            "parse bounded page ranges and merge them; useful for long PDFs "
            "that exceed available memory"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    if args.pages_per_batch is not None and args.pages_per_batch <= 0:
        print("--pages-per-batch must be positive.", file=sys.stderr)
        return 2

    pdfs = discover_pdfs(args.pdfs)
    if not pdfs:
        print(
            f"No PDFs found in {RAW_HARDWARE_DIR}. Add the five project datasheets "
            "or pass explicit paths.",
            file=sys.stderr,
        )
        return 2

    print(f"MinerU {mineru_version()}: parsing {len(pdfs)} document(s).", flush=True)
    results: list[tuple[str, list[dict[str, Any]], str]] = []
    failures: list[tuple[Path, Exception]] = []

    for index, pdf_path in enumerate(pdfs, start=1):
        print(f"\n[{index}/{len(pdfs)}] {pdf_path.name}", flush=True)
        try:
            if args.normalize_only:
                segments, backend = normalize_existing_parse(
                    pdf_path,
                    output_root=args.output_root,
                )
            else:
                segments, backend = parse_pdf(
                    pdf_path,
                    output_root=args.output_root,
                    timeout=args.timeout,
                    allow_pipeline_fallback=not args.no_pipeline_fallback,
                    try_vlm=not args.pipeline_only,
                    pages_per_batch=args.pages_per_batch,
                )
        except (MinerUError, OSError, ValueError) as exc:
            failures.append((pdf_path, exc))
            print(f"  FAILED: {exc}", file=sys.stderr, flush=True)
            continue
        results.append((pdf_path.name, segments, backend))
        print(f"  Extracted {_format_counts(segments)} via {backend}.", flush=True)

    print("\nSegment counts by document:")
    for name, segments, backend in results:
        print(f"  {name}: {_format_counts(segments)} [{backend}]")
    for path, exc in failures:
        print(f"  {path.name}: FAILED ({exc})")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
