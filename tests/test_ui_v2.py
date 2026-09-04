"""
UI v2 — the layout RB sketched (A19), plus the two things he asked for while
it was being built: the cards lined up with the composer, and a progress
readout that says the engine is alive and roughly how much longer.

WHAT THIS FILE IS NOT. It is not a second mode shell. `MODES` and
`modeShows` are A15's and are asserted in `test_mode_shell.py`; A19 changed
the ARRANGEMENT, not the architecture. What is tested here is what the new
arrangement promises: three cards per mode read from that mode's own table
entry, a drawer that starts closed, a landing screen with nothing else on it,
and a clock that cannot count into negative numbers or outrun its own
promise line.
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
SRC        = INDEX_HTML.read_text(encoding="utf-8")

SEARCH_MODES = ["review", "case", "learn"]
TAGLINE      = "Evidence-Based Dental Educator"

# The clock and the table it reads its budget from.
CLOCK = ["MODES", "_etaTimer", "_etaStart", "_etaBudget",
         "_fmtClock", "_etaTick", "_startEtaClock", "_stopEtaClock"]

# A stub DOM with one progress card in it, and a clock we control. `_etaTick`
# is the production function; nothing here restates what it computes.
DOM_STUB = """
var _now = 0;
Date.now = function () { return _now; };
var _card = { style: { display: 'block' } };
var _eta  = { textContent: '', _cls: {},
              classList: { toggle: function (c, on) { _eta._cls[c] = !!on; },
                           add:    function (c) { _eta._cls[c] = true; },
                           remove: function (c) { _eta._cls[c] = false; } } };
var document = { getElementById: function (id) {
  if (id === 'progressCard') return _card;
  if (id === 'progressEta')  return _eta;
  return null;
} };
var setInterval  = function () { return 1; };
var clearInterval = function () {};
"""


def clock(js, mode="review"):
    return run_node(js, names=CLOCK, mode=mode, preamble=DOM_STUB)[0]


# The poll loop, and a fetch we can make answer 404 or throw.
POLL_FNS = ["MODES", "_etaTimer", "_etaStart", "_etaBudget", "_fmtClock",
            "_etaTick", "_startEtaClock", "_stopEtaClock",
            "_pollMisses", "_jobIsGone", "pollStatus"]

POLL_STUB = """
// Widen the clock's stub: the poll touches elements it does not, and a
// getElementById returning null would throw rather than fail the assertion.
var _extra = {};
function _el(id) {
  if (id === 'progressCard') return _card;
  if (id === 'progressEta')  return _eta;
  if (!_extra[id]) _extra[id] = {id: id, style: {}, textContent: '',
                                 disabled: false,
                                 classList: {toggle: function () {},
                                             add: function () {},
                                             remove: function () {}}};
  return _extra[id];
}
document = { getElementById: _el, querySelector: function () { return null; },
             querySelectorAll: function () { return []; } };
