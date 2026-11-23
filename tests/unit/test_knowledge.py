"""BM25 retrieval over the methodology corpus (rag/corpus) and its wiring into the agent."""

from pathlib import Path

import pytest

from tools.knowledge import BM25KnowledgeBase, Chunk, parse_document, tokenize

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "rag" / "corpus"

# The planner's search_knowledge queries (training/templates.py METHODOLOGY_TOPICS) and the
# section each must retrieve first. This is the retrieval eval: the LoRA planner emits these.
EXPECTED_TOP1 = {
    "ZHVI definition": ("zhvi", "What ZHVI measures"),
    "ZORI definition": ("zori", "What ZORI measures"),
    "ZHVI methodology": ("zhvi", "How ZHVI is calculated"),
    "ZORI methodology": ("zori", "How ZORI is calculated"),
    "smoothing seasonal adjustment": ("zhvi", "Smoothing and seasonal adjustment"),
    "ZHVI tier percentile": ("zhvi", "Tiers and the series used here"),
    "ZHVI vs ZORI": ("zhvi_vs_zori", "Differences between ZHVI and ZORI"),
    "ZHVI sale price appraisal limitations": ("zhvi", "Limitations of ZHVI"),
    "data update frequency": ("data_coverage", "How often the data is updated"),
    "city geography definition": ("data_coverage", "Geography of the city series"),
    "missing months data coverage": ("data_coverage", "Why some months are missing"),
    "ZORI housing types": ("zori", "Housing types in ZORI"),
    "ZORI asking rent observed rent": ("zori", "Asking rent versus rent paid"),
}


@pytest.fixture(scope="module")
def kb():
    return BM25KnowledgeBase.from_dir(CORPUS)


def test_every_planner_query_has_an_expected_section():
    from training.templates import METHODOLOGY_TOPICS

    assert {q for q, _ in METHODOLOGY_TOPICS} == set(EXPECTED_TOP1)


@pytest.mark.parametrize("query, expected", EXPECTED_TOP1.items())
def test_planner_queries_retrieve_the_right_section_first(kb, query, expected):
    top = kb.search(query, 3)[0]
    assert (top.doc_id, top.section) == expected


def test_passages_carry_source_metadata(kb):
    hits = kb.search("ZORI asking rent", 2)
    assert len(hits) == 2 and all(h.source_url.startswith("https://") for h in hits)
    assert hits[0].score >= hits[1].score > 0


def test_unrelated_or_empty_queries_return_nothing(kb):
    assert kb.search("", 3) == []
    assert kb.search("the of and", 3) == []  # stopwords only


def test_corpus_version_is_a_content_hash(kb, tmp_path):
    assert kb.version == BM25KnowledgeBase.from_dir(CORPUS).version
    (tmp_path / "a.md").write_text(
        "---\ndoc_id: a\ntitle: A\nsource_url: https://x\n---\n## S\nText one.\n"
    )
    v1 = BM25KnowledgeBase.from_dir(tmp_path).version
    (tmp_path / "a.md").write_text(
        "---\ndoc_id: a\ntitle: A\nsource_url: https://x\n---\n## S\nText two.\n"
    )
    assert BM25KnowledgeBase.from_dir(tmp_path).version != v1


