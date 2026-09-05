"""Item 2 — what the broadened guideline topic does to the lane's empty rate.

MEASURE ONLY. The change is already in `endo_ai.fetch_papers`; this measures
it, and the pre-declared thresholds decide whether it stays.

WHAT IS COMPARED, AND WHY IT IS NOT A BEFORE/AFTER RUN. Two full 29-question
runs a few minutes apart would move two things at once: the query AND whatever
PubMed returned that minute. Instead each question's generated terms are
produced ONCE and both queries — the full conjunction the lane used to send,
and the subject group it sends now — are issued against the same terms, back to
back. The only difference is the topic half of the query.

That also makes it cheap: one esearch per arm per term, no efetch, no scoring.

PRE-DECLARED (from the batch): the lane's empty rate must fall below 50% and
the change must add under 10 s per question, or report and do not ship.

Usage:  python scripts/measure_guideline_lane_query.py [--json OUT.json]
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E                      # noqa: E402

GUIDELINE_FILTER = None                  # taken from tier_query_lanes below


def lane_filter():
    for key, terms, _label in E.tier_query_lanes():
        if key == "guideline":
            return " OR ".join(terms)
    raise SystemExit("no guideline lane in tier_query_lanes()")


def esearch_count(topic, filt):
    term = (f"({topic}) AND ({filt}) AND {E.ENDO_DOMAIN_FILTER} "
            f'NOT "Retracted Publication"[pt]')
    t0 = time.time()
    try:
        r = E.ncbi_get(f"{E.NCBI_EUTILS_BASE}/esearch.fcgi",
                       params=E._ncbi_params({"db": "pubmed", "term": term,
                                              "retmode": "json",
                                              "retmax": 50}), timeout=20)
        n = int(r.json().get("esearchresult", {}).get("count", 0))
    except Exception as ex:
        print("      esearch failed: %s" % ex)
        n = -1
    return n, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_out", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    cases = json.load(open("eval/questions.json"))["cases"]
    if args.limit:
        cases = cases[:args.limit]
    filt = lane_filter()

    print("=" * 78)
    print("ITEM 2 — GUIDELINE LANE TOPIC: full conjunction vs subject group")
    print("=" * 78)
    print("same generated terms for both arms; only the topic half differs\n")

    rows = []
    for i, case in enumerate(cases, 1):
        cid = case["id"]
        try:
            smart = E.generate_search_terms(case["question"])
        except Exception as ex:
            print("[%2d/%d] %-38s TERMS FAILED: %s" % (i, len(cases), cid, ex))
            continue
        broad = E.guideline_topic(smart)
        n_old, t_old = esearch_count(smart, filt)
        n_new, t_new = esearch_count(broad, filt)
        rows.append({"id": cid, "old_hits": n_old, "new_hits": n_new,
                     "old_s": round(t_old, 2), "new_s": round(t_new, 2),
                     "broadened": broad != smart})
        print("[%2d/%d] %-38s old %5s -> new %5s   %s"
              % (i, len(cases), cid[:38], n_old, n_new,
                 "" if broad != smart else "(no boolean structure — unchanged)"))

    ok = [r for r in rows if r["old_hits"] >= 0 and r["new_hits"] >= 0]
    n = max(1, len(ok))
    old_empty = len([r for r in ok if r["old_hits"] == 0])
    new_empty = len([r for r in ok if r["new_hits"] == 0])
    print()
    print("=" * 78)
    print("RESULT")
    print("=" * 78)
    print("  questions measured                %d" % len(ok))
    print("  lane EMPTY, full conjunction      %d  (%.0f%%)"
          % (old_empty, 100.0 * old_empty / n))
    print("  lane EMPTY, subject group         %d  (%.0f%%)"
          % (new_empty, 100.0 * new_empty / n))
    print("  questions gaining a guideline     %d"
          % len([r for r in ok if r["old_hits"] == 0 and r["new_hits"] > 0]))
    print("  questions LOSING one              %d"
          % len([r for r in ok if r["old_hits"] > 0 and r["new_hits"] == 0]))
    print()
    print("  mean esearch latency  old %.2fs   new %.2fs   delta %+.2fs"
          % (sum(r["old_s"] for r in ok) / n, sum(r["new_s"] for r in ok) / n,
             (sum(r["new_s"] for r in ok) - sum(r["old_s"] for r in ok)) / n))
    print()
    print("  PRE-DECLARED: empty rate below 50%, added latency under 10 s.")
    rate = 100.0 * new_empty / n
    lat = (sum(r["new_s"] for r in ok) - sum(r["old_s"] for r in ok)) / n
    print("    empty rate  %.0f%%  ->  %s" % (rate, "PASS" if rate < 50 else "FAIL"))
    print("    added latency %+.2fs  ->  %s" % (lat, "PASS" if lat < 10 else "FAIL"))
    print("    VERDICT: %s" % ("SHIP" if rate < 50 and lat < 10
                               else "REPORT, DO NOT SHIP"))

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        json.dump(rows, open(args.json_out, "w"), indent=1)
        print("\n  wrote %s" % args.json_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
