"""A49/A2 — quarantine the guideline records that name no verifiable document.

Sixteen guideline records were hardcoded into the library by
`ingest_aae_guidelines.py`. Matching them against the 60-entry manifest in
`data/guidelines_seed.json` by organisation + subject + year — never by slug,
because the slug is the thing under suspicion — the A2 audit found:

     4  verified against a real document
     6  WRONG YEAR: the organisation publishes on that subject, but there is
        no edition in the year the record claims
     6  NO SUCH DOCUMENT on that subject anywhere in the manifest

and 103 stored answers cite one of them.

These are fabricated or misdated sources sitting in a library that answers
clinical questions, at score 90.0 — which outranks 100% of the 3,192 real
evidence rows, because no genuine paper in the library scores above 85.9.

QUARANTINE, NOT DELETION, and the distinction is the whole design. Nothing is
removed: the rows keep their text, their scores and their identifiers, and a
single `--restore` puts them back. RB decides removal; this script only makes
them unciteable in the meantime. `quarantine_reason` carries the REASON rather
than a boolean, because the two failure modes have different remedies — a
wrong-year record has a real document behind it and can be re-pointed, while a
no-such-document record cannot.

WHAT THIS DOES NOT TOUCH
  - the 4 verified records, which keep working exactly as before
  - the 5 genuinely PubMed-indexed guidelines also at level_key='guideline'
  - `ingest_aae_guidelines.py`, deliberately out of scope for this item: it is
    the thing that WROTE these rows and rewriting it is A49 phase 2. Quarantine
    first, so the corpus is safe while that is decided.

Usage
  python scripts/quarantine_unverified_guidelines.py            # DRY RUN
  python scripts/quarantine_unverified_guidelines.py --apply
  python scripts/quarantine_unverified_guidelines.py --restore  # undo
"""
import os
import sys

sys.path.insert(0, os.getcwd())

import psycopg2                       # noqa: E402
import psycopg2.extras                # noqa: E402
from rag import DATABASE_URL          # noqa: E402

WRONG_YEAR = "wrong_year"
NO_SUCH_DOCUMENT = "no_such_document"

# The A2 verdicts, verbatim, one line per record. The reason string is what
# lands in the database, so it names the audit, the failure mode and the real
# document where one exists — a future reader must be able to act on this row
# without finding the report.
QUARANTINE = {
    "AAE-PS-antibiotics": (
        WRONG_YEAR,
        "A2: stored as 2023; the real document is AAE-ANTIBIOTICS-2017 "
        "(status under_review). No 2023 edition exists."),
    "AAE-PS-cbct": (
        WRONG_YEAR,
        "A2: stored as 2021; the real AAE/AAOMR CBCT statements are 2015 "
        "(superseded) and 2025 (current). No 2021 edition exists."),
    "AAE-PS-microscope": (
        WRONG_YEAR,
        "A2: stored as 2012; the real document is dated 2020."),
    "AAE-PS-regenerative": (
        WRONG_YEAR,
        "A2: stored as 2021; the real documents are 2025 and 2013."),
    "AAE-PS-trauma": (
        WRONG_YEAR,
        "A2: stored as 2020; the real document is dated 2026."),
    "ESE-QG-2023": (
        WRONG_YEAR,
        "A2: there is no 2023 ESE Quality Guideline. The 2023 document is "
        "ESE-S3-2023, a differently-named S3-level guideline, PMID 37772327, "
        "which is already in the library as a real record."),

    "AAE-PS-cracked-tooth": (
        NO_SUCH_DOCUMENT,
        "A2: no AAE document on this subject in the 60-entry manifest."),
    "AAE-PS-implant-v-endo": (
        NO_SUCH_DOCUMENT,
        "A2: no AAE document on this subject in the 60-entry manifest."),
    "AAE-PS-isolation": (
        NO_SUCH_DOCUMENT,
        "A2: no AAE document on this subject in the 60-entry manifest."),
    "AAE-PS-obturation": (
        NO_SUCH_DOCUMENT,
        "A2: no AAE document on this subject in the 60-entry manifest."),
    "AAE-PS-retreatment": (
        NO_SUCH_DOCUMENT,
        "A2: no AAE document on this subject in the 60-entry manifest."),
    "AAE-PS-safety": (
        NO_SUCH_DOCUMENT,
        "A2: no AAE document on this subject in the 60-entry manifest."),
}