def test_documents_need_front_matter_and_sections(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text("## Section\nNo front matter.\n")
    with pytest.raises(ValueError, match="front matter"):
        parse_document(bad)
    bad.write_text("---\ndoc_id: x\ntitle: X\nsource_url: https://x\n---\nNo sections.\n")
    with pytest.raises(ValueError, match="sections"):
        parse_document(bad)


def test_tokenizer_folds_plurals_and_synonyms():
    assert tokenize("What are rents?") == ["rent"]
    assert tokenize("ZHVI definition") == tokenize("ZHVI measures")
    assert tokenize("methodology") == tokenize("calculated")
    assert "ss" not in tokenize("class")  # no stray folding


def test_every_corpus_document_parses_with_citations():
    for path in sorted(CORPUS.glob("*.md")):
        chunks = parse_document(path)
        assert chunks and all(isinstance(c, Chunk) and c.source_url for c in chunks)


# ---- wired into the agent and API --------------------------------------------------------------


def test_methodology_question_is_answered_with_sources(db, kb):
    from agent.model_clients.stub import ScriptedModelClient
    from agent.orchestrator import Agent

    call = {"call": {"tool": "search_knowledge", "query": "ZORI asking rent observed rent"}}
    reply = "ZORI reflects asking rents on listed units, not rents in signed leases."
    r = Agent(db, ScriptedModelClient([call, reply]), knowledge=kb).run_turn("Is ZORI asking rent?")
    assert (r.kind, r.answer_source) == ("answer", "model")
    assert r.sources[0].section == "Asking rent versus rent paid"


def test_api_loads_the_corpus_and_reports_it(db, monkeypatch):
    from fastapi.testclient import TestClient

    from agent.model_clients.stub import StubModelClient, demo_rules
    from agent.orchestrator import Agent
    from api.main import create_app, knowledge_from_env

    monkeypatch.setenv("RAG_CORPUS_DIR", str(CORPUS))
    kb = knowledge_from_env()
    assert kb is not None and len(kb.chunks) >= 15
    agent = Agent(db, StubModelClient(rules=demo_rules()), knowledge=kb)
    with TestClient(create_app(agent=agent)) as client:
        catalog = client.get("/v1/catalog").json()
        body = client.post(
            "/v1/ask", json={"question": "What is ZORI and how is it smoothed?"}
        ).json()
    assert catalog["knowledge"]["version"] == kb.version
    assert {d[0] for d in catalog["knowledge"]["documents"]} >= {"zhvi", "zori"}
    assert body["kind"] == "answer" and body["sources"]  # no longer "knowledge base unavailable"
    monkeypatch.setenv("RAG_BACKEND", "none")
    assert knowledge_from_env() is None


# ---- PR #7 review follow-ups --------------------------------------------------------------------


def test_fallback_quotes_whole_sentences():
    from agent.orchestrator import first_sentences

    text = "First sentence here. Second one is a bit longer. Third sentence would not fit at all."
    assert first_sentences(text, limit=50) == "First sentence here. Second one is a bit longer."
    long = "word " * 200
    out = first_sentences(long, limit=40)
    assert out.endswith("…") and len(out) <= 41 and not out[:-1].endswith(" ")
    for passage in BM25KnowledgeBase.from_dir(CORPUS).chunks:
        assert first_sentences(passage.text)[-1] in ".!?…"


def test_catalog_works_with_a_search_only_knowledge_base(db):
    from fastapi.testclient import TestClient

    from agent.model_clients.stub import StubModelClient
    from agent.orchestrator import Agent
    from api.main import create_app
    from tools.knowledge import Passage

    class SearchOnly:
        def search(self, query, top_k):
            return [
                Passage(
                    doc_id="d", title="T", section="S", source_url="https://x", text="t.", score=1.0
                )
            ]

    with TestClient(create_app(agent=Agent(db, StubModelClient(), knowledge=SearchOnly()))) as c:
        r = c.get("/v1/catalog")
    assert r.status_code == 200 and r.json()["knowledge"]["documents"] == []


def test_statistical_mean_is_not_folded_into_measure():
    assert tokenize("the mean of asking rents") == ["mean", "asking", "rent"]
    assert tokenize("ZHVI definition") == tokenize("ZHVI measures")


def test_coverage_document_matches_the_loaded_dataset():
    """The coverage figures are written into the document; after re-importing newer data, this
    fails until the document is updated. Needs the real dataset, so it's skipped in CI."""
    import re

    from housing.db import HousingDB

    data_dir = ROOT / "data"
    if not (data_dir / "active_version.txt").exists():
        pytest.skip("real dataset not ingested")
    db = HousingDB(data_dir)
    text = (CORPUS / "data_coverage.md").read_text()
    assert f"dataset version {db.dataset_version}" in text
    for metric, label in (("zhvi", "home values"), ("zori", "rents")):
        cov = db.coverage[metric]
        rounded = f"{round(cov.regions, -2):,}"
        span = f"{cov.first_month:%B %Y} to {cov.last_month:%B %Y}"
        section = re.search(
            rf"{label} \((?:ZHVI|ZORI)\) cover about ([\d,]+) cities from (.*?)\.",
            " ".join(text.split()),
            re.I,
        )
        assert section, f"no coverage sentence for {label}"
        assert section.group(1) == rounded and section.group(2) == span
