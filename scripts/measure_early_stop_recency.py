"""D1 — what would a RECENCY EXEMPTION on the review-mode early stop admit?

MEASURE ONLY. Nothing is changed by this script and the exemption is NOT
implemented; this is the measurement the decision is gated on.

THE PROPOSAL. In Review mode, once cochrane + level1 supply
EARLY_STOP_MIN_PAPERS (15), the weaker lanes are skipped entirely. D1 keeps
that but exempts RECENCY: weaker lanes are still fetched, and papers published
in the last `--months` (default 18) are kept while older ones are dropped as
before. The reasoning is that a settled topic is exactly where a new
contradicting finding matters most, and an old contradicting paper has already
been absorbed or refuted.

WHAT IS MEASURED, per question:
  - whether the early stop fires at all (it only fires in review mode, and
    only when the strong tiers are deep enough)
  - how many papers the skipped lanes would return
  - how many of those are within the recency window -- THE NUMBER THAT DECIDES
  - the cost: extra esearch/efetch round trips and seconds

PRE-DECLARED THRESHOLD (from the ORDER): if the exemption adds more than ~15
papers per question on average, report before shipping.

WHY THIS COSTS A LIVE RUN. The early stop is a LIVE-path behaviour: it decides
which lanes are fetched from PubMed. There is no library-side proxy for "what
would those lanes have returned", and substituting one would be measuring a
different thing and calling it this (rule 27). So every question here is a real
live retrieval and this script is slow by construction.

Usage:  python scripts/measure_early_stop_recency.py [--months 18] [--json OUT]
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E                      # noqa: E402
import app as A                          # noqa: E402


def within_months(paper, months):
    """Is this paper inside the recency window?

    PubMed metadata carries a YEAR here, not a month, so a month-granular
    window cannot be evaluated exactly. The window is therefore applied at
    YEAR granularity and rounded OUTWARD -- a paper is in if its year is
    within ceil(months/12) years of now. That admits slightly more than the
    stated window rather than slightly less, which is the safe direction for a
    measurement whose whole purpose is to bound how much the exemption lets
    in: it cannot understate the cost.
    """
    try:
        y = int(paper.get("year", 0))
    except (ValueError, TypeError):
        return False
    if y <= 0:
        return False
    span = -(-months // 12)
    return (datetime.now().year - y) <= span


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=18)
    ap.add_argument("--json", dest="json_out", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    cases = [c for c in json.load(open("eval/questions.json"))["cases"]
             if c.get("mode", "review") == "review"]
    if args.limit:
        cases = cases[:args.limit]

    E.LIBRARY_WRITE_BACK = False
    span = -(-args.months // 12)
    print("=" * 78)
    print("D1 — RECENCY EXEMPTION ON THE REVIEW-MODE EARLY STOP")
    print("=" * 78)
    print("measure only; the exemption is NOT implemented")
    print("window %d months, evaluated at year granularity as %d year(s), "
          "rounded outward" % (args.months, span))
    print("early stop: mode=review and cochrane+level1 >= %d\n"
          % A.EARLY_STOP_MIN_PAPERS)

    rows = []
    for i, case in enumerate(cases, 1):
        qid = case["id"]
        print("-" * 78)
        print("[%2d/%d] %s" % (i, len(cases), qid))
        job = "d1-%s" % qid
        A.jobs[job] = {"status": "running", "steps": [], "progress": 0}
        exchanges = (case.get("context") or {}).get("exchanges") or []
        ctx = E.build_context_block(exchanges) if exchanges else ""
        prior = E.context_prior_pmids(exchanges) if exchanges else None

        # PASS 1 — production as it stands. force_route="live" so the early
        # stop is actually reachable; on the library route it never runs.
        t0 = time.time()
        try:
            ev = A.build_evidence_base_with_progress(
                job, case["question"], force_route="live", mode="review",
                context_block=ctx, prior_pmids=prior) or {}
        except Exception as e:
            print("   PASS1 FAILED: %s" % e)
            rows.append({"id": qid, "error": str(e)})
            continue
        t_base = time.time() - t0

        n_strong = sum(len((ev.get(t) or {}).get("scored") or [])
                       for t in ("cochrane", "level1"))
        weak = [t for t in E.TIER_ORDER
                if t not in ("cochrane", "level1", "guideline")]
        served_weak = sum(len((ev.get(t) or {}).get("scored") or []) for t in weak)
        fired = (n_strong >= A.EARLY_STOP_MIN_PAPERS) and served_weak == 0

        row = {"id": qid, "n_strong": n_strong, "served_weak": served_weak,
               "early_stop_fired": fired, "seconds_base": round(t_base, 1)}

        if not fired:
            print("   early stop did NOT fire (strong=%d, weak served=%d) — "
                  "the exemption changes nothing here" % (n_strong, served_weak))
            row.update({"would_admit": 0, "would_admit_recent": 0,
                        "seconds_extra": 0.0})
            rows.append(row)
            continue

        # PASS 2 — the same question with the early stop disabled, so the
        # skipped lanes actually run and we can count what they would have
        # returned. The threshold is raised rather than the branch edited:
        # production code is not modified by a measurement.
        saved = A.EARLY_STOP_MIN_PAPERS
        A.EARLY_STOP_MIN_PAPERS = 10 ** 6
        t0 = time.time()
        try:
            ev2 = A.build_evidence_base_with_progress(
                job + "-full", case["question"], force_route="live",
                mode="review", context_block=ctx, prior_pmids=prior) or {}
        except Exception as e:
            print("   PASS2 FAILED: %s" % e)
            A.EARLY_STOP_MIN_PAPERS = saved
            row["error_pass2"] = str(e)
            rows.append(row)
            continue
        finally:
            A.EARLY_STOP_MIN_PAPERS = saved
        t_full = time.time() - t0

        admitted, recent, per_tier = 0, 0, {}
        for t in weak:
            sc = (ev2.get(t) or {}).get("scored") or []
            r = [p for p in sc if within_months(p, args.months)]
            admitted += len(sc)
            recent += len(r)
            if sc:
                per_tier[t] = {"all": len(sc), "recent": len(r)}
        row.update({"would_admit": admitted, "would_admit_recent": recent,
                    "per_tier": per_tier,
                    "seconds_extra": round(t_full - t_base, 1)})
        rows.append(row)
        print("   early stop FIRED (strong=%d). Weak lanes would return %d; "
              "%d within %dmo. +%.0fs"
              % (n_strong, admitted, recent, args.months, t_full - t_base))
        if per_tier:
            print("   " + ", ".join("%s %d/%d" % (t, v["recent"], v["all"])
                                    for t, v in sorted(per_tier.items())))

    ok = [r for r in rows if "error" not in r]
    fired = [r for r in ok if r.get("early_stop_fired")]
    print()
    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print("  review-mode questions measured     %d" % len(ok))
    print("  early stop FIRED on                %d" % len(fired))
    if fired:
        adm = sum(r["would_admit"] for r in fired)
        rec = sum(r["would_admit_recent"] for r in fired)
        sec = sum(r["seconds_extra"] for r in fired)
        print()
        print("  ON THE QUESTIONS WHERE IT FIRES:")
        print("    weak-lane papers, all ages       %d  (mean %.1f/question)"
              % (adm, adm / len(fired)))
        print("    within the recency window        %d  (mean %.1f/question)"
              % (rec, rec / len(fired)))
        print("    extra wall-clock                 %.0fs (mean %.0fs/question)"
              % (sec, sec / len(fired)))
        print()
        print("  PRE-DECLARED THRESHOLD: report before shipping if the")
        print("  exemption adds more than ~15 papers per question on average.")
        print("    measured mean: %.1f  ->  %s"
              % (rec / len(fired),
                 "OVER — report before shipping" if rec / len(fired) > 15
                 else "under the threshold"))
    print()
    print("  %-36s %7s %6s %8s %7s" % ("question", "strong", "fired",
                                       "recent", "all"))
    for r in ok:
        print("  %-36s %7d %6s %8s %7s"
              % (r["id"][:36], r["n_strong"],
                 "YES" if r.get("early_stop_fired") else "-",
                 r.get("would_admit_recent", "-"), r.get("would_admit", "-")))

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        json.dump(rows, open(args.json_out, "w"), indent=1)
        print("\n  wrote %s" % args.json_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
