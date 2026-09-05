"""
WORKLIST 1.5 dry run — what does the flat quality floor actually cost?

QUALITY_FLOOR is a single number (50) applied to every tier. Score is not
comparable across tiers by construction: the design axis contributes 39% of it,
so a Cochrane review starts from 100 and a case series from 20 before anything
about the paper is considered. A flat cut therefore does not remove weak papers
evenly — it removes whole tiers.

This measures the effect on the real library rather than arguing about it, and
prints what per-tier percentile floors would keep instead.

    python scripts/measure_quality_floor.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2.extras

from endo_ai import (QUALITY_FLOOR, MIN_PAPERS_KEPT, TIER_ORDER, LEVEL_SCORES,
                     TIER_LABEL)
from rag import get_conn


def pct(values, p):
    if not values:
        return None
    s = sorted(values)
    i = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[i]


def main():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""
            SELECT level_key, score FROM endo_papers_rag
             WHERE COALESCE(level_key,'') <> '' AND level_key <> 'retracted'
               AND score IS NOT NULL;
        """)
        by_tier = {}
        for r in cur.fetchall():
            by_tier.setdefault(r["level_key"], []).append(float(r["score"]))

        print(f"FLAT FLOOR = {QUALITY_FLOOR}  (MIN_PAPERS_KEPT={MIN_PAPERS_KEPT} "
              f"tops a tier back up, so 'survive' below is before that rescue)\n")
        print(f"  {'tier':<10} {'design':>6} {'n':>5} {'survive':>8} {'share':>7} "
              f"{'median':>7} {'p90':>6}  {'verdict'}")
        proposal = {}
        # TIER_ORDER only, DELIBERATELY: this fits per-tier QUALITY FLOORS from
        # a score distribution, and PROVISIONAL_KEY papers carry score=None by
        # design. There is no distribution to fit and no floor to propose.
        for tier in TIER_ORDER:
            v = by_tier.get(tier)
            if not v:
                continue
            surv = [s for s in v if s >= QUALITY_FLOOR]
            share = len(surv) / len(v)
            med, p90 = pct(v, 50), pct(v, 90)
            # A tier whose own 90th percentile sits under the flat floor cannot
            # contribute its BEST work — the floor is not filtering quality
            # there, it is deleting the tier.
            verdict = ("TIER DELETED — even its p90 is below the floor"
                       if (p90 or 0) < QUALITY_FLOOR else
                       "thinned" if share < 0.5 else "ok")
            print(f"  {tier:<10} {LEVEL_SCORES.get(tier, 0):>6} {len(v):>5} "
                  f"{len(surv):>8} {share:>6.0%} {med:>7.1f} {p90:>6.1f}  {verdict}")
            # Percentile floor: keep the top 60% OF THAT TIER, so each tier is
            # judged against its own distribution instead of a global constant.
            proposal[tier] = round(pct(v, 40) or 0, 1)

        print(f"\nPROPOSED per-tier floors (keep the top ~60% within each tier)")
        print(f"  {'tier':<10} {'flat':>6} {'proposed':>9} {'keeps':>7} {'was':>6}")
        # TIER_ORDER only — same reason as above: a provisional paper
        # carries no score, so there is no floor to propose for it.
        for tier in TIER_ORDER:
            v = by_tier.get(tier)
            if not v:
                continue
            f = proposal[tier]
            keeps = len([s for s in v if s >= f])
            was = len([s for s in v if s >= QUALITY_FLOOR])
            print(f"  {tier:<10} {QUALITY_FLOOR:>6} {f:>9} {keeps:>7} {was:>6}")
        print("\n(dry run — no changes written)")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
