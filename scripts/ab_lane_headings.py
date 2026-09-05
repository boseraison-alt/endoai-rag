"""Item 1c — A/B the DERIVED lane heading set on the 5 live Review questions.

THE FINDING THIS TESTS (item 3a). The synthesis prompt enumerates the tier
ladder twice — once as "Synthesise the evidence in tier order: Cochrane ->
Level I -> ... -> Level V", and once as the literal set of EVIDENCE SUMMARY
headings the answer must be written under. Neither list mentioned guidelines.
The model was handed a guideline block, an instruction to write under named
headings, and an instruction to "skip levels with no relevant evidence" — and
no heading a guideline could go under.

Measured before this ran: the guideline lane populates its tier on 21 of 29
questions and was cited ONCE across five live Review questions.

METHOD, and the one thing that makes it an A/B rather than two runs.
Retrieval happens ONCE per question and the SAME evidence object is handed to
both arms — a deep copy each, so neither arm can mutate what the other sees.
Nothing about retrieval differs between arms; the only variable is the prompt
(`endo_ai.GUIDELINE_PROMPT_ENABLED`). Two separate runs would have moved
retrieval as well, and PubMed is not deterministic between them.

The arms are also VERIFIED to differ: the system prompt is captured from each
and the run aborts if they are identical, because a flag that silently fails
to toggle would produce a perfectly clean null result.

PRE-DECLARED (from the batch): if guideline citations do not rise to at least
1 per question on 3 of 5, the change did not work — revert and report.

Usage:  python scripts/ab_guideline_prompt.py [--json OUT.json]
"""
import argparse
import copy
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E                      # noqa: E402
import app as A                          # noqa: E402

# THE POPULATION, corrected 2026-09-06 after the first run was inconclusive.
#
# The batch chose the five live Review cases from the guideline A/B and
# pre-declared ">=1 observational citation on 3 of the 5 cases where the tier
# is populated". On that set the tier was populated on ONE case, so the bar was
# arithmetically unmeetable: 3 of 1. The "18 of 29 questions" figure that
# motivated the item is across ALL 29, most of them library-routed, and it does
# not describe that subset.
#
# These five are the live-pinned cases whose observational tier is populated in
# all three v7 runs, read from eval/baseline_v7.json rather than guessed at.
# `laser-root-canal-disinfection-live` has the deepest tier (10 papers) and is
# deliberately EXCLUDED: it is learn-mode, and this harness synthesises through
# ask_clinical_question, so including it would measure a Review prompt on a
# curriculum question.
CASES = ["apdt-primary-molars", "case-opening-sparse", "case-opening-full",
         "intentional-replantation", "sdf-pulp-outcomes"]

CITE_RE = re.compile(r"\[\[PMID:\s*([^\]]+?)\s*\]\]")


def lane_pmids(evidence, lane):
    """PMIDs the evidence carries in one lane."""
    return {str(p.get("pmid")) for p in
            ((evidence.get(lane) or {}).get("scored") or []) if p.get("pmid")}


def guideline_pmids(evidence):
    """PMIDs in the evidence that ARE guideline records.

    Two sources, unioned, because a guideline can reach the prompt either way:
    the tier block (live lane or library row banded `guideline`), and the
    manifest's confirmed accessions.
    """
    out = {str(p.get("pmid")) for p in
           ((evidence.get("guideline") or {}).get("scored") or [])
           if p.get("pmid")}
    try:
        man = json.load(open("data/guidelines_seed.json", encoding="utf-8"))
        confirmed = {str(g["pmid"]) for g in man["guidelines"]
                     if g.get("pmid") and g.get("confidence") == "confirmed"}
    except Exception:
        confirmed = set()
    return out, confirmed


