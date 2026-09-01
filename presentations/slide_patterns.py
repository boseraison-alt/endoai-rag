"""
Curo — Slide Pattern Library
=============================
The eight approved layouts of spec §1.4, plus the restyled
"module not generated" notice, plus adapters that keep the pattern names the
slide generator already emits working unchanged.

    1. title_slide       — hero + the mandatory evidence-shape card
    2. section_divider   — flat #1e40af module break
    3. content_slide     — furniture + bullets (+ optional figure)
    4. table_slide       — bordered container, zebra rows, PMID pills
    5. decision_tree     — 2-col IF / THEN / BECAUSE cards
    6. chart_slide       — a chart that passed the §1.5 hard rules
    7. takeaways_slide   — 2x2 serif numerals + "does not apply when" notice
    8. references_slide  — numbered rows with tier chip, pill, score
    9. notice_slide      — "module not generated — insufficient evidence"

Every coordinate comes from design_tokens; every visible run goes through
slide_helpers, so no pattern can put a raw citation marker on a slide.

Two structural notes
--------------------
* **A pattern may return a list of slides.** When a body overflows its budget
  (spec §1.3) the pattern emits continuation slides and returns all of them.
  `build_deck` flattens the result, so callers upstream — including `app.py`,
  which this phase does not modify — are unaffected.

* **Legacy pattern names are adapters, not duplicates.** `objectives_slide`,
  `cascade_slide`, `two_column_compare`, `three_route_grid`, `decision_table`,
  `stat_panel` and `evidence_summary` are the vocabulary
  `endo_ai.generate_slides_specs` emits. Each maps onto one of the eight
  approved layouts rather than defining a ninth look.
"""

from __future__ import annotations

from pptx.enum.text import PP_ALIGN

from presentations.design_tokens import (
    COLORS, SIZES, SIZES_PX, LAYOUT, LINE_HEIGHT, BODY_BUDGET,
    TIER_ORDER, TIER_LABELS, TIER_CHART_FILL, TIER_CHART_FILL_LIGHT,
    CHIP_IF, CHIP_THEN, CHIP_BECAUSE, TAKEAWAY_NUMERALS, BULLET_MARKER,
    TRACK_EYEBROW, TRACK_CHIP, px_in, tier_key,
)
from presentations.slide_helpers import (
    new_presentation, blank_slide, dark_slide, slide_background,
    add_textbox, add_multiline_textbox, add_filled_rect, add_rounded_rect,
    add_circle, add_hairline, add_chip, add_tier_chip, add_pmid_pill,
    chip_width_in, add_header_row, add_slide_title, add_lead, add_footer,
    add_notice_box, add_bullet_row, add_image_bytes,
    estimate_height_in, resolve_color, sanitize, extract_pmids,
)
from presentations.text_budget import (
    split_rows, split_cards, continuation_eyebrow, bullet_cost,
)
from presentations import chart_data, charts

_W = LAYOUT["slide_w_in"]
_H = LAYOUT["slide_h_in"]
_PX = LAYOUT["pad_x_in"]
_CW = LAYOUT["content_w_in"]

CURO_LABEL = "CURO"


# ── shared furniture ─────────────────────────────────────────────────────────

def _citation_fields(spec: dict) -> str:
    """Short citation line for the footer, assembled from the spec's own text.

    Never composed from nothing: only fields the generator actually wrote are
    used, plus the PMIDs harvested out of them. `add_textbox` strips the raw
    markers, so the footer shows author/journal prose plus clean PMID text.
    """
    parts: list[str] = []
    for key in ("citation", "footer_caption", "caption", "footer_metadata",
                "source", "footer"):
        val = spec.get(key)
        if isinstance(val, str) and sanitize(val).strip():
            parts.append(sanitize(val).strip().rstrip("."))
            break

    pmids: list[str] = []
    for key, val in spec.items():
        if key.startswith("_") or key == "speaker_notes":
            continue
        pmids.extend(extract_pmids(_flatten_text(val)))
    seen, ordered = set(), []
    for p in pmids:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    if ordered:
        parts.append(" · ".join(f"PMID {p}" for p in ordered[:4]))
    return " · ".join(p for p in parts if p)


def _flatten_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten_text(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten_text(v) for v in value)
    return ""


def _content_frame(prs, *, eyebrow: str, title: str,
                   tier: str | None = None,
                   right_label: str | None = None,
                   lead: str | None = None,
                   citations: str = "",
                   page_num: int | None = None,
                   title_width: float | None = None,
                   reserve_bottom: float = 0.0):
    """Paint the furniture every content-class slide shares. Returns
    (slide, body_top_y, body_height).

    `reserve_bottom` withholds space above the footer rule for something the
    caller will draw there — a notice box, a caption — so the body is laid out
    around it instead of underneath it.
    """
    slide = dark_slide(prs)
    add_header_row(slide, eyebrow, tier=tier,
                   right_label=right_label if not tier else None)
    title_bottom = add_slide_title(slide, title, width_in=title_width)
    body_top = add_lead(slide, lead or "", title_bottom) + px_in(26)
    add_footer(slide, citations=citations, page_num=page_num)
    body_h = LAYOUT["footer_rule_y_in"] - px_in(22) - reserve_bottom - body_top
    return slide, body_top, max(body_h, px_in(60))


def _pages_meta(page_index: int, eyebrow: str, page_num) -> tuple[str, int | None]:
    """Eyebrow + page number for the nth page of a split body."""
    return (continuation_eyebrow(eyebrow, page_index),
            None if page_num is None else page_num + page_index)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Title
# ─────────────────────────────────────────────────────────────────────────────

