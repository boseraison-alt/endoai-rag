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


# ── One question's write-back, as fetch_papers() actually issues it ──────
# fetch_papers() calls learn_from_live_results() ONCE PER TIER, so a single
# question produces a sequence of small write-backs, not one large one. These
# are the real top laser/irrigation rows of each tier in endo_papers_rag
# (pulled 2026-08-30), four per tier — the shape of the write-back the laser
# question produces. The `cochrane` tier is absent because a laser search
# genuinely returns no Cochrane reviews; that is what the real batch looks
# like. 23 papers in total, and NOT ONE of the six calls reaches 5.
REAL_TIER_BATCHES = [
    ("level1", [
        ("41833582", "Clinical Efficiency of Lasers in Endodontic Treatment of Primary Endodontic Cases",
         "OBJECTIVES: To evaluate and synthesise the current evidence on the efficacy of l"),
        ("39287434", "Efficacy of laser adjuvant therapy in the management of post-operative endodontic pain",
         "BACKGROUND: Postoperative endodontic pain (PEP) is crucial in clinical practice."),
        ("41063319", "Preventive and therapeutic effects of semiconductor laser on pain in root canal treatment",
         "OBJECTIVE: This study aimed to evaluate the preventive and therapeutic effects o"),
        ("40492415", "Clinical efficacy of diode laser for pulpotomy in primary teeth: a meta-analysis",
         "To systematically evaluate the efficacy of diode laser for pulpotomy in primary "),
    ]),
    ("level2", [
        ("39815035", "Evaluation of the effect of different irrigation solutions used in regenerative endodontics",
         "OBJECTIVES: This study evaluates the effect of different irrigation solutions fo"),
        ("35267110", "Postoperative pain after SWEEPS, PIPS, sonic and ultrasonic-assisted irrigation",
         "To investigate the efficacy of a new laser irrigation activation system [shock w"),
        ("41436629", "Effect of Er, Cr: YSGG laser-activated final irrigation on gingival crevicular fluid",
         "This study aims to investigate the effect of Er, Cr: YSGG laser activation of Na"),
        ("40407835", "Clinical and radiographic evaluation of Er: YAG laser-assisted direct pulp capping",
         "PURPOSE: The study aimed to evaluate the clinical and radiographic outcomes of t"),
    ]),
    ("level3a", [
        ("40287087", "Healing Outcomes Following the Treatment of Molars Using Different Root Canal Protocols",
         "INTRODUCTION: To address the shortage of clinical outcome studies on contemporar"),
        ("42482547", "Effectiveness and safety of water laser-assisted endodontic-periodontal therapy",
         "ObjectiveCombined endodontic-periodontal lesions are challenging to manage becau"),
        ("37849444", "Evaluation of photobiomodulation for postoperative discomfort following laser treatment",
         "BACKGROUND: Minimally invasive endodontics is recommended for young, immature te"),
        ("38157279", "The Outcome of GaAlAs Diode Laser (980 Nm) Pulpotomy in Patients with Symptomatic Pulpitis",
         "OBJECTIVE: To evaluate the effect of diode laser (GaAlAs-980 nm) for full corona"),
    ]),
    ("level4", [
        ("40889700", "Managing Perforating Internal Root Resorption in Mature Incisor with Laser-assisted Therapy",
         "INTRODUCTION: This report presented the successful application of laser-assisted"),
        ("39917669", "Unique root anatomy of mandibular second premolars: clinical strategies",
         "It is difficult to predict the outcomes of non-surgical root canal treatment (NS"),
        ("11678544", "Laser Doppler flowmetry for monitoring traumatized teeth.",
         "Laser Doppler Flowmetry (LDF) has been shown to be valuable in monitoring revasc"),
    ]),
    ("invitro", [
        ("40261531", "Comparative analysis of antimicrobial activity and oxidative damage induced by laser ablation",
         "Laser ablation and Antimicrobial Photodynamic Therapy (aPDT) serve as adjunctive"),
        ("40713572", "Effect of intracanal medicaments on dentinal tubule penetration of root canal sealers",
         "BACKGROUND: This study investigated the effect of three intracanal medicaments o"),
        ("39888502", "In vitro evaluation of dye penetration and dentin microhardness after laser irradiation",
         "The purpose of this study was to compare the penetration of methylene blue (MB) "),
        ("41389357", "Comparative analysis of laser and ultrasonic irrigation techniques for smear layer removal",
         "OBJECTIVE: This in vitro study compared the efficacy of Er, Cr: YSGG laser (2780"),
    ]),
    ("level5", [
        ("42513311", "Prognosis of Periapical Lesions Treated by Activated Disinfection (PUI, Laser)",
         "Background/Objectives: Activated irrigation techniques improve intracanal disinf"),
        ("35338652", "Present status and future directions - irrigants and irrigation methods.",
         "Irrigation is considered the primary means of cleaning and disinfection of the r"),
        ("24640478", "Traditional and contemporary techniques for optimizing root canal irrigation.",
         "Canal irrigation during root canal treatment is an important component of chemo-"),
        ("24651335", "Irrigation in endodontics.",
         "Irrigation is a key part of successful root canal treatment. It has several impo"),
    ]),
]


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