var _cleared = false, _lastError = '', _httpStatus = 200, _throwOnFetch = false;
var _body = {error: 'Job not found'};
var currentJob = null, pollTimer = null, _streamActive = false;
clearInterval = function () { _cleared = true; };
setInterval = function () { return 1; };
function showError(m) { _lastError = m; }
function setLandingVisible() {}
function updateStepPills() {}
function showResult() {}
function showStreamingPartial() {}
function fetch() {
  if (_throwOnFetch) {
    return { then: function () { return this; },
             catch: function (f) { f(new Error('network')); return this; } };
  }
  var res = { status: _httpStatus,
              json: function () { return Promise.resolve(_body); } };
  return Promise.resolve(res);
}
"""


# ── A19b — one tagline, everywhere ────────────────────────

class TestTheTagline:

    def test_the_page_carries_the_new_tagline(self):
        assert SRC.count(TAGLINE) >= 2, "header and <title> both carry it"
        assert "<title>Curo — %s</title>" % TAGLINE in SRC

    @pytest.mark.parametrize("path", [
        "templates/index.html", "templates/tos.html",
        "endo_ai.py", "ui-options/option-c.html",
    ])
    def test_no_surface_still_says_assistant(self, path):
        """RB's edit: Curo teaches, it does not assist. A surface left behind
        is the same defect class as A17's stale method copy — the product
        describing itself as something it no longer claims to be."""
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "Clinical Assistant" not in text
        assert "Clinical Educator" not in text


# ── A19d — three cards per mode, and every claim on them true ──

class TestTheWhatYouGetCards:

    # Frozen deliberately. These are read aloud at a demo and each one is a
    # claim about the engine, so changing the copy should require changing a
    # test and saying why.
    EXPECTED = {
        "review": [
            ("Graded by study design",
             "Cochrane, trial, cohort, bench — never by journal or impact factor."),
            ("Every claim checked",
             "Each cited claim is verified against its abstract, and anything "
             "unsourced is marked as such."),
            ("Sources you can open",
             "Full bibliography with PMIDs."),
        ],
        "case": [
            ("Differential first",
             "What else this could be, before what to do about it."),
            ("Only questions that matter",
             "It asks back only where the answer would actually change — and "
             "never re-asks what you already said."),
            ("Cited like a review",
             "The same evidence engine and the same checks as a literature answer."),
        ],
        "learn": [
            ("Four modules",
             "Built to teach from, not to skim — roughly 12,000 words."),
            ("A graded bibliography",
             "Every paper cited in the text, banded by study design, with "
             "conflicts of interest flagged."),
            ("Slides and audio",
             "Export the same content as a deck, a narrated video or a podcast."),
        ],
    }

    def _cards(self):
        return run_node("console.log(JSON.stringify([MODES]));", names=["MODES"])[0]

    def test_every_mode_has_exactly_three(self):
        cfg = self._cards()
        assert [len(cfg[m]["what"]) for m in SEARCH_MODES] == [3, 3, 3]

    @pytest.mark.parametrize("mode", SEARCH_MODES)
    def test_the_copy_is_the_approved_copy(self, mode):
        got = [(c["title"], c["text"]) for c in self._cards()[mode]["what"]]
        assert got == self.EXPECTED[mode]

    def test_no_two_modes_share_a_card(self):
        """The leak the shell exists to prevent, read at the content level:
        if Case ever renders Literature's cards the sets would intersect."""
        cfg = self._cards()
        seen = {}
        for m in SEARCH_MODES:
            for c in cfg[m]["what"]:
                assert c["title"] not in seen, (
                    "%s and %s share the card %r" % (m, seen.get(c["title"]), c["title"]))
                seen[c["title"]] = m

    @pytest.mark.parametrize("signal", ["impact factor", "citation", "journal"])
    def test_no_card_claims_a_forbidden_ranking_signal(self, signal):
        """A17/A19d. The card these replaced said papers are ranked by
        "citations & impact factor" — invariant 11's signal, named on the
        surface most likely to be read out loud.

        A card may still MENTION one of these, but only to disclaim it. The
        test is therefore not "the word is absent" — that would have passed
        by deleting the honest disclaimer too — but "every mention is a
        denial"."""
        cfg = self._cards()
        for m in SEARCH_MODES:
            for c in cfg[m]["what"]:
                text = c["text"].lower()
                if signal not in text:
                    continue
                before = text.split(signal)[0]
                assert "never by" in before, (
                    "%s card %r asserts %r as something the engine uses: %r"
                    % (m, c["title"], signal, c["text"]))

    def test_the_engine_really_does_ignore_the_two_it_disclaims(self):
        """The copy is only true while the code is. Journal identity is
        invariant 11; the impact factor is off by default and renormalised
        out of the score."""
        endo = (ROOT / "endo_ai.py").read_text(encoding="utf-8")
        assert 'USE_IMPACT_FACTOR = os.getenv("USE_IMPACT_FACTOR", "false")' in endo
        assert "def score_paper(level_key, year, citations, sample_size," in endo
        # and no journal name reaches the arithmetic
        body = endo[endo.index("def score_paper("):endo.index("# ── FETCH COCHRANE")]
        for forbidden in ("journal", "issn", "venue"):
            assert forbidden not in body.lower(), (
                "score_paper reads %r; the card says it never does" % forbidden)


