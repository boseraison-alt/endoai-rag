"""
Endo AI — Slide Pattern Library
=================================
Ten named layout functions. Each accepts structured content dicts and writes
one fully-composed slide into the supplied Presentation object.

All coordinates are in inches, all sizes in points. Every color/font/size is
read from design_tokens — no magic numbers here.

Pattern signatures follow the spec in the implementation plan. Optional keyword
args default to sensible values so callers only supply what varies per slide.
"""

from __future__ import annotations

from pptx.enum.text import PP_ALIGN

from presentations.design_tokens import COLORS, FONTS, SIZES, LAYOUT, SEMANTIC
from presentations.slide_helpers import (
    new_presentation, blank_slide,
    hex_rgb, set_font,
    add_textbox, add_multiline_textbox,
    add_eyebrow, add_title, add_body, add_footer,
    add_filled_rect, add_circle, add_concentric_circles,
    add_callout_box, add_left_accent_bar,
    add_icon_glyph, add_icon_in_circle,
)

# ── convenience ───────────────────────────────────────────────────────────────
_W  = LAYOUT["slide_w_in"]
_H  = LAYOUT["slide_h_in"]
_MX = LAYOUT["margin_x_in"]
_MY = LAYOUT["margin_y_in"]


# ─────────────────────────────────────────────────────────────────────────────
# 1. title_slide
# ─────────────────────────────────────────────────────────────────────────────

def title_slide(
    prs,
    *,
    eyebrow: str,
    title: str,
    subtitle: str,
    tagline: str = "",
    footer_metadata: str = "",
    motif_color: str | None = None,
    _page_num: int = 1,
    _total_pages: int = 1,
):
    """
    Dark teal hero slide.

    Layout:
      • Concentric circles — top-right decorative motif
      • Eyebrow — coral, top-left, ALL-CAPS
      • Big serif italic title (44 pt)
      • Subtitle — muted white, 24 pt sans
      • Thin coral rule
      • Tagline — cream callout box (if supplied)
      • Footer metadata line at bottom
    """
    if motif_color is None:
        motif_color = COLORS["rule_on_dark"]

    slide = blank_slide(prs)

    # ── Background ──
    add_filled_rect(slide, 0, 0, _W, _H, COLORS["bg_dark"])

    # ── Concentric circles — center anchored 1.8" from right edge, vertically
    #    centered in the upper half. cx > slide_w intentionally lets rings bleed
    #    off the right edge for the partial-arc motif seen in the reference deck.
    add_concentric_circles(
        slide,
        cx=_W - 1.4,
        cy=2.6,
        max_diameter=LAYOUT["concentric_max_diameter_in"],
        color=motif_color,
        rings=5,
    )

    # ── Eyebrow — coral so it pops on dark ──
    add_textbox(
        slide, eyebrow.upper(),
        _MX, LAYOUT["eyebrow_y_in"], _W * 0.60, 0.38,
        font_role="mono", size=SIZES["eyebrow"],
        color=COLORS["accent_coral"],
        tracking=150,
    )

    # ── Main title — serif italic, 44 pt
    #    Height is generous: 44pt × 1.2 line-spacing × 3 lines ≈ 2.2"
    _title_y = 0.92
    _title_h = 2.30
    add_title(
        slide, title,
        _MX, _title_y,
        size=SIZES["title_xl"],
        color=COLORS["ink_on_dark"],
        italic=True,
        width=_W * 0.62,
        height=_title_h,
    )

    # ── Coral accent rule — fixed anchor below the title zone ──
    _rule_y = _title_y + _title_h + 0.12   # 0.12" breathing room
    add_filled_rect(slide, _MX, _rule_y, 3.2, 0.025, COLORS["accent_coral"])

    # ── Subtitle ──
    add_body(
        slide, subtitle,
        _MX, _rule_y + 0.15, _W * 0.60, 0.75,
        size=SIZES["subtitle"],
        color=COLORS["ink_on_dark_muted"],
    )

    # ── Tagline callout box ──
    if tagline:
        add_callout_box(
            slide, tagline,
            _MX, _rule_y + 1.05, _W * 0.58, 0.75,
            accent_color=COLORS["accent_coral"],
            bg_color="#1A4F53",
            color=COLORS["ink_on_dark"],
            italic=True,
        )

    # ── Footer metadata ──
    if footer_metadata:
        add_textbox(
            slide, footer_metadata,
            _MX, LAYOUT["footer_y_in"], _W - 2 * _MX, 0.35,
            font_role="mono", size=SIZES["footer"],
            color=COLORS["ink_on_dark_muted"],
            tracking=100,
        )

    return slide


# ─────────────────────────────────────────────────────────────────────────────
# 2. section_divider
# ─────────────────────────────────────────────────────────────────────────────

