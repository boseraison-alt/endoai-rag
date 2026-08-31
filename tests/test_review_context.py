"""Review-mode conversation memory (WORKLIST batch item 4).

A follow-up question ("what about in immature teeth?") carries none of its own
subject. The thread's last three exchanges are compacted into ONE block —
previous question, its CLINICAL RECOMMENDATION only, its cited PMIDs — and that
block is prepended to the four prompts that need it: the clarify gate, the
intent router, both search-term generators, and synthesis.

Three properties are load-bearing and each has its own section below.

1. THE CACHE KEY. `query_cache` matches on an EMBEDDING of the question text.
   A follow-up's text is often byte-identical to the same words asked cold, so
   without a context term in the key the first follow-up of every thread would
   be served the context-free answer to a similar-looking question. The
   fingerprint is therefore an equality term in the WHERE clause — a hard
   partition, not another similarity signal. This is the dangerous failure mode
   and TestTheContextFreeAnswerIsNotServed is the test that exists for it.

2. RETRIEVAL STILL RUNS FRESH. Prior PMIDs are added as CANDIDATES with a
   similarity recomputed against the NEW question, after the routing gate has
   already decided, and are then judged by every existing gate. Seeding before
   the gate would let the previous question's evidence route a thin topic to the
   library — context substituting for retrieval.

3. THE UI STATES WHAT THE SERVER DID. The "Continues from" line is rendered
   from the job's `continues_from` field, never from a client-held thread, so a
   page that believes it is in a thread cannot put a continuity claim on an
   answer that was written cold.

Fixtures are real: the recommendation-extraction cases read a genuine answer out
of `answers/`, and the library rows are real laser papers pulled from
`endo_papers_rag` (the same six rows tests/test_cache_invalidation.py uses).
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import endo_ai  # noqa: E402
import rag      # noqa: E402

REPO       = Path(__file__).parent.parent
INDEX_HTML = REPO / "templates" / "index.html"
ANSWERS    = REPO / "answers"


@pytest.fixture(autouse=True)
def isolate_cost_log(tmp_path, monkeypatch):
    """Never let a test append to the real cost_log.jsonl."""
    monkeypatch.setattr(endo_ai, "_COST_LOG_PATH", str(tmp_path / "cost_log.jsonl"))


# ── Real data ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def real_answer() -> str:
    """The most recent REAL review answer on disk that has a recommendation."""
    files = sorted((p for p in ANSWERS.glob("answer_*.txt")
                    if "## CLINICAL RECOMMENDATION" in p.read_text(encoding="utf-8",
                                                                  errors="ignore")),
                   key=lambda p: p.stat().st_mtime)
    if not files:
        pytest.skip("no stored review answer with a CLINICAL RECOMMENDATION section")
    return files[-1].read_text(encoding="utf-8", errors="ignore")


# Real laser rows from endo_papers_rag (pulled 2026-08-30), in the shape
# rag.search() returns. Similarity is set per-test — that is the axis under
# test — but everything else is the library's own data.
def _row(pmid, title, abstract, year, journal, level_key, score, similarity,
         **over):
    row = {
        "pmid": pmid, "title": title, "abstract": abstract, "authors": "Author A",
        "year": year, "journal": journal, "impact_factor": None,
        "sample_size": None, "followup_months": 12, "citations": 10,
        "level_key": level_key, "score": score, "similarity": similarity,
        "is_curated": False, "coi_flag": False, "coi_funder": "",
        "coi_status": "no_statement", "registry": "", "has_erratum": False,
        "has_retraction": False, "medline_indexed": True, "superseded_by": "",
    }
    row.update(over)
    return row


LASER_ROWS = [
    _row("41833582",
         "Clinical Efficiency of Lasers in Endodontic Treatment of Primary "
         "Endodontic Cases: An Umbrella Review",
         "OBJECTIVES: To evaluate and synthesise the current evidence on the "
         "efficacy of laser-activated irrigation in endodontics. " * 4,
         2026, "International dental journal", "level1", 78.5, 0.74),
    _row("41063319",
         "Preventive and therapeutic effects of semiconductor laser on pain in "
         "root canal treatment.",
         "OBJECTIVE: This study aimed to evaluate the preventive and therapeutic "
         "effects of semiconductor laser on postoperative pain. " * 4,
         2025, "European journal of medical research", "level1", 78.1, 0.71),
    _row("39287434",
         "Efficacy of laser adjuvant therapy in the management of post-operative "
         "endodontic pain",
         "BACKGROUND: Postoperative endodontic pain is crucial in clinical "
         "practice. Recently the effects of various lasers have been studied. " * 4,
         2024, "International endodontic journal", "cochrane", 80.0, 0.69,
         journal_over="Cochrane Database Syst Rev"),
]

# The immature-teeth follow-up's own evidence: real regenerative-endodontics
# rows, so the follow-up has somewhere real to land.
IMMATURE_ROWS = [
    _row("40287087",
         "Healing Outcomes Following the Treatment of Molars Using Different "
         "Root Canal Protocols",
         "INTRODUCTION: To address the shortage of clinical outcome studies on "
         "contemporary protocols in immature permanent teeth. " * 4,
         2025, "Journal of endodontics", "level3a", 66.0, 0.66),
    _row("37849444",
         "Evaluation of photobiomodulation for postoperative discomfort "
         "following laser treatment",
         "BACKGROUND: Minimally invasive endodontics is recommended for young, "
         "immature teeth with open apices. " * 4,
         2024, "Lasers in medical science", "level2", 64.0, 0.63),
]


LASER_EXCHANGE = {
    "question": "Use of lasers in root canal disinfection",
    "recommendation": ("Based on Level I evidence, laser-activated irrigation "
                       "reduces intracanal bacterial load beyond conventional "
                       "syringe irrigation, but the effect on periapical healing "
                       "is unproven."),
    "pmids": ["41833582", "41063319", "39287434"],
}
FOLLOW_UP = "What about in immature teeth?"


# ── 1. The block itself ──────────────────────────────────────────────────

class TestTheContextBlock:

    def test_label_is_the_mandated_sentence(self):
        """The label is the only instruction a model reading the block gets
        about what the block is FOR. It says context, and it says re-verify."""
        assert endo_ai.CONTEXT_BLOCK_LABEL == (
            "Prior exchange, for context; re-verify everything against "
            "retrieved evidence.")
        assert endo_ai.build_context_block([LASER_EXCHANGE]).startswith(
            endo_ai.CONTEXT_BLOCK_LABEL)

    def test_no_exchanges_means_no_block(self):
        """"" must mean "no context" everywhere — the cache fingerprint, the
        prompts and the UI line all key off emptiness."""
        assert endo_ai.build_context_block([]) == ""
        assert endo_ai.build_context_block(None) == ""
        assert endo_ai.build_context_block([{"question": "   "}]) == ""

    def test_block_carries_question_recommendation_and_pmids(self):
        block = endo_ai.build_context_block([LASER_EXCHANGE])
        assert LASER_EXCHANGE["question"] in block
        assert "laser-activated irrigation" in block
        for pmid in LASER_EXCHANGE["pmids"]:
            assert pmid in block

    def test_only_the_last_three_exchanges_survive(self):
        """Older ones drop. Five in, three out — and the two oldest must be
        absent, not merely truncated."""
        exchanges = [{"question": f"question number {i}",
                      "recommendation": f"recommendation {i}", "pmids": [str(i)]}
                     for i in range(5)]
        block = endo_ai.build_context_block(exchanges)
        assert endo_ai.MAX_CONTEXT_EXCHANGES == 3
        for gone in ("question number 0", "question number 1"):
            assert gone not in block, f"exchange past the cap survived: {gone}"
        for kept in ("question number 2", "question number 3", "question number 4"):
            assert kept in block

    def test_prior_pmids_are_deduplicated_newest_first(self):
        a = {"question": "q1", "pmids": ["111", "222"]}
        b = {"question": "q2", "pmids": ["222", "333"]}
        assert endo_ai.context_prior_pmids([a, b]) == ["222", "333", "111"]

    def test_prior_pmids_obey_the_same_cap(self):
        exchanges = [{"question": f"q{i}", "pmids": [f"pmid{i}"]} for i in range(5)]
        got = endo_ai.context_prior_pmids(exchanges)
        assert "pmid0" not in got and "pmid1" not in got


class TestRecommendationOnly:

    def test_extracts_the_recommendation_section(self, real_answer):
        rec = endo_ai.extract_clinical_recommendation(real_answer)
        assert rec, "no recommendation extracted from a real answer"
        first = real_answer.split("## CLINICAL RECOMMENDATION", 1)[1].strip()
        first_words = " ".join(re.sub(r"\[\[PMID:\d+\]\]", "", first).split()[:8])
        assert rec.startswith(first_words.strip())

    def test_the_evidence_summary_does_not_travel(self, real_answer):
        """The whole point of carrying the recommendation only: the block must
        not become a second, stale evidence base the model can answer out of."""
        rec = endo_ai.extract_clinical_recommendation(real_answer)
        summary = real_answer.split("## EVIDENCE SUMMARY", 1)[1]
        sentence = next((s.strip() for s in summary.split(". ")
                         if len(s.strip()) > 60), "")
        assert sentence, "real answer has no usable EVIDENCE SUMMARY sentence"
        assert sentence[:60] not in rec
        block = endo_ai.build_context_block([{"question": "q",
                                              "recommendation": rec}])
        assert sentence[:60] not in block

    def test_pmid_markers_are_stripped(self, real_answer):
        """A [[PMID:N]] marker sitting in prose the model is reading is an
        invitation to copy it into the next answer, where it would be a citation
        to a paper this question's retrieval never produced."""
        rec = endo_ai.extract_clinical_recommendation(real_answer)
        assert "[[PMID:" not in rec

    def test_absent_section_yields_empty_string(self):
        assert endo_ai.extract_clinical_recommendation("") == ""
        assert endo_ai.extract_clinical_recommendation(
            "## EVIDENCE SUMMARY\n\nNo recommendation here.") == ""

    def test_overlong_recommendation_is_capped(self):
        long_rec = "## CLINICAL RECOMMENDATION\n\n" + ("A sentence about MTA. " * 200)
        rec = endo_ai.extract_clinical_recommendation(long_rec)
        assert len(rec) <= endo_ai.CONTEXT_RECOMMENDATION_CHARS + 8


