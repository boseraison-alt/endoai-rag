"""
WORKLIST C3 — classify scoping reviews consistently.

THE INCONSISTENCY
-----------------
Scoping reviews in this library disagree with themselves: when the WORKLIST
was written, 8 sat at `level1` and 3 at `level5`, because two earlier
migrations both declined to invent a tier and defaulted opposite ways
(reclassify_by_pubtype.py reported them untouched at level1;
fix_empty_level_key.py parked its three at level5). Write-back has since
added more — the scope here is EVERY row whose title says "scoping review",
so the same rule lands on all of them and on nothing else.

THE RULE
--------
`level5`, UNLESS `PublicationTypeList` includes "Systematic Review" or
"Meta-Analysis" on a MEDLINE-indexed record — in which case `level1`, because
NLM's indexers read the full text and decided the paper is a genuine evidence
synthesis whatever its title says ("systematic scoping review" hybrids are
real). A scoping review charts a literature without effect estimates or
quality appraisal, so presenting one to Claude as Level I overstates it; the
recommendation recorded in HANDOVER.md ("move all 11 to level5") is what this
implements.

THE MEDLINE GATE IS NOT OPTIONAL
--------------------------------
Publisher-supplied records carry only ["Journal Article", "Review"] no matter
what the paper is (HANDOVER: "trusting a PubMed field that is only populated
for some records"; a pubtype-only pass would have demoted 45 genuine
systematic reviews). Here the gate cuts the other way too: a non-MEDLINE
record CANNOT earn the level1 exception, because its pubtype list proves
nothing — but it can still be demoted to level5, because the demotion is
keyed on the TITLE (self-referential — "…: A Scoping Review" names its own
design), not on the missing pubtypes.

REUSE, NOT A SECOND COPY
------------------------
Publication types and MEDLINE status come from
scripts.reclassify_by_pubtype.fetch_pubtypes, which already batches the
efetch through endo_ai._merge_corrections_and_registries with _ncbi_params
(tool/email/api_key) and parses MedlineCitation/@Status per record. Nothing
about the fetch or the parse is reimplemented here.

Rows already at the tier the rule chooses are reported unchanged. Curated
rows are excluded. Rows at `invitro` are reported but NOT moved: the two
there were placed by classify_invitro's hand-reviewed migration, and moving
level5-bound rows OUT of invitro (15 -> 10) is a demotion this task did not
ask for — they are listed for a human instead.

    python scripts/reclassify_scoping_reviews.py                 # dry run
    python scripts/reclassify_scoping_reviews.py --cache sc.json # reuse fetch
    python scripts/reclassify_scoping_reviews.py --apply
    python scripts/rescore_library.py --apply                    # ALWAYS after
"""
import argparse
import json
import time
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2.extras

from scripts.reclassify_by_pubtype import fetch_pubtypes, LEVEL1_PUBTYPES
from rag import get_conn

BACKUP_TABLE = "endo_papers_rag_tier_backup"
RUN_ID = "scoping_reviews_" + time.strftime("%Y%m%dT%H%M%S")

# The two pubtypes that earn the level1 exception, and only on MEDLINE rows.
SYNTHESIS_PUBTYPES = {"systematic review", "meta-analysis"}

# Guideline / consensus / RCT pubtypes that reclassify_by_pubtype maps to
# level1. A "scoping review" title co-occurring with one of these on a
# MEDLINE record is NOT plainly a scoping review — the real case in this
# library is PMID 39487671, an IADT terminology paper NLM tagged both
# "Scoping Review" and "Consensus Statement". Demoting it here while
# reclassify_by_pubtype promotes consensus statements would recreate the
# exact two-rules-disagree failure C3 exists to fix, so such rows are parked
# for a human instead. Decline-only: this never promotes anything.
CONFLICTING_LEVEL1_PUBTYPES = tuple(t for t in LEVEL1_PUBTYPES
                                    if t not in SYNTHESIS_PUBTYPES)