def section_divider(
    prs,
    *,
    module_label: str,
    module_title: str,
    module_subtitle: str = "",
    footer: str = "",
    _page_num: int = 1,
    _total_pages: int = 1,
):
    """
    Minimal dark-teal divider between modules.

    Layout:
      • Full dark background
      • Small coral module label eyebrow (e.g. "MODULE 03")
      • Large serif title, vertically centered-ish
      • Muted subtitle below
      • Thin coral left accent bar beside title block
      • Footer section label + page count
    """
    slide = blank_slide(prs)

    # ── Background ──
    add_filled_rect(slide, 0, 0, _W, _H, COLORS["bg_dark"])

    # ── Left accent bar — coral, full content-height strip ──
    bar_x = _MX
    bar_h = 3.2
    bar_y = 2.0
    add_filled_rect(slide, bar_x, bar_y, LAYOUT["left_accent_bar_w_in"] * 2, bar_h,
                    COLORS["accent_coral"])

    # ── Content block — offset right of the bar ──
    cx = bar_x + LAYOUT["left_accent_bar_w_in"] * 2 + 0.28

    # Module eyebrow
    add_textbox(
        slide, module_label.upper(),
        cx, bar_y + 0.10, 6.0, 0.40,
        font_role="mono", size=SIZES["eyebrow"],
        color=COLORS["accent_coral"],
        tracking=200,
    )

    # Main title
    add_title(
        slide, module_title,
        cx, bar_y + 0.58,
        size=SIZES["title"],
        color=COLORS["ink_on_dark"],
        italic=False,
        width=_W - cx - _MX,
        height=1.30,
    )

    # Subtitle
    if module_subtitle:
        add_body(
            slide, module_subtitle,
            cx, bar_y + 2.05,
            _W - cx - _MX, 0.80,
            size=SIZES["body"],
            color=COLORS["ink_on_dark_muted"],
            italic=True,
        )

    # ── Decorative small concentric circles — bottom-right ──
    add_concentric_circles(
        slide,
        cx=_W - _MX - 0.5,
        cy=_H - 1.5,
        max_diameter=2.8,
        color=COLORS["rule_on_dark"],
        rings=4,
    )

    # ── Footer ──
    label = footer if footer else module_label
    add_footer(slide, section_label=label, page_num=_page_num,
               total_pages=_total_pages, theme="dark")

    return slide


# ─────────────────────────────────────────────────────────────────────────────
# 3. objectives_slide
# ─────────────────────────────────────────────────────────────────────────────

def objectives_slide(
    prs,
    *,
    eyebrow: str,
    title: str,
    items: list[dict],
    closing_callout: str | None = None,
    _page_num: int = 1,
    _total_pages: int = 1,
):
    """
    Light background. Eyebrow + serif title at top.
    Up to 4 objective rows — each row: icon-in-circle (left) + bold header + body text.
    Optional cream callout box at bottom.

    items: [{"icon": str, "number": "01", "header": str, "body": str}, ...]
    """
    slide = blank_slide(prs)
    add_filled_rect(slide, 0, 0, _W, _H, COLORS["bg_light"])

    # ── Eyebrow ──
    add_eyebrow(slide, eyebrow, on_dark=False)

    # ── Title — 26 pt so even a long sentence stays on 1-2 lines without
    #    dominating the slide. Objectives slides are content-heavy; the title
    #    is a short framing statement, not the hero element.
    _title_y = 0.82
    _title_h = 0.72   # 26 pt × 1.2× spacing × 2 lines ≈ 0.87" — generous
    add_title(slide, title,
              _MX, _title_y,
              size=26,
              color=COLORS["ink_primary"],
              italic=False,
              height=_title_h)

    # ── Teal underline — anchored below title zone, never inside it ──
    _underline_y = _title_y + _title_h + 0.08
    add_filled_rect(slide, _MX, _underline_y, 3.5, 0.018, COLORS["accent_teal"])

    # ── Row layout — calculated from underline down to footer rule ──
    n_items   = min(len(items), 4)
    avail_h   = LAYOUT["footer_rule_y_in"] - (_underline_y + 0.18)
    # If callout needed, reserve 0.75" for it at the bottom
    if closing_callout:
        avail_h -= 0.85
    row_gap  = 0.14
    row_h    = (avail_h - row_gap * (n_items - 1)) / n_items
    row_h    = min(row_h, 1.05)   # cap so items don't get too tall on short lists

    content_y = _underline_y + 0.18
    circle_d  = 0.52
    circle_x  = _MX
    text_x    = _MX + circle_d + 0.20
    text_w    = _W - text_x - _MX - 0.2

    circle_colors = [
        COLORS["accent_coral"],
        COLORS["accent_teal"],
        COLORS["accent_gold"],
        COLORS["ink_primary"],
    ]

    for i, item in enumerate(items[:4]):
        y  = content_y + i * (row_h + row_gap)
        cy = y + circle_d / 2

        # Icon circle — vertically centered on the row
        add_icon_in_circle(
            slide, item.get("icon", "bullet"),
            cx=circle_x + circle_d / 2, cy=cy,
            diameter=circle_d,
            circle_fill=circle_colors[i % len(circle_colors)],
            icon_color=COLORS["ink_on_dark"],
            icon_size_pt=16,
        )

        # Small number badge — top-right corner of the circle
        add_textbox(
            slide, item.get("number", f"{i+1:02d}"),
            circle_x + circle_d - 0.04, y - 0.03, 0.28, 0.24,
            font_role="mono", size=7,
            color=COLORS["ink_muted"],
        )

        # Header + body
        add_multiline_textbox(
            slide,
            [
                {
                    "text": item.get("header", ""),
                    "font_role": "serif", "size": SIZES["section_header"],
                    "bold": True, "color": COLORS["ink_primary"],
                },
                {
                    "text": item.get("body", ""),
                    "font_role": "sans", "size": SIZES["body_sm"],
                    "color": COLORS["ink_secondary"],
                    "space_before": 3,
                },
            ],
            text_x, y + 0.04, text_w, row_h - 0.04,
        )

        # Subtle separator rule between rows
        if i < n_items - 1:
            rule_y = y + row_h + row_gap * 0.48
            add_filled_rect(slide, text_x, rule_y, text_w, 0.007,
                            COLORS["rule_subtle"])

    # ── Optional closing callout ──
    if closing_callout:
        callout_y = content_y + n_items * (row_h + row_gap) - row_gap + 0.08
        add_callout_box(
            slide, closing_callout,
            _MX, callout_y, _W - 2 * _MX, 0.68,
            accent_color=COLORS["accent_coral"],
        )

    add_footer(slide, section_label=eyebrow, page_num=_page_num,
               total_pages=_total_pages, theme="light")
    return slide


