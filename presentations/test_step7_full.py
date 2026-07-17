"""
Step 7 checkpoint — full 10-slide reference-content deck using all patterns.

Run:
    python presentations/test_step7_full.py
Output:
    presentations/test_step7_full.pptx
"""

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from presentations.slide_helpers import new_presentation
from presentations.slide_patterns import (
    title_slide, section_divider, objectives_slide,
    two_column_compare, cascade_slide, decision_table,
    three_route_grid, stat_panel, evidence_summary, takeaways_slide,
)

OUT   = os.path.join(os.path.dirname(__file__), "test_step7_full.pptx")
TOTAL = 10


def main():
    prs = new_presentation()

    # 1 ── Title
    title_slide(prs,
        eyebrow="Endo AI · Deep Learning · Regenerative Endodontics",
        title="Why Regenerative\nEndodontic Procedures Fail",
        subtitle="Infection · Immature Anatomy · The Disinfection–Regeneration Tension",
        tagline="The same compromise that permits regeneration is the same compromise that permits reinfection.",
        footer_metadata="Evidence: Level I–II RCTs + Systematic Reviews  ·  AAE / ESE Guidelines 2016–2023  ·  Endo AI v2",
        _page_num=1, _total_pages=TOTAL)

    # 2 ── Section divider
    section_divider(prs,
        module_label="Module 01",
        module_title="The Biology of REP Failure",
        module_subtitle="Persistent infection · Incomplete apexification · The SCAP vulnerability window",
        footer="Module 1 · Pathophysiology",
        _page_num=2, _total_pages=TOTAL)

    # 3 ── Objectives
    objectives_slide(prs,
        eyebrow="Module 1 · Learning Objectives",
        title="By the end of this module you will understand",
        items=[
            {"icon":"microscope","number":"01","header":"The microbial basis of REP failure","body":"Why residual E. faecalis and polymicrobial biofilm persist after reduced-concentration irrigation."},
            {"icon":"tooth","number":"02","header":"How immature anatomy amplifies risk","body":"Thin dentinal walls, open apices, and the Hertwig epithelial root sheath — why young teeth are uniquely vulnerable."},
            {"icon":"alert","number":"03","header":"The disinfection–regeneration tension","body":"The pharmacological trade-off that forces every REP protocol to choose between sterility and stem-cell viability."},
            {"icon":"chart_bar","number":"04","header":"Evidence quality and guideline limits","body":"Why AAE / ESE success rates of 85–96% mask a long-term retreatment burden that case series under-report."},
        ],
        closing_callout="Clinical implication: the protocol you choose on Day 1 determines the failure mode you will manage in Year 3.",
        _page_num=3, _total_pages=TOTAL)

    # 4 ── Two-column compare
    two_column_compare(prs,
        eyebrow="Module 1 · The Core Tension",
        title="The disinfection–regeneration trade-off",
        left_card={
            "label": "Conventional NaOCl 5.25%",
            "headline": "Full biofilm elimination",
            "lines": ["Kills E. faecalis reliably.", "Destroys SCAP stem cells.", "Collagen scaffold degraded.", "Regeneration impossible."],
            "verdict": {"icon":"x_circle","text":"Incompatible with regeneration","color":"accent_red"},
        },
        right_card={
            "label": "REP Protocol NaOCl 1.5%",
            "headline": "Stem-cell preservation",
            "lines": ["SCAP viability maintained.", "Residual bacteria tolerated.", "Scaffold intact for ingrowth.", "Reinfection risk accepted."],
            "verdict": {"icon":"check_circle","text":"Compatible — but a compromise","color":"accent_teal"},
        },
        center_chip="arrow_both",
        caption="Reducing NaOCl from 5.25% to 1.5% preserves the stem-cell niche but leaves a residual biofilm that drives long-term failure.",
        _page_num=4, _total_pages=TOTAL)

    # 5 ── Cascade
    cascade_slide(prs,
        eyebrow="Module 2 · The Failure Cascade",
        title="How a successful REP becomes a retreatment case",
        steps=[
            {"number":"01","header":"Residual biofilm","body":"1.5% NaOCl leaves a sub-threshold bacterial load at the apical third."},
            {"number":"02","header":"Immune provocation","body":"Low-grade periapical inflammation — undetected on standard radiographs."},
            {"number":"03","header":"Scaffold degradation","body":"Chronic inflammation degrades the extracellular matrix; new tissue loses structural support."},
            {"number":"04","header":"Symptomatic recurrence","body":"Sinus tract, swelling, or pain — typically 2–5 years post-procedure."},
            {"number":"05","header":"Retreatment or extraction","body":"Canal obliteration makes conventional retreatment technically demanding or impossible."},
        ],
        footer_callout="The failure cascade is clinically silent for months to years — the 24-month RCT endpoint misses it entirely.",
        _page_num=5, _total_pages=TOTAL)

    # 6 ── Evidence summary
    evidence_summary(prs,
        eyebrow="Module 2 · Evidence Hierarchy",
        title="What the evidence actually shows",
        hierarchy_rows=[
            {"tier_label":"PRIMARY","description":"Systematic reviews + RCTs — periapical healing, root development, survival","stat":"96.1%","color":"accent_teal"},
            {"tier_label":"SECONDARY","description":"Prospective cohort studies — long-term follow-up beyond 24 months","stat":"78.4%","color":"accent_gold"},
            {"tier_label":"TERTIARY","description":"Retrospective case series — retreatment and complication rates","stat":"61.2%","color":"accent_coral"},
            {"tier_label":"EXPERT","description":"AAE / ESE position statements and clinical guidelines","stat":"—","color":"ink_secondary"},
            {"tier_label":"CLASSIC","description":"Foundational anatomy, microbiology, and pulp biology studies","stat":"—","color":"ink_muted"},
        ],
        trap_callout={
            "heading": "THE TRAP",
            "body": "The 96.1% headline figure comes from studies ending at 24 months. The retreatment literature — mostly case series — shows a very different picture when follow-up extends to 5+ years.",
            "stat": "61%",
            "stat_label": "5-year survival in retreatment cohort studies (weighted average)",
            "color": "accent_coral",
        },
        _page_num=6, _total_pages=TOTAL)

    # 7 ── Decision table
    decision_table(prs,
        eyebrow="Module 3 · Clinical Decision Framework",
        title="Findings at re-evaluation and their implications",
        rows=[
            {"finding":"Periapical healing + root development","implication":"Protocol working as intended; continue monitoring","path":"Observe at 12-month intervals","severity_color":"accent_teal"},
            {"finding":"Persistent sinus tract at 6 months","implication":"Biofilm load exceeding immune threshold","path":"Retreatment with MTA apical plug","severity_color":"accent_red"},
            {"finding":"Calcific barrier, no symptoms","implication":"Calcific rather than pulp-like tissue regeneration","path":"Monitor — do not instrument","severity_color":"accent_gold"},
            {"finding":"Coronal discolouration (MTA)","implication":"Chromogenic by-product from grey MTA","path":"Bleaching or white MTA replacement","severity_color":"accent_gold"},
            {"finding":"Root fracture on CBCT","implication":"Thin walls, procedural stress, or resorption","path":"Extraction; consider implant timeline","severity_color":"accent_red"},
            {"finding":"No radiographic change at 12 months","implication":"Inconclusive — process ongoing or stalled","path":"Repeat CBCT; discuss risk with patient","severity_color":"ink_secondary"},
        ],
        footer_caption="All pathways follow AAE Position Statement on REP (2016, updated 2021). CBCT indicated where 2D radiograph is equivocal.",
        _page_num=7, _total_pages=TOTAL)

    # 8 ── Three-route grid
    three_route_grid(prs,
        eyebrow="Module 3 · Treatment Routes",
        title="Three paths after failed REP",
        routes=[
            {
                "color": "accent_teal",
                "icon": "repeat",
                "name": "REP Retreatment",
                "tagline": "When pulp space is accessible",
                "when": "Immature apex remains, patient is young, and no canal obliteration on CBCT.",
                "how": "Re-irrigate with 17% EDTA + 1.5% NaOCl. Re-establish blood clot. Seal with white MTA.",
                "citation": "Diogenes & Hargreaves, JOE 2017",
            },
            {
                "color": "accent_coral",
                "icon": "tooth",
                "name": "Apical Surgery",
                "tagline": "When canal is obliterated",
                "when": "Canal calcification prevents orthograde access. Periapical lesion persists.",
                "how": "Apicoectomy + retrograde MTA fill. Guided bone regeneration if buccal plate lost.",
                "citation": "AAE Microsurgery Position Statement, 2020",
            },
            {
                "color": "accent_gold",
                "icon": "x",
                "name": "Extraction + Implant",
                "tagline": "When the tooth is non-restorable",
                "when": "Root fracture confirmed. Root length < 9 mm. Patient preference after counselling.",
                "how": "Atraumatic extraction. Ridge preservation graft. Implant after 4–6 months.",
                "citation": "Torabinejad et al., JOE 2020",
            },
        ],
        _page_num=8, _total_pages=TOTAL)

    # 9 ── Stat panel
    stat_panel(prs,
        eyebrow="Module 3 · Outcomes in Numbers",
        title="What the numbers say about REP success",
        primary_stat="96.1%",
        primary_label="Periapical healing at 24 months in AAE meta-analysis (n = 412 teeth, Level I evidence)",
        secondary_stat="61%",
        secondary_label="Estimated 5-year survival when long-term retreatment cohorts are included (Level III evidence)",
        callout="The gap between 96% and 61% is not a contradiction — it is a follow-up problem. Studies that end at 24 months cannot see the failure cascade.",
        citation="Sources: Alobaid et al. JOE 2014; Bukhari et al. JOE 2017; Diogenes & Hargreaves JOE 2017; AAE Position Statement 2021.",
        _page_num=9, _total_pages=TOTAL)

    # 10 ── Takeaways
    takeaways_slide(prs,
        eyebrow="Module Summary · Key Takeaways",
        title="What every clinician must remember",
        items=[
            {"number":"01","header":"REP is a biological compromise, not a cure","body":"Success requires the residual biofilm to remain sub-threshold — forever."},
            {"number":"02","header":"Immature anatomy is both the indication and the liability","body":"Thin walls fracture; open apices leak. The anatomy that makes REP necessary also makes it fragile."},
            {"number":"03","header":"The failure cascade is clinically silent","body":"Sinus tracts and symptoms appear 2–5 years post-procedure — long after the 24-month RCT endpoint."},
            {"number":"04","header":"Retreatment options narrow with time","body":"Canal obliteration forecloses orthograde access. Early recognition and intervention preserves options."},
            {"number":"05","header":"Shared decision-making is non-negotiable","body":"Patients must understand the long-term monitoring commitment before consenting to REP."},
        ],
        _page_num=10, _total_pages=TOTAL)

    prs.save(OUT)
    print(f"Saved: {OUT}")
    print(f"Slides: {TOTAL}")
    print(f"Patterns used: title_slide, section_divider, objectives_slide, two_column_compare,")
    print(f"               cascade_slide, evidence_summary, decision_table, three_route_grid,")
    print(f"               stat_panel, takeaways_slide  (all 10)")


if __name__ == "__main__":
    main()
