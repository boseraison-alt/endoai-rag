"""The eight approved layouts (PRESENTATION_WORKLIST.md §1.4), as HTML.

`generate_slides_specs()` emits ten PATTERNS; §1.4 approves eight LAYOUTS.
They are not the same list, so `LAYOUT_FOR_PATTERN` below maps one onto the
other and the mapping is the only place that decision lives. Nothing in this
module writes clinical prose: every string on a slide is copied out of the
spec, and the only text this file originates is furniture (page numbers, the
"MODULE n OF m" eyebrow, the IF / THEN / BECAUSE chip labels, column headers).

Body budget (§1.3) — max 5 bullets or one table or one figure per slide, about
25 words of bullet text — is enforced by SPLITTING, never by truncating. A
long bullet costs more than one slot and pushes its neighbours to a
continuation slide; the words themselves are never edited, because editing
them would be authoring.
"""
from __future__ import annotations

import math
import re

from . import tokens as T
from .citations import (esc, extract_pmids, footer_citation, pill_html,
                        render_inline, strip_markers)

# ── body budget ──────────────────────────────────────────
BULLET_SLOTS_PER_SLIDE = 5      # §1.3 "max 5 bullets"
WORDS_PER_SLOT         = 25     # §1.3 "~25 words of bullet text"
TABLE_ROWS_PER_SLIDE   = 6
CARDS_PER_SLIDE        = 4      # §1.4 #5 "2-col grid of cards"
TAKEAWAYS_PER_SLIDE    = 4      # §1.4 #7 "2×2 grid"
REFERENCE_ROWS_PER_SLIDE = 7

# spec pattern → approved layout (§1.4)
LAYOUT_FOR_PATTERN = {
    "title_slide":        "title",
    "section_divider":    "divider",
    "objectives_slide":   "content",
    "cascade_slide":      "content",
    "bullets":            "content",
    # A two-way comparison IS a table: two labelled columns of paired lines.
    # §1.4 #5 reserves the card grid for IF/THEN/BECAUSE rules and says it must
    # never be filled with bullets, which is what a comparison would become.
    "two_column_compare": "table",
    "three_route_grid":   "decision",
    "decision_table":     "decision",
    "stat_panel":         "chart",
    "evidence_summary":   "table",
    "takeaways_slide":    "takeaways",
    "references":         "references",
    "notice":             "notice",
}
DEFAULT_LAYOUT = "content"


def slot_cost(text: str) -> int:
    """How much of a slide's five-slot budget one bullet consumes."""
    words = len((text or "").split())
    return max(1, math.ceil(words / WORDS_PER_SLOT))


def split_by_budget(items, text_of=lambda x: x, max_slots=BULLET_SLOTS_PER_SLIDE):
    """Group items into slides without editing any of them.

    A single item wider than the whole budget still gets its own slide — the
    alternative is dropping or trimming clinical text, which the prime rule
    forbids.
    """
    pages, page, used = [], [], 0
    for item in items or []:
        cost = slot_cost(text_of(item))
        if page and used + cost > max_slots:
            pages.append(page)
            page, used = [], 0
        page.append(item)
        used += cost
    if page:
        pages.append(page)
    return pages or [[]]


def chunk(items, size):
    items = list(items or [])
    if not items:
        return [[]]
    return [items[i:i + size] for i in range(0, len(items), size)]


# ── §1.5 chart hard rules ────────────────────────────────
_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def value_is_cited(value: str, source_text: str) -> bool:
    """§1.5: every plotted value must appear verbatim in the cited text.

    "Verbatim" is checked on the NUMBER, not the whole label: the spec writes
    "96.1%" where the answer may write "96.1 %" or "96.1% of cases". Anything
    with no number in it is not plottable at all.
    """
    nums = _NUM.findall(str(value or ""))
    if not nums:
        return False
    haystack = source_text or ""
    return all(n in haystack for n in nums)


