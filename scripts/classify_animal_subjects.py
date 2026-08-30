"""
WORKLIST C2 — route animal-subject studies out of the clinical tiers.

"Vital pulp therapy in dogs maintains an 80% success rate independent of
patient age: a 25-year retrospective study" (*J Am Vet Med Assoc*, PMID
40683315) was scoring 59.8 in the clinical hierarchy, retrievable as human
clinical evidence, because nothing in this codebase had any concept of a
non-human subject. It is a good study. It is about dogs.

Animal-subject rows move to `invitro` (LEVEL_SCORES 15, between case series
and expert opinion) — the tier this project already uses for evidence that is
real about a mechanism and silent about what happens in a patient.

WHAT THIS SCRIPT WILL NOT DO
----------------------------
* It never PROMOTES. A row already at or below `invitro`'s 15 (i.e. `level5`)
  is left where it is and reported under "held back". Raising a paper's tier
  on the strength of a text cue is the dangerous direction, and this is the
  same rule `scripts/classify_invitro.py` follows.
* It never touches `cochrane`, `level1` or `classic`
  (`animal_subjects._ANIMAL_PROTECTED_LEVELS`). Level I synthesis abstracts
  are full of animal vocabulary because that is what they excluded; the
  `classic` tier holds the seminal monkey and dog experiments of endodontics
  deliberately.
* It never touches curated rows, retracted rows, or rows already at `invitro`.

The dry run prints EVERY affected row — pmid, journal, title, and the cue that
fired — not a sample, because the whole risk of this classifier is false
positives and a count cannot show one. It also prints the rows it declined
that contain animal vocabulary anyway, so a reviewer can see what the vetoes
caught as well as what the cues did.

    python scripts/classify_animal_subjects.py            # dry run
    python scripts/classify_animal_subjects.py --apply
    python scripts/rescore_library.py --apply             # ALWAYS after --apply
"""
import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2.extras

from animal_subjects import (detect_animal_subject, _ANIMAL_PROTECTED_LEVELS,
                             _ANIMAL_STRONG_RE, _VET_JOURNAL_HINTS)
from endo_ai import LEVEL_SCORES
from rag import get_conn

TARGET_TIER   = "invitro"
TARGET_SCORE  = LEVEL_SCORES[TARGET_TIER]
BACKUP_TABLE  = "endo_papers_rag_tier_backup"
RUN_ID        = "animal_subjects_20260830"

import re

