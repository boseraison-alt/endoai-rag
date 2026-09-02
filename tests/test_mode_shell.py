"""
The unified search bar and three modes (A15).

Replaces `test_mode_panels.py`, whose subject — the Deep Learning report list
appearing on the Case screen — is now a consequence of the shell rather than a
bug with its own patch. That invariant is kept here, asserted through the new
predicate, so nothing is lost by the rewrite.

WHY THE SHELL IS BUILT THIS WAY. The five-tab version decided visibility per
branch, and the `case` branch simply forgot to hide a panel. A fourth mode
would have inherited the same omission. Everything a mode changes is now DATA
in `MODES`, applied by one function, and every surface asks one predicate —
`modeShows(mode, panel)` — which these tests EXECUTE rather than restate
(standing rule 14).
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

SEARCH_MODES = ["review", "case", "learn"]
ALL_MODES    = SEARCH_MODES + ["assess", "profile"]
SHELL = ["MODES", "SEARCH_MODES", "modeShows", "looksLikeACase",
         "_CASE_AGE", "_CASE_TOOTH", "_CASE_FIND"]


def shell(js):
    return run_node(js, names=SHELL)


# ── A15a — one mode value, one predicate ──────────────────

class TestTheModeTable:

    def test_there_are_exactly_three_search_modes(self):
        got = shell("console.log(JSON.stringify([SEARCH_MODES]));")[0]
        assert got == SEARCH_MODES

    def test_each_mode_carries_everything_the_bar_needs(self):
        cfg = shell("console.log(JSON.stringify([MODES]));")[0]
        for m in SEARCH_MODES:
            for key in ("label", "badge", "accent", "placeholder", "button",
                        "promiseWhat", "promiseWhen", "chip"):
                assert cfg[m].get(key), "MODES.%s is missing %s" % (m, key)

    def test_the_labels_are_the_approved_ones(self):
        cfg = shell("console.log(JSON.stringify([MODES]));")[0]
        assert [cfg[m]["label"] for m in SEARCH_MODES] == \
            ["Literature", "Case", "Curriculum"]

    def test_only_the_curriculum_is_marked_slow(self):
        """A15c — the mode that takes minutes says so, and the two that take
        seconds do not borrow its warning styling."""
        cfg = shell("console.log(JSON.stringify([MODES]));")[0]
        assert [bool(cfg[m].get("slow")) for m in SEARCH_MODES] == [False, False, True]
        assert "minutes" in cfg["learn"]["promiseWhen"]

    def test_only_case_gets_the_taller_field(self):
        cfg = shell("console.log(JSON.stringify([MODES]));")[0]
        assert [bool(cfg[m].get("tall")) for m in SEARCH_MODES] == [False, True, False]


class TestTheOnePredicate:
    """Every surface routes through `modeShows`. These run it."""

    def _grid(self):
        return shell(
            "var out={}; %s.forEach(function(m){ out[m]={}; "
            "['searchBar','caseThread','caseComposer','assess','profile',"
            "'welcome','history','suggestion'].forEach(function(p){"
            "out[m][p]=modeShows(m,p);});});"
            "console.log(JSON.stringify([out]));" % json.dumps(ALL_MODES))[0]

    def test_the_search_bar_shows_in_all_three_search_modes(self):
        g = self._grid()
        assert [g[m]["searchBar"] for m in SEARCH_MODES] == [True, True, True]
        assert g["assess"]["searchBar"] is False
        assert g["profile"]["searchBar"] is False

    def test_the_curriculum_list_never_appears_on_the_case_screen(self):
        """The bug the old shell had, kept as an assertion. It reported 22
        report cards above the case composer.

        A19e moved the list off the landing screen altogether and into a
        drawer, so the invariant now reads: the list is shared and badged
        rather than belonging to one mode, and it is reachable from every
        search mode and from neither of the two full-page surfaces."""
        g = self._grid()
        assert g["case"]["history"] is True, "the unified list is not per-mode"
        assert g["review"]["history"] is True
        assert g["learn"]["history"] is True
        assert g["assess"]["history"] is False
        assert g["profile"]["history"] is False

    def test_the_composer_appears_only_once_the_thread_exists(self):
        """A15b — exactly one input. On an empty Case screen the search bar is
        the only way in; the thread's composer is a CONTINUATION.

        Run with `caseMessages` actually defined, because the predicate reads
        it: a mutation showing the composer for the whole of Case mode survived
        a version of this test that left the variable undefined."""
        empty, started = run_node(
            "var caseMessages = [];"
            "var a = modeShows('case','caseComposer');"
            "caseMessages = [{role:'user',content:'x'}];"
            "var b = modeShows('case','caseComposer');"
            "console.log(JSON.stringify([[a, b]]));", names=SHELL)[0]
        assert empty is False, "two inputs on an empty Case screen"
        assert started is True, "the thread has no composer to continue in"

    def test_no_other_mode_gets_the_composer_even_with_a_thread(self):
        got = run_node(
            "var caseMessages = [{role:'user',content:'x'}];"
            "console.log(JSON.stringify([%s.map(function(m){"
            "return modeShows(m,'caseComposer');})]));" % json.dumps(ALL_MODES),
            names=SHELL)[0]
        assert got == [m == "case" for m in ALL_MODES]

    def test_the_case_thread_belongs_to_case_alone(self):
        g = self._grid()
        for m in ALL_MODES:
            assert g[m]["caseThread"] is (m == "case"), m

    def test_the_landing_cards_belong_to_every_search_mode(self):
        """A19d — Case gets three cards of its own. What the five-tab shell
        could not do was keep them DIFFERENT; they are read from the mode's
        own MODES entry now, so one mode cannot render another's copy. That
        half of the invariant is asserted in TestTheWhatYouGetCards."""
        g = self._grid()
        assert [g[m]["welcome"] for m in SEARCH_MODES] == [True, True, True]
        assert g["assess"]["welcome"] is False
        assert g["profile"]["welcome"] is False

    def test_the_cards_step_aside_once_a_case_thread_exists(self):
        """From the first turn on, the thread IS the Case screen. This is the
        same boundary `caseComposer` reads from the other side."""
        empty, started = run_node(
            "var caseMessages = [];"
            "var a = modeShows('case','welcome');"
            "caseMessages = [{role:'user',content:'x'}];"
            "var b = modeShows('case','welcome');"
            "console.log(JSON.stringify([[a, b]]));", names=SHELL)[0]
        assert empty is True, "the Case landing screen has no cards"
        assert started is False, "the cards sit above a live case thread"

    def test_the_suggestion_belongs_to_literature_alone(self):
        g = self._grid()
        for m in ALL_MODES:
            assert g[m]["suggestion"] is (m == "review"), m

    def test_an_unknown_panel_is_hidden_rather_than_shown(self):
        """Fail closed. A typo in a panel name must not reveal something."""
        assert shell("console.log(JSON.stringify(["
                     "modeShows('review','nonesuch')]));")[0] is False

    def test_an_unknown_mode_reveals_nothing(self):
        got = shell("console.log(JSON.stringify([['','x',null]"
                    ".map(function(m){return modeShows(m,'caseThread');})]));")[0]
        assert got == [False, False, False]


class TestSetModeRoutesThroughThePredicate:
    """Standing rule 14 — the predicate is only worth having if `setMode`
    consults it, and a mutation deleting a condition from the real function
    must fail a test."""

    def _set_mode(self):
        src = INDEX_HTML.read_text(encoding="utf-8")
        i = src.index("function setMode(m) {")
        j = src.index("\n}", src.index("renderWhatCards();", i))
        return src[i:j]

    @pytest.mark.parametrize("panel", ["searchBar", "caseThread", "caseComposer",
                                       "assess", "profile", "welcome", "history"])
    def test_every_surface_is_decided_by_modeShows(self, panel):
        body = self._set_mode()
        assert "modeShows(m, '%s')" % panel in body, (
            "setMode decides %s without asking the shared predicate" % panel)

    def test_no_surface_is_toggled_by_a_bare_mode_comparison(self):
        """The old shell's shape: `if (m === 'case') { ...show/hide... }`.
        One comparison survives — the Case bar routes text into the thread's
        composer, which is behaviour rather than visibility."""
        body = self._set_mode()
        assert body.count("m === 'case'") == 0, (
            "a surface is still decided by a bare mode comparison:\n%s" % body)

    def test_the_page_enters_a_mode_on_load(self):
        """The bar's placeholder, promise line, button and history list all
        come from MODES. Without this the page renders the markup's defaults —
        which is exactly what it did on the first build."""
        src = INDEX_HTML.read_text(encoding="utf-8")
        assert re.search(r"^setMode\(mode\);", src, re.M)


# ── A15e — suggest, never switch ──────────────────────────

class TestModeSuggestion:

    CASE_TEXT = ("62-year-old, tooth 26, tender to percussion with a periapical "
                 "radiolucency, already opened last week")
    LIT_TEXT  = ("What is the evidence for MTA versus calcium hydroxide in vital "
                 "pulp therapy?")

    def test_it_recognises_a_patient_case(self):
        assert shell("console.log(JSON.stringify([looksLikeACase(%s)]));"
                     % json.dumps(self.CASE_TEXT))[0] is True

    def test_a_literature_question_is_not_a_case(self):
        assert shell("console.log(JSON.stringify([looksLikeACase(%s)]));"
                     % json.dumps(self.LIT_TEXT))[0] is False

    @pytest.mark.parametrize("text", [
        "62-year-old patient with a question about sealers",      # age only
        "tooth 26 restoration options",                            # tooth only
        "tender to percussion after obturation",                   # finding only
        "62-year-old with tooth 26 discomfort",                    # age + tooth
    ])
    def test_it_needs_all_three_signals(self, text):
        """Any two of age / tooth / finding is a literature question with a
        number in it. Requiring all three is what keeps the strip rare."""
        assert shell("console.log(JSON.stringify([looksLikeACase(%s)]));"
                     % json.dumps(text))[0] is False

    def test_nothing_in_the_page_auto_switches_a_mode(self):
        """Curriculum costs a median $1.33 and one stored run cost $6.51. The
        strip offers; the clinician decides."""
        src = INDEX_HTML.read_text(encoding="utf-8")
        i = src.index("function maybeSuggestCaseMode")
        body = src[i:src.index("\n}", src.index("el.style.display = 'flex'", i))]
        # the only setMode inside is bound to the button's own click handler
        for m in re.finditer(r"setMode\(", body):
            before = body[max(0, m.start() - 120):m.start()]
            assert "onclick" in before, (
                "maybeSuggestCaseMode switches a mode outside a click handler")