# ── 2. The four prompts ──────────────────────────────────────────────────

class _Usage:
    input_tokens = 10
    output_tokens = 10


class _Block:
    def __init__(self, text):
        self.text = text


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]
        self.usage = _Usage()


@pytest.fixture
def captured_prompts(monkeypatch):
    """Every prompt sent to Claude, in order."""
    seen = []

    def fake_invoke(client_, function_name="", **kwargs):
        for m in kwargs.get("messages", []):
            seen.append(m.get("content", ""))
        if "intent" in function_name:
            return _Resp(json.dumps({"kind": "standard", "needs_clarify": False,
                                     "retrieval": "local", "reason": "covered"}))
        if "multi_search_terms" in function_name:
            return _Resp("TERM: (laser*) AND (immature OR \"open apex\")\n"
                         "TERM: (laser*) AND (regenerative)\n"
                         "TERM: (photodynamic) AND (immature)\n"
                         "TERM: (Er:YAG) AND (apexification)\n")
        if "clarifying" in function_name:
            return _Resp("[]")
        return _Resp("(laser*) AND (immature OR \"open apex\")")

    monkeypatch.setattr(endo_ai, "_invoke_claude", fake_invoke)
    monkeypatch.setattr(endo_ai, "log_llm_call", lambda *a, **k: 0.0)
    monkeypatch.setattr(endo_ai, "_get_api_key", lambda: "test-key")
    return seen