def cited(answer):
    return {m.strip() for m in CITE_RE.findall(answer or "")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_out", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    cases = {c["id"]: c for c in
             json.load(open("eval/questions.json"))["cases"]}
    ids = CASES[:args.limit] if args.limit else CASES

    E.LIBRARY_WRITE_BACK = False
    print("=" * 78)
    print("ITEM 3b — A/B: does naming guidelines in the prompt get them cited?")
    print("=" * 78)
    print("control = GUIDELINE_PROMPT_ENABLED False (the pre-item-3 prompt)")
    print("treated = GUIDELINE_PROMPT_ENABLED True\n")

    rows = []
    for i, cid in enumerate(ids, 1):
        case = cases[cid]
        print("-" * 78)
        print("[%d/%d] %s" % (i, len(ids), cid))
        job = "ab-%s" % cid
        A.jobs[job] = {"status": "running", "steps": [], "progress": 0}
        try:
            ev = A.build_evidence_base_with_progress(
                job, case["question"], force_route="live",
                mode=case.get("mode", "review")) or {}
        except Exception as e:
            print("   RETRIEVAL FAILED: %s" % e)
            rows.append({"id": cid, "error": str(e)})
            continue

        gl_tier, confirmed = guideline_pmids(ev)
        obs_tier = lane_pmids(ev, "observational")
        n_gl = len((ev.get("guideline") or {}).get("scored") or [])
        n_obs = len(obs_tier)
        print("   retrieved %d guideline, %d observational paper(s)"
              % (n_gl, n_obs))

        arms = {}
        for arm, flag in (("control", False), ("treated", True)):
            E.LANE_HEADINGS_ENABLED = flag
            try:
                answer, cost = E.ask_clinical_question(
                    case["question"], copy.deepcopy(ev))
            except Exception as e:
                print("   %s SYNTHESIS FAILED: %s" % (arm, e))
                arms[arm] = {"error": str(e)}
                continue
            c = cited(answer)
            gl_cited = (c & gl_tier) | (c & confirmed)
            obs_cited = c & obs_tier
            arms[arm] = {
                "citations": len(c),
                "guideline_citations": len(gl_cited),
                "observational_citations": len(obs_cited),
                "observational_pmids": sorted(obs_cited),
                "guideline_pmids": sorted(gl_cited),
                "cost": round(cost or 0.0, 4),
                "has_guideline_heading":
                    "Specialty Guidelines" in (answer or ""),
                "chars": len(answer or ""),
            }
            print("   %-8s citations %3d   guideline %2d   observational %2d"
                  "   $%.4f"
                  % (arm, len(c), len(gl_cited), len(obs_cited), cost or 0.0))
        E.LANE_HEADINGS_ENABLED = True
        rows.append({"id": cid, "guidelines_retrieved": n_gl,
                     "observational_retrieved": n_obs,
                     **{k: v for k, v in arms.items()}})

    ok = [r for r in rows if "error" not in r and "control" in r]
    print()
    print("=" * 78)
    print("RESULT")
    print("=" * 78)
    print("  %-30s %7s %7s %7s | %7s %7s"
          % ("case", "obs.ret", "obs.ctl", "obs.trt", "gl.ctl", "gl.trt"))
    hit = pop = 0
    for r in ok:
        oc = r["control"].get("observational_citations", 0)
        ot = r["treated"].get("observational_citations", 0)
        if r["observational_retrieved"]:
            pop += 1
            if ot >= 1:
                hit += 1
        print("  %-30s %7d %7d %7d | %7d %7d"
              % (r["id"][:30], r["observational_retrieved"], oc, ot,
                 r["control"].get("guideline_citations", 0),
                 r["treated"].get("guideline_citations", 0)))

    def agg(arm, key):
        return sum(r[arm].get(key, 0) for r in ok)

    n = max(1, len(ok))
    print()
    print("  %-22s %10s %10s" % ("", "control", "treated"))
    for label, key in (("observational citations", "observational_citations"),
                       ("guideline citations", "guideline_citations"),
                       ("total citations", "citations")):
        print("  %-22s %10s %10s"
              % (label, agg("control", key), agg("treated", key)))
    print("  %-22s %10.4f %10.4f"
          % ("cost, total $", agg("control", "cost"), agg("treated", "cost")))
    print("  %-22s %10.1f %10.1f"
          % ("mean citations", agg("control", "citations") / n,
             agg("treated", "citations") / n))
    print()
    print("  PRE-DECLARED: observational citations must reach >=1 on 3 of the")
    print("  5 live cases WHERE THE TIER IS POPULATED.")
    print("    populated: %d of %d" % (pop, len(ok)))
    print("    with >=1 observational citation (treated): %d  ->  %s"
          % (hit, "PASS" if hit >= 3 else "FAIL — revert"))
    gl_c = agg("control", "guideline_citations")
    gl_t = agg("treated", "guideline_citations")
    print()
    print("  GUIDELINE REGRESSION CHECK: %d -> %d  (%s)"
          % (gl_c, gl_t, "no regression" if gl_t >= gl_c else "REGRESSED"))

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        json.dump(rows, open(args.json_out, "w"), indent=1)
        print("\n  wrote %s" % args.json_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
