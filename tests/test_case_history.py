"""Case discussions reach the History sidebar — and are never served back.

THE DEFECT. Case was the one mode whose answers vanished when the tab closed.
The whole READ path was already case-aware and had been all along:

    /history            parses the `[case] ` prefix into a mode tag
    /history/<id>       parses it again and returns `mode`
    loadHistoryItem()   branches on `itemMode === 'case'`

Nothing ever wrote a `[case] ` row. `save_query_cache` is called once, in the
`/ask` job path; `run_case_chat` completed with `update_job` and stopped.

THE TRAP, which is why this file exists. `query_cache` is BOTH the history
store and the answer cache, and `get_cached_answer` filters on cosine and
`context_hash` with no mode term. Writing case rows would therefore have made
patient A's case discussion eligible to be returned for patient B's similar
description at >=0.92 cosine — the worst failure this system can have, arriving
as a side effect of a history feature. Invariant 21 forbids exactly that.

So the fix has two halves and the second is what makes the first safe:

    save_case_history()   writes one row per CONVERSATION, updated in place
    get_cached_answer()   excludes every `[case] ` row, in the WHERE clause

`TestTheGuardIsLoadBearing` is the rule-4 pair: it proves the exclusion is what
does the work, rather than the embedding happening to be distant.

Live-DB tests follow `test_cache_invalidation.py`: they seed their own rows and
remove them again, and skip without DATABASE_URL.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import rag  # noqa: E402

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL") and not getattr(rag, "DATABASE_URL", None),
    reason="live query_cache required")

CONV = "pytest-case-history-conv"
# Every row this file writes carries this marker, so cleanup can find them
# even when the mutation harness has broken the context key they are filed
# under. It is inside the question text, which no mutant touches.
_SENTINEL = "PYTEST-CASE-HISTORY-ROW"
# A real case description, from the `case-opening-full` eval fixture, with the
# sentinel appended so it can never be mistaken for a clinician's own row.
CASE_Q = ("62-year-old female, well-controlled type 2 diabetes, no other "
          "medical history, no bisphosphonates. Tooth 26, previously root "
          "treated 8 years ago, now tender to percussion for 3 weeks. "
          + _SENTINEL)


def _exec(sql, params=(), fetch=False, commit=False):
    """Run one statement and ALWAYS return the connection to the pool.

    `rag.get_conn()` hands out a POOLED connection; it has to be closed to go
    back. A first version of this file used `with rag.get_conn().cursor()` and
    never closed the connection, so the pool drained after two tests and the
    third blocked forever waiting for a free one — the suite looked hung rather
    than failed. Production does the same thing correctly in a `finally`
    (`save_query_cache`), which is what this mirrors.
    """
    conn = rag.get_conn()
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        rows = cur.fetchall() if fetch else None
        if commit:
            conn.commit()
        return rows
    finally:
        cur.close()
        conn.close()


def _rows(ctx_like="case:pytest-case-history%"):
    return _exec("SELECT id, question_text, answer, context_hash "
                 "FROM query_cache WHERE context_hash LIKE %s",
                 (ctx_like,), fetch=True)


def _purge():
    """Remove this file's rows — by BOTH keys, deliberately.

    Purging on `context_hash` alone is not enough. The mutation harness has a
    mutant that replaces the conversation key with a constant, and under it the
    tests wrote rows the purge pattern no longer matched: a row leaked into the
    real `query_cache` and showed up in the History sidebar. A cleanup must not
    depend on the thing being mutated, so it also matches the sentinel text
    these tests write.
    """
    _exec("DELETE FROM query_cache WHERE context_hash LIKE %s "
          "   OR question_text LIKE %s OR question_text LIKE %s",
          ("case:pytest-case-history%",
           "%" + _SENTINEL + "%",
           "[review] pytest sentinel%"), commit=True)


@pytest.fixture(autouse=True)
def clean():
    _purge()
    yield
    _purge()


class TestOneRowPerConversation:
    """`save_query_cache` is a plain INSERT. Called per turn it would fill the
    sidebar with rows whose `question_text` is identical, because every turn
    carries the same `messages[0]` case description."""

    def test_first_turn_creates_a_row(self):
        rag.save_case_history(CONV, CASE_Q, "turn 1 answer", [{"pmid": "1"}])
        rows = _rows()
        assert len(rows) == 1, rows
        assert rows[0][1].startswith("[case] "), rows[0][1]
        assert rows[0][3] == "case:%s" % CONV

    def test_later_turns_update_that_row_instead_of_adding(self):
        rag.save_case_history(CONV, CASE_Q, "turn 1 answer", [{"pmid": "1"}])
        rag.save_case_history(CONV, CASE_Q, "turn 2 answer, longer",
                              [{"pmid": "1"}, {"pmid": "2"}])
        rag.save_case_history(CONV, CASE_Q, "turn 3 answer, longer still",
                              [{"pmid": "1"}, {"pmid": "2"}, {"pmid": "3"}])
        rows = _rows()
        assert len(rows) == 1, "three turns produced %d rows" % len(rows)
        assert rows[0][2] == "turn 3 answer, longer still", rows[0][2]

    def test_a_second_conversation_is_its_own_row(self):
        rag.save_case_history(CONV, CASE_Q, "conv A", [])
        rag.save_case_history(CONV + "-b", "A different patient entirely. " + _SENTINEL,
                              "conv B", [])
        assert len(_rows()) == 2


class TestInvariant21:
    """A case answer is never served to anyone.

    TWO INDEPENDENT DEFENCES, and it matters which one is being tested.
    `save_case_history` writes into a `case:<conv_id>` context partition, and
    `context_hash` is already an equality term in the lookup — so a case row
    written by THIS implementation is unreachable even with the prefix guard
    deleted. A first version of this class asserted only that, and the mutant
    that removes the guard survived every test in the file.

    The prefix guard defends the OTHER case: a `[case] ` row sitting in the
    default partition, which is precisely what the obvious fix — "just call
    `save_query_cache` from `case_chat`" — would have produced.
    """

    def test_a_case_row_is_not_returned_for_its_own_question(self):
        rag.save_case_history(CONV, CASE_Q, "patient A's discussion", [])
        assert rag.get_cached_answer(CASE_Q) is None, (
            "a case answer was served back — invariant 21 is broken")

    def test_a_case_row_is_not_returned_to_a_similar_case(self):
        """The real risk is not the identical question, it is the NEXT
        patient whose description embeds close to this one."""
        rag.save_case_history(CONV, CASE_Q, "patient A's discussion", [])
        near = ("61-year-old woman, controlled type 2 diabetes, no other "
                "medical history, no bisphosphonates. Tooth 26, root treated "
                "8 years ago, tender to percussion for 3 weeks. " + _SENTINEL)
        assert rag.get_cached_answer(near) is None, (
            "patient A's case answer was offered for patient B")

    def test_a_case_row_in_the_DEFAULT_partition_is_still_refused(self):
        """The guard's actual job.

        Written with `context_hash=''`, so the partition offers no protection
        at all and only `question_text NOT LIKE '[case] %'` stands between
        patient A's discussion and patient B's question. This is the shape a
        naive `save_query_cache(f"[case] {q}", ...)` fix produces.
        """
        key = "[case] " + CASE_Q
        _exec("INSERT INTO query_cache (question_text, question_embedding,"
              " answer, papers, context_hash) VALUES (%s,%s,%s,%s,%s)",
              (key, rag.embed(key), "patient A's discussion", "[]", ""),
              commit=True)
        try:
            assert rag.get_cached_answer(key) is None, (
                "a [case] row in the default partition was served — the only "
                "thing guarding invariant 21 here is the prefix exclusion")
        finally:
            _exec("DELETE FROM query_cache WHERE question_text = %s AND "
                  "COALESCE(context_hash,'') = ''", (key,), commit=True)

    def test_that_refusal_is_the_PREFIX_doing_the_work(self):
        """Rule 4's pair for the test above: the identical row, identical
        empty partition, with `[case] ` stripped, MUST come back. If it does
        not, the test above is measuring a cache that never matches rather
        than a guard that refuses."""
        key = CASE_Q
        _exec("INSERT INTO query_cache (question_text, question_embedding,"
              " answer, papers, context_hash) VALUES (%s,%s,%s,%s,%s)",
              (key, rag.embed(key), "served", "[]", ""), commit=True)
        try:
            hit = rag.get_cached_answer(key)
            assert hit is not None and hit["answer"] == "served", (
                "the un-prefixed twin was ALSO refused, so the guard test "
                "above proves nothing")
        finally:
            _exec("DELETE FROM query_cache WHERE question_text = %s AND "
                  "COALESCE(context_hash,'') = ''", (key,), commit=True)

    def test_the_case_row_is_still_visible_to_history(self):
        """Excluding it from the cache must not hide it from the sidebar —
        that would fix the leak by removing the feature."""
        rag.save_case_history(CONV, CASE_Q, "patient A's discussion", [])
        rows = _exec("SELECT question_text FROM query_cache "
                     "WHERE context_hash = %s", ("case:%s" % CONV,), fetch=True)
        assert rows and rows[0][0].startswith("[case] "), rows


class TestTheGuardIsLoadBearing:
    """Rule 4 — without this, every assertion above passes against a broken
    guard, because they cannot tell "excluded by the WHERE clause" from
    "never matched anything in the first place"."""

    def test_the_same_row_without_the_prefix_IS_served(self):
        """Identical text and identical partition, `[case] ` removed. If this
        does not come back, the tests above prove nothing about the exclusion —
        they are just measuring a cache that never matches."""
        key = CASE_Q
        _exec("INSERT INTO query_cache (question_text, question_embedding,"
              " answer, papers, context_hash) VALUES (%s,%s,%s,%s,%s)",
              (key, rag.embed(key), "served", "[]",
               "case:pytest-case-history-bare"), commit=True)
        try:
            hit = rag.get_cached_answer(CASE_Q,
                                        context_hash="case:pytest-case-history-bare")
            assert hit is not None, (
                "an un-prefixed row with the same text was ALSO not served, so "
                "the invariant-21 tests are vacuous — the miss has some other "
                "cause")
            assert hit["answer"] == "served"
        finally:
            _purge()

    def test_review_lookups_are_unaffected(self):
        """The exclusion must not have broken ordinary caching."""
        key = "[review] pytest sentinel question about apical periodontitis"
        _exec("INSERT INTO query_cache (question_text, question_embedding,"
              " answer, papers, context_hash) VALUES (%s,%s,%s,%s,%s)",
              (key, rag.embed(key), "review answer", "[]",
               "case:pytest-case-history-review"), commit=True)
        try:
            hit = rag.get_cached_answer(
                key, context_hash="case:pytest-case-history-review")
            assert hit is not None and hit["answer"] == "review answer"
        finally:
            _purge()


class TestTheCompletionPathCallsIt:
    """Rule 14, and last night's M9 lesson: a test that calls the helper
    directly passes with nothing calling it. This drives the real
    `run_case_chat` with its generation stubbed."""

    def test_run_case_chat_records_history_on_completion(self, monkeypatch):
        import app
        import endo_ai

        seen = {}

        def _fake_save(conv_id, question, answer, papers):
            seen.update(conv_id=conv_id, question=question,
                        answer=answer, papers=papers)

        monkeypatch.setattr(rag, "save_case_history", _fake_save)
        monkeypatch.setattr(endo_ai, "classify_case_intent",
                            lambda *a, **k: "treatment")
        monkeypatch.setattr(endo_ai, "case_prior_pmids", lambda *a, **k: [])
        monkeypatch.setattr(endo_ai, "ask_case_question",
                            lambda *a, **k: ("THE ANSWER", 0.01))
        monkeypatch.setattr(
            app, "build_evidence_base_with_progress",
            lambda *a, **k: {"_summary": {"all_scored": [{"pmid": "42"}]}})

        job_id = app.create_job(CASE_Q, mode="case")
        app.run_case_chat(job_id, [{"role": "user", "content": CASE_Q}],
                          "conv-under-test")

        assert seen, "run_case_chat completed without recording history"
        assert seen["conv_id"] == "conv-under-test"
        assert seen["question"] == CASE_Q
        assert seen["answer"] == "THE ANSWER"
        assert seen["papers"] == [{"pmid": "42"}]

    def test_a_history_failure_does_not_lose_the_answer(self, monkeypatch):
        """The write is after `update_job` on purpose: the clinician must keep
        the answer already on screen even if the sidebar write fails."""
        import app
        import endo_ai

        def _boom(*a, **k):
            raise RuntimeError("history table on fire")

        monkeypatch.setattr(rag, "save_case_history", _boom)
        monkeypatch.setattr(endo_ai, "classify_case_intent",
                            lambda *a, **k: "treatment")
        monkeypatch.setattr(endo_ai, "case_prior_pmids", lambda *a, **k: [])
        monkeypatch.setattr(endo_ai, "ask_case_question",
                            lambda *a, **k: ("THE ANSWER", 0.01))
        monkeypatch.setattr(
            app, "build_evidence_base_with_progress",
            lambda *a, **k: {"_summary": {"all_scored": []}})

        job_id = app.create_job(CASE_Q, mode="case")
        app.run_case_chat(job_id, [{"role": "user", "content": CASE_Q}], "c2")

        job = app.get_job(job_id) if hasattr(app, "get_job") else app.jobs[job_id]
        assert job["status"] == "complete", job.get("status")
        assert job["answer"] == "THE ANSWER"