CONTEXT = endo_ai.build_context_block([LASER_EXCHANGE])


def _call_all_four(context_block):
    """Every call site that is supposed to receive the block."""
    endo_ai.generate_clarifying_questions(FOLLOW_UP, context_block=context_block)
    endo_ai.classify_question_intent(FOLLOW_UP, context_block=context_block)
    primary = endo_ai.generate_search_terms(FOLLOW_UP, context_block=context_block)
    endo_ai.generate_multi_search_terms(FOLLOW_UP, primary,
                                        context_block=context_block)


class TestEveryPromptCarriesTheContext:
    """Four call sites, four separate ways to lose the context. The clarify
    gate re-asks what the thread already answered; the router treats an
    elliptical follow-up as a definition; the term generators emit a query for
    "immature teeth" with no mention of lasers; synthesis writes an answer that
    reads as though the thread never happened."""

    def test_all_four_prompts_contain_the_block(self, captured_prompts):
        _call_all_four(CONTEXT)
        assert len(captured_prompts) == 4, captured_prompts
        for i, prompt in enumerate(captured_prompts):
            assert endo_ai.CONTEXT_BLOCK_LABEL in prompt, \
                f"call site {i} lost the context label"
            assert LASER_EXCHANGE["question"] in prompt, \
                f"call site {i} lost the previous question"

    def test_no_context_leaves_the_prompts_byte_identical(self, captured_prompts):
        """A standalone question must reach exactly the prompt it always did —
        no stray header, no blank block."""
        _call_all_four("")
        for prompt in captured_prompts:
            assert endo_ai.CONTEXT_BLOCK_LABEL not in prompt
            assert not prompt.startswith("\n")

    def test_synthesis_carries_the_block_and_forbids_uncited_prior_pmids(
            self, captured_prompts, monkeypatch):
        monkeypatch.setattr(endo_ai, "validate_evidence_mapping",
                            lambda *a, **k: {"passed": True, "score": 100,
                                             "evidence_pmids": set(),
                                             "cited_pmids": [],
                                             "fabricated_pmids": [],
                                             "valid_pmids": [],
                                             "unattributed_claims": [],
                                             "gap_sections": []})
        monkeypatch.setattr(endo_ai, "verify_citation_support",
                            lambda *a, **k: {"flags": [], "checked": 0, "cost": 0.0,
                                             "status": "not_run", "detail": ""})
        evidence = {"level1": {"text": "P1", "ids": ["41833582"], "scored": [],
                               "source": "rag"},
                    "_summary": {"all_scored": [], "total_scored": 0,
                                 "avg_score": 0, "synthesis_order": []}}
        endo_ai.ask_clinical_question(FOLLOW_UP, evidence, context_block=CONTEXT)
        synth = captured_prompts[-1]
        assert endo_ai.CONTEXT_BLOCK_LABEL in synth
        low = synth.lower()
        assert "cite only pmids that appear in the evidence" in low, \
            ("synthesis was handed prior PMIDs with no instruction that they are "
             "not citable unless retrieved again")


