"""Item 1a — what would a per-tier QUALITY floor cost the library route?

MEASURE ONLY. Nothing is changed by this script and no fix is applied.

`scripts/measure_library_route_floor.py` measured the defect against the whole
library: 516 of 3,346 rows sit below their own tier's floor. That is the
corpus-side number. This is the QUESTION-side number, which is the one that
decides whether the fix is shippable: for each of the 29 eval questions, forced
onto the library route, how many papers does the floor remove, from which
tiers, and does the surviving count fall under `min_evidence_papers` 40.

WHY 40 MATTERS AND WHY THE RESCUE CANNOT SAVE IT. `apply_evidence_floor`'s
rescue branch runs on the SIMILARITY axis, before banding, and tops the pool up
to 40 most-similar rows. A quality floor applied after banding cuts from that
already-rescued pool, and nothing tops it back up. The two guards are on
different axes and the second one has no floor of its own. That is the
interaction the pre-declared threshold is about.

HOW THE "AFTER" IS COMPUTED, and why it is not a re-implementation. The
library branch's banding is ~15 lines inside a 550-line function, and copying
it here is exactly the instrument error this project keeps making (rules 33,
34). Instead `cap_by_relevance` is wrapped for the duration of the run so
production hands us the REAL pre-cap bucket for every tier, and the "after"
figure is then computed with production's own `_tier_floor`, `_tier_cap` and
`cap_by_relevance`. The "before" figure is production's own returned evidence
base, untouched.

The wrapper is verified, not trusted: for every question the recorded
before-counts are compared against the evidence base the function actually
returned, and any disagreement is printed as WRAPPER MISMATCH.

NULL-SCORE EXEMPTION. 48 guideline rows store `score` NULL by design and
`rag_results_to_scored` coalesces that to 0.0. A floor that reads the coalesced
0.0 deletes every guideline. This script measures BOTH ways so the size of that
trap is a number rather than a warning:
    strict    — floor applied to the coalesced score (the naive fix)
    exempt    — NULL-score rows are never cut by the floor (the proposed fix)

Usage:  python scripts/measure_library_floor_29.py [--json OUT.json]
"""
import argparse
import collections
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E                      # noqa: E402
import app as A                          # noqa: E402


def null_scored(paper, null_pmids):
    """Did this row store score NULL before rag_results_to_scored coalesced it?

    Read from the set of NULL-score PMIDs collected straight from the table, so
    the measurement does not depend on the fix's own flag existing yet.
    """
    return paper.get("pmid") in null_pmids


