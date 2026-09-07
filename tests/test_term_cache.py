"""Item C (2026-09-08) — the search-term cache, and what its key must contain.

THE MEASUREMENT THAT MADE THIS NECESSARY. `generate_search_terms` is the one
model call every retrieval depends on, and it passed no `temperature`, so the
API default applied. Across 10 real eval questions x 5 runs:

    identical query string     0/10
    identical AND-group set    0/10
    mean pairwise Jaccard      0.135
    5 distinct queries in 5 runs   9 of 10 questions

Two runs of the same build were searching PubMed for different things. That is
the root of rule 38 — the 2026-09-06 "confinement proof" measured 61/256 pools
changed against an IDENTICAL build — and of A54's probe returning three
different guideline pools. With `temperature=0` the same measurement is 10/10.

So why a cache at all, if temperature 0 already fixed it? Because temperature 0
is near-deterministic in a SERVED model, not guaranteed, and says nothing across
a model version change. The cache pins the exact string a stored answer was
built from, which is what makes a pool re-derivable a year later rather than
re-guessed. The tests below are about the KEY, because a cache that returns the
wrong entry is worse than no cache: it is a wrong pool, served silently.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import endo_ai as E  # noqa: E402
import rag  # noqa: E402

Q = "Single-visit versus multiple-visit root canal treatment for necrotic teeth"
PROMPT = "Convert this question into a PubMed query.\nQuestion: %s\nQuery:" % Q


class TestTheQuestionIsNormalisedButNotMangled:

    def test_case_and_whitespace_do_not_make_a_new_entry(self):
        assert (E._normalise_question("  Single-Visit   VERSUS Multiple  ")
                == E._normalise_question("single-visit versus multiple"))

    def test_a_trailing_question_mark_does_not_make_a_new_entry(self):
        assert (E._normalise_question("Does MTA work?")
                == E._normalise_question("Does MTA work"))

    def test_two_clinically_different_questions_never_collide(self):
        """The normalisation is deliberately shallow. Stemming or stopword
        removal would fold these two onto one cache entry and serve the pool
        for one as the evidence for the other."""
        a = E._normalise_question(
            "MTA versus Biodentine for pulpotomy in mature permanent teeth")
        b = E._normalise_question(
            "MTA versus Biodentine for pulpotomy in immature permanent teeth")
        assert a != b

    def test_negation_survives_normalisation(self):
        assert (E._normalise_question("antibiotics indicated")
                != E._normalise_question("antibiotics not indicated"))


class TestTheKey:

    def test_the_same_question_and_prompt_give_the_same_key(self):
        k1, _ = E._term_cache_key(Q, PROMPT, "review")
        k2, _ = E._term_cache_key(Q, PROMPT, "review")
        assert k1 == k2

    def test_the_mode_is_part_of_the_key(self):
        """`review` and `learn` apply different tier quotas to the same pool,
        and a follow-up asked in one mode must not be answered from terms
        generated for the other."""
        k1, _ = E._term_cache_key(Q, PROMPT, "review")
        k2, _ = E._term_cache_key(Q, PROMPT, "learn")
        assert k1 != k2

    def test_changing_the_prompt_retires_the_entry(self):
        """THE POINT OF HASHING THE PROMPT. Without this, improving the prompt
        leaves every existing question served by the old prompt's terms —
        silently, and precisely when someone has just made it better."""
        k1, _ = E._term_cache_key(Q, PROMPT, "review")
        k2, _ = E._term_cache_key(Q, PROMPT + "\nPrefer MeSH terms.", "review")
        assert k1 != k2

    def test_the_question_is_elided_from_the_prompt_hash(self):
        """Otherwise the question is counted twice and nothing breaks — but a
        prompt that embeds the question would make the prompt component vary
        per question, so a genuine prompt CHANGE could not be distinguished
        from a different question. The key must separate the two."""
        other = "Does CBCT change management in apical periodontitis"
        k_a, _ = E._term_cache_key(Q, PROMPT, "review")
        k_b, _ = E._term_cache_key(
            other, PROMPT.replace(Q, other), "review")
        # different questions, same template -> different keys
        assert k_a != k_b
        # same question, same template, reached via a different call -> same key
        k_c, _ = E._term_cache_key(Q, PROMPT, "review")
        assert k_a == k_c

    def test_a_conversation_context_block_changes_the_key(self):
        """`_with_context` prepends the earlier exchange, which changes what
        the model is asked and therefore what it returns. A follow-up must not
        be served the cold question's terms."""
        k1, _ = E._term_cache_key(Q, PROMPT, "review")
        k2, _ = E._term_cache_key(
            Q, "Earlier: we discussed immature teeth.\n" + PROMPT, "review")
        assert k1 != k2


