"""
Endo AI — Icon System (Approach B: Unicode Glyphs)
====================================================
Ships Unicode characters that map to well-known symbols available in every
modern font stack. Tabler Icons (tabler.io) informed the semantic naming
convention; the glyphs themselves are standard Unicode so no SVG renderer,
cairosvg, or image file is required.

Each entry in ICON_MAP stores a primary character and a plain-ASCII fallback
for environments that cannot render the primary (e.g., very old PDF viewers).

Usage
-----
    from presentations.icons import get_icon_char, ICON_MAP

    ch = get_icon_char("check")       # → "✓"
    ch = get_icon_char("no_entry")    # → "✕"
    ch = get_icon_char("__missing__") # → "•"  (safe default)

Font note
---------
These glyphs render correctly in the Segoe UI Symbol / Segoe UI Emoji stack
on Windows (the OS PowerPoint runs on) and in Symbola / Noto Symbol on Linux.
When adding a run that contains an icon character, callers should set the font
to "Segoe UI Symbol" (Windows) or leave it inherited — python-pptx will let
PowerPoint pick the best symbol font automatically.
"""

# ── Icon registry ─────────────────────────────────────────────────────────────
# Keys follow Tabler's semantic naming where possible so the upstream SVG set
# can be consulted for visual reference even though we render as Unicode.
#
# Format: "semantic_name": (primary_glyph, ascii_fallback)
#
# Tabler reference URLs (for documentation / future SVG upgrade path):
#   https://github.com/tabler/tabler-icons/blob/main/icons/outline/<name>.svg

ICON_MAP: dict[str, tuple[str, str]] = {
    # ── Decision / verdict ────────────────────────────────────────────────────
    "check":            ("✓",  "Y"),   # tabler: check
    "check_circle":     ("✔",  "Y"),   # tabler: circle-check
    "x":                ("✕",  "N"),   # tabler: x
    "x_circle":         ("✖",  "N"),   # tabler: circle-x
    "alert":            ("⚠",  "!"),   # tabler: alert-triangle
    "alert_circle":     ("⚠",  "!"),   # tabler: alert-circle
    "ban":              ("⊘",  "X"),   # tabler: ban
    "question":         ("?",  "?"),   # tabler: question-mark

    # ── Navigation / flow ─────────────────────────────────────────────────────
    "arrow_right":      ("→",  ">"),   # tabler: arrow-right
    "arrow_left":       ("←",  "<"),   # tabler: arrow-left
    "arrow_up":         ("↑",  "^"),   # tabler: arrow-up
    "arrow_down":       ("↓",  "v"),   # tabler: arrow-down
    "arrow_both":       ("⇄",  "<>"),  # tabler: arrows-exchange
    "chevron_right":    ("›",  ">"),   # tabler: chevron-right
    "chevron_down":     ("⌄",  "v"),   # tabler: chevron-down
    "branch":           ("⑂",  "|"),   # tabler: git-branch
    "route":            ("⤳",  "->"),  # tabler: route

    # ── Clinical / medical ────────────────────────────────────────────────────
    "tooth":            ("🦷", "T"),   # tabler: (dental)
    "stethoscope":      ("🩺", "Rx"),  # tabler: stethoscope
    "pill":             ("💊", "Rx"),  # tabler: pill
    "heart_pulse":      ("♡",  "HR"),  # tabler: heart-rate-monitor
    "microscope":       ("🔬", "Lab"), # tabler: microscope
    "syringe":          ("💉", "Inj"),  # tabler: vaccine
    "thermometer":      ("🌡", "Tmp"), # tabler: temperature

    # ── Evidence / research ───────────────────────────────────────────────────
    "book":             ("📖", "Lit"), # tabler: book
    "chart_bar":        ("▦",  "Bar"), # tabler: chart-bar
    "chart_line":       ("📈", "Trnd"),# tabler: chart-line
    "magnify":          ("⊕",  "Q"),   # tabler: zoom-in  (alt: search)
    "search":           ("🔍", "Srch"),# tabler: search
    "clipboard":        ("📋", "Rx"),  # tabler: clipboard
    "database":         ("◫",  "DB"),  # tabler: database
    "certificate":      ("★",  "*"),   # tabler: certificate
    "star":             ("★",  "*"),   # tabler: star-filled
    "star_half":        ("⯨",  "~*"),  # tabler: star-half-filled

    # ── Status / outcome ──────────────────────────────────────────────────────
    "success":          ("✔",  "OK"),  # tabler: circle-check-filled
    "failure":          ("✖",  "FAIL"),# tabler: circle-x-filled
    "caution":          ("⚠",  "!"),   # tabler: alert-triangle-filled
    "info":             ("ℹ",  "i"),   # tabler: info-circle
    "trend_up":         ("↗",  "/^"),  # tabler: trending-up
    "trend_down":       ("↘",  "\\v"), # tabler: trending-down
    "flag":             ("⚑",  "F"),   # tabler: flag

    # ── Structure / layout ────────────────────────────────────────────────────
    "bullet":           ("•",  "-"),   # tabler: point-filled
    "diamond":          ("◆",  "*"),   # tabler: diamond-filled
    "square":           ("■",  "#"),   # tabler: square-filled
    "circle":           ("●",  "o"),   # tabler: circle-filled
    "triangle":         ("▶",  ">"),   # tabler: triangle-filled
    "dash":             ("—",  "-"),   # em-dash separator
    "ellipsis":         ("…",  "..."), # tabler: dots

    # ── Process / time ────────────────────────────────────────────────────────
    "clock":            ("⏱",  "t"),   # tabler: clock
    "calendar":         ("📅", "Cal"), # tabler: calendar
    "repeat":           ("↺",  "Re"),  # tabler: refresh
    "steps":            ("⑃",  "→"),   # tabler: steps
    "hourglass":        ("⧗",  "~t"),  # tabler: hourglass
}


# ── Default character returned when a name isn't found ───────────────────────
_FALLBACK_CHAR = "•"
_FALLBACK_ASCII = "-"


def get_icon_char(icon_name: str, *, ascii_safe: bool = False) -> str:
    """Return the Unicode glyph (or ASCII fallback) for *icon_name*.

    Parameters
    ----------
    icon_name : str
        Key from ICON_MAP (e.g. "check", "arrow_right").
    ascii_safe : bool
        If True, return the plain-ASCII fallback instead of the Unicode glyph.
        Use this when targeting environments with no symbol-font support.

    Returns the bullet "•" character when *icon_name* is not in ICON_MAP.
    """
    entry = ICON_MAP.get(icon_name)
    if entry is None:
        return _FALLBACK_ASCII if ascii_safe else _FALLBACK_CHAR
    primary, fallback = entry
    return fallback if ascii_safe else primary


def icon_names() -> list[str]:
    """Return all registered icon names, sorted."""
    return sorted(ICON_MAP.keys())


__all__ = ["ICON_MAP", "get_icon_char", "icon_names"]
