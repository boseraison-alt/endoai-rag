"""
A copied answer keeps its citations (`case-v3` Item A).

THE DEFECT, measured on a real two-turn case conversation in the user's own
browser before anything was changed:

  citations rendered on screen   34
  citations in the copied text    0
  characters shown            18,045
  characters copied           17,609   (the 436-char difference IS the citations)

`.claim-cite` carried `user-select: none`, so a native browser selection
skipped every citation. Text pasted into a note or an email carried the
clinical claims and none of the evidence — and every claim then looked
uncited, which is how this item started.

Two changes, and the tests below cover both halves because either alone leaves
a hole:

  1. `user-select: none` is gone, so the citation is part of the selection;
  2. a `copy` listener rewrites each citation in the CLIPBOARD ONLY to the
     short form ` [PMID N]`. The on-screen pill still reads "Sjögren U et al.,
     J Endod., 1990;16(10):498-504", which is right for reading and far too
     long inline in a pasted paragraph.

The structural half runs in the normal suite. The browser half is opt-in via
RUN_BROWSER_TESTS=1, the same convention `tests/test_webdeck.py` uses.
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

TEMPLATE = Path(__file__).parent.parent / "templates" / "index.html"


@pytest.fixture(scope="module")
def html():
    return TEMPLATE.read_text(encoding="utf-8")


class TestTheStylesheetDoesNotHideCitationsFromASelection:

    @staticmethod
    def _block(html):
        """The `.claim-cite` declarations, with CSS comments removed.

        The comments matter: the rule now carries a long note explaining why
        `user-select: none` was taken out, and a naive substring search finds
        the words inside its own tombstone. Strip comments, then look for a
        DECLARATION.
        """
        block = re.search(r"\.claim-cite\s*\{(.*?)\}", html, re.S)
        assert block, ".claim-cite rule not found"
        return re.sub(r"/\*.*?\*/", "", block.group(1), flags=re.S)

    def test_claim_cite_does_not_set_user_select(self, html):
        """The whole defect, in one declaration. Asserted on the `.claim-cite`
        block specifically rather than on the file, because `user-select: none`
        is legitimate elsewhere (buttons, chips)."""
        decls = self._block(html)
        assert not re.search(r"user-select\s*:", decls), (
            "`.claim-cite` sets user-select again — a copied answer will lose "
            "every citation, which is how this item started")

    def test_the_rule_still_styles_the_pill(self, html):
        """Removing the wrong declaration must not have removed the rule."""
        decls = self._block(html)
        for prop in ("background", "border", "font-size", "cursor"):
            assert prop in decls, f".claim-cite lost {prop}"


class TestTheCopyHandlerExists:

    def test_a_copy_listener_is_registered(self, html):
        assert "addEventListener('copy'" in html

    def test_it_rewrites_to_the_short_form(self, html):
        handler = html.split("addEventListener('copy'")[1][:1600]
        assert "[PMID " in handler, "the clipboard form is not [PMID N]"
        assert "claim-cite" in handler

    def test_it_reads_the_range_rather_than_the_selection_string(self, html):
        """`getSelection().toString()` applies `user-select`; `cloneContents()`
        is DOM-level and does not. Building from the range is what makes the
        handler correct whether or not the stylesheet cooperates — belt and
        braces, deliberately."""
        handler = html.split("addEventListener('copy'")[1][:1600]
        assert "cloneContents()" in handler

    def test_it_sets_both_plain_and_html_flavours(self, html):
        handler = html.split("addEventListener('copy'")[1][:1600]
        assert "'text/plain'" in handler and "'text/html'" in handler

    def test_a_throwing_handler_does_not_break_copy(self, html):
        """A copy that raises must still copy. The catch leaves the browser's
        own behaviour in place, which is correct now that the CSS is fixed."""
        handler = html.split("addEventListener('copy'")[1][:1600]
        assert "catch" in handler

    def test_it_leaves_a_selection_with_no_citations_alone(self, html):
        """No citations in the selection means nothing to rewrite, and
        preventDefault on an ordinary copy would be a regression for every
        other piece of text on the page."""
        handler = html.split("addEventListener('copy'")[1][:1600]
        assert "querySelector('.claim-cite')" in handler
        assert "return" in handler.split("querySelector('.claim-cite')")[1][:120]


# ── the browser half ──────────────────────────────────────

@pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1",
                    reason="set RUN_BROWSER_TESTS=1 to run the Playwright half")
class TestInTheBrowser:
    """Renders a real marker through the page's OWN `renderAnswer`, then fires
    a real `copy` event and reads what the handler put on the clipboard."""

    @pytest.fixture(scope="class")
    def page(self):
        pw = pytest.importorskip("playwright.sync_api")
        import app as app_mod
        rendered = app_mod.app.test_client().get("/").data.decode("utf-8")
        with pw.sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1280, "height": 900})
            pg.set_content(rendered)
            pg.wait_for_timeout(400)
            yield pg
            pg.close()
            b.close()

    PROBE = """
      setCitationMeta([{pmid:'2084204', authors:'Sjogren U, Hagglund B',
                        journal_abbrev:'J Endod', year:'1990',
                        volume:'16', issue:'10', pages:'498-504'}]);
      var host = document.createElement('div');
      host.id = 'probe';
      host.innerHTML = renderAnswer(
        'Success rates exceed 86% for necrotic teeth [[PMID:2084204]].');
      document.body.appendChild(host);
    """

    def test_the_pill_still_renders_and_is_clickable(self, page):
        page.evaluate(self.PROBE)
        got = page.evaluate("""() => {
          const c = document.querySelector('#probe .claim-cite');
          return {text: c && c.textContent,
                  click: c && !!c.getAttribute('onclick'),
                  sel: c && getComputedStyle(c).userSelect};
        }""")
        assert got["click"] is True
        assert "Sjogren" in (got["text"] or "")
        assert got["sel"] != "none"

    def test_the_clipboard_carries_a_short_form_citation(self, page):
        page.evaluate(self.PROBE)
        got = page.evaluate("""() => {
          const host = document.getElementById('probe');
          const sel = window.getSelection();
          sel.removeAllRanges();
          const r = document.createRange();
          r.selectNodeContents(host);
          sel.addRange(r);
          const dt = new DataTransfer();
          document.dispatchEvent(new ClipboardEvent(
            'copy', {clipboardData: dt, bubbles: true, cancelable: true}));
          sel.removeAllRanges();
          return dt.getData('text/plain');
        }""")
        assert "[PMID 2084204]" in got, (
            f"the copied text lost its citation: {got!r}")
        assert "Success rates exceed 86%" in got
        assert "J Endod" not in got, (
            "the long author-style form was pasted inline; the clipboard "
            "should carry the short form")