# The four A2 verified as real. Listed so the script can ASSERT they are
# untouched rather than leaving it to be inferred from the absence of a line.
VERIFIED_KEEP = {
    "AAE-PS-diagnosis":  "matches AAE-DIAGNOSIS-2009 (current)",
    "AAE-PS-vital-pulp": "matches AAE-VPT-2021 (current)",
    "ESE-QG-2006":       "id is in the manifest (superseded)",
    # Verified as a real document, but see report_title_mismatch(): the stored
    # TITLE names a third document. Kept citeable per the batch instruction
    # that the four verified records keep working; the mismatch is reported,
    # not silently corrected, because inventing a corrected title would be the
    # same class of error as the records being quarantined here.
    "ESE-PS-VPT-2019":   "matches ESE-DEEPCARIES-2019 (title mismatch, see report)",
}

BACKUP_TABLE = "endo_papers_rag_quarantine_backup"


def connect():
    if not DATABASE_URL:
        print("FATAL: DATABASE_URL not set")
        sys.exit(2)
    return psycopg2.connect(DATABASE_URL)


def fetch_state(cur):
    cur.execute("""
        SELECT pmid, title, year, level_key, score, impact_factor,
               COALESCE(quarantine_reason, '') AS quarantine_reason
        FROM endo_papers_rag
        WHERE pmid = ANY(%s)
        ORDER BY pmid
    """, (sorted(set(QUARANTINE) | set(VERIFIED_KEEP)),))
    return {r["pmid"]: dict(r) for r in cur.fetchall()}


def tier_census(cur):
    """Citeable rows per tier. The delta between two of these is what the dry
    run reports — a count of rows that will stop being reachable, split by the
    tier they sit in, so the blast radius is visible before anything is written.
    """
    cur.execute("""
        SELECT level_key, COUNT(*) AS n
        FROM endo_papers_rag
        WHERE COALESCE(quarantine_reason, '') = ''
          AND NOT COALESCE(has_retraction, FALSE)
          AND title NOT ILIKE 'WITHDRAWN:%%'
          AND COALESCE(superseded_by, '') = ''
        GROUP BY level_key
        ORDER BY level_key
    """)
    return {r["level_key"]: r["n"] for r in cur.fetchall()}


def report_title_mismatch(state):
    """ESE-PS-VPT-2019 resolves to a real document under the wrong title.

    Reported every run, never auto-corrected. A2 matched it to
    ESE-DEEPCARIES-2019, but the stored title is "ESE Position Statement:
    Outcome of Primary Root Canal Treatment", which is neither vital pulp
    therapy nor deep caries — the record disagrees with its own slug. A
    clinician following that citation reads one document's title over another
    document's content, which is arguably worse than a fabricated slug because
    it looks right.

    It is NOT quarantined: the batch instruction is that the four verified
    records keep working, and the document behind it is real. It is NOT
    retitled either, because choosing a replacement title would be inventing
    bibliographic data, which is the exact failure being cleaned up here.
    """
    row = state.get("ESE-PS-VPT-2019")
    if not row:
        return
    print()
    print("  FOUND NOT FIXED — ESE-PS-VPT-2019 title mismatch")
    print("    stored title : %s" % row["title"])
    print("    A2 match     : ESE-DEEPCARIES-2019")
    print("    the stored title names a THIRD document. Kept citeable (it is "
          "one of the\n    four verified); not retitled, because choosing a "
          "replacement title would be\n    inventing bibliographic data. "
          "Needs RB.")