def title_slide(prs, *, title: str, subtitle: str = "", eyebrow: str = "",
                tagline: str = "", footer_metadata: str = "",
                tier_counts: dict | None = None,
                disclaimer: str | None = None,
                _page_num: int = 1, _total_pages: int = 1, **_ignored):
    """Dark hero: wordmark row, serif title, subtitle, evidence-shape card.

    The light evidence-shape card is MANDATORY on every deck (spec §1.4) — it
    is the product signature. When the caller supplies no per-tier paper counts
    the card is still drawn, and says so: the label row appears with an honest
    "breakdown not available" line rather than a bar built from invented
    numbers.
    """
    slide = dark_slide(prs)

    # ── Wordmark row: "Curo" serif italic · 1px divider · cyan eyebrow ──
    row_y = LAYOUT["pad_top_in"]
    mark_w = px_in(74)
    add_textbox(slide, "Curo", _PX, row_y, mark_w, px_in(34),
                font_role="display", size=SIZES["wordmark"],
                color=COLORS["text_title"], italic=True, wrap=False)
    div_x = _PX + mark_w
    add_filled_rect(slide, div_x, row_y + px_in(6), LAYOUT["hairline_in"],
                    px_in(22), COLORS["border"])
    if eyebrow:
        add_textbox(slide, eyebrow, div_x + px_in(16), row_y + px_in(10),
                    _CW - mark_w - px_in(16), px_in(22),
                    font_role="body", size=SIZES["eyebrow"],
                    color=COLORS["accent_cyan"], bold=True, upper=True,
                    tracking=TRACK_EYEBROW, wrap=False)

    # ── Hero title ──
    title_y = row_y + px_in(64)
    title_h = estimate_height_in(title, SIZES["title_hero"], _CW * 0.92,
                                 font_role="display",
                                 line_height=LINE_HEIGHT["title"])
    add_textbox(slide, title, _PX, title_y, _CW * 0.92, title_h + px_in(10),
                font_role="display", size=SIZES["title_hero"],
                color=COLORS["text_title"], line_spacing=LINE_HEIGHT["title"])
    y = title_y + title_h + px_in(26)

    if subtitle:
        sub_h = estimate_height_in(subtitle, SIZES["subtitle"], _CW * 0.80,
                                   line_height=LINE_HEIGHT["lead"])
        add_textbox(slide, subtitle, _PX, y, _CW * 0.80, sub_h + px_in(6),
                    font_role="body", size=SIZES["subtitle"],
                    color=COLORS["text_lead"],
                    line_spacing=LINE_HEIGHT["lead"])
        y += sub_h + px_in(10)

    if tagline:
        tag_h = estimate_height_in(tagline, SIZES["lead"], _CW * 0.78,
                                   line_height=LINE_HEIGHT["lead"])
        add_textbox(slide, tagline, _PX, y, _CW * 0.78, tag_h + px_in(6),
                    font_role="body", size=SIZES["lead"],
                    color=COLORS["text_secondary"], italic=True,
                    line_spacing=LINE_HEIGHT["lead"])
        y += tag_h + px_in(12)

    # ── The evidence-shape card ──
    # Mandatory on every deck; sized to what it actually carries so a deck
    # without per-tier counts gets a compact honest card, not a tall empty one.
    card_h = px_in(150) if tier_counts else px_in(96)
    card_y = min(max(y + px_in(14), px_in(392)),
                 LAYOUT["footer_rule_y_in"] - card_h - px_in(40))
    _evidence_shape_card(slide, _PX, card_y, _CW, card_h, tier_counts)

    # ── Footer disclaimer ──
    note = disclaimer or footer_metadata
    if note:
        add_textbox(slide, note, _PX, card_y + card_h + px_in(12), _CW,
                    px_in(20), font_role="body", size=SIZES["footer"],
                    color=COLORS["title_disclaimer"], wrap=False)
    return slide


def _evidence_shape_card(slide, x, y, w, h, tier_counts: dict | None):
    """Light card holding the label row, stacked tier bar, and legend."""
    add_rounded_rect(slide, x, y, w, h, COLORS["light_card"],
                     radius_in=LAYOUT["container_radius_in"])
    pad = px_in(22)
    ix, iw = x + pad, w - pad * 2

    add_textbox(slide, "Evidence shape of this deck", ix, y + pad, iw,
                px_in(18), font_role="body", size=SIZES["eyebrow"],
                color=COLORS["light_card_ink_muted"], bold=True, upper=True,
                tracking=TRACK_EYEBROW, wrap=False)

    chart = chart_data.evidence_shape(tier_counts or {})
    bar_y = y + pad + px_in(28)
    bar_h = LAYOUT["evidence_bar_h_in"]

    if chart is None:
        # No counts supplied. The card stays — the bar does not get invented.
        add_textbox(slide, "Evidence breakdown not available for this deck",
                    ix, bar_y + px_in(4), iw, px_in(24),
                    font_role="body", size=SIZES["lead"],
                    color=COLORS["light_card_ink_muted"], italic=True)
        return

    png = charts.render_evidence_shape(chart, on_light_card=True,
                                       width_in=iw, height_in=0.42)
    if png:
        add_image_bytes(slide, png, ix, bar_y, width_in=iw)
    else:
        _draw_stacked_bar(slide, ix, bar_y, iw, bar_h, chart)

    # Legend row: swatch + name + count per tier.
    legend_y = bar_y + bar_h + px_in(22)
    lx = ix
    for tier, label, value in zip(chart.tier_keys, chart.labels, chart.values):
        swatch = px_in(10)
        add_rounded_rect(slide, lx, legend_y + px_in(4), swatch, swatch,
                         TIER_CHART_FILL_LIGHT[tier], radius_in=px_in(2))
        text = f"{label} {int(value)}"
        tw = px_in(len(text) * 7.6 + 10)
        add_textbox(slide, text, lx + swatch + px_in(6), legend_y, tw,
                    px_in(20), font_role="body", size=SIZES["footer"],
                    color=COLORS["light_card_ink"], wrap=False)
        lx += swatch + px_in(6) + tw + px_in(14)


def _draw_stacked_bar(slide, x, y, w, h, chart):
    """Vector fallback for the evidence-shape bar when matplotlib is absent."""
    total = sum(chart.values) or 1.0
    gap = LAYOUT["evidence_gap_in"]
    usable = w - gap * max(0, len(chart.values) - 1)
    cx = x
    for tier, value in zip(chart.tier_keys, chart.values):
        seg = usable * (value / total)
        add_filled_rect(slide, cx, y, max(seg, px_in(3)), h,
                        TIER_CHART_FILL_LIGHT[tier])
        cx += seg + gap


# ─────────────────────────────────────────────────────────────────────────────
# 2. Section divider
# ─────────────────────────────────────────────────────────────────────────────

