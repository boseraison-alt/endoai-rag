"""
The Deep Learning report list belongs to Deep Learning alone.

REPORTED FROM THE RUNNING APP: 22 "RECENT DEEP LEARNING REPORTS" cards were
rendering on the **Case Discussion** tab, above the case composer.

CAUSE. `setMode` showed the panel in its `learn` branch and hid it in its
`review` branch, and the `case` branch set nothing at all:

    if (m === 'learn')      { panel.style.display = 'block'; ... }
    else if (m === 'case')  { /* No changes needed for standard input */ }
    else                    { panel.style.display = 'none'; }

Three branches, two of which had to remember, and a fourth mode would have
inherited the same bug. Visibility is now one expression evaluated for every
mode, keyed on a predicate this file EXECUTES rather than restates —
standing rule 14, which exists because A1 shipped a gate whose condition every
test asserted around rather than through.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from js_harness import run_node

ROOT       = Path(__file__).parent.parent
INDEX_HTML = ROOT / "templates" / "index.html"

MODES = ["review", "learn", "case", "assess", "profile"]


class TestOnlyDeepLearningShowsItsReportList:

    def test_the_predicate_is_true_for_learn_and_false_for_every_other_mode(self):
        """Runs the shipped function, not a copy of its rule."""
        got = run_node(
            "console.log(JSON.stringify([%s.map(learnHistoryVisible)]));"
            % json.dumps(MODES),
            names=["learnHistoryVisible"])[0]
        assert dict(zip(MODES, got)) == {
            "review": False, "learn": True, "case": False,
            "assess": False, "profile": False,
        }

    def test_case_discussion_is_the_mode_that_regressed(self):
        assert run_node("console.log(JSON.stringify([learnHistoryVisible('case')]));",
                        names=["learnHistoryVisible"])[0] is False

    def test_an_unknown_future_mode_does_not_inherit_the_panel(self):
        """The original bug was a branch that set nothing. A new mode must
        default to hidden rather than to whatever the last mode left."""
        got = run_node(
            "console.log(JSON.stringify([['', null, undefined, 'new-mode']"
            ".map(learnHistoryVisible)]));", names=["learnHistoryVisible"])[0]
        assert got == [False, False, False, False]


class TestVisibilityIsSetFromOneExpression:
    """Standing rule 14. The predicate above is only meaningful if `setMode`
    actually routes the panel through it."""

    def _set_mode(self):
        src = INDEX_HTML.read_text(encoding="utf-8")
        i = src.index("var learnHistPanel = document.getElementById('learnHistoryPanel');")
        j = src.index("\n  if (m !== 'case') renderPrompts();", i)
        return src[i:j]

    def test_the_panel_display_is_assigned_through_the_predicate(self):
        body = self._set_mode()
        m = re.search(r"learnHistPanel\.style\.display\s*=\s*([^;]+);", body)
        assert m, "setMode no longer assigns the panel's display"
        assert "learnHistoryVisible(m)" in m.group(1), (
            "display is set from something other than the shared predicate: %s"
            % m.group(1))

    def test_no_branch_sets_the_display_a_second_time(self):
        """The bug was per-branch assignment. One assignment means no branch can
        forget, and no branch can disagree."""
        body = self._set_mode()
        assert len(re.findall(r"learnHistPanel\.style\.display\s*=", body)) == 1

    def test_the_history_load_is_gated_by_the_same_predicate(self):
        """Loading the list for a mode that does not show it is a wasted fetch
        on every tab switch."""
        body = self._set_mode()
        m = re.search(r"if \((.+?)\)\s*loadLearnModeHistory\(\);", body)
        assert m, "loadLearnModeHistory is called unconditionally"
        assert "learnHistoryVisible(m)" in m.group(1), m.group(1)
