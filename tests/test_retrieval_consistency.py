"""
Retrieval consistency (WORKLIST Phase A) — the Cochrane miss.

The synthesis subset found that an answer to "single-visit versus
multiple-visit root canal treatment" neither cited nor mentioned Cochrane
CD005296, the definitive review on exactly that question, though it sits in the
library at score 70.4, current version, not superseded.

The cause was not what it looked like. Measured against the real generated
queries pulled from pubmed_audit.jsonl:

    raw clinician question                 0.680  rank 20  kept
    bag-of-words generated query           0.585  rank 19  kept
    3-group query, best spec compliance    0.546  rank 11  CUT by the floor

The review was rank 11 in the whole library for the query that missed it. A
well-formed PubMed boolean is mostly operators, quotes and truncation
asterisks, so it embeds FURTHER from a paper's prose than a sloppy query does —
the better the boolean, the worse the vector search. One string was serving two
purposes that pull in opposite directions.

Every query string below is real, taken from the audit log.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from endo_ai import (cap_and_groups, _broaden_query, _split_and_groups,
                     _or_breadth, MAX_AND_GROUPS, BROADEN_THRESHOLD)

# ── Real queries from pubmed_audit.jsonl ─────────────────────────────────

Q_3GROUP_COMPLIANT = (
    '("single visit" OR "single-visit" OR "one appointment" OR "same-day" OR '
    '"same day" OR "one-day" OR "one day") AND ("multiple visit*" OR '
    '"multi-visit" OR "multiple appointment*" OR "multi-appointment" OR '
    '"conventional treatment") AND ("root canal" OR endodontic* OR '
    '"pulp therapy" OR RCT)')

# pips-vs-ultrasonic, the run that retrieved 3 papers where siblings got 29.
Q_4GROUP_OVERNARROW = (
    '(laser* OR PIPS OR SWEEPS OR "photodynamic therapy" OR aPDT) AND '
    '(irrigat* OR activation) AND ("ultrasonic activation" OR '
    '"ultrasonic agitation" OR UAA OR PUI) AND ("periapical healing" OR '
    '"periapical repair" OR "apical periodontitis" OR "healing outcome*")')

# The drifted multi-term angle that returned 3 hits across 6 uses, as
# fetch_papers assembles it.
Q_ASSEMBLED = (
    '(("chlorhexidine" OR "sodium hypochlorite" OR "irrigation protocol*") AND '
    '("treatment completion" OR "one-visit endodontic*" OR "rapid root canal") '
    'AND ("periradicular lesion*" OR "apical periodontitis" OR '
    '"healing outcome*")) AND (randomized controlled trial[pt]) AND '
    '(endodontics[MeSH] OR endodontic*[tiab]) NOT "Retracted Publication"[pt]')


class TestGroupSplitting:

    def test_splits_on_top_level_and_only(self):
        assert len(_split_and_groups(Q_3GROUP_COMPLIANT)) == 3

    def test_does_not_split_inside_parentheses(self):
        assert len(_split_and_groups('(a AND b OR c) AND (d)')) == 2

    def test_does_not_split_inside_quotes(self):
        """A quoted phrase containing AND is one token, not a separator."""
        assert len(_split_and_groups('("cats AND dogs" OR x) AND (y)')) == 2

    def test_breadth_counts_alternatives(self):
        assert _or_breadth('(a OR b OR c)') == 3
        assert _or_breadth('(a)') == 1


class TestAndGroupCap:
    """A2. Each extra AND is a hard conjunction demanding all concepts co-occur
    in one record."""

    def test_real_four_group_query_is_capped(self):
        out, dropped = cap_and_groups(Q_4GROUP_OVERNARROW)
        assert len(_split_and_groups(out)) == MAX_AND_GROUPS
        assert len(dropped) == 1

    def test_the_narrowest_group_is_the_one_dropped(self):
        """(irrigat* OR activation) offers 2 alternatives; the others offer 4-5."""
        _out, dropped = cap_and_groups(Q_4GROUP_OVERNARROW)
        assert "irrigat*" in dropped[0]

    def test_the_broadest_groups_survive(self):
        out, _ = cap_and_groups(Q_4GROUP_OVERNARROW)
        assert "laser*" in out and "ultrasonic activation" in out

    def test_compliant_three_group_query_is_untouched(self):
        assert cap_and_groups(Q_3GROUP_COMPLIANT) == (Q_3GROUP_COMPLIANT, [])

    def test_output_is_still_a_valid_query(self):
        from endo_ai import _looks_like_query
        out, _ = cap_and_groups(Q_4GROUP_OVERNARROW)
        assert _looks_like_query(out)


class TestAutoBroaden:
    """A3. A tier that comes back nearly empty is usually over-conjoined rather
    than genuinely unstudied."""

    def test_threshold_is_low_enough_to_mean_empty(self):
        assert BROADEN_THRESHOLD <= 5

    def test_broadens_inside_the_topic_group(self):
        out = _broaden_query(Q_ASSEMBLED)
        assert out, "assembled query should be broadenable"
        assert "chlorhexidine" not in out, "narrowest topic group should go"

    def test_never_drops_the_design_filter(self):
        """Dropping a depth-0 group would remove the design or domain filter
        and return most of PubMed."""
        out = _broaden_query(Q_ASSEMBLED)
        assert "[pt]" in out and "[MeSH]" in out

    def test_keeps_the_retraction_exclusion(self):
        assert "Retracted Publication" in _broaden_query(Q_ASSEMBLED)

    def test_single_topic_group_is_not_broadenable(self):
        """Nothing left to drop without gutting the query."""
        assert _broaden_query('(a OR b) AND (review[pt])') == ""

    def test_empty_input(self):
        assert _broaden_query("") == ""


class TestMultiQuerySearch:
    """A4. The direct fix: embed the clinician's question alongside every
    generated term and keep the best similarity per paper."""

    def _fake(self, monkeypatch, mapping):
        import rag
        def _search(q, level_key=None, limit=100):
            return mapping.get(q, [])
        monkeypatch.setattr(rag, "search", _search)

    def test_union_keeps_the_best_similarity_per_pmid(self, monkeypatch):
        from app import multi_query_search
        self._fake(monkeypatch, {
            "the question": [{"pmid": "36512807", "similarity": 0.680}],
            "boolean":      [{"pmid": "36512807", "similarity": 0.546}],
        })
        out = multi_query_search("the question", ["boolean"])
        assert len(out) == 1
        assert out[0]["similarity"] == pytest.approx(0.680), \
            "the raw question's better score must win over the boolean's"

    def test_best_wins_even_when_it_is_seen_last(self, monkeypatch):
        """Order-independence. The question is searched first, so a
        keep-the-first-seen implementation would pass the test above by
        accident — here the best score arrives from the LAST query."""
        from app import multi_query_search
        self._fake(monkeypatch, {
            "q":   [{"pmid": "X", "similarity": 0.50}],
            "t1":  [{"pmid": "X", "similarity": 0.55}],
            "t2":  [{"pmid": "X", "similarity": 0.90}],
        })
        out = multi_query_search("q", ["t1", "t2"])
        assert out[0]["similarity"] == pytest.approx(0.90)

    def test_recall_is_the_union_not_the_intersection(self, monkeypatch):
        from app import multi_query_search
        self._fake(monkeypatch, {
            "q":  [{"pmid": "1", "similarity": 0.7}],
            "t1": [{"pmid": "2", "similarity": 0.6}],
            "t2": [{"pmid": "3", "similarity": 0.6}],
        })
        assert {p["pmid"] for p in multi_query_search("q", ["t1", "t2"])} == {"1", "2", "3"}

    def test_one_failing_query_does_not_lose_the_others(self, monkeypatch):
        import rag
        from app import multi_query_search
        def _search(q, level_key=None, limit=100):
            if q == "bad":
                raise RuntimeError("boom")
            return [{"pmid": "1", "similarity": 0.7}]
        monkeypatch.setattr(rag, "search", _search)
        assert len(multi_query_search("q", ["bad"])) == 1

    def test_duplicate_query_strings_are_searched_once(self, monkeypatch):
        import rag
        from app import multi_query_search
        calls = []
        def _search(q, level_key=None, limit=100):
            calls.append(q)
            return []
        monkeypatch.setattr(rag, "search", _search)
        multi_query_search("q", ["q", "q"])
        assert calls == ["q"]

    def test_results_are_sorted_by_similarity(self, monkeypatch):
        from app import multi_query_search
        self._fake(monkeypatch, {"q": [
            {"pmid": "a", "similarity": 0.5}, {"pmid": "b", "similarity": 0.9}]})
        assert [p["pmid"] for p in multi_query_search("q", [])] == ["b", "a"]


class TestCrossQueryVarianceProtection:
    """A5's real backstop, and A32's replacement for the one that never fired.

    The failure this exists for: a well-formed boolean embeds FURTHER from a
    paper's prose than a sloppy one, so the better the generated query the
    worse the vector search. CD005296 was rank 11 for the query that missed it.

    `ensure_authoritative` was supposed to be the guarantee. It never once
    fired — `usable()` required similarity at or above the floor and the
    `relevant` list already held every such candidate — and its tests passed
    only because they called it with `relevant=[]`, a state production never
    produces. One of them, `test_cochrane_below_the_floor_is_reinstated`, used
    floor=0.50 against similarity 0.546 and so asserted the opposite of its own
    name. A32 deleted it rather than letting it reach below the floor, which
    would be authority overriding relevance.

    What actually protects the paper is the union-of-max below. These tests
    move to it."""

    COCHRANE = {"pmid": "36512807", "level_key": "cochrane",
                "journal": "Cochrane Database Syst Rev", "score": 70.4}

    def _fake_search(self, monkeypatch, by_query):
        import app as app_mod
        import rag

        def fake(q, level_key=None, limit=100, **kw):
            return [dict(r) for r in by_query.get(q, [])]

        monkeypatch.setattr(rag, "search", fake)
        return app_mod.multi_query_search

    def test_one_badly_embedding_query_cannot_lose_the_paper(self):
        """The whole mechanism in one assertion: the raw question finds the
        review at 0.680, the tightest boolean scores it 0.546, and the merge
        keeps 0.680. Under the old behaviour the boolean's number was what
        survived if it came last."""
        import app as app_mod
        import rag
        import pytest as _pytest
        by_query = {
            "single visit versus multiple visit root canal treatment":
                [dict(self.COCHRANE, similarity=0.680)],
            "(single-visit OR one-visit) AND (root canal therapy)":
                [dict(self.COCHRANE, similarity=0.546)],
        }
        orig = rag.search
        try:
            rag.search = lambda q, level_key=None, limit=100, **kw: [
                dict(r) for r in by_query.get(q, [])]
            out = app_mod.multi_query_search(
                "single visit versus multiple visit root canal treatment",
                ["(single-visit OR one-visit) AND (root canal therapy)"])
        finally:
            rag.search = orig
        assert len(out) == 1
        assert out[0]["similarity"] == 0.680, (
            "the merge kept a worse query's similarity for the same paper")

    def test_a_paper_only_one_query_finds_still_arrives(self):
        import app as app_mod
        import rag
        orig = rag.search
        try:
            rag.search = lambda q, level_key=None, limit=100, **kw: (
                [dict(self.COCHRANE, similarity=0.62)] if q == "term-3" else [])
            out = app_mod.multi_query_search("q", ["term-1", "term-2", "term-3"])
        finally:
            rag.search = orig
        assert [p["pmid"] for p in out] == ["36512807"]

    def test_a_failing_query_does_not_lose_the_others_recall(self):
        import app as app_mod
        import rag
        orig = rag.search

        def flaky(q, level_key=None, limit=100, **kw):
            if q == "bad":
                raise RuntimeError("boom")
            return [dict(self.COCHRANE, similarity=0.7)]
        try:
            rag.search = flaky
            out = app_mod.multi_query_search("q", ["bad"])
        finally:
            rag.search = orig
        assert [p["pmid"] for p in out] == ["36512807"]

    def test_the_deleted_guarantee_has_not_come_back(self):
        """A32d. If a later change reintroduces it, this fails and whoever
        does it has to read why it went."""
        import app as app_mod
        assert not hasattr(app_mod, "ensure_authoritative"), (
            "ensure_authoritative is back — see the A32 note in app.py before "
            "reinstating it; it must never reach below the similarity floor")
        src = (Path(__file__).parent.parent / "app.py").read_text(encoding="utf-8")
        assert "A32 — `ensure_authoritative` was deleted here" in src
