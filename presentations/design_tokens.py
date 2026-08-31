"""
Curo — Presentation Design Tokens
==================================
Single source of truth for the slide deck's visual identity. Every helper and
every pattern function reads from this module — there are no hardcoded colors,
fonts, or sizes anywhere downstream.

This file encodes the APPROVED DESIGN SPEC (PRESENTATION_WORKLIST.md §1)
verbatim. It replaced an earlier teal/coral/cream *light* palette that was
lifted from a reference deck; that palette is gone, not deprecated. The theme
is DARK throughout.

Reference frame
---------------
The spec is written in CSS pixels against a 1280x720 frame. python-pptx wants
inches for geometry and points for type, so everything here is authored in the
spec's own px numbers and converted once, at the bottom of each block, by
`px_in()` / `px_pt()`. 1280px / 96 = 13.333in and 720px / 96 = 7.5in, so the
px frame and the 16:9 pptx frame are the same rectangle — a value copied out
of the spec lands where the spec says it lands.

Font fallbacks — why the mapping exists
---------------------------------------
The spec's faces are Instrument Serif (display) and Inter (everything else).
Both are webfonts. **PowerPoint cannot embed a webfont from a CSS @font-face
rule** — a .pptx can only reference fonts installed on the viewing machine (and
python-pptx has no embedding API at all), so a deck asking for "Instrument
Serif" on a clinician's laptop silently renders in the theme default, usually
Calibri, which collapses the serif/sans distinction the layouts depend on.

The deck therefore names locally-installed stand-ins, per spec §1.1:

    Instrument Serif  ->  Georgia          (high-contrast transitional serif,
                                            ships with Windows and macOS)
    Inter             ->  Calibri / Segoe UI
                                           (humanist sans, ships with Windows;
                                            Segoe UI is the closer match to
                                            Inter's metrics where present)

The web deck (Phase 2) loads the real faces from Google Fonts; only the PPTX
substitutes. Keep the two in visual sympathy — if the web deck's faces change,
change the stand-ins here too.
"""

from __future__ import annotations

# ── Unit conversion ───────────────────────────────────────
# The spec is authored in CSS px on a 1280x720 frame at 96 px/in.
PX_PER_IN = 96.0
PX_PER_PT = 96.0 / 72.0   # 1.3333


def px_in(px: float) -> float:
    """CSS px (1280x720 reference frame) -> inches, for python-pptx geometry."""
    return px / PX_PER_IN


def px_pt(px: float) -> float:
    """CSS px -> points, for python-pptx type sizes."""
    return px / PX_PER_PT


# ── Colour palette — spec §1.1 ────────────────────────────
COLORS = {
    # Surfaces
    "bg":            "#131b2c",   # every slide background
    "surface":       "#1c2740",   # table header rows, notice boxes, diagram fills
    "surface_alt":   "#17213a",   # table zebra rows
    "card":          "#1a2440",   # decision-tree cards
    "border":        "#2c3a58",   # all hairlines, table borders, footer rule
    "leader":        "#33425f",   # chart leader / grid lines

    # Ink
    "text_title":     "#ffffff",  # slide titles (Title / Divider)
    "text_body":      "#eef2fa",  # titles + primary body on content slides
    "text_secondary": "#c6d0e2",  # BECAUSE text, table body alt
    "text_lead":      "#aebad0",  # lead paragraphs, labels
    "text_eyebrow":   "#93a3bd",  # eyebrow rows
    "text_footer":    "#8296b3",  # citation footers
    "text_muted":     "#7d8fae",  # page numbers, chart axis numbers

    # Accents
    "accent_cyan":   "#8bd7e8",   # title-slide eyebrow, divider tick marks
    "divider_bg":    "#1e40af",   # section-divider background (flat)
    "divider_numeral": "#3556c4", # giant module numeral on the divider

    # The light card that carries the evidence-shape bar on the title slide.
    "light_card":    "#fcfcfd",
    "light_card_ink":       "#1a2333",
    "light_card_ink_muted": "#5b6880",
    "title_disclaimer":     "#7487a3",

    # Alert / COI family. Spec §1.2: reserved, NEVER used as a tier colour.
    "alert_red":     "#f87171",
    "alert_bg":      "#3a1520",
}


# ── Tier colour ladder — spec §1.2 ────────────────────────
# A hue always means the same tier, everywhere. Order is the fixed ladder order.
TIER_ORDER = [
    "cochrane", "level1", "level2", "level3", "level4", "invitro", "level5",
]

