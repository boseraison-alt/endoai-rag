"""Item 4b — pool size, latency and cost, with the provisional lane off and on.

An A/B on the SAME code. The lane is disabled in the "before" arm by stubbing
`fetch_untyped_recent` to return nothing, so the two arms differ in exactly
one thing. Comparing against a stored answer instead would confound this with
the A2 quarantine, the impact-factor removal and the guideline seed, all of
which landed in the same branch.

Both arms are still n=1 against a stochastic generator. Pool size and latency
are deterministic enough to read directly; a citation-count difference of one
or two is noise and is reported as such.

Usage:
  python scripts/measure_provisional_lane.py --mode review
  python scripts/measure_provisional_lane.py --mode learn
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E                # noqa: E402

OUT = ROOT / "eval" / "reports" / "a49_provisional_lane"
PMID_RE = re.compile(r"\[\[PMID:\s*([A-Za-z0-9\-]+)\s*\]\]")

QUESTIONS = {
    "review": "Single-visit versus multiple-visit root canal treatment for "
              "necrotic teeth with apical periodontitis",
    "learn":  "vital pulp therapy in adult teeth",
}

_REAL_FETCH = E.fetch_untyped_recent


def run_arm(mode, question, lane_on):
    if lane_on:
        E.fetch_untyped_recent = _REAL_FETCH
    else:
        E.fetch_untyped_recent = lambda *a, **kw: ("", [], [])

    t0 = time.perf_counter()
    if mode == "learn":
        text, cost, evidence = E.build_deep_learning_module(
            question, progress_cb=lambda p, m: None)
    else:
        evidence = E.build_evidence_base(question, mode="review")
        text, cost = E.ask_clinical_question(question, evidence)
    elapsed = time.perf_counter() - t0

    out = E.finalise_answer_text(text)
    served = out[0] if isinstance(out, tuple) else out

    prov = (evidence or {}).get(E.PROVISIONAL_KEY, {}) or {}
    prov_papers = prov.get("scored") or []
    summary = (evidence or {}).get("_summary", {}) or {}
    tiered = summary.get("all_scored") or []
    cites = PMID_RE.findall(served or "")
    prov_ids = {p["pmid"] for p in prov_papers}

    return {
        "lane": "on" if lane_on else "off",
        "elapsed_s": round(elapsed, 1),
        "cost_usd": round(float(cost or 0), 4),
        "tiered_pool": len(tiered),
        "provisional_pool": len(prov_papers),
        "total_pool": len(tiered) + len(prov_papers),
        "citation_markers": len(cites),
        "distinct_cited": sorted(set(cites)),
        "n_distinct_cited": len(set(cites)),
        "provisional_cited": sorted(set(cites) & prov_ids),
        "provisional_designs": [
            {"pmid": p["pmid"], "year": p.get("year"),
             "design": p.get("stated_design")} for p in prov_papers],
        "answer_chars": len(served or ""),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["review", "learn"], required=True)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    q = QUESTIONS[args.mode]

    print("=" * 78)
    print("ITEM 4b — PROVISIONAL LANE A/B  (mode=%s)" % args.mode)
    print("=" * 78)
    print("question: %s\n" % q)

    arms = {}
    for lane_on in (False, True):
        print("\n--- ARM: lane %s ---" % ("ON" if lane_on else "OFF"))
        try:
            arms["on" if lane_on else "off"] = run_arm(args.mode, q, lane_on)
        finally:
            E.fetch_untyped_recent = _REAL_FETCH

    a, b = arms["off"], arms["on"]
    print()
    print("=" * 78)
    print("  %-24s %12s %12s %10s" % ("", "lane OFF", "lane ON", "delta"))
    for k, fmt in (("tiered_pool", "%d"), ("provisional_pool", "%d"),
                   ("total_pool", "%d"), ("citation_markers", "%d"),
                   ("n_distinct_cited", "%d"), ("answer_chars", "%d")):
        print("  %-24s %12s %12s %10s"
              % (k, fmt % a[k], fmt % b[k], "%+d" % (b[k] - a[k])))
    print("  %-24s %12.1f %12.1f %+10.1f"
          % ("elapsed_s", a["elapsed_s"], b["elapsed_s"],
             b["elapsed_s"] - a["elapsed_s"]))
    print("  %-24s %12.4f %12.4f %+10.4f"
          % ("cost_usd", a["cost_usd"], b["cost_usd"],
             b["cost_usd"] - a["cost_usd"]))
    print()
    print("  provisional papers admitted : %d" % b["provisional_pool"])
    for d in b["provisional_designs"][:12]:
        print("      %-10s %-6s %s" % (d["pmid"], d["year"], d["design"]))
    print("  provisional papers CITED    : %s"
          % (", ".join(b["provisional_cited"]) or "none"))
    print()
    print("  Rule 32 — the lane finding nothing, or finding papers the answer")
    print("  does not use, is a legitimate outcome and is reported as one.")

    (OUT / ("%s.json" % args.mode)).write_text(
        json.dumps({"question": q, "arms": arms}, indent=1), encoding="utf-8")
    print("\nwrote %s" % (OUT / ("%s.json" % args.mode)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