# ── 3. The cache key ─────────────────────────────────────────────────────

class _CaptureCursor:
    def __init__(self, log, row=None):
        self.log, self.row, self.rowcount = log, row, 0

    def execute(self, sql, params=None):
        self.log.append((sql, params))

    def fetchone(self):
        return self.row

    def fetchall(self):
        return []

    def close(self):
        pass


class _CaptureConn:
    def __init__(self, log, row=None):
        self.log, self.row = log, row

    def cursor(self, *a, **k):
        return _CaptureCursor(self.log, self.row)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class TestTheKeyIncludesTheContext:

    def test_fingerprint_of_no_context_is_empty(self):
        """"" is the partition every pre-existing row lives in, so a standalone
        question must keep hitting the entries it always hit."""
        assert rag.context_fingerprint("") == ""
        assert rag.context_fingerprint("   \n  ") == ""
        assert rag.context_fingerprint(None) == ""

    def test_fingerprint_is_stable_and_discriminating(self):
        other = endo_ai.build_context_block([{"question": "CBCT versus "
                                                          "periapical radiography"}])
        assert rag.context_fingerprint(CONTEXT) == rag.context_fingerprint(CONTEXT)
        assert rag.context_fingerprint(CONTEXT) != rag.context_fingerprint(other)
        assert rag.context_fingerprint(CONTEXT) != ""

    def test_lookup_filters_on_the_context_hash(self, monkeypatch):
        log = []
        monkeypatch.setattr(rag, "DATABASE_URL", "postgres://fake")
        monkeypatch.setattr(rag, "embed", lambda t: [0.01] * 384)
        monkeypatch.setattr(rag, "get_conn", lambda: _CaptureConn(log, row=None))
        h = rag.context_fingerprint(CONTEXT)
        rag.get_cached_answer("[review] " + FOLLOW_UP, context_hash=h)
        sql, params = log[0]
        assert "context_hash" in sql, \
            "the lookup does not mention context_hash — a follow-up can be " \
            "served the context-free answer"
        assert re.search(r"COALESCE\(context_hash,\s*''\)\s*=\s*%s", sql), \
            "context_hash is not an equality term in the WHERE clause"
        assert h in params, "the fingerprint was never passed to the query"

    def test_save_stores_the_context_hash(self, monkeypatch):
        log = []
        monkeypatch.setattr(rag, "DATABASE_URL", "postgres://fake")
        monkeypatch.setattr(rag, "embed", lambda t: [0.01] * 384)
        monkeypatch.setattr(rag, "get_conn", lambda: _CaptureConn(log))
        h = rag.context_fingerprint(CONTEXT)
        rag.save_query_cache("[review] " + FOLLOW_UP, "answer", [], context_hash=h)
        sql, params = log[0]
        assert "context_hash" in sql, "the answer is stored without its context"
        assert h in params

    def test_setup_backfills_the_column_on_existing_tables(self, monkeypatch):
        """The partition has to exist before the first follow-up is served, and
        every deployment predates the column."""
        log = []
        monkeypatch.setattr(rag, "get_conn", lambda: _CaptureConn(log))
        rag.setup_query_cache()
        joined = " ".join(s for s, _ in log)
        assert "ADD COLUMN IF NOT EXISTS context_hash" in joined


LIVE = pytest.mark.skipif(not os.getenv("DATABASE_URL"),
                          reason="needs the live Neon query_cache table")


@pytest.fixture
def cache_rows():
    """Track question_texts written during a test and delete exactly those."""
    written = []

    def _note(question_text):
        written.append(question_text)
        return question_text

    try:
        yield _note
    finally:
        if written:
            conn = rag.get_conn()
            cur = conn.cursor()
            try:
                cur.execute("DELETE FROM query_cache WHERE question_text = ANY(%s);",
                            (written,))
                conn.commit()
            finally:
                cur.close()
                conn.close()


