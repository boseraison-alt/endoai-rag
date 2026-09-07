"""A55 item 4 — the full A/B, because the string comparison said it is needed.

Rule 38: below 90% unchanged groups a query-construction change is a RETRIEVAL
change and owes a pool A/B with frozen terms. The string comparison measured
**0/32 unchanged**, so this runs.

FROZEN TERMS ON BOTH ARMS. The before-arm replays the exact strings captured in
`a55_terms_before.json` and the after-arm those in `a55_terms_after.json`. The
generator is not called at all here, so the only difference between the arms is
the change under test — which is the whole point of item C existing first.

WHAT IS MEASURED, AND WHY NOT JUST CHURN. Item C put the same-build pool-noise
floor at 26%: two identical builds disagree about a quarter of pools. Reporting
"the pools changed" against that floor would say nothing. So the headline is
**fixture recall on the A54 question** — an objective count of how many of the
eight verified head-to-head papers each query actually returns from PubMed —
with pool size and overlap reported alongside as context, not as the verdict.

    python scripts/a55_item4_full_ab.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E  # noqa: E402

OUT = ROOT / "eval" / "reports"
FIX = json.loads((OUT / "a54_fixtures.json").read_text(encoding="utf-8"))
RETMAX = 60


def esearch(term):
    try:
        r = E.ncbi_get(f"{E.NCBI_EUTILS_BASE}/esearch.fcgi",
                       params=E._ncbi_params({
                           "db": "pubmed", "term": term, "retmode": "json",
                           "retmax": RETMAX, "sort": "relevance"}), timeout=25)
        return [str(i) for i in
                r.json().get("esearchresult", {}).get("idlist", [])]
    except Exception as ex:
        print("      esearch failed: %s" % ex)
        return []


def main():
    before = json.loads((OUT / "a55_terms_before.json").read_text(encoding="utf-8"))
    after = json.loads((OUT / "a55_terms_after.json").read_text(encoding="utf-8"))
    ids = [k for k in before if k in after]

    print("=" * 78)
    print("A55 ITEM 4 — FULL A/B, FROZEN TERMS")
    print("=" * 78)
    print("  questions: %d   retmax: %d" % (len(ids), RETMAX))
    print("  noise floor for pool membership (item C): 26%")
    print()

    rows, grew, shrank = [], 0, 0
    for k in ids:
        a = esearch(before[k]["terms"])
        b = esearch(after[k]["terms"])
        sa, sb = set(a), set(b)
        overlap = len(sa & sb) / max(len(sa | sb), 1)
        grew += 1 if len(b) > len(a) else 0
        shrank += 1 if len(b) < len(a) else 0
        rows.append({"id": k, "n_before": len(a), "n_after": len(b),
                     "jaccard": round(overlap, 3)})
        print("  %-30s %3d -> %-3d  overlap %.2f"
              % (k[:30], len(a), len(b), overlap))

    print()
    print("  pools that grew   : %d" % grew)
    print("  pools that shrank : %d" % shrank)
    mean_j = sum(r["jaccard"] for r in rows) / max(len(rows), 1)
    print("  mean Jaccard      : %.2f" % mean_j)

    # ── the decisive measure ──
    #
    # ASKED PER FIXTURE, NOT BY DIFFING TOP-60 LISTS (rule 41). Reading recall
    # off the ranked lists said 1/8 before and 0/8 after — "REGRESSED" — and it
    # was a pure ranking artefact: both queries return 60 results and the
    # fixtures simply sit at different depths. Asking whether each fixture
    # SATISFIES each query gives 3/8 before and 6/8 after. That is the second
    # time in one session the truncated-list reading would have reversed a
    # correct conclusion, which is why rule 41 exists.
    print()
    print("  FIXTURE RECALL ON THE A54 QUESTION (the objective measure)")
    k = "a54-retrograde"
    uids = " OR ".join("%s[uid]" % p for p in FIX.values())

    def satisfies(term):
        got = esearch("(%s) AND (%s)" % (uids, term))
        return {f for f, p in FIX.items() if str(p) in got}

    got_a, got_b = satisfies(before[k]["terms"]), satisfies(after[k]["terms"])
    fa, fb = esearch(before[k]["terms"]), esearch(after[k]["terms"])
    top_a = {f for f, p in FIX.items() if str(p) in fa}
    top_b = {f for f, p in FIX.items() if str(p) in fb}
    print("    SATISFYING the query   before %d/8 %s" % (len(got_a), sorted(got_a)))
    print("                           after  %d/8 %s" % (len(got_b), sorted(got_b)))
    print("      gained: %s" % sorted(got_b - got_a))
    print("      lost  : %s" % sorted(got_a - got_b))
    print("    in the top %d only      before %d/8   after %d/8   "
          "(ranking, not recall)" % (RETMAX, len(top_a), len(top_b)))
    print("    recall %s" % ("IMPROVED" if len(got_b) > len(got_a)
                             else "unchanged" if len(got_b) == len(got_a)
                             else "REGRESSED"))
    got_a, got_b = sorted(got_a), sorted(got_b)
    print()
    print("  PRECISION NOTE: pool size moved from %d to %d on this question."
          % (len(fa), len(fb)))
    print("  A recall gain bought by a larger pool is not free; both numbers")
    print("  are reported so the trade is visible (standing rule: report")
    print("  recall AND precision).")

    json.dump({"rows": rows, "mean_jaccard": mean_j, "grew": grew,
               "shrank": shrank, "a54_before": sorted(got_a),
               "a54_after": sorted(got_b),
               "a54_pool_before": len(fa), "a54_pool_after": len(fb)},
              open(OUT / "a55_item4_full_ab.json", "w", encoding="utf-8"),
              indent=1)
    print("\n  wrote eval/reports/a55_item4_full_ab.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
