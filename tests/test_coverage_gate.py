"""
The coverage gate — does the retrieved set address the QUESTION? (addendum A1)

WHAT THE MEASUREMENT FOUND. For "eliquis in patients who needs apicectomy" the
library-first gate passed all four of its conditions — 200 hits, 14 above the
similarity floor against a minimum of 12, 11 high-tier, newest 2026 — and live
PubMed was never attempted. Zero esearch rows for the whole run.

**None of the retrieved papers mentions anticoagulation.**

Every one of those four conditions is a question about the CORPUS: is the
library big enough, similar enough, strong enough, fresh enough. All four are
satisfiable by the endodontic HALF of a two-part question, so a question with
one foot outside the library scores as well covered as one entirely inside it.

THE CONDITION THIS FILE PINS. `generate_search_terms` emits a PubMed boolean
whose top-level AND-groups are the question's concepts:

    (Eliquis OR apixaban)                                    <- the drug
    AND (apicectomy OR apicoectomy OR "periapical surgery")  <- the procedure
    AND (anticoagul* OR "bleeding risk" OR hemorrhage)       <- the setting

Each group is a hard requirement in the query the system would otherwise have
sent to PubMed. Requiring each to be REPRESENTED in the candidate set is not a
new judgement about the question — it is the query's own structure, applied to
what came back.

Measured on the real candidate pools:

    apixaban      drug concept        0 of 200 candidates
                  procedure          18
                  setting             1
    retreatment   retreatment        22 of 200
                  single/two visit   22

which is why the apixaban question must route live and the retreatment question
must not — the retreatment answer's defect is elsewhere (a per-tier cap
discarded the on-point RCT; see `eval/reports/a5a_missed_rcts.md`).
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai
from endo_ai import coverage_groups, parse_search_term_groups, question_coverage

ROOT = Path(__file__).parent.parent

# The primary terms `generate_search_terms` actually produced for these two
# questions, copied verbatim from the runs.
APIXABAN_TERM = ('(Eliquis OR apixaban) AND (apicectomy OR apicoectomy OR '
                 '"periapical surgery" OR "endodontic surgery") AND '
                 '(anticoagul* OR "bleeding risk" OR hemorrhage OR coagulation)')
RETREATMENT_TERM = ('("retreatment" OR "re-treatment" OR "non-surgical retreatment") '
                    'AND ("single visit" OR "one visit" OR "two visit*" OR '
                    '"multiple visit*" OR "appointment*") AND '
                    '("root canal" OR endodontic*)')
LASER_TERM = ('(laser* OR "photodynamic therapy" OR aPDT OR PIPS OR SWEEPS OR '
              'Er:YAG OR Nd:YAG OR diode) AND ("root canal" OR endodontic*) AND '
              '(disinfect* OR antibacterial OR biofilm)')


# ── the query's own structure ─────────────────────────────

class TestConceptsComeFromTheQuery:

    def test_and_groups_are_the_concepts(self):
        groups = parse_search_term_groups(APIXABAN_TERM)
        assert len(groups) == 3
        assert "apixaban" in groups[0]
        assert "apicectomy" in groups[1]
        assert "anticoagul*" in groups[2]

    def test_quotes_and_field_tags_are_stripped(self):
        g = parse_search_term_groups('("periapical surgery"[tiab] OR endodontic*)')
        assert g == [["periapical surgery", "endodontic*"]]

    def test_a_group_of_pure_endodontic_vocabulary_is_dropped(self):
        """`("root canal" OR endodontic*)` is satisfied by every paper in an
        endodontic library. Testing it would rebuild the tautology the old gate
        was made of."""
        assert ["root canal", "endodontic*"] in parse_search_term_groups(RETREATMENT_TERM)
        assert ["root canal", "endodontic*"] not in coverage_groups(RETREATMENT_TERM)

    def test_the_discriminating_concepts_survive(self):
        got = coverage_groups(RETREATMENT_TERM)
        assert len(got) == 2
        assert "retreatment" in got[0]
        assert "single visit" in got[1]

    def test_a_question_wholly_inside_the_library_still_has_concepts(self):
        """The laser question is endodontic through and through, but 'laser' is
        not corpus-wide vocabulary — so the condition still has something to
        test and does not abstain on ordinary questions."""
        got = coverage_groups(LASER_TERM)
        assert any("laser*" in g for g in got)
        assert any("disinfect*" in g for g in got)


# ── matching a concept against candidate text ─────────────

class TestConceptMatching:

    PAPERS = [
        {"pmid": "1", "title": "Outcome of single- versus two-visit root canal "
                               "retreatment in teeth with apical periodontitis"},
        {"pmid": "2", "title": "Apicoectomy versus apical curettage with L-PRF"},
        {"pmid": "3", "title": "Anticoagulants and dental extraction: a review",
         "abstract": "Patients on anticoagulant therapy undergoing extraction."},
        {"pmid": "4", "title": "Rotary versus reciprocating instrumentation"},
    ]

    def test_a_wildcard_matches_its_inflections(self):
        cov = question_coverage([["anticoagul*"]], self.PAPERS)
        assert cov[0]["hits"] == 1

    def test_the_abstract_counts_as_well_as_the_title(self):
        cov = question_coverage([["anticoagulant therapy"]], self.PAPERS)
        assert cov[0]["hits"] == 1

    def test_a_concept_absent_from_every_candidate_scores_zero(self):
        assert question_coverage([["apixaban", "eliquis"]], self.PAPERS)[0]["hits"] == 0

    def test_a_paper_matching_any_synonym_counts_once(self):
        cov = question_coverage([["single visit", "two visit", "retreatment"]],
                                self.PAPERS)
        assert cov[0]["hits"] == 1

    def test_a_substring_inside_a_word_does_not_match(self):
        """`ilium` must not match `auxilium`. Without the boundary the count
        drifts upward and the condition quietly stops firing."""
        papers = [{"pmid": "9", "title": "Auxilium and the maxillary sinus"}]
        assert question_coverage([["ilium"]], papers)[0]["hits"] == 0

    def test_a_candidate_with_no_text_is_not_evidence_of_coverage(self):
        assert question_coverage([["apixaban"]], [{"pmid": "x"}])[0]["hits"] == 0


# ── the gate decision, on the real measured pools ─────────

# Coverage measured against the REAL candidate pools returned by
# `multi_query_search` for each question (200 candidates each). Recorded here
# so the decision logic is testable without a database.
MEASURED = {
    "apixaban": [{"terms": ["eliquis", "apixaban"], "hits": 0},
                 {"terms": ["apicectomy", "apicoectomy"], "hits": 18},
                 {"terms": ["anticoagul*", "bleeding risk"], "hits": 1}],
    "retreatment": [{"terms": ["retreatment", "re-treatment"], "hits": 22},
                    {"terms": ["single visit", "one visit"], "hits": 22}],
}


def gate_covers(coverage, minimum):
    """The decision `build_evidence_base_with_progress` makes, in isolation."""
    weakest = min([c["hits"] for c in coverage], default=None)
    return (weakest is None) or (weakest >= minimum)


class TestTheGateDecision:

    @pytest.mark.parametrize("minimum", [1, 2, 3, 5, 8, 12])
    def test_the_apixaban_question_fails_coverage_at_every_threshold(self, minimum):
        """Its drug concept has ZERO representation in 200 candidates, so this
        does not depend on where the threshold is set."""
        assert not gate_covers(MEASURED["apixaban"], minimum)

    @pytest.mark.parametrize("minimum", [1, 2, 3, 5, 8, 12])
    def test_the_retreatment_question_still_short_circuits(self, minimum):
        """A1d's other direction. Both of its concepts are represented 22 times.

        This is also the honest prediction recorded in
        `eval/reports/a5a_missed_rcts.md`: A1 alone does NOT fix the
        retreatment question, because its defect is a per-tier cap discarding
        the on-point RCT after retrieval, not the routing decision."""
        assert gate_covers(MEASURED["retreatment"], minimum)

    def test_a_query_with_no_discriminating_concept_abstains(self):
        """A plain endodontic question has no concept outside the corpus. The
        condition must not block those — it has nothing to say about them."""
        assert coverage_groups('("root canal" OR endodontic*)') == []
        assert gate_covers([], 3) is True

    def test_a_degraded_query_abstains_rather_than_routing_everything_live(self):
        """When term generation fails, `generate_search_terms` falls back to the
        RAW QUESTION. That parses as one group holding one 60-character string
        no title contains, so coverage scored 0 and the condition sent every
        degraded run to live PubMed.

        Found by `tests/test_end_to_end.py`, which drives the real path with a
        stubbed Claude and hit the fallback — ten tests went red. It is exactly
        the failure mode A1c bounds, and it would have been paid in latency on
        every run whose term generation slipped."""
        for fallback in ("Single visit versus multiple visit endodontic treatment?",
                         # A SHORT fallback matters separately: the long one is
                         # also caught by the prose-clause filter, so it cannot
                         # prove the >=2-groups rule on its own. A mutation that
                         # removed that rule survived until this case existed.
                         "Apixaban and apicectomy",
                         "dens evaginatus"):
            assert coverage_groups(fallback) == [], fallback
            assert gate_covers(question_coverage(coverage_groups(fallback), []), 3)

    def test_a_prose_clause_is_not_treated_as_a_matchable_term(self):
        """No title contains a whole clause. Left in, it drags its group's count
        to zero and fails a question that is perfectly well covered."""
        term = ('(retreatment OR "a comparison of single visit and multiple '
                'visit protocols in molars") AND (apixaban)')
        groups = coverage_groups(term)
        assert groups[0] == ["retreatment"]

    def test_the_configured_threshold_is_the_one_that_ships(self):
        import app as app_mod
        assert app_mod.RELEVANCE_GATE["min_concept_papers"] >= 1
        assert not gate_covers(MEASURED["apixaban"],
                               app_mod.RELEVANCE_GATE["min_concept_papers"])
        assert gate_covers(MEASURED["retreatment"],
                           app_mod.RELEVANCE_GATE["min_concept_papers"])


class TestTheConditionIsActuallyWiredIntoTheGate:
    """A4's lesson, applied to this item before it can bite.

    Everything above tests the coverage FUNCTIONS and a local restatement of the
    decision. A mutation that deleted `covers_concepts` from the real gate
    expression in `app.py` passed all of it — the tests were asserting on the
    right logic in the wrong place, which is precisely the defect A4 warned
    about ("a tests-assert-on-the-wrong-surface defect, not a missed edge
    case").

    This reads the actual conjunction the router evaluates.
    """

    def _gate_expression(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        i = src.index("library_covers_question = (")
        j = src.index("if force_route", i)
        return src[i:j]

    def test_the_coverage_condition_is_a_conjunct_of_the_routing_decision(self):
        expr = self._gate_expression()
        assert "covers_concepts" in expr, (
            "the gate no longer consults the coverage condition:\n%s" % expr)
        assert "and covers_concepts" in expr.replace("\n", " ").replace("  ", " "), \
            "coverage is mentioned but not ANDed into the decision"

    def test_the_other_four_conditions_are_still_there(self):
        """Standing rule 6 in test form: adding a condition must not quietly
        remove one."""
        expr = self._gate_expression()
        for cond in ("MIN_RAG_RESULTS", "MIN_RAG_RELEVANT", "has_high_tier",
                     "topic_is_stale"):
            assert cond in expr, "the gate lost its %s condition" % cond

    def test_the_condition_is_computed_from_the_primary_generated_term(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        i = src.index("_cov_groups = ")
        line = src[i:src.index("\n", i)]
        assert "smart_topic" in line, (
            "coverage must be read off the primary generated query: %s" % line)


class TestTheGateSaysWhatItDecided:
    """A1b / standing rule §1.5. A gate that short-circuits live retrieval
    discards the entire live candidate pool; doing that silently is the defect
    class this whole batch keeps finding."""

    def test_every_condition_reports_its_own_verdict(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        block = src[src.index("[rag_gate] hits="):src.index("-> {'LIBRARY'")]
        for condition in ("hits=", "relevant=", "high_tier=", "newest=", "concepts>="):
            assert condition in block, "the gate log does not report %s" % condition
        assert "_v(" in block, "the log states values without a pass/fail verdict"

    def test_the_coverage_terms_and_counts_are_logged(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        assert "[rag_gate:coverage]" in src
        assert "NOT COVERED" in src

    def test_an_abstaining_condition_says_so(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        assert "condition abstains" in src