def section_divider(prs, *, module_title: str = "", module_label: str = "",
                    module_subtitle: str = "", topics: list | None = None,
                    tier: str | None = None, caveat: str = "",
                    footer: str = "",
                    _module_index: int | None = None,
                    _module_total: int | None = None,
                    _page_num: int = 1, _total_pages: int = 1, **_ignored):
    """Flat #1e40af module break with the giant serif numeral top-right."""
    slide = dark_slide(prs, COLORS["divider_bg"])

    # Giant serif module number, top-right, kept clear of the text column.
    numeral = _module_numeral(module_label, _module_index)
    if numeral:
        add_textbox(slide, numeral, _W - _PX - px_in(300),
                    LAYOUT["pad_top_in"] - px_in(24), px_in(300), px_in(230),
                    font_role="display", size=SIZES["title_hero"] * 2.6,
                    color=COLORS["divider_numeral"], align=PP_ALIGN.RIGHT,
                    wrap=False)

    text_w = max(LAYOUT["divider_text_min_in"], _CW - px_in(320))

    eyebrow = _module_eyebrow(module_label, _module_index, _module_total)

    # Measure the whole text block first, then centre it between the top
    # padding and the bottom chip row. A divider with no topic lines otherwise
    # leaves a half-slide void under the title.
    topic_texts = [
        sanitize(t if isinstance(t, str) else _flatten_text(t))
        for t in (topics or [])[:3]
    ]
    topic_texts = [t for t in topic_texts if t]
    tick_x = _PX + LAYOUT["divider_tick_w_in"] + px_in(14)
    block_h = (px_in(30) if eyebrow else 0.0)
    block_h += estimate_height_in(module_title, SIZES["title_divider"],
                                  text_w, font_role="display",
                                  line_height=LINE_HEIGHT["title"]) + px_in(26)
    for text in topic_texts:
        block_h += estimate_height_in(text, SIZES["divider_tick"],
                                      text_w - (tick_x - _PX),
                                      line_height=LINE_HEIGHT["lead"]) \
            + px_in(14)

    top = LAYOUT["pad_top_in"] + px_in(40)
    bottom = LAYOUT["footer_rule_y_in"] - px_in(90)
    y = max(top, top + (bottom - top - block_h) / 2)

    if eyebrow:
        add_textbox(slide, eyebrow, _PX, y, text_w, px_in(20),
                    font_role="body", size=SIZES["eyebrow"],
                    color="#c7d6ff", bold=True, upper=True,
                    tracking=TRACK_EYEBROW, wrap=False)
        y += px_in(30)

    title_h = estimate_height_in(module_title, SIZES["title_divider"], text_w,
                                 font_role="display",
                                 line_height=LINE_HEIGHT["title"])
    add_textbox(slide, module_title, _PX, y, text_w, title_h + px_in(10),
                font_role="display", size=SIZES["title_divider"],
                color=COLORS["text_title"], line_spacing=LINE_HEIGHT["title"])
    y += title_h + px_in(26)

    # Tick-mark topic lines: 18x2px cyan dash + #dbe6fd text.
    for text in topic_texts:
        add_filled_rect(slide, _PX, y + px_in(11),
                        LAYOUT["divider_tick_w_in"],
                        LAYOUT["divider_tick_h_in"], COLORS["accent_cyan"])
        tx = tick_x
        th = estimate_height_in(text, SIZES["divider_tick"],
                                text_w - (tx - _PX),
                                line_height=LINE_HEIGHT["lead"])
        add_textbox(slide, text, tx, y, text_w - (tx - _PX), th + px_in(4),
                    font_role="body", size=SIZES["divider_tick"],
                    color="#dbe6fd", line_spacing=LINE_HEIGHT["lead"])
        y += th + px_in(14)

    # Bottom: module evidence chip + one-line caveat.
    bottom_y = LAYOUT["footer_rule_y_in"] - px_in(56)
    cx = _PX
    if tier and tier_key(tier):
        cx += add_tier_chip(slide, tier, cx, bottom_y) + px_in(14)
    note = sanitize(caveat or module_subtitle)
    if note:
        add_textbox(slide, note, cx, bottom_y + px_in(1),
                    _CW - (cx - _PX), px_in(26),
                    font_role="body", size=SIZES["table_body"],
                    color="#c7d6ff", wrap=False)
    return slide


def _module_numeral(module_label: str, index: int | None) -> str:
    import re
    if module_label:
        m = re.search(r"(\d+)", str(module_label))
        if m:
            return f"{int(m.group(1)):02d}"
    if index:
        return f"{index:02d}"
    return ""


def _module_eyebrow(module_label: str, index: int | None,
                    total: int | None) -> str:
    if index and total:
        return f"Module {index} of {total}"
    return sanitize(module_label)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Content
# ─────────────────────────────────────────────────────────────────────────────

def content_slide(prs, *, title: str, eyebrow: str = "",
                  bullets: list | None = None, lead: str | None = None,
                  tier: str | None = None, citations: str = "",
                  figure_png: bytes | None = None,
                  figure_caption: str = "",
                  _page_num: int | None = None,
                  _total_pages: int = 1, **_ignored):
    """Furniture + bullets, with an optional right-side figure.

    Overflows the body budget by splitting onto continuation slides; returns a
    list when it does.

    Pagination applies TWO budgets, because they catch different overflows:

      * the WORD budget (§1.3: at most 5 bullets of ~25 words), which knows
        nothing about the frame the bullets will be drawn into;
      * the HEIGHT actually available on the page — `avail`, which
        `_content_frame` computes from where the title wrapped and whether a
        lead was drawn.

    The word budget alone let `cascade_slide` overflow the footer rule: five
    steps of under 25 words each cost five slots and fit, but each renders as
    a bold header line PLUS a body paragraph, so the drawn body ran to 7.385in
    against a 7.000in rule (spec 01e071f7 slide 9). `avail` was already being
    returned by `_content_frame` and simply never consulted. Text is never
    truncated to fit — a bullet that does not fit starts the next page.
    """
    body_w = _CW * (0.56 if figure_png else 1.0)
    avail_first, avail_rest = _body_capacity(
        title=title, eyebrow=eyebrow, tier=tier, lead=lead,
        citations=citations,
        title_width=body_w if figure_png else None)
    pages = _paginate(bullets or [], body_w, avail_first, avail_rest)
    out = []

    for i, page in enumerate(pages):
        eb, pn = _pages_meta(i, eyebrow, _page_num)
        slide, y, avail = _content_frame(
            prs, eyebrow=eb, title=title, tier=tier,
            right_label=CURO_LABEL, lead=lead if i == 0 else None,
            citations=citations, page_num=pn,
            title_width=body_w if figure_png else None)

        for item in page:
            y = _draw_bullet(slide, item, _PX, y, body_w) + px_in(16)

        if figure_png and i == 0:
            fig_x = _PX + _CW * 0.60
            fig_w = _CW * 0.40
            add_image_bytes(slide, figure_png, fig_x,
                            LAYOUT["title_y_in"] + px_in(20), width_in=fig_w)
            if figure_caption:
                add_textbox(slide, figure_caption, fig_x,
                            LAYOUT["footer_rule_y_in"] - px_in(46), fig_w,
                            px_in(30), font_role="body", size=SIZES["footer"],
                            color=COLORS["text_footer"])
        out.append(slide)
    return out if len(out) > 1 else out[0]


def _body_capacity(**frame_kw) -> tuple[float, float]:
    """Body height available on the first page and on a continuation page.

    Measured by painting the real furniture — the title wrap and the lead are
    what move this number, and both are text-dependent — into a THROWAWAY
    presentation, which is then dropped. Nothing is added to `prs`.
    """
    lead = frame_kw.pop("lead", None)
    probe = new_presentation()
    _, _, first = _content_frame(probe, right_label=CURO_LABEL, lead=lead,
                                 **frame_kw)
    _, _, rest = _content_frame(probe, right_label=CURO_LABEL, lead=None,
                                **frame_kw)
    return first, rest


def _paginate(bullets: list, w: float, avail_first: float,
              avail_rest: float) -> list[list]:
    """Pages that satisfy the word budget AND fit the frame, balanced.

    Enforces the word budget's caps (`bullet_cost`, `max_bullets`) and the
    frame's height, then spreads the bullets over the pages it is forced onto
    anyway — the same anti-orphan rule `text_budget.split_bullets` applies in
    word-space. Never drops or truncates a bullet.
    """
    items = list(bullets or [])
    if not items:
        return [[]]
    heights = [_bullet_height(it, w) for it in items]

    # 1. How many pages the frame forces when each is filled to the brim.
    tight = _pack_by_height(items, heights, None, avail_first, avail_rest)
    if len(tight) <= 1:
        return tight

    # 2. Spread the same bullets over the same number of pages. An exactly
    #    even target usually needs one page MORE than the tight packing
    #    (greedy filling to an average always spills), so the target is
    #    relaxed until the page count comes back down to where it was. This
    #    is the height-space version of what `split_bullets` does in
    #    word-space with `max(target, max(costs))`.
    target = sum(heights) / float(len(tight))
    for _ in range(80):
        balanced = _pack_by_height(items, heights, target, avail_first, avail_rest)
        if len(balanced) <= len(tight):
            return balanced
        target *= 1.05
    return tight


