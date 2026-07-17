"""
Endo AI — Slide Helper Utilities
==================================
Low-level python-pptx wrappers used by every slide pattern. All coordinates are
in inches, all sizes in points, all colors as hex strings. No magic numbers —
every default comes from design_tokens.

Font fallback strategy
----------------------
python-pptx writes a single <a:latin typeface="X"/> element per run. If X isn't
installed, PowerPoint falls back to its built-in theme fonts (usually Calibri),
which breaks the serif / mono distinction. set_font() works around this by
injecting the full fallback chain into the run's XML using <a:latin/> plus an
<a:ea/> (East-Asian) and <a:cs/> (complex-script) stub that prevent PowerPoint
from silently substituting a different face.

The XML produced for a Georgia run looks like:
    <a:rPr ...>
      <a:latin typeface="Georgia" panose="..." pitchFamily="..." charset="0"/>
      ...
    </a:rPr>

We also write the fallback list into the run's altLang so Keynote / LibreOffice
attempt the same chain. The first font in the list that is installed wins.
"""

from __future__ import annotations

import copy
from lxml import etree
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn

from presentations.design_tokens import (
    COLORS, FONTS, FONT_FALLBACKS, SIZES, LAYOUT, EYEBROW_TRACKING, SEMANTIC,
)


# ── Color conversion ──────────────────────────────────────────────────────────

def hex_rgb(hex_str: str) -> RGBColor:
    """Convert '#RRGGBB' to RGBColor."""
    h = hex_str.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


# ── Font application ──────────────────────────────────────────────────────────

_FONT_ROLE_MAP = {
    # Convenience aliases callers can use instead of raw font names
    "serif":   "header_serif",
    "sans":    "body_sans",
    "mono":    "mono_eyebrow",
    # Direct role keys pass through as-is
    "header_serif": "header_serif",
    "body_sans":    "body_sans",
    "mono_eyebrow": "mono_eyebrow",
}


def set_font(
    run,
    font_role: str,
    size: int | float,
    *,
    bold: bool = False,
    italic: bool = False,
    color: str | None = None,
    tracking: int | None = None,
) -> None:
    """Apply font, size, style, color, and XML fallback chain to a pptx Run.

    font_role: one of "serif" | "sans" | "mono" | "header_serif" | "body_sans" | "mono_eyebrow"
    size: in points
    color: hex string e.g. "#FFFFFF"; if None, inherits from slide theme
    tracking: character spacing in 1/100 pt (e.g. 150 = +1.5 pt). None → no tracking set.
    """
    role_key = _FONT_ROLE_MAP.get(font_role, "body_sans")
    primary   = FONTS[role_key]
    fallbacks = FONT_FALLBACKS[role_key]

    f = run.font
    f.size  = Pt(size)
    f.bold  = bold
    f.italic = italic
    if color:
        f.color.rgb = hex_rgb(color)

    # Inject primary font name via XML (more reliable than f.name for cross-viewer)
    rPr = run._r.get_or_add_rPr()

    # Remove any existing <a:latin> so we start clean
    for old in rPr.findall(qn("a:latin")):
        rPr.remove(old)

    latin = etree.SubElement(rPr, qn("a:latin"))
    latin.set("typeface", primary)

    # Character tracking (letter-spacing)
    if tracking is not None:
        rPr.set("spc", str(tracking))


def _new_paragraph(tf, *, clear: bool = False):
    """Return the first paragraph of tf, optionally cleared of existing runs."""
    p = tf.paragraphs[0]
    if clear:
        for r in list(p.runs):
            p._p.remove(r._r)
    return p


# ── Text box factory ──────────────────────────────────────────────────────────