# Any species word at all — used ONLY to build the "declined but contains
# animal vocabulary" review list, never to classify.
_ANY_ANIMAL_WORD_RE = re.compile(
    r"\b(?:dogs?|canines?|rats?|mice|mouse|murine|bovine|porcine|swine|pigs?|"
    r"sheep|ovine|rabbits?|monkeys?|macaque\w*|primates?|ferrets?|hamsters?|"
    r"guinea[- ]pigs?|zebrafish|felines?|cattle|calves|goats?|equine|"
    r"animal\s+(?:model|stud\w+|experiment\w*)|veterinar\w*)\b",
    re.IGNORECASE)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write the change (default: dry run)")
    ap.add_argument("--show-declined", type=int, default=25,
                    help="how many declined-but-animal-flavoured rows to print")
    args = ap.parse_args()

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""
            SELECT pmid, title, COALESCE(abstract,'') AS abstract,
                   COALESCE(journal,'') AS journal, level_key,
                   ROUND(COALESCE(score,0)::numeric, 1) AS score
              FROM endo_papers_rag
             WHERE COALESCE(level_key,'') <> ''
               AND level_key <> %s
               AND level_key <> 'retracted'
               AND NOT COALESCE(is_curated, FALSE)
             ORDER BY pmid;
        """, (TARGET_TIER,))
        rows = cur.fetchall()
        print(f"[animal] rows examined: {len(rows)}")
        print(f"[animal] protected tiers (never moved): "
              f"{sorted(_ANIMAL_PROTECTED_LEVELS)}")
        print(f"[animal] target tier: {TARGET_TIER} (LEVEL_SCORES {TARGET_SCORE})\n")

        moves, held, declined_with_vocab = [], [], []
        held_counter = Counter()
        for r in rows:
            hit, why = detect_animal_subject(r["title"], r["abstract"],
                                             r["journal"], r["level_key"])
            if not hit:
                if _ANY_ANIMAL_WORD_RE.search(
                        f"{r['title']}\n{r['abstract']}\n{r['journal']}"):
                    declined_with_vocab.append((r, why))
                continue
            if LEVEL_SCORES.get(r["level_key"], 0) <= TARGET_SCORE:
                held.append((r, why))
                held_counter["would promote"] += 1
                continue
            moves.append((r, why))

        # ── delta split by source tier ──
        by_tier = Counter(r["level_key"] for r, _ in moves)
        totals  = Counter(r["level_key"] for r in rows)
        print("=" * 78)
        print(f"DELTA SPLIT — rows moving to `{TARGET_TIER}`, by source tier")
        print("=" * 78)
        print(f"  {'tier':<10} {'moving':>7} {'of':>7} {'share':>7} "
              f"{'LEVEL_SCORES':>13}")
        for tier in sorted(totals, key=lambda t: -by_tier.get(t, 0)):
            n = by_tier.get(tier, 0)
            if n:
                print(f"  {tier:<10} {n:>7} {totals[tier]:>7} "
                      f"{n / totals[tier]:>6.0%} {LEVEL_SCORES.get(tier, 0):>13} "
                      f"-> {TARGET_SCORE}")
        print(f"  {'TOTAL':<10} {len(moves):>7} {len(rows):>7} "
              f"{len(moves) / max(len(rows), 1):>6.0%}")
        if held_counter:
            print("  held back: " +
                  ", ".join(f"{v} {k}" for k, v in held_counter.items()))

        # ── every affected row, in full ──
        grouped = defaultdict(list)
        for r, why in moves:
            grouped[r["level_key"]].append((r, why))
        for tier in sorted(grouped, key=lambda t: -len(grouped[t])):
            print(f"\n--- {tier} -> {TARGET_TIER}: {len(grouped[tier])} row(s), "
                  f"ALL shown ---")
            for r, why in sorted(grouped[tier],
                                 key=lambda x: -float(x[0]["score"])):
                print(f"  {r['pmid']:>9}  {r['score']:>5}  "
                      f"[{why[:46]:<46}]")
                print(f"             {r['journal'][:44]:<44} | "
                      f"{(r['title'] or '')[:96]}")

        if held:
            print(f"\n--- HELD BACK — already at or below {TARGET_TIER} "
                  f"(moving them would PROMOTE): {len(held)} row(s) ---")
            for r, why in held:
                print(f"  {r['pmid']:>9}  {r['level_key']:<8} {r['score']:>5}  "
                      f"[{why[:40]:<40}]")
                print(f"             {r['journal'][:44]:<44} | "
                      f"{(r['title'] or '')[:96]}")

        if args.show_declined and declined_with_vocab:
            print(f"\n--- DECLINED but contains animal vocabulary: "
                  f"{len(declined_with_vocab)} row(s), first "
                  f"{min(args.show_declined, len(declined_with_vocab))} shown ---")
            print("    (these are the false positives the vetoes prevented — "
                  "read them too)")
            for r, why in declined_with_vocab[:args.show_declined]:
                print(f"  {r['pmid']:>9}  {r['level_key']:<8} {r['score']:>5}  "
                      f"[{why[:40]:<40}] {(r['title'] or '')[:70]}")

        if not args.apply:
            print("\n[animal] DRY RUN — review every row above, then --apply, "
                  "then python scripts/rescore_library.py --apply")
            return 0

        if not moves:
            print("\n[animal] nothing to move")
            return 0

        pmids = [r["pmid"] for r, _ in moves]
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {BACKUP_TABLE} (
                run_id TEXT, pmid TEXT, level_key TEXT, score REAL,
                journal TEXT, backed_up TIMESTAMP DEFAULT NOW());
        """)
        cur.execute(f"""
            INSERT INTO {BACKUP_TABLE} (run_id, pmid, level_key, score, journal)
            SELECT %s, pmid, level_key, score, journal FROM endo_papers_rag
             WHERE pmid = ANY(%s);
        """, (RUN_ID, pmids))
        print(f"\n[animal] backed up {cur.rowcount} row(s) under run_id={RUN_ID}")
        print(f"[animal] restore:\n"
              f"    UPDATE endo_papers_rag e\n"
              f"       SET level_key = b.level_key, score = b.score\n"
              f"      FROM {BACKUP_TABLE} b\n"
              f"     WHERE b.run_id = '{RUN_ID}' AND b.pmid = e.pmid;")

        cur.execute("UPDATE endo_papers_rag SET level_key = %s WHERE pmid = ANY(%s);",
                    (TARGET_TIER, pmids))
        moved = cur.rowcount
        cur.execute("DELETE FROM query_cache;")
        purged = cur.rowcount
        conn.commit()
        print(f"[animal] APPLIED — {moved} row(s) -> {TARGET_TIER}; "
              f"purged {purged} cached answer(s)")
        print("[animal] NEXT: python scripts/rescore_library.py --apply")
        return 0

    except Exception as e:
        conn.rollback()
        print(f"[animal] FAILED: {e}")
        return 1
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
