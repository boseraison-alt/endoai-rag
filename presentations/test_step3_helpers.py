"""
Step 3 checkpoint — render a 2-slide PPTX that exercises every slide_helper.

Slide 1 (light):  eyebrow · serif title · body copy · callout box · icon-in-circle · footer
Slide 2 (dark):   concentric circles · dark eyebrow · serif italic title · accent bar · footer

Run:
    python presentations/test_step3_helpers.py
Output:
    presentations/test_step3_helpers.pptx
"""

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pptx.enum.text import PP_ALIGN
from presentations.design_tokens import COLORS, SIZES, LAYOUT, SEMANTIC
from presentations.slide_helpers import (
    new_presentation, blank_slide,
    add_eyebrow, add_title, add_body, add_footer,
    add_filled_rect, add_circle, add_concentric_circles,
    add_callout_box, add_left_accent_bar,
    add_icon_glyph, add_icon_in_circle,
    add_textbox,
)

OUT = os.path.join(os.path.dirname(__file__), "test_step3_helpers.pptx")


def slide_light(prs):
    """Light-background slide exercising most helpers."""
    slide = blank_slide(prs)

    # Background
    add_filled_rect(slide, 0, 0, LAYOUT["slide_w_in"], LAYOUT["slide_h_in"],
                    COLORS["bg_light"])

    # Eyebrow
    add_eyebrow(slide, "Step 3 · Helper Proof Sheet · Light Theme", on_dark=False)

    # Serif title (Georgia fallback chain)
    add_title(slide, "Georgia Title — Serif Bold 40 pt",
              color=COLORS["ink_primary"])

    # Thin coral underline below title
    add_filled_rect(slide,
                    LAYOUT["margin_x_in"], LAYOUT["title_underline_y"],
                    5.0, 0.022,
                    COLORS["accent_coral"])

    # Body copy (Calibri)
    add_body(slide,
             "Calibri body copy at 15 pt — regular weight, dark ink. "
             "This line verifies the sans-serif font fallback chain renders "
             "correctly and does not fall back to the theme default.",
             LAYOUT["margin_x_in"], 2.05, 7.5, 0.60,
             color=COLORS["ink_primary"])

    add_body(slide,
             "Italic secondary body copy — used for captions, evidence qualifiers, "
             "and emphasis lines inside card content.",
             LAYOUT["margin_x_in"], 2.72, 7.5, 0.50,
             color=COLORS["ink_secondary"], italic=True,
             size=SIZES["body_sm"])

    # Callout box
    add_callout_box(
        slide,
        "Callout box — cream background, coral left edge. Used for key takeaways "
        "and clinical punch lines at the base of content slides.",
        LAYOUT["margin_x_in"], 3.35, 7.8, 0.82,
        accent_color=COLORS["accent_coral"],
    )

    # Icon-in-circle row  (4 icons across)
    icon_y = 4.42
    icons = [
        ("check",      COLORS["accent_teal"],  "Yes / Go"),
        ("x",          COLORS["accent_red"],   "No / Stop"),
        ("alert",      COLORS["accent_gold"],  "Caution"),
        ("arrow_right",COLORS["accent_coral"], "Next step"),
    ]
    start_x = LAYOUT["margin_x_in"]
    col_w   = 2.0
    for i, (name, fill, label) in enumerate(icons):
        cx = start_x + i * col_w + 0.3
        add_icon_in_circle(slide, name, cx, icon_y + 0.25, 0.52, circle_fill=fill)
        add_textbox(slide, label,
                    cx - 0.5, icon_y + 0.62, 1.2, 0.30,
                    font_role="sans", size=10,
                    color=COLORS["ink_secondary"], align=PP_ALIGN.CENTER)

    # Left accent bars of various colors (severity demo)
    bar_x   = 9.2
    bar_data = [
        (COLORS["accent_red"],  "High severity — red bar"),
        (COLORS["accent_gold"], "Medium — gold bar"),
        (COLORS["accent_teal"], "Favourable — teal bar"),
    ]
    for j, (bar_c, label) in enumerate(bar_data):
        by = 2.05 + j * 0.72
        add_left_accent_bar(slide, bar_x, by, 0.55, bar_c)
        add_body(slide, label, bar_x + 0.18, by + 0.08, 3.8, 0.42,
                 size=SIZES["body_sm"], color=COLORS["ink_primary"])

    # Footer
    add_footer(slide, section_label="Step 3 · Helpers", page_num=1, total_pages=2,
               theme="light")


def slide_dark(prs):
    """Dark-background slide: concentric circles, serif italic, dark footer."""
    slide = blank_slide(prs)

    # Dark background
    add_filled_rect(slide, 0, 0, LAYOUT["slide_w_in"], LAYOUT["slide_h_in"],
                    COLORS["bg_dark"])

    # Concentric circles motif — top-right quadrant
    add_concentric_circles(
        slide,
        cx=LAYOUT["slide_w_in"] - 1.5,
        cy=1.8,
        max_diameter=LAYOUT["concentric_max_diameter_in"],
        color=COLORS["rule_on_dark"],
        rings=5,
    )

    # Eyebrow (on dark)
    add_eyebrow(slide, "Step 3 · Helper Proof Sheet · Dark Theme", on_dark=True)

    # Serif italic title
    add_title(slide,
              "Georgia Italic — a serif title on dark teal",
              color=COLORS["ink_on_dark"], italic=True)

    # Coral accent bar beneath title
    add_filled_rect(slide,
                    LAYOUT["margin_x_in"], LAYOUT["title_underline_y"],
                    4.0, 0.022,
                    COLORS["accent_coral"])

    # Subtitle line
    add_body(slide,
             "Calibri body on dark — muted white ink for secondary text and subheads.",
             LAYOUT["margin_x_in"], 2.10, 8.0, 0.50,
             color=COLORS["ink_on_dark_muted"])

    # Gold callout box on dark slide
    add_callout_box(
        slide,
        "Gold accent callout — used for evidence-quality caveats on dark slides.",
        LAYOUT["margin_x_in"], 2.80, 7.8, 0.72,
        accent_color=COLORS["accent_gold"],
        bg_color="#1A4F53",
        color=COLORS["ink_on_dark"],
    )

    # Lone icon glyphs (not in circles) — for inline use
    glyph_y = 3.80
    pairs = [
        ("tooth",      COLORS["accent_coral"]),
        ("microscope", COLORS["accent_teal"]),
        ("book",       COLORS["accent_gold"]),
        ("certificate",COLORS["ink_on_dark"]),
        ("star",       COLORS["accent_gold"]),
        ("check",      COLORS["accent_teal"]),
    ]
    gx = LAYOUT["margin_x_in"]
    for name, col in pairs:
        add_icon_glyph(slide, name, gx, glyph_y, size=22, color=col)
        add_textbox(slide, name, gx - 0.05, glyph_y + 0.38, 0.9, 0.28,
                    font_role="mono", size=8, color=COLORS["ink_on_dark_muted"])
        gx += 1.05

    # Footer (dark theme)
    add_footer(slide, section_label="Step 3 · Helpers", page_num=2, total_pages=2,
               theme="dark")


def main():
    prs = new_presentation()
    slide_light(prs)
    slide_dark(prs)
    prs.save(OUT)
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    main()