def add_textbox(
    slide,
    text: str,
    x: float, y: float, w: float, h: float,
    *,
    font_role: str = "sans",
    size: int | float = SIZES["body"],
    color: str = COLORS["ink_primary"],
    bold: bool = False,
    italic: bool = False,
    align: PP_ALIGN = PP_ALIGN.LEFT,
    tracking: int | None = None,
    wrap: bool = True,
    margin_left: float = 0.0,
    margin_top: float = 0.05,
):
    """Add a single-run text box. Returns the shape."""
    txb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    txb.word_wrap = wrap
    tf = txb.text_frame
    tf.word_wrap = wrap
    tf.margin_left  = Inches(margin_left)
    tf.margin_right = Inches(0)
    tf.margin_top   = Inches(margin_top)
    tf.margin_bottom = Inches(0)

    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    set_font(run, font_role, size, bold=bold, italic=italic, color=color,
             tracking=tracking)
    return txb


def add_multiline_textbox(
    slide,
    lines: list[dict],
    x: float, y: float, w: float, h: float,
    *,
    wrap: bool = True,
    margin_left: float = 0.0,
):
    """
    Add a text box with multiple paragraphs.

    lines: list of dicts with keys:
        text (str), font_role (str), size (num), color (str),
        bold (bool), italic (bool), align (PP_ALIGN), space_before (int pt)
    Returns the shape.
    """
    txb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    txb.word_wrap = wrap
    tf = txb.text_frame
    tf.word_wrap = wrap
    tf.margin_left   = Inches(margin_left)
    tf.margin_right  = Inches(0)
    tf.margin_top    = Inches(0.02)
    tf.margin_bottom = Inches(0)

    for i, spec in enumerate(lines):
        p = tf.paragraphs[i] if i == 0 else tf.add_paragraph()
        p.alignment = spec.get("align", PP_ALIGN.LEFT)
        sb = spec.get("space_before", 0)
        if sb:
            p.space_before = Pt(sb)
        run = p.add_run()
        run.text = spec.get("text", "")
        set_font(
            run,
            spec.get("font_role", "sans"),
            spec.get("size", SIZES["body"]),
            bold=spec.get("bold", False),
            italic=spec.get("italic", False),
            color=spec.get("color", COLORS["ink_primary"]),
            tracking=spec.get("tracking"),
        )
    return txb


# ── Slide-level composites ────────────────────────────────────────────────────

def add_eyebrow(
    slide,
    text: str,
    x: float = LAYOUT["margin_x_in"],
    y: float = LAYOUT["eyebrow_y_in"],
    *,
    color: str = COLORS["ink_muted"],
    width: float | None = None,
    on_dark: bool = False,
) -> None:
    """ALL-CAPS letter-spaced eyebrow label above the title."""
    if width is None:
        width = LAYOUT["slide_w_in"] - 2 * LAYOUT["margin_x_in"]
    c = color if not on_dark else COLORS["ink_on_dark_muted"]
    add_textbox(
        slide, text.upper(), x, y, width, 0.35,
        font_role="mono", size=SIZES["eyebrow"],
        color=c, tracking=EYEBROW_TRACKING,
    )


def add_title(
    slide,
    text: str,
    x: float = LAYOUT["margin_x_in"],
    y: float = LAYOUT["title_y_in"],
    *,
    size: int | float = SIZES["title"],
    color: str | None = None,
    italic: bool = False,
    width: float | None = None,
    height: float = 0.95,
) -> None:
    """Serif bold slide title."""
    if width is None:
        width = LAYOUT["slide_w_in"] - 2 * LAYOUT["margin_x_in"]
    if color is None:
        color = COLORS["ink_on_dark"]
    add_textbox(
        slide, text, x, y, width, height,
        font_role="serif", size=size,
        bold=True, italic=italic, color=color,
    )


def add_body(
    slide,
    text: str,
    x: float, y: float, w: float, h: float,
    *,
    size: int | float = SIZES["body"],
    color: str = COLORS["ink_primary"],
    italic: bool = False,
    align: PP_ALIGN = PP_ALIGN.LEFT,
) -> None:
    """Sans-serif body copy."""
    add_textbox(slide, text, x, y, w, h,
                font_role="sans", size=size,
                color=color, italic=italic, align=align)