def load_null_score_pmids():
    import psycopg2
    from rag import DATABASE_URL
    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute("SELECT pmid FROM endo_papers_rag WHERE score IS NULL")
        out = {r[0] for r in cur.fetchall()}
    conn.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_out", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    cases = json.load(open("eval/questions.json"))["cases"]
    if args.limit:
        cases = cases[:args.limit]

    null_pmids = load_null_score_pmids()
    print("=" * 78)
    print("ITEM 1a — PER-TIER QUALITY FLOOR ON THE LIBRARY ROUTE, 29 QUESTIONS")
    print("=" * 78)
    print("measure only; nothing changed")
    print("%d rows in the library store score NULL\n" % len(null_pmids))

    E.LIBRARY_WRITE_BACK = False

    # ── the recording wrapper ──
    recorded = {}
    real_cap = A.cap_by_relevance

    def recording_cap(bucket, cap, tier=""):
        recorded.setdefault(tier, []).append(list(bucket))
        return real_cap(bucket, cap, tier)

    results = []
    A.cap_by_relevance = recording_cap
    try:
        for i, case in enumerate(cases, 1):
            qid = case["id"]
            mode = case.get("mode", "review")
            recorded.clear()
            job_id = "floor29-%s" % qid
            A.jobs[job_id] = {"status": "running", "steps": [], "progress": 0}
            exchanges = (case.get("context") or {}).get("exchanges") or []
            ctx = E.build_context_block(exchanges) if exchanges else ""
            prior = E.context_prior_pmids(exchanges) if exchanges else None
            print("-" * 78)
            print("[%2d/%d] %-38s mode=%-6s" % (i, len(cases), qid, mode))
            try:
                ev = A.build_evidence_base_with_progress(
                    job_id, case["question"], force_route="library",
                    mode=mode, context_block=ctx, prior_pmids=prior) or {}
            except Exception as e:
                print("   RETRIEVAL FAILED: %s" % e)
                results.append({"id": qid, "mode": mode, "error": str(e)})
                continue

            before_tiers, after_strict_tiers, after_exempt_tiers = {}, {}, {}
            cap_only, floor_only = {}, {}
            removed_by_tier, removed_guideline = {}, 0
            mismatch = []

            for tier in E.TIER_ORDER:
                block = ev.get(tier) or {}
                served = block.get("scored") or []
                if served:
                    before_tiers[tier] = len(served)
                buckets = recorded.get(tier) or []
                if not buckets:
                    if served:
                        mismatch.append("%s: served %d, wrapper never called"
                                        % (tier, len(served)))
                    continue
                pre = buckets[-1]
                # verify the wrapper saw what production served
                check = real_cap(pre, A.RELEVANCE_GATE["max_per_tier"], tier)
                if len(check) != len(served):
                    mismatch.append("%s: wrapper %d, served %d"
                                    % (tier, len(check), len(served)))

                floor = E._tier_floor(tier)
                cap = E._tier_cap(mode, tier)
                strict = [p for p in pre if float(p.get("score") or 0) >= floor]
                exempt = [p for p in pre
                          if null_scored(p, null_pmids)
                          or float(p.get("score") or 0) >= floor]
                s_kept = real_cap(strict, cap, tier)
                e_kept = real_cap(exempt, cap, tier)
                if s_kept:
                    after_strict_tiers[tier] = len(s_kept)
                if e_kept:
                    after_exempt_tiers[tier] = len(e_kept)
                # Rule 22 — the fix changes TWO things, and a single
                # before/after cannot say which did the cutting. Isolate them:
                #   cap_only    the MODE_TIER_QUOTAS cap, floor never applied
                #   floor_only  the floor, still under the flat 25
                cap_only[tier] = len(real_cap(pre, cap, tier))
                floor_only[tier] = len(
                    real_cap(exempt, A.RELEVANCE_GATE["max_per_tier"], tier))
                cut = len(served) - len(e_kept)
                if cut:
                    removed_by_tier[tier] = cut
                if tier == "guideline":
                    removed_guideline = len(served) - len(s_kept)

            n_before = sum(before_tiers.values())
            n_strict = sum(after_strict_tiers.values())
            n_exempt = sum(after_exempt_tiers.values())
            row = {
                "id": qid, "mode": mode,
                "before": n_before, "after_strict": n_strict,
                "after_exempt": n_exempt,
                "cap_only": sum(cap_only.values()),
                "floor_only": sum(floor_only.values()),
                "before_tiers": before_tiers,
                "after_exempt_tiers": after_exempt_tiers,
                "removed_by_tier": removed_by_tier,
                "guideline_before": before_tiers.get("guideline", 0),
                "guideline_lost_strict": removed_guideline,
                "below_40_before": n_before < 40,
                "below_40_after": n_exempt < 40,
                "route": (ev.get("_summary") or {}).get("route", ""),
                "mismatch": mismatch,
            }
            results.append(row)
            print("   before %3d   cap-only %3d   floor-only %3d   both %3d   %s"
                  % (n_before, sum(cap_only.values()),
                     sum(floor_only.values()), n_exempt,
                     "BELOW 40" if n_exempt < 40 else ""))
            if removed_by_tier:
                print("   removed: %s" % ", ".join(
                    "%s -%d" % (t, n) for t, n in sorted(removed_by_tier.items())))
            if mismatch:
                print("   WRAPPER MISMATCH: %s" % "; ".join(mismatch))
    finally:
        A.cap_by_relevance = real_cap

    ok = [r for r in results if "error" not in r]
    print()
    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print("  %-34s %6s %6s %6s %6s %6s %4s"
          % ("question", "before", "cap", "floor", "both", "strict", "<40"))
    for r in ok:
        print("  %-34s %6d %6d %6d %6d %6d %4s"
              % (r["id"][:34], r["before"], r["cap_only"], r["floor_only"],
                 r["after_exempt"], r["after_strict"],
                 "YES" if r["below_40_after"] else ""))

    below = [r for r in ok if r["below_40_after"]]
    below_before = [r for r in ok if r["below_40_before"]]
    tot_removed = collections.Counter()
    for r in ok:
        tot_removed.update(r["removed_by_tier"])

    print()
    print("  questions measured                 %d" % len(ok))
    print("  papers before, total               %d" % sum(r["before"] for r in ok))
    print("  papers after (NULL-exempt), total  %d" % sum(r["after_exempt"] for r in ok))
    print("  papers after (strict), total       %d" % sum(r["after_strict"] for r in ok))
    print()
    print("  ATTRIBUTION (rule 22) — which of the two changes does the cutting:")
    print("    cap alone  (MODE_TIER_QUOTAS, no floor)  %d"
          % sum(r["cap_only"] for r in ok))
    print("    floor alone (flat 25 cap kept)           %d"
          % sum(r["floor_only"] for r in ok))
    n_cap_below = len([r for r in ok if r["cap_only"] < 40])
    n_fl_below = len([r for r in ok if r["floor_only"] < 40])
    print("    below 40 under cap alone   %d" % n_cap_below)
    print("    below 40 under floor alone %d" % n_fl_below)
    print()
    print("  PRE-DECLARED THRESHOLD: stop if more than 5 of 29 fall below 40")
    print("  below 40 BEFORE the floor          %d  (%s)"
          % (len(below_before), ", ".join(r["id"] for r in below_before) or "none"))
    print("  below 40 AFTER  the floor          %d  (%s)"
          % (len(below), ", ".join(r["id"] for r in below) or "none"))
    newly = [r for r in below if not r["below_40_before"]]
    print("  NEWLY below 40 (caused by floor)   %d  (%s)"
          % (len(newly), ", ".join(r["id"] for r in newly) or "none"))
    print()
    print("  removed by tier, all questions:")
    for t, n in sorted(tot_removed.items(), key=lambda kv: -kv[1]):
        print("     %-14s %5d" % (t, n))
    g_lost = sum(r["guideline_lost_strict"] for r in ok)
    g_before = sum(r["guideline_before"] for r in ok)
    print()
    print("  THE TRAP, measured: a STRICT floor cuts %d of %d served guideline"
          % (g_lost, g_before))
    print("  paper-instances across the 29 questions. The NULL exemption keeps them.")
    mism = [r for r in ok if r["mismatch"]]
    print()
    print("  wrapper fidelity: %d of %d questions agreed with the served base"
          % (len(ok) - len(mism), len(ok)))

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        json.dump(results, open(args.json_out, "w"), indent=1)
        print("\n  wrote %s" % args.json_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
