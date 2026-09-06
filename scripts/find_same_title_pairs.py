"""Item E.4 — how general is the co-publication problem?

`42018467`, `42017497` and `42014635` are one document with three accessions.
The manifest's `alt_pmid` field catches the cases somebody has already noticed.
This asks the corpus itself: how many pairs of rows share a normalised title
and a year but carry different PMIDs?

REPORT ONLY. Nothing is merged. Two rows with the same title and year can be a
co-publication, an erratum, a reprint, a conference abstract and its full
paper, or two genuinely different papers that happen to share a generic title
("Editorial", "Letter to the Editor"). Deciding which needs eyes, and merging
on a normalised string would silently destroy real rows.

    python scripts/find_same_title_pairs.py
"""
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import rag  # noqa: E402

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")
# Titles too generic for a match to mean anything. Named rather than filtered
# by length, so the exclusion is auditable.
GENERIC = {"editorial", "letter to the editor", "erratum", "correction",
           "introduction", "preface", "abstracts", "contents", "corrigendum"}


def norm(t):
    s = _PUNCT.sub(" ", (t or "").lower())
    return _WS.sub(" ", s).strip()


def main():
    conn = rag.get_conn()
    cur = conn.cursor()
    cur.execute("""SELECT pmid, title, year, journal, level_key,
                          COALESCE(guideline_id,'')
                   FROM endo_papers_rag
                   WHERE COALESCE(title,'') <> ''""")
    rows = cur.fetchall()
    print("=" * 78)
    print("ITEM E.4 — SAME NORMALISED TITLE + SAME YEAR, DIFFERENT PMID")
    print("=" * 78)
    print("  rows with a title            %d" % len(rows))

    buckets = defaultdict(list)
    for pmid, title, year, journal, lk, gid in rows:
        n = norm(title)
        if not n or n in GENERIC:
            continue
        buckets[(n, year)].append((pmid, title, journal, lk, gid))

    pairs = {k: v for k, v in buckets.items() if len({p for p, *_ in v}) > 1}
    n_rows = sum(len(v) for v in pairs.values())
    print("  distinct (title, year) groups with >1 PMID   %d" % len(pairs))
    print("  rows involved                                %d" % n_rows)
    print()

    if len(pairs) <= 30:
        print("  EVERY GROUP (<=30, so all are printed)")
        for (n, year), members in sorted(pairs.items(),
                                         key=lambda kv: -len(kv[1])):
            print("  --- %s (%s), %d rows" % (n[:64], year, len(members)))
            for pmid, title, journal, lk, gid in members:
                print("      %-10s %-11s %-34s %s"
                      % (pmid, lk or "-", (journal or "-")[:34],
                         ("gid=" + gid) if gid else ""))
    else:
        print("  MORE THAN 30 GROUPS — count only, per the item.")

    same_journal = sum(
        1 for members in pairs.values()
        if len({(j or "").strip().lower() for _p, _t, j, _l, _g in members}) == 1)
    print()
    print("  groups whose rows share a JOURNAL too  %d" % same_journal)
    print("    (a co-publication appears in DIFFERENT journals; same-journal")
    print("     duplicates are more likely reprints, errata or versions)")
    print()
    print("  NOT MERGED. Reported for a human, per the item.")
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