@pytest.mark.skipif(not rag.DATABASE_URL, reason="DATABASE_URL not set")
class TestTheStore:

    KEY = "test-term-cache-%s" % ("0" * 32)

    def _clean(self):
        conn = rag.get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM search_term_cache WHERE cache_key = %s",
                    (self.KEY,))
        conn.commit()
        cur.close()
        conn.close()

    def setup_method(self):
        rag.setup_term_cache()
        self._clean()

    def teardown_method(self):
        self._clean()

    def test_a_miss_returns_none(self):
        assert rag.get_cached_terms(self.KEY) is None

    def test_what_goes_in_comes_back_out(self):
        terms = '(a OR b) AND (c OR d)'
        assert rag.cache_terms(self.KEY, Q, "q", terms, mode="review")
        assert rag.get_cached_terms(self.KEY) == terms

    def test_an_entry_is_never_silently_rewritten(self):
        """An entry records what a given prompt produced. Overwriting it would
        erase exactly the provenance the cache exists to keep — a stored answer
        pointing at this key would then name a query that never built it."""
        rag.cache_terms(self.KEY, Q, "q", "(first) AND (query)", mode="review")
        rag.cache_terms(self.KEY, Q, "q", "(second) AND (query)", mode="review")
        assert rag.get_cached_terms(self.KEY) == "(first) AND (query)"

    def test_an_empty_query_is_never_stored(self):
        assert not rag.cache_terms(self.KEY, Q, "q", "", mode="review")
        assert rag.get_cached_terms(self.KEY) is None


class TestTheDegradedFallbackIsNeverCached:
    """`generate_search_terms` falls back to the RAW QUESTION when it cannot
    parse a query. Caching that would freeze a known-bad retrieval in place
    and hide it: the next run would hit the cache, print nothing, and never
    re-attempt generation. `_log_term_degradation` counts those runs; the
    cache must not remember them.
    """

    def test_the_fallback_path_writes_nothing(self, monkeypatch):
        """MUTATION-CHECKED BY RUNNING THE REAL FUNCTION with a model that
        returns junk, not by reading the source for a guard."""
        writes = []
        monkeypatch.setattr(rag, "cache_terms",
                            lambda *a, **k: writes.append(a) or True)
        monkeypatch.setattr(rag, "get_cached_terms", lambda *a, **k: None)

        class _Msg:
            usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()
            content = [type("C", (), {"text": ""})()]

        monkeypatch.setattr(E, "_invoke_claude", lambda *a, **k: _Msg())
        monkeypatch.setattr(E, "log_llm_call", lambda *a, **k: None)
        monkeypatch.setattr(E, "_log_term_degradation", lambda *a, **k: None)
        monkeypatch.setattr(E, "_get_api_key", lambda: "test")

        out = E.generate_search_terms(Q, mode="review")
        assert out == Q, "the degraded fallback is the raw question"
        assert writes == [], (
            "a degraded run was written to the cache — the next run would hit "
            "it and never retry generation")

    def test_a_good_query_IS_written(self, monkeypatch):
        """The control arm. Without it the test above passes for a build in
        which the cache write never happens at all."""
        writes = []
        monkeypatch.setattr(rag, "cache_terms",
                            lambda *a, **k: writes.append(a) or True)
        monkeypatch.setattr(rag, "get_cached_terms", lambda *a, **k: None)

        good = '(single-visit OR "one-visit") AND ("root canal" OR endodontic*)'

        class _Msg:
            usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()
            content = [type("C", (), {"text": good})()]

        monkeypatch.setattr(E, "_invoke_claude", lambda *a, **k: _Msg())
        monkeypatch.setattr(E, "log_llm_call", lambda *a, **k: None)
        monkeypatch.setattr(E, "_get_api_key", lambda: "test")

        out = E.generate_search_terms(Q, mode="review")
        assert out and out != Q
        assert len(writes) == 1, "a usable query was not cached"


class TestProvenanceDoesNotLeakBetweenThreads:

    def test_two_threads_record_their_own_question(self, monkeypatch):
        """A module-level dict here would let one question's query string be
        stored as another question's provenance — a wrong audit trail, which
        is worse than none because it looks authoritative. Curo serves
        concurrent requests and the curriculum builder runs a thread pool.
        """
        import threading

        monkeypatch.setattr(rag, "get_cached_terms", lambda *a, **k: None)
        monkeypatch.setattr(rag, "cache_terms", lambda *a, **k: True)
        monkeypatch.setattr(E, "log_llm_call", lambda *a, **k: None)
        monkeypatch.setattr(E, "_get_api_key", lambda: "test")

        def fake_invoke(*a, **k):
            q = k["messages"][0]["content"]
            # REAL QUERY SHAPE. `_clean_single_query` rejects a bare
            # "(alpha)": it wants OR-groups joined by AND, and a rejected
            # query falls back to the raw question — which made the first
            # version of this test assert against the fallback instead of
            # against the provenance it meant to check.
            term = ('(laser* OR aPDT) AND ("root canal" OR endodontic*)'
                    if "lasers" in q else
                    '(CBCT OR "cone beam") AND ("apical periodontitis")')
            return type("M", (), {
                "usage": type("U", (), {"input_tokens": 1,
                                        "output_tokens": 1})(),
                "content": [type("C", (), {"text": term})()]})()

        monkeypatch.setattr(E, "_invoke_claude", fake_invoke)

        got, barrier = {}, threading.Barrier(2)

        def run(question, slot):
            E.generate_search_terms(question, mode="review")
            barrier.wait(timeout=10)          # force the overlap
            got[slot] = E.retrieval_provenance()

        ts = [threading.Thread(target=run, args=("Use of lasers in canals", "a")),
              threading.Thread(target=run, args=("CBCT versus radiography", "b"))]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=20)

        assert "laser" in got["a"]["terms"], got["a"]
        assert "CBCT" in got["b"]["terms"], got["b"]
        assert "lasers" in got["a"]["question_norm"]
        assert "cbct" in got["b"]["question_norm"]