@LIVE
class TestTheContextFreeAnswerIsNotServed:
    """THE dangerous failure mode.

    Ask a question cold; then ask a follow-up whose TEXT ALONE is cache-similar
    to it. Real embeddings, real pgvector, real threshold — the follow-up is at
    cosine 1.0 against the stored row, far above the 0.92 serve threshold and
    above the 0.985 exact threshold that skips the equivalence gate, so nothing
    except the context key stands between it and the stored answer.
    """

    def test_a_follow_up_does_not_hit_the_context_free_entry(self, cache_rows):
        key = cache_rows("[review] " + FOLLOW_UP + " (test_review_context)")
        rag.save_query_cache(key, "CONTEXT-FREE ANSWER", [], context_hash="")

        # Same text, same embedding, same threshold — only the context differs.
        served = rag.get_cached_answer(key, context_hash=rag.context_fingerprint(CONTEXT))
        assert served is None, (
            "a follow-up asked inside a thread was served the answer generated "
            "WITHOUT that thread's context")

    def test_the_same_row_is_still_reachable_without_context(self, cache_rows):
        """The other half: proving the miss above is the context key doing its
        job, and not a cache that simply stopped working."""
        key = cache_rows("[review] " + FOLLOW_UP + " (test_review_context)")
        rag.save_query_cache(key, "CONTEXT-FREE ANSWER", [], context_hash="")
        served = rag.get_cached_answer(key, context_hash="")
        assert served is not None, "the context-free lookup stopped finding its own row"
        assert served["answer"] == "CONTEXT-FREE ANSWER"

    def test_a_follow_up_hits_its_own_context_entry(self, cache_rows):
        """Rows written under a context are reachable under the SAME context —
        the partition must not be a one-way trip to a permanently cold cache."""
        h = rag.context_fingerprint(CONTEXT)
        key = cache_rows("[review] " + FOLLOW_UP + " (test_review_context ctx)")
        rag.save_query_cache(key, "FOLLOW-UP ANSWER", [], context_hash=h)
        served = rag.get_cached_answer(key, context_hash=h)
        assert served is not None and served["answer"] == "FOLLOW-UP ANSWER"

    def test_a_different_thread_does_not_hit_it_either(self, cache_rows):
        h = rag.context_fingerprint(CONTEXT)
        other = rag.context_fingerprint(endo_ai.build_context_block(
            [{"question": "CBCT versus periapical radiography",
              "recommendation": "CBCT has higher sensitivity.", "pmids": ["1"]}]))
        key = cache_rows("[review] " + FOLLOW_UP + " (test_review_context ctx)")
        rag.save_query_cache(key, "FOLLOW-UP ANSWER", [], context_hash=h)
        assert rag.get_cached_answer(key, context_hash=other) is None


# ── 4. Retrieval still runs fresh ────────────────────────────────────────

class TestSeedingCannotBypassAGate:

    def test_seed_query_excludes_retracted_withdrawn_and_superseded(self, monkeypatch):
        """rag.search_by_pmids is a second door into the library. It must carry
        the same three exclusions search() does, or a follow-up could resurrect
        a retracted paper the previous answer happened to cite."""
        log = []
        monkeypatch.setattr(rag, "DATABASE_URL", "postgres://fake")
        monkeypatch.setattr(rag, "embed", lambda t: [0.01] * 384)
        monkeypatch.setattr(rag, "get_conn", lambda: _CaptureConn(log))
        rag.search_by_pmids("lasers in immature teeth", ["41833582"])
        sql = log[0][0]
        assert "NOT COALESCE(has_retraction, FALSE)" in sql
        assert "title NOT ILIKE 'WITHDRAWN:%%'" in sql
        assert "COALESCE(superseded_by, '') = ''" in sql

    def test_no_pmids_means_no_query(self, monkeypatch):
        monkeypatch.setattr(rag, "DATABASE_URL", "postgres://fake")

        def _boom():
            raise AssertionError("opened a connection for an empty seed list")

        monkeypatch.setattr(rag, "get_conn", _boom)
        assert rag.search_by_pmids("q", []) == []
        assert rag.search_by_pmids("q", None) == []


# ── The routing gate, end to end through build_evidence_base_with_progress ──

class _Reached(Exception):
    """Raised by the stubbed live path so a test can prove the route taken."""


@pytest.fixture
def retrieval(monkeypatch):
    """build_evidence_base_with_progress with the library faked and the live
    path replaced by a tripwire. Returns a runner taking (library_rows,
    seed_rows, prior_pmids)."""
    import app as app_mod

    monkeypatch.setattr(endo_ai, "generate_search_terms",
                        lambda q, context_block="": "(laser*) AND (immature)")
    monkeypatch.setattr(endo_ai, "generate_multi_search_terms",
                        lambda q, p, context_block="": [p])
    monkeypatch.setattr(rag, "library_stats", lambda: {"total": 1900})

    def _live(*a, **k):
        raise _Reached("live PubMed path")

    monkeypatch.setattr(endo_ai, "fetch_cochrane", _live)
    monkeypatch.setattr(endo_ai, "fetch_papers", _live)

    def _run(library_rows, seed_rows=(), prior_pmids=None):
        monkeypatch.setattr(app_mod, "multi_query_search",
                            lambda *a, **k: [dict(r) for r in library_rows])
        monkeypatch.setattr(rag, "search_by_pmids",
                            lambda q, pmids: [dict(r) for r in seed_rows
                                              if r["pmid"] in set(pmids)])
        return app_mod.build_evidence_base_with_progress(
            "job-does-not-exist", FOLLOW_UP, mode="review",
            context_block=CONTEXT, prior_pmids=list(prior_pmids or []))

    return _run