def _pack_by_height(items, heights, target, avail_first, avail_rest):
    """Greedy fill, hard-capped by the real frame. `target` may be None.

    The word budget's per-page caps are enforced here too — dropping them
    would let a page of short bullets grow past the 5-bullet rule just because
    the pixels happened to fit.
    """
    max_bullets = BODY_BUDGET["max_bullets"]
    costs = [bullet_cost(_bullet_text_of(it)) for it in items]
    pages, page, used, slots = [], [], 0.0, 0
    for item, h, c in zip(items, heights, costs):
        cap = avail_first if not pages else avail_rest
        # A single bullet taller than the whole frame still gets a page: the
        # alternative is cutting clinical text.
        over = (used + h > cap
                or (target is not None and used + h > target)
                or slots + c > max_bullets or len(page) >= max_bullets)
        if page and over:
            pages.append(page)
            page, used, slots = [], 0.0, 0
        page.append(item)
        used += h
        slots += c
    if page:
        pages.append(page)
    return pages


def _bullet_text_of(item) -> str:
    header, body = _bullet_parts(item)
    return " ".join(p for p in (header, body) if p)


def _bullet_parts(item) -> tuple[str, str]:
    """(header, body) for a bullet in whatever shape it arrived in."""
    if isinstance(item, dict):
        header = sanitize(item.get("header") or item.get("heading")
                          or item.get("label") or "")
        body = sanitize(item.get("body") or item.get("description")
                        or item.get("text") or "")
        number = sanitize(str(item.get("number") or ""))
        if number and header:
            header = f"{number} · {header}"
        return header, body
    return sanitize(str(item)), ""


def _bullet_height(item, w: float) -> float:
    """Height `_draw_bullet` will consume, INCLUDING the gap after it.

    Shares `_bullet_parts` and the same `estimate_height_in` calls as the
    drawing code so the prediction cannot drift from what is drawn.
    """
    header, body = _bullet_parts(item)
    d = LAYOUT["bullet_dot_in"]
    text_w = w - (d + px_in(14))
    if header and body:
        h1 = estimate_height_in(header, SIZES["bullet"], text_w,
                                line_height=LINE_HEIGHT["bullet"])
        h2 = estimate_height_in(body, SIZES["bullet"], text_w,
                                line_height=LINE_HEIGHT["bullet"])
        return h1 + h2 + px_in(4) + px_in(16)
    h = estimate_height_in(header or body, SIZES["bullet"], text_w,
                           line_height=LINE_HEIGHT["bullet"])
    h = max(h, (SIZES["bullet"] * LINE_HEIGHT["bullet"]) / 72.0)
    return h + px_in(16)


def _draw_bullet(slide, item, x, y, w) -> float:
    """One bullet. A {header, body} bullet renders as bold lead + body line."""
    header, body = _bullet_parts(item)

    if header and body:
        d = LAYOUT["bullet_dot_in"]
        text_x = x + d + px_in(14)
        text_w = w - (text_x - x)
        add_circle(slide, x + d / 2, y + px_in(11), d, BULLET_MARKER)
        h1 = estimate_height_in(header, SIZES["bullet"], text_w,
                                line_height=LINE_HEIGHT["bullet"])
        h2 = estimate_height_in(body, SIZES["bullet"], text_w,
                                line_height=LINE_HEIGHT["bullet"])
        add_multiline_textbox(slide, [
            {"text": header, "font_role": "body", "size": SIZES["bullet"],
             "bold": True, "color": COLORS["text_body"],
             "line_spacing": LINE_HEIGHT["bullet"]},
            {"text": body, "font_role": "body", "size": SIZES["bullet"],
             "color": COLORS["text_secondary"], "space_before": 2,
             "line_spacing": LINE_HEIGHT["bullet"]},
        ], text_x, y, text_w, h1 + h2 + px_in(8))
        return y + h1 + h2 + px_in(4)

    return add_bullet_row(slide, header or body, x, y, w,
                          marker_color=BULLET_MARKER)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Table
# ─────────────────────────────────────────────────────────────────────────────

def table_slide(prs, *, title: str, headers: list, rows: list,
                eyebrow: str = "", tier: str | None = None,
                citations: str = "", col_spans: list | None = None,
                reserve_bottom: float = 0.0,
                _page_num: int | None = None, _total_pages: int = 1,
                **_ignored):
    """Bordered rounded container, 12-col grid rows, header repeated on split.

    `rows` is a list of cell lists. A cell that is a list of PMIDs (or a dict
    {"pmids": [...]}) renders as right-aligned PMID pills in that column.
    """
    headers = [sanitize(str(h)) for h in (headers or [])]
    ncols = max(1, len(headers))
    spans = col_spans or _default_spans(ncols)
    pages = split_rows(rows or [])
    out = []

    for i, page in enumerate(pages):
        eb, pn = _pages_meta(i, eyebrow, _page_num)
        slide, y, avail = _content_frame(
            prs, eyebrow=eb, title=title, tier=tier,
            right_label=CURO_LABEL, citations=citations, page_num=pn,
            reserve_bottom=reserve_bottom if i == len(pages) - 1 else 0.0)

        header_h = px_in(34)
        row_h = min(px_in(78), max(px_in(44),
                                   (avail - header_h) / max(len(page), 1)))
        table_h = header_h + row_h * len(page)

        add_rounded_rect(slide, _PX, y, _CW, table_h, COLORS["bg"],
                         radius_in=LAYOUT["table_radius_in"],
                         line_color=COLORS["border"], line_width_pt=0.75)
        add_rounded_rect(slide, _PX, y, _CW, header_h, COLORS["surface"],
                         radius_in=LAYOUT["table_radius_in"])

        xs = _col_positions(spans, _PX, _CW)
        pad = px_in(16)
        for label, (cx, cwid) in zip(headers, xs):
            add_textbox(slide, label, cx + pad, y + px_in(9), cwid - pad * 1.4,
                        px_in(20), font_role="body",
                        size=SIZES["table_header"],
                        color=COLORS["text_body"], bold=True, upper=True,
                        tracking=TRACK_EYEBROW, wrap=False)

        ry = y + header_h
        for r, row in enumerate(page):
            if r % 2 == 0:
                add_filled_rect(slide, _PX + LAYOUT["hairline_in"], ry,
                                _CW - LAYOUT["hairline_in"] * 2, row_h,
                                COLORS["surface_alt"])
            add_hairline(slide, _PX, ry, _CW, COLORS["border"])
            cells = row if isinstance(row, (list, tuple)) else [row]
            for c, (cx, cwid) in enumerate(xs):
                if c >= len(cells):
                    break
                _draw_cell(slide, cells[c], cx, ry, cwid, row_h,
                           first_col=(c == 0), last_col=(c == len(xs) - 1))
            ry += row_h
        out.append(slide)
    return out if len(out) > 1 else out[0]