# ── A19f — the landing screen holds four things and nothing else ──

class TestTheLandingScreen:

    def test_the_prompt_cards_are_gone(self):
        """"Nothing else" is the whole instruction. The prompt grid, its data
        and its click handler all go, so a later edit cannot restore half of
        it — and `reviewWhat` went with them, because it held the very
        "ranked ... citations and follow-up" line A17 is a sweep for."""
        for gone in ("promptsGrid", "renderPrompts", "fillQ(", "reviewWhat",
                     "learnWhat", "reviewPrompts", "learnPrompts"):
            assert gone not in SRC, "%s survived the landing-screen cull" % gone

    def test_there_is_exactly_one_input_on_the_landing_screen(self):
        """A15b's invariant, re-checked after the composer was rebuilt: the
        Case thread's own textarea is a continuation, not a second way in."""
        landing = SRC[SRC.index('<div class="center-col"'):SRC.index("<!-- Progress -->")]
        assert landing.count("<textarea") == 1

    def test_the_chips_are_inside_the_composer(self):
        """A19c — docked along the card's lower edge, not floating above it."""
        card = SRC[SRC.index('<div class="input-card" id="inputCard">'):]
        card = card[:card.index("<!-- A15c")]
        assert '<div class="composer-bar">' in card
        assert 'class="mode-chips"' in card
        assert 'id="askBtn"' in card
        assert card.index('<textarea') < card.index('class="composer-bar"')

    def test_there_is_no_tab_strip(self):
        assert '<div class="mode-bar">' not in SRC
        assert 'class="mode-tab' not in SRC

    def test_the_cards_line_up_with_the_composer(self):
        """RB, while it was being built: the cards stopped short of the box
        above them, because the pre-A19 rule capped the grid at 80% of its
        column. Both live in the same 820px column and the cap is lifted."""
        rule = SRC[SRC.index(".what-grid {", SRC.index("A19 - UI v2")):]
        rule = rule[:rule.index("}")]
        assert "max-width: none" in rule

    def test_the_promise_line_says_nothing_about_follow_up_questions(self):
        """RB asked for the phrase off the page. A20 still removes the
        behaviour; the line went back to saying what Literature does."""
        assert "follow-up question" not in SRC.lower()
        assert "follow up question" not in SRC.lower()


# ── A19e — history is a drawer ────────────────────────────

class TestTheHistoryDrawer:

    def test_it_starts_closed(self):
        """"Closed by default" is the point of the item: nothing on the
        landing screen competes with the question box."""
        markup = SRC[SRC.index('<aside class="hist-drawer"'):]
        markup = markup[:markup.index("</aside>")]
        assert 'class="hist-drawer"' in markup, "the drawer ships with `open` set"
        assert 'aria-hidden="true"' in markup

    def test_it_filters_by_all_three_modes_and_all(self):
        for f in ("all", "review", "case", "learn"):
            assert "setHistFilter('%s')" % f in SRC

    def test_the_filter_is_over_the_stored_mode(self):
        """The drawer is a record of what has been asked, not a view of where
        you happen to be standing, so the filter must not follow `mode`."""
        items = json.dumps([{"mode": "review"}, {"mode": "learn"},
                            {"mode": "learn"}, {"mode": "case"}])
        got = run_node(
            "_histItems = %s;"
            "var out = {};"
            "['all','review','case','learn'].forEach(function (f) {"
            "  _histFilter = f; out[f] = histVisibleItems().length; });"
            "console.log(JSON.stringify([out]));" % items,
            names=["_histFilter", "_histItems", "SEARCH_MODES",
                   "histVisibleItems"],
            mode="learn")[0]
        assert got == {"all": 4, "review": 1, "case": 1, "learn": 2}

    def test_an_unknown_filter_falls_back_to_all(self):
        """Fail open here rather than closed: a bad filter value must not
        make a clinician's history look empty."""
        got = run_node(
            "_histItems = [{mode:'review'},{mode:'learn'}];"
            "_histFilter = 'nonesuch';"
            "console.log(JSON.stringify([histVisibleItems().length]));",
            names=["_histFilter", "_histItems", "SEARCH_MODES",
                   "histVisibleItems"])[0]
        assert got == 2

    def test_the_row_shows_what_tells_two_entries_apart(self):
        """A15f.2's two identical laser rows. The cache row has no cost on it,
        so the count goes out alone rather than beside an invented figure."""
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        assert "jsonb_array_length(papers)" in app
        assert '"paper_count": r[4] or 0,' in app
        assert "r.paper_count + ' papers'" in SRC
        assert "' hits'" not in SRC, "the cache statistic is back on the row"

    def test_the_landing_screen_no_longer_carries_a_recent_list(self):
        for gone in ("learnHistoryPanel", "learnHistoryVisible",
                     "loadLearnModeHistory", "HIST_VISIBLE"):
            assert gone not in SRC, "%s outlived the drawer" % gone