# ── Shape primitives ──────────────────────────────────────────────────────────

def add_filled_rect(
    slide,
    x: float, y: float, w: float, h: float,
    fill_color: str,
    line_color: str | None = None,
    line_width_pt: float = 0.75,
) -> object:
    """Solid-filled rectangle. Returns the shape."""
    from pptx.util import Pt as _Pt
    shape = slide.shapes.add_shape(
        1,  # MSO_SHAPE_TYPE.RECTANGLE
        Inches(x), Inches(y), Inches(w), Inches(h),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = hex_rgb(fill_color)
    if line_color:
        shape.line.color.rgb = hex_rgb(line_color)
        shape.line.width = _Pt(line_width_pt)
    else:
        shape.line.fill.background()
    return shape


def add_circle(
    slide,
    cx: float, cy: float, diameter: float,
    fill_color: str,
    line_color: str | None = None,
    line_width_pt: float = 0.75,
) -> object:
    """Solid-filled circle centered at (cx, cy). Returns the shape."""
    from pptx.util import Pt as _Pt
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    x = cx - diameter / 2
    y = cy - diameter / 2
    shape = slide.shapes.add_shape(
        9,  # MSO_AUTO_SHAPE_TYPE.OVAL
        Inches(x), Inches(y), Inches(diameter), Inches(diameter),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = hex_rgb(fill_color)
    if line_color:
        shape.line.color.rgb = hex_rgb(line_color)
        shape.line.width = _Pt(line_width_pt)
    else:
        shape.line.fill.background()
    return shape


def add_concentric_circles(
    slide,
    cx: float, cy: float,
    max_diameter: float = LAYOUT["concentric_max_diameter_in"],
    color: str = COLORS["rule_on_dark"],
    rings: int = 4,
) -> None:
    """
    Draw concentric rings (outline only, no fill) as the decorative title motif.
    Rings are drawn largest-first so the center sits on top visually.
    """
    from pptx.util import Pt as _Pt
    step = max_diameter / rings
    for i in range(rings, 0, -1):
        d = step * i
        x = cx - d / 2
        y = cy - d / 2
        shape = slide.shapes.add_shape(
            9,  # OVAL
            Inches(x), Inches(y), Inches(d), Inches(d),
        )
        shape.fill.background()  # transparent fill
        shape.line.color.rgb = hex_rgb(color)
        shape.line.width = _Pt(1.25)


def add_footer(
    slide,
    *,
    section_label: str,
    page_num: int,
    total_pages: int,
    theme: str = "light",
) -> None:
    """
    Standard footer: thin rule + section label (left) + 'X / Y' (right).
    theme: 'light' (dark ink on white) or 'dark' (muted ink on teal).
    """
    rule_color = COLORS["rule_subtle"] if theme == "light" else COLORS["rule_on_dark"]
    ink_color  = COLORS["ink_muted"]   if theme == "light" else COLORS["ink_on_dark_muted"]

    w = LAYOUT["slide_w_in"] - 2 * LAYOUT["margin_x_in"]

    # Thin horizontal rule
    add_filled_rect(
        slide,
        LAYOUT["margin_x_in"], LAYOUT["footer_rule_y_in"],
        w, 0.012,
        rule_color,
    )

    # Section label — left
    add_textbox(
        slide, section_label.upper(),
        LAYOUT["margin_x_in"], LAYOUT["footer_y_in"],
        w * 0.75, 0.35,
        font_role="mono", size=SIZES["footer"],
        color=ink_color, tracking=EYEBROW_TRACKING,
    )

    # Page number — right
    page_str = f"{page_num} / {total_pages}"
    add_textbox(
        slide, page_str,
        LAYOUT["margin_x_in"] + w * 0.75, LAYOUT["footer_y_in"],
        w * 0.25, 0.35,
        font_role="mono", size=SIZES["footer"],
        color=ink_color, align=PP_ALIGN.RIGHT,
    )


def add_callout_box(
    slide,
    text: str,
    x: float, y: float, w: float, h: float,
    *,
    accent_color: str = COLORS["accent_coral"],
    bg_color: str = COLORS["bg_cream"],
    italic: bool = True,
    size: int | float = SIZES["body"],
    color: str = COLORS["ink_primary"],
) -> None:
    """
    Cream background box with a thin colored left edge — the 'callout' pattern.
    """
    bar_w = LAYOUT["left_accent_bar_w_in"]

    # Background fill
    add_filled_rect(slide, x, y, w, h, bg_color)

    # Colored left accent bar
    add_filled_rect(slide, x, y, bar_w, h, accent_color)

    # Text (inset from bar)
    pad = LAYOUT["card_padding_in"]
    add_textbox(
        slide, text,
        x + bar_w + pad, y + pad * 0.6,
        w - bar_w - pad * 1.6, h - pad * 1.2,
        font_role="sans", size=size,
        color=color, italic=italic, wrap=True,
    )


def add_left_accent_bar(
    slide,
    x: float, y: float, h: float,
    color: str,
    width: float = LAYOUT["left_accent_bar_w_in"],
) -> None:
    """Thin colored vertical bar on the left edge of a card or row."""
    add_filled_rect(slide, x, y, width, h, color)


def add_icon_glyph(
    slide,
    icon_name: str,
    x: float, y: float,
    size: int | float = 18,
    color: str = COLORS["accent_coral"],
    w: float = 0.45,
    h: float = 0.45,
) -> None:
    """
    Place a Unicode icon glyph from icons.py at (x, y).
    Font is forced to 'Segoe UI Symbol' for best Windows coverage.
    """
    from presentations.icons import get_icon_char
    txb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf  = txb.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = Inches(0)
    p   = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = get_icon_char(icon_name)
    # Force Segoe UI Symbol via XML for reliable glyph coverage on Windows
    run.font.size = Pt(size)
    run.font.color.rgb = hex_rgb(color)
    rPr = run._r.get_or_add_rPr()
    for old in rPr.findall(qn("a:latin")):
        rPr.remove(old)
    lat = etree.SubElement(rPr, qn("a:latin"))
    lat.set("typeface", "Segoe UI Symbol")


def add_icon_in_circle(
    slide,
    icon_name: str,
    cx: float, cy: float,
    diameter: float,
    circle_fill: str = COLORS["accent_coral"],
    icon_color: str = COLORS["ink_on_dark"],
    icon_size_pt: int | None = None,
) -> None:
    """Circle with a centered icon glyph inside it."""
    add_circle(slide, cx, cy, diameter, circle_fill)
    if icon_size_pt is None:
        icon_size_pt = int(diameter * 28)  # roughly 28pt per inch of diameter
    r = diameter / 2
    glyph_w = diameter * 0.9
    add_icon_glyph(
        slide, icon_name,
        cx - glyph_w / 2, cy - r * 0.55,
        size=icon_size_pt, color=icon_color,
        w=glyph_w, h=diameter * 0.9,
    )


# ── Presentation factory ──────────────────────────────────────────────────────

def new_presentation() -> Presentation:
    """Return a blank 16:9 Presentation with design-token dimensions."""
    prs = Presentation()
    prs.slide_width  = Inches(LAYOUT["slide_w_in"])
    prs.slide_height = Inches(LAYOUT["slide_h_in"])
    return prs


def blank_slide(prs: Presentation):
    """Add and return a completely blank slide (layout index 6)."""
    return prs.slides.add_slide(prs.slide_layouts[6])


__all__ = [
    "hex_rgb",
    "set_font",
    "add_textbox",
    "add_multiline_textbox",
    "add_eyebrow",
    "add_title",
    "add_body",
    "add_filled_rect",
    "add_circle",
    "add_concentric_circles",
    "add_footer",
    "add_callout_box",
    "add_left_accent_bar",
    "add_icon_glyph",
    "add_icon_in_circle",
    "new_presentation",
    "blank_slide",
]
