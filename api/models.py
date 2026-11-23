"""Pydantic models for the M-RAG HTTP API."""

from typing import Literal

from pydantic import BaseModel, Field


ChatMode = Literal["mrag", "text_only", "plain"]
HistoryRole = Literal["user", "assistant"]


class HistoryMessage(BaseModel):
    """One prior chat turn supplied to the router and answer generator."""

    role: HistoryRole
    content: str


class ChatRequest(BaseModel):
    """Request body for the streaming chat endpoint."""

    message: str = Field(min_length=1)
    mode: ChatMode
    doc: str | None = None
    corpus_id: str | None = None
    scope: Literal["document", "collection"] = "document"
    history: list[HistoryMessage] = Field(default_factory=list)
    k: int = Field(default=5, ge=1, le=20)