# ── RB — the progress clock ───────────────────────────────

class TestTheProgressClock:

    def test_it_formats_minutes_and_seconds(self):
        got = clock("console.log(JSON.stringify([[0,9,60,65,605]"
                    ".map(_fmtClock)]));")
        assert got == ["0:00", "0:09", "1:00", "1:05", "10:05"]

    def test_it_counts_down_towards_the_estimate(self):
        got = clock("_startEtaClock(); _now = 5000; _etaTick();"
                    "console.log(JSON.stringify([_eta.textContent]));")
        assert got == "elapsed 0:05 · about 10s left"

    def test_it_never_counts_past_zero(self):
        """The failure this replaces is a countdown that goes negative and
        turns a slow answer into an obviously broken page. Past the estimate
        it stops predicting and says only that it is still working."""
        got = clock("_startEtaClock(); _now = 26000; _etaTick();"
                    "console.log(JSON.stringify([[_eta.textContent, !!_eta._cls.over]]));")
        assert got == ["elapsed 0:26 · longer than usual — still working", True]
        assert "-" not in got[0].replace("—", "")

    def test_the_curriculum_does_not_get_a_countdown(self):
        """Measured curricula run from under a minute to $6.51-worth of them.
        A number here would be a promise the engine cannot keep."""
        got = clock("_startEtaClock(); _now = 90000; _etaTick();"
                    "console.log(JSON.stringify([_eta.textContent]));", mode="learn")
        assert got == "elapsed 1:30 · usually several minutes"
        assert "left" not in got

    def test_the_clock_and_the_promise_line_cannot_drift(self):
        """Both come off the same MODES row. If the copy says 15 seconds and
        the clock budgets 20, one of them is lying to the clinician."""
        cfg = run_node("console.log(JSON.stringify([MODES]));", names=["MODES"])[0]
        for m in SEARCH_MODES:
            said = re.search(r"about (\d+) seconds", cfg[m]["promiseWhen"])
            if said:
                assert cfg[m]["etaSeconds"] == int(said.group(1)), m
            else:
                assert cfg[m]["etaSeconds"] is None, (
                    "%s quotes no seconds but the clock counts them down" % m)

    def test_it_ticks_on_its_own_timer_rather_than_on_the_poll(self):
        """The whole point is "it is not stuck". A readout that only moves
        when a poll returns says nothing when the poll is what is stuck."""
        body = SRC[SRC.index("function _startEtaClock() {"):]
        body = body[:body.index("\n}")]
        assert "setInterval(_etaTick, 1000)" in body
        assert "_startEtaClock();" in SRC[SRC.index("function _startPollJob("):
                                          SRC.index("function _runSearch(")]

    def _dead(self, status, body, start_clock=False):
        """Drive one poll against a server that has forgotten the job."""
        return run_node(
            POLL_STUB +
            "_httpStatus = %d; _body = %s;" % (status, body) +
            ("_startEtaClock(); _now = 9000; _etaTick();" if start_clock else "") +
            "var _etaBefore = _eta.textContent;"
            "currentJob = 'gone'; pollTimer = 1;"
            "pollStatus('apicoectomy of mandibular teeth');"
            "setTimeout(function () {"
            "  console.log(JSON.stringify([{cleared: _cleared, job: currentJob,"
            "    card: _el('progressCard').style.display, eta: _eta.textContent,"
            "    eta_before: _etaBefore,"
            "    err: _lastError, asked: _el('askBtn').disabled}]));"
            "}, 10);",
            names=POLL_FNS, preamble=DOM_STUB)[0]

    def test_a_forgotten_job_is_terminal_not_slow(self):
        """Found live, and the worst kind of finding: a curriculum sat at
        "elapsed 27:34 · usually several minutes" with the spinner turning,
        while every poll behind it came back 404 because the dev server had
        restarted and taken the jobs table with it.

        `/status` answers 404 with `{"error": ...}` and no `status`, so none
        of pollStatus's terminal branches fired and `.catch(){}` ate the rest.
        The clock then made the page look MORE alive the longer it had been
        dead — the exact inverse of why it was added, and §7.2's fail-open
        gate wearing a different hat."""
        got = self._dead(status=404, body="{}")
        assert got["cleared"] is True, "the poll kept running against a dead job"
        assert got["job"] is None
        assert got["card"] == "none"
        assert got["asked"] is False, "the clinician could not ask again"
        assert "no longer running" in got["err"]
        assert "apicoectomy of mandibular teeth" in got["err"], (
            "the message does not say what to re-ask")

    def test_the_clock_stops_with_it(self):
        """Asserted with the clock actually RUNNING. Reading an empty readout
        off a clock that was never started is the vacuous assertion standing
        rule 4 is about — and it passed a mutant that deleted the stop."""
        got = self._dead(status=404, body="{}", start_clock=True)
        assert got["eta_before"], "the clock was not running, so this proves nothing"
        assert got["eta"] == "", "the clock kept counting on a job nobody was running"

    def test_an_error_body_with_no_status_is_terminal_too(self):
        """Belt and braces, tested separately from the 404. Together they
        cover for each other, which is good code and a bad test: each mutant
        survived while only one case was exercised."""
        got = self._dead(status=200, body='{"error": "Job not found"}')
        assert got["cleared"] is True
        assert got["job"] is None
        assert "no longer running" in got["err"]

    def test_one_dropped_poll_is_not_a_dead_job(self):
        """The counterpart, and the reason this is not simply "give up on any
        failure": networks blip, and tearing down a live 20-minute curriculum
        because one poll timed out would be worse than the bug it fixes."""
        got = run_node(
            POLL_STUB +
            "_throwOnFetch = true;"
            "currentJob = 'alive'; pollTimer = 1;"
            "for (var i = 0; i < 5; i++) pollStatus('q');"
            "setTimeout(function () {"
            "  console.log(JSON.stringify([{cleared: _cleared, job: currentJob,"
            "                               misses: _pollMisses}]));"
            "}, 10);",
            names=POLL_FNS, preamble=DOM_STUB)[0]
        assert got["cleared"] is False, "five blips tore down a live job"
        assert got["job"] == "alive"
        assert got["misses"] == 5

    def test_it_stops_itself_when_the_card_goes_away(self):
        """Six paths hide the progress card. The ticker checks the card rather
        than trusting each of them to remember a stop call."""
        body = SRC[SRC.index("function _etaTick() {"):]
        body = body[:body.index("\n}")]
        assert "card.style.display === 'none'" in body
        assert "_stopEtaClock()" in body

