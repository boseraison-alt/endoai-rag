"""
Recompute every stored score in endo_papers_rag with the CURRENT scoring rules.

Why: library scores were computed at ingestion time. Any change to the scoring
model (e.g. turning journal impact factor off via USE_IMPACT_FACTOR) leaves the
library on the old scale, so RAG-path answers rank papers by stale weights while
live-PubMed answers use the new ones.

Usage:
    python scripts/rescore_library.py            # dry run — report only
    python scripts/rescore_library.py --apply    # write the new scores
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2.extras
from endo_ai import score_paper, get_impact_factor, USE_IMPACT_FACTOR
from rag import get_conn


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    print(f"[rescore] USE_IMPACT_FACTOR = {USE_IMPACT_FACTOR}")

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        # Backfill level_key for Cochrane reviews that were ingested without one.
        # Without this they score as "unknown design" (the weakest tier) despite
        # being the strongest evidence in the library.
        cur.execute("""
            UPDATE endo_papers_rag
            SET level_key = 'cochrane'
            WHERE COALESCE(level_key,'') = ''
              AND LOWER(COALESCE(journal,'')) LIKE '%cochrane%';
        """)
        if cur.rowcount:
            print(f"[rescore] backfilled level_key='cochrane' for {cur.rowcount} review(s)")
            if args.apply:
                conn.commit()
            else:
                conn.rollback()

        # Only rescore rows we can score FAITHFULLY:
        #  - level_key must be known (an empty one would be scored as unknown
        #    design, burying papers that simply were never labelled)
        #  - is_curated rows carry hand-assigned authority scores (AAE/ESE
        #    position statements, guidelines) and are never recomputed
        cur.execute("""
            SELECT pmid, year, citations, sample_size, followup_months,
                   journal, level_key, score,
                   COALESCE(coi_flag, FALSE)        AS coi_flag,
                   COALESCE(medline_indexed, TRUE)  AS medline_indexed,
                   COALESCE(has_erratum, FALSE)     AS has_erratum,
                   COALESCE(has_retraction, FALSE)  AS has_retraction,
                   COALESCE(registry, '')           AS registry
            FROM endo_papers_rag
            WHERE COALESCE(level_key,'') <> ''
              AND COALESCE(is_curated, FALSE) = FALSE;
        """)
        rows = cur.fetchall()
        print(f"[rescore] {len(rows)} papers eligible for faithful rescoring "
              f"(unlabelled + curated entries are preserved)")

        updates, deltas, unchanged = [], [], 0
        for r in rows:
            _, if_pts = get_impact_factor(r.get("journal") or "")
            new_score, _ = score_paper(
                r.get("level_key") or "",
                r.get("year"),
                r.get("citations") or 0,
                r.get("sample_size"),
                r.get("followup_months"),
                if_pts,
            )
            # Provenance adjustments are baked into the STORED score — this is
            # the single place they are applied. Because RAG ranks on
            # `score * 0.6 + similarity * 40`, they influence retrieval order
            # and not merely the badge shown afterwards.
            if r["coi_flag"]:
                new_score = round(new_score * 0.85, 1)
            if r["registry"]:
                new_score = round(min(new_score * 1.05, 100.0), 1)
            if r["has_erratum"]:
                new_score = round(new_score * 0.97, 1)
            if r["has_retraction"]:
                new_score = round(new_score * 0.50, 1)
            if not r["medline_indexed"]:
                new_score = round(new_score * 0.97, 1)
            old_score = round(float(r.get("score") or 0), 1)
            if abs(new_score - old_score) < 0.05:
                unchanged += 1
                continue
            updates.append((new_score, r["pmid"]))
            deltas.append(new_score - old_score)

        if deltas:
            deltas_sorted = sorted(deltas)
            print(f"[rescore] changed: {len(updates)}   unchanged: {unchanged}")
            print(f"[rescore] delta  min {deltas_sorted[0]:+.1f} / "
                  f"median {deltas_sorted[len(deltas_sorted)//2]:+.1f} / "
                  f"max {deltas_sorted[-1]:+.1f} / "
                  f"mean {sum(deltas)/len(deltas):+.1f}")
            # How many cross the quality floor of 50 in either direction?
            print(f"[rescore] papers moving up:   {sum(1 for d in deltas if d > 0)}")
            print(f"[rescore] papers moving down: {sum(1 for d in deltas if d < 0)}")
        else:
            print("[rescore] nothing to change")

        if not args.apply:
            print("\n[rescore] DRY RUN — re-run with --apply to write these scores.")
            return 0

        if updates:
            psycopg2.extras.execute_batch(
                cur,
                "UPDATE endo_papers_rag SET score = %s WHERE pmid = %s;",
                updates,
                page_size=500,
            )
            conn.commit()
            print(f"[rescore] APPLIED — {len(updates)} scores updated.")
        return 0

    except Exception as e:
        conn.rollback()
        print(f"[rescore] FAILED: {e}")
        return 1
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
