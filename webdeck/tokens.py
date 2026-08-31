"""Design tokens for the web deck — PRESENTATION_WORKLIST.md §1, encoded exactly.

DELIBERATE DUPLICATION. `presentations/design_tokens.py` carries the same §1
spec for the PPTX exporter and is owned by another agent during this phase.
Importing it here would couple a browser renderer to python-pptx colour
objects and to a file being rewritten concurrently, so the values are restated
as plain hex strings. `tests/test_webdeck.py::TestSpecTokens` pins every value
against the worklist table, which is the thing both files must agree with —
reconcile the two against §1, not against each other.
"""
from __future__ import annotations

# ── §1.1 identity ────────────────────────────────────────
FONT_DISPLAY = '"Instrument Serif", Georgia, "Times New Roman", serif'
FONT_BODY    = '"Inter", "Segoe UI", Calibri, system-ui, sans-serif'

# The PPTX fallback mapping documented in §1.1, restated so the web deck's
# font stacks and the deck template's degrade to the same faces.
PPTX_FONT_FALLBACK = {"Instrument Serif": "Georgia", "Inter": "Calibri"}

GOOGLE_FONTS_HREF = (
    "https://fonts.googleapis.com/css2"
    "?family=Instrument+Serif:ital@0;1"
    "&family=Inter:wght@400;500;600;700"
    "&display=swap"
)

# ── §1.1 dark theme ──────────────────────────────────────
DARK = {
    "bg":             "#131b2c",
    "surface":        "#1c2740",
    "surface-alt":    "#17213a",
    "card":           "#1a2440",
    "border":         "#2c3a58",
    "leader":         "#33425f",
    "text-title":     "#ffffff",
    "text-body":      "#eef2fa",
    "text-secondary": "#c6d0e2",
    "text-lead":      "#aebad0",
    "text-eyebrow":   "#93a3bd",
    "text-footer":    "#8296b3",
    "text-muted":     "#7d8fae",
    "accent-cyan":    "#8bd7e8",
    "divider-bg":     "#1e40af",
    "divider-num":    "#3556c4",
}

# ── §1.2 tier ladder ─────────────────────────────────────
# Ladder ORDER is semantic: a hue always means the same tier, everywhere.
TIER_SLOTS = ["cochrane", "level1", "level2", "level3", "level4", "invitro", "level5"]

TIER_NAME = {
    "cochrane": "Cochrane",
    "level1":   "Level I",
    "level2":   "Level II",
    "level3":   "Level III",
    "level4":   "Level IV",
    "invitro":  "In vitro",
    "level5":   "Level V",
    "other":    "Other",
}

# Chart fills on dark, ladder order.
TIER_CHART_DARK = {
    "cochrane": "#4ec78f",
    "level1":   "#22c0dd",
    "level2":   "#60a5fa",
    "level3":   "#c4b5fd",
    "level4":   "#f27596",
    "invitro":  "#fbbf24",
    "level5":   "#e18aef",
}

# Chip background / chip text on dark.
TIER_CHIP_DARK = {
    "cochrane": ("#12301f", "#5ad196"),
    "level1":   ("#0e2b33", "#5fd4e8"),
    "level2":   ("#1e2f55", "#93b4f5"),
    "level3":   ("#241d47", "#c4b5fd"),
    "level4":   ("#331420", "#f27596"),
    "invitro":  ("#33270f", "#f5b84d"),
    "level5":   ("#2e1633", "#e18aef"),
}

# §1.2: the evidence-shape bar sits on a LIGHT card and uses the light-surface
# ladder there. This exact set passed the CVD validator — keep the light card.
TIER_CHART_LIGHT = {
    "cochrane": "#0f7a4d",
    "level1":   "#0891b2",
    "level2":   "#2563eb",
    "level3":   "#a78bfa",
    "level4":   "#9f1239",
    "invitro":  "#d97706",
    "level5":   "#86198f",
}

EVIDENCE_CARD_BG = "#fcfcfd"

# Level III must always carry its text label (§1.2) — the lavender fill is the
# one that does not survive on its own for a colour-blind reader.
ALWAYS_LABEL = {"level3"}

# §1.2 PMID pills and the IF / THEN / BECAUSE chips.
PMID_PILL   = ("#1e2f55", "#93b4f5")
CHIP_IF     = ("#1c2740", "#aebad0")
CHIP_THEN   = ("#1e2f55", "#93b4f5")
CHIP_BECAUSE = ("#12301f", "#5ad196")

# Single-series chart marks use this and only this (§1.5).
CHART_SERIES = "#60a5fa"

# §1.4 layout 7: the four takeaway numerals, in order.
TAKEAWAY_NUMERALS = ["#60a5fa", "#4ec78f", "#fbbf24", "#e18aef"]

# ── library level_key → ladder slot ──────────────────────
# The library carries finer tiers than the seven-colour ladder (level3a /
# level3b split retrospective cohort from case-control, and `classic` is a
# curated foundational set that is not a design tier at all). Collapsing
# 3a/3b into Level III is the spec's own grouping; anything with no slot goes
# to an explicitly-labelled "other" bucket rather than borrowing a tier's
# colour, because a wrong tier colour is a claim about evidence strength.
LEVEL_KEY_TO_SLOT = {
    "cochrane": "cochrane",
    "level1":   "level1",
    "level2":   "level2",
    "level3":   "level3",
    "level3a":  "level3",
    "level3b":  "level3",
    "level4":   "level4",
    "invitro":  "invitro",
    "level5":   "level5",
}

OTHER_CHART_DARK  = DARK["leader"]
OTHER_CHART_LIGHT = "#94a3b8"
OTHER_CHIP_DARK   = (DARK["surface"], DARK["text-lead"])


def slot_for(level_key: str) -> str:
    """Map a library `level_key` onto a ladder slot, or 'other'."""
    return LEVEL_KEY_TO_SLOT.get((level_key or "").strip().lower(), "other")


def chip_colors(slot: str):
    return TIER_CHIP_DARK.get(slot, OTHER_CHIP_DARK)


def chart_color_dark(slot: str) -> str:
    return TIER_CHART_DARK.get(slot, OTHER_CHART_DARK)


def chart_color_light(slot: str) -> str:
    return TIER_CHART_LIGHT.get(slot, OTHER_CHART_LIGHT)


def css_variables() -> str:
    """`:root` block. The deck is dark-only by approval (§6 puts a light
    variant out of scope), so there is no theme switch to guard."""
    lines = [f"  --{name}: {value};" for name, value in DARK.items()]
    lines.append(f"  --font-display: {FONT_DISPLAY};")
    lines.append(f"  --font-body: {FONT_BODY};")
    lines.append(f"  --evidence-card: {EVIDENCE_CARD_BG};")
    lines.append(f"  --chart-series: {CHART_SERIES};")
    return ":root {\n" + "\n".join(lines) + "\n}"
