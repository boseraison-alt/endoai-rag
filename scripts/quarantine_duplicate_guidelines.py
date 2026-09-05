"""Item 3b — a slug-id guideline row that duplicates a verified PMID row.

THE PROBLEM. 31 citeable rows at `level_key='guideline'` carry a slug id
(`ESE-QG-2006`, `AAE-VPT-2021`, …) rather than a PMID. The synthesis prompt
requires `[[PMID:nnnnnnn]]`, so on the library route those rows **cannot be
cited in the required format at all**.

ITEM 3a SPLIT THEM, and the answer is much narrower than it looked:

    31  slug rows, citeable
     1  the seed manifest carries a CONFIRMED PMID for that document
    30  it does not, and they stay — see below

Of the 30: **18 are `confirmed` documents with no PMID in the seed at all**
(AAE position statements, SDCEP, NICE — real documents PubMed does not index),
**10 are `unconfirmed_pmid`** and must never be matched by PMID because that
accession is precisely the field nobody has verified, and **2 have no seed
record**. None can be re-keyed without inventing bibliographic data.

THE ONE THAT CAN: `ESE-QG-2006` → PMID 17180780. And the target ALREADY EXISTS
in the library, unquarantined, at `level_key='guideline'`, with
`guideline_id='ESE-QG-2006'`, org ESE, status superseded, confidence confirmed
and a NULL score — the verified copy, ingested from the manifest.

So this is not a re-key. Re-keying would create a second row for 17180780,
which is the duplicate this repo already made once with 30664240. The slug row
is an unverified copy of a document already present in verified form, and it is
quarantined `duplicate_of:17180780` — the same treatment ESE-PS-VPT-2019 got.

Not renamed: its title differs in capitalisation and journal formatting from
the verified row, and choosing between them is inventing bibliographic data.
Not deleted: RB decides removal.

Usage
  python scripts/quarantine_duplicate_guidelines.py            # DRY RUN
  python scripts/quarantine_duplicate_guidelines.py --apply
  python scripts/quarantine_duplicate_guidelines.py --restore
"""
import os
import sys

sys.path.insert(0, os.getcwd())

import psycopg2                       # noqa: E402
import psycopg2.extras                # noqa: E402
from rag import DATABASE_URL          # noqa: E402

# slug -> the verified PMID row it duplicates
DUPLICATES = {
    "ESE-QG-2006": "17180780",
}

BACKUP = "endo_papers_rag_quarantine_backup"


def connect():
    if not DATABASE_URL:
        print("FATAL: DATABASE_URL not set")
        sys.exit(2)
    return psycopg2.connect(DATABASE_URL)


def census(cur):
    cur.execute("""
        SELECT COUNT(*) AS citeable,
               COUNT(*) FILTER (WHERE pmid ~ '^[0-9]+$') AS numeric_pmid,
               COUNT(*) FILTER (WHERE pmid !~ '^[0-9]+$') AS slug
        FROM endo_papers_rag
        WHERE level_key = 'guideline' AND COALESCE(quarantine_reason, '') = ''
    """)
    return dict(cur.fetchone())


def main():
    apply_ = "--apply" in sys.argv
    restore = "--restore" in sys.argv
    conn = connect()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    print("=" * 78)
    print("ITEM 3b — QUARANTINE A SLUG ROW THAT DUPLICATES A VERIFIED PMID ROW")
    print("=" * 78)
    print("mode: %s\n" % ("RESTORE" if restore else
                          "APPLY" if apply_ else "DRY RUN (nothing written)"))

    if restore:
        cur.execute("""
            UPDATE endo_papers_rag SET quarantine_reason = ''
            WHERE pmid = ANY(%s) AND quarantine_reason LIKE 'duplicate_of:%%'
        """, (sorted(DUPLICATES),))
        print("  un-quarantined %d row(s)" % cur.rowcount)
        conn.commit()
        conn.close()
        return 0

    before = census(cur)

    # THE SAFETY CHECK, and it is the whole reason this is safe: the row is
    # only redundant BECAUSE the verified one is present and citeable. If the
    # survivor were missing or quarantined, this would be removing the document
    # from the library rather than deduplicating it.
    for slug, pmid in sorted(DUPLICATES.items()):
        cur.execute("""SELECT pmid, title, level_key, score, guideline_id,
                              guideline_confidence,
                              COALESCE(quarantine_reason,'') AS q
                       FROM endo_papers_rag WHERE pmid IN (%s, %s)""",
                    (slug, pmid))
        rows = {r["pmid"]: r for r in cur.fetchall()}
        if slug not in rows:
            print("  ABORT: %s is not in the table" % slug)
            conn.close()
            return 2
        surv = rows.get(pmid)
        if surv is None:
            print("  ABORT: the survivor %s is NOT in the library — this would "
                  "remove the document, not deduplicate it" % pmid)
            conn.close()
            return 2
        if surv["q"]:
            print("  ABORT: the survivor %s is itself quarantined (%s)"
                  % (pmid, surv["q"]))
            conn.close()
            return 2
        if surv["guideline_confidence"] != "confirmed":
            print("  ABORT: the survivor %s is not a confirmed record" % pmid)
            conn.close()
            return 2
        print("  %-16s -> quarantine as duplicate_of:%s" % (slug, pmid))
        print("      slug row : %s" % (rows[slug]["title"] or "")[:66])
        print("      survivor : %s" % (surv["title"] or "")[:66])
        print("      survivor gid=%s conf=%s score=%s"
              % (surv["guideline_id"], surv["guideline_confidence"],
                 surv["score"]))

    cur.execute("""
        INSERT INTO %s (pmid, title, year, level_key, score, impact_factor,
                        prior_quarantine_reason, backed_up_at)
        SELECT pmid, title, year, level_key, score, impact_factor,
               COALESCE(quarantine_reason, ''), now()
        FROM endo_papers_rag WHERE pmid = ANY(%%s)
        ON CONFLICT (pmid) DO NOTHING
    """ % BACKUP, (sorted(DUPLICATES),))

    for slug, pmid in DUPLICATES.items():
        cur.execute("""UPDATE endo_papers_rag SET quarantine_reason = %s
                       WHERE pmid = %s AND COALESCE(quarantine_reason,'') = ''""",
                    ("duplicate_of:" + pmid, slug))

    after = census(cur)
    print()
    print("  DELTA — citeable guideline rows")
    print("    %-16s %8s %8s" % ("", "before", "after"))
    for k in ("citeable", "numeric_pmid", "slug"):
        mark = "   <-- CHANGED" if before[k] != after[k] else ""
        print("    %-16s %8d %8d%s" % (k, before[k], after[k], mark))

    if apply_:
        conn.commit()
        print("\n  COMMITTED.  undo: --restore")
    else:
        conn.rollback()
        print("\n  ROLLED BACK — dry run. Re-run with --apply to write.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