def _default_spans(ncols: int) -> list[int]:
    """12-col grid: the parameter column gets the extra width."""
    if ncols <= 1:
        return [12]
    base = 12 // ncols
    spans = [base] * ncols
    spans[0] += 12 - base * ncols
    return spans


def _col_positions(spans: list[int], x: float, w: float):
    total = sum(spans) or 1
    out, cx = [], x
    for s in spans:
        cw = w * (s / total)
        out.append((cx, cw))
        cx += cw
    return out


def _draw_cell(slide, cell, x, y, w, h, *, first_col: bool, last_col: bool):
    pad = px_in(16)
    pmids = cell.get("pmids") if isinstance(cell, dict) else None
    if pmids is None and isinstance(cell, (list, tuple)):
        pmids = [str(p) for p in cell]
    if pmids is None and isinstance(cell, str):
        found = extract_pmids(cell)
        if found and not sanitize(cell).strip():
            pmids = found

    if pmids:
        px_right = x + w - pad
        cy = y + (h - LAYOUT["chip_h_in"]) / 2
        for pmid in list(pmids)[:2][::-1]:
            used = add_pmid_pill(slide, str(pmid), 0, cy, right_edge=px_right)
            px_right -= used + px_in(6)
        return

    # Only the source column is right-aligned, and only because it holds PMID
    # pills (spec §1.4). Prose stays left-aligned whichever column it is in.
    text = sanitize(cell if isinstance(cell, str) else _flatten_text(cell))
    add_textbox(slide, text, x + pad, y + px_in(10), w - pad * 1.6,
                h - px_in(14), font_role="body", size=SIZES["table_body"],
                color=COLORS["text_body"] if first_col
                else COLORS["text_secondary"],
                bold=first_col, line_spacing=LINE_HEIGHT["card"])


# ─────────────────────────────────────────────────────────────────────────────
# 5. Decision tree
# ─────────────────────────────────────────────────────────────────────────────

def decision_tree(prs, *, title: str, cards: list, eyebrow: str = "",
                  tier: str | None = None, citations: str = "",
                  _page_num: int | None = None, _total_pages: int = 1,
                  **_ignored):
    """2-col grid of IF / THEN / BECAUSE cards. Never rendered as bullets.

    Cards are measured before they are placed. A card whose text needs more
    room than the grid row can give would otherwise render clipped, so the
    grid packs by measured height and starts a continuation slide when the
    next row will not fit.
    """
    gap = px_in(24)
    cols = 2 if len(cards or []) > 1 else 1
    card_w = (_CW - gap * (cols - 1)) / cols
    # A page is worth roughly the body height; measure against that up front.
    probe_avail = LAYOUT["footer_rule_y_in"] - LAYOUT["title_y_in"] - px_in(110)
    pages = _pack_rows(cards or [], cols, card_w, probe_avail, gap)

    out = []
    for i, page in enumerate(pages):
        eb, pn = _pages_meta(i, eyebrow, _page_num)
        slide, y, avail = _content_frame(
            prs, eyebrow=eb, title=title, tier=tier,
            right_label=CURO_LABEL, citations=citations, page_num=pn)

        rows = [page[k:k + cols] for k in range(0, len(page), cols)]
        heights = [max(_decision_card_height(c, card_w) for c in row)
                   for row in rows]
        scale = 1.0
        needed = sum(heights) + gap * (len(rows) - 1)
        if needed > avail:
            scale = avail / needed
        cy = y
        for row, row_h in zip(rows, heights):
            row_h *= scale
            for j, card in enumerate(row):
                cx = _PX + j * (card_w + gap)
                _draw_decision_card(slide, card, cx, cy, card_w, row_h)
            cy += row_h + gap
        out.append(slide)
    return out if len(out) > 1 else out[0]


def _pack_rows(cards: list, cols: int, card_w: float, avail: float,
               gap: float) -> list[list]:
    """Group cards into pages whose measured rows fit the body height."""
    pages, page, used = [], [], 0.0
    for k in range(0, len(cards), cols):
        row = cards[k:k + cols]
        row_h = max(_decision_card_height(c, card_w) for c in row)
        extra = row_h + (gap if page else 0.0)
        if page and used + extra > avail:
            pages.append(page)
            page, used = [], 0.0
            extra = row_h
        page.extend(row)
        used += extra
    if page:
        pages.append(page)
    return pages or [[]]


def _decision_card_height(card, card_w: float) -> float:
    """Predicted height of one IF/THEN/BECAUSE card at `card_w` wide."""
    pad_x, pad_y = px_in(28), px_in(26)
    iw = card_w - pad_x * 2
    total = pad_y * 2
    for chip_label, keys, _ in _DECISION_ROWS:
        text = _decision_row_text(card, keys)
        if not text:
            continue
        cw = chip_width_in(chip_label, size_px=SIZES_PX["chip"])
        tw = iw - cw - px_in(12)
        th = estimate_height_in(text, SIZES["card_body"], tw,
                                line_height=LINE_HEIGHT["card"])
        total += max(th, LAYOUT["chip_h_in"]) + px_in(14)
    return max(total, px_in(110))


def _decision_row_text(card, keys) -> str:
    if not isinstance(card, dict):
        return sanitize(str(card))
    for key in keys:
        val = card.get(key)
        if isinstance(val, str) and sanitize(val).strip():
            return sanitize(val).strip()
        if isinstance(val, (list, tuple)) and val:
            return sanitize(" ".join(str(v) for v in val))
    return ""


_DECISION_ROWS = (
    ("IF", ("if", "finding", "when", "condition", "label"), CHIP_IF),
    ("THEN", ("then", "path", "action", "how", "headline"), CHIP_THEN),
    ("BECAUSE", ("because", "implication", "why", "rationale", "tagline"),
     CHIP_BECAUSE),
)


def _draw_decision_card(slide, card, x, y, w, h):
    add_rounded_rect(slide, x, y, w, h, COLORS["card"],
                     radius_in=LAYOUT["card_radius_in"],
                     line_color=COLORS["border"], line_width_pt=0.75)
    pad_x, pad_y = px_in(28), px_in(26)
    iy = y + pad_y
    iw = w - pad_x * 2

    if not isinstance(card, dict):
        card = {"then": str(card)}

    for chip_label, keys, (chip_bg, chip_fg) in _DECISION_ROWS:
        text = _decision_row_text(card, keys)
        if not text:
            continue
        cw = add_chip(slide, chip_label, x + pad_x, iy,
                      bg=chip_bg, fg=chip_fg,
                      radius_in=LAYOUT["chip_radius_in"],
                      tracking=TRACK_CHIP)
        tx = x + pad_x + cw + px_in(12)
        tw = iw - cw - px_in(12)
        th = estimate_height_in(text, SIZES["card_body"], tw,
                                line_height=LINE_HEIGHT["card"])
        color = (COLORS["text_secondary"] if chip_label == "BECAUSE"
                 else COLORS["text_body"])
        add_textbox(slide, text, tx, iy, tw, th + px_in(4),
                    font_role="body", size=SIZES["card_body"], color=color,
                    line_spacing=LINE_HEIGHT["card"])
        iy += max(th, LAYOUT["chip_h_in"]) + px_in(14)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Chart
