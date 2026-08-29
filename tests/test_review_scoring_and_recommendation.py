"""
Two correctness fixes that the scorer and the validator were getting wrong.

1. Systematic reviews were scored on their COUNT OF INCLUDED STUDIES.
   extract_sample_size() pulled any "n=" from the abstract, so a meta-analysis
   of 1,300 patients that reported "n=12 trials" was scored like a 12-person
   pilot — on a term worth 17% of the total, applied to the highest-tier
   evidence in the library.

2. The Clinical Recommendation was exempt from validation. It is the 2-4
   sentences a clinician acts on; citations were forbidden there by prompt and
   the unattributed-claim detector skipped the section, so the most
   consequential text in the answer was the only unverified part.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from endo_ai import (extract_sample_size, score_paper, is_review_design,
                     validate_evidence_mapping, _check_recommendation,
                     _build_corrective_message)


class TestReviewSampleSize:

    @pytest.mark.parametrize("text", [
        "A systematic review. We included 12 studies identified by database search.",
        "Meta-analysis. n=12 trials met the inclusion criteria.",
        "This systematic review analysed 28 randomized controlled trials.",
        "A meta-analysis of 15 RCTs was conducted following PRISMA.",
    ])
    def test_study_counts_are_not_read_as_sample_size(self, text):
        assert extract_sample_size(text, "cochrane") is None, \
            "count of included studies must not be reported as a participant count"

    def test_participant_count_is_used_when_stated(self):
        n = extract_sample_size(
            "A meta-analysis of 12 randomized trials involving 1340 patients.", "cochrane")
        assert n == 1340

    def test_primary_study_sample_size_still_works(self):
        assert extract_sample_size(
            "A randomized trial. 150 patients were enrolled and followed 24 months.",
            "level1") == 150
        assert extract_sample_size("Randomized trial (n=85) comparing sealers.",
                                   "level1") == 85

    def test_review_with_unknown_n_is_exempt_not_penalised(self):
        """Exempting mirrors how classics are exempt from recency: a synthesis
        pooling several trials is presumptively better powered than any one of
        them, so the 'unknown' penalty is exactly backwards here."""
        exempt, _  = score_paper("cochrane", 2022, 40, None, 24, 11.0, is_review=True)
        penalised, _ = score_paper("cochrane", 2022, 40, None, 24, 11.0, is_review=False)
        assert exempt > penalised

    def test_review_beats_being_scored_as_a_12_person_study(self):
        """The concrete regression: the old path scored this Cochrane review as
        if it had 12 participants."""
        correct, _ = score_paper("cochrane", 2022, 40, None, 24, 11.0, is_review=True)
        old_bug, _ = score_paper("cochrane", 2022, 40, 12, 24, 11.0, is_review=False)
        assert correct > old_bug


class TestIsReviewDesign:

    def test_cochrane_is_always_a_review(self):
        assert is_review_design("cochrane", "") is True

    def test_level1_review_detected_from_text(self):
        assert is_review_design("level1", "This systematic review of 20 trials...") is True
        assert is_review_design("level1", "A meta-analysis was performed.") is True

    def test_level1_rct_is_not_a_review(self):
        assert is_review_design(
            "level1", "A randomized controlled trial of 90 patients.") is False

    def test_primary_designs_are_never_reviews(self):
        for lk in ("level2", "level3a", "level4", "level5"):
            assert is_review_design(lk, "systematic review") is False


class TestClinicalRecommendationIsValidated:

    EV = {"cochrane": {"ids": ["111"]}}

    def _answer(self, rec_body):
        return (f"## CLINICAL RECOMMENDATION\n\n{rec_body}\n\n"
                "## EVIDENCE SUMMARY\n\n"
                "Pooled analysis favours the intervention [[PMID:111]] across "
                "several controlled trials with consistent direction of effect.\n")

    def test_recommendation_without_citation_fails(self):
        r = validate_evidence_mapping(
            self._answer("Use MTA for vital pulp therapy in mature molars."), self.EV)
        assert r["passed"] is False
        assert "UNTRACEABLE_RECOMMENDATION" in r["failure_reason"]

    def test_recommendation_without_evidence_tier_fails(self):
        r = validate_evidence_mapping(
            self._answer("Use MTA for vital pulp therapy [[PMID:111]]."), self.EV)
        assert r["passed"] is False
        assert "strength of evidence" in r["failure_reason"]

    def test_traceable_recommendation_passes(self):
        r = validate_evidence_mapping(
            self._answer("Based on Level I evidence, use MTA for vital pulp "
                         "therapy in mature molars [[PMID:111]]."), self.EV)
        assert r["recommendation"]["has_citation"] is True
        assert r["recommendation"]["names_tier"] is True
        assert r["recommendation"]["issues"] == []
        assert r["passed"] is True

    def test_cochrane_wording_counts_as_naming_a_tier(self):
        rec = _check_recommendation(
            "## CLINICAL RECOMMENDATION\n\nCochrane-level evidence supports MTA "
            "over calcium hydroxide [[PMID:111]].\n")
        assert rec["names_tier"] is True and rec["issues"] == []

    def test_absent_section_is_not_a_failure(self):
        """Deep-Learning curricula have no recommendation section."""
        rec = _check_recommendation("## Module 1\n\nSome teaching content here.\n")
        assert rec["present"] is False and rec["issues"] == []

    def test_corrective_message_names_the_problem(self):
        msg = _build_corrective_message({
            "recommendation": {"issues": ["CLINICAL RECOMMENDATION has no citation"]}
        })
        assert "CLINICAL RECOMMENDATION NOT TRACEABLE" in msg


class TestCheckStatusIsVisible:
    """A fail-open check that stays silent is indistinguishable from one that
    passed, so every outcome must be stated."""

    def test_verified_status_is_shown(self):
        from endo_ai import _append_support_warnings
        out = _append_support_warnings("ANSWER", {"status": "verified", "checked": 7, "flags": []})
        assert "Citation support: verified" in out
        assert "7" in out

    def test_not_run_status_is_shown(self):
        from endo_ai import _append_support_warnings
        out = _append_support_warnings(
            "ANSWER", {"status": "not_run", "detail": "check unavailable", "flags": []})
        assert "not available" in out
        assert "was not verified" in out

    def test_flags_still_reported(self):
        from endo_ai import _append_support_warnings
        out = _append_support_warnings("ANSWER", {
            "status": "verified", "checked": 5,
            "flags": [{"pmid": "999", "claim": "Success was 92%."}]})
        assert "1 of 5 flagged" in out
        assert "[[PMID:999]]" in out
