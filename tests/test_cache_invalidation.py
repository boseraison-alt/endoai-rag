"""WORKLIST 4.6 — cache invalidation on write-back.

`learn_from_live_results()` adds papers to the library. `query_cache` serves a
previously generated answer whenever a new question lands within 0.92 cosine of
a cached one. When a write-back materially thickens a topic, the answers cached
on that topic were synthesised from a thinner evidence base and are stale — but
nothing stopped them being served.

The rule under test: a write-back that adds >= CACHE_INVALIDATION_MIN_PAPERS
papers deletes every `query_cache` row within CACHE_INVALIDATION_SIMILARITY
(0.85) cosine of the query it came from. 0.85 is deliberately looser than the
0.92 serve threshold — a topic-level change should clear a wider neighbourhood
than an exact-question match.

Two halves:

* Offline (fake connection) — the write-back side. Papers, titles and abstracts
  are REAL rows pulled from `endo_papers_rag`, so the candidate filter sees the
  shapes it sees in production.
* Live (`DATABASE_URL` required, skipped otherwise) — the deletion side. The
  0.85 boundary and NULL handling are properties of pgvector and of the SQL
  actually sent, and a hand-written fake would only assert that the fake models
  Postgres the way the author imagined. These tests seed their own rows from
  REAL eval questions (`eval/questions.json`) and remove them again.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import rag  # noqa: E402


# ── Real library rows (endo_papers_rag, pulled 2026-08-30) ───────────────
# Six real laser papers above the quality floor, each with a real abstract.
# Six so a test can write 5 (threshold met) or 4 (not met) from the same set.
REAL_PAPERS = [
    ("41833582",
     "Clinical Efficiency of Lasers in Endodontic Treatment of Primary Endodontic Cases: An Umbrella Review",
     "OBJECTIVES: To evaluate and synthesise the current evidence on the efficacy of laser-activated irrigation in endodontics.",
     2026, "International dental journal", "level1", 78.5),
    ("41063319",
     "Preventive and therapeutic effects of semiconductor laser on pain in root canal treatment.",
     "OBJECTIVE: This study aimed to evaluate the preventive and therapeutic effects of semiconductor laser on postoperative pain.",
     2025, "European journal of medical research", "level1", 78.1),
    ("39287434",
     "Efficacy of laser adjuvant therapy in the management of post-operative endodontic pain",
     "BACKGROUND: Postoperative endodontic pain (PEP) is crucial in clinical practice. Recently, the effects of various lasers have been studied.",
     2024, "International endodontic journal", "level1", 78.1),
    ("40492415",
     "Clinical efficacy of diode laser for pulpotomy in primary teeth: a meta-analysis of randomized trials",
     "To systematically evaluate the efficacy of diode laser for pulpotomy in primary teeth using meta-analysis.",
     2025, "Acta odontologica Scandinavica", "level1", 78.1),
    ("40558896",
     "Antibacterial and Bactericidal Effects of the Er: YAG Laser on Oral Bacteria: A Systematic Review",
     "BACKGROUND: The Er:YAG laser has gained attention in dentistry for its potential to enhance microbial disinfection.",
     2025, "Journal of functional biomaterials", "level1", 76.1),
    ("41918875",
     "Effects of dual-wavelength laser combined with periodontal flap surgery on periodontal parameters",
     "OBJECTIVE: This study investigated the clinical effectiveness of dual-wavelength laser with periodontal flap surgery.",
     2026, "Frontiers in cellular and infection microbiology", "level1", 75.6),
]

# Real eval question (eval/questions.json, laser case) — the topic these six
# papers would have been written back under.
REAL_QUESTION = "Use of lasers in root canal disinfection"


def _scored(n):
    """n real papers in the shape fetch_papers() hands to write-back."""
    out = []
    for pmid, title, _abs, year, journal, level_key, score in REAL_PAPERS[:n]:
        out.append({
            "pmid": pmid, "score": score, "year": year, "journal": journal,
            "level_key": level_key, "authors": "", "citations": 0,
            "has_retraction": False, "superseded_by": "",
            "medline_indexed": True, "has_erratum": False, "registry": "",
            "has_coi": False, "coi_funder": "", "coi_status": "no_statement",
        })
    return out


def _per_pmid(n):
    return {p[0]: {"title": p[1], "abstract": p[2]} for p in REAL_PAPERS[:n]}


# ── Fake connection for the offline half ─────────────────────────────────

class _FakeCursor:
    def __init__(self, log):
        self.log = log
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.log.append(sql)

    def fetchall(self):
        return []          # the library holds none of these PMIDs yet

    def close(self):
        pass


class _FakeConn:
    def __init__(self, log):
        self.log = log

    def cursor(self, *a, **k):
        return _FakeCursor(self.log)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture
def write_back(monkeypatch):
    """Run learn_from_live_results() against a fake library, with the
    invalidation call replaced by a spy. Returns (runner, calls)."""
    calls = []
    monkeypatch.setattr(rag, "embed", lambda text: [0.01] * 384)
    monkeypatch.setattr(rag, "get_conn", lambda: _FakeConn([]))
    monkeypatch.setattr(rag, "invalidate_cache_near_query",
                        lambda *a, **k: calls.append((a, k)) or 0)

    def _run(n_papers, **kwargs):
        return rag.learn_from_live_results(_scored(n_papers),
                                           _per_pmid(n_papers), **kwargs)

    return _run, calls


# ── The write-back side ──────────────────────────────────────────────────

class TestWriteBackTriggersInvalidation:

    def test_threshold_is_a_named_constant(self):
        """A literal 5 buried in a conditional cannot be found or tuned."""
        assert rag.CACHE_INVALIDATION_MIN_PAPERS == 5
        assert rag.CACHE_INVALIDATION_SIMILARITY == 0.85

    def test_invalidation_threshold_is_looser_than_the_serve_threshold(self):
        """0.85 must stay BELOW the 0.92 get_cached_answer() default. A
        topic-level change clears a wider neighbourhood than an exact-question
        match; if these ever cross, invalidation would leave behind rows that
        are still close enough to be served."""
        import inspect
        serve = inspect.signature(rag.get_cached_answer).parameters["threshold"].default
        assert rag.CACHE_INVALIDATION_SIMILARITY < serve

    def test_small_write_back_does_not_invalidate(self, write_back):
        """Four papers is not a topic-level change. Cached answers stand."""
        run, calls = write_back
        written = run(rag.CACHE_INVALIDATION_MIN_PAPERS - 1,
                      query_text=REAL_QUESTION)
        assert written == rag.CACHE_INVALIDATION_MIN_PAPERS - 1
        assert calls == [], \
            f"invalidated the cache after only {written} paper(s)"

    def test_write_back_at_the_threshold_invalidates(self, write_back):
        """Five papers is, and the written-back query must reach the cache."""
        run, calls = write_back
        written = run(rag.CACHE_INVALIDATION_MIN_PAPERS,
                      query_text=REAL_QUESTION)
        assert written == rag.CACHE_INVALIDATION_MIN_PAPERS
        assert len(calls) == 1, "cache was not invalidated after a 5-paper write-back"
        args, kwargs = calls[0]
        passed = (args[0] if args else kwargs.get("query_text"))
        assert passed == REAL_QUESTION, \
            f"invalidation ran against {passed!r}, not the written-back query"

    def test_write_back_above_the_threshold_invalidates(self, write_back):
        run, calls = write_back
        run(rag.CACHE_INVALIDATION_MIN_PAPERS + 1, query_text=REAL_QUESTION)
        assert len(calls) == 1


class TestTheLiveCallSiteActuallyThreadsTheQuery:
    """Three live bugs have shipped in this codebase with a green suite because
    the unit tests imported the symbol directly and nothing exercised the real
    call path (HANDOVER: "green unit tests over a path nothing exercises end to
    end"). Every test above calls learn_from_live_results() itself, so all of
    them stay green if fetch_papers() simply never passes a query.

    Driving fetch_papers() for real means two live NCBI round-trips, so this
    reads the call site out of the AST instead. It is a weaker test than an
    end-to-end run and is not a substitute for one — but it is the only thing
    here that fails when the write-back call site stops threading the query."""

    def _write_back_call(self):
        import ast, inspect
        import endo_ai
        tree = ast.parse(inspect.getsource(endo_ai.fetch_papers))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "learn_from_live_results"):
                return node
        return None

    def test_fetch_papers_calls_write_back(self):
        assert self._write_back_call() is not None, \
            "fetch_papers() no longer calls learn_from_live_results()"

    def test_fetch_papers_passes_a_query_to_write_back(self):
        call = self._write_back_call()
        kwargs = {k.arg for k in call.keywords}
        assert "query_text" in kwargs, (
            "fetch_papers() writes papers back without telling the cache which "
            "query they came from — invalidation can never fire")


class TestWriteBackStaysSafe:
    """`learn_from_live_results` documents that it never raises: a failure
    here must not break the answer already being returned to the clinician.
    Adding invalidation must not weaken that."""

    def test_missing_query_text_degrades_to_no_invalidation(self, monkeypatch):
        """Every pre-4.6 caller omits the query. They must keep working, and
        must not reach the database looking for rows to delete."""
        embedded = []
        monkeypatch.setattr(rag, "embed", lambda text: embedded.append(text) or [0.01] * 384)
        monkeypatch.setattr(rag, "get_conn", lambda: _FakeConn([]))

        # No query_text at all — the pre-4.6 call signature.
        written = rag.learn_from_live_results(_scored(6), _per_pmid(6))
        assert written == 6

        # ... and the invalidation itself must no-op on an empty query rather
        # than embedding None and asking the database about it.
        embedded.clear()
        assert rag.invalidate_cache_near_query(None) == 0
        assert rag.invalidate_cache_near_query("   ") == 0
        assert embedded == [], \
            f"embedded {embedded!r} for a missing query instead of no-opping"

    def test_exception_inside_invalidation_does_not_propagate(self, monkeypatch):
        """The papers were written; the answer is in flight. A cache failure
        loses neither."""
        monkeypatch.setattr(rag, "embed", lambda text: [0.01] * 384)
        monkeypatch.setattr(rag, "get_conn", lambda: _FakeConn([]))

        def _boom(*a, **k):
            raise RuntimeError("pgvector index rebuilt out from under us")

        monkeypatch.setattr(rag, "invalidate_cache_near_query", _boom)
        written = rag.learn_from_live_results(_scored(6), _per_pmid(6),
                                              query_text=REAL_QUESTION)
        assert written == 6, "a cache-invalidation failure swallowed the write-back"

    def test_invalidation_swallows_its_own_database_errors(self, monkeypatch):
        """Same property one level down — the function itself never raises."""
        monkeypatch.setattr(rag, "embed", lambda text: [0.01] * 384)

        def _no_db():
            raise RuntimeError("connection pool exhausted")

        monkeypatch.setattr(rag, "get_conn", _no_db)
        assert rag.invalidate_cache_near_query(REAL_QUESTION) == 0


# ── The deletion side (live database) ────────────────────────────────────

LIVE = pytest.mark.skipif(not os.getenv("DATABASE_URL"),
                          reason="needs the live Neon query_cache table")

# Real eval questions, plus literal rephrasings of the laser case. Measured
# cosine against REAL_QUESTION is in the comment on each.
SEEDED = [
    ("[review] Use of lasers in root canal disinfection", True),                       # 0.99
    ("[review] Lasers in root canal disinfection: are they effective?", True),         # 0.97
    ("[learn] Is laser irradiation effective for disinfecting root canals "
     "during endodontic treatment?", True),                                            # 0.86
    ("[review] Laser-activated irrigation PIPS SWEEPS versus ultrasonic "
     "activation periapical healing outcomes", True),                                  # 0.51
    ("[review] CBCT versus periapical radiography for detecting apical "
     "periodontitis", True),                                                           # 0.38
    ("[review] Single-visit versus multiple-visit root canal treatment for "
     "necrotic teeth with apical periodontitis", False),                               # NULL embedding
]


@pytest.fixture
def seeded_cache():
    """Insert the six rows above into the real query_cache and yield
    {question_text: id}. Removes exactly its own rows afterwards."""
    conn = rag.get_conn()
    cur  = conn.cursor()
    ids  = {}
    try:
        for text, has_embedding in SEEDED:
            cur.execute(
                "INSERT INTO query_cache (question_text, question_embedding,"
                " answer, papers) VALUES (%s,%s,%s,%s) RETURNING id;",
                (text, rag.embed(text) if has_embedding else None,
                 "seeded by test_cache_invalidation", json.dumps([])))
            ids[text] = cur.fetchone()[0]
        conn.commit()
    finally:
        cur.close(); conn.close()

    def _survivors():
        c = rag.get_conn(); k = c.cursor()
        try:
            k.execute("SELECT id FROM query_cache WHERE id = ANY(%s);",
                      (list(ids.values()),))
            return {r[0] for r in k.fetchall()}
        finally:
            k.close(); c.close()

    try:
        yield ids, _survivors
    finally:
        c = rag.get_conn(); k = c.cursor()
        try:
            k.execute("DELETE FROM query_cache WHERE id = ANY(%s);",
                      (list(ids.values()),))
            c.commit()
        finally:
            k.close(); c.close()


@LIVE
class TestDeletionAgainstRealPgvector:

    def test_rows_within_the_threshold_are_deleted(self, seeded_cache):
        ids, survivors = seeded_cache
        deleted = rag.invalidate_cache_near_query(REAL_QUESTION)
        assert deleted >= 3, \
            f"expected the 3 laser rows (cos 0.99/0.97/0.86) to go, deleted {deleted}"
        left = survivors()
        for text, _ in SEEDED[:3]:
            assert ids[text] not in left, \
                f"stale cached answer survived invalidation: {text[:60]}"

    def test_rows_below_the_threshold_survive(self, seeded_cache):
        """0.85 is a neighbourhood, not a domain. Two other endodontic
        questions — one about the same lasers, at 0.51 — are different
        clinical questions and their answers are still valid."""
        ids, survivors = seeded_cache
        rag.invalidate_cache_near_query(REAL_QUESTION)
        left = survivors()
        for text, _ in SEEDED[3:5]:
            assert ids[text] in left, \
                f"invalidation reached too far and deleted: {text[:60]}"

    def test_null_embedding_rows_survive(self, seeded_cache):
        """Some rows carry no embedding. 'We cannot tell what this row is
        about' must resolve to keeping it, not to purging it."""
        ids, survivors = seeded_cache
        null_row = SEEDED[5][0]
        rag.invalidate_cache_near_query(REAL_QUESTION)
        assert ids[null_row] in survivors(), \
            "a row with a NULL question_embedding was deleted"

    def test_dry_run_deletes_nothing(self, seeded_cache):
        ids, survivors = seeded_cache
        n = rag.invalidate_cache_near_query(REAL_QUESTION, dry_run=True)
        assert n >= 3
        assert survivors() == set(ids.values()), "dry run deleted rows"
