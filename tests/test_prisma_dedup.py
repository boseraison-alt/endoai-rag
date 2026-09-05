"""
A38 — the PRISMA dedup notice asserted a bibliographic fact the engine could
not know, and it acted on it.

WHAT IT DID. It took the newest SR/MA *year* anywhere in cochrane+level1,
subtracted a two-year buffer, flagged every older primary study, and wrote into
the synthesis prompt that those papers were "likely already synthesised inside
PMID X — defer to the SR's pooled estimate". No topic test. No citation linkage.

WHAT WAS MEASURED, across the 29 eval questions (2026-09-03):

    1,294 of 3,301 retrieved papers — 39% of everything retrieved — carried
    that claim. Median 39% per question, min 24%, max 53%. All 29 questions.

    Where PubMed exposes the nominated review's reference list, 10 of 482
    flagged papers were actually cited by it. TWO PERCENT.

    The rule nominated a different review from the most relevant one on 26 of
    29 questions, and on the bisphosphonate question 70 of 133 papers were told
    to defer to "Regenerative Potential of Biodentine in Complex Endodontic
    Cases" — including MRONJ radiographic predictors.

This file did not exist before the fix. A mechanism that rewrote the synthesis
prompt on every answer, on 39% of every pool, had no test of any kind — which is
the same shape as the three inert checks A32 and Q1 found, except this one was
not inert.

Every test here is mutation-checked.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai as e


def sr(pmid, year, sim=0.0, tier="level1"):
    return {"pmid": pmid, "year": year, "similarity": sim, "score": 70.0,
            "title": f"review {pmid}", "level_key": tier}


def primary(pmid, year, tier="level3a"):
    return {"pmid": pmid, "year": year, "score": 50.0,
            "title": f"trial {pmid}", "level_key": tier}


def evidence(srs=(), primaries=(), primary_tier="level3a"):
    ev = {}
    for p in srs:
        ev.setdefault(p["level_key"], {"scored": []})["scored"].append(p)
    if primaries:
        ev[primary_tier] = {"scored": list(primaries)}
    return ev


@pytest.fixture(autouse=True)
def _clean_cache():
    e._reset_sr_refs_cache()
    yield
    e._reset_sr_refs_cache()


class TestA38cTheReviewIsChosenByRelevance:
    """The old rule picked the newest year in the tier. It disagreed with the
    most relevant review on 26 of 29 eval questions, nominating "Root anatomy
    and canal configuration" for dens invaginatus and "Impact of iRoot SP on
    Periodontal Clinical Parameters" for sonic-versus-ultrasonic."""

    def test_relevance_beats_a_newer_but_less_relevant_review(self):
        ev = evidence(srs=[sr("NEWER", 2026, sim=0.55, tier="cochrane"),
                           sr("RELEVANT", 2023, sim=0.81)],
                      primaries=[primary("P", 2015)])
        e.flag_superseded_by_review(ev, verify=False)
        assert ev["_prisma"]["sr_pmid"] == "RELEVANT"
        assert ev["_prisma"]["chosen_by"] == "relevance"

    def test_the_year_rule_survives_where_there_is_no_similarity(self):
        """The live path carries no similarity — each tier ran its own PubMed
        query, so there is nothing comparable between tiers."""
        ev = evidence(srs=[sr("OLD", 2019), sr("NEW", 2025)],
                      primaries=[primary("P", 2015)])
        e.flag_superseded_by_review(ev, verify=False)
        assert ev["_prisma"]["sr_pmid"] == "NEW"
        assert "year" in ev["_prisma"]["chosen_by"]

    def test_the_cutoff_follows_the_chosen_review_not_the_newest(self):
        ev = evidence(srs=[sr("NEWER", 2026, sim=0.55), sr("RELEVANT", 2020, sim=0.81)],
                      primaries=[primary("P", 2015)])
        e.flag_superseded_by_review(ev, verify=False)
        assert ev["_prisma"]["sr_year"] == 2020
        # 2015 <= 2020 - 2, so it is in the window even under the older review
        assert ev["_prisma"]["in_window"] == 1

    def test_no_review_at_all_leaves_the_evidence_untouched(self):
        ev = evidence(primaries=[primary("P", 2015)])
        e.flag_superseded_by_review(ev, verify=False)
        assert "_prisma" not in ev


