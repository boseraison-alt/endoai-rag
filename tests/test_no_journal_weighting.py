"""
No journal-identity signal in scoring (`classics-v1` [C], RB's decision of
2026-09-02, taken on the JOE-vs-IEJ question).

THE DECISION. Venue is metadata and Cochrane-verification only. A paper is not
better because of where it appeared, and the remedy for a missing canon paper
is a retrieval or ingestion fix — never venue weight. That decision needs a
test, because the plumbing for venue weight already exists in this file:
`get_impact_factor(journal_name)` is called at both scoring call sites and its
result is passed into `score_paper` as `if_score`.

THIS IS NOT A SOURCE GREP. Every assertion below runs the real
`endo_ai.score_paper` and compares numbers it returns. A grep for "journal"
would pass while a journal signal flowed through a differently-named variable,
and would fail on the Cochrane verification and the display metadata, which
are both allowed.

THE POSITIVE CONTROL IS THE LOAD-BEARING PART. `TestTheProbeCanDetectAVenue
Signal` flips `USE_IMPACT_FACTOR` and shows the SAME sweep does move the score.
Without it, every test here would pass just as well against a `score_paper`
that ignored all its arguments.
"""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai
from endo_ai import score_paper


# A spread of real paper shapes, so a venue signal cannot hide in one corner
# of the input space. (level_key, year, citations, n, followup_months)
PAPERS = [
    ("cochrane", 2019, 400, 1200, 24),
    ("level1",   2015, 180,  240, 12),
    ("level2",   2008,  60,   90,  6),
    ("level3a",  2001,  25,   40, 36),
    ("level4",   1993,   8,   14, None),
    ("level5",   1987,   3, None, None),
    ("classic",  1990, 500,  100, 60),
    ("invitro",  2022,   1,   30, None),
]

# The whole range `score_impact_factor` can produce, which is what a journal
# name turns into before it reaches the arithmetic.
IF_SCORES = [0.0, 1.0, 3.0, 5.0, 7.5, 10.0, 12.0, 15.0]


def _scores(if_score, is_review=False):
    return [score_paper(lk, y, c, n, fu, if_score, is_review=is_review)[0]
            for lk, y, c, n, fu in PAPERS]


class TestVenueCannotMoveAScore:

    def test_the_impact_factor_term_changes_nothing(self):
        """The direct statement of the invariant, run rather than read."""
        baseline = _scores(IF_SCORES[0])
        for v in IF_SCORES[1:]:
            assert _scores(v) == baseline, (
                f"a venue-derived value of {v} moved the score: "
                f"{_scores(v)} vs {baseline}")

    def test_it_holds_for_reviews_too(self):
        baseline = _scores(IF_SCORES[0], is_review=True)
        for v in IF_SCORES[1:]:
            assert _scores(v, is_review=True) == baseline

    def test_the_impact_factor_component_is_always_zero(self):
        """Not merely cancelled out of the total — absent from the breakdown,
        which is what the UI and `rescore_library` both read."""
        for v in IF_SCORES:
            for lk, y, c, n, fu in PAPERS:
                _total, parts = score_paper(lk, y, c, n, fu, v)
                assert parts["impact_factor"] == 0.0, (
                    f"if_score={v} produced an impact_factor component of "
                    f"{parts['impact_factor']} for {lk}")

    def test_the_toggle_is_off_as_shipped(self):
        """`USE_IMPACT_FACTOR` predates the decision and can still turn venue
        weight back on from the environment. RB's decision makes that a
        violation rather than a configuration, and this is where a future
        session finds out."""
        assert endo_ai.USE_IMPACT_FACTOR is False, (
            "USE_IMPACT_FACTOR is on. Journal impact factor is a "
            "venue-derived signal, and no venue-derived signal may reach the "
            "score — see CURO_HANDOVER.md invariant 11.")

    def test_score_paper_takes_no_venue_parameter(self):
        """Structural, via the signature rather than a text search. `if_score`
        is the one venue-derived argument and the tests above prove it inert;
        nothing else may appear."""
        params = list(inspect.signature(score_paper).parameters)
        for p in params:
            low = p.lower()
            assert not any(w in low for w in
                           ("journal", "issn", "venue", "publisher", "source")), (
                f"score_paper grew a venue parameter: {p}")
        assert "if_score" in params, (
            "if_score was removed — if that is deliberate, delete this test "
            "and the toggle with it, do not leave the invariant untested")


class TestTheProbeCanDetectAVenueSignal:
    """THE POSITIVE CONTROL. Everything above passes trivially against a
    `score_paper` that ignores its arguments. This shows the same sweep DOES
    move the score the moment a venue signal is admitted, which is the only
    thing that makes the assertions above evidence."""

    def test_turning_the_toggle_on_moves_the_score(self, monkeypatch):
        monkeypatch.setattr(endo_ai, "USE_IMPACT_FACTOR", True)
        low, high = _scores(0.0), _scores(15.0)
        assert low != high, (
            "with USE_IMPACT_FACTOR on, the impact-factor term STILL did not "
            "move the score — this test is dead and so is every test above it")
        assert all(h >= l for h, l in zip(high, low))

    def test_the_journal_lookup_really_does_discriminate(self):
        """And the other half: journal names map to DIFFERENT values, so the
        invariant is not holding because the lookup is a constant."""
        vals = set()
        for name in ("Journal of Endodontics", "International Endodontic Journal",
                     "Cochrane Database of Systematic Reviews",
                     "Some Predatory Dental Bulletin", ""):
            try:
                if_val, if_pts = endo_ai.get_impact_factor(name)
            except Exception:            # pragma: no cover — offline lookup
                pytest.skip("impact-factor lookup unavailable")
            vals.add(round(float(if_pts or 0), 3))
        assert len(vals) > 1, (
            "every journal maps to the same impact-factor score, so the "
            "invariant above is untested — it would hold even if the value "
            "were used")
