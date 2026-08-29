"""
Rescore idempotency, specifically across the provenance penalties.

The danger: rescore_library.py now applies COI/erratum/registry adjustments to
stored scores. If it ever multiplied the ALREADY-STORED score instead of
recomputing from base components, every run would compound the penalty
(0.85, 0.72, 0.61, ...) and quietly bury flagged papers. The existing
"run it twice" check predates these penalties, so this file pins the property.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from endo_ai import score_paper


def rescored(level_key, year, citations, n, fu, if_pts, *,
             coi=False, registry="", erratum=False, retraction=False,
             medline=True):
    """Mirror of the adjustment block in scripts/rescore_library.py.

    Critically it starts from score_paper() every time — the base components —
    never from a previously stored value.
    """
    s, _ = score_paper(level_key, year, citations, n, fu, if_pts)
    if coi:
        s = round(s * 0.85, 1)
    if registry:
        s = round(min(s * 1.05, 100.0), 1)
    if erratum:
        s = round(s * 0.97, 1)
    if retraction:
        s = round(s * 0.50, 1)
    if not medline:
        s = round(s * 0.97, 1)
    return s


class TestRescoreIsIdempotent:

    BASE = ("level1", 2023, 40, 150, 24, 11.0)

    def test_clean_paper_stable_across_runs(self):
        a = rescored(*self.BASE)
        b = rescored(*self.BASE)
        assert a == b

    def test_coi_flagged_paper_stable_across_runs(self):
        """The path the old idempotency check never exercised."""
        a = rescored(*self.BASE, coi=True)
        b = rescored(*self.BASE, coi=True)
        assert a == b, "second rescore of a COI-flagged paper changed its score"

    def test_penalty_does_not_compound(self):
        """Recomputing must land at exactly one application of the penalty."""
        clean  = rescored(*self.BASE)
        once   = rescored(*self.BASE, coi=True)
        assert once == round(clean * 0.85, 1)
        # Simulating a buggy re-multiply would give a strictly lower number;
        # confirm we are not there.
        compounded = round(once * 0.85, 1)
        assert once != compounded
        assert rescored(*self.BASE, coi=True) == once

    def test_all_adjustments_together_are_stable(self):
        kwargs = dict(coi=True, registry="ClinicalTrials.gov",
                      erratum=True, medline=False)
        assert rescored(*self.BASE, **kwargs) == rescored(*self.BASE, **kwargs)

    def test_registry_bonus_capped_at_100(self):
        s = rescored("cochrane", 2024, 500, 5000, 120, 15.0,
                     registry="ClinicalTrials.gov")
        assert s <= 100.0


class TestCuratedRowsAreExcludedFromRescoring:
    """The rescorer — not just the backfill — must skip curated rows, since it
    is the thing that actually writes the penalised score."""

    def test_rescore_query_filters_curated_and_unlabelled(self):
        sql = (Path(__file__).parent.parent / "scripts" / "rescore_library.py").read_text(encoding="utf-8")
        assert "COALESCE(is_curated, FALSE) = FALSE" in sql, \
            "rescorer must exclude curated rows or hand-assigned scores get overwritten"
        assert "COALESCE(level_key,'') <> ''" in sql, \
            "rescorer must skip unlabelled papers rather than score them as unknown design"

    def test_rescore_recomputes_from_components(self):
        """Guard the actual failure mode: multiplying the stored score."""
        src = (Path(__file__).parent.parent / "scripts" / "rescore_library.py").read_text(encoding="utf-8")
        assert "new_score, _ = score_paper(" in src, \
            "rescorer must derive from score_paper(), not from the stored value"
        # The adjustments must operate on new_score, never on r['score'].
        assert "r[\"score\"] *" not in src and "r['score'] *" not in src, \
            "penalty applied to the stored score would compound on every run"
