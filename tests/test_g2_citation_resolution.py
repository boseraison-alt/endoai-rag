"""G2 — a citation that resolves to nothing is dropped, loudly.

WHY THIS IS NARROWER THAN IT WAS SPECIFIED. The instruction read "never emit a
non-PMID identifier into a PMID slot". Taken literally that deletes a
deliberate, tested feature: `trust-surface-v1` Q4 introduced synthetic library
keys so hand-ingested authority documents could be cited at all, and
`tests/test_pseudo_pmid_keys.py` pins six consumers of them. The alternative was
considered and rejected there in as many words — "rendering the marker as a pill
without widening that guard would only have traded a raw marker for a dead one".

MEASURED before choosing: of 432 citation slots holding a non-numeric identifier
across 207 stored answers, **430 RESOLVE** to a real library row and render
correctly. Dropping them removes RIGHT output, which is the one thing these
gates are not allowed to do. So the gate is on RESOLUTION, not on shape.

It drops 0 slots on today's corpus. Its value is what happens when the sixteen
fabricated guideline rows are removed (the A49-proper decision): those 430 slots
become unresolvable that instant, and this is what stops them rendering as
dangling citations.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import endo_ai as e  # noqa: E402


# ── G2 ────────────────────────────────────────────────────────────────
KNOWN = {"ESE-QG-2023", "AAE-PS-cbct", "NBK430685"}


class TestG2CitationsThatResolveToNothing:

    def test_an_unresolvable_marker_is_dropped(self):
        t = "This claims something [[PMID:AAE-PS-imaginary]]."
        out, dropped = e.drop_unresolvable_citations(t, known=KNOWN)
        assert dropped == ["AAE-PS-imaginary"]
        assert "AAE-PS-imaginary" not in out

    def test_an_unresolvable_reference_entry_is_dropped(self):
        t = "1. [PMID: ESE-FAKE-2099] Some document that does not exist."
        out, dropped = e.drop_unresolvable_citations(t, known=KNOWN)
        assert dropped == ["ESE-FAKE-2099"]
        assert "ESE-FAKE-2099" not in out

    def test_a_RESOLVING_synthetic_key_survives(self):
        """The 430 slots that are the feature working, not the defect."""
        t = "Magnification is endorsed [[PMID:ESE-QG-2023]]."
        out, dropped = e.drop_unresolvable_citations(t, known=KNOWN)
        assert dropped == []
        assert "[[PMID:ESE-QG-2023]]" in out

    def test_a_numeric_pmid_is_never_touched(self):
        """Numeric ids resolve through eutils, and a fabricated numeric PMID is
        the fabrication validator's job — not this gate's."""
        t = "A real paper says so [[PMID:36512807]] and [PMID: 9477818]."
        out, dropped = e.drop_unresolvable_citations(t, known=set())
        assert dropped == []
        assert out == t

    def test_the_drop_is_counted_not_silent(self, capsys):
        """Rule 32 and invariant 15. A silently dropped citation is what made a
        banner read '9/9 CONSISTENT' over an answer with ten cited claims."""
        t = "Claim one [[PMID:AAE-PS-nope]]. Claim two [[PMID:AAE-PS-nope]]."
        _out, dropped = e.drop_unresolvable_citations(t, known=KNOWN)
        assert len(dropped) == 2
        printed = capsys.readouterr().out
        assert "[G2]" in printed and "AAE-PS-nope" in printed

    def test_the_gate_fails_OPEN_when_the_library_is_unreachable(self,
                                                                monkeypatch):
        """Dropping every synthetic citation because the database blinked would
        be a far worse answer than leaving them in."""
        monkeypatch.setattr(e, "_known_synthetic_keys", lambda: None)
        t = "Endorsed [[PMID:ESE-QG-2023]] and [[PMID:AAE-PS-imaginary]]."
        out, dropped = e.drop_unresolvable_citations(t)
        assert dropped == []
        assert out == t

    def test_it_runs_on_the_path_that_serves_answers(self, monkeypatch):
        """Rule 14 — the tests above call the helper directly, so they pass
        with nothing calling it. This goes through `finalise_answer_text`,
        which every served and cached answer passes through."""
        monkeypatch.setattr(e, "_known_synthetic_keys", lambda: set(KNOWN))
        raw = ("## Findings\n\nReal claim [[PMID:36512807]]. "
               "Fake claim [[PMID:AAE-PS-imaginary]].\n")
        served, _blocks = e.finalise_answer_text(raw)
        assert "AAE-PS-imaginary" not in served
        assert "[[PMID:36512807]]" in served


class TestTheGatesOnlyRemove:
    """Both gates are specified as able to remove wrong output and nothing
    else. These pin that they never ADD or REWRITE."""

    def test_g2_leaves_everything_else_byte_identical(self, monkeypatch):
        monkeypatch.setattr(e, "_known_synthetic_keys", lambda: set(KNOWN))
        t = ("Prose with **bold**, an em-dash — and a table row |a|b|.\n"
             "A citation [[PMID:36512807]] and a resolving key "
             "[[PMID:NBK430685]].\n")
        out, dropped = e.drop_unresolvable_citations(t)
        assert dropped == []
        assert out == t

    def test_g1_returns_the_same_objects_not_copies(self):
        pool = [{"pmid": "333", "title": "Good", "journal": "Int Endod J"}]
        kept = e._exclude_withdrawn(pool)
        assert kept[0] is pool[0]