# ─────────────────────────────────────────────────────────────────────────────

def chart_slide(prs, *, title: str, chart, eyebrow: str = "",
                tier: str | None = None, citations: str = "",
                lead: str | None = None,
                _page_num: int | None = None, _total_pages: int = 1,
                **_ignored):
    """Render an already-verified ChartSpec. Never call this with raw numbers —
    `chart_data.detect_chartable` is the gate, and it is the only gate."""
    # The chart's own PMIDs go in the footer (spec §1.5), but the adapters
    # already harvest PMIDs from the whole spec — dedupe so a cited paper is
    # not listed twice.
    footer = citations or ""
    if chart is not None and chart.pmids:
        already = set(extract_pmids(footer))
        extra = [p for p in chart.pmids if p not in already]
        if extra:
            pmid_text = " · ".join(f"PMID {p}" for p in extra[:4])
            footer = f"{footer} · {pmid_text}" if footer else pmid_text

    slide, y, avail = _content_frame(
        prs, eyebrow=eyebrow, title=title, tier=tier,
        right_label=CURO_LABEL, lead=lead, citations=footer,
        page_num=_page_num)

    png = charts.render_chart_png(chart)
    if png:
        # Fit the rendered PNG inside the body box preserving its aspect. The
        # matplotlib output is cropped to its content, so its aspect is not
        # known ahead of time — placing it at a fixed width would stretch a
        # short chart across the slide or push a tall one through the footer.
        w, h = _CW, avail
        size = charts.png_size(png)
        if size:
            aspect = size[1] / float(size[0])
            if _CW * aspect <= avail:
                w, h = _CW, _CW * aspect
            else:
                h, w = avail, avail / aspect
        add_image_bytes(slide, png, _PX + (_CW - w) / 2, y,
                        width_in=w, height_in=h)
    return slide


# ─────────────────────────────────────────────────────────────────────────────
# 7. Key takeaways
# ─────────────────────────────────────────────────────────────────────────────