# ─────────────────────────────────────────────────────────────────────────────
# 4. two_column_compare
# ─────────────────────────────────────────────────────────────────────────────

def two_column_compare(
    prs,
    *,
    eyebrow: str,
    title: str,
    left_card: dict,
    right_card: dict,
    center_chip: str = "arrow_both",
    caption: str | None = None,
    _page_num: int = 1,
    _total_pages: int = 1,
):
    """
    Light background. Two cream cards side-by-side with a central icon chip.

    left_card / right_card: {
        "label": str,           eyebrow label (colored)
        "headline": str,        large serif card title
        "lines": [str, ...],    body lines (first line bold-italic if it's the key contrast)
        "verdict": {
            "icon": str,        icon name
            "text": str,        verdict label
            "color": str,       hex color key from COLORS or raw hex
        }
    }
    """
    slide = blank_slide(prs)
    add_filled_rect(slide, 0, 0, _W, _H, COLORS["bg_light"])

    add_eyebrow(slide, eyebrow, on_dark=False)

    _title_y = 0.82
    _title_h = 0.72
    add_title(slide, title, _MX, _title_y,
              size=26, color=COLORS["ink_primary"], height=_title_h)
    _underline_y = _title_y + _title_h + 0.08
    add_filled_rect(slide, _MX, _underline_y, 3.5, 0.018, COLORS["accent_coral"])

    # Card geometry
    gap        = LAYOUT["col_gap_in"]
    chip_w     = 0.70
    card_y     = _underline_y + 0.18
    card_h     = LAYOUT["footer_rule_y_in"] - card_y - 0.05
    usable_w   = _W - 2 * _MX - chip_w - gap * 2
    card_w     = usable_w / 2
    left_x     = _MX
    chip_x     = left_x + card_w + gap
    right_x    = chip_x + chip_w + gap
    pad        = LAYOUT["card_padding_in"]
    bar_w      = LAYOUT["left_accent_bar_w_in"]

    def _draw_card(card: dict, x: float, accent: str):
        # Cream card background
        add_filled_rect(slide, x, card_y, card_w, card_h, COLORS["bg_cream"])
        # Colored left accent bar
        add_left_accent_bar(slide, x, card_y, card_h, accent)

        ix = x + bar_w + pad
        iw = card_w - bar_w - pad * 1.5
        iy = card_y + pad * 0.6

        # Card eyebrow label
        add_textbox(
            slide, card.get("label", "").upper(),
            ix, iy, iw, 0.32,
            font_role="mono", size=SIZES["eyebrow"],
            color=accent, tracking=120,
        )

        # Headline
        add_title(
            slide, card.get("headline", ""),
            ix, iy + 0.38,
            size=SIZES["card_header"],
            color=COLORS["ink_primary"],
            italic=False,
            width=iw, height=0.72,
        )

        # Body lines
        line_y = iy + 1.20
        lines  = card.get("lines", [])
        for j, line in enumerate(lines[:5]):
            bold_it = (j == 0)  # first line is the key contrast — bold italic
            add_textbox(
                slide, line,
                ix, line_y, iw, 0.40,
                font_role="sans", size=SIZES["body_sm"],
                color=COLORS["ink_primary"],
                bold=bold_it, italic=bold_it,
            )
            line_y += 0.38

        # Verdict footer
        verdict = card.get("verdict", {})
        if verdict:
            vcolor_key = verdict.get("color", "accent_teal")
            vcolor = COLORS.get(vcolor_key, vcolor_key)
            add_filled_rect(slide, x, card_y + card_h - 0.55, card_w, 0.55, "#EAE4DB")
            add_icon_glyph(
                slide, verdict.get("icon", "check"),
                ix, card_y + card_h - 0.48, size=13, color=vcolor, w=0.28, h=0.38,
            )
            add_textbox(
                slide, verdict.get("text", ""),
                ix + 0.30, card_y + card_h - 0.48, iw - 0.30, 0.38,
                font_role="sans", size=SIZES["body_sm"],
                color=vcolor, bold=True,
            )

    # Left card — coral accent
    left_accent  = COLORS.get(
        left_card.get("accent", "accent_coral"), COLORS["accent_coral"])
    right_accent = COLORS.get(
        right_card.get("accent", "accent_teal"),  COLORS["accent_teal"])
    _draw_card(left_card,  left_x,  left_accent)
    _draw_card(right_card, right_x, right_accent)

    # Center chip — dark circle with swap/arrow icon
    chip_cy = card_y + card_h / 2
    chip_cx = chip_x + chip_w / 2
    add_icon_in_circle(
        slide, center_chip,
        cx=chip_cx, cy=chip_cy,
        diameter=0.60,
        circle_fill=COLORS["ink_primary"],
        icon_color=COLORS["ink_on_dark"],
        icon_size_pt=16,
    )

    # Optional italic caption below cards
    if caption:
        cap_y = card_y + card_h + 0.18
        add_textbox(
            slide, caption,
            _MX, cap_y, _W - 2 * _MX, 0.45,
            font_role="sans", size=SIZES["caption"],
            color=COLORS["ink_secondary"], italic=True,
            align=PP_ALIGN.CENTER,
        )

    add_footer(slide, section_label=eyebrow, page_num=_page_num,
               total_pages=_total_pages, theme="light")
    return slide


