"""Phase-0 / delta counter for the 2026-09-06 night batch.

Prints the three numbers the batch's Phase 0 pins (total rows in
endo_papers_rag, and the guideline / level1 / level2 tier counts), plus the
full tier split so a delta can be read off directly.

CITEABLE vs RAW matters here. The 2026-09-11 handover's "citeable guideline 55"
is a count under `COALESCE(quarantine_reason,'') = ''`, which is the filter
rag.py's three retrieval queries apply (rag.py:570, 626, 708). The raw count is
74. Printing only one of them is how a Phase-0 check gets read as a mismatch.

Usage:  python scripts/night_counts.py [label]
"""
import os
import sys

sys.path.insert(0, os.getcwd())

import rag  # noqa: E402

CITEABLE = "COALESCE(quarantine_reason, '') = ''"


def split(cur, where):
    cur.execute(
        "SELECT COALESCE(level_key, '<null>'), count(*) "
        "FROM endo_papers_rag WHERE %s GROUP BY 1" % where)
    return dict(cur.fetchall())


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else ""
    conn = rag.get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM endo_papers_rag")
        total = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM endo_papers_rag WHERE " + CITEABLE)
        total_cite = cur.fetchone()[0]
        raw = split(cur, "TRUE")
        cite = split(cur, CITEABLE)
    if label:
        print("== %s ==" % label)
    print("total endo_papers_rag: %d   (citeable %d)" % (total, total_cite))
    print("  %-22s %8s %10s" % ("tier", "raw", "citeable"))
    for k in sorted(set(raw) | set(cite), key=lambda k: -raw.get(k, 0)):
        print("  %-22s %8d %10d" % (k, raw.get(k, 0), cite.get(k, 0)))
    conn.close()


if __name__ == "__main__":
    main()
