"""WORKLIST C3 — scoping reviews classified consistently.

Two earlier migrations both declined to invent a tier for scoping reviews and
defaulted opposite ways, leaving 8 at level1 and 3 at level5 (plus more added
by write-back since). The rule now implemented by
scripts/reclassify_scoping_reviews.py:

    level5, UNLESS PublicationTypeList includes "Systematic Review" or
    "Meta-Analysis" on a MEDLINE-indexed record (then level1 — NLM read the
    paper and says it is an evidence synthesis whatever the title claims).

The MEDLINE gate is the load-bearing part (HANDOVER: publisher-supplied
records carry only ["Journal Article", "Review"] regardless of content; a
previous pubtype-only pass would have demoted 45 genuine systematic reviews).

Every pubtype list below is REAL — fetched from PubMed for the actual
scoping-review rows on 2026-08-30 by the migration's own dry run.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.reclassify_scoping_reviews import target_tier, SYNTHESIS_PUBTYPES
from scripts.reclassify_by_pubtype import LEVEL1_PUBTYPES


# (pmid, pubtypes as returned by PubMed, medline_indexed, expected tier)
REAL_RECORDS = [
    # The common case: NLM's dedicated Scoping Review pubtype, MEDLINE.
    ("42183648", ["Journal Article", "Scoping Review"], True, "level5"),
    ("40287048", ["Journal Article", "Scoping Review",
                  "Research Support, Non-U.S. Gov't"], True, "level5"),
    # "Systematic Scoping Review" in the TITLE — but NLM tagged it Scoping
    # Review, not Systematic Review, so the title's "systematic" wins nothing.
    ("30970065", ["Journal Article", "Scoping Review"], True, "level5"),
    # Publisher-supplied records: pubtypes not authoritative, but the DEMOTION
    # is keyed on the self-referential title, so they still go to level5.
    ("36044911", ["Journal Article"], False, "level5"),
    ("36078953", ["Journal Article", "Scoping Review"], False, "level5"),
    ("40740278", ["Journal Article", "Review"], False, "level5"),
    # Already level5 and stays there.
    ("39015942", ["Journal Article", "Scoping Review"], True, "level5"),
]


class TestTheRule:

    @pytest.mark.parametrize("pmid,pts,mi,expected", REAL_RECORDS,
                             ids=[r[0] for r in REAL_RECORDS])
    def test_real_records_map_to_level5(self, pmid, pts, mi, expected):
        tier, why = target_tier(pts, mi)
        assert tier == expected, f"PMID {pmid}: {tier} ({why})"

    def test_medline_systematic_review_pubtype_earns_level1(self):
        """The exception: a MEDLINE record NLM tagged Systematic Review is a
        genuine evidence synthesis whatever its title says. No current
        scoping-review row carries this (NLM uses its dedicated Scoping
        Review type), but future hybrids must not be buried."""
        tier, why = target_tier(["Journal Article", "Systematic Review"], True)
        assert tier == "level1"
        assert "MEDLINE" in why

    def test_meta_analysis_pubtype_earns_level1(self):
        tier, _ = target_tier(["Journal Article", "Meta-Analysis"], True)
        assert tier == "level1"

    def test_the_medline_gate_is_not_optional(self):
        """A NON-MEDLINE record cannot earn the level1 exception even with the
        pubtype present: an unindexed pubtype list proves nothing (the trap
        that would have demoted 45 genuine SRs cuts both ways — it must not
        PROMOTE on unverified metadata either)."""
        tier, why = target_tier(["Journal Article", "Systematic Review"], False)
        assert tier == "level5"
        assert "NOT MEDLINE" in why

    def test_conflicting_consensus_pubtype_parks_the_row(self):
        """PMID 39487671 (real record): NLM tagged it both Scoping Review and
        Consensus Statement. reclassify_by_pubtype maps consensus statements
        to level1; demoting it here would recreate the exact
        two-rules-disagree failure C3 fixes. The row is parked (None), never
        guessed at."""
        tier, why = target_tier(
            ["Journal Article", "Scoping Review", "Consensus Statement"], True)
        assert tier is None
        assert "consensus statement" in why

    def test_conflict_guard_only_applies_on_medline_records(self):
        """On a publisher-supplied record 'Consensus Statement' is as
        unverifiable as everything else in the list — the demotion (keyed on
        the title) proceeds."""
        tier, _ = target_tier(
            ["Journal Article", "Scoping Review", "Consensus Statement"], False)
        assert tier == "level5"

    def test_empty_pubtypes_still_demote_by_title(self):
        """The scope query already established the title says 'scoping
        review'; a record PubMed returned nothing for is still one."""
        tier, _ = target_tier([], True)
        assert tier == "level5"
        tier, _ = target_tier(None, False)
        assert tier == "level5"

    def test_matching_is_case_insensitive(self):
        tier, _ = target_tier(["systematic review"], True)
        assert tier == "level1"
        tier, _ = target_tier(["SYSTEMATIC REVIEW"], True)
        assert tier == "level1"


class TestConsistencyWithTheOtherMigration:
    """The two scripts must keep agreeing about which pubtypes mean level1,
    or C3's inconsistency comes back through the side door."""

    def test_synthesis_pubtypes_are_a_subset_of_level1_pubtypes(self):
        assert SYNTHESIS_PUBTYPES <= set(LEVEL1_PUBTYPES)

    def test_every_other_level1_pubtype_parks_rather_than_demotes(self):
        for tag in LEVEL1_PUBTYPES:
            if tag in SYNTHESIS_PUBTYPES:
                continue
            tier, why = target_tier(["Scoping Review", tag], True)
            assert tier is None, (
                f"'{tag}' maps to level1 in reclassify_by_pubtype but this "
                f"rule demoted through it ({tier}: {why})")
