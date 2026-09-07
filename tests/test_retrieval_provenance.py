"""Item C (2026-09-08) — a stored answer records the query that built its pool.

WHAT WAS MISSING. A stored answer named its papers but not how they were found,
and `generate_search_terms` produced a different query on every run — measured
0/10 reproducible across 10 eval questions x 5 runs. So for every answer in
`query_cache`, the pool could be re-listed but never re-derived: there was no
record of what was actually asked of PubMed, and re-running the question
produced a different query and therefore a different pool.

That is the difference between an audit trail and a list. A clinician asking
"why these papers?" a year from now needs the question that was searched, not
just what came back.

The column is NULLABLE and stays so. The 100+ answers stored before this item
have no honest value to put in it, and back-filling a guess would be worse than
a NULL: it would look like a record of what happened.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import endo_ai as E  # noqa: E402
import rag  # noqa: E402

Q = "MTA versus bioceramic as retrograde filling after apicoectomy"
GOOD = '(MTA OR "mineral trioxide") AND (retrograde OR "root-end") AND (apicoect*)'


def _stub_generator(monkeypatch, text=GOOD, cached=None):
    monkeypatch.setattr(rag, "get_cached_terms", lambda *a, **k: cached)
    monkeypatch.setattr(rag, "cache_terms", lambda *a, **k: True)
    monkeypatch.setattr(E, "log_llm_call", lambda *a, **k: None)
    monkeypatch.setattr(E, "_get_api_key", lambda: "test")
    monkeypatch.setattr(E, "_invoke_claude", lambda *a, **k: type("M", (), {
        "usage": type("U", (), {"input_tokens": 1, "output_tokens": 1})(),
        "content": [type("C", (), {"text": text})()]})())


class TestTheGeneratorRecordsWhatItDid:

    def test_a_generated_query_is_recorded_with_its_key(self, monkeypatch):
        _stub_generator(monkeypatch)
        E.generate_search_terms(Q, mode="review")
        p = E.retrieval_provenance()
        assert p["terms"] == GOOD
        assert p["source"] == "model"
        assert p["mode"] == "review"
        assert len(p["cache_key"]) == 64, "the key is a sha256"
        assert p["question_norm"] == E._normalise_question(Q)

    def test_a_cache_hit_says_it_was_a_cache_hit(self, monkeypatch):
        """A pool built from a cached query and one built from a fresh call are
        not the same event, and an audit trail that cannot tell them apart
        cannot answer "was this the model's judgement, or a replay?"."""
        E.TERM_CACHE_ENABLED = True   # conftest turns it off by default
        _stub_generator(monkeypatch, cached=GOOD)
        E.generate_search_terms(Q, mode="review")
        assert E.retrieval_provenance()["source"] == "cache"

    def test_a_degraded_run_is_recorded_as_degraded(self, monkeypatch):
        """The fallback is the RAW QUESTION, which has no AND-groups, so A1's
        coverage condition abstains and the run takes the LIBRARY route — the
        less cautious of the two — on a signal nothing else records. An answer
        produced that way must say so."""
        _stub_generator(monkeypatch, text="")
        monkeypatch.setattr(E, "_log_term_degradation", lambda *a, **k: None)
        out = E.generate_search_terms(Q, mode="review")
        assert out == Q
        p = E.retrieval_provenance()
        assert p["source"] == "degraded", (
            "a degraded retrieval is indistinguishable from a good one in the "
            "record it leaves: %r" % p)

    def test_the_caller_cannot_hold_a_live_reference(self, monkeypatch):
        """`retrieval_provenance()` returns a COPY. A caller that stashed the
        thread-local itself would find its stored answer's provenance rewritten
        by the next question on that worker thread."""
        _stub_generator(monkeypatch)
        E.generate_search_terms(Q, mode="review")
        held = E.retrieval_provenance()
        _stub_generator(monkeypatch, text='(other) AND (query OR thing)')
        E.generate_search_terms("A completely different question", mode="learn")
        assert held["terms"] == GOOD, (
            "the first answer's provenance was overwritten by the second "
            "question")


@pytest.mark.skipif(not rag.DATABASE_URL, reason="DATABASE_URL not set")
class TestItReachesTheStoredAnswer:

    def _rows(self, sql, args=()):
        conn = rag.get_conn()
        cur = conn.cursor()
        cur.execute(sql, args)
        out = cur.fetchall()
        cur.close()
        conn.close()
        return out

    def test_the_column_exists(self):
        got = self._rows("""
            SELECT column_name, is_nullable FROM information_schema.columns
            WHERE table_name = 'query_cache'
              AND column_name = 'retrieval_provenance'
        """)
        assert got, "query_cache has no retrieval_provenance column"
        assert got[0][1] == "YES", (
            "the column must stay nullable — answers stored before this item "
            "have no honest value and a back-filled guess would look like a "
            "record of what happened")

    def test_a_saved_answer_carries_its_query(self):
        marker = "ZZ-provenance-roundtrip-test"
        prov = {"terms": GOOD, "cache_key": "a" * 64, "mode": "review",
                "source": "model", "question_norm": marker}
        conn = rag.get_conn()
        cur = conn.cursor()
        try:
            rag.save_query_cache(marker, "answer text", [],
                                 retrieval_provenance=prov)
            cur.execute("SELECT retrieval_provenance FROM query_cache "
                        "WHERE question_text = %s", (marker,))
            row = cur.fetchone()
            assert row, "the answer was not stored"
            assert row[0], "stored with no provenance"
            back = json.loads(row[0])
            assert back["terms"] == GOOD
            assert back["source"] == "model"
        finally:
            cur.execute("DELETE FROM query_cache WHERE question_text = %s",
                        (marker,))
            conn.commit()
            cur.close()
            conn.close()

    def test_omitting_it_stores_null_rather_than_an_empty_object(self):
        """`{}` would read as "we recorded the provenance and it was empty".
        NULL reads as "not recorded", which is the truth for every answer
        stored before this item."""
        marker = "ZZ-provenance-null-test"
        conn = rag.get_conn()
        cur = conn.cursor()
        try:
            rag.save_query_cache(marker, "answer text", [])
            cur.execute("SELECT retrieval_provenance FROM query_cache "
                        "WHERE question_text = %s", (marker,))
            assert cur.fetchone()[0] is None
        finally:
            cur.execute("DELETE FROM query_cache WHERE question_text = %s",
                        (marker,))
            conn.commit()
            cur.close()
            conn.close()


class TestTheWiringNotJustTheHelper:
    """`app.py` is what actually stores answers. A provenance helper nobody
    calls is the defect rule 14 exists for."""

    def test_app_passes_the_provenance_to_the_store(self):
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "app.py"), encoding="utf-8").read()
        i = src.index("save_query_cache(")
        call = src[max(0, i - 400):i + 200]
        assert "retrieval_provenance" in call, (
            "app.py stores answers without their query")
        assert "retrieval_provenance()" in call, (
            "app.py does not read the generator's record")
