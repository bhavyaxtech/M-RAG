"""FastAPI and SSE transport for the M-RAG conversational agent."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import mimetypes
from pathlib import Path
import threading
import time
from typing import Any, cast
from uuid import uuid4

import faiss
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import pymupdf

from api.models import ChatRequest
from scripts.agent import (
    Evidence,
    RouterDecision,
    RELEVANCE_FLOOR,
    answer_stream,
    cited_labels,
    gather_evidence,
    generation_deployment,
    plain_stream,
    provenance,
    route_question,
    router_deployment,
)
from scripts.azure_client import warm_up
from scripts.corpus import (
    Corpus,
    Document,
    corpus_for_document,
    get_corpus,
    get_document,
    load_registry,
)
from scripts.embed_and_index import (
    METADATA_FILENAME,
    MRAG_INDEX_FILENAME,
    RUN_METADATA_FILENAME,
    TEXT_ONLY_INDEX_FILENAME,
    VISUAL_TYPES,
)
from scripts.query import QueryMode


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PAGE_CACHE_DIR = PROJECT_ROOT / "data" / "page_cache"
STATIC_UI_DIR = Path(__file__).resolve().parent / "static"


@dataclass(frozen=True)
class ModelNames:
    """Model and deployment names shown in API provenance."""

    embedding: str
    generation: str
    router: str


@dataclass(frozen=True)
class StartupState:
    """Read-only artifacts loaded once for the process lifetime."""

    meta: dict[str, Any]
    image_paths: dict[str, Path]
    bboxes: dict[str, dict[str, Any]]
    indexes_ready: bool
    models: ModelNames


def _safe_contained_path(candidate: Path, root: Path) -> Path | None:
    try:
        resolved = candidate.resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    return resolved


def _safe_raw_pdf_path(doc_id: str) -> Path | None:
    """Resolve a registered document PDF without trusting the path parameter."""
    try:
        document = get_document(doc_id)
        corpus = corpus_for_document(document.doc_id)
    except KeyError:
        return None
    return _safe_contained_path(
        corpus.raw_dir / f"{document.doc_id}.pdf",
        corpus.raw_dir,
    )


def _zero_document(document: Document) -> dict[str, Any]:
    return {
        "doc_id": document.doc_id,
        "title": document.title,
        "pages": 0,
        "segments": 0,
        "text": 0,
        "figures": 0,
        "tables": 0,
        "text_vectors": 0,
        "visual_vectors": 0,
        "visual_share": 0.0,
        "has_pdf": False,
    }


def _document_stats(
    document: Document,
    corpus: Corpus,
    vector_counts: Mapping[str, Mapping[str, int]],
) -> dict[str, Any]:
    """Count parsed segments and indexed vectors for one registered document."""
    result = _zero_document(document)
    segments_path = corpus.parsed_dir / document.doc_id / "segments.json"
    if not segments_path.is_file():
        payload: Any = []
    else:
        try:
            payload = json.loads(segments_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = []

    pages: list[int] = []
    if isinstance(payload, list):
        for segment in payload:
            if not isinstance(segment, dict):
                continue
            page = segment.get("page")
            if isinstance(page, int) and not isinstance(page, bool) and page > 0:
                pages.append(page)

            segment_type = segment.get("type")
            if segment_type not in {"text", *VISUAL_TYPES}:
                continue
            result["segments"] += 1
            if segment_type == "text":
                result["text"] += 1
            elif segment_type == "figure":
                result["figures"] += 1
            elif segment_type == "table":
                result["tables"] += 1

    counts = vector_counts.get(document.doc_id, {})
    text_vectors = int(counts.get("text", 0))
    visual_vectors = int(counts.get("visual", 0))
    vector_total = text_vectors + visual_vectors
    result["pages"] = max(pages, default=0)
    result["text_vectors"] = text_vectors
    result["visual_vectors"] = visual_vectors
    result["visual_share"] = (
        round(visual_vectors / vector_total, 3) if vector_total else 0.0
    )
    pdf_path = _safe_raw_pdf_path(document.doc_id)
    result["has_pdf"] = bool(pdf_path is not None and pdf_path.is_file())
    if result["has_pdf"]:
        try:
            with pymupdf.open(pdf_path) as source_pdf:
                result["pages"] = source_pdf.page_count
        except (OSError, RuntimeError, ValueError):
            pass  # Retain the parsed-page fallback if the PDF cannot be opened.
    return result


def _read_run_metadata(corpus: Corpus) -> dict[str, Any]:
    path = corpus.index_dir / RUN_METADATA_FILENAME
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _metadata_text(payload: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _index_dimensions(corpus: Corpus) -> int:
    index_path = corpus.index_dir / MRAG_INDEX_FILENAME
    if not index_path.is_file():
        return 0
    try:
        return int(faiss.read_index(str(index_path)).d)
    except (OSError, RuntimeError, ValueError):
        return 0


def _safe_parsed_image_path(
    image_path: object,
    parsed_dir: Path | None = None,
) -> Path | None:
    """Resolve a metadata image only when it remains under parsed data."""
    if not isinstance(image_path, str) or not image_path.strip():
        return None

    candidate = Path(image_path).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    parsed_roots = (
        (parsed_dir,) if parsed_dir is not None else tuple(
            corpus.parsed_dir for corpus in load_registry()
        )
    )
    for parsed_root in parsed_roots:
        resolved = _safe_contained_path(candidate, parsed_root)
        if resolved is not None:
            return resolved
    return None


def _load_image_paths() -> dict[str, Path]:
    """Build the segment image map once from index metadata."""
    image_paths: dict[str, Path] = {}
    for corpus in load_registry():
        metadata_path = corpus.index_dir / METADATA_FILENAME
        if not metadata_path.is_file():
            continue
        try:
            lines = metadata_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                not isinstance(payload, dict)
                or payload.get("type") not in VISUAL_TYPES
            ):
                continue
            segment_id = payload.get("segment_id")
            path = _safe_parsed_image_path(
                payload.get("image_path"),
                corpus.parsed_dir,
            )
            if isinstance(segment_id, str) and segment_id.strip() and path is not None:
                image_paths.setdefault(segment_id, path)
    return image_paths


def _load_bboxes() -> dict[str, dict[str, Any]]:
    """Load extracted visual bounds once for evidence serialization."""
    bboxes: dict[str, dict[str, Any]] = {}
    for corpus in load_registry():
        for document in corpus.documents:
            path = corpus.parsed_dir / document.doc_id / "bboxes.json"
            if not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            for segment_id, bbox_payload in payload.items():
                if isinstance(segment_id, str) and isinstance(bbox_payload, dict):
                    bboxes.setdefault(segment_id, bbox_payload)
    return bboxes


def _vector_counts(corpus: Corpus) -> dict[str, dict[str, int]]:
    """Count actual metadata rows by document and retrievable modality."""
    counts = {
        document.doc_id: {"text": 0, "visual": 0}
        for document in corpus.documents
    }
    metadata_path = corpus.index_dir / METADATA_FILENAME
    if not metadata_path.is_file():
        return counts
    try:
        lines = metadata_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return counts

    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        document_counts = counts.get(payload.get("doc"))
        if document_counts is None:
            continue
        if payload.get("type") == "text":
            document_counts["text"] += 1
        elif payload.get("type") in VISUAL_TYPES:
            document_counts["visual"] += 1
    return counts


def _indexes_ready() -> bool:
    return all(
        path.is_file()
        for corpus in load_registry()
        for path in (
            corpus.index_dir / MRAG_INDEX_FILENAME,
            corpus.index_dir / TEXT_ONLY_INDEX_FILENAME,
            corpus.index_dir / METADATA_FILENAME,
        )
    )


def _load_startup_state() -> StartupState:
    corpora = load_registry()
    run_metadata_by_corpus = {
        corpus.corpus_id: _read_run_metadata(corpus) for corpus in corpora
    }
    fallback_run_metadata = next(
        (
            metadata
            for metadata in run_metadata_by_corpus.values()
            if metadata
        ),
        {},
    )

    try:
        generation = generation_deployment()
        router = router_deployment()
    except (OSError, RuntimeError, ValueError):
        generation = _metadata_text(fallback_run_metadata, "generation_deployment")
        router = _metadata_text(fallback_run_metadata, "router_deployment")

    models = ModelNames(
        embedding=_metadata_text(
            fallback_run_metadata,
            "embedding_model",
            "embedding_deployment",
        ),
        generation=generation,
        router=router,
    )

    corpus_payloads: list[dict[str, Any]] = []
    for corpus in corpora:
        vector_counts = _vector_counts(corpus)
        documents = [
            _document_stats(document, corpus, vector_counts)
            for document in corpus.documents
        ]
        text_vectors = sum(int(document["text_vectors"]) for document in documents)
        visual_vectors = sum(
            int(document["visual_vectors"]) for document in documents
        )
        run_metadata = run_metadata_by_corpus[corpus.corpus_id]
        corpus_payloads.append(
            {
                "corpus_id": corpus.corpus_id,
                "title": corpus.title,
                "blurb": corpus.blurb,
                "evaluated": corpus.evaluated,
                "documents": documents,
                "totals": {
                    "documents": len(documents),
                    "pages": sum(int(document["pages"]) for document in documents),
                    "segments": sum(
                        int(document["segments"]) for document in documents
                    ),
                    "text_vectors": text_vectors,
                    "visual_vectors": visual_vectors,
                    "vectors": text_vectors + visual_vectors,
                },
                "index": {
                    "type": _metadata_text(run_metadata, "vector_store")
                    or "faiss.IndexFlatIP",
                    "normalized": bool(
                        run_metadata.get("embeddings_normalized", True)
                    ),
                    "dimensions": _index_dimensions(corpus),
                },
            }
        )

    meta = {
        "corpora": corpus_payloads,
        "models": {
            "embedding": models.embedding,
            "generation": models.generation,
            "router": models.router,
        },
        "relevance_floor": float(RELEVANCE_FLOOR),
    }
    return StartupState(
        meta=meta,
        image_paths=_load_image_paths(),
        bboxes=_load_bboxes(),
        indexes_ready=_indexes_ready(),
        models=models,
    )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    app.state.startup = _load_startup_state()
    # Loading a local embedder or probing the Codex CLI takes tens of seconds;
    # do it now so the first question does not pay for it.
    threading.Thread(target=warm_up, name="provider-warm-up", daemon=True).start()
    yield


app = FastAPI(title="M-RAG API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _startup(request: Request) -> StartupState:
    state = getattr(request.app.state, "startup", None)
    if not isinstance(state, StartupState):
        state = _load_startup_state()
        request.app.state.startup = state
    return state


def _sse_frame(payload: Mapping[str, Any]) -> str:
    return f"data: {json.dumps(dict(payload), ensure_ascii=False, separators=(',', ':'))}\n\n"


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _numeric_values(value: object, length: int) -> list[int | float] | None:
    if not isinstance(value, list) or len(value) != length:
        return None
    if not all(
        isinstance(item, (int, float)) and not isinstance(item, bool) for item in value
    ):
        return None
    return list(value)


def _evidence_payload(
    evidence: Evidence,
    bboxes: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    segments: list[dict[str, Any]] = []
    for segment in evidence.segments:
        segment_id = str(segment.get("segment_id", ""))
        doc_id = str(segment.get("doc", ""))
        page = int(segment.get("page", 0))
        segment_type = str(segment.get("type", "text"))
        try:
            doc_title = get_document(doc_id).title
        except KeyError:
            doc_title = doc_id
        pdf_path = _safe_raw_pdf_path(doc_id)
        source_segment_id = str(segment.get("source_segment_id", segment_id))
        bbox_payload = (bboxes or {}).get(source_segment_id)
        bbox = None
        if isinstance(bbox_payload, Mapping) and bbox_payload.get("page") == page:
            bbox = _numeric_values(bbox_payload.get("bbox"), 4)
        segments.append(
            {
                "label": str(segment.get("label", "")),
                "segment_id": segment_id,
                "doc": doc_id,
                "doc_title": doc_title,
                "page": page,
                "type": segment_type,
                "score": float(segment.get("score", 0.0)),
                "text": str(segment.get("text_or_caption", "")),
                "image_url": (
                    f"/api/image/{segment_id}"
                    if segment_type in VISUAL_TYPES
                    else None
                ),
                "page_url": (
                    f"/api/page/{doc_id}/{page}"
                    if page > 0 and pdf_path is not None and pdf_path.is_file()
                    else None
                ),
                "bbox": bbox,
            }
        )
    return {
        "type": "evidence",
        "grounded": bool(evidence.grounded),
        "page_addressed": bool(evidence.page_addressed),
        "requested_page": evidence.requested_page,
        "top_score": float(evidence.top_score),
        "segments": segments,
    }


def _model_payload(models: ModelNames) -> dict[str, str]:
    return {"generation": models.generation, "router": models.router}


def _resolve_chat_corpus(chat_request: ChatRequest) -> Corpus:
    """Validate explicit selectors before an HTTP response starts streaming."""
    corpus = None
    if chat_request.corpus_id is not None:
        try:
            corpus = get_corpus(chat_request.corpus_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown corpus_id") from exc

    if chat_request.doc is not None:
        try:
            document_corpus = corpus_for_document(chat_request.doc)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown doc") from exc
        if corpus is not None and corpus.corpus_id != document_corpus.corpus_id:
            raise HTTPException(
                status_code=422,
                detail="doc does not belong to corpus_id",
            )
        corpus = document_corpus
    elif corpus is not None and chat_request.scope == "document":
        raise HTTPException(
            status_code=422,
            detail="doc is required for scope=document when corpus_id is supplied",
        )

    if corpus is not None:
        return corpus
    if chat_request.scope == "collection":
        raise HTTPException(
            status_code=422,
            detail="corpus_id or doc is required for scope=collection",
        )
    # Only legacy document requests with neither selector keep the default corpus.
    return load_registry()[0]


def _chat_events(
    chat_request: ChatRequest,
    state: StartupState,
    corpus: Corpus | None = None,
) -> Iterator[str]:
    started = time.perf_counter()
    history = [
        {"role": item.role, "content": item.content}
        for item in chat_request.history
    ]
    answer_parts: list[str] = []
    evidence = Evidence()
    decision: RouterDecision | None = None
    route_ms = 0
    retrieve_ms = 0
    first_token_ms = 0
    first_token_seen = False
    has_read_stage = False

    try:
        if chat_request.mode == "plain":
            yield _sse_frame({"type": "stage", "stage": "answer", "status": "active"})
            generated = plain_stream(chat_request.message)
        else:
            mode = cast(QueryMode, chat_request.mode)
            if corpus is None:
                corpus = _resolve_chat_corpus(chat_request)
            docs = (chat_request.doc,) if chat_request.doc is not None else None
            active_document = chat_request.doc
            if chat_request.scope == "collection":
                docs = None
                active_document = None
            available_document_titles = tuple(
                registered_document.title
                for registered_document in corpus.documents
            )
            yield _sse_frame({"type": "stage", "stage": "route", "status": "active"})
            route_started = time.perf_counter()
            decision = route_question(
                chat_request.message,
                history,
                document=active_document,
                available_document_titles=available_document_titles,
            )
            route_ms = int((time.perf_counter() - route_started) * 1000)
            yield _sse_frame(
                {
                    "type": "route",
                    "route": decision.route,
                    "search_query": decision.search_query,
                    "page": decision.page,
                    "confidence": decision.confidence,
                    "reason": decision.reason,
                    "fallback": decision.fallback,
                }
            )
            yield _sse_frame({"type": "stage", "stage": "route", "status": "done"})

            if decision.route == "datasheet":
                yield _sse_frame(
                    {"type": "stage", "stage": "retrieve", "status": "active"}
                )
                retrieve_started = time.perf_counter()
                evidence = gather_evidence(
                    decision.search_query,
                    mode,
                    k=chat_request.k,
                    index_dir=corpus.index_dir,
                    docs=docs,
                    page=decision.page,
                    collection=chat_request.scope == "collection",
                    reference_query=chat_request.message,
                )
                retrieve_ms = int((time.perf_counter() - retrieve_started) * 1000)
                yield _sse_frame(_evidence_payload(evidence, state.bboxes))
                yield _sse_frame(
                    {"type": "stage", "stage": "retrieve", "status": "done"}
                )

            has_read_stage = (
                chat_request.mode == "mrag"
                and evidence.grounded
                and (
                    evidence.requested_page is None or evidence.page_addressed
                )
                and evidence.visual_count > 0
            )
            if has_read_stage:
                yield _sse_frame({"type": "stage", "stage": "read", "status": "active"})
            yield _sse_frame({"type": "stage", "stage": "answer", "status": "active"})
            generated = answer_stream(
                chat_request.message,
                decision,
                evidence,
                mode,
                history,
                document=active_document,
                available_document_titles=available_document_titles,
            )

        for delta in generated:
            if not delta:
                continue
            if not first_token_seen:
                first_token_seen = True
                first_token_ms = _elapsed_ms(started)
                if chat_request.mode != "plain" and has_read_stage:
                    yield _sse_frame(
                        {"type": "stage", "stage": "read", "status": "done"}
                    )
            answer_parts.append(delta)
            yield _sse_frame({"type": "token", "text": delta})

        answer = "".join(answer_parts)
        total_ms = _elapsed_ms(started)
        if chat_request.mode == "plain":
            cited: list[str] = []
            answer_provenance = "plain"
        else:
            if decision is None:
                raise RuntimeError("router decision was not produced")
            cited = cited_labels(answer, evidence.segments)
            answer_provenance = provenance(decision, evidence, cited)
        yield _sse_frame(
            {
                "type": "done",
                "answer": answer,
                "cited": cited,
                "provenance": answer_provenance,
                "timings_ms": {
                    "route": route_ms,
                    "retrieve": retrieve_ms,
                    "first_token": first_token_ms,
                    "total": total_ms,
                },
                "models": _model_payload(state.models),
            }
        )
    except Exception as exc:
        yield _sse_frame({"type": "error", "message": str(exc)})


@app.get("/api/health")
def health(request: Request) -> dict[str, bool | str]:
    """Return service status and whether the persisted indexes are available."""
    state = _startup(request)
    return {"status": "ok", "indexes_ready": state.indexes_ready}


@app.get("/api/meta")
def meta(request: Request) -> dict[str, Any]:
    """Return cached corpus, model, and index provenance."""
    return _startup(request).meta


@app.post("/api/chat")
def chat(chat_request: ChatRequest, request: Request) -> StreamingResponse:
    """Stream one agent turn as compact server-sent JSON events."""
    corpus = _resolve_chat_corpus(chat_request)
    state = _startup(request)
    return StreamingResponse(
        _chat_events(chat_request, state, corpus),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/image/{segment_id}")
def image(segment_id: str, request: Request) -> FileResponse:
    """Serve a known cropped visual segment from parsed data."""
    path = _startup(request).image_paths.get(segment_id)
    safe_path = _safe_parsed_image_path(str(path)) if path is not None else None
    if safe_path is None or not safe_path.is_file():
        raise HTTPException(status_code=404, detail="image not found")
    media_type = mimetypes.guess_type(safe_path.name)[0] or "application/octet-stream"
    return FileResponse(
        safe_path,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get("/api/page/{doc}/{page}")
def page_image(doc: str, page: int) -> FileResponse:
    """Render and cache one page from a registered source PDF at 144 DPI."""
    pdf_path = _safe_raw_pdf_path(doc)
    if pdf_path is None or not pdf_path.is_file() or page < 1:
        raise HTTPException(status_code=404, detail="page not found")

    try:
        with pymupdf.open(str(pdf_path)) as pdf_document:
            if page > pdf_document.page_count:
                raise HTTPException(status_code=404, detail="page not found")

            PAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            registered_doc_id = get_document(doc).doc_id
            cache_path = _safe_contained_path(
                PAGE_CACHE_DIR / f"{registered_doc_id}-p{page:04d}.png",
                PAGE_CACHE_DIR,
            )
            if cache_path is None:
                raise HTTPException(status_code=404, detail="page not found")

            if not cache_path.is_file():
                temporary_path = cache_path.with_name(
                    f".{cache_path.stem}.{uuid4().hex}.tmp.png"
                )
                try:
                    rendered_page = pdf_document.load_page(page - 1).get_pixmap(
                        dpi=144,
                        alpha=False,
                    )
                    rendered_page.save(str(temporary_path))
                    temporary_path.replace(cache_path)
                finally:
                    if temporary_path.exists():
                        temporary_path.unlink()
    except HTTPException:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="page render failed") from exc

    return FileResponse(
        cache_path,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


# The exported Next.js UI is mounted last so that every /api/* route above keeps
# precedence. When api/static/ is absent (a dev checkout that runs `pnpm dev`
# separately on port 3000) the mount is skipped and the API serves JSON only.
if STATIC_UI_DIR.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=STATIC_UI_DIR, html=True),
        name="ui",
    )
