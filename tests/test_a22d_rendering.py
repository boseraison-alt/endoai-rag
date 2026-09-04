"""A22d and A22a's renderer half — measured in the running app, then pinned.

Every number in this file was read off the LAID-OUT page on the stored
apicoectomy curriculum, which is the document A22 was written from and a demo
surface. None of it is visible to an assertion on markup or on served JSON.

  literal `*` on screen                  90  ->  0
  literal `**` on screen                  3  ->  0
  uncited marks ending mid-word         7/9  ->  0
  uncited-mark contrast, inside a block  1.02:1  ->  13.34:1
  uncited-mark contrast, outside one     6.54-10.52:1 (unchanged)

The 1.02:1 is the one that matters: near-white `#eef2fa`, inherited from the
dark quarantine block, on this element's own pale amber ground. Six of ten
marks on that curriculum were literally invisible, and outside a block the same
marks were fine — which is why nothing caught it.
"""
import json
from pathlib import Path

import pytest

from tests.js_harness import RENDER_DEPS, run_node

INDEX_HTML = Path(__file__).parent.parent / "templates" / "index.html"


class TestSingleAsteriskEmphasis:
    """`renderAnswer` handled `**bold**` and had NO rule for `*italic*`, so
    every single asterisk in the corpus rendered literally."""

    def _render(self, text):
        html, = run_node("console.log(JSON.stringify([renderAnswer(%s)]));"
                         % json.dumps(text))
        return html

    def test_single_asterisks_become_emphasis(self):
        html = self._render("Teeth linked to odontogenic cysts were *vital*, "
                            "meaning treatment would not have helped.")
        assert "<em>vital</em>" in html, html
        assert "*" not in html

    def test_the_legend_no_longer_shows_its_own_asterisks(self):
        """The legend Curo writes itself contains `*NOT CHECKED*`."""
        html = self._render(
            "> **NOT CHECKED** — passages marked ° below, and the blocks "
            "headed *NOT CHECKED*, are general clinical practice.")
        assert "*NOT CHECKED*" not in html
        assert "<em>NOT CHECKED</em>" in html

    def test_a_list_bullet_does_not_open_an_italic(self):
        """`* item` is a bullet, and `(?!\\s)` is what stops it opening a run.

        Bullets on SEPARATE lines prove nothing here — `[^*\\n]` already blocks
        a match across the newline, so that version of this test passed with
        the guard removed. Two markers on ONE line is the case the guard is
        for, and it is what the mutant has to survive.
        """
        html = self._render("* first item * second item")
        assert "<em>" not in html, html
        html = self._render("* first item\n* second item\n")
        assert "<em>" not in html, html

    def test_emphasis_never_spans_a_paragraph(self):
        html = self._render("An *unclosed run here\n\nand a later * asterisk.")
        assert "<em>" not in html, html

    def test_bold_still_wins(self):
        html = self._render("A **bold phrase** and an *italic* one.")
        assert "<strong>bold phrase</strong>" in html
        assert "<em>italic</em>" in html


class TestTheUncitedMarkIsReadableAnywhere:

    def test_the_mark_does_not_inherit_its_colour(self):
        """`color: inherit` is what put near-white text on pale amber.

        Asserted on the stylesheet because the computed-contrast version lives
        in the Playwright test below; this one states the cause, so a revert is
        legible in the diff rather than only in a rendered ratio.
        """
        css = INDEX_HTML.read_text(encoding="utf-8")
        block = css.split(".uncited-claim {", 1)[1].split("}", 1)[0]
        assert "color: inherit" not in block, (
            "the uncited mark inherits its colour again - inside the dark "
            "quarantine block that renders at 1.02:1 and is unreadable")
        assert "color:" in block

    def test_the_highlight_does_not_end_mid_word(self):
        """The probe is a 60-character PREFIX, so it lands mid-word about half
        the time; the highlight extends to the end of that word."""
        answer = (
            "It found no evidence of a difference between single- and "
            "multiple-visit regimens for tooth extraction.\n\n"
            '> - "It found no evidence of a difference between single- and '
            'multiple-visit regimens for tooth extraction."\n')
        html, = run_node(
            "console.log(JSON.stringify([markUncitedClaims(renderAnswer(%s),"
            " _uncitedClaimQuotes(%s))]));" % (json.dumps(answer),
                                               json.dumps(answer)),
            names=RENDER_DEPS)
        assert "<mark" in html, html
        marked = html.split('class="uncited-claim"', 1)[1].split(">", 1)[1]
        marked = marked.split("</mark>", 1)[0]
        assert marked.endswith("multiple-visit"), (
            "the highlight still stops mid-word: %r" % marked[-30:])


