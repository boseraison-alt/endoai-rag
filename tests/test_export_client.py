"""
The browser half of the export-source fix.

tests/test_export_source.py proves the SERVER accepts a client-supplied
answer. That is only half the bug: the other half was that the page never
sent one, and left `currentJob` pointing at a previous live question after
loading a history item — which is how an export could narrate a different
answer than the one on screen.

These run the real JavaScript out of templates/index.html under node, the
same technique tests/test_streaming.py uses, because the behaviour lives in
that file and asserting on a Python re-implementation would prove nothing.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

INDEX_HTML = Path(__file__).parent.parent / "templates" / "index.html"


def _extract_function(name):
    """Pull one top-level `function name(...) {...}` out of index.html by
    brace-matching. Regex alone cannot find the closing brace of a function
    containing nested braces, template strings and object literals."""
    src = INDEX_HTML.read_text(encoding="utf-8")
    m = re.search(r"^function\s+" + re.escape(name) + r"\s*\(", src, re.MULTILINE)
    if not m:
        raise AssertionError(f"function {name} not found in index.html")
    i = src.index("{", m.end())
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1]
        j += 1
    raise AssertionError(f"unbalanced braces in {name}")


def _run_node(js):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available — cannot exercise the shipped JS")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(js)
        path = f.name
    try:
        r = subprocess.run([node, path], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()
    finally:
        Path(path).unlink(missing_ok=True)


# A DOM stub just wide enough for the functions under test.
HARNESS = """
var _els = {};
function _el(id) {
  if (!_els[id]) _els[id] = {id: id, textContent: '', value: '', style: {},
                             classList: {add: function(){}, toggle: function(){}},
                             dataset: {}};
  return _els[id];
}
var document = {
  getElementById: _el,
  querySelectorAll: function(){ return []; },
  querySelector: function(){ return null; },
};
// The export payloads read window._lastJob for the paper list that feeds the
// evidence-shape card; node has no window.
var window = {_lastJob: {papers: [{pmid: "1", level_key: "level1"}]}};
var _fetches = [];
function fetch(url, opts) {
  _fetches.push({url: url, body: opts && opts.body ? JSON.parse(opts.body) : null});
  return { then: function(){ return this; }, catch: function(){ return this; } };
}
// Stubs for everything startExport touches on its way to the fetch.
function _hideAudioPlayer(){} function _lockExportBtns(){} function _showPhaseBar(){}
function _hidePhaseBar(){} function showDentalAnim(){} function hideDentalAnim(){}
function pollAudioJob(){} function setMode(){} function showResult(){}
function escHtml(s){ return s; } function _markHistoryGone(){}
var _exportDuration = 5, _exportVoice = 'onyx', _exportStyle = 'lecture';
var _currentExportId = null, currentJob = null, _exportSource = null;
"""


class TestExportRequestCarriesDisplayedAnswer:

    def _js(self, body):
        return (HARNESS
                + _extract_function("startExport") + "\n"
                + _extract_function("_startAudioExport") + "\n"
                + _extract_function("_startVideoExport") + "\n"
                + _extract_function("_startSlidesExport") + "\n"
                + body)

    def test_audio_export_sends_the_displayed_answer(self):
        out = _run_node(self._js("""
            _exportSource = {question: 'Q on screen', answer: 'A on screen'};
            currentJob = null;
            _exportStyle = 'lecture';
            startExport();
            console.log(JSON.stringify(_fetches[0].body));
        """))
        import json
        body = json.loads(out)
        assert body["answer"] == "A on screen"
        assert body["question"] == "Q on screen"

    @pytest.mark.parametrize("style,url", [
        ("lecture", "/generate_audio"),
        ("conversation", "/generate_audio"),
        ("video", "/generate_video"),
        ("slides", "/generate_slides"),
    ])
    def test_every_export_type_sends_it(self, style, url):
        """All three endpoints had the same bug, so all three must send it."""
        out = _run_node(self._js(f"""
            _exportSource = {{question: 'Q', answer: 'A on screen'}};
            currentJob = null;
            _exportStyle = '{style}';
            startExport();
            console.log(JSON.stringify({{url: _fetches[0].url,
                                         answer: _fetches[0].body.answer}}));
        """))
        import json
        got = json.loads(out)
        assert got["url"] == url
        assert got["answer"] == "A on screen"

    def test_export_is_allowed_with_no_live_job(self):
        """The history-loaded case: before the fix this printed
        'No answer to export.' and never issued a request."""
        out = _run_node(self._js("""
            _exportSource = {question: 'Q', answer: 'A'};
            currentJob = null;
            startExport();
            console.log(JSON.stringify({n: _fetches.length,
                                        status: document.getElementById('exportStatus').textContent}));
        """))
        import json
        got = json.loads(out)
        assert got["n"] == 1, "no export request was issued"
        assert got["status"] != "No answer to export."

    def test_export_is_still_refused_with_nothing_on_screen(self):
        """The guard must not have been loosened into meaninglessness."""
        out = _run_node(self._js("""
            _exportSource = null; currentJob = null;
            startExport();
            console.log(JSON.stringify({n: _fetches.length,
                                        status: document.getElementById('exportStatus').textContent}));
        """))
        import json
        got = json.loads(out)
        assert got["n"] == 0
        assert got["status"] == "No answer to export."


class TestHistoryLoadClearsStaleJob:
    """The wrong-answer failure mode. With a stale currentJob set, the server
    prefers that job and narrates an answer the user is not looking at."""

    def test_loadHistoryItem_nulls_currentjob_before_rendering(self):
        src = _extract_function("loadHistoryItem")
        assert "currentJob = null" in src, (
            "loadHistoryItem must clear currentJob, or an export will prefer "
            "the previous live job server-side and narrate the wrong answer")
        # Ordering matters: clearing it after showResult would leave a window.
        assert src.index("currentJob = null") < src.index("showResult("), \
            "currentJob must be cleared BEFORE the answer is rendered"

    def test_showresult_captures_the_export_source(self):
        src = _extract_function("showResult")
        assert "_exportSource" in src, (
            "showResult must record the rendered answer as the export source")


# Every function that renders a stored answer into the answer card. The
# Review-mode loader goes through showResult(); the Deep Learning one renders
# the card itself, which is exactly how it kept the bug after loadHistoryItem
# was fixed — the export bar said "No answer to export." on every Deep
# Learning report opened from history.
#
# Parametrised deliberately: a fourth loader added later joins this list and
# inherits both assertions, rather than quietly shipping the same defect a
# third time.
HISTORY_LOADERS = ["loadHistoryItem", "openLearnHistoryItem"]


class TestEveryHistoryLoaderArmsTheExportBar:

    @pytest.mark.parametrize("fn", HISTORY_LOADERS)
    def test_loader_arms_the_export_source(self, fn):
        """Either directly, or by delegating to showResult() which does it.
        Both are fine; rendering the card yourself and doing NEITHER is the
        bug."""
        src = _extract_function(fn)
        arms = "_exportSource" in src or "showResult(" in src
        assert arms, (
            f"{fn} renders an answer but neither sets _exportSource nor goes "
            f"through showResult, so every export from it reports 'No answer "
            f"to export.'")

    @pytest.mark.parametrize("fn", HISTORY_LOADERS)
    def test_loader_clears_any_stale_live_job(self, fn):
        """A leftover currentJob outranks the displayed answer server-side and
        exports the previous question instead."""
        src = _extract_function(fn)
        assert "currentJob = null" in src, (
            f"{fn} must clear currentJob or an export may narrate the wrong "
            f"answer")
