"""
Demote library rows falsely tagged as Cochrane reviews.

COCHRANE_TERM used to be "Cochrane Review[pt]", which is not a real PubMed
publication type. PubMed translated it to

    ("cochran" OR "cochrane" OR ...) AND "Review"[Publication Type]

so every systematic review that merely mentioned searching the Cochrane Library
came back tagged as the top tier. endo_ai.py now scopes that filter to
'"Cochrane Database Syst Rev"[jour]' and demotes stragglers at fetch time, but
that only protects new retrievals. Rows already in the library keep whatever
level_key they were stored with, and the library read path reads that column
directly — so the false tier survives the code fix until this runs.

Demoting changes the design axis from 100 to 80 (39% weight), so score must be
recomputed. This script only rewrites level_key; run

    python scripts/rescore_library.py --apply

immediately afterwards to bring `score` back in line. Dry-run by default.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2.extras

from endo_ai import _COCHRANE_JOURNAL_HINTS
from rag import get_conn

# Rendered as SQL so the hint list has exactly one definition.
_JOURNAL_TEST = " OR ".join(
    f"LOWER(COALESCE(journal,'')) LIKE '%{h}%'" for h in _COCHRANE_JOURNAL_HINTS
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write the change (default is a dry run)")
    args = ap.parse_args()

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute(f"""
            SELECT pmid, year, journal, title, score
              FROM endo_papers_rag
             WHERE level_key = 'cochrane' AND NOT ({_JOURNAL_TEST})
             ORDER BY score DESC;
        """)
        bad = cur.fetchall()

        cur.execute(f"""
            SELECT COUNT(*) AS n FROM endo_papers_rag
             WHERE level_key = 'cochrane' AND ({_JOURNAL_TEST});
        """)
        genuine = cur.fetchone()["n"]

        print(f"genuine Cochrane Database reviews : {genuine}")
        print(f"falsely tagged, to demote -> level1: {len(bad)}")

        if not bad:
            print("nothing to do")
            return

        journals = {}
        for r in bad:
            journals[r["journal"] or "(none)"] = journals.get(r["journal"] or "(none)", 0) + 1
        print("\ntop journals among the mislabelled:")
        for j, n in sorted(journals.items(), key=lambda kv: -kv[1])[:12]:
            print(f"   {n:>4}  {j}")

        print("\nhighest-scoring mislabelled rows (these outranked real evidence):")
        for r in bad[:10]:
            print(f"   {r['score']:>5.1f}  {r['pmid']}  {r['year']}  {(r['title'] or '')[:58]}")

        if not args.apply:
            print("\nDRY RUN. Re-run with --apply, then rescore_library.py --apply")
            return

        cur.execute(f"""
            UPDATE endo_papers_rag
               SET level_key = 'level1'
             WHERE level_key = 'cochrane' AND NOT ({_JOURNAL_TEST});
        """)
        demoted = cur.rowcount

        # Any cached answer may have been built on the false tier ordering, and
        # the cache stores its own paper list rather than re-reading the table.
        cur.execute("DELETE FROM query_cache;")
        purged = cur.rowcount

        conn.commit()
        print(f"\ndemoted {demoted} row(s) cochrane -> level1")
        print(f"purged {purged} cached answer(s) built on the old tiering")
        print("NEXT: python scripts/rescore_library.py --apply")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
