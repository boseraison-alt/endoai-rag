"""
Per-tier quality floors (WORKLIST 1.5).

QUALITY_FLOOR was one number (50) applied to every tier. Score is not
comparable across tiers by construction — design contributes 39%, so a Cochrane
review starts at 100 and a case series at 20 before the paper itself is weighed
— so a flat cut did not remove weak papers evenly, it removed whole tiers.
Measured on the real library: level4 kept 4 of 175, invitro 1 of 155, level5 3
of 153. Only MIN_PAPERS_KEPT=3 was rescuing them, so a "case series" block shown
to a clinician held three papers chosen by a rule that had already thrown away
the other 172.

The safety property that makes this change reviewable is that it can only ever
LOOSEN a tier. That is asserted first and hardest.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from endo_ai import (QUALITY_FLOOR, TIER_QUALITY_FLOORS, _tier_floor,
                     _apply_quality_threshold, MIN_PAPERS_KEPT, TIER_ORDER)


def _papers(scores):
    return [{"pmid": str(i), "score": s} for i, s in enumerate(sorted(scores, reverse=True))]


class TestFloorsCanOnlyLoosen:
    """The whole change is safe if and only if this holds: no paper that
    reaches a clinician today can be removed by it."""

    @pytest.mark.parametrize("tier", TIER_ORDER)
    def test_no_tier_floor_exceeds_the_global_ceiling(self, tier):
        assert _tier_floor(tier) <= QUALITY_FLOOR

    def test_configured_values_are_capped_even_if_someone_raises_one(self):
        """The cap lives in _tier_floor, not in the dict, so a careless edit to
        the config cannot tighten a tier."""
        import endo_ai
        original = dict(endo_ai.TIER_QUALITY_FLOORS)
        try:
            endo_ai.TIER_QUALITY_FLOORS["level4"] = 95
            assert _tier_floor("level4") == QUALITY_FLOOR
        finally:
            endo_ai.TIER_QUALITY_FLOORS.clear()
            endo_ai.TIER_QUALITY_FLOORS.update(original)

    def test_unknown_tier_falls_back_to_the_global_floor(self):
        assert _tier_floor("no-such-tier") == QUALITY_FLOOR
        assert _tier_floor("") == QUALITY_FLOOR


class TestItIsAConfigNotLiterals:
    def test_every_tier_in_tier_order_has_an_entry(self):
        missing = [t for t in TIER_ORDER if t not in TIER_QUALITY_FLOORS]
        assert not missing, f"tiers with no configured floor: {missing}"

    def test_strong_tiers_are_unchanged_from_the_flat_floor(self):
        """This change is about the bottom of the hierarchy. If it starts
        moving Cochrane or Level I, something has gone wrong."""
        for tier in ("cochrane", "level1", "classic", "level2", "level3b"):
            assert _tier_floor(tier) == QUALITY_FLOOR

    def test_weak_tiers_are_actually_loosened(self):
        for tier in ("level4", "invitro", "level5", "level3", "level3a"):
            assert _tier_floor(tier) < QUALITY_FLOOR, \
                f"{tier} was supposed to be loosened but is still at the flat floor"


class TestThresholdApplication:

    def test_weak_tier_keeps_its_best_work_instead_of_three_rescued_papers(self):
        """The real level4 distribution: nothing near 50, plenty near 40."""
        papers = _papers([44, 43, 41, 38, 35, 33, 30, 28, 22, 18])
        kept = _apply_quality_threshold(papers, mode="review", tier_key="level4")
        assert len(kept) > MIN_PAPERS_KEPT, \
            "level4 still falls through to the top-up rescue"
        assert all(p["score"] >= _tier_floor("level4") for p in kept)

    def test_strong_tier_behaviour_is_untouched(self):
        papers = _papers([88, 74, 66, 52, 48, 30])
        kept = _apply_quality_threshold(papers, mode="review", tier_key="cochrane")
        assert [p["score"] for p in kept] == [88, 74, 66, 52]

    def test_top_up_still_rescues_a_genuinely_empty_tier(self):
        """Loosening must not remove the last-resort behaviour."""
        papers = _papers([9, 7, 5, 3])
        kept = _apply_quality_threshold(papers, mode="review", tier_key="level5")
        assert len(kept) == MIN_PAPERS_KEPT

    def test_empty_input(self):
        assert _apply_quality_threshold([], mode="review", tier_key="level4") == []

    def test_cap_still_applies(self):
        papers = _papers(list(range(40, 90)))
        kept = _apply_quality_threshold(papers, mode="review", tier_key="level1")
        assert len(kept) <= 25