def main():
    apply_ = "--apply" in sys.argv
    restore = "--restore" in sys.argv
    if apply_ and restore:
        print("FATAL: --apply and --restore are mutually exclusive")
        return 2

    conn = connect()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    before_state = fetch_state(cur)
    before_census = tier_census(cur)

    missing = sorted(set(QUARANTINE) - set(before_state))
    if missing:
        print("FATAL: %d record(s) named for quarantine are not in the "
              "library: %s" % (len(missing), missing))
        print("Refusing to run: the audit and the library disagree about what "
              "exists.")
        return 2

    mode = "RESTORE" if restore else ("APPLY" if apply_ else "DRY RUN")
    print("=" * 74)
    print("A49/A2 GUIDELINE QUARANTINE  —  %s" % mode)
    print("=" * 74)

    print("\n  TO QUARANTINE (%d)" % len(QUARANTINE))
    by_reason = {}
    for slug, (kind, why) in sorted(QUARANTINE.items()):
        by_reason.setdefault(kind, []).append(slug)
        row = before_state[slug]
        state = "already quarantined" if row["quarantine_reason"] else "citeable"
        print("    %-24s %-12s score=%-6s IF=%-5s  [%s]"
              % (slug, kind, row["score"], row["impact_factor"], state))
    for kind, slugs in sorted(by_reason.items()):
        print("      %s: %d" % (kind, len(slugs)))

    print("\n  KEEPING CITEABLE — A2 verified (%d)" % len(VERIFIED_KEEP))
    for slug, why in sorted(VERIFIED_KEEP.items()):
        row = before_state.get(slug)
        print("    %-24s score=%-6s  %s"
              % (slug, row["score"] if row else "?", why))

    if not (apply_ or restore):
        # Dry run: compute the delta by doing the write inside a transaction
        # we then roll back, so what is reported is what Postgres would
        # actually do rather than an arithmetic prediction of it.
        cur.execute("""
            UPDATE endo_papers_rag SET quarantine_reason = %s
            WHERE pmid = ANY(%s)
        """, ("dry-run", sorted(QUARANTINE)))
        after_census = tier_census(cur)
        conn.rollback()
    elif restore:
        cur.execute("""
            UPDATE endo_papers_rag SET quarantine_reason = ''
            WHERE pmid = ANY(%s)
        """, (sorted(QUARANTINE),))
        after_census = tier_census(cur)
        conn.commit()
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS %s (
                pmid TEXT PRIMARY KEY,
                title TEXT, year INTEGER, level_key TEXT,
                score DOUBLE PRECISION, impact_factor DOUBLE PRECISION,
                prior_quarantine_reason TEXT,
                backed_up_at TIMESTAMP DEFAULT NOW()
            );
        """ % BACKUP_TABLE)
        for slug in sorted(QUARANTINE):
            r = before_state[slug]
            cur.execute("""
                INSERT INTO %s (pmid, title, year, level_key, score,
                                impact_factor, prior_quarantine_reason)
                VALUES (%%s, %%s, %%s, %%s, %%s, %%s, %%s)
                ON CONFLICT (pmid) DO NOTHING
            """ % BACKUP_TABLE,
                (r["pmid"], r["title"], r["year"], r["level_key"], r["score"],
                 r["impact_factor"], r["quarantine_reason"]))
        for slug, (kind, why) in sorted(QUARANTINE.items()):
            cur.execute("""
                UPDATE endo_papers_rag SET quarantine_reason = %s
                WHERE pmid = %s
            """, ("%s: %s" % (kind, why), slug))
        after_census = tier_census(cur)
        conn.commit()

    print("\n  DELTA — CITEABLE ROWS PER TIER")
    print("    %-16s %8s %8s %8s" % ("tier", "before", "after", "delta"))
    for tier in sorted(set(before_census) | set(after_census)):
        b = before_census.get(tier, 0)
        a = after_census.get(tier, 0)
        mark = "" if b == a else "   <-- changed"
        print("    %-16s %8d %8d %+8d%s" % (tier, b, a, a - b, mark))
    tb, ta = sum(before_census.values()), sum(after_census.values())
    print("    %-16s %8d %8d %+8d" % ("TOTAL", tb, ta, ta - tb))

    # The check that matters: nothing outside 'guideline' may move.
    moved = [t for t in set(before_census) | set(after_census)
             if before_census.get(t, 0) != after_census.get(t, 0)
             and t != "guideline"]
    if moved:
        print("\n  *** UNEXPECTED: tiers other than 'guideline' changed: %s"
              % moved)
        print("  *** This is additive to nothing. Investigate before applying.")
        if apply_:
            return 1

    report_title_mismatch(before_state)

    if not (apply_ or restore):
        print("\n  DRY RUN — nothing written. Re-run with --apply.")
    else:
        print("\n  %s COMMITTED." % mode)
        if apply_:
            print("  Before-state saved to %s. Undo: --restore" % BACKUP_TABLE)

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
