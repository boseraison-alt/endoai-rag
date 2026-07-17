"""
Endo AI presentation engine — design-token-driven PPTX deck builder.

Public surface:
    from presentations.design_tokens import COLORS, FONTS, SIZES, LAYOUT, FONT_FALLBACKS
    from presentations.slide_helpers  import set_font, add_title, add_eyebrow, ...
    from presentations.slide_patterns import title_slide, two_column_compare, ...
    from presentations.build_deck     import build_deck_from_specs

Internal layout:
    presentations/
        design_tokens.py   — palette, fonts, sizes, slide geometry (single source of truth)
        slide_helpers.py   — python-pptx boilerplate (font, color, shape primitives)
        icons.py           — SVG → PNG icon renderer (cairosvg) with Unicode fallback
        slide_patterns.py  — 10 named slide-layout functions
        build_deck.py      — pattern-name → function dispatcher
        icons/             — monochrome SVG icon set (Tabler / Lucide)
"""
