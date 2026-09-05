"""D1 — a RECENT weak-tier paper survives the early stop; an old one does not.

THE EARLY STOP'S PREMISE, and where it stops holding. Once cochrane + level1
supply 15 papers in Review mode, the weaker lanes are skipped, on the
reasoning that tier banding means a case series cannot override a Level I
finding. That is true of an OLD weak paper — the literature has already
absorbed or refuted it — and false of a new one. A settled topic is exactly
where a new contradicting finding matters most.

The paper this exists for: **Sulaiman 2026**, a level2 single-centre trial
finding no association between haemostasis time and partial pulpotomy outcome
up to 15 minutes. The VPT curriculum builds a six-minute threshold into nine
places — three decision branches, a key takeaway, an abort-treatment
instruction — and vital pulp therapy is a well-covered question, so the early
stop fires on it and level2 was skipped.

WHY ONLY level2 AND level3a. The FULL exemption was measured across 20
review-mode questions and breached both pre-declared thresholds: 24.6 extra
papers per question against ~15, and +48 s against ~30 s. Narrowed to the two
rungs where a Sulaiman-type paper lands once MEDLINE types it, it passes both:

    extra papers    11.1 per question   (threshold ~15)
    extra latency     14 s per question (threshold ~30 s)
    fires on 17 of 20 review questions

AND THE FIRST NARROWED MEASUREMENT WAS WRONG, in my own harness. `--lanes`
filtered only what was COUNTED, so pass 2 still swept every weak lane and
reported 48 s for the narrowed scope — identical to the full one, which is
what gave it away. An exemption that fetches two lanes cannot cost the same as
one that fetches eight.
"""
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import app as A


def paper(pmid, year, score=60.0, level="level2"):
    return {"pmid": pmid, "year": str(year), "score": score,
            "level_key": level, "title": "t", "abstract": "a",
            "authors": "A", "citations": 1, "sample_size": None,
            "followup_months": None, "impact_factor": None,
            "has_coi": False, "is_old": False, "is_outlier": False}


THIS_YEAR = datetime.now().year


class TestTheWindowItself:

    def test_a_recent_paper_is_inside(self):
        assert A._within_recency_window(paper("NEW", THIS_YEAR))

    def test_last_year_is_inside(self):
        assert A._within_recency_window(paper("LASTYEAR", THIS_YEAR - 1))

    def test_an_old_paper_is_outside(self):
        assert not A._within_recency_window(paper("OLD", THIS_YEAR - 5))

    def test_the_boundary_rounds_outward(self):
        """18 months cannot be evaluated against a YEAR, so the window is
        ceil(18/12) = 2 years and rounds OUTWARD — admitting slightly more
        rather than slightly less. The cost of that extra year was measured at
        11.1 papers per question; the cost of rounding the other way is missing
        the paper the exemption exists for."""
        assert A._within_recency_window(paper("EDGE", THIS_YEAR - 2))
        assert not A._within_recency_window(paper("PAST", THIS_YEAR - 3))

    @pytest.mark.parametrize("bad", ["", "Unknown", None, "n/a", 0])
    def test_an_unusable_year_is_outside_not_inside(self, bad):
        """Fails CLOSED. A paper whose year cannot be read is not evidence
        that it is recent, and admitting it would let the exemption widen on
        bad metadata rather than on new literature."""
        assert not A._within_recency_window({"year": bad})


class TestTheLaneScope:

    def test_only_level2_and_level3a_are_exempt(self):
        assert A.EARLY_STOP_RECENCY_LANES == ("level2", "level3a")

    def test_the_exempt_lanes_are_real_weak_lanes(self):
        """Rule 4 — if a lane is renamed, the tuple above still reads fine and
        the exemption silently stops applying to anything."""
        import endo_ai as E
        for lane in A.EARLY_STOP_RECENCY_LANES:
            assert lane in E.TIER_ORDER
            assert lane not in A.EARLY_STOP_TIERS
            assert lane != "cochrane"

    def test_the_weakest_lanes_are_NOT_exempt(self):
        """The measured reason, not a preference: including them cost 24.6
        papers and 48 s per question."""
        for lane in ("level4", "level5", "invitro", "observational"):
            assert lane not in A.EARLY_STOP_RECENCY_LANES


class TestItIsWiredIntoTheEarlyStopBranch:
    """Rule 14, and the reason this file exists at all: a correct window with
    a branch that never calls it is the exact shape of the defect five wiring
    sites had."""

    def _branch(self):
        src = (Path(__file__).parent.parent / "app.py").read_text(encoding="utf-8")
        i = src.index("        if early:")
        j = src.index("        else:", i)
        return src[i:j]

    def test_the_early_branch_fetches_the_exempt_lanes(self):
        b = self._branch()
        assert "EARLY_STOP_RECENCY_LANES" in b, (
            "the early-stop branch does not fetch the exempt lanes — the "
            "exemption is dead code")

    def test_it_passes_recent_only_so_old_papers_are_dropped(self):
        b = self._branch()
        assert "recent_only=EARLY_STOP_RECENCY_LANES" in b, (
            "the lanes are fetched but not filtered, so the early stop has "
            "become no early stop at all for them")

    def test_the_guideline_lane_still_survives_alongside_it(self):
        """It survives for a DIFFERENT reason — a guideline is not weaker
        evidence, it is a different axis — and adding the recency lanes must
        not have displaced it."""
        assert 'l[0] == "guideline"' in self._branch()

    def test_the_filter_runs_before_the_text_is_rebuilt(self):
        """Pruning after the fold would leave papers in `text` that are not in
        `scored` — the 26%-visibility bug in a mirror."""
        src = (Path(__file__).parent.parent / "app.py").read_text(encoding="utf-8")
        i = src.index("if level_key in recent_only:")
        j = src.index("level_text = _scored_to_text(", i)
        assert i < j, "the recency filter runs after the text is built"


class TestTheFoldFiltersWhatItIsTold:
    """Behavioural: the window and the wiring are pinned above; this pins that
    the fold actually drops the old ones and keeps the new."""

    def test_recent_survives_and_old_does_not(self):
        recent, old = paper("RECENT", THIS_YEAR), paper("OLD", THIS_YEAR - 6)
        kept = [p for p in (recent, old) if A._within_recency_window(p)]
        assert [p["pmid"] for p in kept] == ["RECENT"]

    def test_a_lane_not_named_is_untouched(self):
        """`recent_only` is a lane list, not a global switch: level1 must keep
        its old papers, or the early stop would start discarding the evidence
        it exists to preserve."""
        assert "level1" not in A.EARLY_STOP_RECENCY_LANES