class TestInvariant3InsideAQuarantineBlock:
    """No raw `[[PMID:N]]` on ANY rendered surface — the block is a surface.

    The block is stashed out of `renderAnswer` before the marker replacer runs
    and re-inserted after it, so its contents were formatted by
    `_unverifiedInline` alone, which knew nothing about citations. MEASURED on
    the stored apicoectomy curriculum: one block carrying **30 raw markers**,
    printed as `[[PMID:20630283]]` in the page text.

    It stayed invisible until the legacy header's `⚠ ` prefix was made optional
    (rule 17) and that block began to be recognised at all — so the two changes
    in this file found each other.
    """

    BLOCK_WITH_MARKERS = (
        "> **NOT FROM THE EVIDENCE BASE — UNVERIFIED**\n"
        ">\n"
        "> MTA is the retrograde material of choice [[PMID:20630283]] and "
        "CBCT helps mapping [[PMID:30818321]].\n"
        ">\n"
        "> **Consult directly:** the specialty guidelines — Curo has not "
        "checked them.\n"
        "\nOrdinary prose with a marker [[PMID:36512807]].\n")

    def test_no_raw_marker_survives_inside_a_block(self):
        html, = run_node("console.log(JSON.stringify([renderAnswer(%s)]));"
                         % json.dumps(self.BLOCK_WITH_MARKERS),
                         names=RENDER_DEPS)
        assert "[[" not in html, (
            "a raw marker survived inside the quarantine block: %s"
            % html[html.find("[["):][:80])

    def test_the_markers_became_pills_on_both_sides_of_the_block(self):
        html, = run_node("console.log(JSON.stringify([renderAnswer(%s)]));"
                         % json.dumps(self.BLOCK_WITH_MARKERS),
                         names=RENDER_DEPS)
        assert html.count('class="claim-cite"') == 3, html
        assert html.count("unverified-block") == 1, (
            "the block itself was lost while fixing its citations")


class TestTheLegacyHeaderVariant:
    """Rule 17 — 114 stored blocks carry the `⚠ ` prefix and 2 do not."""

    BARE = ("> **NOT FROM THE EVIDENCE BASE — UNVERIFIED**\n"
            ">\n"
            "> Epinephrine is used for haemostasis — standard practice, not "
            "from the retrieved evidence base.\n"
            ">\n"
            "> **Consult directly:** the specialty guidelines for this "
            "question — Curo has not retrieved or checked them.\n")

    def test_python_matches_a_header_with_no_warning_sign(self):
        import endo_ai as e
        assert e._LEGACY_QUARANTINE_BLOCK_RE.search(self.BARE), (
            "a bare-header block is invisible to every legacy-block reader, "
            "so it renders as ordinary prose with no warning at all")

    def test_python_still_matches_the_common_shape(self):
        import endo_ai as e
        assert e._LEGACY_QUARANTINE_BLOCK_RE.search(
            self.BARE.replace("> **NOT FROM", "> ⚠ **NOT FROM"))

    @pytest.mark.parametrize("prefix", ["", "⚠ "])
    def test_the_browser_matches_both_shapes(self, prefix):
        text = self.BARE.replace("> **NOT FROM", "> %s**NOT FROM" % prefix)
        html, = run_node("console.log(JSON.stringify([renderAnswer(%s)]));"
                         % json.dumps(text))
        assert 'class="unverified-block"' in html, (
            "prefix=%r rendered as ordinary blockquote prose" % prefix)
