"""
The tier hierarchy must be real on BOTH retrieval paths.

The bug this guards: the RAG path banded library papers into evidence tiers by
SCORE (>=70 -> cochrane/level1, 50-70 -> level2/3, <50 -> level4/5). A
well-cited recent case series scoring 72 was therefore handed to Claude
labelled "Level I — RCTs and Systematic Reviews", while a smaller Cochrane
review scoring 58 was demoted to Level II/III. The system prompt instructs
Claude to trust the tier label absolutely and to let a higher tier override a
lower one, so this inverted the product's central guarantee on the path most
questions take.

Invariant: study design decides the BAND; score only ranks WITHIN a band.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from endo_ai import TIER_ORDER, TIER_LABEL, LEVEL_SCORES


def band(papers):
    """Mirror of the banding in app.build_evidence_base_with_progress()."""
    by_tier = {}
    for p in papers:
        tier = (p.get("level_key") or "").strip()
        if tier not in TIER_ORDER:
            tier = "level5"          # unknown design -> weakest, never promoted
        by_tier.setdefault(tier, []).append(p)
    for tier, bucket in by_tier.items():
        bucket.sort(key=lambda x: x["score"], reverse=True)
    return by_tier


def paper(pmid, level_key, score):
    return {"pmid": pmid, "level_key": level_key, "score": score}


class TestScoreNeverPromotesAcrossTiers:

    def test_high_scoring_case_series_stays_level4(self):
        """The exact inversion that shipped: a case series outscoring a
        Cochrane review must NOT be presented as higher-tier evidence."""
        bands = band([
            paper("case", "level4", 72.0),
            paper("cochrane", "cochrane", 58.0),
        ])
        assert "case" in [p["pmid"] for p in bands["level4"]]
        assert "cochrane" in [p["pmid"] for p in bands["cochrane"]]
        assert "case" not in [p["pmid"] for p in bands.get("level1", [])]

    def test_low_scoring_cochrane_stays_top_tier(self):
        bands = band([paper("c", "cochrane", 41.0)])
        assert bands["cochrane"][0]["pmid"] == "c"

    @pytest.mark.parametrize("tier", ["cochrane", "level1", "level2",
                                      "level3a", "level3b", "level4", "level5"])
    def test_every_tier_lands_in_its_own_band(self, tier):
        bands = band([paper("x", tier, 90.0)])
        assert tier in bands and bands[tier][0]["pmid"] == "x"

    def test_score_ranks_within_a_tier(self):
        bands = band([
            paper("weak", "level1", 55.0),
            paper("strong", "level1", 88.0),
            paper("mid", "level1", 70.0),
        ])
        assert [p["pmid"] for p in bands["level1"]] == ["strong", "mid", "weak"]


class TestUnknownDesignIsDemotedNotPromoted:

    def test_unlabelled_paper_goes_to_weakest_tier(self):
        """An unknown design must never be presented as strong evidence,
        however well it scores."""
        bands = band([paper("mystery", "", 95.0)])
        assert bands["level5"][0]["pmid"] == "mystery"
        assert "cochrane" not in bands and "level1" not in bands

    def test_unrecognised_tier_key_is_demoted(self):
        bands = band([paper("odd", "not_a_real_tier", 99.0)])
        assert bands["level5"][0]["pmid"] == "odd"


class TestTierOrderIsComplete:
    """A tier missing from TIER_ORDER is invisible to _build_evidence_context(),
    so its papers never reach Claude at all."""

    def test_every_labelled_tier_is_in_tier_order(self):
        missing = [k for k in TIER_LABEL if k not in TIER_ORDER]
        assert not missing, f"tiers with labels but absent from TIER_ORDER: {missing}"

    def test_classics_are_included(self):
        """272 library papers are 'classic'. Before this was added they would
        have been silently dropped once banding switched to level_key."""
        assert "classic" in TIER_ORDER

    def test_order_is_strongest_first(self):
        """TIER_ORDER must be monotonically non-increasing in design strength,
        or 'higher tier leads' means nothing."""
        scores = [LEVEL_SCORES.get(t, 0) for t in TIER_ORDER]
        assert scores == sorted(scores, reverse=True), \
            f"TIER_ORDER is not strongest-first: {list(zip(TIER_ORDER, scores))}"
