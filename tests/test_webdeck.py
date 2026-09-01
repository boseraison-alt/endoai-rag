"""The web-deck export (PRESENTATION_WORKLIST §3).

Fixtures are real: `webdeck_spec.json` is nine slides lifted verbatim from the
generated laser-curriculum deck, `webdeck_answer.txt` is the answer they were
generated from, and `webdeck_papers.json` is that run's scored papers. The
rules being guarded here are all rules about text that reaches a clinician, so
testing them against invented slides would prove nothing about the thing that
ships.

Two rules carry most of the weight:

  * §0 prime rule — rendering only, never authoring. The tests that matter
    most are the ones asserting that clinical text arrives on a slide
    UNCHANGED: the body budget splits rather than truncates, and a value that
    is not in the answer never becomes a chart.
  * §1.3 — a raw [[PMID:N]] marker must never appear on a slide.
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from webdeck import assets, builder, citations, layouts, narration, plan, tokens

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def spec():
    return json.loads((FIX / "webdeck_spec.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def answer():
    return (FIX / "webdeck_answer.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def papers_list():
    return json.loads((FIX / "webdeck_papers.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def papers(papers_list):
    return {str(p["pmid"]): p for p in papers_list}


@pytest.fixture(scope="module")
def deck_html(spec, answer, papers_list):
    return builder.build_web_deck(spec, "Use of lasers in root canal disinfection",
                                  answer, papers_list=papers_list,
                                  abstracts={}, spec_hash="deadbeef")


def slide_bodies(html: str):
    """Every <section>, i.e. exactly what a viewer sees — not the config JSON
    or the runtime, where a PMID marker would be harmless."""
    return re.findall(r'<section class="deck-slide.*?</section>', html, re.S)


# ── §1 design tokens ─────────────────────────────────────
class TestSpecTokens:
    """Pinned against the §1.1 / §1.2 tables. `presentations/design_tokens.py`
    restates the same spec for the PPTX side; both must match §1, and this is
    the half that catches a hex typo in the web deck."""

    @pytest.mark.parametrize("name,value", [
        ("bg", "#131b2c"), ("surface", "#1c2740"), ("surface-alt", "#17213a"),
        ("card", "#1a2440"), ("border", "#2c3a58"), ("leader", "#33425f"),
        ("text-title", "#ffffff"), ("text-body", "#eef2fa"),
        ("text-secondary", "#c6d0e2"), ("text-lead", "#aebad0"),
        ("text-eyebrow", "#93a3bd"), ("text-footer", "#8296b3"),
        ("text-muted", "#7d8fae"), ("accent-cyan", "#8bd7e8"),
        ("divider-bg", "#1e40af"), ("divider-num", "#3556c4"),
    ])
    def test_dark_palette(self, name, value):
        assert tokens.DARK[name] == value

    @pytest.mark.parametrize("slot,fill,chip", [
        ("cochrane", "#4ec78f", ("#12301f", "#5ad196")),
        ("level1",   "#22c0dd", ("#0e2b33", "#5fd4e8")),
        ("level2",   "#60a5fa", ("#1e2f55", "#93b4f5")),
        ("level3",   "#c4b5fd", ("#241d47", "#c4b5fd")),
        ("level4",   "#f27596", ("#331420", "#f27596")),
        ("invitro",  "#fbbf24", ("#33270f", "#f5b84d")),
        ("level5",   "#e18aef", ("#2e1633", "#e18aef")),
    ])
    def test_tier_ladder(self, slot, fill, chip):
        assert tokens.TIER_CHART_DARK[slot] == fill
        assert tokens.TIER_CHIP_DARK[slot] == chip

    def test_light_ladder_is_the_cvd_validated_set(self):
        """§1.2 says this exact set passed the colour-blindness validator on
        the light evidence card. Substituting the dark ladder there — the
        obvious 'simplification' — silently discards that validation."""
        assert [tokens.TIER_CHART_LIGHT[s] for s in tokens.TIER_SLOTS] == [
            "#0f7a4d", "#0891b2", "#2563eb", "#a78bfa", "#9f1239",
            "#d97706", "#86198f"]

    def test_ladder_order_is_strongest_first(self):
        assert tokens.TIER_SLOTS[0] == "cochrane"
        assert tokens.TIER_SLOTS[-1] == "level5"

    def test_level_three_is_flagged_always_label(self):
        """§1.2: Level III 'must always carry its text label'."""
        assert "level3" in tokens.ALWAYS_LABEL

    def test_both_library_level_three_keys_collapse_to_one_ladder_slot(self):
        """The library splits retrospective cohort from case-control; the
        seven-colour ladder does not. Leaving 3b unmapped would paint
        case-control papers with the neutral 'other' colour."""
        assert tokens.slot_for("level3a") == "level3"
        assert tokens.slot_for("level3b") == "level3"

    def test_an_unknown_tier_never_borrows_a_tier_colour(self):
        """`classic` and `retracted` have no ladder slot. Mapping either onto a
        real tier would be a false claim about evidence strength."""
        for key in ("classic", "retracted", "", None, "nonsense"):
            assert tokens.slot_for(key) == "other"
        assert tokens.chart_color_dark("other") not in tokens.TIER_CHART_DARK.values()


# ── §1.3 the rule about raw markers ──────────────────────
class TestNoRawMarkerReachesASlide:

    def test_rendered_deck_has_no_provenance_markers(self, deck_html):
        for section in slide_bodies(deck_html):
            assert "[[PMID:" not in section
            assert "[PMID:" not in section

    def test_strip_markers_leaves_the_sentence_readable(self):
        got = citations.strip_markers(
            "Nd:YAG lasers penetrate tubules [[PMID:36978686]] [[PMID:40136729]].")
        assert got == "Nd:YAG lasers penetrate tubules."

    def test_a_marker_becomes_a_clickable_pill_not_a_deletion(self, papers):
        html = citations.render_inline("Healing improved [[PMID:36156804]].", papers)
        assert 'data-pmid="36156804"' in html
        assert "[[PMID:" not in html


# ── §1.3 body budget: split, never truncate ──────────────
class TestBodyBudget:

    def test_six_short_bullets_split_onto_two_slides(self):
        pages = layouts.split_by_budget(["one two three"] * 6)
        assert [len(p) for p in pages] == [5, 1]

    def test_a_long_bullet_costs_more_than_one_slot(self):
        """~25 words is one slot, so a 60-word bullet takes three and cannot
        share a slide with four others."""
        long = " ".join(["word"] * 60)
        assert layouts.slot_cost(long) == 3
        pages = layouts.split_by_budget([long, "a", "b", "c"])
        assert pages[0] == [long, "a", "b"]
        assert pages[1] == ["c"]

    def test_an_oversized_bullet_is_never_shortened(self):
        """The prime rule. Trimming to fit would edit clinical text; the
        bullet gets its own slide with every word intact instead."""
        huge = " ".join(f"w{i}" for i in range(300))
        pages = layouts.split_by_budget([huge])
        assert pages == [[huge]]
        assert pages[0][0] == huge

    def test_no_slide_carries_more_than_five_bullets(self, deck_html):
        for section in slide_bodies(deck_html):
            assert len(re.findall(r'<li class="bullet', section)) <= 5

    def test_continuation_slides_are_marked(self, spec, answer, papers, papers_list):
        planned = plan.plan_deck(spec, papers, papers_list, answer)
        conts = [s for s in planned if s.get("_continued")]
        assert conts, "the takeaways slide has six items and must split"
        assert all(s["layout"] != "title" for s in conts)

    def test_a_split_keeps_the_same_title_rather_than_inventing_one(
            self, spec, answer, papers, papers_list):
        planned = plan.plan_deck(spec, papers, papers_list, answer)
        tk = [s for s in planned if s["layout"] == "takeaways"]
        assert len(tk) == 2
        assert tk[0]["title"] == tk[1]["title"]

    def test_a_long_table_splits_and_repeats_its_header(self):
        rows = [[f"r{i}", "x", "y"] for i in range(14)]
        cols = [{"label": "A", "span": 4}, {"label": "B", "span": 4},
                {"label": "C", "span": 4}]
        pages = plan._plan_table({}, "T", cols, rows)
        assert [len(p["_rows"]) for p in pages] == [6, 6, 2]
        assert all(p["_columns"] == cols for p in pages), \
            "a continuation table without its header row is unreadable"

    def test_every_source_row_survives_a_table_split(self):
        rows = [[f"r{i}", "x", "y"] for i in range(14)]
        cols = [{"label": "A", "span": 12}]
        pages = plan._plan_table({}, "T", cols, rows)
        assert [r for p in pages for r in p["_rows"]] == rows


# ── §1.5 chart hard rules ────────────────────────────────
class TestChartHardRules:

    def test_a_value_absent_from_the_source_is_not_chartable(self):
        assert not layouts.value_is_cited("91.4%", "healing reached 86.9% at 12 months")

    def test_a_value_present_in_the_source_is_chartable(self):
        assert layouts.value_is_cited("86.9%", "healing reached 86.9% at 12 months")

    def test_a_value_with_no_number_is_never_chartable(self):
        assert not layouts.value_is_cited("substantial", "substantial improvement")

    def test_uncited_numbers_produce_no_chart(self, papers):
        s = {"pattern": "stat_panel", "title": "Outcome",
             "primary_stat": "99.9%", "primary_label": "Made up",
             "secondary_stat": "11.1%", "secondary_label": "Also made up"}
        out = plan.adapt(s, papers, "the answer mentions 86.9% and 74.5%")
        assert all(o["layout"] != "chart" for o in out), \
            "an uncited number must not acquire the authority of a plotted mark"

    def test_a_cited_comparison_produces_one_chart(self, papers, answer):
        s = {"pattern": "stat_panel", "title": "Periapical healing",
             "primary_stat": "86.9%", "primary_label": "SWEEPS LAI at 12 months",
             "secondary_stat": "74.5%", "secondary_label": "Control at 12 months"}
        out = plan.adapt(s, papers, answer)
        assert [o["layout"] for o in out] == ["chart"]
        assert [raw for _n, _v, raw in out[0]["_series"]] == ["86.9%", "74.5%"]

    def test_the_uncited_fallback_still_shows_the_numbers_as_text(self, papers):
        """Refusing the chart must not delete the figure — the clinician still
        sees what the spec said, just without a plotted mark behind it."""
        s = {"pattern": "stat_panel", "title": "Outcome",
             "primary_stat": "99.9%", "primary_label": "Made up"}
        out = plan.adapt(s, papers, "nothing relevant here")
        rendered = "".join(
            layouts.LAYOUT_RENDERERS[o["layout"]](o, {"papers": papers})
            for o in out)
        assert "99.9%" in rendered

    def test_near_equal_values_use_a_dot_plot(self):
        assert layouts.chart_kind(["86.9%", "85.4%"]) == "dot"

    def test_a_magnitude_comparison_uses_bars_from_zero(self):
        assert layouts.chart_kind(["86.9%", "45.0%"]) == "bar"

    def test_a_truncated_axis_carries_its_note(self):
        svg = layouts._dot_svg([("A", 86.9, "86.9%"), ("B", 85.4, "85.4%")])
        assert "axis starts at" in svg, \
            "§1.5 allows a truncated axis ONLY with an explicit axis note"

    def test_bars_start_at_zero_and_carry_no_axis_note(self):
        svg = layouts._bar_svg([("A", 86.9, "86.9%"), ("B", 45.0, "45.0%")])
        assert "axis starts at" not in svg

    def test_single_series_marks_use_the_one_approved_colour(self):
        svg = layouts._bar_svg([("A", 10.0, "10"), ("B", 20.0, "20")])
        fills = set(re.findall(r'<rect[^>]*fill="(#[0-9a-f]{6})"', svg))
        assert fills == {"#60a5fa"}

    def test_an_elided_axis_label_still_appears_verbatim_on_the_slide(self, papers):
        """The SVG cannot wrap, so a long label is elided inside the chart.
        The full text is printed under it, or the elision would be an edit."""
        label = ("Lesion volume reduction with SWEEPS LAI at 12 months — "
                 "Dogan et al. 2024, CBCT-registered RCT, n=56")
        s = {"layout": "chart", "title": "T",
             "_series": [(label, 86.9, "86.9%"), ("Control", 74.5, "74.5%")],
             "_chart_kind": "bar"}
        html = layouts.layout_chart(s, {"papers": papers})
        # Inside the <svg> the label is elided and duplicated into a <title>
        # tooltip, neither of which a printed slide shows. It has to be in the
        # visible key beneath the chart.
        keys = re.search(r'<div class="chart-keys">(.*?)</div>\s*(<p|</div>)',
                         html, re.S).group(1)
        assert citations.esc(label) in keys
        assert "…" in re.search(r"<svg.*?</svg>", html, re.S).group(0), \
            "the fixture label is long enough that the SVG must elide it"


# ── §1.4 #1 the evidence-shape card ──────────────────────
class TestEvidenceShapeCard:

    def test_the_card_is_on_the_title_slide(self, deck_html):
        title = slide_bodies(deck_html)[0]
        assert 'class="evidence-card"' in title, \
            "§1.4 calls the evidence-shape card MANDATORY on every deck"

    def test_segments_are_weighted_by_paper_count(self):
        html = layouts.evidence_shape({"cochrane": 3, "level1": 22})
        assert "flex-grow:3" in html and "flex-grow:22" in html

    def test_no_tier_data_says_so_rather_than_rendering_nothing(self):
        """HANDOVER.md bug class (d): a check that fails open and shows
        nothing is indistinguishable from one that ran clean."""
        html = layouts.evidence_shape({})
        assert 'class="evidence-card"' in html
        assert "not available" in html
        assert "unavailable" in html

    def test_level_three_carries_its_label_even_when_tiny(self):
        html = layouts.evidence_shape({"level1": 200, "level3": 1})
        assert "Level III" in html

    def test_a_small_tier_without_the_always_label_flag_is_legend_only(self):
        html = layouts.evidence_shape({"level1": 200, "level4": 1})
        in_bar = re.findall(r'<span class="ev-seg-label"[^>]*>([^<]+)<', html)
        assert "Level IV" not in in_bar    # 1 of 201 is a sliver, not a label
        assert "Level IV" in html          # still named in the legend

    def test_the_segment_label_ink_is_chosen_by_measured_contrast(self):
        """A fixed white label fails on #a78bfa — and Level III, whose fill
        that is, is the tier §1.2 says must ALWAYS carry its label."""
        assert layouts.ink_for("#a78bfa") == layouts.DARK_INK
        assert layouts.ink_for("#d97706") == layouts.DARK_INK
        assert layouts.ink_for("#0f7a4d") == layouts.LIGHT_INK
        assert layouts.ink_for("#86198f") == layouts.LIGHT_INK
        assert 'style="color:#1b2033"' in layouts.evidence_shape({"level3": 10})

    def test_counts_come_from_the_run_and_use_the_library_tier_keys(self, papers_list):
        counts = builder.tier_counts(papers_list)
        assert counts["level3"] == sum(
            1 for p in papers_list if p.get("level_key") in ("level3a", "level3b"))
        assert sum(counts.values()) == len(papers_list)

    def test_a_retracted_paper_is_never_counted_as_evidence(self):
        counts = builder.tier_counts([
            {"pmid": "1", "level_key": "level1"},
            {"pmid": "2", "level_key": "level1", "has_retraction": True}])
        assert counts == {"level1": 1}


# ── §3.2 citations ───────────────────────────────────────
class TestCitations:

    def test_format_cite_matches_the_apps_inline_shape(self, papers):
        got = citations.format_cite("36156804", papers)
        assert got.startswith("Meire MA et al.")
        assert "International endodontic" in got or "Int Endod" in got

    def test_an_unknown_pmid_degrades_to_a_bare_label(self):
        assert citations.format_cite("999", {}) == "PMID 999"

    def test_footer_citation_uses_the_spec_shape(self, papers):
        got = citations.footer_citation("38878107", papers)
        assert "PMID 38878107" in got
        assert " · " in got
        assert re.search(r"n = \d+", got)

    def test_author_year_resolves_when_it_is_unambiguous(self, papers):
        assert citations.resolve_author_year(
            "Meire et al., J Endod 2023", papers) == ["36156804"]

    def test_two_candidates_yield_no_pill_rather_than_a_guess(self, papers):
        """Attributing a clinical sentence to the wrong study is worse than
        showing no pill, so ambiguity resolves to nothing."""
        twins = {"1": {"pmid": "1", "authors": "Meire MA", "year": "2023"},
                 "2": {"pmid": "2", "authors": "Meire M, De Moor R", "year": "2023"}}
        assert citations.resolve_author_year("Meire et al. 2023", twins) == []

    def test_a_wrong_year_yields_no_pill(self, papers):
        assert citations.resolve_author_year("Meire et al., J Endod 1999", papers) == []

    def test_the_gap_can_cross_et_al_but_not_a_whole_sentence(self, papers):
        """'et al.' contains a period, so the gap class must admit one — but
        bounded, or a year could reach back to an unrelated name."""
        assert citations.resolve_author_year(
            "Meire et al., J Endod 2023", papers) == ["36156804"]
        far = ("Meire wrote about irrigation. " + "x" * 60 + " Some other thing 2023")
        assert citations.resolve_author_year(far, papers) == []

    def test_body_prose_is_not_mined_for_citations(self):
        """A surname inside a clinical sentence is not a citation; pinning a
        pill to it would over-claim."""
        fields = plan._citation_fields(
            {"pattern": "cascade_slide",
             "steps": [{"body": "Follow the Weine 2019 taper convention."}]})
        assert fields == []

    def test_every_pill_carries_the_pmid_the_overlay_needs(self, deck_html):
        pills = re.findall(r'<button[^>]*class="cite-pill[^"]*"[^>]*>', deck_html)
        assert pills
        assert all("data-pmid=" in p for p in pills)

    def test_footers_actually_get_citations(self, deck_html):
        with_cites = [s for s in slide_bodies(deck_html)
                      if 'class="foot-cites"' in s and "cite-pill" in s]
        assert with_cites, "no slide footer resolved a single citation"

    def test_html_in_paper_metadata_cannot_inject_markup(self):
        evil = {"9": {"pmid": "9", "authors": "<img src=x onerror=alert(1)>",
                      "journal": "J", "year": "2024"}}
        html = citations.pill_html("9", evil)
        assert "<img" not in html
        assert "&lt;img" in html


# ── §1.4 the eight layouts ───────────────────────────────
class TestLayouts:

    def test_all_eight_approved_layouts_render(self, deck_html):
        used = set(re.findall(r'data-layout="(\w+)"', deck_html))
        assert used >= {"title", "divider", "content", "table", "decision",
                        "chart", "takeaways", "references"}

    def test_every_emitted_pattern_maps_to_an_approved_layout(self):
        approved = set(layouts.LAYOUT_RENDERERS)
        assert set(layouts.LAYOUT_FOR_PATTERN.values()) <= approved
        assert layouts.DEFAULT_LAYOUT in approved

    def test_a_two_way_comparison_is_a_table_not_a_card_grid(self):
        """§1.4 #5 reserves the card grid for IF/THEN/BECAUSE rules and says it
        must never be filled with bullets."""
        assert layouts.LAYOUT_FOR_PATTERN["two_column_compare"] == "table"

    def test_decision_cards_are_if_then_because_rows(self, papers, answer, spec):
        planned = plan.plan_deck(spec, papers, [], answer)
        dec = next(s for s in planned if s["layout"] == "decision")
        html = layouts.layout_decision(dec, {"papers": papers})
        assert ">IF<" in html and ">THEN<" in html
        assert '<li class="bullet' not in html

    def test_an_unknown_pattern_is_rendered_not_dropped(self, papers):
        out = plan.adapt({"pattern": "some_future_pattern", "title": "T",
                          "items": ["a real clinical line"]}, papers, "")
        assert out and out[0]["layout"] == layouts.DEFAULT_LAYOUT
        assert out[0]["_bullets"] == ["a real clinical line"]

    def test_divider_topics_are_the_module_s_own_slide_titles(
            self, spec, answer, papers, papers_list):
        planned = plan.plan_deck(spec, papers, papers_list, answer)
        div = next(s for s in planned if s["layout"] == "divider")
        after = [s.get("title") for s in planned[planned.index(div) + 1:]]
        assert div["topics"]
        assert all(t in after for t in div["topics"]), \
            "divider tick lines must quote existing slide titles, not new text"

    def test_content_class_slides_carry_the_full_furniture(self, deck_html):
        for section in slide_bodies(deck_html):
            layout = re.search(r'data-layout="(\w+)"', section).group(1)
            if layout in plan.CONTENT_CLASS:
                assert 'class="furniture-head"' in section
                assert 'class="furniture-foot"' in section
                assert 'class="slide-title"' in section

    def test_page_numbers_are_sequential_over_content_slides(self, deck_html):
        nums = [int(n) for n in
                re.findall(r'<div class="foot-page">(\d+)</div>', deck_html)]
        assert nums == list(range(1, len(nums) + 1))

    def test_references_are_built_from_metadata_and_score_honestly(self, deck_html):
        refs = [s for s in slide_bodies(deck_html) if 'data-layout="references"' in s]
        assert refs
        assert "Curo evidence scores" in refs[0]

    def test_the_insufficient_evidence_slide_is_a_notice_not_an_error(self, papers):
        html = layouts.layout_notice(
            {"title": "Module 4", "body": "A search returned no papers."},
            {"papers": papers})
        assert "MODULE NOT GENERATED — INSUFFICIENT EVIDENCE" in html
        assert 'class="notice-box' in html


# ── §1.3 the slide's tier chip ───────────────────────────
class TestTierChip:

    def test_the_strongest_cited_tier_wins(self, papers):
        assert plan.strongest_slot(["36156804", "36978686"], papers) == "level1"

    def test_unresolved_evidence_shows_curo_not_a_tier(self, deck_html):
        """An 'OTHER' chip sitting in the tier position reads as a tier claim
        about papers we could not identify."""
        for section in slide_bodies(deck_html):
            head = re.search(r'<header class="furniture-head">.*?</header>',
                             section, re.S)
            if head:
                assert ">Other<" not in head.group(0)

    def test_takeaways_and_references_carry_the_curo_label(self, deck_html):
        for section in slide_bodies(deck_html):
            if re.search(r'data-layout="(takeaways|references)"', section):
                head = re.search(r'<header class="furniture-head">.*?</header>',
                                 section, re.S).group(0)
                assert "curo-chip" in head


# ── §3.1 self-contained ──────────────────────────────────
class TestSelfContained:

    def test_reveal_is_pinned_to_an_exact_version(self, deck_html):
        assert assets.REVEAL_VERSION == "5.1.0"
        assert f"/reveal.js/{assets.REVEAL_VERSION}/" in deck_html
        assert "/latest/" not in deck_html

    def test_the_cdn_assets_carry_integrity_hashes(self, deck_html):
        for tag in re.findall(r"<(?:script|link)[^>]*cdnjs[^>]*>", deck_html):
            assert "integrity=" in tag and "sha512-" in tag

    def test_only_the_two_declared_hosts_are_contacted(self, deck_html):
        hosts = set(re.findall(r'https?://([a-z0-9.\-]+)', deck_html))
        allowed = {"cdnjs.cloudflare.com", "fonts.googleapis.com",
                   "fonts.gstatic.com", "pubmed.ncbi.nlm.nih.gov",
                   "www.w3.org"}
        assert hosts <= allowed, f"unexpected external host: {hosts - allowed}"

    def test_the_deck_css_and_js_are_inline(self, deck_html):
        assert "<style>" in deck_html
        assert ".evidence-card" in deck_html
        assert "function openAbstract" in deck_html

    def test_both_approved_faces_are_requested(self, deck_html):
        assert "Instrument+Serif" in deck_html and "Inter:wght" in deck_html
        assert "Instrument Serif" in deck_html and "Georgia" in deck_html

    def test_the_pptx_font_fallback_mapping_is_documented(self):
        assert tokens.PPTX_FONT_FALLBACK == {"Instrument Serif": "Georgia",
                                             "Inter": "Calibri"}

    def test_a_dead_cdn_still_leaves_a_readable_document(self, deck_html):
        assert "no-reveal" in deck_html
        assert 'typeof Reveal === "undefined"' in deck_html

    def test_embedded_abstracts_travel_inside_the_file(self, spec, answer,
                                                       papers_list):
        html = builder.build_web_deck(
            spec, "Q", answer, papers_list=papers_list,
            abstracts={"36156804": {"pmid": "36156804", "title": "T",
                                    "abstract": "A real abstract body.",
                                    "journal": "J", "year": "2023",
                                    "authors": "Meire MA"}})
        assert "A real abstract body." in html

    def test_an_abstract_cannot_close_the_inline_script(self, spec, answer):
        """The deck is served from the app's own origin, so a `</script>` in a
        PubMed abstract is the difference between an embedded abstract and
        stored XSS against a logged-in clinician."""
        html = builder.build_web_deck(
            spec, "Q", answer,
            abstracts={"1": {"pmid": "1", "title": "t",
                             "abstract": "</script><script>alert(1)</script>"}})
        payload = html.split("<script>\n")[-1]
        assert "</script><script>alert(1)" not in payload
        assert "\\u003c/script" in html


# ── §3.4 print ───────────────────────────────────────────
class TestPrintCss:

    def test_print_mode_skips_reveal_entirely(self, deck_html):
        assert 'if (PRINT) { setupNarration(null); return; }' in deck_html
        assert 'root.classList.add("print-pdf")' in deck_html

    def test_dark_backgrounds_are_forced_to_print(self, deck_html):
        block = re.search(r"@media print \{.*?\n\}\n", deck_html, re.S).group(0)
        # On html/body alone the browser still drops the backgrounds of every
        # nested element — the slide frames, table header rows and tier chips
        # are exactly what would go white. The universal selector is the rule
        # that actually does the work.
        universal = re.search(r"\n  \* \{(.*?)\}", block, re.S)
        assert universal, "the @media print block needs a universal rule"
        assert "print-color-adjust: exact" in universal.group(1)
        assert "-webkit-print-color-adjust: exact" in universal.group(1)
        body_rule = re.search(r"\n  html, body \{(.*?)\n  \}", block, re.S).group(1)
        assert "print-color-adjust: exact" in body_rule

    def test_one_page_per_slide(self, deck_html):
        block = re.search(r"@media print \{.*?\n\}\n", deck_html, re.S).group(0)
        assert "page-break-after: always" in block
        assert "break-after: page" in block
        assert "page-break-inside: avoid" in block

    def test_the_page_box_is_the_slide_box(self, deck_html):
        assert "@page {" in deck_html
        assert f"size: {assets.SLIDE_W}px {assets.SLIDE_H}px" in deck_html

    def test_the_overlay_and_narration_bar_do_not_print(self, deck_html):
        block = re.search(r"@media print \{.*?\n\}\n", deck_html, re.S).group(0)
        assert "#abs-overlay" in block and "#narration" in block


# ── §3.3 narration ───────────────────────────────────────
REAL_SIDECAR = {
    "version": 1, "audio_id": "abc", "style": "lecture", "backend": "openai",
    "voice": "onyx", "model": "tts-1-hd", "duration_seconds": 606.024,
    "total_chars": 9404, "created_at": "2026-08-30T20:46:38",
    "slides": [
        {"index": 0, "title": "Welcome", "start": 0.0, "end": 5.016,
         "char_start": 0, "char_end": 78, "preview": "Welcome…"},
        {"index": 1, "title": "Lasers", "start": 5.016, "end": 46.429,
         "char_start": 78, "char_end": 722, "preview": "Over the past…"},
        {"index": 2, "title": "Summary", "start": 46.429, "end": 606.024,
         "char_start": 722, "char_end": 9341, "preview": "In summary…"},
    ],
}


def _write_sidecar(tmp_path, audio_id="abc", data=None):
    (tmp_path / f"{audio_id}.timestamps.json").write_text(
        json.dumps(data if data is not None else REAL_SIDECAR), encoding="utf-8")
    (tmp_path / f"{audio_id}.mp3").write_bytes(b"ID3fake-audio-bytes")


def _unsynced_deck_html(spec, answer, tmp_path):
    """A deck whose narration has 3 segments against 9 spec slides — the real
    lecture-vs-slides mismatch, in miniature."""
    _write_sidecar(tmp_path)
    return builder.build_web_deck(
        spec, "Q", answer,
        narration_loader=lambda n, m: narration.load_narration(
            tmp_path, "abc", n, m))


class TestNarrationSidecar:
    """Agent C's producer writes `<audio_id>.timestamps.json`. These pin the
    shape this consumer actually reads, so a producer change breaks a test
    rather than the deck."""

    def test_the_real_producer_shape_parses(self):
        got = narration.parse_sidecar(REAL_SIDECAR)
        assert got["duration_sec"] == 606.024
        assert [c["index"] for c in got["cues"]] == [0, 1, 2]
        assert got["cues"][0]["start"] == 0.0
        assert got["cues"][-1]["end"] == 606.024

    def test_the_producers_filename_is_the_one_looked_for(self, tmp_path):
        _write_sidecar(tmp_path)
        assert narration.find_sidecar(tmp_path, "abc").name == "abc.timestamps.json"

    def test_a_missing_end_is_inferred_from_the_next_segment(self):
        got = narration.parse_sidecar(
            {"duration_seconds": 30.0,
             "slides": [{"index": 0, "start": 0.0}, {"index": 1, "start": 12.0}]})
        assert got["cues"][0]["end"] == 12.0
        assert got["cues"][1]["end"] == 30.0

    def test_a_one_based_producer_is_normalised(self):
        got = narration.parse_sidecar(
            {"slides": [{"index": 1, "start": 0.0, "end": 5.0},
                        {"index": 2, "start": 5.0, "end": 9.0}]})
        assert [c["index"] for c in got["cues"]] == [0, 1]

    def test_milliseconds_are_accepted(self):
        got = narration.parse_sidecar(
            {"segments": [{"index": 0, "start_ms": 2500, "end_ms": 9000}]})
        assert got["cues"][0]["start"] == 2.5 and got["cues"][0]["end"] == 9.0

    @pytest.mark.parametrize("raw", [
        "{not json", "", None, [], {}, {"slides": []},
        {"slides": [{"index": 0}]},          # no timing at all
        {"slides": ["not a dict"]},
    ])
    def test_malformed_input_returns_none_rather_than_raising(self, raw):
        assert narration.parse_sidecar(raw) is None

    def test_no_sidecar_means_a_deck_without_audio(self, tmp_path):
        assert narration.load_narration(tmp_path, "nothing-here", 3) is None

    def test_no_audio_id_never_guesses_at_a_sidecar(self, tmp_path):
        """The sidecar records no answer identity, so picking the newest file
        would eventually play one answer's narration over another's slides."""
        _write_sidecar(tmp_path)
        assert narration.find_sidecar(tmp_path, "") is None

    def test_a_sidecar_with_no_audio_file_is_refused(self, tmp_path):
        (tmp_path / "abc.timestamps.json").write_text(
            json.dumps(REAL_SIDECAR), encoding="utf-8")
        assert narration.load_narration(tmp_path, "abc", 3) is None

    def test_audio_is_embedded_as_a_data_uri(self, tmp_path):
        _write_sidecar(tmp_path)
        got = narration.load_narration(tmp_path, "abc", 3)
        assert got["audio_src"].startswith("data:audio/mpeg;base64,")

    def test_matching_counts_arm_auto_advance_through_the_section_map(self, tmp_path):
        _write_sidecar(tmp_path)
        got = narration.load_narration(tmp_path, "abc", 3,
                                       spec_to_section={0: 0, 1: 4, 2: 9})
        assert got["synced"] is True
        assert [c["slide"] for c in got["cues"]] == [1, 5, 10]

    def test_a_count_mismatch_disarms_auto_advance_and_says_why(self, tmp_path):
        """3 narration sections against a 25-slide deck. Advancing anyway would
        show the wrong slide for the sentence being heard while LOOKING like it
        worked — HANDOVER.md bug class (d), dressed as a feature."""
        _write_sidecar(tmp_path)
        got = narration.load_narration(tmp_path, "abc", 25)
        assert got is not None and got["audio_src"]
        assert got["synced"] is False
        assert got["cues"] == []
        assert "3 sections" in got["sync_note"] and "25 slides" in got["sync_note"]

    def test_the_deck_carries_the_unsynced_verdict_into_the_page(
            self, spec, answer, tmp_path):
        """The config the runtime reads. That the runtime then DISABLES the
        button is asserted in the browser class below — a string check here
        would pass with the guard deleted, since the string lives inside it."""
        html = _unsynced_deck_html(spec, answer, tmp_path)
        assert '"synced": false' in html or '"synced":false' in html
        assert "Auto-advance off" in html

    def test_a_loader_that_raises_costs_the_audio_not_the_export(self, spec, answer):
        def boom(n, m):
            raise RuntimeError("sidecar on fire")
        html = builder.build_web_deck(spec, "Q", answer, narration_loader=boom)
        assert "<section class=\"deck-slide" in html
        assert '"narration": null' in html or '"narration":null' in html

    def test_the_spec_to_section_map_points_at_the_first_expansion(
            self, spec, answer, papers, papers_list):
        """A spec slide that splits under the body budget must resolve to the
        FIRST of its sections, not the last."""
        planned = plan.plan_deck(spec, papers, papers_list, answer)
        mapping = plan.spec_to_section_map(planned)
        assert mapping[0] == 0
        for spec_index, section in mapping.items():
            assert planned[section]["_spec_index"] == spec_index
            assert not planned[section].get("_continued")


# ── the canonical text object (§0 prime rule) ────────────
class TestRenderingOnly:

    def test_every_bullet_word_survives_to_the_html(self, spec, answer,
                                                    papers, papers_list):
        """The strongest form of the prime rule available offline: take the
        spec's own step bodies and assert each one arrives whole."""
        html = builder.build_web_deck(spec, "Q", answer, papers_list=papers_list)
        checked = 0
        for s in spec["slides"]:
            for item in (s.get("items") or s.get("steps") or []):
                body = (item or {}).get("body")
                if body and "[[PMID" not in body:
                    assert citations.esc(body) in html, f"lost: {body[:60]}"
                    checked += 1
        assert checked >= 5

    def test_the_builder_never_calls_the_slide_generator(self):
        """§5.1 needs both exports to read ONE spec object. A web deck that
        generated its own would produce a different hash every build."""
        import ast
        for path in (ROOT / "webdeck").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    assert node.id != "generate_slides_specs", \
                        f"{path.name} must consume the cached spec, not build its own"
                if isinstance(node, ast.Attribute):
                    assert node.attr != "generate_slides_specs", path.name
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [getattr(node, "module", "") or ""] + \
                            [a.name for a in node.names]
                    assert "endo_ai" not in names, \
                        f"{path.name} imports the generator directly"

    def test_the_route_obtains_its_spec_from_the_shared_cache(self):
        app_src = (ROOT / "app.py").read_text(encoding="utf-8")
        worker = app_src.split("def run_generate_webdeck")[1].split("\ndef ")[0]
        assert "slide_spec_cache.get_or_build" in worker
        assert "generate_slides_specs" not in worker

    def test_slides_are_not_re_derived_from_the_answer_markdown(self, spec, answer):
        """The answer is a citation source and the §1.5 value check — it must
        not be a second slide source."""
        few = {"slides": spec["slides"][:2]}
        html = builder.build_web_deck(few, "Q", answer)
        assert html.count('<section class="deck-slide') <= 4