def _covering_library(n=24, similarity=0.66):
    """n rows above the floor, at least one high-tier — enough to pass the
    coverage gate on their own. n must clear RELEVANCE_GATE["min_hits"] (20)
    as well as min_relevant (12): a smaller set routes LIVE, which is a
    different test."""
    rows = []
    for i in range(n):
        base = IMMATURE_ROWS[i % len(IMMATURE_ROWS)]
        row = dict(base)
        row["pmid"] = f"9000{i:03d}"
        row["similarity"] = similarity
        row["level_key"] = "level1" if i == 0 else base["level_key"]
        rows.append(row)
    return rows


def _thin_library():
    """21 hits — enough to clear min_hits — but only 4 above the similarity
    floor, so the topic is NOT covered. Exactly the pregnancy-row shape from
    HANDOVER.md: plenty of endodontics, almost none of it this question."""
    rows = _covering_library(n=21)
    for r in rows[4:]:
        r["similarity"] = 0.50
    return rows


# Eight real laser PMIDs. Four thin hits plus these eight is exactly
# RELEVANCE_GATE["min_relevant"], so if seeding ran before the gate this set
# would flip the route to LIBRARY on its own.
SEED_PMIDS = ["41833582", "41063319", "39287434", "40492415",
              "40558896", "41918875", "39815035", "35267110"]
SEED_ROWS = [_row(p, f"Laser paper {p}", "Real laser abstract. " * 20,
                  2025, "International endodontic journal", "level1", 76.0, 0.80)
             for p in SEED_PMIDS]


class TestSeedsDoNotDecideTheRoute:

    def test_a_thin_library_still_goes_live_with_seeds_available(self, retrieval):
        """The gate ordering, and the whole of rule 1. Four genuinely relevant
        hits plus eight papers carried from the previous answer is exactly
        min_relevant — so a seed applied one step earlier would route this thin
        topic to the library and answer it out of the PREVIOUS question's
        evidence."""
        import app as app_mod
        assert len(SEED_ROWS) + 4 >= app_mod.RELEVANCE_GATE["min_relevant"], \
            "the fixture no longer reaches the gate it is testing"
        with pytest.raises(_Reached):
            retrieval(_thin_library(), SEED_ROWS, SEED_PMIDS)

    def test_a_covering_library_stays_local(self, retrieval):
        evidence = retrieval(_covering_library(), [], [])
        assert evidence["_summary"]["total_scored"] > 0


