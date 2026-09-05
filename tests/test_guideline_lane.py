"""A49 item 5 — guidelines have a rung the live path can actually reach.

`level_key='guideline'` already existed as a tier. LEVEL_SCORES gave it 12,
TIER_ORDER placed it between invitro and level5, TIER_LABEL named it. What did
not exist was a query that could reach one, so it was a tier nothing ever
queried — which is the same shape of bug A31 fixed for observational designs,
one document class over.

`ingest_aae_guidelines.py` was written BECAUSE of this gap: the live path
could not reach a guideline, so sixteen were hardcoded instead, twelve of
which the A2 audit found name no verifiable document. This lane is the fix at
the level the workaround was compensating for.

PURELY ADDITIVE, and this file pins each half of that separately:
  - the taxonomy is unchanged (no new tier, no score moved, no order changed)
  - the lane is actually issued, not merely declared
  - it takes no slot from any tier above it
"""

from pathlib import Path

import pytest

import endo_ai as E

ROOT = Path(__file__).parent.parent


class TestTheLaneExists:

    def test_the_filter_names_the_publication_types_guidelines_carry(self):
        terms = [t.lower() for t in E.LEVEL_GUIDELINE_TERMS]
        assert "practice guideline[pt]" in terms
        assert "guideline[pt]" in terms
        assert "consensus development conference[pt]" in terms

    def test_it_is_actually_issued_and_not_merely_declared(self):
        """The bug this item fixes is precisely a tier no query runs."""
        by_key = {k: (terms, label) for k, terms, label in E.tier_query_lanes()}
        assert "guideline" in by_key, (
            "the guideline tier is in TIER_ORDER but not in the list "
            "build_evidence_base iterates — it would never be queried")
        terms, label = by_key["guideline"]
        assert terms is E.LEVEL_GUIDELINE_TERMS
        assert label == E.TIER_LABEL["guideline"]

    def test_build_evidence_base_iterates_that_list(self):
        src = (ROOT / "endo_ai.py").read_text(encoding="utf-8")
        body = src[src.index("def build_evidence_base(topic"):]
        body = body[:body.index("\ndef ")]
        assert "tier_query_lanes()" in body

    def test_it_is_reachable_through_live_path_filters(self):
        assert "guideline" in E.live_path_filters()


class TestItIsAdditive:
    """A12 — reachability now, ranking later, never in one commit."""

    def test_the_taxonomy_did_not_change(self):
        assert E.LEVEL_SCORES["guideline"] == 12
        assert E.TIER_ORDER.index("guideline") == E.TIER_ORDER.index("invitro") + 1
        assert E.TIER_ORDER.index("guideline") < E.TIER_ORDER.index("level5")

    def test_it_ranks_below_every_real_study_design(self):
        """A guideline is a specialty's stated position, not a study. It must
        not outrank a bench result about a mechanism, let alone a trial —
        which is exactly what the hardcoded records did at score 90."""
        for tier in ("cochrane", "level1", "level2", "level3a", "level3b",
                     "level4", "invitro"):
            assert E.LEVEL_SCORES["guideline"] < E.LEVEL_SCORES[tier], tier

    @pytest.mark.parametrize("mode", ["review", "learn", "case"])
    def test_it_has_its_own_quota_in_every_mode(self, mode):
        assert E._tier_cap(mode, "guideline") > 0

    @pytest.mark.parametrize("mode,tier,expected", [
        ("review", "level1", 18), ("learn", "level1", 10),
        ("review", "cochrane", 10), ("learn", "level5", 25),
    ])
    def test_no_existing_quota_changed(self, mode, tier, expected):
        assert E._tier_cap(mode, tier) == expected

    def test_no_existing_lane_was_removed_or_reordered(self):
        keys = [k for k, _t, _l in E.tier_query_lanes()]
        assert keys == ["level1", "level2", "level3a", "level3b", "level4",
                        "guideline", "level5", "observational"]

    def test_the_label_says_it_is_not_a_study(self):
        label = E.TIER_LABEL["guideline"].lower()
        assert "consensus" in label and "not a study" in label


class TestItReachesTheDocumentItWasBuiltFor:

    def test_efcd_is_admitted_by_the_guideline_lane(self):
        """Measured against PubMed, committed as a fixture. The EFCD-ESE-ORCA
        S3 deep-caries guideline was reachable only through level5 at rank
        521 of 608."""
        import json
        rec = json.loads(
            (ROOT / "tests" / "fixtures" / "missed_papers" / "42018467.json")
            .read_text(encoding="utf-8"))
        entry = rec["admission_map"]["guideline"]
        assert entry["admits"] is True
        assert entry["filter"] == " OR ".join(E.LEVEL_GUIDELINE_TERMS), (
            "the lane's filter changed since the fixture was measured; "
            "re-run scripts/fetch_missed_paper_fixtures.py")

    def test_the_quarantine_is_not_undone_by_the_lane(self):
        """The lane reaches REAL guidelines from PubMed. It must not become a
        way back in for the twelve quarantined records, which have no PMID and
        are excluded in SQL — checked here because 'we added a guideline path'
        is exactly when someone would re-enable them."""
        import rag
        rows = rag.search("endodontic guideline", level_key="guideline",
                          limit=200, similarity_threshold=0.0)
        bad = {"AAE-PS-cbct", "AAE-PS-safety", "ESE-QG-2023",
               "AAE-PS-retreatment", "AAE-PS-obturation", "AAE-PS-isolation",
               "AAE-PS-antibiotics", "AAE-PS-microscope", "AAE-PS-trauma",
               "AAE-PS-regenerative", "AAE-PS-cracked-tooth",
               "AAE-PS-implant-v-endo"}
        got = {r.get("pmid") for r in rows}
        assert not (got & bad), f"quarantined records came back: {got & bad}"