# ── the export route wiring (§3.5) ───────────────────────
class TestExportRouteWiring:

    def test_the_route_reuses_the_shared_export_source_resolver(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        endpoint = src.split("def generate_webdeck_endpoint")[1].split("\ndef ")[0]
        assert "_resolve_export_source(data)" in endpoint, \
            "§3.5 says REUSE the displayed-answer mechanism, do not reimplement"
        assert "ExportSourceTooLarge" in endpoint
        assert "413" in endpoint

    def test_client_supplied_papers_are_whitelisted_and_bounded(self):
        import app
        out = app._sanitize_export_papers(
            [{"pmid": "1", "level_key": "level1", "abstract": "SECRET",
              "title": "x" * 5000}] * 5000)
        assert len(out) <= app.MAX_EXPORT_PAPERS
        assert "abstract" not in out[0]
        assert len(out[0]["title"]) == 400

    def test_a_row_without_a_real_pmid_is_dropped(self):
        import app
        assert app._sanitize_export_papers(
            [{"pmid": "not-a-pmid"}, {"level_key": "level1"}, "junk"]) == []

    def test_the_media_index_can_serve_the_html_type(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        assert '"html": "text/html"' in src, \
            "without this the Media tab downloads the deck as octet-stream"


# ── the page's own JavaScript (§3.5) ─────────────────────
# Runs the real functions out of templates/index.html under node, the technique
# tests/test_export_client.py established. Asserting on a Python
# re-implementation of the dispatcher would prove nothing about the page.
class TestExportBarJavaScript:

    @staticmethod
    def _js(body):
        from test_export_client import HARNESS, _extract_function
        return (HARNESS
                + "var _lastJob = null; var window = {};\n"
                + _extract_function("startExport") + "\n"
                + _extract_function("_startWebDeckExport") + "\n"
                + _extract_function("_startAudioExport") + "\n"
                + _extract_function("_startVideoExport") + "\n"
                + _extract_function("_startSlidesExport") + "\n"
                + body)

    def _run(self, body):
        from test_export_client import _run_node
        return json.loads(_run_node(self._js(body)))

    def test_the_web_deck_style_reaches_its_own_endpoint(self):
        got = self._run("""
            _exportSource = {question: 'Q', answer: 'A on screen'};
            currentJob = null; _exportStyle = 'webdeck';
            startExport();
            console.log(JSON.stringify({url: _fetches[0].url,
                                        body: _fetches[0].body}));
        """)
        assert got["url"] == "/generate_webdeck"
        assert got["body"]["answer"] == "A on screen"
        assert got["body"]["question"] == "Q"

    def test_a_history_loaded_answer_still_exports(self):
        """The bug the audio fix closed. With no live job the deck export must
        still go out, carrying the answer the clinician is looking at."""
        got = self._run("""
            _exportSource = {question: 'Q', answer: 'A'};
            currentJob = null; _exportStyle = 'webdeck';
            startExport();
            console.log(JSON.stringify({n: _fetches.length,
                status: document.getElementById('exportStatus').textContent}));
        """)
        assert got["n"] == 1
        assert got["status"] != "No answer to export."

    def test_paper_metadata_travels_with_the_request(self):
        """Without it a history-loaded deck has no evidence-shape card and no
        references — the two things built from paper metadata."""
        got = self._run("""
            _exportSource = {question: 'Q', answer: 'A'};
            window._lastJob = {papers: [{pmid: '1', level_key: 'level1'}]};
            currentJob = null; _exportStyle = 'webdeck';
            startExport();
            console.log(JSON.stringify(_fetches[0].body.papers));
        """)
        assert got == [{"pmid": "1", "level_key": "level1"}]

    def test_missing_paper_metadata_sends_an_empty_list_not_a_crash(self):
        got = self._run("""
            _exportSource = {question: 'Q', answer: 'A'};
            window._lastJob = undefined;
            currentJob = null; _exportStyle = 'webdeck';
            startExport();
            console.log(JSON.stringify({papers: _fetches[0].body.papers,
                                        n: _fetches.length}));
        """)
        assert got["papers"] == [] and got["n"] == 1

    def test_the_other_export_styles_are_untouched(self):
        for style, url in [("lecture", "/generate_audio"),
                           ("video", "/generate_video"),
                           ("slides", "/generate_slides")]:
            got = self._run(f"""
                _exportSource = {{question: 'Q', answer: 'A'}};
                currentJob = null; _exportStyle = '{style}';
                startExport();
                console.log(JSON.stringify({{url: _fetches[0].url}}));
            """)
            assert got["url"] == url

    def test_the_export_bar_offers_the_web_deck_card(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        card = re.search(r'<div class="style-card[^"]*" data-style="webdeck".*?</div>',
                         html, re.S)
        assert card, "no Web deck card in the export bar"
        assert "selectExportStyle('webdeck')" in card.group(0)

    def test_the_media_tab_can_open_a_saved_deck(self):
        """A .html item with only a Download button is a dead end in the
        sidebar — the whole point of the format is that it opens."""
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        render = html.split("function renderMediaItem")[1].split("\nfunction ")[0]
        assert "webdeck:" in render
        assert "/webdeck_view/" in render


# ── the browser half (§3.6) ──────────────────────────────
# Runs the shipped page under a real engine. Opt-in because it needs a
# Chromium download; the assertions above cover the same rules structurally.
class TestInTheBrowser:

    @pytest.fixture(scope="class")
    def browser(self):
        import os
        if os.getenv("RUN_BROWSER_TESTS") != "1":
            pytest.skip("set RUN_BROWSER_TESTS=1 to run the Playwright half")
        pw = pytest.importorskip("playwright.sync_api")
        with pw.sync_playwright() as p:
            b = p.chromium.launch()
            yield b
            b.close()

    @pytest.fixture(scope="class")
    def page(self, browser, tmp_path_factory):
        spec_data = json.loads((FIX / "webdeck_spec.json").read_text(encoding="utf-8"))
        answer_data = (FIX / "webdeck_answer.txt").read_text(encoding="utf-8")
        papers_data = json.loads((FIX / "webdeck_papers.json").read_text(encoding="utf-8"))
        html = builder.build_web_deck(
            spec_data, "Use of lasers in root canal disinfection", answer_data,
            papers_list=papers_data,
            abstracts={"36156804": {"pmid": "36156804", "title": "Adjunct therapy",
                                    "abstract": "BACKGROUND: A real embedded abstract "
                                                "body, long enough to be meaningful.",
                                    "journal": "Int Endod J", "year": "2023",
                                    "authors": "Meire MA"}})
        path = tmp_path_factory.mktemp("deck") / "deck.html"
        path.write_text(html, encoding="utf-8")
        pg = browser.new_page(viewport={"width": 1280, "height": 720})
        pg.goto(path.as_uri())
        pg.wait_for_timeout(2000)
        yield pg
        pg.close()

    def test_the_deck_renders_every_slide(self, page):
        n = page.evaluate(
            "document.querySelectorAll('.reveal .slides > section').length")
        assert n > 0
        assert n == page.evaluate("window.CuroDeck.slideCount")

    def test_reveal_actually_initialised(self, page):
        assert page.evaluate("!!(window.CuroDeck && window.CuroDeck.reveal)")

    def test_a_citation_pill_opens_a_non_empty_abstract_offline(self, page):
        """file://, nothing serving — the overlay must come from the copy
        embedded at build time (§3.2)."""
        page.evaluate("window.CuroDeck.closeAbstract()")
        page.evaluate("window.CuroDeck.openAbstract('36156804')")
        page.wait_for_timeout(1200)
        got = page.evaluate("""() => ({
            open: document.getElementById('abs-overlay').classList.contains('open'),
            source: document.getElementById('abs-source').textContent,
            len: document.getElementById('abs-body').textContent.length})""")
        assert got["open"] is True
        assert got["len"] > 40
        assert "embedded" in got["source"]

    def test_a_pmid_with_no_abstract_says_so_rather_than_showing_a_blank(self, page):
        page.evaluate("window.CuroDeck.openAbstract('99999999')")
        page.wait_for_timeout(1200)
        assert "not available" in page.evaluate(
            "document.getElementById('abs-source').textContent")

    def test_print_pdf_stacks_one_full_slide_box_per_section(self, page):
        page.goto(page.url.split("?")[0] + "?print-pdf")
        page.wait_for_timeout(1200)
        got = page.evaluate("""() => {
            const secs = [...document.querySelectorAll('.reveal .slides > section')];
            const cs = getComputedStyle(secs[1]);
            return {n: secs.length, printMode: window.CuroDeck.printMode,
                    revealInit: !!window.CuroDeck.reveal,
                    w: cs.width, h: cs.height, transform: cs.transform,
                    display: cs.display};
        }""")
        assert got["printMode"] is True
        assert got["revealInit"] is False, "Reveal's transform would break paging"
        assert got["n"] == page.evaluate("window.CuroDeck.slideCount")
        assert (got["w"], got["h"]) == ("1280px", "720px")
        assert got["transform"] == "none"
        assert got["display"] == "block"

    def test_an_unsynced_narration_disables_auto_advance_in_the_page(
            self, browser, tmp_path_factory):
        """The behaviour, not the string: with the guard removed the button
        would still SAY 'Auto-advance off' while quietly staying live."""
        spec_data = json.loads((FIX / "webdeck_spec.json").read_text(encoding="utf-8"))
        answer_data = (FIX / "webdeck_answer.txt").read_text(encoding="utf-8")
        tmp = tmp_path_factory.mktemp("narr")
        html = _unsynced_deck_html(spec_data, answer_data, tmp)
        path = tmp / "deck.html"
        path.write_text(html, encoding="utf-8")
        pg = browser.new_page(viewport={"width": 1280, "height": 720})
        try:
            pg.goto(path.as_uri())
            pg.wait_for_timeout(1800)
            got = pg.evaluate("""() => {
                const b = document.getElementById('n-sync');
                return {barOn: document.getElementById('narration')
                                 .classList.contains('on'),
                        disabled: b.disabled,
                        pressed: b.getAttribute('aria-pressed'),
                        why: b.title};
            }""")
        finally:
            pg.close()
        assert got["barOn"] is True, "the audio must still be playable"
        assert got["disabled"] is True
        assert got["pressed"] == "false"
        assert "sections" in got["why"] and "slides" in got["why"]


# ── Multi-arm comparisons reach BOTH exports (CURO_HANDOVER §5[D]) ──────────

class TestMultiArmOnTheWebDeck:
    """Invariant 9: both deck exports consume the same slide spec. `arms` was
    read by neither until this batch, and adding it to the PPTX side alone
    would have produced a chart there and an empty slide here from one spec."""

    SOURCE = ("1% NaOCl achieved 78.4% reduction, 2.5% NaOCl achieved 88.1% "
              "reduction, and 5.25% NaOCl achieved 96.2% reduction.")
    ARMS = [{"label": "1% NaOCl", "stat": "78.4%"},
            {"label": "2.5% NaOCl", "stat": "88.1%"},
            {"label": "5.25% NaOCl", "stat": "96.2%"}]

    def _plan(self, arms, source=None):
        from webdeck.plan import adapt
        slide = {"pattern": "stat_panel", "title": "Bacterial reduction",
                 "arms": arms,
                 "citation": "Vertucci et al. 2024 [[PMID:12345678]]"}
        return adapt(slide, {}, source or self.SOURCE)

    def test_three_arms_plan_a_three_series_chart(self):
        planned = self._plan(self.ARMS)
        charts = [p for p in planned if p.get("layout") == "chart"]
        assert charts, "a verified three-arm comparison must plot on the web deck"
        assert len(charts[0]["_series"]) == 3
        assert [lit for _n, _v, lit in charts[0]["_series"]] == \
            ["78.4%", "88.1%", "96.2%"]

    def test_an_uncited_arm_kills_the_whole_chart(self):
        """All-or-nothing: one unsourced bar inherits the credibility of the
        sourced bars beside it."""
        arms = self.ARMS + [{"label": "6% NaOCl", "stat": "99.9%"}]
        planned = self._plan(arms)
        assert not [p for p in planned if p.get("layout") == "chart"]
        blob = json.dumps(planned)
        assert "99.9%" in blob, "the refused value is still slide content"

    def test_mixed_units_produce_no_chart(self):
        arms = self.ARMS[:2] + [{"label": "contact time", "stat": "30 min"}]
        planned = self._plan(arms, self.SOURCE + " Contact time was 30 min.")
        assert not [p for p in planned if p.get("layout") == "chart"]

    def test_a_range_arm_produces_no_chart(self):
        """Same unit throughout, so the unit gate cannot mask the range gate."""
        arms = self.ARMS[:2] + [{"label": "pooled", "stat": "80-90%"}]
        planned = self._plan(arms, self.SOURCE + " Pooled spanned 80-90%.")
        assert not [p for p in planned if p.get("layout") == "chart"]

    def test_the_two_arm_path_still_charts(self):
        """The gates added here must not have suppressed charting outright."""
        from webdeck.plan import adapt
        planned = adapt({"pattern": "stat_panel", "title": "T",
                         "primary_stat": "86.9%", "primary_label": "Laser",
                         "secondary_stat": "74.5%", "secondary_label": "Control"},
                        {}, "86.9% with laser versus 74.5% control")
        assert [p for p in planned if p.get("layout") == "chart"]

    def test_a_unitless_two_arm_pair_no_longer_charts(self):
        """The hole this closes on the web side: a P-score of 0.993 beside an
        SMD of 0.58 measure nothing in common, and both are unitless."""
        from webdeck.plan import adapt
        planned = adapt({"pattern": "stat_panel", "title": "T",
                         "primary_stat": "0.993", "primary_label": "P-score",
                         "secondary_stat": "0.58", "secondary_label": "SMD"},
                        {}, "a P-score of 0.993 and an SMD of 0.58")
        assert not [p for p in planned if p.get("layout") == "chart"]