# ─────────────────────────────────────────────────────────────────────────────
# 5. takeaways_slide
# ─────────────────────────────────────────────────────────────────────────────

def takeaways_slide(
    prs,
    *,
    eyebrow: str,
    title: str,
    items: list[dict],
    _page_num: int = 1,
    _total_pages: int = 1,
):
    """
    Dark background closing slide. Large coral numbered rows, serif italic body.
    Concentric circles motif in background corner.

    items: [{"number": "01", "header": str, "body": str}, ...]  (up to 5)
    """
    slide = blank_slide(prs)
    add_filled_rect(slide, 0, 0, _W, _H, COLORS["bg_dark"])

    # Faint concentric circles — bottom-right background motif
    add_concentric_circles(
        slide,
        cx=_W - 0.6, cy=_H - 0.4,
        max_diameter=4.0,
        color=COLORS["rule_on_dark"],
        rings=5,
    )

    # Eyebrow — coral
    add_textbox(
        slide, eyebrow.upper(),
        _MX, LAYOUT["eyebrow_y_in"], _W - 2 * _MX, 0.35,
        font_role="mono", size=SIZES["eyebrow"],
        color=COLORS["accent_coral"], tracking=150,
    )

    # Title — serif italic on dark
    add_title(slide, title,
              _MX, LAYOUT["title_y_in"],
              size=SIZES["title"],
              color=COLORS["ink_on_dark"],
              italic=True,
              height=0.72)

    # Thin coral underline
    add_filled_rect(slide, _MX, LAYOUT["title_underline_y"], 3.5, 0.022,
                    COLORS["accent_coral"])

    # Takeaway rows
    row_y   = LAYOUT["content_y_in"]
    row_gap = 0.08
    num_w   = 0.65
    text_x  = _MX + num_w + 0.15
    text_w  = _W - text_x - _MX - 0.3
    row_h   = (LAYOUT["footer_rule_y_in"] - row_y - row_gap * 4) / 5

    for i, item in enumerate(items[:5]):
        y = row_y + i * (row_h + row_gap)

        # Large coral number
        add_textbox(
            slide, item.get("number", f"{i+1:02d}"),
            _MX, y, num_w, row_h,
            font_role="serif", size=32,
            color=COLORS["accent_coral"],
            bold=True, italic=True,
        )

        # Header + body
        add_multiline_textbox(
            slide,
            [
                {
                    "text": item.get("header", ""),
                    "font_role": "serif", "size": SIZES["body"],
                    "bold": True, "color": COLORS["ink_on_dark"],
                },
                {
                    "text": item.get("body", ""),
                    "font_role": "sans", "size": SIZES["body_sm"],
                    "italic": True, "color": COLORS["ink_on_dark_muted"],
                    "space_before": 2,
                },
            ],
            text_x, y + 0.04, text_w, row_h,
        )

        # Subtle rule between rows
        if i < len(items) - 1:
            add_filled_rect(slide,
                            _MX, y + row_h + row_gap * 0.5,
                            _W - 2 * _MX, 0.008,
                            COLORS["rule_on_dark"])

    add_footer(slide, section_label=eyebrow, page_num=_page_num,
               total_pages=_total_pages, theme="dark")
    return slide

# ─────────────────────────────────────────────────────────────────────────────
# 6. cascade_slide
# ─────────────────────────────────────────────────────────────────────────────

