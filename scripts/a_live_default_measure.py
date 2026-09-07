"""Item A (2026-09-09) — what live-by-default actually did.

Runs the REAL builder, `app.build_evidence_base_with_progress`, once per
question, so the numbers describe the product rather than a reconstruction of
it. Terms come from the item C cache, so two runs of this ask PubMed the same
questions (rule 38).

WHAT IS MEASURED
  route          expected LIVE 32/32 — verified, not assumed. "By construction"
                 is how the coverage gate came to be trusted for a year while
                 declaring coverage it did not have.
  pool size      before (the A55 measurement's library-route pool) -> after.
  missing-live   the A55 harness's fraction of the live set absent from the
                 library. Expected 0 now, because the live set IS the pool.
  latency/spend  wall clock per question, and the cost log's delta across it.

    python scripts/a_live_default_measure.py
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app  # noqa: E402
import endo_ai as E  # noqa: E402
import rag  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from measure_guideline_admission_rules import questions  # noqa: E402

A54_Q = "MTA versus bioceramic as retrograde filling after apicoectomy"
COST_LOG = ROOT / "cost_log.jsonl"


def cost_total():
    if not COST_LOG.exists():
        return 0.0
    tot = 0.0
    with COST_LOG.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                tot += float(json.loads(line).get("cost_usd") or 0)
            except Exception:
                pass
    return tot


def live_pmids(term, retmax=40):
    r = E.ncbi_get(f"{E.NCBI_EUTILS_BASE}/esearch.fcgi",
                   params=E._ncbi_params({
                       "db": "pubmed", "term": term, "retmode": "json",
                       "retmax": retmax, "sort": "relevance"}), timeout=25)
    return [str(i) for i in
            r.json().get("esearchresult", {}).get("idlist", [])]


def main():
    qs = questions()
    if not any(q == A54_Q for _i, q in qs):
        qs.append(("a54-retrograde", A54_Q))

    before = {}
    p = ROOT / "eval" / "reports" / "a55_false_coverage.json"
    if p.exists():
        for r in json.loads(p.read_text(encoding="utf-8"))["rows"]:
            before[r["id"]] = r

    print("=" * 78)
    print("ITEM A — LIVE BY DEFAULT, MEASURED ON THE REAL BUILDER")
    print("=" * 78)
    print("  questions: %d" % len(qs))
    print()

    rows = []
    for i, (qid, q) in enumerate(qs, 1):
        c0, t0 = cost_total(), time.time()
        try:
            ev = app.build_evidence_base_with_progress("measure-%d" % i, q)
        except Exception as ex:
            print("  %-30s FAILED: %s" % (qid[:30], ex))
            rows.append({"id": qid, "route": "ERROR", "error": str(ex)[:200]})
            continue
        dt, spend = time.time() - t0, cost_total() - c0
        summ = ev.get("_summary", {}) or {}
        pool = summ.get("all_scored", []) or []
        srcs = {}
        for pa in pool:
            srcs[pa.get("source") or "live"] = srcs.get(pa.get("source")
                                                        or "live", 0) + 1
        # missing-live: of what the live query returns, how much is absent from
        # the assembled pool. Zero is the claim; this is the check.
        term = E.generate_search_terms(q, mode="review")
        lp = live_pmids(term)
        have = {str(pa.get("pmid")) for pa in pool}
        missing = [x for x in lp if x not in have]
        b = before.get(qid, {})
        rows.append({"id": qid, "question": q, "route": "LIVE",
                     "pool_after": len(pool),
                     "pool_before": b.get("relevant"),
                     "route_before": b.get("route"),
                     "by_source": srcs, "seconds": round(dt, 1),
                     "spend_usd": round(spend, 5),
                     "live_returned": len(lp),
                     "missing_from_pool": len(missing),
                     "missing_frac": (round(len(missing) / len(lp), 3)
                                      if lp else None)})
        print("  %-30s pool %3s -> %-4d  %5.1fs  $%.4f  missing-live %d/%d"
              % (qid[:30], b.get("relevant", "?"), len(pool), dt, spend,
                 len(missing), len(lp)))

    ok = [r for r in rows if r["route"] == "LIVE"]
    print()
    print("  " + "-" * 70)
    print("  routed LIVE            : %d/%d" % (len(ok), len(rows)))
    secs = sorted(r["seconds"] for r in ok)
    if secs:
        print("  latency median / max   : %.1f s / %.1f s"
              % (secs[len(secs) // 2], secs[-1]))
        print("  spend median / total   : $%.4f / $%.2f"
              % (sorted(r["spend_usd"] for r in ok)[len(ok) // 2],
                 sum(r["spend_usd"] for r in ok)))
    grew = [r for r in ok if r.get("pool_before") is not None
            and r["pool_after"] > r["pool_before"]]
    print("  pools that grew        : %d of %d comparable"
          % (len(grew), sum(1 for r in ok if r.get("pool_before") is not None)))
    miss = [r for r in ok if (r["missing_from_pool"] or 0) > 0]
    print("  questions still missing live papers : %d" % len(miss))
    if miss:
        print("    (the claim was zero — these are the exceptions)")
        for r in miss[:8]:
            print("      %-30s %d/%d" % (r["id"][:30], r["missing_from_pool"],
                                         r["live_returned"]))

    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    json.dump({"rows": rows}, open("eval/reports/a_live_default.json", "w",
                                   encoding="utf-8"), indent=1)
    print("\n  wrote eval/reports/a_live_default.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
