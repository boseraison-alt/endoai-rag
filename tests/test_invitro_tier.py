"""
The in vitro / ex vivo tier (WORKLIST 1.4).

Bench studies — extracted teeth, dentine blocks, bovine incisors, agar plates —
were indexed as ordinary journal articles and read as "prospective", so they sat
at Level II and were shown to clinicians as the second-strongest kind of
evidence there is. An in vitro result is real evidence about a mechanism and no
evidence at all about what happens in a patient.

The classifier is deliberately asymmetric: demoting a real clinical trial to a
bench tier is far worse than leaving one bench paper at Level II, so a single
weak hint never suffices and clinical language vetoes everything.

Abstract snippets below are shortened from real library rows flagged by the
migration dry run.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from endo_ai import (detect_in_vitro, LEVEL_SCORES, TIER_ORDER, TIER_LABEL,
                     _DEMOTABLE_TIERS, _demote_one_tier)


class TestTierPlacement:

    def test_ranks_below_case_series_and_above_expert_opinion(self):
        """A bench result outranks an opinion and is outranked by anything
        that happened in a patient, however weakly."""
        assert LEVEL_SCORES["level4"] > LEVEL_SCORES["invitro"] > LEVEL_SCORES["level5"]

    def test_is_in_tier_order_and_ordering_stays_monotonic(self):
        assert "invitro" in TIER_ORDER
        # TIER_ORDER only: this asserts the ladder's scores are monotonic.
        # PROVISIONAL_KEY carries no score, so it has nothing to order.
        scores = [LEVEL_SCORES.get(t, 0) for t in TIER_ORDER]
        assert scores == sorted(scores, reverse=True), \
            f"TIER_ORDER not strongest-first: {list(zip(TIER_ORDER, scores))}"

    def test_sits_between_level4_and_level5_in_the_order(self):
        assert TIER_ORDER.index("level4") < TIER_ORDER.index("invitro") < \
               TIER_ORDER.index("level5")

    def test_has_a_label_that_says_it_is_not_clinical(self):
        """The label is what Claude is told the evidence IS."""
        assert "invitro" in TIER_LABEL
        assert "not clinical" in TIER_LABEL["invitro"].lower()

    def test_is_on_the_demotion_ladder(self):
        """A superseded bench paper must step to level5, not skip a rung."""
        assert "invitro" in _DEMOTABLE_TIERS
        assert _demote_one_tier("level4") == "invitro"
        assert _demote_one_tier("invitro") == "level5"


class TestStrongCues:
    """One strong cue is enough: each names a preparation that cannot be a
    patient."""

    @pytest.mark.parametrize("abstract", [
        "Sixty extracted human teeth were instrumented and divided into groups.",
        "Dentine slices were prepared and the sealer applied.",
        "Bovine incisors were sectioned for the adhesion test.",
        "Canals were prepared in resin blocks and scanned.",
        "An agar diffusion test was performed against E. faecalis.",
        "This ex vivo study evaluated shaping performance.",
        "An in vitro comparison of two irrigation techniques.",
    ])
    def test_detected(self, abstract):
        hit, why = detect_in_vitro("A study", abstract, "level2")
        assert hit, f"missed: {why}"


class TestWeakCuesNeedCorroboration:

    def test_one_weak_cue_is_not_enough(self):
        hit, why = detect_in_vitro(
            "Canal transportation", "Micro-CT was used to assess transportation.", "level2")
        assert not hit and "insufficient" in why

    def test_two_weak_cues_suffice(self):
        hit, _ = detect_in_vitro(
            "Biofilm reduction",
            "A monomicrobial biofilm model with Enterococcus faecalis; CFU were counted.",
            "level2")
        assert hit


class TestClinicalLanguageVetoes:
    """The expensive error. Every case here would be a real clinical study
    demoted to a bench tier."""

    @pytest.mark.parametrize("abstract", [
        "120 patients were randomized. Extracted teeth were also examined in vitro.",
        "Informed consent was obtained. Dentine blocks were prepared for SEM.",
        "Ethics committee approval was granted; bovine teeth served as controls.",
        "A randomised controlled trial with a follow-up of 24 months; in vitro "
        "testing supported the findings.",
    ])
    def test_clinical_language_wins_over_bench_cues(self, abstract):
        hit, why = detect_in_vitro("A study", abstract, "level2")
        assert not hit, f"clinical study would have been demoted: {why}"
        assert "override" in why


class TestProtectedTiers:
    """A systematic review OF in vitro studies is a real category and stays
    where it is; an RCT is not reclassified on a phrase in its abstract."""

    @pytest.mark.parametrize("tier", ["cochrane", "level1", "classic"])
    def test_never_moved(self, tier):
        hit, why = detect_in_vitro(
            "Systematic review of in vitro studies",
            "We pooled in vitro evidence from extracted human teeth.", tier)
        assert not hit and why == "protected tier"


class TestMigrationPolicy:
    """Policy guards that live in scripts/classify_invitro.py, not the
    classifier — both were added because the dry run surfaced them."""

    def test_moving_from_level5_would_be_a_promotion(self):
        """invitro (15) outranks level5 (10), so a narrative review that merely
        discusses bench work must not be 'demoted' into it."""
        assert LEVEL_SCORES["level5"] < LEVEL_SCORES["invitro"]

    def test_case_report_title_guard_matches_real_titles(self):
        from scripts.classify_invitro import _CASE_REPORT_TITLE_RE as rx
        assert rx.search("A case of tooth autotransplantation after cryopreservation")
        assert rx.search("Management of a fractured instrument: a case report")
        assert not rx.search("Comparison of two negative pressure irrigation techniques")


class TestEmptyInput:
    def test_no_text_is_not_in_vitro(self):
        hit, why = detect_in_vitro("", "", "level2")
        assert not hit and why == "no text"
