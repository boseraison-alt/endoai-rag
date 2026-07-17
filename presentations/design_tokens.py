"""
Endo AI — Presentation Design Tokens
=====================================
Single source of truth for the slide deck's visual identity. Every helper and
every pattern function reads from this module — there are no hardcoded colors,
fonts, or sizes anywhere downstream.

Palette grounded in the reference deck (Failed_REP_Retreatment.pptx):
  • deep teal `#0F3D40`  — dominant 60-70% (dark slide backgrounds, primary ink)
  • coral    `#E76F51`  — sharp accent for headlines, numbers, callout edges
  • cream    `#F4EFE6`  — callout-box background ONLY (never a slide background)
  • gold     `#E9B949`  — secondary accent for tags, severity bands
  • charcoal `#1F2A2C`  — body text on light backgrounds

Type pairing follows the reference: a Georgia-class serif for slide titles and
big numbers (gives editorial gravitas), a Calibri-class sans for body copy
(reliable cross-viewer rendering), and a Consolas-class mono for the all-caps
letter-spaced eyebrow labels that anchor each slide to its module.

All sizes are in points (Pt-friendly) and all geometry in inches (Inches-friendly)
so callers can pass them straight into python-pptx without conversion noise.
"""

# ── Colour palette ────────────────────────────────────────
COLORS = {
    # Backgrounds
    "bg_dark":          "#0F3D40",   # deep teal — title, dividers, takeaways
    "bg_light":         "#FFFFFF",   # default content background
    "bg_cream":         "#F4EFE6",   # callout boxes ONLY (never a full slide bg)

    # Ink (text)
    "ink_primary":      "#0F3D40",   # body + serif titles on light slides
    "ink_secondary":    "#5A6C70",   # subheads, captions on light slides
    "ink_muted":        "#8A9499",   # eyebrows, footers on light slides
    "ink_on_dark":      "#FFFFFF",   # body + titles on dark slides
    "ink_on_dark_muted":"#A8C2C4",   # subheads, captions on dark slides

    # Accents
    "accent_coral":     "#E76F51",   # primary accent — headlines, big numbers, callout left edge
    "accent_teal":      "#1B8A8F",   # success / regeneration / "go" branch
    "accent_gold":      "#E9B949",   # warning, attention, mid severity
    "accent_red":       "#D64545",   # contraindication, "stop" branch, high severity
    "accent_green":     "#1B8A8F",   # alias of accent_teal — semantic naming for go-decisions

    # Rules / dividers
    "rule_subtle":      "#E2DCD0",   # thin separator on light slides (cream-tinted)
    "rule_on_dark":     "#1F5558",   # thin separator on dark slides (teal-tinted)
}


# ── Typography ────────────────────────────────────────────
# Primary font names (used by helpers when no fallback list is required).
FONTS = {
    "header_serif":  "Georgia",    # slide titles, big stat callouts, takeaways numbers
    "body_sans":     "Calibri",    # body copy, card labels, footer text
    "mono_eyebrow":  "Consolas",   # ALL-CAPS letter-spaced section labels
}

# Cross-viewer fallback chains. set_font() in slide_helpers writes ALL of these
# into the run's <a:latin> XML so PowerPoint, LibreOffice, Keynote, and Google
# Slides each pick the first installed font in the chain.
FONT_FALLBACKS = {
    "header_serif":  ["Georgia",  "Cambria",     "Palatino",    "Times New Roman", "serif"],
    "body_sans":     ["Calibri",  "Arial",       "Helvetica",   "Segoe UI",        "sans-serif"],
    "mono_eyebrow":  ["Consolas", "Monaco",      "Courier New", "Menlo",           "monospace"],
}


# ── Type sizes (points) ───────────────────────────────────
SIZES = {
    "title_xl":        44,    # title slide hero (slide 1)
    "title":           40,    # content slide title
    "subtitle":        24,    # title-slide subtitle, divider subtitle
    "section_header":  20,    # in-card headers, table column labels
    "card_header":     22,    # card headlines (e.g. two_column_compare)
    "stat_xl":         60,    # big numerical callouts (success rates, etc.)
    "body":            15,    # default body copy
    "body_sm":         13,    # secondary body in dense layouts
    "caption":         11,    # italic captions below tables / panels
    "eyebrow":         11,    # ALL-CAPS letter-spaced section labels
    "footer":          10,    # footer line: section name + page number
}


# ── Slide geometry (inches) ───────────────────────────────
# 16:9 widescreen. Margins are generous so cards, rules, and footers all align.
LAYOUT = {
    "slide_w_in":       13.333,
    "slide_h_in":        7.5,

    # Outer margins — never put text inside this gutter
    "margin_x_in":       0.6,
    "margin_y_in":       0.5,

    # Vertical anchors used by most content patterns
    "eyebrow_y_in":      0.55,   # eyebrow label sits above the title
    "title_y_in":        0.95,   # main slide title baseline
    "title_underline_y": 1.85,   # subtle rule under title (when used)
    "content_y_in":      2.20,   # first content row begins here
    "footer_rule_y_in":  6.85,   # thin rule above the footer line
    "footer_y_in":       7.00,   # footer text baseline

    # Card / row spacing
    "row_gap_in":        0.30,   # vertical gap between content rows / cards
    "col_gap_in":        0.40,   # horizontal gap between side-by-side cards
    "card_padding_in":   0.30,   # internal padding inside a card

    # Decorative motif
    "concentric_max_diameter_in": 4.5,  # title-slide decorative circles
    "left_accent_bar_w_in":       0.08, # thin colored bar on left of cards/rows
}


# ── Letter-spacing (track) for eyebrow labels ─────────────
# python-pptx exposes character spacing via run._r.set("spc", "150") in 1/100 pt.
# 150 = +1.5pt tracking, which gives the airy ALL-CAPS look of the reference deck.
EYEBROW_TRACKING = 150


# ── Convenience accessor — semantic colour roles ──────────
# Avoids litter of bare COLORS["accent_coral"] strings inside pattern code by
# letting callers reference the *role* the colour is playing in this layout.
SEMANTIC = {
    "verdict_yes":      COLORS["accent_teal"],
    "verdict_no":       COLORS["accent_red"],
    "verdict_caution":  COLORS["accent_gold"],
    "endpoint_card":    COLORS["bg_dark"],     # the inverted last card in a cascade
    "endpoint_band":    COLORS["accent_coral"],
    "callout_edge":     COLORS["accent_coral"],
    "table_header_bg":  COLORS["bg_dark"],
    "table_header_ink": COLORS["ink_on_dark"],
}


__all__ = [
    "COLORS", "FONTS", "FONT_FALLBACKS", "SIZES", "LAYOUT",
    "EYEBROW_TRACKING", "SEMANTIC",
]