def cascade_slide(
    prs,
    *,
    eyebrow: str,
    title: str,
    steps: list[dict],
    footer_callout: str | None = None,
    _page_num: int = 1,
    _total_pages: int = 1,
):
    """
    Light background. Horizontal sequence of N cards (3–5) with arrow connectors.
    Last card is inverted (dark bg, coral top band) to signal the endpoint.

    steps: [{"number": "01", "header": str, "body": str}, ...]
    """
    slide = blank_slide(prs)
    add_filled_rect(slide, 0, 0, _W, _H, COLORS["bg_light"])

    add_eyebrow(slide, eyebrow, on_dark=False)

    _title_y = 0.82
    _title_h = 0.72
    add_title(slide, title, _MX, _title_y,
              size=26, color=COLORS["ink_primary"], height=_title_h)
    _underline_y = _title_y + _title_h + 0.08
    add_filled_rect(slide, _MX, _underline_y, 3.5, 0.018, COLORS["accent_coral"])

    n          = min(len(steps), 5)
    arrow_w    = 0.28
    card_y     = _underline_y + 0.18
    card_h     = 3.60 if not footer_callout else 3.10
    usable_w   = _W - 2 * _MX - arrow_w * (n - 1)
    card_w     = usable_w / n
    band_h     = 0.42   # colored top band height
    pad        = 0.20

    # Top-band colors cycle through palette (last card always coral)
    band_colors = [
        COLORS["accent_teal"],
        COLORS["accent_gold"],
        COLORS["ink_secondary"],
        COLORS["accent_coral"],
        COLORS["accent_coral"],
    ]

    for i, step in enumerate(steps[:n]):
        is_last = (i == n - 1)
        x = _MX + i * (card_w + arrow_w)

        card_bg   = COLORS["bg_dark"]  if is_last else COLORS["bg_cream"]
        band_col  = COLORS["accent_coral"]
        num_col   = COLORS["ink_on_dark"] if is_last else COLORS["accent_coral"]
        head_col  = COLORS["ink_on_dark"] if is_last else COLORS["ink_primary"]
        body_col  = COLORS["ink_on_dark_muted"] if is_last else COLORS["ink_secondary"]

        if not is_last:
            band_col = band_colors[i % len(band_colors)]

        # Card body
        add_filled_rect(slide, x, card_y, card_w, card_h, card_bg)

        # Colored top band
        add_filled_rect(slide, x, card_y, card_w, band_h, band_col)

        # Step number inside band
        add_textbox(
            slide, step.get("number", f"{i+1:02d}"),
            x + pad, card_y + 0.04, card_w - pad * 2, band_h - 0.08,
            font_role="serif", size=18,
            color=COLORS["ink_on_dark"], bold=True,
        )

        # Header
        add_textbox(
            slide, step.get("header", ""),
            x + pad, card_y + band_h + 0.12,
            card_w - pad * 2, 0.72,
            font_role="serif", size=SIZES["body"],
            color=head_col, bold=True, wrap=True,
        )

        # Body
        add_textbox(
            slide, step.get("body", ""),
            x + pad, card_y + band_h + 0.92,
            card_w - pad * 2, card_h - band_h - 1.05,
            font_role="sans", size=SIZES["body_sm"],
            color=body_col, wrap=True,
        )

        # Arrow connector (between cards, not after last)
        if not is_last:
            ax = x + card_w + arrow_w * 0.15
            ay = card_y + card_h / 2 - 0.18
            add_icon_glyph(
                slide, "arrow_right",
                ax, ay, size=20,
                color=COLORS["ink_muted"],
                w=arrow_w * 0.70, h=0.36,
            )

    # Optional callout below cards
    if footer_callout:
        fc_y = card_y + card_h + 0.16
        add_callout_box(
            slide, footer_callout,
            _MX, fc_y, _W - 2 * _MX, 0.65,
            accent_color=COLORS["accent_coral"],
        )

    add_footer(slide, section_label=eyebrow, page_num=_page_num,
               total_pages=_total_pages, theme="light")
    return slide


# ─────────────────────────────────────────────────────────────────────────────
# 7. decision_table
# ─────────────────────────────────────────────────────────────────────────────

def decision_table(
    prs,
    *,
    eyebrow: str,
    title: str,
    rows: list[dict],
    footer_caption: str | None = None,
    _page_num: int = 1,
    _total_pages: int = 1,
):
    """
    Light background. Dark teal header row + data rows with colored left bars.

    rows: [{
        "finding": str,
        "implication": str,
        "path": str,
        "severity_color": str,   # COLORS key or raw hex
    }, ...]
    """
    slide = blank_slide(prs)
    add_filled_rect(slide, 0, 0, _W, _H, COLORS["bg_light"])

    add_eyebrow(slide, eyebrow, on_dark=False)

    # 26 pt — table slides are content-heavy; title is a framing label, not hero
    _title_y = 0.82
    _title_h = 0.72
    add_title(slide, title, _MX, _title_y,
              size=26, color=COLORS["ink_primary"], height=_title_h)
    _underline_y = _title_y + _title_h + 0.08
    add_filled_rect(slide, _MX, _underline_y, 3.5, 0.018, COLORS["accent_coral"])

    # Table geometry — anchored below underline, not off hardcoded content_y
    table_y   = _underline_y + 0.18
    table_w   = _W - 2 * _MX
    bar_w     = LAYOUT["left_accent_bar_w_in"]
    header_h  = 0.38
    n_rows    = min(len(rows), 6)
    footer_reserve = 0.55 if footer_caption else 0.0
    avail_h   = LAYOUT["footer_rule_y_in"] - table_y - header_h - footer_reserve - 0.10
    row_h     = avail_h / n_rows

    # Column widths (proportional)
    col_w = [table_w * 0.30, table_w * 0.38, table_w * 0.32]
    col_x = [_MX, _MX + col_w[0], _MX + col_w[0] + col_w[1]]
    pad   = 0.14

    # ── Header row ──
    add_filled_rect(slide, _MX, table_y, table_w, header_h, COLORS["bg_dark"])
    col_labels = ["FINDING", "IMPLICATION", "FAVOURED PATH"]
    for j, (label, cx, cw) in enumerate(zip(col_labels, col_x, col_w)):
        add_textbox(
            slide, label,
            cx + pad, table_y + 0.06, cw - pad * 1.5, header_h - 0.10,
            font_role="mono", size=SIZES["eyebrow"],
            color=COLORS["ink_on_dark"], tracking=100,
        )

    # ── Data rows ──
    for i, row in enumerate(rows[:n_rows]):
        ry      = table_y + header_h + i * row_h
        alt_bg  = "#F7F4EE" if i % 2 == 0 else COLORS["bg_light"]
        sev_col = COLORS.get(row.get("severity_color", "accent_teal"),
                             row.get("severity_color", COLORS["accent_teal"]))

        # Row background
        add_filled_rect(slide, _MX, ry, table_w, row_h, alt_bg)

        # Colored severity bar
        add_left_accent_bar(slide, _MX, ry, row_h, sev_col)

        # Finding (col 0) — bold serif
        add_textbox(
            slide, row.get("finding", ""),
            col_x[0] + bar_w + pad, ry + 0.06,
            col_w[0] - bar_w - pad * 1.5, row_h - 0.12,
            font_role="serif", size=SIZES["body_sm"],
            color=COLORS["ink_primary"], bold=True, wrap=True,
        )

        # Implication (col 1) — regular sans
        add_textbox(
            slide, row.get("implication", ""),
            col_x[1] + pad, ry + 0.06,
            col_w[1] - pad * 1.5, row_h - 0.12,
            font_role="sans", size=SIZES["body_sm"],
            color=COLORS["ink_secondary"], wrap=True,
        )

        # Favoured path (col 2) — italic, colored
        add_textbox(
            slide, row.get("path", ""),
            col_x[2] + pad, ry + 0.06,
            col_w[2] - pad * 1.5, row_h - 0.12,
            font_role="sans", size=SIZES["body_sm"],
            color=sev_col, italic=True, wrap=True,
        )

        # Bottom rule
        if i < n_rows - 1:
            add_filled_rect(slide, _MX, ry + row_h - 0.006, table_w, 0.006,
                            COLORS["rule_subtle"])

    # ── Optional caption ──
    if footer_caption:
        cap_y = table_y + header_h + n_rows * row_h + 0.10
        add_textbox(
            slide, footer_caption,
            _MX, cap_y, table_w, 0.38,
            font_role="sans", size=SIZES["caption"],
            color=COLORS["ink_muted"], italic=True,
        )

    add_footer(slide, section_label=eyebrow, page_num=_page_num,
               total_pages=_total_pages, theme="light")
    return slide