def _as_float(value):
    m = _NUM.search(str(value or ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def chart_kind(values) -> str:
    """§1.5 grammar: dot plot for near-equal comparisons, bar for magnitude
    comparisons from zero."""
    nums = [v for v in (_as_float(v) for v in values) if v is not None]
    if len(nums) < 2:
        return "bar"
    hi, lo = max(nums), min(nums)
    if hi <= 0:
        return "bar"
    return "dot" if (hi - lo) / hi < 0.10 else "bar"


# ── shared furniture (§1.3) ──────────────────────────────
def _tier_chip(slot: str, label: str | None = None) -> str:
    bg, fg = T.chip_colors(slot)
    name = label or T.TIER_NAME.get(slot, "Curo")
    return (f'<span class="tier-chip" style="background:{bg};color:{fg}">'
            f'<i class="chip-dot" style="background:{T.chart_color_dark(slot)}"></i>'
            f'{esc(name)}</span>')


def _curo_chip() -> str:
    return ('<span class="tier-chip curo-chip">'
            f'<i class="chip-dot" style="background:{T.DARK["accent-cyan"]}"></i>CURO</span>')


def _header(eyebrow: str, right_html: str) -> str:
    return ('<header class="furniture-head">'
            f'<span class="eyebrow">{esc(strip_markers(eyebrow or ""))}</span>'
            f'{right_html}</header>')


def _footer(pmids, papers, page_no) -> str:
    """§1.3 footer: short citations left, page number right.

    The citations are the clickable pills of §3.2 rather than dead text — the
    generator keeps provenance markers out of slide bodies, so the footer is
    where a clinician can actually reach the source from.
    """
    cites = "".join(
        f'<button type="button" class="cite-pill foot-pill" data-pmid="{esc(p)}" '
        f'title="Show source abstract (PMID {esc(p)})">'
        f'{esc(footer_citation(p, papers))}</button>' for p in pmids[:3])
    return ('<footer class="furniture-foot">'
            f'<div class="foot-cites">{cites}</div>'
            f'<div class="foot-page">{esc(page_no)}</div></footer>')


def _pill_row(pmids, papers) -> str:
    if not pmids:
        return ""
    return ('<div class="pill-row">'
            + "".join(pill_html(p, papers) for p in pmids)
            + "</div>")


def _is_light(hex_color: str) -> bool:
    """WCAG relative luminance, used only to pick black-or-white ink on a
    coloured chip. The 0.42 cut is where #a78bfa (Level III) lands on the
    light side and #0891b2 (Level I) on the dark side."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b) > 0.42


# ── evidence-shape bar (§1.4 #1 — MANDATORY on every deck) ──
def evidence_shape(tier_counts: dict) -> str:
    """The product signature: a light card carrying the deck's paper mix.

    When no tier data reached the exporter the card still renders, and says
    so. A silently-absent card and a card that ran clean would look identical
    otherwise — the failure mode HANDOVER.md calls bug class (d).
    """
    counts = {k: int(v) for k, v in (tier_counts or {}).items() if int(v or 0) > 0}
    total = sum(counts.values())

    if not total:
        return ('<div class="evidence-card">'
                '<div class="ev-label-row"><span class="ev-label">EVIDENCE SHAPE</span>'
                '<span class="ev-total">not available</span></div>'
                '<div class="ev-bar"><span class="ev-seg ev-seg-empty" '
                'style="flex-grow:1"></span></div>'
                '<div class="ev-legend"><span class="ev-legend-item">'
                '<i class="ev-swatch" style="background:#94a3b8"></i>'
                'Tier breakdown unavailable for this export</span></div></div>')

    ordered = [s for s in T.TIER_SLOTS if s in counts]
    if "other" in counts:
        ordered.append("other")

    segs, legend = [], []
    for slot in ordered:
        n = counts[slot]
        color = T.chart_color_light(slot)
        name = T.TIER_NAME.get(slot, slot)
        # Level III's fill is the light lavender of the CVD-validated set, so a
        # white in-segment label on it fails contrast outright — and Level III
        # is exactly the tier §1.2 says must ALWAYS carry its label.
        ink = "#1b2033" if _is_light(color) else "#ffffff"
        label = (f'<span class="ev-seg-label" style="color:{ink}">{esc(name)}</span>'
                 if (slot in T.ALWAYS_LABEL or n / total >= 0.16) else "")
        segs.append(f'<span class="ev-seg" style="flex-grow:{n};background:{color}" '
                    f'title="{esc(name)}: {n}">{label}</span>')
        legend.append('<span class="ev-legend-item">'
                      f'<i class="ev-swatch" style="background:{color}"></i>'
                      f'{esc(name)}<b>{n}</b></span>')

    return ('<div class="evidence-card">'
            '<div class="ev-label-row"><span class="ev-label">EVIDENCE SHAPE</span>'
            f'<span class="ev-total">{total} papers scored and banded</span></div>'
            f'<div class="ev-bar">{"".join(segs)}</div>'
            f'<div class="ev-legend">{"".join(legend)}</div></div>')


# ── layout 1: title ──────────────────────────────────────
def layout_title(s, ctx) -> str:
    title = strip_markers(s.get("title") or ctx["question"])
    subtitle = strip_markers(s.get("subtitle") or "")
    tagline = strip_markers(s.get("tagline") or "")
    eyebrow = strip_markers(s.get("eyebrow") or "CURO · CLINICAL EVIDENCE DECK")
    disclaimer = ("Evidence tiers are Curo bandings of the retrieved literature. "
                  "Every figure on every slide is quoted from the cited papers.")
    return (
        '<div class="frame frame-title">'
        '<div class="wordmark-row">'
        '<span class="wordmark">Curo</span>'
        '<span class="wordmark-rule"></span>'
        f'<span class="wordmark-eyebrow">{esc(eyebrow)}</span>'
        '</div>'
        f'<h1 class="title-main">{esc(title).replace(chr(10), "<br>")}</h1>'
        + (f'<p class="title-sub">{esc(subtitle)}</p>' if subtitle else "")
        + (f'<p class="title-tagline">{esc(tagline)}</p>' if tagline else "")
        + (f'<p class="title-meta">{esc(strip_markers(s.get("footer_metadata")))}</p>'
           if s.get("footer_metadata") else "")
        + evidence_shape(ctx.get("tier_counts") or {})
        + f'<p class="title-disclaimer">{esc(disclaimer)}</p>'
        '</div>')


# ── layout 2: section divider ────────────────────────────
def layout_divider(s, ctx) -> str:
    label = strip_markers(s.get("module_label") or "")
    m = re.search(r"(\d+)", label)
    number = m.group(1) if m else ""
    total = ctx.get("module_total") or 0
    idx = ctx.get("module_index") or (int(number) if number.isdigit() else 0)
    eyebrow = f"MODULE {idx} OF {total}" if (idx and total) else (label or "MODULE")

    topics = [strip_markers(t) for t in (s.get("topics") or []) if strip_markers(t)]
    if not topics:
        sub = strip_markers(s.get("module_subtitle") or "")
        topics = [sub] if sub else []
    ticks = "".join(f'<li><i class="tick"></i><span>{esc(t)}</span></li>'
                    for t in topics[:3])

    caveat = strip_markers(s.get("module_subtitle") or s.get("caveat")
                           or s.get("footer") or "")
    slot = ctx.get("slide_tier") or "other"
    chip = _curo_chip() if slot == "other" else _tier_chip(slot)
    return (
        '<div class="frame frame-divider">'
        f'<div class="divider-num">{esc(number)}</div>'
        '<div class="divider-col">'
        f'<div class="divider-eyebrow">{esc(eyebrow)}</div>'
        f'<h2 class="divider-title">{esc(strip_markers(s.get("module_title") or ""))}</h2>'
        + (f'<ul class="divider-ticks">{ticks}</ul>' if ticks else "")
        + '</div>'
        '<div class="divider-foot">'
        + chip
        + (f'<span class="divider-caveat">{esc(caveat)}</span>' if caveat else "")
        + '</div></div>')


# ── layout 3: content ────────────────────────────────────
def _figure_svg(fig) -> str:
    """The §1.4 #3 figure slot. Only `canal_emission` — the approved worked
    example — is drawn; an unknown kind renders nothing rather than a guess."""
    if not isinstance(fig, dict) or fig.get("kind") != "canal_emission":
        return ""
    left = esc(fig.get("left_label") or "Full-wall coverage")
    right = esc(fig.get("right_label") or "Forward cone only")

    def canal(x, radial):
        rays = ("".join(
            f'<line x1="{x + 30}" y1="{y}" x2="{x + 4}" y2="{y}"/>'
            f'<line x1="{x + 30}" y1="{y}" x2="{x + 56}" y2="{y}"/>'
            for y in range(120, 231, 22))
            if radial else
            f'<path d="M{x + 30} 120 L{x + 6} 236 L{x + 54} 236 Z"/>')
        return (f'<path d="M{x} 40 L{x + 8} 250 L{x + 52} 250 L{x + 60} 40 Z"/>'
                f'<line x1="{x + 30}" y1="60" x2="{x + 30}" y2="{"120" if radial else "120"}"/>'
                f'<g class="ray">{rays}</g>')

    return ('<figure class="slide-figure">'
            '<svg viewBox="0 0 300 290" role="img" aria-label="Fibre emission comparison">'
            f'<g class="canal">{canal(20, True)}{canal(180, False)}</g></svg>'
            '<figcaption>'
            f'<span class="cap-chip cap-ok">{left}</span>'
            f'<span class="cap-chip cap-warn">{right}</span>'
            '</figcaption></figure>')


def layout_content(s, ctx) -> str:
    bullets = s.get("_bullets") or []
    lead = strip_markers(s.get("lead") or s.get("closing_callout") or "")
    fig = _figure_svg(s.get("figure"))

    items = []
    for b in bullets:
        if isinstance(b, dict):
            number = b.get("number") or ""
            head = b.get("header") or ""
            body = b.get("body") or ""
            inner = ""
            if number:
                inner += f'<span class="b-num">{esc(strip_markers(str(number)))}</span>'
            if head:
                inner += f'<span class="b-head">{render_inline(head, ctx["papers"])}</span>'
            if body:
                inner += f'<span class="b-body">{render_inline(body, ctx["papers"])}</span>'
            items.append(f'<li class="bullet has-parts">{inner}</li>')
        else:
            items.append(f'<li class="bullet">{render_inline(str(b), ctx["papers"])}</li>')

    return (
        f'<h2 class="slide-title">{esc(strip_markers(s.get("title") or ""))}</h2>'
        + (f'<p class="slide-lead">{render_inline(lead, ctx["papers"])}</p>' if lead else "")
        + f'<div class="slide-body{" with-figure" if fig else ""}">'
        f'<ul class="bullets">{"".join(items)}</ul>{fig}</div>')


# ── layout 4: table ──────────────────────────────────────
def layout_table(s, ctx) -> str:
    columns = s.get("_columns") or []
    rows = s.get("_rows") or []
    notice = strip_markers(s.get("_notice") or "")

    head = "".join(f'<div class="th" style="grid-column:span {c["span"]}">'
                   f'{esc(c["label"])}</div>' for c in columns)
    body = []
    for i, row in enumerate(rows):
        cells = []
        for c, cell in zip(columns, row):
            cls = "td" + (" td-key" if c.get("key") else "") + \
                  (" td-src" if c.get("source") else "")
            cells.append(f'<div class="{cls}" style="grid-column:span {c["span"]}">'
                         f'{cell}</div>')
        body.append(f'<div class="tr{" zebra" if i % 2 else ""}">{"".join(cells)}</div>')

    return (
        f'<h2 class="slide-title">{esc(strip_markers(s.get("title") or ""))}</h2>'
        '<div class="slide-body">'
        f'<div class="grid-table"><div class="tr th-row">{head}</div>'
        f'{"".join(body)}</div>'
        + (('<div class="notice-box">'
            + (f'<div class="notice-label">{esc(s.get("_notice_label"))}</div>'
               if s.get("_notice_label") else "")
            + f'<div class="notice-text">{render_inline(notice, ctx["papers"])}</div>'
            '</div>') if notice else "")
        + '</div>')


# ── layout 5: decision tree ──────────────────────────────
def _chip(kind: str) -> str:
    bg, fg = {"IF": T.CHIP_IF, "THEN": T.CHIP_THEN, "BECAUSE": T.CHIP_BECAUSE}[kind]
    return f'<span class="itb-chip" style="background:{bg};color:{fg}">{kind}</span>'


def layout_decision(s, ctx) -> str:
    cards = []
    for card in (s.get("_cards") or []):
        rows = []
        for kind in ("IF", "THEN", "BECAUSE"):
            text = card.get(kind.lower())
            if not text:
                continue
            rows.append(f'<div class="itb-row">{_chip(kind)}'
                        f'<span class="itb-text">{render_inline(text, ctx["papers"])}</span>'
                        '</div>')
        label = card.get("label")
        cards.append('<div class="dt-card">'
                     + (f'<div class="dt-card-label">{esc(strip_markers(label))}</div>'
                        if label else "")
                     + "".join(rows) + '</div>')

    caption = strip_markers(s.get("_caption") or "")
    return (
        f'<h2 class="slide-title">{esc(strip_markers(s.get("title") or ""))}</h2>'
        '<div class="slide-body">'
        f'<div class="dt-grid">{"".join(cards)}</div>'
        + (f'<p class="dt-caption">{render_inline(caption, ctx["papers"])}</p>'
           if caption else "")
        + '</div>')


# ── layout 6: chart ──────────────────────────────────────
def _wrap_tspans(text, x, y, width=20, max_lines=2, dy=15):
    """SVG has no text wrapping. An axis label that overflows is elided HERE
    only — `layout_chart` also prints every label verbatim beneath the chart,
    so no word is lost from the slide."""
    words, lines, cur = str(text or "").split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:width - 1].rstrip() + "…"
    return "".join(f'<tspan x="{x:.1f}" dy="{0 if i == 0 else dy}">{esc(l)}</tspan>'
                   for i, l in enumerate(lines))


def _bar_svg(series) -> str:
    vals = [v for _, v, _ in series]
    hi = max(vals) or 1
    w, h = 760, 250
    n = len(series)
    slot = w / max(n, 1)
    bw = min(120, slot * 0.5)
    bars, labels, grid = [], [], []
    for i in range(5):
        y = h - (h * i / 4)
        grid.append(f'<line x1="0" y1="{y:.1f}" x2="{w}" y2="{y:.1f}" class="grid"/>')
    for i, (name, value, raw) in enumerate(series):
        bh = (value / hi) * (h - 34)
        x = slot * i + (slot - bw) / 2
        y = h - bh
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                    f'height="{bh:.1f}" rx="3" fill="{T.CHART_SERIES}"/>')
        labels.append(f'<text x="{x + bw / 2:.1f}" y="{y - 10:.1f}" '
                      f'class="v-label" text-anchor="middle">{esc(raw)}</text>')
        cx = x + bw / 2
        labels.append(f'<text y="{h + 22:.1f}" class="x-label" text-anchor="middle">'
                      f'<title>{esc(name)}</title>{_wrap_tspans(name, cx, h + 22)}</text>')
    return (f'<svg class="chart" viewBox="0 0 {w} {h + 56}" role="img">'
            f'{"".join(grid)}{"".join(bars)}{"".join(labels)}'
            f'<line x1="0" y1="{h}" x2="{w}" y2="{h}" class="axis"/></svg>')


def _dot_svg(series) -> str:
    vals = [v for _, v, _ in series]
    hi, lo = max(vals), min(vals)
    pad = max((hi - lo) * 0.6, hi * 0.01, 0.5)
    lo_axis, hi_axis = lo - pad, hi + pad
    w, h = 760, 220
    step = h / (len(series) + 1)
    rows = []
    for i, (name, value, raw) in enumerate(series):
        y = step * (i + 1)
        x = 200 + ((value - lo_axis) / (hi_axis - lo_axis)) * (w - 260)
        rows.append(f'<line x1="200" y1="{y:.1f}" x2="{w - 40}" y2="{y:.1f}" class="grid"/>')
        rows.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="{T.CHART_SERIES}"/>')
        rows.append(f'<text y="{y - 2:.1f}" class="x-label" text-anchor="end">'
                    f'<title>{esc(name)}</title>{_wrap_tspans(name, 188)}</text>')
        rows.append(f'<text x="{x:.1f}" y="{y - 16:.1f}" class="v-label" '
                    f'text-anchor="middle">{esc(raw)}</text>')
    note = f"axis starts at {lo_axis:g}"
    return (f'<svg class="chart" viewBox="0 0 {w} {h + 26}" role="img">{"".join(rows)}'
            f'<text x="200" y="{h + 18}" class="axis-note">{esc(note)}</text></svg>')


def layout_chart(s, ctx) -> str:
    series = s.get("_series") or []
    kind = s.get("_chart_kind") or chart_kind([raw for _, _, raw in series])
    svg = _dot_svg(series) if kind == "dot" else _bar_svg(series)
    callout = strip_markers(s.get("callout") or "")
    label = strip_markers(s.get("_axis_label") or "")
    # Every label verbatim, so the elision inside the SVG never loses a word.
    legend = "".join(
        f'<span class="chart-key"><i style="background:{T.CHART_SERIES}"></i>'
        f'{esc(raw)} — {esc(name)}</span>' for name, _v, raw in series)
    return (
        f'<h2 class="slide-title">{esc(strip_markers(s.get("title") or ""))}</h2>'
        + (f'<p class="slide-lead">{esc(label)}</p>' if label else "")
        + f'<div class="slide-body chart-body">{svg}'
        + f'<div class="chart-keys">{legend}</div>'
        + (f'<p class="chart-callout">{render_inline(callout, ctx["papers"])}</p>'
           if callout else "")
        + '</div>')


# ── layout 7: key takeaways ──────────────────────────────
def layout_takeaways(s, ctx) -> str:
    cells = []
    for i, item in enumerate(s.get("_items") or []):
        color = T.TAKEAWAY_NUMERALS[i % len(T.TAKEAWAY_NUMERALS)]
        number = strip_markers(str(item.get("number") or (i + 1)))
        text = item.get("body") or ""
        header = item.get("header") or ""
        joined = f"**{header}** {text}".strip() if header else text
        cells.append(f'<div class="tk-cell">'
                     f'<span class="tk-num" style="color:{color}">{esc(number)}</span>'
                     f'<span class="tk-text">{render_inline(joined, ctx["papers"])}</span>'
                     '</div>')
    notice = strip_markers(s.get("_notice") or "")
    return (
        f'<h2 class="slide-title">{esc(strip_markers(s.get("title") or ""))}</h2>'
        '<div class="slide-body">'
        f'<div class="tk-grid">{"".join(cells)}</div>'
        + ('<div class="notice-box"><div class="notice-label">DOES NOT APPLY WHEN</div>'
           f'<div class="notice-text">{render_inline(notice, ctx["papers"])}</div></div>'
           if notice else "")
        + '</div>')


# ── layout 8: references ─────────────────────────────────
def layout_references(s, ctx) -> str:
    rows = []
    for ref in (s.get("_refs") or []):
        slot = T.slot_for(ref.get("level_key"))
        score = ref.get("score")
        rows.append(
            '<div class="ref-row">'
            f'<span class="ref-n">{esc(ref["n"])}</span>'
            '<span class="ref-main">'
            f'<span class="ref-title">{esc(ref.get("title") or "Title unavailable")}</span>'
            f'<span class="ref-meta">{esc(ref.get("meta") or "")}</span></span>'
            f'<span class="ref-chip">{_tier_chip(slot)}</span>'
            # The row already carries the title, journal and year, so the pill
            # only needs to be the handle onto the abstract.
            f'{pill_html(ref["pmid"], ctx["papers"], label="PMID " + str(ref["pmid"]), extra_class="ref-pill")}'
            f'<span class="ref-score">{esc(f"{score:.0f}" if isinstance(score, (int, float)) else "—")}</span>'
            '</div>')
    return (
        f'<h2 class="slide-title">{esc(strip_markers(s.get("title") or "References"))}</h2>'
        f'<div class="slide-body"><div class="ref-list">{"".join(rows)}</div>'
        '<p class="ref-note">Scores are Curo evidence scores, not journal metrics.</p>'
        '</div>')


# ── the restyled "module not generated" notice ───────────
def layout_notice(s, ctx) -> str:
    return (
        f'<h2 class="slide-title">{esc(strip_markers(s.get("title") or ""))}</h2>'
        '<div class="slide-body">'
        '<div class="notice-box notice-big">'
        '<div class="notice-label">MODULE NOT GENERATED — INSUFFICIENT EVIDENCE</div>'
        f'<div class="notice-text">{render_inline(s.get("body") or "", ctx["papers"])}</div>'
        '</div></div>')


LAYOUT_RENDERERS = {
    "title":      layout_title,
    "divider":    layout_divider,
    "content":    layout_content,
    "table":      layout_table,
    "decision":   layout_decision,
    "chart":      layout_chart,
    "takeaways":  layout_takeaways,
    "references": layout_references,
    "notice":     layout_notice,
}