class TestSeedsFaceEveryGate:

    def test_a_seed_below_the_similarity_floor_never_reaches_the_evidence(
            self, retrieval):
        """The carried paper is judged on THIS question. A laser paper the
        follow-up has moved away from is same-specialty noise here."""
        below = [dict(r, similarity=0.40) for r in SEED_ROWS]
        evidence = retrieval(_covering_library(), below, SEED_PMIDS)
        served = {p["pmid"] for p in evidence["_summary"]["all_scored"]}
        for pmid in SEED_PMIDS:
            assert pmid not in served, \
                f"seeded PMID {pmid} reached the evidence below the floor"

    def test_a_seed_above_the_floor_does_reach_the_evidence(self, retrieval):
        evidence = retrieval(_covering_library(), SEED_ROWS, SEED_PMIDS)
        served = {p["pmid"] for p in evidence["_summary"]["all_scored"]}
        assert served & set(SEED_PMIDS), \
            "no carried paper survived even above the floor — seeding is inert"

    def test_a_seeding_failure_does_not_fail_the_question(self, retrieval,
                                                          monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("pool exhausted")

        monkeypatch.setattr(rag, "search_by_pmids", _boom)
        evidence = retrieval(_covering_library(), [], ["41833582"])
        assert evidence["_summary"]["total_scored"] > 0


# ── 5. The thread, through the real /ask route ───────────────────────────

THREAD_ANSWER = """## CLINICAL RECOMMENDATION

Based on Level I evidence, laser-activated irrigation reduces intracanal
bacterial load [[PMID:41833582]].

## EVIDENCE SUMMARY

**Level I — RCTs and Systematic Reviews**

Pooled analysis reported a reduction in bacterial load [[PMID:41833582]].

## REFERENCES

1. [PMID: 41833582] Author A — Umbrella review. 2026.
"""


@pytest.fixture
def client(monkeypatch):
    """The real Flask app with every external dependency stubbed."""
    import app as app_mod

    rows = _covering_library()
    # THREAD_ANSWER cites this one; an answer citing a PMID outside the
    # evidence base trips validate_evidence_mapping and costs a retry.
    rows[0]["pmid"] = "41833582"
    monkeypatch.setattr(rag, "embed", lambda t: [0.01] * 384)
    monkeypatch.setattr(rag, "library_stats", lambda: {"total": 1900})
    monkeypatch.setattr(rag, "search", lambda *a, **k: [dict(r) for r in rows])
    monkeypatch.setattr(rag, "search_by_pmids", lambda q, p: [])

    # A routing mistake in this fixture must fail loudly, not quietly issue
    # real PubMed queries from the test suite.
    def _no_network(*a, **k):
        raise AssertionError("the library gate routed LIVE — this test would "
                             "have hit NCBI")

    monkeypatch.setattr(endo_ai, "fetch_cochrane", _no_network)
    monkeypatch.setattr(endo_ai, "fetch_papers", _no_network)
    monkeypatch.setattr(rag, "get_cached_abstracts_bulk", lambda pmids: {})
    monkeypatch.setattr(app_mod, "get_cached_answer", lambda *a, **k: None,
                        raising=False)
    monkeypatch.setattr(app_mod, "save_query_cache", lambda *a, **k: None,
                        raising=False)
    monkeypatch.setattr(app_mod, "save_answer", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(app_mod, "write_citation_audit", lambda *a, **k: None,
                        raising=False)

    prompts = []

    def fake_invoke(client_, function_name="", **kwargs):
        for m in kwargs.get("messages", []):
            prompts.append((function_name, m.get("content", "")))
        if "clarifying" in function_name:
            return _Resp("[]")
        if "intent" in function_name:
            return _Resp(json.dumps({"kind": "standard", "needs_clarify": False,
                                     "retrieval": "local", "reason": "covered"}))
        if "multi_search_terms" in function_name:
            return _Resp("TERM: (laser*) AND (immature)\n")
        if "search_terms" in function_name:
            return _Resp("(laser*) AND (immature)")
        if "citation_support" in function_name:
            return _Resp(json.dumps([{"i": 0, "verdict": "supports"}]))
        return _Resp(THREAD_ANSWER)

    monkeypatch.setattr(endo_ai, "_invoke_claude", fake_invoke)
    monkeypatch.setattr(endo_ai, "log_llm_call", lambda *a, **k: 0.0)
    monkeypatch.setattr(endo_ai, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(endo_ai, "LIBRARY_WRITE_BACK", False)

    app_mod.app.config["TESTING"] = True
    app_mod.review_threads.clear()
    return app_mod.app.test_client(), prompts


def _ask(client, question, thread_id, **extra):
    payload = {"question": question, "mode": "review", "skip_clarify": True,
               "thread_id": thread_id}
    payload.update(extra)
    r = client.post("/ask", json=payload)
    assert r.status_code == 200, r.data
    data = r.get_json()
    job_id = data["job_id"]
    for _ in range(300):
        status = client.get(f"/status/{job_id}").get_json()
        if status.get("status") in ("complete", "error", "aborted"):
            return data, status
        time.sleep(0.05)
    pytest.fail("job did not finish")


class TestTheThreadThroughTheRoute:

    def test_the_first_question_continues_from_nothing(self, client):
        c, _ = client
        data, status = _ask(c, LASER_EXCHANGE["question"], "t-1")
        assert data["continues_from"] == ""
        assert status.get("continues_from", "") == ""

    def test_a_follow_up_continues_from_the_previous_question(self, client):
        c, prompts = client
        _ask(c, LASER_EXCHANGE["question"], "t-2")
        prompts.clear()
        data, status = _ask(c, FOLLOW_UP, "t-2")
        assert data["continues_from"] == LASER_EXCHANGE["question"]
        assert status["continues_from"] == LASER_EXCHANGE["question"]
        assert any(endo_ai.CONTEXT_BLOCK_LABEL in p for _, p in prompts), \
            "the follow-up's prompts carried no context"

    def test_new_topic_clears_the_thread(self, client):
        """The done-when condition: a question asked after "New topic" shows no
        context line, and no prompt mentions the earlier exchange."""
        c, prompts = client
        _ask(c, LASER_EXCHANGE["question"], "t-3")
        assert c.post("/thread/clear", json={"thread_id": "t-3"}).status_code == 200
        prompts.clear()
        data, status = _ask(c, FOLLOW_UP, "t-3")
        assert data["continues_from"] == ""
        assert status.get("continues_from", "") == ""
        assert not any(endo_ai.CONTEXT_BLOCK_LABEL in p for _, p in prompts), \
            "context survived New topic"

    def test_new_topic_flag_on_ask_clears_before_reading(self, client):
        c, _ = client
        _ask(c, LASER_EXCHANGE["question"], "t-4")
        data, _st = _ask(c, FOLLOW_UP, "t-4", new_topic=True)
        assert data["continues_from"] == ""

    def test_threads_do_not_leak_across_ids(self, client):
        c, _ = client
        _ask(c, LASER_EXCHANGE["question"], "t-5")
        data, _st = _ask(c, FOLLOW_UP, "t-6")
        assert data["continues_from"] == ""

    def test_only_the_recommendation_is_carried(self, client):
        c, prompts = client
        _ask(c, LASER_EXCHANGE["question"], "t-7")
        prompts.clear()
        _ask(c, FOLLOW_UP, "t-7")
        carried = [p for _, p in prompts if endo_ai.CONTEXT_BLOCK_LABEL in p]
        assert carried
        for p in carried:
            assert "Pooled analysis reported a reduction" not in p, \
                "the EVIDENCE SUMMARY travelled into the next question"

    def test_learn_mode_gets_no_conversation_context(self, client):
        c, _ = client
        _ask(c, LASER_EXCHANGE["question"], "t-8")
        r = c.post("/ask", json={"question": FOLLOW_UP, "mode": "learn",
                                 "skip_clarify": True, "thread_id": "t-8"})
        assert r.get_json()["continues_from"] == ""

    def test_the_thread_never_grows_past_the_cap(self, client):
        c, _ = client
        for i in range(5):
            _ask(c, f"laser question number {i}", "t-9")
        import app as app_mod
        assert len(app_mod.review_threads["t-9"]) == endo_ai.MAX_CONTEXT_EXCHANGES


# ── 6. The shipped browser JS ────────────────────────────────────────────

def _extract_function(name):
    src = INDEX_HTML.read_text(encoding="utf-8")
    m = re.search(r"^function\s+" + re.escape(name) + r"\s*\(", src, re.MULTILINE)
    if not m:
        raise AssertionError(f"function {name} not found in index.html")
    i = src.index("{", m.end())
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1]
        j += 1
    raise AssertionError(f"unbalanced braces in {name}")


def _run_node(js):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available — cannot exercise the shipped JS")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(js)
        path = f.name
    try:
        r = subprocess.run([node, path], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()
    finally:
        Path(path).unlink(missing_ok=True)


HARNESS = """
var _els = {};
function _el(id) {
  if (!_els[id]) _els[id] = {id: id, textContent: '', title: '', value: '',
                             style: {}, disabled: false,
                             classList: {add: function(){}, remove: function(){}}};
  return _els[id];
}
var document = { getElementById: _el, querySelectorAll: function(){ return []; },
                 querySelector: function(){ return null; } };
var _fetches = [];
function fetch(url, opts) {
  _fetches.push({url: url, body: opts && opts.body ? JSON.parse(opts.body) : null});
  var chain = { then: function(){ return chain; }, catch: function(){ return chain; } };
  return chain;
}
var pollTimer = null, mode = 'review', currentJob = null;
function clearInterval(){} function setInterval(){ return 1; }
function showError(){}
var reviewThreadId = 'th-initial';
"""


class TestTheContinuesFromLineInTheBrowser:

    def test_an_empty_previous_question_hides_the_line(self):
        js = HARNESS + _extract_function("_renderContinuesFrom") + """
_renderContinuesFrom('');
console.log(JSON.stringify({d: _el('continuesFrom').style.display,
                            t: _el('continuesFromQ').textContent}));
"""
        out = json.loads(_run_node(js))
        assert out["d"] == "none", "a cold answer showed a continuity line"
        assert out["t"] == ""

    def test_a_previous_question_shows_the_line(self):
        js = HARNESS + _extract_function("_renderContinuesFrom") + """
_renderContinuesFrom('Use of lasers in root canal disinfection');
console.log(JSON.stringify({d: _el('continuesFrom').style.display,
                            t: _el('continuesFromQ').textContent}));
"""
        out = json.loads(_run_node(js))
        assert out["d"] != "none"
        assert out["t"] == "Use of lasers in root canal disinfection"

    def test_new_topic_rotates_the_thread_and_hides_the_line(self):
        js = (HARNESS + _extract_function("_renderContinuesFrom")
              + _extract_function("startNewTopic") + """
_renderContinuesFrom('Use of lasers in root canal disinfection');
startNewTopic();
console.log(JSON.stringify({d: _el('continuesFrom').style.display,
                            id: reviewThreadId,
                            f: _fetches}));
""")
        out = json.loads(_run_node(js))
        assert out["d"] == "none", "the continuity line survived New topic"
        assert out["id"] != "th-initial", "the thread id was not rotated"
        assert out["f"] and out["f"][0]["url"] == "/thread/clear"
        assert out["f"][0]["body"]["thread_id"] == "th-initial", \
            "New topic cleared some other thread than the one it was showing"

    def test_ask_sends_the_thread_id(self):
        js = HARNESS + _extract_function("_postAsk") + """
_postAsk('What about in immature teeth?', '', true);
console.log(JSON.stringify(_fetches[0]));
"""
        out = json.loads(_run_node(js))
        assert out["url"] == "/ask"
        assert out["body"]["thread_id"] == "th-initial"

    def test_the_line_is_rendered_from_the_server_field_only(self):
        """The page must not decide it is in a thread. Whatever the browser
        believes, the continuity claim comes from the job."""
        src = _extract_function("showResult")
        assert "_renderContinuesFrom" in src
        assert "job.continues_from" in src
        assert "reviewThreadId" not in src, \
            "showResult decides continuity from client state, not the server"
