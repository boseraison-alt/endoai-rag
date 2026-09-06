"""Item B — the two syntheses that show the GL citation form working.

WHICH LITERATURE QUESTION, and why it is named rather than "the one with the
most guideline rows". Six of the 29 tied at 20 in last night's measurement,
because 20 is the esearch retmax, not a pool size — so "the most" does not
pick a question. `retreatment-vs-microsurgery` is chosen from that tied set
because its own named regression fixture IS a guideline: PMID 37772327, the
ESE S3 2023 clinical practice guideline. A question whose known target is a
guideline is the one where a guideline citation form has to work.

Reported per answer: GL citations, PMID-slot slugs after rewrite (must be 0),
rewrites performed, unknown GL drops.

    python scripts/run_gl_syntheses.py
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RUNS = [
    ("probe3-retreat-implant",
     "Mature molar with a failed root canal retreatment. The patient asks for "
     "extraction and an implant. How should this be decided?"),
    ("retreatment-vs-microsurgery",
     "Nonsurgical retreatment versus apical microsurgery for persistent "
     "apical periodontitis"),
]


def main():
    from app import build_evidence_base_with_progress, jobs
    import endo_ai as E

    results = {}
    for cid, question in RUNS:
        print("=" * 78)
        print("ITEM B SYNTHESIS — %s" % cid)
        print("=" * 78)
        job = "glsyn_%s" % cid
        jobs[job] = {"status": "running", "steps": [], "progress": 0}
        ev = build_evidence_base_with_progress(job, question) or {}

        gl_rows = [(p.get("pmid"), p.get("guideline_id"))
                   for p in ((ev.get("guideline") or {}).get("scored") or [])]
        print("  guideline pool: %d  %s"
              % (len(gl_rows), [g or p for p, g in gl_rows]))

        # CAPTURE WHAT THE MODEL ACTUALLY WROTE.
        #
        # The first version of this script counted markers in the value
        # `ask_clinical_question` returns and called them "raw". They are not:
        # that function calls `finalise_answer_text` internally (endo_ai.py
        # ~10044), so the GL markers have already been rendered to text and
        # the PMID-slot slugs have already been rewritten by the time the
        # value comes back. It reported "GL markers the model wrote: 0"
        # alongside "rendered guideline citations: 1", which cannot both be
        # true and is what gave the instrument away.
        #
        # So the finaliser is wrapped and its INPUT recorded. That is the only
        # place the model's own text exists.
        captured = []
        _real_finalise = E.finalise_answer_text

        def _spy(a):
            captured.append(a)
            return _real_finalise(a)

        E.finalise_answer_text = _spy
        try:
            ans = E.ask_clinical_question(question, ev)
        finally:
            E.finalise_answer_text = _real_finalise
        served = ans if isinstance(ans, str) else (
            ans[0] if isinstance(ans, tuple) else str(ans))
        text = captured[0] if captured else served

        gl_marks = re.findall(r"\[\[GL:\s*([^\]]+?)\s*\]\]", text)
        pmid_marks = re.findall(r"\[\[PMID:\s*([^\]]+?)\s*\]\]", text)
        slug_in_pmid = [i for i in pmid_marks if not i.strip().isdigit()]
        gl_after = re.findall(r"\[\[GL:\s*([^\]]+?)\s*\]\]", served)
        pmid_after = re.findall(r"\[\[PMID:\s*([^\]]+?)\s*\]\]", served)
        slug_after = [i for i in pmid_after if not i.strip().isdigit()]

        rec = {
            "question": question,
            "guideline_pool": [g or p for p, g in gl_rows],
            "raw_gl_markers": gl_marks,
            "raw_pmid_slot_slugs": slug_in_pmid,
            "served_gl_markers_left": gl_after,
            "served_pmid_slot_slugs": slug_after,
            "rendered_guideline_citations": re.findall(
                r"\[[A-Z][^\]]{0,90}\(\d{4}[^\]]*\)\]", served),
        }
        results[cid] = rec
        Path("eval/reports").mkdir(parents=True, exist_ok=True)
        Path("eval/reports/night9_itemb_%s.md" % cid).write_text(
            served, encoding="utf-8")

        print("  GL markers the model wrote          %d  %s"
              % (len(gl_marks), sorted(set(gl_marks))))
        print("  guideline ids in a PMID slot (raw)  %d  %s"
              % (len(slug_in_pmid), sorted(set(slug_in_pmid))))
        print("  --- after finalise_answer_text ---")
        print("  guideline ids in a PMID slot        %d   <-- MUST BE 0"
              % len(slug_after))
        print("  unrendered GL markers left          %d   <-- MUST BE 0"
              % len(gl_after))
        print("  rendered guideline citations        %d"
              % len(rec["rendered_guideline_citations"]))
        for r in rec["rendered_guideline_citations"][:6]:
            print("      %s" % r[:110])
        print()

    json.dump(results, open("eval/reports/night9_item_b_syntheses.json", "w"),
              indent=1)
    print("  wrote eval/reports/night9_item_b_syntheses.json")
    bad = {k: v["served_pmid_slot_slugs"] for k, v in results.items()
           if v["served_pmid_slot_slugs"]}
    print("  VERDICT: %s" % ("PASS — no guideline id in a PMID slot on either"
                             " answer" if not bad else "FAIL %s" % bad))
    return 0


if __name__ == "__main__":
    sys.exit(main())