# ─────────────────────────────────────────────────────────────────────────────
# 8. three_route_grid
# ─────────────────────────────────────────────────────────────────────────────

def three_route_grid(
    prs,
    *,
    eyebrow: str,
    title: str,
    routes: list[dict],
    _page_num: int = 1,
    _total_pages: int = 1,
):
    """
    Light background. Three equal cards across the slide, each with a colored
    header band, icon, WHEN section, HOW section, and citation footer.

    routes: [{
        "color": str,       COLORS key or raw hex for header band
        "icon": str,        icon name
        "name": str,        card title
        "tagline": str,     italic subtitle in header
        "when": str,        WHEN section body
        "how": str,         HOW section body
        "citation": str,    bottom citation line
    }, ...]   (exactly 3)
    """
    slide = blank_slide(prs)
    add_filled_rect(slide, 0, 0, _W, _H, COLORS["bg_light"])

    add_eyebrow(slide, eyebrow, on_dark=False)

    # 26 pt — cards need all the vertical space below
    _title_y = 0.82
    _title_h = 0.72
    add_title(slide, title, _MX, _title_y,
              size=26, color=COLORS["ink_primary"], height=_title_h)
    _underline_y = _title_y + _title_h + 0.08
    add_filled_rect(slide, _MX, _underline_y, 3.5, 0.018, COLORS["accent_teal"])

    gap     = LAYOUT["col_gap_in"]
    card_y  = _underline_y + 0.18
    card_h  = LAYOUT["footer_rule_y_in"] - card_y - 0.05
    card_w  = (_W - 2 * _MX - gap * 2) / 3
    band_h  = 1.10
    pad     = 0.18
    sec_gap = 0.22   # gap between WHEN and HOW sections

    for i, route in enumerate(routes[:3]):
        x       = _MX + i * (card_w + gap)
        col     = COLORS.get(route.get("color", "accent_teal"),
                             route.get("color", COLORS["accent_teal"]))

        # Card shell
        add_filled_rect(slide, x, card_y, card_w, card_h, COLORS["bg_cream"])

        # Colored header band
        add_filled_rect(slide, x, card_y, card_w, band_h, col)

        # Icon circle in header band (top-center)
        icon_cx = x + card_w / 2
        icon_cy = card_y + 0.40
        add_icon_in_circle(
            slide, route.get("icon", "circle"),
            cx=icon_cx, cy=icon_cy,
            diameter=0.46,
            circle_fill=COLORS["bg_light"],
            icon_color=col,
            icon_size_pt=14,
        )

        # Card name
        add_textbox(
            slide, route.get("name", ""),
            x + pad, card_y + 0.58, card_w - pad * 2, 0.38,
            font_role="serif", size=SIZES["body"],
            color=COLORS["ink_on_dark"], bold=True,
            align=PP_ALIGN.CENTER,
        )

        # Tagline
        if route.get("tagline"):
            add_textbox(
                slide, route["tagline"],
                x + pad, card_y + 0.92, card_w - pad * 2, 0.30,
                font_role="sans", size=9,
                color="#C8DFE0", italic=True,
                align=PP_ALIGN.CENTER,
            )

        # Content area starts below band
        cy = card_y + band_h + pad * 0.6

        # WHEN section
        add_textbox(
            slide, "WHEN",
            x + pad, cy, card_w - pad * 2, 0.22,
            font_role="mono", size=SIZES["eyebrow"],
            color=col, tracking=120,
        )
        cy += 0.24
        add_textbox(
            slide, route.get("when", ""),
            x + pad, cy, card_w - pad * 2,
            (card_h - band_h - pad * 0.6 - 0.24 * 2 - sec_gap - 0.30) / 2,
            font_role="sans", size=SIZES["body_sm"],
            color=COLORS["ink_secondary"], wrap=True,
        )
        cy += (card_h - band_h - pad * 0.6 - 0.24 * 2 - sec_gap - 0.30) / 2 + sec_gap

        # HOW section
        add_textbox(
            slide, "HOW",
            x + pad, cy, card_w - pad * 2, 0.22,
            font_role="mono", size=SIZES["eyebrow"],
            color=col, tracking=120,
        )
        cy += 0.24
        add_textbox(
            slide, route.get("how", ""),
            x + pad, cy, card_w - pad * 2,
            (card_h - band_h - pad * 0.6 - 0.24 * 2 - sec_gap - 0.30) / 2,
            font_role="sans", size=SIZES["body_sm"],
            color=COLORS["ink_secondary"], wrap=True,
        )

        # Citation footer strip
        add_filled_rect(slide, x, card_y + card_h - 0.30, card_w, 0.30, "#E8E2D8")
        if route.get("citation"):
            add_textbox(
                slide, route["citation"],
                x + pad, card_y + card_h - 0.26, card_w - pad * 2, 0.22,
                font_role="sans", size=8,
                color=COLORS["ink_muted"], italic=True,
            )

    add_footer(slide, section_label=eyebrow, page_num=_page_num,
               total_pages=_total_pages, theme="light")
    return slide