@pytest.fixture(autouse=True)
def _fresh_tally():
    """The write-back count is accumulated PER QUESTION across the seven
    tier-by-tier calls one question makes (WORKLIST C1), so it survives
    between tests in the same process. Every test here starts from zero;
    without this, the 4-paper test would leave 4 on the tally and the next
    test's first paper would trip the threshold."""
    rag._reset_writeback_tally()
    yield
    rag._reset_writeback_tally()


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


# ── The threshold counts per QUESTION, not per tier (WORKLIST C1) ────────

def _tier_scored(papers, tier):
    """One tier's write-back, in the shape fetch_papers() hands over."""
    return [{
        "pmid": pmid, "score": 70.0, "year": 2025, "journal": "",
        "level_key": tier, "authors": "", "citations": 0,
        "has_retraction": False, "superseded_by": "",
        "medline_indexed": True, "has_erratum": False, "registry": "",
        "has_coi": False, "coi_funder": "", "coi_status": "no_statement",
    } for pmid, _t, _a in papers]


def _tier_per_pmid(papers):
    return {p[0]: {"title": p[1], "abstract": p[2]} for p in papers}


class TestTheThresholdCountsPerQuestionNotPerTier:
    """`learn_from_live_results` is called ONCE PER TIER by fetch_papers() —
    up to seven times for one question. Testing the threshold against a single
    call therefore tests something the production call path never does.

    The bug this pins: a question that writes four papers into each of six
    tiers adds 23 papers to the library — a large topic change, and exactly
    the shape of a real laser-question write-back — while no individual call
    reaches five, so the old `written >= 5` test invalidated nothing at all.
    """

    @pytest.fixture
    def tier_run(self, monkeypatch):
        calls = []
        monkeypatch.setattr(rag, "embed", lambda text: [0.01] * 384)
        monkeypatch.setattr(rag, "get_conn", lambda: _FakeConn([]))
        monkeypatch.setattr(rag, "invalidate_cache_near_query",
                            lambda *a, **k: calls.append((a, k)) or 0)

        def _run(papers, tier="level1", **kwargs):
            return rag.learn_from_live_results(_tier_scored(papers, tier),
                                               _tier_per_pmid(papers), **kwargs)

        return _run, calls

    def test_no_single_tier_batch_reaches_the_threshold(self):
        """Guards the premise. If a fixture tier ever grew to five papers the
        test below would pass for the wrong reason."""
        for tier, papers in REAL_TIER_BATCHES:
            assert len(papers) < rag.CACHE_INVALIDATION_MIN_PAPERS, (
                f"{tier} holds {len(papers)} papers — this fixture no longer "
                f"demonstrates the per-tier/per-question difference")

    def test_one_question_across_all_its_tiers_invalidates(self, tier_run):
        run, calls = tier_run
        total = 0
        for tier, papers in REAL_TIER_BATCHES:
            total += run(papers, tier=tier, query_text=REAL_QUESTION)
        assert total == 23, f"fixture wrote {total} papers, expected 23"
        assert len(calls) == 1, (
            f"{total} papers written for one question across "
            f"{len(REAL_TIER_BATCHES)} tiers produced {len(calls)} "
            f"invalidation(s) — the threshold is still being applied per tier")
        args, kwargs = calls[0]
        assert (args[0] if args else kwargs.get("query_text")) == REAL_QUESTION

    def test_it_fires_on_the_tier_that_crosses_the_threshold(self, tier_run):
        """Not after the last tier: the moment the question's running total
        reaches five. That is still before synthesis, so this question's own
        cache row (written afterwards by save_query_cache) is never the one
        deleted."""
        run, calls = tier_run
        first, second = REAL_TIER_BATCHES[0][1], REAL_TIER_BATCHES[1][1]
        run(first[:2], tier="level1", query_text=REAL_QUESTION)      # total 2
        assert calls == []
        run(first[2:4], tier="level1", query_text=REAL_QUESTION)     # total 4
        assert calls == []
        run(second[:1], tier="level2", query_text=REAL_QUESTION)     # total 5
        assert len(calls) == 1

    def test_it_fires_only_once_per_question(self, tier_run):
        """The neighbourhood is already cleared. Re-running the delete on
        every later tier would only remove rows cached since — including,
        eventually, this question's own answer."""
        run, calls = tier_run
        for tier, papers in REAL_TIER_BATCHES:
            run(papers, tier=tier, query_text=REAL_QUESTION)
        assert len(calls) == 1
        for tier, papers in REAL_TIER_BATCHES:      # a second full sweep
            run(papers, tier=tier, query_text=REAL_QUESTION)
        assert len(calls) == 1

    def test_two_different_questions_do_not_pool_their_counts(self, tier_run):
        """A single global counter would pass every test above and be wrong:
        four papers on lasers plus four on CBCT is not a topic change to
        either topic."""
        run, calls = tier_run
        other = "CBCT versus periapical radiography for detecting apical periodontitis"
        run(REAL_TIER_BATCHES[0][1], tier="level1", query_text=REAL_QUESTION)
        run(REAL_TIER_BATCHES[1][1], tier="level1", query_text=other)
        assert calls == [], (
            "counts from two different questions were pooled — invalidation "
            "fired on a topic that gained only four papers")

    def test_the_same_question_asked_again_later_can_invalidate_again(
            self, tier_run):
        """The tally is a per-question session, not a permanent record: a
        question re-asked after the write-backs have stopped must be able to
        clear the cache again. Simulated by ageing the tally entry past the
        idle gap, which is what a second ask an hour later looks like."""
        run, calls = tier_run
        for tier, papers in REAL_TIER_BATCHES[:2]:
            run(papers, tier=tier, query_text=REAL_QUESTION)
        assert len(calls) == 1

        key = REAL_QUESTION.lower()
        assert key in rag._writeback_tally
        rag._writeback_tally[key]["last"] -= (rag._WRITEBACK_SESSION_GAP_SECONDS + 1)

        for tier, papers in REAL_TIER_BATCHES[:2]:
            run(papers, tier=tier, query_text=REAL_QUESTION)
        assert len(calls) == 2, (
            "the same question asked again after the idle gap could not "
            "invalidate — the tally is permanent, not a session")

    def test_a_write_back_with_no_query_never_accumulates(self, tier_run):
        """Pre-C1 callers pass no query. They must not silently accumulate
        against each other under a shared empty key and then invalidate a
        neighbourhood nobody named."""
        run, calls = tier_run
        for tier, papers in REAL_TIER_BATCHES:
            run(papers, tier=tier)
        assert calls == []
        assert rag._writeback_total("") == 0

    def test_the_running_total_is_the_papers_actually_written(self, tier_run):
        run, _calls = tier_run
        written = 0
        for tier, papers in REAL_TIER_BATCHES[:3]:
            written += run(papers, tier=tier, query_text=REAL_QUESTION)
        assert rag._writeback_total(REAL_QUESTION) == written == 12

    def test_the_key_ignores_whitespace_and_case(self, tier_run):
        """The same question arriving with different spacing from two tiers
        must land on one tally, not two."""
        run, calls = tier_run
        run(REAL_TIER_BATCHES[0][1], tier="level1", query_text=REAL_QUESTION)
        run(REAL_TIER_BATCHES[1][1][:1], tier="level2",
            query_text="  " + REAL_QUESTION.upper() + "\n")
        assert len(calls) == 1

    def test_the_tally_does_not_grow_without_bound(self, tier_run):
        """A long-lived server answers thousands of questions; the accumulator
        must not become a leak."""
        run, _ = tier_run
        for i in range(rag._WRITEBACK_TALLY_MAX * 2):
            run(REAL_TIER_BATCHES[0][1][:1], tier="level1",
                query_text=f"endodontic question number {i}")
        assert len(rag._writeback_tally) <= rag._WRITEBACK_TALLY_MAX

    def test_a_broken_tally_still_invalidates_on_a_big_single_call(
            self, tier_run, monkeypatch):
        """Never-raises, one level deeper: if the accounting itself fails the
        write-back must still complete AND must fall back to the old per-call
        rule rather than silently dropping invalidation altogether."""
        run, calls = tier_run

        def _boom(*a, **k):
            raise RuntimeError("tally lock held by a dead thread")

        monkeypatch.setattr(rag, "_note_writeback", _boom)
        written = run(REAL_TIER_BATCHES[0][1] + REAL_TIER_BATCHES[1][1],
                      tier="level1", query_text=REAL_QUESTION)
        assert written == 8
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