def target_tier(pubtypes, medline_indexed: bool) -> tuple:
    """(target level_key | None, reason) for one title-identified scoping
    review. None means: conflicting authoritative pubtypes — report, don't
    touch."""
    lowered = {str(p).strip().lower() for p in (pubtypes or []) if str(p).strip()}
    hits = sorted(lowered & SYNTHESIS_PUBTYPES)
    if hits and medline_indexed:
        return "level1", f"MEDLINE + {'/'.join(hits)}[pt] — NLM says evidence synthesis"
    if medline_indexed:
        clash = sorted(t for t in CONFLICTING_LEVEL1_PUBTYPES if t in lowered)
        if clash:
            return None, (f"MEDLINE record also tagged {'/'.join(clash)}[pt] — "
                          f"conflicts with the level1 mapping in "
                          f"reclassify_by_pubtype; needs a human")
    if hits and not medline_indexed:
        # Cannot happen in practice (publisher records don't carry these
        # types) but the gate is written out: an unindexed record earns no
        # exception.
        return "level5", f"{'/'.join(hits)}[pt] but NOT MEDLINE-indexed — not authoritative"
    return "level5", ("scoping review by title; no MEDLINE SR/MA publication type"
                      if medline_indexed else
                      "scoping review by title; record not MEDLINE-indexed")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--cache", default="",
                    help="JSON cache of fetched pubtypes, so --apply "
                         "reclassifies exactly what the dry run reported")
    args = ap.parse_args()

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""
            SELECT pmid, title, journal, level_key,
                   ROUND(COALESCE(score,0)::numeric, 1) AS score,
                   COALESCE(medline_indexed, TRUE) AS stored_mi
              FROM endo_papers_rag
             WHERE title ~* 'scoping review'
               AND NOT COALESCE(is_curated, FALSE)
               AND pmid ~ '^[0-9]+$'
             ORDER BY level_key, pmid;
        """)
        rows = cur.fetchall()
        print(f"[scoping] rows whose title says 'scoping review': {len(rows)}")
        for k, n in sorted(Counter(r["level_key"] for r in rows).items()):
            print(f"          {n:3}  currently {k}")

        cache_path = Path(args.cache) if args.cache else None
        fetched = {}
        if cache_path and cache_path.exists():
            fetched = json.loads(cache_path.read_text(encoding="utf-8"))
            print(f"[scoping] loaded {len(fetched)} cached record(s)")
        missing = [r["pmid"] for r in rows if r["pmid"] not in fetched]
        if missing:
            print(f"[scoping] efetch PublicationTypeList for {len(missing)} PMIDs "
                  f"(via reclassify_by_pubtype.fetch_pubtypes)")
            fetched.update(fetch_pubtypes(missing))
            if cache_path:
                cache_path.write_text(json.dumps(fetched), encoding="utf-8")

        updates, unchanged, parked = [], [], []
        print("\n" + "=" * 110)
        print(f"{'pmid':>9} {'cur':<8} {'->':<2} {'new':<7} {'MEDLINE':<7} "
              f"{'publication types':<52} title")
        print("=" * 110)
        for r in rows:
            rec = fetched.get(r["pmid"]) or {}
            pts = rec.get("pubtypes") or []
            mi = bool(rec.get("medline_indexed", True))
            new, reason = target_tier(pts, mi)
            pts_s = ", ".join(pts)[:50] or "(none returned)"
            arrow = "->" if new != r["level_key"] else "=="
            line = (f"{r['pmid']:>9} {r['level_key']:<8} {arrow} "
                    f"{(new or 'PARKED'):<7} "
                    f"{str(mi):<7} {pts_s:<52} {(r['title'] or '')[:46]}")
            if new is None:
                parked.append((r, new, reason))
                print(line + f"\n{'':>12}[PARKED] {reason}")
                continue
            if r["level_key"] == "invitro":
                parked.append((r, new, reason))
                print(line + "   [PARKED - invitro, see docstring]")
                continue
            print(line)
            if new == r["level_key"]:
                unchanged.append(r)
            else:
                updates.append((new, r["pmid"], r["level_key"]))

        moves = Counter(f"{old}  ->  {new}" for new, _p, old in updates)
        print("\nDELTA SPLIT — tier changes by direction")
        for k, n in moves.most_common():
            print(f"    {n:3}   {k}")
        print(f"    {len(updates):3}   TOTAL changing")
        print(f"    {len(unchanged):3}   already consistent")
        print(f"    {len(parked):3}   parked (reported, untouched)")

        if not args.apply:
            print("\n[scoping] DRY RUN — re-run with --apply, then "
                  "python scripts/rescore_library.py --apply")
            return 0
        if not updates:
            print("\n[scoping] nothing to write")
            return 0

        pmids = [p for _n, p, _o in updates]
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
        print(f"\n[scoping] backed up {cur.rowcount} row(s) under run_id={RUN_ID}")
        print(f"[scoping] restore:\n"
              f"    UPDATE endo_papers_rag e SET level_key = b.level_key, "
              f"score = b.score\n"
              f"      FROM {BACKUP_TABLE} b\n"
              f"     WHERE b.run_id = '{RUN_ID}' AND b.pmid = e.pmid;")

        psycopg2.extras.execute_batch(cur, """
            UPDATE endo_papers_rag SET level_key = %s WHERE pmid = %s;
        """, [(n, p) for n, p, _o in updates], page_size=100)
        cur.execute("DELETE FROM query_cache;")
        purged = cur.rowcount
        conn.commit()
        print(f"[scoping] APPLIED — {len(updates)} level_key(s) rewritten; "
              f"purged {purged} cached answer(s)")
        print("[scoping] NEXT: python scripts/rescore_library.py --apply")
        return 0
    except Exception as e:
        conn.rollback()
        print(f"[scoping] FAILED: {e}")
        return 1
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
