"""
Step 10 — End-to-end test
==========================
Calls generate_slides_specs() with a realistic 10-module answer, passes the
result through build_deck_from_specs(), and saves the final PPTX.

Run:
    python presentations/test_step10_e2e.py

Output:
    presentations/test_step10_e2e.pptx
"""

import sys, os, json, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.abspath("."), ".env"))

from endo_ai import generate_slides_specs
from presentations.build_deck import build_deck_from_specs

OUT   = os.path.join(os.path.dirname(__file__), "test_step10_e2e.pptx")
TOPIC = "Why regenerative endodontic procedures fail: infection, immature anatomy, and the disinfection-regeneration tension"
MINS  = 12

# ── Realistic "answer" — the kind produced by stitch_curriculum() ─────────────
# This simulates the output that arrives at generate_slides_specs from the
# Deep Learning pipeline without needing to run the full curriculum engine.
MOCK_ANSWER = """
# Why Regenerative Endodontic Procedures Fail

## MODULE 1 — The Biology of Failure

Regenerative endodontic procedures (REP) exploit the stem cells of the apical papilla (SCAP) to regenerate pulp-like tissue in immature permanent teeth with pulpal necrosis. When the protocol works, radiographs at 24 months show periapical healing (96.1% in the AAE meta-analysis, n=412) and continued root development in 72–80% of cases (Alobaid et al., JOE 2014 [[PMID:25218510]]).

When it fails, the failure is biological: residual Enterococcus faecalis and polymicrobial biofilm survive the reduced-concentration irrigation mandated by the protocol. Conventional root canal disinfection uses 5.25% NaOCl — bactericidal and effective. REP protocols cap NaOCl at 1.5–3% to preserve SCAP viability. The trade-off is accepted knowingly; the risk is that residual bacteria remain sub-threshold until immune competence declines or a secondary carious lesion allows recolonisation.

Bukhari et al. (JOE 2017 [[PMID:28336379]]) found that 14% of REP cases showed evidence of persistent periapical pathology at 24 months, rising to an estimated 22% at 5 years in retrospective cohort studies.

---

## MODULE 2 — The Disinfection–Regeneration Tension

The AAE and ESE guidelines converge on 1.5% NaOCl as the irrigation ceiling for REP. Above this concentration, SCAP viability drops precipitously: Trevino et al. (JOE 2011 [[PMID:21496672]]) demonstrated 80% SCAP death at 2.5% NaOCl, with the effect concentration-dependent and irreversible.

This creates a hard clinical constraint: the clinician must choose between complete disinfection and stem-cell preservation. No irrigation protocol eliminates biofilm at 1.5% with the same reliability as 5.25%. Triple antibiotic paste (TAP — ciprofloxacin, metronidazole, minocycline) was introduced as an adjunct, but minocycline causes crown discolouration and TAP concentrations above 0.1 mg/mL are cytotoxic to SCAP (Ruparel et al., JOE 2012 [[PMID:22244641]]).

Current protocols favour Ca(OH)₂ or double antibiotic paste (DAP — ciprofloxacin + metronidazole) at ultra-low concentrations to balance disinfection with stem-cell preservation.

---

## MODULE 3 — Immature Anatomy as Both Indication and Liability

REP is indicated specifically because immature teeth have open apices — the portal of entry for SCAP migration and scaffold ingrowth. But immature anatomy also creates the failure conditions:

1. Thin dentinal walls (< 1 mm in some cases) are vulnerable to procedural fracture and external inflammatory root resorption.
2. Open apices allow bacterial reinfection from periapical tissue once the immune environment becomes permissive.
3. The Hertwig epithelial root sheath (HERS) must remain intact for continued root elongation; irrigation trauma or inter-appointment contamination disrupts this.

The failure cascade: residual biofilm → periapical immune activation → extracellular matrix degradation → scaffold failure → symptomatic recurrence. This cascade is clinically silent for 18–36 months. The 24-month RCT endpoint misses it.

---

## MODULE 4 — Evidence Quality and Guideline Limits

The AAE 2016 position statement cites 85–96% periapical healing success. This figure represents radiographic healing, not retreatment-free survival. When retreatment rates are extracted from case series with ≥ 5-year follow-up, the success rate falls to 61–72% (weighted average across 8 studies reviewed by Diogenes and Hargreaves, JOE 2017 [[PMID:28336379]]).

Evidence hierarchy:
- PRIMARY: Systematic reviews + RCTs — 96.1% periapical healing at 24 months
- SECONDARY: Prospective cohort studies — 78.4% at 36 months
- TERTIARY: Retrospective case series — 61.2% at 60+ months

The discrepancy is a follow-up problem, not a treatment problem. Clinicians who quote 96% to patients are quoting a 24-month figure from controlled trial conditions.

---

## MODULE 5 — Clinical Decision Framework

At 6-month re-evaluation, the following findings guide management:

| Finding | Implication | Action |
|---------|-------------|--------|
| Periapical healing + root development | Protocol successful | Observe 12-monthly |
| Persistent sinus tract | Biofilm load exceeds immune threshold | Retreatment with MTA apical plug |
| Calcific barrier, no symptoms | Calcific rather than pulp-like tissue | Monitor — do not instrument |
| Root fracture on CBCT | Thin walls + stress | Extraction, implant planning |
| Canal obliteration | HERS stimulation without pulp regeneration | Monitor; orthograde access may be impossible |

When retreatment is indicated, three routes exist: (1) REP retreatment if canal is accessible, (2) apical surgery if obliteration prevents orthograde access, (3) extraction + implant if root length or fracture precludes retention.

---

## KEY STATISTICS
- Periapical healing at 24 months: 96.1% (AAE meta-analysis, n=412)
- Continued root development: 72–80% (Alobaid et al. 2014)
- Persistent pathology at 24 months: 14% (Bukhari et al. 2017)
- Estimated 5-year retreatment rate: 22–39% (retrospective cohorts)
- SCAP death at 2.5% NaOCl: 80% (Trevino et al. 2011)
- 5-year survival in retreatment cohorts: 61% (Diogenes & Hargreaves 2017)
"""