def takeaways_slide(prs, *, title: str = "", items: list | None = None,
                    eyebrow: str = "", does_not_apply: str = "",
                    citations: str = "",
                    _page_num: int | None = None, _total_pages: int = 1,
                    **_ignored):
    """2x2 grid of serif numerals + text, over a 'does not apply when' notice."""
    pages = split_cards(items or [], max_cards=BODY_BUDGET["max_takeaways"])
    notice_text = sanitize(does_not_apply or "")
    notice_h = 0.0
    if notice_text:
        notice_h = estimate_height_in(
            notice_text, SIZES["card_body"], _CW - px_in(44),
            line_height=LINE_HEIGHT["card"]) + px_in(76)

    out = []
    for i, page in enumerate(pages):
        eb, pn = _pages_meta(i, eyebrow, _page_num)
        last = (i == len(pages) - 1)
        slide, y, avail = _content_frame(
            prs, eyebrow=eb, title=title, right_label=CURO_LABEL,
            citations=citations, page_num=pn)

        grid_h = avail - (notice_h + px_in(24) if notice_h and last else 0)
        gap = px_in(28)
        cols = 2 if len(page) > 1 else 1
        cell_w = (_CW - gap * (cols - 1)) / cols
        rows_n = max(1, (len(page) + cols - 1) // cols)
        cell_h = (grid_h - gap * (rows_n - 1)) / rows_n

        for j, item in enumerate(page):
            cx = _PX + (j % cols) * (cell_w + gap)
            cy = y + (j // cols) * (cell_h + gap)
            _draw_takeaway(slide, item, j, cx, cy, cell_w, cell_h)

        if notice_text and last:
            add_notice_box(slide, notice_text, _PX,
                           y + grid_h + px_in(24), _CW, notice_h,
                           heading="Does not apply when")
        out.append(slide)
    return out if len(out) > 1 else out[0]


def _numeral_width_in(text: str, size_pt: float) -> float:
    """Predicted width of a serif numeral run, for sizing its gutter."""
    return (len(text or "") * size_pt * 0.545) / 72.0 + px_in(18)


def _draw_takeaway(slide, item, index, x, y, w, h):
    if isinstance(item, dict):
        number = sanitize(str(item.get("number") or f"{index + 1:02d}"))
        header = sanitize(item.get("header") or item.get("heading") or "")
        body = sanitize(item.get("body") or "")
    else:
        number = f"{index + 1:02d}"
        header, body = sanitize(str(item)), ""

    color = TAKEAWAY_NUMERALS[index % len(TAKEAWAY_NUMERALS)]
    # The numeral column is sized to the numeral. "01" and "96.1%" are both
    # legitimate here (stat_panel routes its numbers through this layout), and
    # a fixed 84px gutter silently overlaps the text for anything wider.
    size = SIZES["takeaway_num"]
    num_w = _numeral_width_in(number, size)
    max_w = w * 0.42
    if num_w > max_w:
        size *= max_w / num_w
        num_w = max_w
    num_w = max(num_w, px_in(84))
    add_textbox(slide, number, x, y - px_in(10), num_w, px_in(76),
                font_role="display", size=size, color=color, wrap=False)

    tx = x + num_w
    tw = w - num_w
    lines = []
    if header:
        lines.append({"text": header, "font_role": "body",
                      "size": SIZES["takeaway_body"], "bold": True,
                      "color": COLORS["text_body"],
                      "line_spacing": LINE_HEIGHT["takeaway"]})
    if body:
        lines.append({"text": body, "font_role": "body",
                      "size": SIZES["takeaway_body"],
                      "color": COLORS["text_secondary"], "space_before": 3,
                      "line_spacing": LINE_HEIGHT["takeaway"]})
    if lines:
        add_multiline_textbox(slide, lines, tx, y + px_in(4), tw, h - px_in(8))


# ─────────────────────────────────────────────────────────────────────────────
# 8. References
# ─────────────────────────────────────────────────────────────────────────────

def references_slide(prs, *, references: list, title: str = "References",
                     eyebrow: str = "", citations: str = "",
                     _page_num: int | None = None, _total_pages: int = 1,
                     **_ignored):
    """Numbered rows: title/journal/year, tier chip, PMID pill, evidence score."""
    pages = split_cards(references or [],
                        max_cards=BODY_BUDGET["max_reference_rows"])
    out = []
    for i, page in enumerate(pages):
        eb, pn = _pages_meta(i, eyebrow, _page_num)
        slide, y, avail = _content_frame(
            prs, eyebrow=eb, title=title, right_label=CURO_LABEL,
            citations=citations, page_num=pn)

        row_h = min(px_in(84), avail / max(len(page), 1))
        for j, ref in enumerate(page):
            _draw_reference_row(slide, ref,
                                i * BODY_BUDGET["max_reference_rows"] + j,
                                _PX, y, _CW, row_h)
            y += row_h
            add_hairline(slide, _PX, y, _CW, COLORS["border"])

        add_textbox(slide,
                    "Scores shown are Curo evidence scores.",
                    _PX, LAYOUT["footer_rule_y_in"] - px_in(26), _CW,
                    px_in(20), font_role="body", size=SIZES["footer"],
                    color=COLORS["text_muted"], wrap=False)
        out.append(slide)
    return out if len(out) > 1 else out[0]


def _draw_reference_row(slide, ref, index, x, y, w, h):
    if not isinstance(ref, dict):
        ref = {"citation": str(ref)}
    num = f"{index + 1}."
    add_textbox(slide, num, x, y + px_in(6), px_in(34), px_in(24),
                font_role="body", size=SIZES["references"],
                color=COLORS["text_muted"], wrap=False)

    text = sanitize(ref.get("citation") or ref.get("title") or "")
    journal = sanitize(ref.get("journal") or "")
    year = sanitize(str(ref.get("year") or ""))
    tail = " · ".join(p for p in (journal, year) if p)
    line = f"{text} · {tail}" if tail else text

    tx = x + px_in(34)
    tw = w * 0.60
    add_textbox(slide, line, tx, y + px_in(4), tw, h - px_in(10),
                font_role="body", size=SIZES["references"],
                color=COLORS["text_body"], line_spacing=LINE_HEIGHT["card"])

    right = x + w
    score = ref.get("score")
    if score not in (None, ""):
        add_textbox(slide, str(score), right - px_in(64), y + px_in(8),
                    px_in(64), px_in(22), font_role="body",
                    size=SIZES["score"], color=COLORS["text_lead"],
                    bold=True, align=PP_ALIGN.RIGHT, wrap=False)
        right -= px_in(76)

    pmid = ref.get("pmid") or (extract_pmids(_flatten_text(ref)) or [None])[0]
    if pmid:
        right -= add_pmid_pill(slide, str(pmid), 0, y + px_in(6),
                               right_edge=right) + px_in(10)

    tier = ref.get("tier") or ref.get("level_key")
    if tier and tier_key(tier):
        add_tier_chip(slide, tier, 0, y + px_in(6), right_edge=right)


# ─────────────────────────────────────────────────────────────────────────────
# 9. Notice — "module not generated, insufficient evidence"
# ─────────────────────────────────────────────────────────────────────────────

def notice_slide(prs, *, title: str = "Module not generated",
                 message: str = "Insufficient evidence",
                 eyebrow: str = "", citations: str = "",
                 heading: str = "Insufficient evidence",
                 _page_num: int | None = None, _total_pages: int = 1,
                 **_ignored):
    """A notice, not an error — the dark-theme restyle of the missing-module
    slide. No alert-red furniture: the deck is reporting a coverage fact."""
    slide, y, avail = _content_frame(
        prs, eyebrow=eyebrow, title=title, right_label=CURO_LABEL,
        citations=citations, page_num=_page_num)
    add_notice_box(slide, message, _PX, y, _CW,
                   min(avail, px_in(180)), heading=heading)
    return slide


# ─────────────────────────────────────────────────────────────────────────────
# Adapters — the vocabulary generate_slides_specs() emits
# ─────────────────────────────────────────────────────────────────────────────

def objectives_slide(prs, *, title: str = "", items: list | None = None,
                     eyebrow: str = "", closing_callout: str | None = None,
                     _source_text: str | None = None, **kw):
    """Learning goals -> content bullets."""
    return content_slide(prs, title=title, eyebrow=eyebrow,
                         bullets=items or [], lead=closing_callout,
                         citations=_citation_fields(kw), **_page_kw(kw))


def cascade_slide(prs, *, title: str = "", steps: list | None = None,
                  eyebrow: str = "", footer_callout: str | None = None,
                  _source_text: str | None = None, **kw):
    """Sequential steps -> numbered content bullets."""
    return content_slide(prs, title=title, eyebrow=eyebrow,
                         bullets=steps or [], lead=footer_callout,
                         citations=_citation_fields(kw), **_page_kw(kw))


def two_column_compare(prs, *, title: str = "", left_card: dict | None = None,
                       right_card: dict | None = None, eyebrow: str = "",
                       caption: str | None = None,
                       _source_text: str | None = None, **kw):
    """Two competing approaches -> two cards in the decision-card grid."""
    cards = [c for c in (left_card, right_card) if c]
    spec = dict(kw)
    spec["caption"] = caption or ""
    return decision_tree(prs, title=title, eyebrow=eyebrow,
                         cards=[_compare_card(c) for c in cards],
                         citations=_citation_fields(spec), **_page_kw(kw))


def _compare_card(card: dict) -> dict:
    """Map a compare card onto the IF/THEN/BECAUSE card.

    The `lines` list is joined with a middot rather than a space: the entries
    are separate clinical statements, and running them together reads as one
    sentence the source never wrote. The separator is punctuation, not text.
    """
    verdict = card.get("verdict") or {}
    lines = [str(l).strip().rstrip(".") for l in (card.get("lines") or [])
             if str(l).strip()]
    return {
        "if": card.get("label") or "",
        "then": card.get("headline") or "",
        "because": " · ".join(lines) or (verdict.get("text") or ""),
    }


def three_route_grid(prs, *, title: str = "", routes: list | None = None,
                     eyebrow: str = "", _source_text: str | None = None, **kw):
    """Three parallel options -> the decision-card grid."""
    cards = []
    for route in (routes or []):
        if not isinstance(route, dict):
            continue
        cards.append({
            "if": route.get("when") or route.get("tagline") or "",
            "then": route.get("name") or "",
            "because": route.get("how") or "",
        })
    return decision_tree(prs, title=title, eyebrow=eyebrow, cards=cards,
                         citations=_citation_fields(
                             {**kw, "routes": routes or []}),
                         **_page_kw(kw))


def decision_table(prs, *, title: str = "", rows: list | None = None,
                   eyebrow: str = "", footer_caption: str | None = None,
                   _source_text: str | None = None, **kw):
    """finding -> implication -> action, as the bordered table."""
    headers = ["Finding", "Implication", "Favoured path"]
    table_rows = []
    for row in (rows or []):
        if isinstance(row, dict):
            table_rows.append([row.get("finding", ""),
                               row.get("implication", ""),
                               row.get("path", "")])
        elif isinstance(row, (list, tuple)):
            table_rows.append(list(row)[:3])
    spec = dict(kw)
    spec["footer_caption"] = footer_caption or ""
    return table_slide(prs, title=title, eyebrow=eyebrow, headers=headers,
                       rows=table_rows, col_spans=[4, 4, 4],
                       citations=_citation_fields(spec), **_page_kw(kw))


def stat_panel(prs, *, title: str = "", primary_stat: str = "",
               primary_label: str = "", secondary_stat: str | None = None,
               secondary_label: str | None = None, eyebrow: str = "",
               callout: str | None = None, citation: str | None = None,
               _source_text: str | None = None, **kw):
    """Big numbers. A chart ONLY if the values are verbatim in the source.

    THREE OR MORE ARMS. `primary_stat`/`secondary_stat` can only hold two, so
    a three-concentration or four-wavelength comparison — the laser deck's
    best chart — had nowhere to go: the spec dict assembled here listed only
    the two-arm keys, so `categories`/`values` never reached
    `detect_chartable` and `_from_explicit_chart` never fired. `arms` is the
    generator-facing shape ([{label, stat}, ...]); it is mapped onto the
    categories/values the detector already understands, and it passes exactly
    the same gates as the two-arm path (every value verbatim in the source
    text, one quantity, one unit, no ranges, PMIDs into the footer).
    """
    arms = [a for a in (kw.get("arms") or []) if isinstance(a, dict)]
    categories = kw.get("categories") or [a.get("label") or a.get("name") or ""
                                          for a in arms]
    arm_values = kw.get("values") or [a.get("stat") for a in arms]
    categories = [c for c in (categories or [])]
    arm_values = [v for v in (arm_values or [])]

    spec = {
        "title": title, "primary_stat": primary_stat,
        "primary_label": primary_label, "secondary_stat": secondary_stat,
        "secondary_label": secondary_label, "citation": citation or "",
        "callout": callout or "",
    }
    if len(categories) >= 2 and len(categories) == len(arm_values):
        spec["categories"] = categories
        spec["values"] = arm_values
        if kw.get("unit"):
            spec["unit"] = kw["unit"]
    chart = chart_data.detect_chartable(spec, _source_text)
    if chart is not None:
        return chart_slide(prs, title=title, eyebrow=eyebrow, chart=chart,
                           lead=callout, citations=_citation_fields(spec),
                           **_page_kw(kw))

    # No verified chart. The values still belong on the slide — they are the
    # slide's content — they are simply not plotted, because plotting them
    # would assert a comparison the source text does not support.
    # Arms are content whether or not they could be plotted: a refused chart
    # must not silently delete the numbers the slide is about.
    pairs = [(primary_stat, primary_label), (secondary_stat, secondary_label)]
    if len(categories) >= 2 and len(categories) == len(arm_values):
        pairs = list(zip(arm_values, categories))
    pairs = [(sanitize(str(s)), sanitize(str(l or ""))) for s, l in pairs if s]

    # The generator does not always put a NUMBER in a "stat" field; real decks
    # come back with "Lowest" or "Lab only". A word is not a numeral, and
    # rendering it at 54pt serif in the numeral gutter overruns the text beside
    # it, so a non-numeric stat becomes a bold bullet lead instead.
    if pairs and all(_is_numeric_stat(s) for s, _ in pairs):
        items = [{"number": s, "header": l, "body": ""} for s, l in pairs]
        return takeaways_slide(prs, title=title, eyebrow=eyebrow, items=items,
                               does_not_apply=sanitize(callout or ""),
                               citations=_citation_fields(spec), **_page_kw(kw))

    bullets = [{"header": s, "body": l} for s, l in pairs]
    return content_slide(prs, title=title, eyebrow=eyebrow, bullets=bullets,
                         lead=sanitize(callout or ""),
                         citations=_citation_fields(spec), **_page_kw(kw))


def _is_numeric_stat(text: str) -> bool:
    """True when a stat field actually holds a number the numeral slot can take."""
    text = (text or "").strip()
    if not text or len(text) > 12:
        return False
    return chart_data.parse_number(text) is not None


def evidence_summary(prs, *, title: str = "",
                     hierarchy_rows: list | None = None,
                     trap_callout: dict | None = None, eyebrow: str = "",
                     _source_text: str | None = None, **kw):
    """Evidence hierarchy -> chart when verified, otherwise the table."""
    spec = {"title": title, "hierarchy_rows": hierarchy_rows or [],
            **{k: v for k, v in kw.items() if isinstance(v, str)}}
    chart = chart_data.detect_chartable(spec, _source_text)
    if chart is not None:
        return chart_slide(prs, title=title, eyebrow=eyebrow, chart=chart,
                           citations=_citation_fields(spec), **_page_kw(kw))

    # "stat" is optional per row, and the generator is told to omit it rather
    # than write a verdict word there — so a whole evidence hierarchy with no
    # comparable number in it is the NORMAL outcome, not an edge case (all six
    # evidence_summary slides in the cached specs are stat-free). Keeping the
    # column then printed a "Reported" header over four or five blank cells,
    # which reads as "these studies reported nothing" rather than "this deck
    # is not quoting a number here". Drop the column instead, and give its
    # width to the description.
    rows = []
    any_stat = False
    for row in (hierarchy_rows or []):
        if not isinstance(row, dict):
            continue
        stat = sanitize(str(row.get("stat") or "")).strip()
        any_stat = any_stat or bool(stat)
        rows.append([row.get("tier_label", ""), row.get("description", ""), stat])

    if any_stat:
        headers = ["Tier", "What the studies are", "Reported"]
        col_spans = [3, 6, 3]
    else:
        headers = ["Tier", "What the studies are"]
        col_spans = [3, 9]
        rows = [r[:2] for r in rows]

    # Measure the trap notice FIRST and reserve its band, so the table is laid
    # out above it rather than under it.
    notice_text = notice_heading = ""
    notice_h = 0.0
    if trap_callout:
        body = sanitize(trap_callout.get("body", ""))
        stat = sanitize(str(trap_callout.get("stat") or ""))
        label = sanitize(trap_callout.get("stat_label", ""))
        notice_text = " · ".join(
            p for p in (body, f"{stat} {label}".strip()) if p)
        notice_heading = sanitize(trap_callout.get("heading") or "") \
            or "Read this before quoting the headline"
        if notice_text:
            inner_w = _CW - px_in(44)
            notice_h = estimate_height_in(
                notice_text, SIZES["card_body"], inner_w,
                line_height=LINE_HEIGHT["card"]) + px_in(76)

    result = table_slide(prs, title=title, eyebrow=eyebrow, headers=headers,
                         rows=rows, col_spans=col_spans,
                         citations=_citation_fields(spec),
                         reserve_bottom=notice_h + px_in(20) if notice_h else 0.0,
                         **_page_kw(kw))

    if notice_text:
        slide = result[-1] if isinstance(result, list) else result
        add_notice_box(slide, notice_text, _PX,
                       LAYOUT["footer_rule_y_in"] - px_in(22) - notice_h,
                       _CW, notice_h, heading=notice_heading)
    return result


def _page_kw(kw: dict) -> dict:
    """Pass the builder's page metadata through an adapter untouched."""
    out = {}
    if "_page_num" in kw:
        out["_page_num"] = kw["_page_num"]
    if "_total_pages" in kw:
        out["_total_pages"] = kw["_total_pages"]
    return out


__all__ = [
    "title_slide", "section_divider", "content_slide", "table_slide",
    "decision_tree", "chart_slide", "takeaways_slide", "references_slide",
    "notice_slide",
    # adapters for the generator's vocabulary
    "objectives_slide", "cascade_slide", "two_column_compare",
    "three_route_grid", "decision_table", "stat_panel", "evidence_summary",
]
