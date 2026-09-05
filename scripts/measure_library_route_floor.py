"""How much evidence does the LIBRARY route serve below its own tier's floor?

MEASURE ONLY. Nothing is changed by this script.

`app.build_evidence_base_with_progress`'s library branch applies a 0.60 cosine
similarity floor and a flat per-tier cap of 25, and nothing else.
`_apply_quality_threshold` / `_tier_floor` / `_tier_cap` / MODE_TIER_QUOTAS
have no callers in app.py at all, so the per-tier QUALITY floors that the live
and curriculum paths apply are absent on the route that answers most warm
questions.

Two consequences, measured here against the live library:
  1. rows served under a tier label whose own floor they do not clear
  2. the cap: 25 per tier on this route against MODE_TIER_QUOTAS' 18 for
     level1 and 4 for the weak tiers, so eight weak tiers can contribute up to
     200 papers against level1's 25.

Usage:  python scripts/measure_library_route_floor.py
"""
import collections
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import psycopg2                    # noqa: E402
import psycopg2.extras             # noqa: E402
import endo_ai as E                # noqa: E402
import app as A                    # noqa: E402
from rag import DATABASE_URL       # noqa: E402


def tier_floor(tier):
    """The floor the live and curriculum paths apply for this tier."""
    floors = getattr(E, "TIER_QUALITY_FLOORS", {}) or {}
    return floors.get(tier, getattr(E, "QUALITY_FLOOR", 0))


def main():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT level_key, score, pmid, title
        FROM endo_papers_rag
        WHERE COALESCE(quarantine_reason,'') = ''
          AND NOT COALESCE(has_retraction, FALSE)
          AND title NOT ILIKE 'WITHDRAWN:%%'
          AND COALESCE(superseded_by,'') = ''
          AND level_key IS NOT NULL
    """)
    rows = cur.fetchall()
    conn.close()

    print("=" * 78)
    print("LIBRARY ROUTE — EVIDENCE SERVED BELOW ITS OWN TIER'S QUALITY FLOOR")
    print("=" * 78)
    print("measure only; nothing changed\n")

    below = collections.Counter()
    total = collections.Counter()
    null_score = collections.Counter()
    worst = []
    for r in rows:
        tier = r["level_key"]
        total[tier] += 1
        if r["score"] is None:
            null_score[tier] += 1
            continue
        f = tier_floor(tier)
        if f and float(r["score"]) < float(f):
            below[tier] += 1
            worst.append((tier, float(r["score"]), f, r["pmid"],
                          (r["title"] or "")[:52]))

    print("  %-16s %8s %8s %8s %8s" % ("tier", "rows", "floor", "below", "null"))
    n_below = n_total = 0
    for tier in sorted(total):
        f = tier_floor(tier)
        print("  %-16s %8d %8s %8d %8d"
              % (tier, total[tier], f or "-", below[tier], null_score[tier]))
        n_below += below[tier]
        n_total += total[tier]
    print("  %-16s %8d %8s %8d %8d"
          % ("TOTAL", n_total, "", n_below, sum(null_score.values())))
    print()
    print("  %d of %d scored rows (%.1f%%) sit below their own tier's floor and"
          % (n_below, n_total, 100.0 * n_below / max(1, n_total)))
    print("  are served by the library route anyway.")

    lvl1 = sorted((w for w in worst if w[0] == "level1"), key=lambda w: w[1])
    if lvl1:
        print()
        print("  Worst offenders rendered under \"Level I — RCTs and Systematic "
              "Reviews\":")
        for tier, sc, f, pmid, title in lvl1[:8]:
            print("      %-10s score %5.1f (floor %s)  %s" % (pmid, sc, f, title))

    print()
    print("  THE CAP, for the same route:")
    print("    library route  flat %d per tier (RELEVANCE_GATE['max_per_tier'])"
          % A.RELEVANCE_GATE["max_per_tier"])
    for t in ("level1", "level4", "level5", "guideline"):
        print("    live/curriculum %-10s %d  (MODE_TIER_QUOTAS review)"
              % (t, E._tier_cap("review", t)))
    print()
    print("  THE TRAP FOR WHOEVER FIXES THIS: %d guideline rows store score"
          % null_score.get("guideline", 0))
    print("  NULL by design, and rag_results_to_scored coalesces that to 0.0.")
    print("  Applying a quality floor naively deletes every guideline from")
    print("  library-served answers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
