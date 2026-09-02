"""
The anesthesia curriculum as a stored regression fixture (`classics-v1` [A],
folded into `dl-quality-v1`).

WHAT THIS FIXTURE IS. `answers/` is gitignored, so the curriculum RB generated
on 2026-09-01 at 20:36 existed as exactly one untracked file on one machine.
It is the evidence for three separate defects, so it is now committed at
`eval/fixtures/curricula/anesthesia_20260901_before.txt` and this module reads
it directly.

WHEN IT WAS GENERATED MATTERS, and the answer is not what it looks like. That
curriculum came from the port-5003 server, which `/health` reported as running
`f23e8c8` with `git_dirty: true`, imported at 18:53 — BEFORE any of the
`dl-quality-v1` work. So it is not evidence that the truncation gate failed;
it is the before-state the gate was built against.

THE BEFORE FIXTURE IS A POSITIVE CONTROL. Assertions that a regenerated
curriculum is clean prove nothing unless the detectors demonstrably fire on a
document known to be dirty. That is the first class below. The second class is
the actual regression assertion and it runs against the AFTER fixture, which
`dl-quality-v1` Item 5 produces.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai

FIXTURES = Path(__file__).parent.parent / "eval" / "fixtures" / "curricula"
BEFORE = FIXTURES / "anesthesia_20260901_before.txt"
AFTER = FIXTURES / "anesthesia_20260901_after.txt"

# The stitcher's own invention. It appears NOWHERE in this codebase — handed a
# module cut mid-sentence, the stitcher LLM declined to reproduce the damage
# and wrote an editorial placeholder instead. The system detected the
# truncation, said so in plain English, and nothing downstream read it.
SUPPLIED_MARKER = "ends here as supplied"

# The support-check footer's own words when the 30-pair cap bites.
UNCHECKED_FOOTER = re.compile(
    r"(\d+)\s+further cited claim\(s\)\s+were NOT checked")


def _modules(text: str) -> list:
    """(heading, body) for each module in a stitched curriculum."""
    body = text.split("## Citation Support by Module")[0]
    parts = re.split(r"^(## Module[^\n]*)$", body, flags=re.M)
    out = []
    for i in range(1, len(parts), 2):
        seg = parts[i + 1].split("\n---\n")[0]
        if len(seg.split()) >= 40:
            out.append((parts[i].strip(), seg))
    return out


@pytest.mark.skipif(not BEFORE.exists(), reason="before fixture not present")
class TestTheBeforeFixtureIsGenuinelyBroken:
    """POSITIVE CONTROL. Without this, the clean-after assertions below could
    pass because the checks are dead."""

    @pytest.fixture(scope="class")
    def text(self):
        return BEFORE.read_text(encoding="utf-8", errors="replace")

    def test_it_carries_the_stitchers_placeholder(self, text):
        n = text.count(SUPPLIED_MARKER)
        assert n >= 2, (
            f"expected the stitcher's invented placeholder at least twice, "
            f"found {n} — has the fixture been overwritten?")

    def test_the_placeholder_is_not_something_we_wrote(self):
        """If it were ours, the fix would be to stop emitting it. It is not:
        the stitcher wrote it, which makes this a signal we discarded."""
        for f in ("endo_ai.py", "app.py"):
            src = (Path(__file__).parent.parent / f).read_text(encoding="utf-8")
            assert SUPPLIED_MARKER not in src, (
                f"{f} contains the marker — the diagnosis in this module's "
                f"docstring is wrong and must be corrected, not the test")

    def test_a_module_ends_mid_sentence(self, text):
        cut = [(h, endo_ai.detect_module_truncation(b))
               for h, b in _modules(text)]
        bad = [(h, r) for h, r in cut if r["truncated"]]
        assert bad, "the fixture no longer reproduces the truncation"
        # The one RB quoted.
        assert "19.35 mm from the" in text

    def test_the_support_footer_admits_unchecked_claims(self, text):
        hits = UNCHECKED_FOOTER.findall(text)
        assert hits, "the fixture no longer reproduces the 30-pair cap"
        assert sum(int(h) for h in hits) > 0


@pytest.mark.skipif(not AFTER.exists(),
                    reason="dl-quality-v1 Item 5 has not regenerated the "
                           "anesthesia curriculum yet")
class TestTheRegeneratedCurriculumIsClean:
    """The regression assertion RB specified, word for word:
    no module ends mid-sentence, no "ends here as supplied" marker, and the
    support-check footer reports 0 unchecked claims."""

    @pytest.fixture(scope="class")
    def text(self):
        return AFTER.read_text(encoding="utf-8", errors="replace")

    def test_no_module_ends_mid_sentence(self, text):
        bad = [(h, endo_ai.detect_module_truncation(b)["reason"])
               for h, b in _modules(text)
               if endo_ai.detect_module_truncation(b)["truncated"]]
        assert not bad, f"truncated module(s): {bad}"

    def test_no_stitcher_placeholder(self, text):
        assert SUPPLIED_MARKER not in text, (
            "the stitcher invented a placeholder, which means it was handed a "
            "module the assembly gate should have withheld")

    def test_the_support_footer_reports_nothing_unchecked(self, text):
        hits = UNCHECKED_FOOTER.findall(text)
        assert not hits, (
            f"the support check still reports unchecked claims: {hits} — the "
            f"30-pair cap is meant to be gone")

    def test_it_is_the_same_question(self, text):
        """A clean curriculum on a different question would pass every
        assertion above and prove nothing."""
        assert "anesthesia" in text.lower()
        assert "endodontic" in text.lower()