# ── setMode, executed ─────────────────────────────────────

# `setMode` is the function under test here, not a description of it. The stub
# is deliberately dumb: any id or selector returns a fresh element, so the test
# cannot accidentally depend on the page's structure.
SHELL_STUB = """
var _els = {};
function _el(id) {
  if (!_els[id]) _els[id] = {
    id: id, style: {}, textContent: '', title: '', innerHTML: '',
    classList: { _s: {},
      toggle: function (c, on) { this._s[c] = on === undefined ? !this._s[c] : !!on; },
      add: function (c) { this._s[c] = true; },
      remove: function (c) { this._s[c] = false; },
      contains: function (c) { return !!this._s[c]; } },
    setAttribute: function (k, v) { this[k] = v; },
    querySelector: function () { return null; },
    closest: function () { return _el('inputCard'); }
  };
  return _els[id];
}
var document = {
  getElementById: _el,
  querySelector: function (sel) { return _el(sel); },
  querySelectorAll: function () { return []; },
  body: { classList: { toggle: function () {} } }
};
var currentJob = null;
var caseMessages = [];
function dismissModeSuggestion() {}
function closeHistDrawer() {}
"""

SHELL_FNS = ["MODES", "SEARCH_MODES", "modeShows", "_show",
             # A16d — `setMode` calls `_syncCaseLanding` after the landing
             # decision, so an open case thread cannot resurrect the landing
             # column that would starve it. Both helpers are dependencies of
             # `setMode` now; leaving them out is the exact drift the
             # `js_harness` docstring describes, and it turned this file red.
             "_caseThreadOpen", "_syncCaseLanding",
             "setMode", "setLandingVisible", "renderWhatCards"]


