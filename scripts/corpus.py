"""Load corpus and document configuration from the project registry."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

from scripts.config import active_index_dir, embed_provider

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = PROJECT_ROOT / "corpora.json"


class CorpusRegistryError(RuntimeError):
    """Raised when the corpus registry is missing or malformed."""


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    corpus_id: str


@dataclass(frozen=True)
class Corpus:
    corpus_id: str
    title: str
    blurb: str
    evaluated: bool
    index_dir: Path
    parsed_dir: Path
    raw_dir: Path
    documents: tuple[Document, ...]


def _required_text(payload: dict[str, Any], key: str, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CorpusRegistryError(f"{context} has no non-empty {key!r} value.")
    return value.strip()


def _project_path(payload: dict[str, Any], key: str, context: str) -> Path:
    configured = Path(_required_text(payload, key, context)).expanduser()
    if not configured.is_absolute():
        configured = PROJECT_ROOT / configured
    return configured.resolve()


@lru_cache(maxsize=1)
def load_registry() -> tuple[Corpus, ...]:
    """Return the validated registry with paths resolved from ``PROJECT_ROOT``."""
    try:
        payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusRegistryError(f"Could not read {REGISTRY_PATH}: {exc}") from exc

    raw_corpora = payload.get("corpora") if isinstance(payload, dict) else None
    if not isinstance(raw_corpora, list) or not raw_corpora:
        raise CorpusRegistryError("corpora.json must contain a non-empty 'corpora' list.")

    corpora: list[Corpus] = []
    corpus_ids: set[str] = set()
    document_ids: set[str] = set()
    for corpus_number, raw_corpus in enumerate(raw_corpora, start=1):
        context = f"Corpus {corpus_number}"
        if not isinstance(raw_corpus, dict):
            raise CorpusRegistryError(f"{context} is not an object.")

        corpus_id = _required_text(raw_corpus, "corpus_id", context)
        if corpus_id in corpus_ids:
            raise CorpusRegistryError(f"Duplicate corpus_id {corpus_id!r}.")
        corpus_ids.add(corpus_id)

        evaluated = raw_corpus.get("evaluated")
        if not isinstance(evaluated, bool):
            raise CorpusRegistryError(f"{context} has no boolean 'evaluated' value.")

        raw_documents = raw_corpus.get("documents")
        if not isinstance(raw_documents, list) or not raw_documents:
            raise CorpusRegistryError(f"{context} must contain documents.")

        documents: list[Document] = []
        for document_number, raw_document in enumerate(raw_documents, start=1):
            document_context = f"{context} document {document_number}"
            if not isinstance(raw_document, dict):
                raise CorpusRegistryError(f"{document_context} is not an object.")
            doc_id = _required_text(raw_document, "doc_id", document_context)
            if doc_id in document_ids:
                raise CorpusRegistryError(f"Duplicate doc_id {doc_id!r}.")
            document_ids.add(doc_id)
            documents.append(
                Document(
                    doc_id=doc_id,
                    title=_required_text(raw_document, "title", document_context),
                    corpus_id=corpus_id,
                )
            )

        corpora.append(
            Corpus(
                corpus_id=corpus_id,
                title=_required_text(raw_corpus, "title", context),
                blurb=_required_text(raw_corpus, "blurb", context),
                # Hand-graded results describe the Azure-embedded index only.
                evaluated=evaluated and embed_provider() == "azure",
                index_dir=active_index_dir(_project_path(raw_corpus, "index_dir", context)),
                parsed_dir=_project_path(raw_corpus, "parsed_dir", context),
                raw_dir=_project_path(raw_corpus, "raw_dir", context),
                documents=tuple(documents),
            )
        )
    return tuple(corpora)


def get_document(doc_id: str) -> Document:
    """Return a registered document or raise ``KeyError``."""
    for corpus in load_registry():
        for document in corpus.documents:
            if document.doc_id == doc_id:
                return document
    raise KeyError(f"Unknown document: {doc_id}")


def get_corpus(corpus_id: str) -> Corpus:
    """Return a registered corpus or raise ``KeyError``."""
    for corpus in load_registry():
        if corpus.corpus_id == corpus_id:
            return corpus
    raise KeyError(f"Unknown corpus: {corpus_id}")


def corpus_for_document(doc_id: str) -> Corpus:
    """Return the corpus containing ``doc_id`` or raise ``KeyError``."""
    return get_corpus(get_document(doc_id).corpus_id)
