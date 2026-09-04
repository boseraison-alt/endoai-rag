"""A16d — the Case thread must actually have height.

WHAT WAS MEASURED, in the browser on `ae20d3e`, before the fix. A case turn was
submitted from the main bar; `POST /case_chat` returned **200**; nothing
appeared on screen. The whole conversation was in the DOM at ZERO height:

    .chat-container            h = 0      (flex:1 1 0; min-height:0; overflow:auto)
      .chat-bubble user        h = 115
      .chat-bubble assistant   h = 241
    .case-section.active       h = 11
    .content                   h = 623

…because the landing column was still standing underneath it:

    #lockup 188 + #inputCard 198 + #welcomeSection 125 + #modePromise 20 = 531

Case mode is the one mode whose thread does not scroll the page — the
`.content-scroll:has(#caseSection.active)` rule makes `.content` a column flex
box and gives `.case-section.active` `flex:1; min-height:0`. A landing column
left standing therefore does not OVERLAP the thread, it STARVES it. Nothing
errors, so nothing anywhere reports it.

`submitQuestion`'s case branch called `sendCaseMessage()` and returned, never
taking the landing down. Before A15 the only way into `sendCaseMessage` was the
thread's own send button, reached after `setMode` had already laid the page out;
A15 made the main bar a second entry point and that path skipped the teardown.

WHY THIS FILE USES A REAL BROWSER. The defect is a flex-layout starvation. No
assertion on markup, on classes or on the served JSON can see it — the DOM was
correct and complete the whole time. `templates/index.html` has zero Jinja
constructs, so it loads straight into Chromium with no server and no database.

Each test below drives the SHIPPED functions (`setMode`, `sendCaseMessage`) and
measures the laid-out box, which is the thing that was wrong.
"""
from pathlib import Path

import pytest

INDEX_HTML = Path(__file__).parent.parent / "templates" / "index.html"

pytest.importorskip("playwright.sync_api",
                    reason="playwright not installed - cannot lay the page out")

from playwright.sync_api import sync_playwright  # noqa: E402


# The viewport the defect was measured at. A tall enough window would hide it:
# the landing's 531px only starves the thread when it is most of the height.
VIEWPORT = {"width": 1280, "height": 720}


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser):
    """A FRESH page per test, with every network call stubbed out.

    Function-scoped deliberately. `setLandingVisible` and `setMode` write
    inline styles that outlive a test, so a shared page makes these tests
    order-dependent — and it hid the real defect state once already: the
    "reproduce the starvation" check below measured 180px instead of 0
    because an earlier test had already hidden the lockup by hand.

    The page fires `/history`, `/api/profile`, `/api/settings`, `/api/media`
    and `/learn_history` on load. They are fulfilled with `{}` rather than
    allowed to fail, because an unhandled rejection mid-boot would leave
    `setMode` undefined and every test here would fail for the wrong reason.
    """
    pg = browser.new_page(viewport=VIEWPORT)
    pg.route("**/*", lambda route: route.fulfill(
        status=200, content_type="application/json", body="{}"))
    pg.set_content(INDEX_HTML.read_text(encoding="utf-8"),
                   wait_until="domcontentloaded")
    pg.wait_for_function("typeof setMode === 'function'")
    yield pg
    pg.close()


def _open_thread(page):
    """Drive the SHIPPED path that was broken: the main bar in Case mode.

    Only `_postCaseChat` is stubbed — it is the network call. Everything the
    defect lived in (`caseMessages.push`, the composer swap, `_syncCaseLanding`)
    is the real function.
    """
    page.evaluate("""() => {
        setMode('case');
        _postCaseChat = function () {};
        document.getElementById('qInput').value = 'Tooth 36 hurts.';
        submitQuestion();
    }""")


def _boxes(page):
    return page.evaluate("""() => {
        const h = s => { const e = document.querySelector(s);
                         return e ? Math.round(e.getBoundingClientRect().height) : -1; };
        return {
            chat:    h('.chat-container'),
            section: h('.case-section'),
            lockup:  h('#lockup'),
            input:   h('#inputCard'),
            welcome: h('#welcomeSection'),
            promise: h('#modePromise'),
            chips:   h('.mode-chips'),
            qinput:  h('#qInput'),
            bodyCls: document.body.className,
        };
    }""")


