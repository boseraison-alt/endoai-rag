"""
Curo presentation engine — design-token-driven PPTX deck builder.

The visual identity is the approved design spec in PRESENTATION_WORKLIST.md §1:
a dark navy theme, Instrument Serif / Inter substituted by Georgia / Calibri,
a semantic tier colour ladder, and eight layouts plus an insufficient-evidence
notice.

Public surface:
    from presentations.design_tokens import COLORS, FONTS, SIZES, LAYOUT, TIER_CHIP
    from presentations.slide_helpers  import add_header_row, add_footer, add_tier_chip, ...
    from presentations.slide_patterns import title_slide, content_slide, table_slide, ...
    from presentations.build_deck     import build_deck_from_specs

Internal layout:
    presentations/
        design_tokens.py   — palette, tier ladder, fonts, sizes, geometry
        text_budget.py     — body-budget auto-split + citation-marker rules
        chart_data.py      — the chartable-data detector (§1.5 hard rules)
        charts.py          — matplotlib chart rendering to PNG
        slide_helpers.py   — python-pptx primitives, chips, pills, furniture
        icons.py           — SVG → PNG icon renderer with Unicode fallback
        slide_patterns.py  — the eight layouts, the notice slide, and adapters
        build_deck.py      — pattern-name → function dispatcher
        icons/             — monochrome SVG icon set (Tabler / Lucide)
"""