TIER_LABELS = {
    "cochrane": "Cochrane",
    "level1":   "Level I",
    "level2":   "Level II",
    "level3":   "Level III",
    "level4":   "Level IV",
    "invitro":  "In vitro",
    "level5":   "Level V",
}

# Chart fills on the dark background.
TIER_CHART_FILL = {
    "cochrane": "#4ec78f",
    "level1":   "#22c0dd",
    "level2":   "#60a5fa",
    "level3":   "#c4b5fd",
    "level4":   "#f27596",
    "invitro":  "#fbbf24",
    "level5":   "#e18aef",
}

# Chip background / chip text on the dark background.
TIER_CHIP = {
    "cochrane": ("#12301f", "#5ad196"),
    "level1":   ("#0e2b33", "#5fd4e8"),
    "level2":   ("#1e2f55", "#93b4f5"),
    "level3":   ("#241d47", "#c4b5fd"),
    "level4":   ("#331420", "#f27596"),
    "invitro":  ("#33270f", "#f5b84d"),
    "level5":   ("#2e1633", "#e18aef"),
}

# Level III must always carry its text label (spec §1.2) — never colour alone.
TIER_LABEL_MANDATORY = {"level3"}

# The evidence-shape bar sits on the LIGHT card and uses the light-surface
# ladder, which is the set that passed the colour-vision-deficiency validator.
# Do not substitute the dark ladder here; the card stays light for this reason.
TIER_CHART_FILL_LIGHT = {
    "cochrane": "#0f7a4d",
    "level1":   "#0891b2",
    "level2":   "#2563eb",
    "level3":   "#a78bfa",
    "level4":   "#9f1239",
    "invitro":  "#d97706",
    "level5":   "#86198f",
}

# PMID pills and the IF / THEN / BECAUSE chips on decision-tree cards.
PILL_PMID   = ("#1e2f55", "#93b4f5")
CHIP_IF     = ("#1c2740", "#aebad0")
CHIP_THEN   = ("#1e2f55", "#93b4f5")
CHIP_BECAUSE = ("#12301f", "#5ad196")

# Single-series chart marks use this and only this (spec §1.5).
CHART_SERIES_SINGLE = "#60a5fa"
# Serif numerals on the key-takeaways grid, in order.
TAKEAWAY_NUMERALS = ["#60a5fa", "#4ec78f", "#fbbf24", "#e18aef"]
# Round bullet markers on content slides.
BULLET_MARKER = "#60a5fa"


# ── Typography — spec §1.1 ────────────────────────────────
FONTS = {
    "display": "Georgia",   # stand-in for Instrument Serif  (see module docstring)
    "body":    "Calibri",   # stand-in for Inter             (see module docstring)
}

# Cross-viewer fallback chains. set_font() writes the primary into the run's
# <a:latin> and records the chain so a machine missing the primary still lands
# on the right *class* of face rather than the theme default.
FONT_FALLBACKS = {
    "display": ["Georgia", "Cambria", "Palatino Linotype", "Times New Roman", "serif"],
    "body":    ["Calibri", "Segoe UI", "Inter", "Helvetica", "Arial", "sans-serif"],
}


# ── Type sizes — spec px, exposed as points ───────────────
SIZES_PX = {
    "title_hero":      68,   # title slide, serif
    "title_divider":   56,   # section divider, serif
    "title":           44,   # content-class slide title, serif
    "takeaway_num":    54,   # takeaway serif numeral
    "wordmark":        24,   # "Curo" serif italic on the title slide
    "subtitle":        18,   # title-slide subtitle
    "lead":            18,   # lead paragraph
    "takeaway_body":   18,   # takeaway text
    "divider_tick":    18,   # divider topic lines
    "bullet":          17,   # content bullets
    "card_body":       16,   # decision-tree card text
    "references":      15,   # reference row title/journal/year
    "table_body":      14,   # table cell text
    "score":           13,   # right-aligned evidence score on references
    "footer":          12,   # citation footer, page number, disclaimer
    "axis":            12,   # chart axis numbers
    "eyebrow":         11,   # eyebrow row
    "chip":            11,   # tier chips, PMID pills, IF/THEN/BECAUSE chips
    "table_header":    11,   # uppercase table column labels
}

SIZES = {k: px_pt(v) for k, v in SIZES_PX.items()}

# Line-height multipliers from the spec, used to budget vertical space.
LINE_HEIGHT = {
    "title":    1.10,
    "lead":     1.50,
    "bullet":   1.55,
    "card":     1.50,
    "takeaway": 1.55,
}

