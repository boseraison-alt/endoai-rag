"""
Step 5 checkpoint — 5-slide test deck covering all patterns so far.

Slides:
  1. title_slide
  2. section_divider
  3. objectives_slide
  4. two_column_compare
  5. takeaways_slide

Run:
    python presentations/test_step5_patterns.py
Output:
    presentations/test_step5_patterns.pptx
"""

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from presentations.slide_helpers import new_presentation
from presentations.slide_patterns import (
    title_slide, section_divider,
    objectives_slide, two_column_compare, takeaways_slide,
)

OUT = os.path.join(os.path.dirname(__file__), "test_step5_patterns.pptx")
TOTAL = 5


def main():
    prs = new_presentation()

    # 1 — Title
    title_slide(
        prs,
        eyebrow="Endo AI · Deep Learning · Regenerative Endodontics",
        title="Why Regenerative\nEndodontic Procedures Fail",
        subtitle="Infection · Immature Anatomy · The Disinfection–Regeneration Tension",
        tagline=(
            "The same compromise that permits regeneration "
            "is the same compromise that permits reinfection."
        ),
        footer_metadata=(
            "Evidence: Level I–II RCTs + Systematic Reviews  ·  "
            "AAE / ESE Guidelines 2016–2023  ·  Endo AI v2"
        ),
        _page_num=1, _total_pages=TOTAL,
    )

    # 2 — Section divider
    section_divider(
        prs,
        module_label="Module 01",
        module_title="The Biology of REP Failure",
        module_subtitle=(
            "Persistent infection · Incomplete apexification · "
            "The SCAP vulnerability window"
        ),
        footer="Module 1 · Pathophysiology",
        _page_num=2, _total_pages=TOTAL,
    )

    # 3 — Objectives
    objectives_slide(
        prs,
        eyebrow="Module 1 · Learning Objectives",
        title="By the end of this module you will understand",
        items=[
            {
                "icon": "microscope",
                "number": "01",
                "header": "The microbial basis of REP failure",
                "body": (
                    "Why residual E. faecalis and polymicrobial biofilm "
                    "persist after reduced-concentration irrigation."
                ),
            },
            {
                "icon": "tooth",
                "number": "02",
                "header": "How immature anatomy amplifies risk",
                "body": (
                    "Thin dentinal walls, open apices, and the Hertwig's "
                    "epithelial root sheath — why young teeth are uniquely vulnerable."
                ),
            },
            {
                "icon": "alert",
                "number": "03",
                "header": "The disinfection–regeneration tension",
                "body": (
                    "The pharmacological trade-off that forces every REP "
                    "protocol to choose between sterility and stem-cell viability."
                ),
            },
            {
                "icon": "chart_bar",
                "number": "04",
                "header": "Evidence quality and guideline limits",
                "body": (
                    "Why AAE / ESE success rates of 85–96% mask a long-term "
                    "retreatment burden that case series under-report."
                ),
            },
        ],
        closing_callout=(
            "Clinical implication: the protocol you choose on Day 1 "
            "determines the failure mode you will manage in Year 3."
        ),
        _page_num=3, _total_pages=TOTAL,
    )

    # 4 — Two-column compare
    two_column_compare(
        prs,
        eyebrow="Module 1 · The Core Tension",
        title="The disinfection–regeneration trade-off",
        left_card={
            "label": "Conventional NaOCl 5.25%",
            "headline": "Full biofilm elimination",
            "lines": [
                "Kills E. faecalis reliably.",
                "Destroys SCAP stem cells.",
                "Collagen scaffold degraded.",
                "Regeneration impossible.",
            ],
            "verdict": {
                "icon": "x_circle",
                "text": "Incompatible with regeneration",
                "color": "accent_red",
            },
        },
        right_card={
            "label": "REP Protocol NaOCl 1.5%",
            "headline": "Stem-cell preservation",
            "lines": [
                "SCAP viability maintained.",
                "Residual bacteria tolerated.",
                "Scaffold intact for ingrowth.",
                "Reinfection risk accepted.",
            ],
            "verdict": {
                "icon": "check_circle",
                "text": "Compatible — but a compromise",
                "color": "accent_teal",
            },
        },
        center_chip="arrow_both",
        caption=(
            "Reducing NaOCl from 5.25% to 1.5% preserves the stem-cell niche "
            "but leaves a residual biofilm that drives long-term failure."
        ),
        _page_num=4, _total_pages=TOTAL,
    )

    # 5 — Takeaways
    takeaways_slide(
        prs,
        eyebrow="Module 1 · Key Takeaways",
        title="What every clinician must remember",
        items=[
            {
                "number": "01",
                "header": "REP is a biological compromise, not a cure",
                "body": "Success requires the residual biofilm to remain sub-threshold — forever.",
            },
            {
                "number": "02",
                "header": "Immature anatomy is both the indication and the liability",
                "body": "Thin walls fracture; open apices leak. The anatomy that makes REP necessary also makes it fragile.",
            },
            {
                "number": "03",
                "header": "1.5% NaOCl is the AAE floor — not a ceiling for safety",
                "body": "Some protocols use EDTA + CHX. Each lowers biofilm further but adds cytotoxicity risk.",
            },
            {
                "number": "04",
                "header": "Long-term follow-up reframes the 96% figure",
                "body": "Most RCTs end at 24 months. Retreatment rates at 5+ years are substantially higher.",
            },
            {
                "number": "05",
                "header": "Patient age and immune status are underweighted variables",
                "body": "Immunocompromised patients and those with systemic disease face disproportionate reinfection risk.",
            },
        ],
        _page_num=5, _total_pages=TOTAL,
    )

    prs.save(OUT)
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    main()