class TestA38aOnlyVerifiedInclusionIsClaimed:

    def _with_refs(self, monkeypatch, refs):
        monkeypatch.setattr(e, "pubmed_reference_pmids",
                            lambda pmid, timeout=10: frozenset(refs))

    def test_a_paper_the_review_cites_is_flagged(self, monkeypatch):
        self._with_refs(monkeypatch, {"CITED"})
        ev = evidence(srs=[sr("SR", 2024, sim=0.8)],
                      primaries=[primary("CITED", 2015), primary("OTHER", 2015)])
        e.flag_superseded_by_review(ev)
        flags = {p["pmid"]: p["superseded_by_review"] for p in ev["level3a"]["scored"]}
        assert flags == {"CITED": True, "OTHER": False}

    def test_a_paper_the_review_does_not_cite_is_not_flagged(self, monkeypatch):
        """Absence from the list is SILENCE, not a negative finding: PubMed
        links only references that are themselves indexed and deposited, so a
        present list is a subset. It can confirm; it can never refute."""
        self._with_refs(monkeypatch, {"SOMETHING-ELSE"})
        ev = evidence(srs=[sr("SR", 2024, sim=0.8)], primaries=[primary("P", 2015)])
        e.flag_superseded_by_review(ev)
        assert ev["level3a"]["scored"][0]["superseded_by_review"] is False
        assert ev["_prisma"]["in_window"] == 1 and ev["_prisma"]["verified"] == 0

    def test_no_reference_list_means_nothing_is_claimed(self, monkeypatch):
        """24% of nominated reviews have a reference list at all."""
        self._with_refs(monkeypatch, set())
        ev = evidence(srs=[sr("SR", 2024, sim=0.8)],
                      primaries=[primary("A", 2015), primary("B", 2010)])
        e.flag_superseded_by_review(ev)
        assert not any(p["superseded_by_review"] for p in ev["level3a"]["scored"])

    def test_a_lookup_that_raises_does_not_take_the_answer_with_it(self, monkeypatch):
        """A network hiccup must never become an assertion about the
        literature — nor an exception on the answer path."""
        def boom(pmid, timeout=10):
            raise RuntimeError("NCBI down")
        monkeypatch.setattr(e, "pubmed_reference_pmids", boom)
        ev = evidence(srs=[sr("SR", 2024, sim=0.8)], primaries=[primary("P", 2015)])
        e.flag_superseded_by_review(ev)          # must not raise
        assert ev["level3a"]["scored"][0]["superseded_by_review"] is False
        assert ev["_prisma"]["refs_known"] == 0

    def test_the_real_fetcher_swallows_a_transport_error(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("NCBI down")
        monkeypatch.setattr(e, "ncbi_get", boom)
        assert e.pubmed_reference_pmids("123") == frozenset()

    def test_verify_false_claims_nothing(self):
        ev = evidence(srs=[sr("SR", 2024, sim=0.8)], primaries=[primary("P", 2015)])
        e.flag_superseded_by_review(ev, verify=False)
        assert ev["level3a"]["scored"][0]["superseded_by_review"] is False

    def test_a_paper_outside_the_year_window_is_not_flagged_even_if_cited(self, monkeypatch):
        """One variable at a time: the candidate window is unchanged, only
        what is CLAIMED about the candidates changed."""
        self._with_refs(monkeypatch, {"RECENT"})
        ev = evidence(srs=[sr("SR", 2024, sim=0.8)], primaries=[primary("RECENT", 2024)])
        e.flag_superseded_by_review(ev)
        assert ev["level3a"]["scored"][0]["superseded_by_review"] is False

    def test_stale_flags_from_an_earlier_call_are_cleared(self, monkeypatch):
        """The differential path calls this once per candidate over a growing
        union, so a paper can be flagged on one pass and must not stay flagged
        on the next when a different review is chosen."""
        self._with_refs(monkeypatch, {"P"})
        ev = evidence(srs=[sr("SR", 2024, sim=0.8)], primaries=[primary("P", 2015)])
        e.flag_superseded_by_review(ev)
        assert ev["level3a"]["scored"][0]["superseded_by_review"] is True
        self._with_refs(monkeypatch, set())
        e.flag_superseded_by_review(ev)
        p = ev["level3a"]["scored"][0]
        assert p["superseded_by_review"] is False
        assert "superseding_sr_pmid" not in p


class TestTheNoticeStopsAssertingInclusion:

    def _context(self, ev):
        ev["_summary"] = {"all_scored": [p for b in ev.values()
                                         if isinstance(b, dict) and b.get("scored")
                                         for p in b["scored"]]}
        return e._build_evidence_context(ev)

    def test_the_old_false_claim_is_gone(self, monkeypatch):
        monkeypatch.setattr(e, "pubmed_reference_pmids",
                            lambda pmid, timeout=10: frozenset())
        ev = evidence(srs=[sr("SR", 2024, sim=0.8)],
                      primaries=[primary("A", 2015), primary("B", 2010)])
        e.flag_superseded_by_review(ev)
        text = self._context(ev)
        assert "already synthesised" not in text
        assert "likely already" not in text

    def test_the_unverified_notice_names_no_paper_and_says_so(self, monkeypatch):
        monkeypatch.setattr(e, "pubmed_reference_pmids",
                            lambda pmid, timeout=10: frozenset())
        ev = evidence(srs=[sr("SR", 2024, sim=0.8)],
                      primaries=[primary("AAAA1111", 2015)])
        e.flag_superseded_by_review(ev)
        text = self._context(ev)
        assert "PRISMA DEDUP" in text
        assert "AAAA1111" not in text.split("PRISMA DEDUP")[1]
        assert "is NOT known" in text

    def test_the_verified_notice_says_cites_not_synthesised(self, monkeypatch):
        monkeypatch.setattr(e, "pubmed_reference_pmids",
                            lambda pmid, timeout=10: frozenset({"AAAA1111"}))
        ev = evidence(srs=[sr("SR", 2024, sim=0.8)],
                      primaries=[primary("AAAA1111", 2015)])
        e.flag_superseded_by_review(ev)
        text = self._context(ev)
        assert "CITES" in text
        assert "AAAA1111" in text.split("PRISMA DEDUP")[1]
        assert "already synthesised" not in text

    def test_no_notice_at_all_without_a_review(self):
        ev = evidence(primaries=[primary("P", 2015)])
        assert "PRISMA DEDUP" not in self._context(ev)


class TestTheReferenceLookup:
    """A38a's machinery. RB's instruction was to build it once — A26's backward
    citation chasing needs the same call."""

    def test_an_empty_pmid_makes_no_request(self, monkeypatch):
        """Counted, not raised: the fetcher swallows every exception by design,
        so an AssertionError here would be caught and the test would pass
        while the request had in fact been made."""
        calls = []
        monkeypatch.setattr(e, "ncbi_get",
                            lambda *a, **k: calls.append(1) or (_ for _ in ()).throw(
                                RuntimeError("no")))
        assert e.pubmed_reference_pmids("") == frozenset()
        assert e.pubmed_reference_pmids("   ") == frozenset()
        assert calls == [], "an empty PMID must not reach NCBI"

    def test_the_result_is_cached(self, monkeypatch):
        calls = []

        class R:
            @staticmethod
            def json():
                return {"linksets": [{"linksetdbs": [{"links": ["1", "2"]}]}]}

        def fake(*a, **k):
            calls.append(1)
            return R()
        monkeypatch.setattr(e, "ncbi_get", fake)
        assert e.pubmed_reference_pmids("99") == frozenset({"1", "2"})
        assert e.pubmed_reference_pmids("99") == frozenset({"1", "2"})
        assert len(calls) == 1, "second lookup should come from the cache"

    def test_the_cache_is_bounded(self, monkeypatch):
        class R:
            @staticmethod
            def json():
                return {"linksets": [{"linksetdbs": [{"links": ["1"]}]}]}
        monkeypatch.setattr(e, "ncbi_get", lambda *a, **k: R())
        for i in range(e._SR_REFS_MAX + 5):
            e.pubmed_reference_pmids(str(i))
        assert len(e._sr_refs_cache) <= e._SR_REFS_MAX

    def test_a_malformed_response_is_not_an_assertion(self, monkeypatch):
        class R:
            @staticmethod
            def json():
                return {"nonsense": True}
        monkeypatch.setattr(e, "ncbi_get", lambda *a, **k: R())
        assert e.pubmed_reference_pmids("77") == frozenset()


class TestTheMeasurementIsRecordedBesideTheCode:
    """Rule 21 and rule 24: the premise this overturned, and the number that
    overturned it, stay next to the thing they justify."""

    def test_the_two_percent_is_written_where_the_fix_is(self):
        src = (Path(__file__).parent.parent / "endo_ai.py").read_text(encoding="utf-8")
        assert "10 of 482" in src
        assert "1,294 of 3,301" in src
        assert "26 of" in src and "29 questions" in src


class TestItem2TheTwoPathsNominateByTheSameRule:
    """One rule, not two rules chosen by which retrieval path happened to run.

    MEASURED 2026-09-05 (`scripts/measure_prisma_nomination.py`, report
    `eval/reports/prisma_nomination.md`). Over one candidate pool per question
    — so the RULE is the only variable — relevance and year nominate a
    different review on **27 of 29** questions. A blind panel of three Haiku
    votes, with the A/B slot order flipped between votes so position bias shows
    up as a split rather than a verdict, judged the titles against the question
    and preferred the RELEVANCE pick on **23 of 27**, year on 4.

    So the asymmetry is resolved by giving the live path the missing signal,
    never by demoting the library path to the weaker rule.
    """

    def test_the_live_shape_nominates_by_relevance_once_a_question_is_passed(
            self, monkeypatch):
        """The shape that used to fall through to year: no similarity anywhere."""
        monkeypatch.setattr("rag.embed", _fake_embed)
        ev = evidence(srs=[sr("NEWER_OFFTOPIC", 2026), sr("OLDER_ONTOPIC", 2019)],
                      primaries=[primary("P", 2010)])
        ev["level1"]["scored"][0]["title"] = "something else entirely"
        ev["level1"]["scored"][1]["title"] = "sodium hypochlorite irrigation"
        e.flag_superseded_by_review(
            ev, verify=False, question="sodium hypochlorite irrigation")
        assert ev["_prisma"]["sr_pmid"] == "OLDER_ONTOPIC"
        assert ev["_prisma"]["chosen_by"].startswith("relevance")

    def test_without_a_question_it_still_degrades_to_year_and_says_so(self):
        """Rule 32 — the fallback is a DEGRADATION now, and it is labelled.
        A caller that forgets the question gets the old behaviour, not a crash,
        and the log says which of the two it is looking at."""
        ev = evidence(srs=[sr("OLD", 2019), sr("NEW", 2025)],
                      primaries=[primary("P", 2015)])
        e.flag_superseded_by_review(ev, verify=False)
        assert ev["_prisma"]["sr_pmid"] == "NEW"
        assert ev["_prisma"]["chosen_by"].startswith("year")
        assert "DEGRADED" in ev["_prisma"]["chosen_by"]

    def test_a_route_that_already_has_similarity_is_not_re_embedded(
            self, monkeypatch):
        """The library path must not pay for an embedding it already has, and
        must not have its stored cosine overwritten by a recomputed one."""
        calls = []
        monkeypatch.setattr("rag.embed",
                            lambda t: calls.append(t) or _fake_embed(t))
        ev = evidence(srs=[sr("A", 2026, sim=0.55), sr("B", 2020, sim=0.81)],
                      primaries=[primary("P", 2010)])
        e.flag_superseded_by_review(ev, verify=False, question="anything")
        assert ev["_prisma"]["sr_pmid"] == "B"
        assert calls == [], "library rows already carry a similarity"

    def test_an_embedding_failure_falls_back_rather_than_raising(self, monkeypatch):
        def boom(_t):
            raise RuntimeError("model unavailable")
        monkeypatch.setattr("rag.embed", boom)
        ev = evidence(srs=[sr("OLD", 2019), sr("NEW", 2025)],
                      primaries=[primary("P", 2015)])
        e.flag_superseded_by_review(ev, verify=False, question="anything")
        assert ev["_prisma"]["sr_pmid"] == "NEW"
        assert "DEGRADED" in ev["_prisma"]["chosen_by"]

    def test_every_production_call_site_passes_a_question(self):
        """THE PARITY ASSERTION, and the reason this class exists.

        The defect was never that either rule was wrong in isolation — it was
        that one function served two paths and the paths disagreed, with
        nothing asserting they agreed. A test of each branch would have passed
        throughout. This asserts the AGREEMENT: every production call site
        supplies the question, so no path can quietly fall back to year again.
        """
        import re
        # `(?<!def )` — the definition line is not a call site. Standing rule
        # 33: a source-grep test that matches its own target's declaration
        # reports a defect that is not there, which is how a day was lost once.
        pat = re.compile(r"(?<!def )flag_superseded_by_review\(([^)]*)\)")
        seen = 0
        for name in ("app.py", "endo_ai.py"):
            src = (Path(__file__).parent.parent / name).read_text(encoding="utf-8")
            for m in pat.finditer(src):
                call = m.group(1)
                if not call.startswith(("evidence", "ev")):
                    continue
                seen += 1
                assert "question=" in call, (
                    f"{name}: flag_superseded_by_review({call}) does not pass "
                    f"a question — that call site nominates by YEAR while "
                    f"every other one nominates by RELEVANCE")
        # Rule 4 — this assertion goes vacuous the moment the regex stops
        # matching anything, and a vacuous parity test is worse than none.
        assert seen == 4, f"expected 4 production call sites, matched {seen}"

    def test_the_measurement_is_recorded_beside_the_code(self):
        """Rule 21/24 — the number that decided this lives next to the code."""
        src = (Path(__file__).parent.parent / "endo_ai.py").read_text(encoding="utf-8")
        assert "23 of 27" in src


def _fake_embed(text):
    """A deterministic stand-in for the sentence-transformer.

    Bag-of-words over a fixed vocabulary, L2-normalised, so the dot product is
    a real cosine and a title sharing words with the question scores higher.
    The production function is `rag.embed`; what is being tested here is the
    NOMINATION, not the embedding, and loading a 90 MB model into a unit test
    would test neither.
    """
    import math
    vocab = ["sodium", "hypochlorite", "irrigation", "something", "else",
             "entirely", "review", "anything"]
    words = text.lower().split()
    v = [float(words.count(w)) for w in vocab]
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class TestItem2TheLivePathCarriesThePaperItself:
    """Why the live path could not nominate by relevance, and the fix.

    `rag_results_to_scored` (library) carries `title` and `abstract` on every
    scored paper. `fetch_papers` (live and curriculum) did not: a live-path
    paper dict knew its authors, journal, year, citations, sample size and
    score, and not what the paper was called. The title reached Claude only
    through the separate `annotated_text` block, so nothing reading the DICT
    could see it — which is why `_candidate_similarities` found 13 of 13
    candidates with no text to embed and the nomination silently degraded to
    the year rule.

    This is a WIRING assertion, not a helper test. `_candidate_similarities`
    was correct and fully tested while the caller handed it papers it could not
    use — the same shape as the bug the whole PRISMA file is about.
    """

    def test_fetch_papers_puts_title_and_abstract_on_the_scored_dict(self):
        """Read from the source, because building a live fetch in a unit test
        would need PubMed. The append site is unique in the file."""
        src = (Path(__file__).parent.parent / "endo_ai.py").read_text(encoding="utf-8")
        block = src.split("scored_papers.append({")[1].split("})")[0]
        assert '"title":' in block, (
            "fetch_papers' scored dict has no title — the live path's PRISMA "
            "nomination will silently degrade to the year rule")
        assert '"abstract":' in block, (
            "fetch_papers' scored dict has no abstract — the similarity would "
            "be computed over a different text than the library indexed")

    def test_the_similarity_is_computed_over_title_AND_abstract(self, monkeypatch):
        """The library indexed `title\nabstract` (rag.py, the ingest path). A
        live-side similarity over the title alone would be a second notion of
        similarity sharing a name with the first — which is the divergence this
        item exists to remove, reintroduced one layer down.

        Behavioural, not a source match: it asserts what reaches `embed`.
        """
        seen = []

        def spy(text):
            seen.append(text)
            return _fake_embed(text)

        monkeypatch.setattr("rag.embed", spy)
        cands = [({"title": "sodium hypochlorite",
                   "abstract": "irrigation something"}, 2020, 0.0)]
        e._candidate_similarities("sodium hypochlorite irrigation", cands)
        assert seen[0] == "sodium hypochlorite irrigation", "question embedded first"
        assert "sodium hypochlorite" in seen[1] and "irrigation something" in seen[1], (
            "the candidate must be embedded over title AND abstract, the same "
            "text the library was indexed with")

    def test_the_abstract_still_cannot_reach_the_browser(self):
        """Adding the abstract to the dict is only safe because `_safe_papers`
        whitelists. Rule 30 — enumerate what reads a shape you changed."""
        import app
        out = app._safe_papers([{"pmid": "1", "title": "t", "abstract": "SECRET",
                                 "score": 50.0}])
        assert out == [{"pmid": "1", "title": "t", "score": 50.0}]
        assert "abstract" not in out[0]
