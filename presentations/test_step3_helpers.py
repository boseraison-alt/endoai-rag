"""
Step 3 checkpoint — render a 2-slide PPTX that exercises every slide_helper.

Rewritten for the approved dark spec (PRESENTATION_WORKLIST §1). The previous
version of this checkpoint proved a *light* theme built from concentric-circle
motifs and cream callout boxes; both of those design decisions are gone — the
deck is dark throughout, and the callout is now a surface-filled notice box —
so the sheet asserts the current furniture rather than the retired furniture.

Slide 1: header row · title · lead · bullets · tier chips · PMID pills · footer
Slide 2: notice box · decision-card chips · table header/zebra · hairlines

Run:
    python presentations/test_step3_helpers.py
Output:
    presentations/test_step3_helpers.pptx
"""

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from presentations.design_tokens import (
    COLORS, SIZES, LAYOUT, TIER_ORDER, TIER_CHIP, TIER_LABELS,
    CHIP_IF, CHIP_THEN, CHIP_BECAUSE, BULLET_MARKER, TRACK_CHIP, px_in,
)
from presentations.slide_helpers import (
    new_presentation, dark_slide,
    add_header_row, add_slide_title, add_lead, add_footer,
    add_bullet_row, add_notice_box, add_chip, add_tier_chip, add_pmid_pill,
    add_filled_rect, add_rounded_rect, add_hairline, add_textbox,
    contrast_ratio, font_fallback_chain,
)

OUT = os.path.join(os.path.dirname(__file__), "test_step3_helpers.pptx")
_PX = LAYOUT["pad_x_in"]
_CW = LAYOUT["content_w_in"]


def slide_typography(prs):
    """Header row, title, lead, bullets, tier chips, PMID pills, footer."""
    slide = dark_slide(prs)
    add_header_row(slide, "Step 3 · helper proof sheet", right_label="CURO")
    y = add_slide_title(slide, "Georgia stands in for Instrument Serif")
    y = add_lead(
        slide,
        "Inter is substituted by Calibri. PowerPoint cannot embed a webfont, "
        "so the deck names locally-installed faces of the same class.",
        y) + px_in(26)

    for text in (
        "Body copy at 17px on a 1.55 line height, in the text-body token.",
        "A bullet marker is an 8px round dot in the single-series blue.",
        "Every run passes through the citation-marker sanitiser on its way in.",
    ):
        y = add_bullet_row(slide, text, _PX, y, _CW,
                           marker_color=BULLET_MARKER) + px_in(16)

    # Tier chip ladder — every chip carries its text label, never colour alone.
    y += px_in(10)
    x = _PX
    for tier in TIER_ORDER:
        x += add_tier_chip(slide, tier, x, y) + px_in(10)

    y += px_in(38)
    x = _PX
    for pmid in ("28294701", "36512807", "36156804"):
        x += add_pmid_pill(slide, pmid, x, y) + px_in(10)

    add_footer(slide,
               citations="Schulte-Lünzum et al. 2017 · Photomedicine and "
                         "Laser Surgery · n = 100 · PMID 28294701",
               page_num=1)


def slide_surfaces(prs):
    """Notice box, decision-card chips, table header/zebra, hairlines."""
    slide = dark_slide(prs)
    add_header_row(slide, "Step 3 · surfaces", tier="level1")
    y = add_slide_title(slide, "Surfaces, chips and rules") + px_in(26)

    add_notice_box(
        slide,
        "A notice box sits on the surface token with a 10px radius. It carries "
        "the contraindication line on takeaways, and the "
        "insufficient-evidence message on a module the evidence gate refused.",
        _PX, y, _CW, px_in(120), heading="Does not apply when")
    y += px_in(146)

    # Decision-card chip row
    card_h = px_in(120)
    add_rounded_rect(slide, _PX, y, _CW * 0.48, card_h, COLORS["card"],
                     radius_in=LAYOUT["card_radius_in"],
                     line_color=COLORS["border"])
    cy = y + px_in(20)
    for label, (bg, fg) in (("IF", CHIP_IF), ("THEN", CHIP_THEN),
                            ("BECAUSE", CHIP_BECAUSE)):
        w = add_chip(slide, label, _PX + px_in(24), cy, bg=bg, fg=fg,
                     radius_in=LAYOUT["chip_radius_in"], tracking=TRACK_CHIP)
        add_textbox(slide, f"{label.title()} row text at 16px.",
                    _PX + px_in(24) + w + px_in(12), cy,
                    _CW * 0.48 - w - px_in(60), px_in(26),
                    size=SIZES["card_body"],
                    color=COLORS["text_secondary"] if label == "BECAUSE"
                    else COLORS["text_body"])
        cy += px_in(32)

    # Table header + zebra rows + hairlines
    tx = _PX + _CW * 0.52
    tw = _CW * 0.48
    add_rounded_rect(slide, tx, y, tw, card_h, COLORS["bg"],
                     radius_in=LAYOUT["table_radius_in"],
                     line_color=COLORS["border"])
    add_rounded_rect(slide, tx, y, tw, px_in(34), COLORS["surface"],
                     radius_in=LAYOUT["table_radius_in"])
    add_textbox(slide, "Parameter", tx + px_in(16), y + px_in(9),
                tw - px_in(32), px_in(20), size=SIZES["table_header"],
                color=COLORS["text_body"], bold=True, upper=True, wrap=False)
    ry = y + px_in(34)
    for i, label in enumerate(("Zebra row", "Plain row", "Zebra row")):
        if i % 2 == 0:
            add_filled_rect(slide, tx + px_in(1), ry, tw - px_in(2), px_in(28),
                            COLORS["surface_alt"])
        add_hairline(slide, tx, ry, tw)
        add_textbox(slide, label, tx + px_in(16), ry + px_in(4),
                    tw - px_in(32), px_in(22), size=SIZES["table_body"],
                    color=COLORS["text_secondary"], wrap=False)
        ry += px_in(28)

    add_footer(slide, citations="Dark surfaces · spec §1.1 tokens", page_num=2)


def main():
    prs = new_presentation()
    slide_typography(prs)
    slide_surfaces(prs)
    prs.save(OUT)
    print(f"Saved: {OUT}")
    print("display fallback:", " > ".join(font_fallback_chain("display")))
    print("body fallback:   ", " > ".join(font_fallback_chain("body")))
    for key in ("text_body", "text_secondary", "text_footer", "text_muted"):
        ratio = contrast_ratio(COLORS[key], COLORS["bg"])
        flag = "OK " if ratio >= 4.5 else "FAIL"
        print(f"  {flag} {key:15s} {ratio:.2f}:1 on {COLORS['bg']}")


if __name__ == "__main__":
    main()
