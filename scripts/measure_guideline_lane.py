"""Item 5 — how much volume does a guideline lane admit? Measure before adding.

`level_key='guideline'` ALREADY EXISTS as a tier: it is in LEVEL_SCORES at 12,
in TIER_ORDER between invitro and level5, and it has a label. What is missing
is a query filter that can reach one. `practice guideline[pt]`, `guideline[pt]`
and `consensus development conference[pt]` appear in no tier filter, so a
clinical practice guideline is reachable only by accident through level5's
review bucket -- PubMed's publication-type tree makes `review[pt]` admit
`Practice Guideline` -- where the EFCD-ESE-ORCA S3 guideline ranked 521 of 608.

This measures what a guideline lane would ADMIT per query before it is added,
because a lane that returns 400 papers is a different design from one that
returns 3.

Nothing is changed. Usage:
    python scripts/measure_guideline_lane.py [--limit N]
"""
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import requests                   # noqa: E402
import endo_ai as E               # noqa: E402

CANDIDATE = ("practice guideline[pt] OR guideline[pt] OR "
             "consensus development conference[pt]")


def esearch(term, retmax=100):
    url = f"{E.NCBI_EUTILS_BASE}/esearch.fcgi"
    p = E._ncbi_params({"db": "pubmed", "term": term, "retmax": retmax,
                        "retmode": "json", "sort": "relevance"})
    r = requests.get(url, params=p, timeout=45)
    r.raise_for_status()
    j = r.json().get("esearchresult", {})
    return j.get("idlist", []), int(j.get("count", 0))


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    cases = json.load(open("eval/questions.json", encoding="utf-8"))["cases"]
    if limit:
        cases = cases[:limit]

    print("=" * 78)
    print("ITEM 5 — VOLUME A GUIDELINE LANE WOULD ADMIT (measure only)")
    print("=" * 78)
    print("filter: %s\n" % CANDIDATE)

    counts, rows = [], []
    for n, c in enumerate(cases, 1):
        try:
            terms = E.generate_search_terms(c["question"])
        except Exception as e:
            print("  %2d. %-36s TERMS FAILED %s" % (n, c["id"][:36], e))
            continue
        seen = set()
        for t in terms[:4]:
            try:
                ids, _ = esearch("(%s) AND (%s)" % (t, CANDIDATE))
            except Exception as e:
                print("      esearch failed: %s" % str(e)[:50])
                continue
            seen.update(ids)
            time.sleep(0.35)
        counts.append(len(seen))
        rows.append({"id": c["id"], "n": len(seen), "pmids": sorted(seen)[:30]})
        print("  %2d. %-38s guidelines admitted = %d" % (n, c["id"][:38], len(seen)))

    if not counts:
        return 1
    s = sorted(counts)
    print()
    print("  n questions %d | min %d | median %d | max %d | mean %.1f | total %d"
          % (len(s), s[0], statistics.median(s), s[-1],
             statistics.fmean(s), sum(s)))
    print("  distribution: %s" % s)
    print()
    print("  A guideline lane is ADDITIVE: its own query, its own tier, its own")
    print("  quota. It takes no slot from any tier above it.")
    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    Path("eval/reports/a49_guideline_lane_volume.json").write_text(
        json.dumps({"filter": CANDIDATE, "distribution": s, "rows": rows},
                   indent=1), encoding="utf-8")
    print("  wrote eval/reports/a49_guideline_lane_volume.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
