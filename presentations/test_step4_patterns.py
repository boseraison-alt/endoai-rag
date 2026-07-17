"""
Step 4 checkpoint — render a 2-slide test deck: title_slide + section_divider.

Run:
    python presentations/test_step4_patterns.py
Output:
    presentations/test_step4_patterns.pptx
"""

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from presentations.slide_helpers import new_presentation
from presentations.slide_patterns import title_slide, section_divider

OUT = os.path.join(os.path.dirname(__file__), "test_step4_patterns.pptx")


def main():
    prs = new_presentation()

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
            "Evidence tier: Level I–II RCTs + Systematic Reviews  ·  "
            "AAE / ESE Guidelines 2016–2023  ·  Endo AI v2"
        ),
        _page_num=1,
        _total_pages=2,
    )

    section_divider(
        prs,
        module_label="Module 01",
        module_title="The Biology of REP Failure",
        module_subtitle=(
            "Persistent infection · Incomplete apexification · "
            "The SCAP vulnerability window"
        ),
        footer="Module 1 · Pathophysiology",
        _page_num=2,
        _total_pages=2,
    )

    prs.save(OUT)
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    main()