def main():
    print("=" * 60)
    print(f"Step 10 — End-to-end pipeline test")
    print(f"  Topic  : {TOPIC}")
    print(f"  Length : {MINS} minutes")
    print("=" * 60)

    t0 = time.perf_counter()
    print("\n[1] Calling generate_slides_specs() ...")
    deck = generate_slides_specs(MOCK_ANSWER, TOPIC, MINS)

    slides = deck.get("slides", [])
    patterns_used = [s.get("pattern", s.get("type", "?")) for s in slides]
    print(f"    → {len(slides)} slides")
    print(f"    → patterns: {patterns_used}")

    # Check pattern diversity
    unique = set(patterns_used)
    print(f"    → {len(unique)} unique patterns: {sorted(unique)}")
    if len(unique) < 6:
        print("    WARNING: fewer than 6 unique patterns — prompt may need tuning")

    print("\n[2] Building PPTX via build_deck_from_specs() ...")
    # source_text is what gates chart rendering: spec §1.5 requires every
    # plotted value to appear verbatim in the cited source, so the builder is
    # handed the answer the deck was written from. Without it, no charts.
    prs, queue = build_deck_from_specs(deck, source_text=MOCK_ANSWER)
    print(f"    → {len(queue)} slides rendered "
          f"({len(queue) - len(slides)} added by the body-budget split)")

    from presentations.text_budget import has_raw_marker
    leaked = [
        n for n, (slide_obj, _, _) in enumerate(queue, 1)
        for shape in slide_obj.shapes
        if shape.has_text_frame and has_raw_marker(shape.text_frame.text)
    ]
    print(f"    → raw citation markers on slides: {len(leaked)} "
          f"{'(FAIL: ' + str(sorted(set(leaked))) + ')' if leaked else '(OK)'}")

    prs.save(OUT)
    size_kb = os.path.getsize(OUT) // 1024
    elapsed = time.perf_counter() - t0
    print(f"    → Saved: {OUT} ({size_kb} KB)")
    print(f"    → Total time: {elapsed:.1f}s")

    print("\n[3] Speaker notes check (TTS pipeline input):")
    for slide_obj, notes, num in queue:
        words = len(notes.split()) if notes else 0
        status = "OK" if words > 10 else "SHORT" if words > 0 else "EMPTY"
        print(f"    slide {num:2d}  {status:5s}  {words} words")

    has_notes = sum(1 for _, n, _ in queue if n and len(n.split()) > 10)
    print(f"\n    {has_notes}/{len(queue)} slides have ≥10-word speaker notes for TTS")

    print("\n" + "=" * 60)
    print("RESULT: open presentations/test_step10_e2e.pptx in PowerPoint")
    print("        Verify: 6+ distinct layouts, no overflow, footer on every slide")
    print("=" * 60)


if __name__ == "__main__":
    main()
