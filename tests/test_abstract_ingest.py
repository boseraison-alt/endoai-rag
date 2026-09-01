"""Every ingest and write-back path must store the FULL abstract.

Background: 1,342 of 2,342 library rows were hard-truncated — 749 at exactly
1,200 characters, 593 at exactly 1,000 — because every record-building path
sliced the abstract before storing it. A PubMed abstract puts its CONCLUSIONS
last, so the cut landed precisely on the findings: the word "conclusion"
survived in 7.2% of truncated rows against 39.3% of whole ones. The synthesis
prompt reads these stored abstracts, so a truncated row is a paper that stops
before it says anything.

These tests assert on the DICT THAT WOULD BE WRITTEN (and, for rag.upsert_paper,
on the parameters handed to the INSERT) — never by grepping source, which would
pass against a cap re-expressed as a variable or a different literal.

Everything here is offline: the abstract comes from a recorded efetch fixture on
disk, embed() and upsert_paper()/get_conn() are monkeypatched out at each
module's own namespace, so no network call and no database write happens.

The embedding-text slices (`abstract[:400]`, `[:300]`, `text[:600]`) are NOT a
bug and are deliberately not asserted against: they feed a 256-token
sentence-transformer, which is a real limit. Only the STORED field is checked.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# A real recorded PubMed efetch batch. PMID 37254176's abstract is 2,741 chars
# and carries a CONCLUSIONS section — i.e. exactly the shape of paper the old
# 1,000/1,200-char caps destroyed.
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "pubmed_xml" / "batch_37254176.txt"
FIXTURE_PMID = "37254176"


@pytest.fixture(scope="module")
def long_abstract() -> str:
    """A real >2,000-char PubMed abstract, parsed from the recorded fixture."""
    if not FIXTURE_PATH.exists():
        pytest.skip(f"fixture missing: {FIXTURE_PATH}")
    from endo_ai import _parse_efetch_batch

    parts = _parse_efetch_batch(FIXTURE_PATH.read_text(encoding="utf-8"))
    abstract = ((parts.get(FIXTURE_PMID) or {}).get("abstract") or "").strip()
    assert len(abstract) > 2000, f"fixture abstract too short: {len(abstract)}"
    assert "CONCLUSION" in abstract.upper(), "fixture must carry a conclusions section"
    return abstract


def _assert_intact(stored: str, original: str, where: str):
    """The stored abstract must be the original, character for character."""
    assert stored == original, (
        f"{where}: stored abstract is not the full abstract "
        f"({len(stored)} chars stored vs {len(original)} given). "
        f"A length cap on the STORED abstract field has been reintroduced."
    )
    # The tail is the part a cap eats, and the part that carries the findings.
    assert stored.endswith(original[-200:]), f"{where}: abstract tail was cut"


def _stub_embed(_text):
    """Stand-in for rag.embed — never loads the sentence-transformer."""
    return [0.0] * 384


class _Capture:
    """Collects the (record, vector) pairs an ingest path tries to upsert."""

    def __init__(self):
        self.records = []

    def __call__(self, record, vector=None, *a, **k):
        self.records.append(record)

    @property
    def only(self) -> dict:
        assert len(self.records) == 1, f"expected 1 upsert, got {len(self.records)}"
        return self.records[0]


@pytest.fixture
def meta() -> dict:
    return {
        "title":     "Comparative clinical success of direct pulp capping materials",
        "journal":   "J Endod",
        "year":      "2023",
        "authors":   "Hatipoglu O, Varli Tekingur E",
        "citations": 12,
    }


# ── build_library.py ──────────────────────────────────────────────────────

def test_build_library_paper_record_stores_full_abstract(long_abstract, meta):
    """build_library.build_paper_record — was abstract_text[:1000]."""
    import build_library

    rec = build_library.build_paper_record(
        FIXTURE_PMID, long_abstract, meta, "level2")
    _assert_intact(rec["abstract"], long_abstract, "build_library.build_paper_record")


def test_build_library_cochrane_entry_stores_full_text(long_abstract, monkeypatch):
    """build_library.process_topic's Cochrane branch — was cochrane_text[:800]."""
    import build_library

    capture = _Capture()
    monkeypatch.setattr(build_library, "fetch_cochrane", lambda topic: long_abstract)
    # Every non-Cochrane tier is short-circuited: no network, no other upserts.
    monkeypatch.setattr(build_library, "fetch_papers",
                        lambda *a, **k: (None, [], []))
    monkeypatch.setattr(build_library, "fetch_metadata", lambda ids: {})
    monkeypatch.setattr(build_library, "embed", _stub_embed)
    monkeypatch.setattr(build_library, "upsert_paper", capture)

    added = build_library.process_topic("vital pulp therapy", set())

    assert added == 1
    _assert_intact(capture.only["abstract"], long_abstract,
                   "build_library.process_topic (cochrane)")


# ── fetch_open_sources.py ─────────────────────────────────────────────────

def test_fetch_open_sources_build_record_stores_full_abstract(long_abstract, meta):
    """fetch_open_sources.build_record — was abstract[:1200]."""
    import fetch_open_sources

    source = {"level_key": "level3", "if_default": 2.0}
    rec = fetch_open_sources.build_record(FIXTURE_PMID, long_abstract, meta, source)
    _assert_intact(rec["abstract"], long_abstract, "fetch_open_sources.build_record")


# ── fetch_pmc_corpus.py ───────────────────────────────────────────────────

