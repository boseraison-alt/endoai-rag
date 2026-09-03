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
        """A33h-i changed the UNLABELLED fallback from OR-arity to position.

        Q_ASSEMBLED's three topic groups all offer 3 alternatives, so `min` on
        arity picked whichever came first — the chlorhexidine SUBJECT group.
        Measured against a clinician on four real queries, OR-arity named the
        qualifier 1 time in 4 and trailing order 3 times in 4, so the trailing
        group goes and the subject stays.
        """
        out = _broaden_query(Q_ASSEMBLED)
        assert out, "assembled query should be broadenable"
        assert "healing outcome*" not in out, "trailing topic group should go"
        assert "chlorhexidine" in out, "the subject group must survive"

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


class TestLabelledRelaxation:
    """A33h-i. Relaxation drops the group the generator DECLARED a qualifier.

    Every query below is one of the four real ones the labelling was validated
    on, with the roles the generator actually produced for it.
    """

    # The laser query. The qualifier sits in the MIDDLE and the scenario is
    # LAST, so this is the case where position and labelling disagree — and
    # where position would drop the outcome concept the question is about.
    LASER_TOPIC = ('(laser* OR "photodynamic therapy" OR aPDT OR PIPS OR Er:YAG '
                   'OR Nd:YAG) AND ("root canal" OR endodontic* OR intracanal) '
                   'AND (disinfect* OR antibacterial OR antimicrobial OR biofilm)')
    LASER_ROLES = ["subject", "qualifier", "scenario"]

    def _assembled(self, topic):
        return (f"({topic}) AND (randomized controlled trial[pt]) AND "
                f'(endodontics[MeSH] OR endodontic*[tiab]) '
                f'NOT "Retracted Publication"[pt]')

    def test_the_declared_qualifier_is_the_group_dropped(self):
        out = _broaden_query(self._assembled(self.LASER_TOPIC), self.LASER_ROLES)
        assert "intracanal" not in out, "the declared qualifier should go"

    def test_the_scenario_survives_where_position_would_drop_it(self):
        """The whole reason labelling beat trailing order, 4/4 against 3/4."""
        assembled = self._assembled(self.LASER_TOPIC)
        labelled  = _broaden_query(assembled, self.LASER_ROLES)
        position  = _broaden_query(assembled)
        assert "disinfect*" in labelled, "the scenario must never be dropped"
        assert "disinfect*" not in position, (
            "this test is only meaningful while position and labelling "
            "disagree on this query — if position now keeps the scenario, "
            "re-read A33h before deleting the labelling")

    def test_the_subject_is_never_dropped(self):
        out = _broaden_query(self._assembled(self.LASER_TOPIC), self.LASER_ROLES)
        assert "laser*" in out

    def test_a_labelled_query_with_no_qualifier_is_not_broadened(self):
        """Falling back to position here would drop a subject or a scenario —
        the exact outcome the labelling exists to prevent."""
        out = _broaden_query(self._assembled(self.LASER_TOPIC),
                             ["subject", "scenario", "scenario"])
        assert out == ""

    def test_roles_that_do_not_match_the_groups_are_ignored(self):
        """A stale or truncated labelling must degrade to position, not
        misalign — role[i] naming group[i] is the whole contract."""
        out = _broaden_query(self._assembled(self.LASER_TOPIC),
                             ["subject", "qualifier"])
        assert out and "disinfect*" not in out, "should fall back to position"

    def test_the_design_and_domain_filters_survive_labelled_relaxation(self):
        out = _broaden_query(self._assembled(self.LASER_TOPIC), self.LASER_ROLES)
        assert "[pt]" in out and "[MeSH]" in out
        assert "Retracted Publication" in out

    def test_the_output_is_still_a_valid_query(self):
        from endo_ai import _looks_like_query
        assert _looks_like_query(
            _broaden_query(self._assembled(self.LASER_TOPIC), self.LASER_ROLES))


class TestGroupRoleRegistry:
    """The roles reach `fetch_papers` keyed on the query text, the way rag.py
    keys the write-back tally — see the note above `_group_roles`."""

    def setup_method(self):
        from endo_ai import _reset_group_roles
        _reset_group_roles()

    def test_roles_round_trip_on_the_query_text(self):
        from endo_ai import register_group_roles, lookup_group_roles
        register_group_roles("(a OR b) AND (c OR d)", ["subject", "qualifier"])
        assert lookup_group_roles("(a OR b) AND (c OR d)") == ("subject", "qualifier")

    def test_whitespace_does_not_lose_the_labelling(self):
        from endo_ai import register_group_roles, lookup_group_roles
        register_group_roles("(a OR b)  AND  (c OR d)", ["subject", "qualifier"])
        assert lookup_group_roles("(a OR b) AND (c OR d)") == ("subject", "qualifier")

    def test_an_unlabelled_query_returns_none_not_an_empty_tuple(self):
        """`None` and `()` reach `_broaden_query` differently: None takes the
        position fallback, and a length-0 tuple would be a count mismatch."""
        from endo_ai import lookup_group_roles
        assert lookup_group_roles("(x OR y) AND (z)") is None

    def test_the_registry_is_bounded(self):
        from endo_ai import register_group_roles, _GROUP_ROLES_MAX, _group_roles
        for i in range(_GROUP_ROLES_MAX + 5):
            register_group_roles(f"(q{i} OR b) AND (c)", ["subject", "qualifier"])
        assert len(_group_roles) <= _GROUP_ROLES_MAX


class TestScenarioExpansion:
    """A33g's vocabulary half. Built, switchable, and default OFF — the
    measurement behind that is in the block above `_ROLE_LINE_RE`.

    What is pinned here is the guard, not the default: an expansion that loses
    an alternative it started with is a narrowing wearing a widening's clothes,
    and it is the failure that would be hardest to see afterwards.
    """
    ORIG = '("access restoration" OR "access opening" OR "coronal seal")'

    def test_a_real_widening_is_accepted(self):
        from endo_ai import _accept_expansion
        assert _accept_expansion(self.ORIG, self.ORIG[:-1] +
                                 ' OR "orifice barrier")')

    def test_an_expansion_that_drops_an_alternative_is_rejected(self):
        from endo_ai import _accept_expansion
        assert not _accept_expansion(
            self.ORIG, '("access restoration" OR "access opening" OR "orifice barrier")')

    def test_an_unbalanced_expansion_is_rejected(self):
        from endo_ai import _accept_expansion
        assert not _accept_expansion(self.ORIG, self.ORIG[:-1] + ' OR "x"')

    def test_an_odd_number_of_quotes_is_rejected(self):
        from endo_ai import _accept_expansion
        assert not _accept_expansion(self.ORIG, self.ORIG[:-1] + ' OR "unclosed)')

    def test_a_restatement_of_the_same_group_is_not_a_widening(self):
        from endo_ai import _accept_expansion
        assert not _accept_expansion(self.ORIG, self.ORIG)

    def test_alternatives_are_split_on_or_only(self):
        from endo_ai import _or_alternatives
        assert _or_alternatives(self.ORIG) == [
            '"access restoration"', '"access opening"', '"coronal seal"']

    def test_the_default_is_off_and_says_why(self):
        """Rule 21: this is a hypothesis that measurement did not support.
        If it is turned on, the numbers beside it have to be re-measured."""
        import endo_ai
        from pathlib import Path as _P
        assert endo_ai.EXPAND_SCENARIO is False
        src = (_P(endo_ai.__file__)).read_text(encoding="utf-8")
        assert "orifice barrier" in src, (
            "the measurement that set this default must stay beside it")


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