# Weights the spec names. python-pptx only exposes bold/not-bold, so 600 and
# 700 both map to bold; 400/500 map to regular.
def is_bold(weight: int) -> bool:
    return weight >= 600


# ── Letter-spacing ────────────────────────────────────────
# python-pptx exposes character spacing as rPr/@spc in 1/100 pt.
# spec: eyebrow 0.1em at 11px, chips 0.08em at 11px.
def tracking_from_em(em: float, size_px: float) -> int:
    """CSS letter-spacing in em at a given px size -> pptx spc (1/100 pt)."""
    return int(round(px_pt(em * size_px) * 100))


TRACK_EYEBROW = tracking_from_em(0.10, SIZES_PX["eyebrow"])   # ~ 83
TRACK_CHIP    = tracking_from_em(0.08, SIZES_PX["chip"])      # ~ 66
TRACK_TABLE_HEADER = TRACK_EYEBROW


# ── Slide geometry — spec §1.3, in the px reference frame ─
GEOM_PX = {
    "slide_w":        1280,
    "slide_h":         720,

    "pad_x":            64,   # padding 56px 64px 0
    "pad_top":          56,

    "header_h":         26,   # fixed header row height
    "title_gap":        22,   # title margin-top, below the header row
    "lead_gap":         14,   # lead margin-top, below the title
    "lead_max_w":      860,

    "footer_rule_y":   672,   # 1px top border above the footer
    "footer_text_y":   686,   # footer text top (padding 14 above, 18 below)

    "hairline":          1,
    "chip_h":           22,   # tier chip / PMID pill height
    "chip_dot":          8,   # colored dot inside a tier chip
    "bullet_dot":        8,   # round bullet marker
    "card_radius":      10,   # decision-tree cards, notice box
    "container_radius": 12,   # title-slide light card
    "chip_radius":       5,   # IF/THEN/BECAUSE chips
    "table_radius":      8,
    "evidence_bar_h":   26,   # stacked evidence-shape bar
    "evidence_gap":      2,   # gap between tier segments
    "divider_tick_w":   18,   # cyan dash on divider topic lines
    "divider_tick_h":    2,
    "divider_text_min": 450,  # keep the text column clear of the giant numeral
}

LAYOUT = {
    "slide_w_in":      px_in(GEOM_PX["slide_w"]),
    "slide_h_in":      px_in(GEOM_PX["slide_h"]),
    "pad_x_in":        px_in(GEOM_PX["pad_x"]),
    "pad_top_in":      px_in(GEOM_PX["pad_top"]),
    "content_w_in":    px_in(GEOM_PX["slide_w"] - 2 * GEOM_PX["pad_x"]),

    "header_y_in":     px_in(GEOM_PX["pad_top"]),
    "header_h_in":     px_in(GEOM_PX["header_h"]),
    "title_y_in":      px_in(GEOM_PX["pad_top"] + GEOM_PX["header_h"]
                             + GEOM_PX["title_gap"]),
    "lead_gap_in":     px_in(GEOM_PX["lead_gap"]),
    "lead_max_w_in":   px_in(GEOM_PX["lead_max_w"]),

    "footer_rule_y_in": px_in(GEOM_PX["footer_rule_y"]),
    "footer_text_y_in": px_in(GEOM_PX["footer_text_y"]),

    "hairline_in":     px_in(GEOM_PX["hairline"]),
    "chip_h_in":       px_in(GEOM_PX["chip_h"]),
    "chip_dot_in":     px_in(GEOM_PX["chip_dot"]),
    "bullet_dot_in":   px_in(GEOM_PX["bullet_dot"]),
    "card_radius_in":  px_in(GEOM_PX["card_radius"]),
    "container_radius_in": px_in(GEOM_PX["container_radius"]),
    "chip_radius_in":  px_in(GEOM_PX["chip_radius"]),
    "table_radius_in": px_in(GEOM_PX["table_radius"]),
    "evidence_bar_h_in": px_in(GEOM_PX["evidence_bar_h"]),
    "evidence_gap_in": px_in(GEOM_PX["evidence_gap"]),
    "divider_tick_w_in": px_in(GEOM_PX["divider_tick_w"]),
    "divider_tick_h_in": px_in(GEOM_PX["divider_tick_h"]),
    "divider_text_min_in": px_in(GEOM_PX["divider_text_min"]),
}