class TestSetModeActuallyRunsThePredicate:
    """Standing rule 14. The sibling test in `test_mode_shell.py` greps
    `setMode` for the predicate's name, and a mutant that kept the name in one
    call while dropping it from the visibility decision survived that grep.
    These RUN the function and read the elements it touched."""

    def _run(self, js):
        return run_node(js, names=SHELL_FNS, preamble=SHELL_STUB)[0]

    def test_the_landing_screen_follows_the_predicate_in_every_mode(self):
        got = self._run(
            "var out = {};"
            "['review','case','learn','assess','profile'].forEach(function (m) {"
            "  setMode(m);"
            "  out[m] = { want: modeShows(m, 'welcome'),"
            "             cards: _el('welcomeSection').style.display !== 'none',"
            "             lockup: _el('lockup').style.display !== 'none' }; });"
            "console.log(JSON.stringify([out]));")
        for m, r in got.items():
            assert r["cards"] is r["want"], (
                "%s: the cards ignore modeShows(m,'welcome')" % m)
            assert r["lockup"] is r["want"], (
                "%s: the lockup and the cards came apart" % m)

    def test_a_running_job_hides_the_landing_screen_in_every_mode(self):
        """The second half of the condition. A mutant keeping only the
        predicate would leave the cards sitting under a live progress bar."""
        got = self._run(
            "currentJob = 'job-1';"
            "var out = {};"
            "['review','case','learn'].forEach(function (m) {"
            "  setMode(m);"
            "  out[m] = _el('welcomeSection').style.display; });"
            "console.log(JSON.stringify([out]));")
        assert set(got.values()) == {"none"}, got

    def test_the_composer_carries_the_active_mode_accent(self):
        """A19c — one border colour per mode, and the icon-only submit keeps
        the mode's verb as its accessible name."""
        got = self._run(
            "var out = {};"
            "SEARCH_MODES.forEach(function (m) {"
            "  setMode(m);"
            "  out[m] = { card: _el('inputCard').classList.contains('m-' + m),"
            "             ask: _el('askBtn')['aria-label'],"
            "             tall: _el('qInput').classList.contains('mode-case-input') };});"
            "console.log(JSON.stringify([out]));")
        assert [got[m]["card"] for m in SEARCH_MODES] == [True, True, True]
        assert [got[m]["ask"] for m in SEARCH_MODES] == \
            ["Search literature", "Start case", "Build curriculum"]
        assert [got[m]["tall"] for m in SEARCH_MODES] == [False, True, False]
