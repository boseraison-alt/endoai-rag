"""A44b — the curriculum table of contents.

MEASURED on the stored apicoectomy curriculum, in the browser: **26,107px** of
laid-out body and **32 headings**, reachable only by scrolling. A ~12,000-word
teaching document is the one thing in this product nobody reads top-to-bottom.

Verified in the running app at three widths before these tests were written:

    1440px   TOC visible, position: sticky, 32 links (13 h2 + 19 h3),
             32 headings given ids, exactly 1 active link,
             clicking the third entry scrolled the overlay 0 -> 434px
    1024px   display: none
     768px   display: none

The width behaviour is a media query, so it needs a real layout engine; the
structural half runs on `buildCurriculumToc` directly.
"""
import json
from pathlib import Path

import pytest

INDEX_HTML = Path(__file__).parent.parent / "templates" / "index.html"

pytest.importorskip("playwright.sync_api",
                    reason="playwright not installed - cannot lay the page out")

from playwright.sync_api import sync_playwright  # noqa: E402


# Real heading structure, taken verbatim from the stored apicoectomy
# curriculum. Note that it is not tidy — see the test at the bottom.
CURRICULUM = "\n\n".join([
    "# Apicoectomy of Mandibular Teeth — 20-Minute Teaching Curriculum",
    "## Overview", "Body text.",
    "## Module 1 — Indications and Anatomical Considerations", "Body text.",
    "## Clinical Application", "Body text.",
    "### 4a. Procedural Protocol", "Body text.",
    "### 4b. Decision Tree", "Body text.",
    "## Module 3 — Surgical Technique", "Body text.",
    "## Key takeaways", "Body text.",
])

SHORT = "## Only one\n\nBody.\n\n## And two\n\nBody.\n"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _page(browser, width=1440):
    pg = browser.new_page(viewport={"width": width, "height": 900})
    pg.route("**/*", lambda route: route.fulfill(
        status=200, content_type="application/json", body="{}"))
    pg.set_content(INDEX_HTML.read_text(encoding="utf-8"),
                   wait_until="domcontentloaded")
    pg.wait_for_function("typeof buildCurriculumToc === 'function'")
    return pg


def _build(pg, markdown):
    return pg.evaluate("""(md) => {
        const body = document.getElementById('ppLearnViewerBody');
        const toc  = document.getElementById('ppLearnToc');
        document.getElementById('ppLearnViewer').classList.add('open');
        body.innerHTML = renderAnswer(md);
        buildCurriculumToc(body, toc);
        const card = document.querySelector('.profile-learn-viewer-card');
        const links = [...toc.querySelectorAll('a[data-toc]')];
        return {
            hasToc:   card.classList.contains('has-toc'),
            display:  getComputedStyle(toc).display,
            position: getComputedStyle(toc).position,
            width:    Math.round(toc.getBoundingClientRect().width),
            links:    links.length,
            subs:     links.filter(a => a.classList.contains('toc-sub')).length,
            labels:   links.map(a => a.textContent.trim()),
            ids:      body.querySelectorAll('h2[id], h3[id]').length,
            targets:  links.map(a => a.getAttribute('data-toc'))
                           .filter(id => !!document.getElementById(id)).length,
        };
    }""", markdown)


class TestTheTocIsBuiltFromWhatIsOnThePage:

    def test_every_heading_gets_a_link_and_every_link_resolves(self, browser):
        pg = _page(browser)
        r = _build(pg, CURRICULUM)
        assert r["links"] == r["ids"] > 0, r
        assert r["targets"] == r["links"], (
            "%d of %d links point at an id that does not exist"
            % (r["links"] - r["targets"], r["links"]))
        pg.close()

    def test_sub_headings_are_marked_as_sub(self, browser):
        pg = _page(browser)
        r = _build(pg, CURRICULUM)
        assert r["subs"] == 2, r["labels"]
        assert "4a. Procedural Protocol" in r["labels"]
        pg.close()

    def test_a_short_answer_gets_no_sidebar(self, browser):
        """Below the threshold a sidebar is noise, not navigation."""
        pg = _page(browser)
        r = _build(pg, SHORT)
        assert r["links"] == 0, r["labels"]
        assert r["hasToc"] is False
        pg.close()

    def test_rebuilding_does_not_duplicate_it(self, browser):
        """The viewer is reopened for every report."""
        pg = _page(browser)
        first = _build(pg, CURRICULUM)
        again = _build(pg, CURRICULUM)
        assert again["links"] == first["links"], (first["links"], again["links"])
        pg.close()

    def test_a_short_report_opened_after_a_long_one_clears_the_sidebar(self, browser):
        """The case the previous test cannot see.

        Rebuilding the SAME document passes with the clear removed, because the
        final `tocEl.innerHTML = ...` overwrites it anyway. The clear only
        matters on the early-return path: open a 32-heading curriculum, then
        open a two-heading report, and the stale sidebar is still on screen
        pointing at ids that no longer exist.
        """
        pg = _page(browser)
        long_one = _build(pg, CURRICULUM)
        assert long_one["links"] > 4
        short = _build(pg, SHORT)
        assert short["links"] == 0, (
            "the previous report's %d links are still in the sidebar"
            % short["links"])
        assert short["hasToc"] is False
        pg.close()