class TestCaseThreadHasHeight:

    def test_thread_is_not_starved_by_the_landing_column(self, page):
        """The assertion the defect would have failed: chat-container > 0."""
        _open_thread(page)
        b = _boxes(page)
        assert b["chat"] > 200, (
            "the case thread laid out at %dpx - the landing column is still "
            "standing (lockup=%d input=%d welcome=%d promise=%d)"
            % (b["chat"], b["lockup"], b["input"], b["welcome"], b["promise"]))
        assert b["section"] > 400, b

    def test_the_landing_column_is_down(self, page):
        _open_thread(page)
        b = _boxes(page)
        assert b["lockup"] == 0, b
        assert b["welcome"] == 0, b
        assert b["promise"] == 0, b
        assert b["qinput"] == 0, "the main textarea is still taking height"

    def test_the_way_out_of_the_thread_survives(self, page):
        """The mode chips live INSIDE #inputCard (A19 moved them there).

        Hiding the whole card takes the thread's height back but leaves the
        clinician with no route to Literature or Curriculum. This is the
        regression the first attempt at the fix introduced, so it is pinned.
        """
        _open_thread(page)
        b = _boxes(page)
        assert b["chips"] > 0, "the mode chips went with the input card"
        assert b["input"] > 0 and b["input"] < 90, (
            "the card should survive as a slim mode switcher, got %dpx"
            % b["input"])
        for chip in ("tabReview", "tabCase", "tabLearn"):
            assert page.evaluate(
                "id => document.getElementById(id).getBoundingClientRect().height > 0",
                chip), "%s is not clickable" % chip

    def test_the_class_is_what_does_it(self, page):
        """Rule 4 — the pair that fails when the assertion above goes vacuous.

        If `.chat-container` were tall for some unrelated reason, every test
        above would pass against a broken fix. Removing the class must put the
        page back into the measured defect state.
        """
        _open_thread(page)
        assert _boxes(page)["chat"] > 200
        # Exactly the pre-A16d state: the class absent and the landing column
        # left standing, which is what `setMode('case')` alone produces.
        page.evaluate("""() => {
            document.body.classList.remove('case-thread-open');
            setLandingVisible(true);
        }""")
        b = _boxes(page)
        assert b["chat"] < 50, (
            "removing `case-thread-open` did not reproduce the starvation, so "
            "the tests above are not measuring the fix: %s" % b)
        assert b["lockup"] + b["input"] + b["welcome"] + b["promise"] > 450, (
            "the landing column did not come back, so this is not the defect "
            "state: %s" % b)
        page.evaluate("() => _syncCaseLanding()")
        assert _boxes(page)["chat"] > 200, "the sync did not put it back"


class TestSymmetry:

    def test_leaving_case_mode_restores_the_landing(self, page):
        """`setMode` restores #inputCard and `setLandingVisible` restores the
        lockup, but NOTHING restores #modePromise — which is why the hide is a
        class and not four inline `display:none`s. If it ever goes back to
        inline styles, this is the test that catches it."""
        _open_thread(page)
        assert _boxes(page)["promise"] == 0
        page.evaluate("() => setMode('review')")
        b = _boxes(page)
        assert "case-thread-open" not in b["bodyCls"], b["bodyCls"]
        assert b["lockup"] > 0, b
        assert b["welcome"] > 0, b
        assert b["promise"] > 0, "modePromise stayed hidden - the leak is back"
        assert b["qinput"] > 0, "the main textarea did not come back"

    def test_re_entering_case_with_an_open_thread_does_not_resurrect_it(self, page):
        """`setMode('case')` calls `setLandingVisible(modeShows(m,'welcome'))`,
        which is true for case mode. Without `_syncCaseLanding` running after
        it, coming back from Literature would starve the thread again."""
        _open_thread(page)
        page.evaluate("() => setMode('review')")
        page.evaluate("() => setMode('case')")
        b = _boxes(page)
        assert "case-thread-open" in b["bodyCls"], b["bodyCls"]
        assert b["chat"] > 200, b
        assert b["lockup"] == 0, b


class TestPredicate:

    def test_thread_open_is_mode_and_messages(self, page):
        """`_caseThreadOpen` is the whole decision; both halves are load-bearing."""
        page.evaluate("() => { setMode('case'); caseMessages = []; }")
        assert page.evaluate("() => _caseThreadOpen()") is False
        page.evaluate("() => { caseMessages = [{role:'user', content:'x'}]; }")
        assert page.evaluate("() => _caseThreadOpen()") is True
        page.evaluate("() => setMode('review')")
        assert page.evaluate("() => _caseThreadOpen()") is False, (
            "a review-mode page with a stale caseMessages must not be 'open'")