# ─────────────────────────────────────────────────────────────────────────────
# 9. stat_panel
# ─────────────────────────────────────────────────────────────────────────────

def stat_panel(
    prs,
    *,
    eyebrow: str,
    title: str,
    primary_stat: str,
    primary_label: str,
    secondary_stat: str | None = None,
    secondary_label: str | None = None,
    callout: str | None = None,
    citation: str | None = None,
    _page_num: int = 1,
    _total_pages: int = 1,
):
    """
    Light background. Hero stat(s) in large serif, descriptive label below.
    Optional second stat side-by-side. Optional cream callout. Citation in muted text.

    primary_stat:  e.g. "96.1%"
    primary_label: e.g. "periapical healing at 24 months (AAE meta-analysis, n=412)"
    """
    slide = blank_slide(prs)
    add_filled_rect(slide, 0, 0, _W, _H, COLORS["bg_light"])

    add_eyebrow(slide, eyebrow, on_dark=False)

    _title_y = 0.82
    _title_h = 0.72
    add_title(slide, title, _MX, _title_y,
              size=26, color=COLORS["ink_primary"], height=_title_h)
    _underline_y = _title_y + _title_h + 0.08
    add_filled_rect(slide, _MX, _underline_y, 3.5, 0.018, COLORS["accent_coral"])

    content_y = _underline_y + 0.30

    has_two = bool(secondary_stat)
    # If two stats: each occupies half the width with a divider
    stat_w   = (_W - 2 * _MX - (0.80 if has_two else 0)) / (2 if has_two else 1)

    def _draw_stat(stat_text, label_text, x, w, accent):
        # Big coral/teal number
        add_textbox(
            slide, stat_text,
            x, content_y, w, 1.40,
            font_role="serif", size=SIZES["stat_xl"],
            color=accent, bold=True,
        )
        # Descriptive label below stat
        add_textbox(
            slide, label_text,
            x, content_y + 1.45, w, 0.70,
            font_role="sans", size=SIZES["body"],
            color=COLORS["ink_secondary"], wrap=True,
        )

    _draw_stat(primary_stat, primary_label,
               _MX, stat_w, COLORS["accent_coral"])

    if has_two:
        # Thin vertical divider
        divider_x = _MX + stat_w + 0.30
        add_filled_rect(slide,
                        divider_x, content_y,
                        0.012, 2.20,
                        COLORS["rule_subtle"])
        _draw_stat(secondary_stat, secondary_label or "",
                   divider_x + 0.50, stat_w, COLORS["accent_teal"])

    # Callout box
    if callout:
        callout_y = content_y + 2.30
        add_callout_box(
            slide, callout,
            _MX, callout_y, _W - 2 * _MX, 0.80,
            accent_color=COLORS["accent_coral"],
        )

    # Muted citation
    if citation:
        cite_y = LAYOUT["footer_rule_y_in"] - 0.42
        add_textbox(
            slide, citation,
            _MX, cite_y, _W - 2 * _MX, 0.35,
            font_role="sans", size=SIZES["caption"],
            color=COLORS["ink_muted"], italic=True,
        )

    add_footer(slide, section_label=eyebrow, page_num=_page_num,
               total_pages=_total_pages, theme="light")
    return slide


# ─────────────────────────────────────────────────────────────────────────────
# 10. evidence_summary
# ─────────────────────────────────────────────────────────────────────────────