def test_fetch_pmc_corpus_build_record_stores_full_abstract(long_abstract, meta):
    """fetch_pmc_corpus.build_paper_record — was abstract_text[:1200]."""
    import fetch_pmc_corpus

    rec = fetch_pmc_corpus.build_paper_record(FIXTURE_PMID, long_abstract, meta)
    _assert_intact(rec["abstract"], long_abstract,
                   "fetch_pmc_corpus.build_paper_record")


# ── ingest_aae_guidelines.py ──────────────────────────────────────────────

def test_aae_pubmed_guideline_stores_full_abstract(long_abstract, meta, monkeypatch):
    """ingest_aae_guidelines.ingest_pubmed_guidelines — was abstract[:1200]."""
    import ingest_aae_guidelines as aae

    capture = _Capture()
    monkeypatch.setattr(aae, "PUBMED_GUIDELINE_QUERIES", ["one query"])
    monkeypatch.setattr(aae, "pubmed_search", lambda q, max_results=15: [FIXTURE_PMID])
    monkeypatch.setattr(aae, "pubmed_fetch_meta", lambda pmids: {FIXTURE_PMID: meta})
    monkeypatch.setattr(aae, "pubmed_fetch_abstracts",
                        lambda pmids: {FIXTURE_PMID: long_abstract})
    monkeypatch.setattr(aae, "embed", _stub_embed)
    monkeypatch.setattr(aae, "upsert_paper", capture)
    monkeypatch.setattr(aae.time, "sleep", lambda *_a: None)

    added = aae.ingest_pubmed_guidelines(dry_run=False)

    assert added == 1
    _assert_intact(capture.only["abstract"], long_abstract,
                   "ingest_aae_guidelines.ingest_pubmed_guidelines")


# ── repair_abstracts.py ───────────────────────────────────────────────────

def test_repair_abstracts_writes_back_full_abstract(long_abstract, meta, monkeypatch):
    """repair_abstracts.update_paper — was abstract[:1000].

    This path exists to REPAIR rows with a missing abstract; storing a
    truncated one just swaps one damaged row for another.
    """
    import repair_abstracts

    capture = _Capture()
    monkeypatch.setattr(repair_abstracts, "embed", _stub_embed)
    monkeypatch.setattr(repair_abstracts, "upsert_paper", capture)

    med = dict(meta, abstract=long_abstract)
    assert repair_abstracts.update_paper(FIXTURE_PMID, med, dry_run=False) is True
    _assert_intact(capture.only["abstract"], long_abstract,
                   "repair_abstracts.update_paper")


# ── ingest_classics.py (regression guard — never had a cap) ───────────────

def test_ingest_classics_stores_full_abstract(long_abstract, meta, monkeypatch):
    """ingest_classics.score_and_upsert must stay cap-free."""
    import ingest_classics

    capture = _Capture()
    monkeypatch.setattr(ingest_classics, "embed", _stub_embed)
    monkeypatch.setattr(ingest_classics, "upsert_paper", capture)

    paper = dict(meta, pmid=FIXTURE_PMID, abstract=long_abstract, year="1985")
    ingest_classics.score_and_upsert(paper, dry_run=False)
    _assert_intact(capture.only["abstract"], long_abstract,
                   "ingest_classics.score_and_upsert")


# ── rag.py (the two paths that actually touch the database) ───────────────

class _FakeCursor:
    """Records every execute() instead of talking to Postgres."""

    def __init__(self, store):
        self.store = store

    def execute(self, sql, params=None):
        self.store.append((sql, params))

    def fetchall(self):
        return []          # the write-back's "which PMIDs do we already hold" probe

    def fetchone(self):
        return None

    def close(self):
        pass


class _FakeConn:
    def __init__(self, store):
        self.store = store

    def cursor(self, *a, **k):
        return _FakeCursor(self.store)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def test_rag_upsert_paper_sends_full_abstract_to_insert(long_abstract, monkeypatch):
    """rag.upsert_paper must hand the whole abstract to the INSERT."""
    import rag

    executed = []
    monkeypatch.setattr(rag, "get_conn", lambda: _FakeConn(executed))

    rag.upsert_paper({
        "pmid": FIXTURE_PMID, "title": "t", "abstract": long_abstract,
        "authors": "a", "year": 2023, "journal": "J Endod", "score": 60.0,
    }, [0.0] * 384)

    assert len(executed) == 1
    _sql, params = executed[0]
    stored = [p for p in params if isinstance(p, str) and len(p) > 500]
    assert stored, "no abstract-length string reached the INSERT"
    _assert_intact(stored[0], long_abstract, "rag.upsert_paper")


def test_rag_write_back_sends_full_abstract_to_insert(long_abstract, monkeypatch):
    """rag.learn_from_live_results (the live write-back) must not truncate."""
    import rag

    executed = []
    monkeypatch.setattr(rag, "get_conn", lambda: _FakeConn(executed))
    monkeypatch.setattr(rag, "embed", _stub_embed)
    # Cache accounting/invalidation are DB-touching side paths, not under test.
    monkeypatch.setattr(rag, "_note_writeback", lambda *a, **k: False)

    scored = [{"pmid": FIXTURE_PMID, "score": 80.0, "year": 2023,
               "journal": "J Endod", "authors": "a", "citations": 5}]
    per_pmid = {FIXTURE_PMID: {"title": "t", "abstract": long_abstract}}

    written = rag.learn_from_live_results(scored, per_pmid=per_pmid,
                                          query_text="pulp capping")

    assert written == 1
    inserts = [p for _s, p in executed if p and any(
        isinstance(x, str) and len(x) > 500 for x in p)]
    assert inserts, "no abstract-length string reached the write-back INSERT"
    stored = [x for x in inserts[0] if isinstance(x, str) and len(x) > 500][0]
    _assert_intact(stored, long_abstract, "rag.learn_from_live_results")
