"""
WORKLIST 1.4 — move bench studies into the `invitro` tier.

Endodontics is heavily bench-based. Extracted teeth, dentine blocks, bovine
incisors and agar plates all read as "prospective" to a design classifier, so
they were sitting at Level II — presented to the clinician as the second
strongest kind of evidence there is. An in vitro result is real evidence about
a mechanism and no evidence at all about what happens in a patient.

Dry-run by default. The dry run prints, per source tier, how many rows would
move and 20 RANDOM titles with the cue that triggered them, because a migration
this broad has to be reviewable by eye before it is trusted — the sample is
random rather than top-N so it cannot flatter itself.

--apply backs up to endo_papers_rag_tier_backup, writes, and truncates
query_cache (every cached answer built on the old tiering is now wrong).
Idempotent: rows already at `invitro` are skipped, so a second run moves none.

    python scripts/classify_invitro.py            # dry run
    python scripts/classify_invitro.py --sample 20
    python scripts/classify_invitro.py --apply
    python scripts/rescore_library.py --apply     # ALWAYS after --apply
"""
import argparse
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2.extras

import re

from endo_ai import (detect_in_vitro, _INVITRO_PROTECTED_LEVELS,
                     LEVEL_SCORES)
from rag import get_conn

# A migration that PROMOTES is not what this tier is for. invitro scores 15;
# level5 scores 10, so moving a narrative review that merely discusses in
# vitro work would raise it. The dry run caught exactly that: "Review of
# ultrasonic irrigation in endodontics" and "The Calcium Hydroxide
# Controversy" are reviews OF bench evidence, not bench studies.
INVITRO_SCORE = LEVEL_SCORES["invitro"]

# Case reports describe a patient. "extracted premolars" in one refers to
# the procedure performed, not to the specimens studied — the dry run
# flagged "A case of tooth autotransplantation after long-term
# cryopreservation", which is clinical evidence however weak.
_CASE_REPORT_TITLE_RE = re.compile(
    r"^\s*(?:a\s+)?case\s+(?:report|of|series)\b|:\s*a\s+case\s+report",
    re.IGNORECASE)

RUN_ID = "invitro_20260830"
# Deterministic sampling so the dry run a human reviewed is the same dry run
# that gets applied.
SEED = 20260830


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--sample", type=int, default=20,
                    help="random titles to print per source tier")
    args = ap.parse_args()

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""
            SELECT pmid, title, abstract, journal, level_key, score
              FROM endo_papers_rag
             WHERE COALESCE(level_key,'') <> ''
               AND level_key <> 'invitro'
               AND level_key <> 'retracted'
               AND NOT COALESCE(is_curated, FALSE)
             ORDER BY pmid;
        """)
        rows = cur.fetchall()
        print(f"rows examined: {len(rows)}")
        print(f"protected tiers (never moved): {sorted(_INVITRO_PROTECTED_LEVELS)}\n")

        moves, skipped = [], Counter()
        for r in rows:
            hit, why = detect_in_vitro(r["title"], r["abstract"], r["level_key"])
            if not hit:
                continue
            if LEVEL_SCORES.get(r["level_key"], 0) <= INVITRO_SCORE:
                skipped["would promote"] += 1
                continue
            if _CASE_REPORT_TITLE_RE.search(r["title"] or ""):
                skipped["case report"] += 1
                continue
            moves.append((r, why))

        by_tier = Counter(r["level_key"] for r, _ in moves)
        totals = Counter(r["level_key"] for r in rows)
        print("DELTA SPLIT — rows moving to `invitro`, by source tier")
        print(f"  {'tier':<10} {'moving':>7} {'of':>7} {'share':>7}")
        for tier in sorted(totals, key=lambda t: -by_tier.get(t, 0)):
            n = by_tier.get(tier, 0)
            if n:
                print(f"  {tier:<10} {n:>7} {totals[tier]:>7} {n / totals[tier]:>6.0%}")
        print(f"  {'TOTAL':<10} {len(moves):>7} {len(rows):>7} "
              f"{len(moves) / max(len(rows), 1):>6.0%}")
        if skipped:
            print("  held back: " + ", ".join(f"{v} {k}" for k, v in skipped.items()))

        grouped = defaultdict(list)
        for r, why in moves:
            grouped[r["level_key"]].append((r, why))
        rng = random.Random(SEED)
        for tier in sorted(grouped, key=lambda t: -len(grouped[t])):
            sample = grouped[tier][:]
            rng.shuffle(sample)
            print(f"\n--- {tier} -> invitro: {len(grouped[tier])} rows, "
                  f"{min(args.sample, len(sample))} random for review ---")
            for r, why in sample[:args.sample]:
                print(f"  {r['pmid']}  {r['score']:>5.1f}  [{why[:34]:<34}] "
                      f"{(r['title'] or '')[:58]}")

        if not args.apply:
            print("\nDRY RUN. Review the samples above, then --apply, "
                  "then scripts/rescore_library.py --apply")
            return

        if not moves:
            print("\nnothing to move")
            return

        pmids = [r["pmid"] for r, _ in moves]
        cur.execute("""
            CREATE TABLE IF NOT EXISTS endo_papers_rag_tier_backup (
                run_id TEXT, pmid TEXT, level_key TEXT, score REAL,
                journal TEXT, backed_up TIMESTAMP DEFAULT NOW());
        """)
        cur.execute("""
            INSERT INTO endo_papers_rag_tier_backup (run_id, pmid, level_key, score, journal)
            SELECT %s, pmid, level_key, score, journal FROM endo_papers_rag
             WHERE pmid = ANY(%s);
        """, (RUN_ID, pmids))
        print(f"\nbacked up {cur.rowcount} row(s) under run_id={RUN_ID}")
        print(f"restore: UPDATE endo_papers_rag e SET level_key = b.level_key, "
              f"score = b.score FROM endo_papers_rag_tier_backup b "
              f"WHERE b.run_id = '{RUN_ID}' AND b.pmid = e.pmid;")

        cur.execute("UPDATE endo_papers_rag SET level_key = 'invitro' WHERE pmid = ANY(%s);",
                    (pmids,))
        moved = cur.rowcount
        cur.execute("DELETE FROM query_cache;")
        purged = cur.rowcount
        conn.commit()
        print(f"applied: {moved} row(s) -> invitro; purged {purged} cached answer(s)")
        print("NEXT: python scripts/rescore_library.py --apply")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
