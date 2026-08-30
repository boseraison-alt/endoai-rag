"""
WORKLIST 1.3 + 1.6: retier book records and retracted rows in the library.

Book records (StatPearls chapters, PubmedBookArticle) are narrative reference
texts; three sat at Level I scoring 67 because the provenance merge loop only
iterated PubmedArticle, so they got no pubtypes and kept the tier of whatever
search retrieved them. Their stored journal is EMPTY (esummary carries a book
title, not a journal), so detection must come from PubMed: this script efetches
every empty-journal row and looks for PubmedBookArticle.

Retracted rows (has_retraction = TRUE) are excluded from search, so there is no
clinician exposure — but the bibliography and admin views still show them
tiered as level1/level5, which misstates what they are. They move to the
terminal 'retracted' tier (LEVEL_SCORES 0, deliberately NOT in TIER_ORDER — in
this codebase, absence from TIER_ORDER is what "never rendered to Claude"
means).

Dry-run by default; --apply writes, after backing up the affected rows to
endo_papers_rag_tier_backup (the first tier migration had no backup and the
identity of its rows is unrecoverable — not again). Idempotent: rows already
migrated match nothing on a re-run.

Run scripts/rescore_library.py --apply afterwards.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from defusedxml import ElementTree as DET

from endo_ai import NCBI_EUTILS_BASE, _ncbi_params
from rag import get_conn

RUN_ID = "books_retracted_20260830"


def find_book_pmids(candidate_pmids):
    """Ask PubMed which of these records are PubmedBookArticle. Returns
    {pmid: book_title}."""
    books = {}
    for i in range(0, len(candidate_pmids), 200):
        chunk = candidate_pmids[i:i + 200]
        r = requests.get(f"{NCBI_EUTILS_BASE}/efetch.fcgi",
                         params=_ncbi_params({"db": "pubmed", "id": ",".join(chunk),
                                              "retmode": "xml"}),
                         timeout=60)
        r.raise_for_status()
        root = DET.fromstring(r.text)
        for book in root.iter("PubmedBookArticle"):
            pmid_el = book.find(".//BookDocument/PMID")
            if pmid_el is None or not pmid_el.text:
                continue
            title_el = book.find(".//BookDocument/Book/BookTitle")
            title = (title_el.text or "").strip() if title_el is not None else ""
            books[pmid_el.text.strip()] = title or "Reference text"
    return books


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = get_conn()
    cur = conn.cursor()
    try:
        # ── Books: candidates are rows with no journal ──
        cur.execute("""
            SELECT pmid FROM endo_papers_rag
             WHERE COALESCE(journal, '') = ''
               AND level_key IS DISTINCT FROM 'level5'
               AND NOT COALESCE(is_curated, FALSE);
        """)
        candidates = [r[0] for r in cur.fetchall()]
        print(f"empty-journal candidates checked against PubMed: {len(candidates)}")
        books = find_book_pmids([p for p in candidates if p.isdigit()])

        cur.execute("""
            SELECT pmid, level_key, score, LEFT(title, 55)
              FROM endo_papers_rag
             WHERE pmid = ANY(%s) ORDER BY score DESC;
        """, (list(books), ))
        book_rows = cur.fetchall()
        print(f"\nBOOK RECORDS -> level5 + journal backfilled: {len(book_rows)}")
        for pmid, lk, score, title in book_rows:
            print(f"   {pmid}  {lk:<8} {score:>5.1f}  [{books[pmid]}]  {title}")

        # ── Retracted rows ──
        cur.execute("""
            SELECT pmid, level_key, score, LEFT(title, 55)
              FROM endo_papers_rag
             WHERE has_retraction AND level_key IS DISTINCT FROM 'retracted'
             ORDER BY level_key, score DESC;
        """)
        retracted = cur.fetchall()
        print(f"\nRETRACTED -> 'retracted' terminal tier: {len(retracted)}")
        by_tier = {}
        for pmid, lk, score, title in retracted:
            by_tier[lk] = by_tier.get(lk, 0) + 1
            print(f"   {pmid}  {lk:<8} {score:>5.1f}  {title}")
        print(f"   split by source tier: {by_tier}")

        if not args.apply:
            print("\nDRY RUN. --apply to write, then scripts/rescore_library.py --apply")
            return

        # Backup before touching anything.
        affected = list(books) + [r[0] for r in retracted]
        cur.execute("""
            CREATE TABLE IF NOT EXISTS endo_papers_rag_tier_backup (
                run_id    TEXT,
                pmid      TEXT,
                level_key TEXT,
                score     REAL,
                journal   TEXT,
                backed_up TIMESTAMP DEFAULT NOW()
            );
        """)
        cur.execute("""
            INSERT INTO endo_papers_rag_tier_backup (run_id, pmid, level_key, score, journal)
            SELECT %s, pmid, level_key, score, journal FROM endo_papers_rag
             WHERE pmid = ANY(%s);
        """, (RUN_ID, affected))
        print(f"\nbacked up {cur.rowcount} row(s) under run_id={RUN_ID}")
        print(f"restore: UPDATE endo_papers_rag e SET level_key = b.level_key, "
              f"score = b.score, journal = b.journal FROM endo_papers_rag_tier_backup b "
              f"WHERE b.run_id = '{RUN_ID}' AND b.pmid = e.pmid;")

        for pmid, title in books.items():
            cur.execute("""
                UPDATE endo_papers_rag SET level_key = 'level5', journal = %s
                 WHERE pmid = %s;
            """, (title, pmid))
        cur.execute("""
            UPDATE endo_papers_rag SET level_key = 'retracted'
             WHERE has_retraction AND level_key IS DISTINCT FROM 'retracted';
        """)
        moved = cur.rowcount
        conn.commit()
        print(f"applied: {len(books)} book(s) -> level5, {moved} retracted row(s) -> terminal tier")
        print("NEXT: python scripts/rescore_library.py --apply")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
