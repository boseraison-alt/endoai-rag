"""A55 item 4 — procedure synonyms in term generation, before and after.

A54 SHOWED THE SURGERY GROUP WAS THE POINT OF FAILURE, not the material group:
`"endodontic microsurgery"` alone recovers F1, F2, F4 and F7. The generated
surgery group was `(apicoectomy OR "apical surgery" OR "surgical endodontic*"
OR "periapical surgery")` — four names for the procedure, missing the four the
recent literature actually titles its papers with.

RULE 38 GOVERNS HOW THIS IS COMPARED. This is a QUERY-CONSTRUCTION change, so
it compares query STRINGS, where the noise floor is now zero (item C took the
generator from 0/10 to 10/10 reproducible). Comparing POOLS instead would put
the effect underneath a 26% same-build noise floor and measure nothing.

The batch's threshold: below 90% unchanged groups it is a retrieval change and
needs the full A/B with frozen terms.

    python scripts/a55_procedure_synonyms_ab.py --tag before
    python scripts/a55_procedure_synonyms_ab.py --tag after
    python scripts/a55_procedure_synonyms_ab.py --compare
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

sys.path.insert(0, str(ROOT / "scripts"))
from measure_guideline_admission_rules import questions  # noqa: E402
from measure_term_variance import groups as split_groups  # noqa: E402

OUT = ROOT / "eval" / "reports"
A54_Q = "MTA versus bioceramic as retrograde filling after apicoectomy"

# The eight the item names, used ONLY to score the A54 question's surgery group.
# They are not added to any prompt as a list — the prompt sentence is general.
APICAL_SYNONYMS = ["apicoectomy", "apicectomy", "root-end resection",
                   "root-end filling", "retrograde filling",
                   "periradicular surgery", "endodontic microsurgery",
                   "apical microsurgery"]


def capture(tag):
    qs = questions()
    if not any(q == A54_Q for _i, q in qs):
        qs.append(("a54-retrograde", A54_Q))
    prev = E.TERM_CACHE_ENABLED
    E.TERM_CACHE_ENABLED = False        # measure the GENERATOR, not the cache
    out = {}
    try:
        for qid, q in qs:
            t = E.generate_search_terms(q, mode="review")
            out[qid] = {"question": q, "terms": t,
                        "groups": sorted(split_groups(t))}
            print("  %-30s %s" % (qid[:30], " ".join(t.split())[:88]))
    finally:
        E.TERM_CACHE_ENABLED = prev
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / ("a55_terms_%s.json" % tag)
    json.dump(out, open(p, "w", encoding="utf-8"), indent=1)
    print("\n  wrote %s" % p)
    return out


def synonyms_in(terms):
    t = (terms or "").lower()
    return [s for s in APICAL_SYNONYMS if s in t]


def compare():
    before = json.load(open(OUT / "a55_terms_before.json", encoding="utf-8"))
    after = json.load(open(OUT / "a55_terms_after.json", encoding="utf-8"))
    ids = [k for k in before if k in after]
    same = [k for k in ids if before[k]["groups"] == after[k]["groups"]]
    print("=" * 78)
    print("A55 ITEM 4 — QUERY STRINGS, BEFORE vs AFTER  (rule 38)")
    print("=" * 78)
    print("  questions compared : %d" % len(ids))
    print("  UNCHANGED groups   : %d  (%.0f%%)"
          % (len(same), 100.0 * len(same) / max(len(ids), 1)))
    print("  changed            : %d" % (len(ids) - len(same)))
    print()
    print("  Rule 38 threshold: below 90%% unchanged this is a RETRIEVAL")
    print("  change and needs the full A/B with frozen terms.")
    verdict = ("retrieval change — full A/B required"
               if 100.0 * len(same) / max(len(ids), 1) < 90 else
               "not a retrieval change")
    print("  VERDICT: %s" % verdict)
    print()
    b = synonyms_in(before.get("a54-retrograde", {}).get("terms", ""))
    a = synonyms_in(after.get("a54-retrograde", {}).get("terms", ""))
    print("  A54 QUESTION — procedure synonyms present")
    print("    before: %d/8  %s" % (len(b), b))
    print("    after : %d/8  %s" % (len(a), a))
    print("    pin is >= 3 after: %s" % ("PASS" if len(a) >= 3 else "FAIL"))
    print()
    print("  CHANGED QUESTIONS")
    for k in ids:
        if before[k]["groups"] != after[k]["groups"]:
            print("    %s" % k)
    json.dump({"compared": len(ids), "unchanged": len(same),
               "verdict": verdict, "a54_before": b, "a54_after": a},
              open(OUT / "a55_item4_ab.json", "w", encoding="utf-8"), indent=1)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default=None)
    ap.add_argument("--compare", action="store_true")
    args = ap.parse_args()
    if args.compare:
        return compare()
    if not args.tag:
        print("give --tag before|after, or --compare")
        return 2
    capture(args.tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