def evidence_summary(
    prs,
    *,
    eyebrow: str,
    title: str,
    hierarchy_rows: list[dict],
    trap_callout: dict | None = None,
    _page_num: int = 1,
    _total_pages: int = 1,
):
    """
    Light background. Left column: evidence tier hierarchy rows.
    Right column: "THE TRAP" or insight callout with a big supporting stat.

    hierarchy_rows: [{
        "tier_label": str,    e.g. "PRIMARY"
        "description": str,   e.g. "Systematic reviews + RCTs"
        "stat": str,          e.g. "96.1%"
        "color": str,         COLORS key for the tier label chip
    }, ...]

    trap_callout: {
        "heading": str,       e.g. "THE TRAP"
        "body": str,          insight text
        "stat": str,          big supporting number
        "stat_label": str,    label under the stat
        "color": str,         accent color key
    }
    """
    slide = blank_slide(prs)
    add_filled_rect(slide, 0, 0, _W, _H, COLORS["bg_light"])

    add_eyebrow(slide, eyebrow, on_dark=False)

    _title_y = 0.82
    _title_h = 0.72
    add_title(slide, title, _MX, _title_y,
              size=26, color=COLORS["ink_primary"], height=_title_h)
    _underline_y = _title_y + _title_h + 0.08
    add_filled_rect(slide, _MX, _underline_y, 3.5, 0.018, COLORS["accent_teal"])

    content_y  = _underline_y + 0.20
    content_h  = LAYOUT["footer_rule_y_in"] - content_y - 0.05

    # Split: left 58% hierarchy, right 38% trap callout (4% gap)
    gap        = 0.40
    left_w     = (_W - 2 * _MX) * 0.58
    right_w    = (_W - 2 * _MX) - left_w - gap
    right_x    = _MX + left_w + gap

    # ── Left: hierarchy rows ──
    n          = min(len(hierarchy_rows), 5)
    row_gap    = 0.12
    row_h      = (content_h - row_gap * (n - 1)) / n
    bar_w      = LAYOUT["left_accent_bar_w_in"]
    pad        = 0.16

    for i, hrow in enumerate(hierarchy_rows[:n]):
        ry      = content_y + i * (row_h + row_gap)
        col_key = hrow.get("color", "accent_teal")
        col     = COLORS.get(col_key, col_key)
        alt_bg  = "#F7F4EE" if i % 2 == 0 else COLORS["bg_light"]

        # Row background + left bar
        add_filled_rect(slide, _MX, ry, left_w, row_h, alt_bg)
        add_left_accent_bar(slide, _MX, ry, row_h, col)

        # Tier chip (colored mono label)
        add_textbox(
            slide, hrow.get("tier_label", "").upper(),
            _MX + bar_w + pad, ry + 0.06,
            1.20, 0.26,
            font_role="mono", size=8,
            color=col, tracking=100,
        )

        # Description
        add_textbox(
            slide, hrow.get("description", ""),
            _MX + bar_w + pad, ry + 0.30,
            left_w - bar_w - pad * 2 - 1.40, row_h - 0.36,
            font_role="sans", size=SIZES["body_sm"],
            color=COLORS["ink_primary"], wrap=True,
        )

        # Stat — right-aligned within the left column
        if hrow.get("stat"):
            add_textbox(
                slide, hrow["stat"],
                _MX + left_w - 1.30, ry + 0.04,
                1.20, row_h - 0.08,
                font_role="serif", size=22,
                color=col, bold=True,
                align=PP_ALIGN.RIGHT,
            )

    # ── Right: trap / insight callout ──
    if trap_callout:
        tc_col_key = trap_callout.get("color", "accent_coral")
        tc_col     = COLORS.get(tc_col_key, tc_col_key)

        # Dark card background
        add_filled_rect(slide, right_x, content_y, right_w, content_h,
                        COLORS["bg_dark"])

        # Colored top band
        band_h = 0.38
        add_filled_rect(slide, right_x, content_y, right_w, band_h, tc_col)

        # Heading
        add_textbox(
            slide, trap_callout.get("heading", "THE TRAP"),
            right_x + pad, content_y + 0.04,
            right_w - pad * 2, band_h - 0.08,
            font_role="mono", size=SIZES["eyebrow"],
            color=COLORS["ink_on_dark"], bold=True, tracking=150,
        )

        # Body text
        body_y = content_y + band_h + 0.18
        add_textbox(
            slide, trap_callout.get("body", ""),
            right_x + pad, body_y,
            right_w - pad * 2, 1.40,
            font_role="sans", size=SIZES["body_sm"],
            color=COLORS["ink_on_dark"], wrap=True,
        )

        # Big supporting stat
        if trap_callout.get("stat"):
            stat_y = body_y + 1.50
            add_textbox(
                slide, trap_callout["stat"],
                right_x + pad, stat_y,
                right_w - pad * 2, 1.10,
                font_role="serif", size=48,
                color=tc_col, bold=True,
                align=PP_ALIGN.CENTER,
            )
            if trap_callout.get("stat_label"):
                add_textbox(
                    slide, trap_callout["stat_label"],
                    right_x + pad, stat_y + 1.15,
                    right_w - pad * 2, 0.50,
                    font_role="sans", size=SIZES["body_sm"],
                    color=COLORS["ink_on_dark_muted"], italic=True,
                    align=PP_ALIGN.CENTER, wrap=True,
                )

    add_footer(slide, section_label=eyebrow, page_num=_page_num,
               total_pages=_total_pages, theme="light")
    return slide


__all__ = [
    "title_slide", "section_divider",
    "objectives_slide", "two_column_compare", "takeaways_slide",
    "cascade_slide", "decision_table", "three_route_grid",
    "stat_panel", "evidence_summary",
]