# ── Body budget — spec §1.3 / §2.2 ────────────────────────
# Max one of: 5 bullets, one table, one figure. Overflow auto-splits.
BODY_BUDGET = {
    "max_bullets":        5,
    "max_words_per_bullet": 25,
    "max_table_rows":     7,    # data rows per table slide; header repeats on split
    "max_cards":          4,    # decision-tree cards (2x2 grid)
    "max_takeaways":      4,    # 2x2 grid
    "max_reference_rows": 6,
}


# ── Legacy semantic aliases ───────────────────────────────
# `endo_ai.generate_slides_specs` emits colour *keys* ("accent_red",
# "accent_teal", ...) inside slide specs, and `app.py` — which this phase must
# not modify — passes those specs straight through. The keys therefore have to
# keep resolving. They are remapped onto the dark spec palette rather than
# deleted, so a spec written against the old vocabulary renders in the new
# theme instead of failing or reintroducing teal/coral.
COLORS.update({
    "bg_dark":           COLORS["bg"],
    "bg_light":          COLORS["light_card"],
    "bg_cream":          COLORS["surface"],
    "ink_primary":       COLORS["text_body"],
    "ink_secondary":     COLORS["text_secondary"],
    "ink_muted":         COLORS["text_muted"],
    "ink_on_dark":       COLORS["text_title"],
    "ink_on_dark_muted": COLORS["text_lead"],
    "rule_subtle":       COLORS["border"],
    "rule_on_dark":      COLORS["border"],
    # Accent keys the LLM prompt still names, mapped to spec hues.
    "accent_teal":       TIER_CHART_FILL["cochrane"],   # "go" / positive
    "accent_green":      TIER_CHART_FILL["cochrane"],
    "accent_coral":      TIER_CHART_FILL["level4"],     # attention
    "accent_gold":       TIER_CHART_FILL["invitro"],    # caution
    "accent_red":        COLORS["alert_red"],           # alert — never a tier
    "accent_blue":       CHART_SERIES_SINGLE,
})

SEMANTIC = {
    "verdict_yes":     TIER_CHART_FILL["cochrane"],
    "verdict_no":      COLORS["alert_red"],
    "verdict_caution": TIER_CHART_FILL["invitro"],
    "table_header_bg": COLORS["surface"],
    "table_zebra_bg":  COLORS["surface_alt"],
    "table_header_ink": COLORS["text_body"],
    "notice_bg":       COLORS["surface"],
    "card_bg":         COLORS["card"],
}


def tier_key(raw: str | None) -> str | None:
    """Normalise a free-text tier name to a ladder key, or None if unknown.

    Accepts the app's internal keys ("level3a") and the human labels the slide
    generator tends to emit ("Level III", "Cochrane review", "in vitro").
    """
    if not raw:
        return None
    s = str(raw).strip().lower().replace("-", " ").replace("_", " ")
    if not s:
        return None
    if "cochrane" in s:
        return "cochrane"
    if "vitro" in s or "ex vivo" in s or "bench" in s or "laborator" in s:
        return "invitro"
    if s in TIER_ORDER:
        return s
    # level3a / level3b collapse onto level3
    for key in TIER_ORDER:
        if s.startswith(key):
            return key
    roman = {
        "i": "level1", "1": "level1",
        "ii": "level2", "2": "level2",
        "iii": "level3", "3": "level3",
        "iv": "level4", "4": "level4",
        "v": "level5", "5": "level5",
    }
    for token in s.split():
        t = token.strip(".:")
        if t in roman and ("level" in s or "tier" in s or "class" in s):
            return roman[t]
    return None


__all__ = [
    "PX_PER_IN", "PX_PER_PT", "px_in", "px_pt",
    "COLORS", "FONTS", "FONT_FALLBACKS",
    "SIZES", "SIZES_PX", "LINE_HEIGHT", "is_bold",
    "GEOM_PX", "LAYOUT", "BODY_BUDGET",
    "TIER_ORDER", "TIER_LABELS", "TIER_CHART_FILL", "TIER_CHIP",
    "TIER_CHART_FILL_LIGHT", "TIER_LABEL_MANDATORY",
    "PILL_PMID", "CHIP_IF", "CHIP_THEN", "CHIP_BECAUSE",
    "CHART_SERIES_SINGLE", "TAKEAWAY_NUMERALS", "BULLET_MARKER",
    "TRACK_EYEBROW", "TRACK_CHIP", "TRACK_TABLE_HEADER", "tracking_from_em",
    "SEMANTIC", "tier_key",
]
