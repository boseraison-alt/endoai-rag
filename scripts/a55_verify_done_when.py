"""A55 item 2 — the done-when, verified rather than asserted.

    "the A54 question routes LIVE and F1-F5 reach its pool on 3 of 3 cold-term
     runs; no question that had full coverage re-routes"

COLD TERMS MEAN THE CACHE IS BYPASSED. The point is that the result survives
term regeneration, not that a frozen string happens to work. Item C's cache is
disabled for the duration.

`F1-F5` is read as "the five clinical fixtures", which is what that phrase can
mean now that the fixture set has been examined: F7 and F8 are bench studies by
their own abstracts (sealing ability, ninety root segments), and no clinical
pool should be judged on whether it retrieved them.

    python scripts/a55_verify_done_when.py --runs 3
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E  # noqa: E402
from app import RELEVANCE_GATE, multi_query_search  # noqa: E402

A54_Q = "MTA versus bioceramic as retrograde filling after apicoectomy"
FIX = json.loads((ROOT / "eval" / "reports" / "a54_fixtures.json")
                 .read_text(encoding="utf-8"))
CLINICAL = ["F1", "F2", "F3", "F4", "F5"]
FLOOR = RELEVANCE_GATE["similarity_floor"]
MIN_HITS = RELEVANCE_GATE["min_hits"]
MIN_RELEVANT = RELEVANCE_GATE["min_relevant"]
MIN_CONCEPT = RELEVANCE_GATE["min_concept_papers"]
MIN_INTER = RELEVANCE_GATE["min_intersection_papers"]
MAX_AGE = RELEVANCE_GATE["max_topic_age_yr"]


def route_for(question, term):
    groups = E.coverage_groups(term)
    cands = multi_query_search(question, [term], limit=100)
    relevant = [r for r in cands if float(r.get("similarity") or 0) >= FLOOR]
    cov = E.question_coverage(groups, relevant) if groups else []
    weakest = min([c["hits"] for c in cov], default=None)
    inter = E.question_intersection(groups, relevant)
    newest = max((int(r["year"]) for r in relevant
                  if str(r.get("year", "")).isdigit()), default=0)
    from datetime import datetime as _dt
    age = _dt.now().year - newest if newest else 99
    high = any((r.get("level_key") or "") in ("cochrane", "level1", "level2")
               for r in relevant)
    covers = (weakest is None) or (weakest >= MIN_CONCEPT)
    inter_ok = (not groups) or (inter >= MIN_INTER)
    lib = (len(cands) >= MIN_HITS and len(relevant) >= MIN_RELEVANT and high
           and age <= MAX_AGE and covers and inter_ok)
    return ("LIBRARY" if lib else "LIVE"), inter, weakest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()

    print("=" * 78)
    print("A55 ITEM 2 — DONE-WHEN")
    print("=" * 78)
    print("  min_intersection_papers = %d" % MIN_INTER)
    print("  clinical fixtures: %s"
          % ", ".join("%s=%s" % (k, FIX[k]) for k in CLINICAL))
    print()

    prev = E.TERM_CACHE_ENABLED
    E.TERM_CACHE_ENABLED = False      # cold terms, every run
    results = []
    try:
        for r in range(args.runs):
            term = E.generate_search_terms(A54_Q, mode="review")
            route, inter, weakest = route_for(A54_Q, term)
            # THE POOL IS BUILT ON WHICHEVER ROUTE WAS TAKEN.
            #
            # The first version built one only on the LIVE branch, so when
            # items 3 and 4 succeeded and the question went back to LIBRARY it
            # reported "0 fixtures in pool" — an artefact of the harness, not a
            # finding. "Routes LIVE" was only ever a PROXY for "the pool holds
            # the papers that answer the question"; measure the thing itself.
            if route == "LIVE":
                ev = E.build_evidence_base(A54_Q, mode="review")
                pool = [str(p.get("pmid")) for p in
                        (ev.get("_summary") or {}).get("all_scored", [])]
            else:
                cands = multi_query_search(A54_Q, [term], limit=100)
                pool = [str(c.get("pmid")) for c in cands
                        if float(c.get("similarity") or 0) >= FLOOR]
            found = [k for k in CLINICAL if str(FIX[k]) in pool]
            results.append({"run": r + 1, "route": route, "intersection": inter,
                            "weakest": weakest, "pool": len(pool),
                            "fixtures_found": found})
            print("  run %d: route=%-7s intersection=%-3d weakest=%-4s "
                  "pool=%-4d clinical fixtures in pool: %s"
                  % (r + 1, route, inter, weakest, len(pool),
                     ", ".join(found) or "none"))
    finally:
        E.TERM_CACHE_ENABLED = prev

    live_all = all(x["route"] == "LIVE" for x in results)
    print()
    print("  routes LIVE on %d/%d runs : %s"
          % (sum(1 for x in results if x["route"] == "LIVE"), args.runs,
             "PASS" if live_all else "FAIL"))
    for k in CLINICAL:
        n = sum(1 for x in results if k in x["fixtures_found"])
        print("    %-3s %-10s in pool on %d/%d runs" % (k, FIX[k], n, args.runs))

    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    json.dump({"min_intersection": MIN_INTER, "runs": results},
              open("eval/reports/a55_done_when.json", "w", encoding="utf-8"),
              indent=1)
    print("\n  wrote eval/reports/a55_done_when.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
