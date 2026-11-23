"""Knowledge retrieval for ``search_knowledge``: BM25 over the reviewed methodology corpus.

The corpus is a folder of Markdown documents (``rag/corpus/*.md``), each with a small front-matter
block (doc_id, title, source_url, ...) and ``## `` sections. Each section is one chunk, and a
chunk's document title and section heading are counted extra, because the planner's queries are
short labels ("ZHVI tier percentile"). The index is built in memory at startup; the corpus is a few
thousand words, so there is no vector store (design doc §13).

Retrieved text is data, not instructions: the answer writer quotes it with its source.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "me",
        "of",
        "on",
        "or",
        "the",
        "this",
        "to",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "you",
        "your",
    ]
)
HEADING_WEIGHT = 3  # title and section words count this many times
# A few domain synonyms, applied to queries and documents alike, so the planner's short labels
# ("ZHVI definition", "ZORI methodology") meet the corpus wording ("what ZHVI measures",
# "how ZORI is calculated").
SYNONYMS = {
    **dict.fromkeys(
        ["definition", "define", "defined", "meaning", "mean", "means", "stand"], "measure"
    ),
    **dict.fromkeys(
        [
            "methodology",
            "method",
            "calculation",
            "calculated",
            "compute",
            "computed",
            "built",
            "build",
            "construct",
            "constructed",
        ],
        "calculate",
    ),
    **dict.fromkeys(
        ["frequency", "frequently", "often", "refreshed", "refresh", "current"], "update"
    ),
    **dict.fromkeys(["gap", "missing", "lack"], "missing"),
}
K1, B = 1.5, 0.75


class Passage(BaseModel):
    doc_id: str
    title: str
    section: str
    source_url: str
    text: str
    score: float


class KnowledgeBase(Protocol):
    def search(self, query: str, top_k: int) -> list[Passage]: ...


def tokenize(text: str) -> list[str]:
    tokens = []
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        if word in STOPWORDS:
            continue
        if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]  # light plural folding: rents -> rent, values -> value
        tokens.append(SYNONYMS.get(word, word))
    return tokens


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    title: str
    section: str
    source_url: str
    text: str


def parse_document(path: Path) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n(.*)", raw, re.S)
    if not match:
        raise ValueError(f"{path.name}: missing front matter")
    meta = dict(line.split(":", 1) for line in match.group(1).splitlines() if ":" in line)
    meta = {k.strip(): v.strip() for k, v in meta.items()}
    for key in ("doc_id", "title", "source_url"):
        if not meta.get(key):
            raise ValueError(f"{path.name}: front matter needs {key!r}")
    chunks = []
    for block in re.split(r"^## ", match.group(2), flags=re.M)[1:]:
        heading, _, body = block.partition("\n")
        text = " ".join(body.split())
        if text:
            chunks.append(Chunk(meta["doc_id"], meta["title"], heading.strip(),
                                meta["source_url"], text))  # fmt: skip
    if not chunks:
        raise ValueError(f"{path.name}: no '## ' sections")
    return chunks


class BM25KnowledgeBase:
    def __init__(self, chunks: list[Chunk], version: str = ""):
        self.chunks = chunks
        self.version = version
        self._docs = [
            tokenize(c.text) + HEADING_WEIGHT * tokenize(f"{c.title} {c.section}") for c in chunks
        ]
        self._tf = [Counter(d) for d in self._docs]
        self._avg_len = sum(len(d) for d in self._docs) / max(len(self._docs), 1)
        df = Counter(term for d in self._docs for term in set(d))
        n = len(self._docs)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    @classmethod
    def from_dir(cls, path: Path | str) -> BM25KnowledgeBase:
        files = sorted(Path(path).glob("*.md"))
        if not files:
            raise FileNotFoundError(f"no corpus documents in {path}")
        digest = hashlib.sha256(b"".join(f.read_bytes() for f in files)).hexdigest()[:10]
        return cls([chunk for f in files for chunk in parse_document(f)], version=digest)

    def _score(self, query: list[str], i: int) -> float:
        tf, length = self._tf[i], len(self._docs[i])
        score = 0.0
        for term in query:
            if term in tf:
                f = tf[term]
                norm = f * (K1 + 1) / (f + K1 * (1 - B + B * length / self._avg_len))
                score += self._idf.get(term, 0.0) * norm
        return score

    def search(self, query: str, top_k: int) -> list[Passage]:
        terms = tokenize(query)
        scored = [(self._score(terms, i), i) for i in range(len(self.chunks))]
        ranked = sorted((s for s in scored if s[0] > 0), key=lambda s: (-s[0], s[1]))[:top_k]
        return [
            Passage(doc_id=c.doc_id, title=c.title, section=c.section, source_url=c.source_url,
                    text=c.text, score=round(score, 3))
            for score, i in ranked
            for c in [self.chunks[i]]
        ]  # fmt: skip
