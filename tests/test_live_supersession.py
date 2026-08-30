"""
Live-path supersession (WORKLIST 1.2).

The library path excludes superseded Cochrane versions via the stored
superseded_by column; before this, the live path had no concept of it, so a
question routed to PubMed could cite a 2012 version of a review updated in
2020 at full tier.

The XML fixture is real efetch output for the CD005296 chain ("Single versus
multiple visits for endodontic treatment", three generations: 17943848 (2007)
→ 27905673 (2016) → 36512807 (2022)), captured from live PubMed — the same
ground truth used to verify the UpdateIn direction for the library backfill.
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from endo_ai import (_apply_supersession, _demote_one_tier,
                     _merge_corrections_and_registries,
                     format_provenance_badges)

FIXTURE = Path(__file__).parent / "fixtures" / "pubmed_xml" / "cd005296_versions.xml"


def _paper(pmid, level_key="cochrane", superseded_by="", score=80.0):
    return {"pmid": pmid, "level_key": level_key, "superseded_by": superseded_by,
            "score": score, "journal": "Cochrane Database Syst Rev"}


class TestUpdateInParsing:
    """Direction matters: UpdateIn sits on the OLDER record and names its
    successor; UpdateOf points backwards. Confusing them inverts the feature —
    the CURRENT version would be flagged stale and the stale ones served."""

    def _run_merge(self):
        meta = {p: {"has_erratum": False, "has_retraction": False,
                    "registry_ids": [], "superseded_by": ""}
                for p in ("17943848", "27905673", "36512807")}
        fake = MagicMock(status_code=200, text=FIXTURE.read_text(encoding="utf-8"))
        with patch("endo_ai.requests.get", return_value=fake):
            _merge_corrections_and_registries(list(meta), meta)
        return meta

    def test_older_records_get_their_successor(self):
        meta = self._run_merge()
        assert meta["27905673"]["superseded_by"] == "36512807"
        # The live path records the DIRECT successor; chain resolution to the
        # terminal version is the library backfill's job.
        assert meta["17943848"]["superseded_by"] == "27905673"

    def test_current_version_is_never_flagged(self):
        meta = self._run_merge()
        assert meta["36512807"]["superseded_by"] == ""


class TestApplySupersession:

    def test_old_version_dropped_when_successor_in_batch(self):
        batch = [_paper("27905673", superseded_by="36512807"),
                 _paper("36512807")]
        kept = _apply_supersession(batch)
        assert [p["pmid"] for p in kept] == ["36512807"]

    def test_old_version_demoted_when_successor_absent(self):
        batch = [_paper("27905673", superseded_by="36512807"),
                 _paper("11111111")]
        kept = _apply_supersession(batch)
        by_pmid = {p["pmid"]: p for p in kept}
        assert "27905673" in by_pmid, "evidence must be kept, not silently lost"
        assert by_pmid["27905673"]["level_key"] == "level1", \
            "a stale version must not sit at the tier its successor earned"
        assert by_pmid["11111111"]["level_key"] == "cochrane"

    def test_three_generation_chain(self):
        """Oldest drops (direct successor present), middle drops (its successor
        present), current survives untouched."""
        batch = [_paper("17943848", superseded_by="27905673"),
                 _paper("27905673", superseded_by="36512807"),
                 _paper("36512807")]
        kept = _apply_supersession(batch)
        assert [p["pmid"] for p in kept] == ["36512807"]
        assert kept[0]["level_key"] == "cochrane"

    def test_clean_batch_is_untouched(self):
        batch = [_paper("1"), _paper("2", level_key="level1")]
        assert _apply_supersession(batch) == batch

    def test_empty_batch(self):
        assert _apply_supersession([]) == []


class TestDemoteOneTier:

    # level4 -> invitro, not level4 -> level5: WORKLIST 1.4 inserted the
    # in vitro tier between them, and a demotion must step one rung rather
    # than skip the new one.
    @pytest.mark.parametrize("src,dst", [
        ("cochrane", "level1"), ("level1", "level2"), ("level2", "level3a"),
        ("level3a", "level3b"), ("level4", "invitro"), ("invitro", "level5"),
        ("level5", "level5"),
    ])
    def test_one_step_down(self, src, dst):
        assert _demote_one_tier(src) == dst

    def test_classic_and_unknown_stay_put(self):
        """'classic' is a curation label, 'level3' a legacy alias — neither is
        a rung on the design ladder."""
        assert _demote_one_tier("classic") == "classic"
        assert _demote_one_tier("level3") == "level3"
        assert _demote_one_tier("") == ""


class TestBadgeParity:
    """One renderer for both retrieval paths — the badge must be identical
    whether the paper came from live PubMed or the library."""

    def test_superseded_badge_renders_and_names_the_successor(self):
        live_shaped = {"pmid": "27905673", "superseded_by": "36512807"}
        library_shaped = {"pmid": "27905673", "superseded_by": "36512807",
                          "similarity": 0.8, "is_curated": False}
        live_badge = format_provenance_badges(live_shaped)
        lib_badge = format_provenance_badges(library_shaped)
        assert "SUPERSEDED" in live_badge and "36512807" in live_badge
        assert live_badge == lib_badge

    def test_no_badge_without_the_field(self):
        assert "SUPERSEDED" not in format_provenance_badges({"pmid": "1"})
