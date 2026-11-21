"""Knowledge-retrieval interface. The BM25 implementation over the methodology corpus is Step 4."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class Passage(BaseModel):
    doc_id: str
    title: str
    section: str
    source_url: str
    text: str
    score: float


class KnowledgeBase(Protocol):
    def search(self, query: str, top_k: int) -> list[Passage]: ...