class TestWidth:

    def test_visible_and_sticky_on_a_wide_screen(self, browser):
        pg = _page(browser, width=1440)
        r = _build(pg, CURRICULUM)
        assert r["display"] == "block", r
        assert r["position"] == "sticky", r
        assert 200 <= r["width"] <= 224, r["width"]
        pg.close()

    @pytest.mark.parametrize("width", [1024, 768])
    def test_hidden_below_1080(self, browser, width):
        pg = _page(browser, width=width)
        r = _build(pg, CURRICULUM)
        assert r["display"] == "none", (width, r)
        pg.close()


class TestMastheadChips:
    """A44d — the provenance a curriculum already computes, in one row.

    Verified in the running app on the stored apicoectomy record:

        papers 95 · cited 40 of 95 · modules 3 · citations 316 ·
        mean score 60.9 · Cochrane 11 · Level I 30 · Level II 14 ·
        Level IIIa 13 · Level IIIb 3 · Level IV 14 · Level V 10 · cost $1.82

    The tier counts sum to 95, which is `total_papers`. And `modules 3`
    independently corroborates the missing `## Module 2` heading — the document
    claims four modules and carries three headings.
    """

    REC = {
        "total_papers": 95, "cost_usd": 1.8203, "avg_paper_score": 60.9,
        "papers": ([{"level_key": "cochrane"}] * 11
                   + [{"level_key": "level1"}] * 30
                   + [{"level_key": "level2"}] * 14),
    }

    def _chips(self, browser, rec, markdown):
        pg = _page(browser)
        out = pg.evaluate("""([rec, md]) => {
            const body = document.getElementById('ppLearnViewerBody');
            const chips = document.getElementById('ppLearnChips');
            body.innerHTML = renderAnswer(md);
            buildMastheadChips(rec, body, chips);
            return [...chips.querySelectorAll('.masthead-chip')]
                     .map(e => e.textContent.trim());
        }""", [rec, markdown])
        pg.close()
        return out

    def test_counts_and_tiers_render_strongest_first(self, browser):
        chips = self._chips(browser, self.REC, CURRICULUM)
        assert "papers 95" in chips, chips
        assert "cost $1.82" in chips, chips
        assert chips.index("Cochrane 11") < chips.index("Level I 30") \
            < chips.index("Level II 14"), chips

    def test_modules_are_counted_from_the_rendered_page(self, browser):
        """CURRICULUM carries `Module 1` and `Module 3` and no `Module 2` —
        the same gap the real document has. The chip must report 2, not 3."""
        chips = self._chips(browser, self.REC, CURRICULUM)
        assert "modules 2" in chips, chips

    def test_a_missing_field_emits_no_chip_rather_than_unknown(self, browser):
        """A11 wanted the build hash visible and `learn_history` does not store
        it. Showing "unknown" would be inventing a field."""
        chips = self._chips(browser, {"total_papers": 12}, CURRICULUM)
        joined = " ".join(chips).lower()
        assert "papers 12" in chips, chips
        assert "cost" not in joined, chips
        assert "unknown" not in joined and "n/a" not in joined, chips

    def test_the_row_is_cleared_between_reports(self, browser):
        pg = _page(browser)
        out = pg.evaluate("""([rec, md]) => {
            const body = document.getElementById('ppLearnViewerBody');
            const chips = document.getElementById('ppLearnChips');
            body.innerHTML = renderAnswer(md);
            buildMastheadChips(rec, body, chips);
            const first = chips.querySelectorAll('.masthead-chip').length;
            buildMastheadChips({}, body, chips);
            return [first, chips.querySelectorAll('.masthead-chip').length];
        }""", [self.REC, CURRICULUM])
        pg.close()
        first, second = out
        assert first > 5, first
        assert second < first, (
            "the previous report's chips are still in the masthead: %s" % out)


class TestWhatTheTocRevealed:
    """A44b was a navigation fix. It is also an instrument, and the first thing
    it measured was that the generator's headings are not what they claim.

    On the stored apicoectomy curriculum, all four modules number their
    subsections **"4a. / 4b. / 4c."** — the prompt's template numbering copied
    verbatim rather than renumbered per module — and five labels repeat:

        Clinical Application            x4
        4a. Procedural Protocol         x4
        4b. Decision Tree               x4
        4c. Materials & Instrumentation x4
        Clinical Protocol Summary       x3

    The module sequence is also **1, [unnamed], 3, 4**: a second module's
    content exists with no `## Module 2 —` heading at all.

    This test does not assert the defect is fixed — fixing it is generator work
    that needs a live curriculum to verify. It pins that the TOC REPORTS the
    document faithfully, duplicates included, so the defect stays visible
    instead of being tidied away by the navigation that found it.
    """

    def test_the_toc_mirrors_duplicate_headings_rather_than_hiding_them(self, browser):
        md = CURRICULUM + "\n\n## Clinical Application\n\nBody text.\n"
        pg = _page(browser)
        r = _build(pg, md)
        assert r["labels"].count("Clinical Application") == 2, r["labels"]
        assert r["targets"] == r["links"], (
            "duplicate labels must still get distinct ids")
        pg.close()
