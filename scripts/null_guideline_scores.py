"""A49 endgame — a guideline row carries NO score. Make the stragglers match.

THE INVARIANT THIS ESTABLISHES:

    no CITEABLE row at level_key='guideline' carries a non-NULL score

A guideline is not on the study-design ladder. It is a specialty's stated
position, ranked by authority and jurisdiction, and the score is computed by a
therapy-shaped scorer that gives a position statement no credit for a
comparison it never made or a follow-up it never had. A49 established this and
the 60 seed records all store NULL. Five rows never got the memo.

    AAE-PS-diagnosis    90.0   hand-set by ingest_aae_guidelines.py
    AAE-PS-vital-pulp   90.0   hand-set
    ESE-PS-VPT-2019     87.0   hand-set
    ESE-QG-2006         50.4   hand-set
    39578680            59.3   COMPUTED, and see below

The first four are the records the A2 audit KEPT because it verified they name
real documents. Verification settled whether the document exists; it never
touched the score, and nothing since has. So the score-as-authority defect A49
was built to remove stayed live on exactly the four rows kept because they are
citeable, rendering "Evidence Score: 90.0/100" against the Schwendicke Cochrane
review's 81.5 — no genuine paper in the library scores above 85.9.

THE FIFTH IS A DELIBERATE ADDITION TO THE BATCH'S LIST OF FOUR. PMID 39578680
is "Position Statement and Recommendations for Custom-Made Sport Mouthguards"
(Dent Traumatol 2025) — a real PubMed paper, banded to the guideline tier, with
a legitimately COMPUTED 59.3 and no seed identity. An earlier report of mine
set it aside as "different: real accession, computed score". That distinction
does not survive the invariant above. A49's principle is about the TIER, not
about how the number was produced: a row at level_key='guideline' carries no
score, and a computed score on a guideline row is the same category error
arriving by a different route. Leaving it would also make the test-pin the
batch asks for impossible to write.

QUARANTINED ROWS ARE DELIBERATELY EXCLUDED. The twelve A2 rows keep their
scores because `quarantine_unverified_guidelines.py` promises that a single
`--restore` puts them back exactly as they were. Nulling their scores would
break that contract to satisfy an invariant about rows that cannot be cited
anyway. The invariant is therefore about CITEABLE rows, which is what it is
actually for.

AND ESE-PS-VPT-2019 IS A DUPLICATE. PMID 30664240 is already in the library
from the verified manifest, with the verified title, a confirmed accession, a
NULL score and its status recorded. The slug row is a second, unverified copy
of a document already present in verified form, so it is quarantined
`duplicate_of:30664240`. Not renamed — choosing a title is inventing
bibliographic data. Not deleted — RB decides removal.

Usage
  python scripts/null_guideline_scores.py            # DRY RUN
  python scripts/null_guideline_scores.py --apply
  python scripts/null_guideline_scores.py --restore  # undo both changes
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.getcwd())

import psycopg2                       # noqa: E402
import psycopg2.extras                # noqa: E402
from rag import DATABASE_URL          # noqa: E402

# The five, with why each is here. The reason string is not decoration: a
# future reader must be able to act on this without finding the report.
NULL_SCORE = {
    "AAE-PS-diagnosis":  "hand-set 90.0 by ingest_aae_guidelines.py; A2-verified "
                         "as AAE-DIAGNOSIS-2009, which does not make the number real",
    "AAE-PS-vital-pulp": "hand-set 90.0; A2-verified as AAE-VPT-2021",
    "ESE-PS-VPT-2019":   "hand-set 87.0; also a duplicate, see QUARANTINE below",
    "ESE-QG-2006":       "hand-set 50.4; the id is in the manifest (superseded)",
    "39578680":          "COMPUTED 59.3 on a real Dent Traumatol position "
                         "statement. A guideline row carries no score whatever "
                         "produced it — the tier is the category error, not the "
                         "provenance of the number",
}

QUARANTINE_DUPLICATE = {
    "ESE-PS-VPT-2019": "duplicate_of:30664240",
}

RUN_ID = "null_guideline_scores_" + datetime.now().strftime("%Y%m%dT%H%M%S")
SCORE_BACKUP = "endo_papers_rag_score_backup"
QUAR_BACKUP = "endo_papers_rag_quarantine_backup"


def connect():
    if not DATABASE_URL:
        print("FATAL: DATABASE_URL not set")
        sys.exit(2)
    return psycopg2.connect(DATABASE_URL)


def guideline_score_census(cur):
    """Citeable guideline rows split by whether they carry a score.

    This IS the invariant, measured. The delta between two of these is what
    the dry run reports.
    """
    cur.execute("""
        SELECT level_key,
               COUNT(*) AS n,
               COUNT(score) AS n_scored,
               MIN(score) AS lo,
               MAX(score) AS hi
        FROM endo_papers_rag
        WHERE COALESCE(quarantine_reason, '') = ''
        GROUP BY level_key
        ORDER BY level_key
    """)
    return {r["level_key"]: dict(r) for r in cur.fetchall()}


def state(cur):
    cur.execute("""
        SELECT pmid, title, year, level_key, score, impact_factor,
               COALESCE(quarantine_reason, '') AS quarantine_reason
        FROM endo_papers_rag
        WHERE pmid = ANY(%s)
        ORDER BY pmid
    """, (sorted(NULL_SCORE),))
    return {r["pmid"]: dict(r) for r in cur.fetchall()}


def print_census_delta(before, after):
    keys = sorted(set(before) | set(after))
    print("\n  %-16s %8s %8s %8s   %s" % ("tier", "rows", "scored", "scored'", "range"))
    for k in keys:
        b = before.get(k, {"n": 0, "n_scored": 0})
        a = after.get(k, {"n": 0, "n_scored": 0})
        rng = ("%.1f-%.1f" % (a["lo"], a["hi"])
               if a.get("lo") is not None else "-")
        mark = "   <-- CHANGED" if b["n_scored"] != a["n_scored"] else ""
        print("  %-16s %8d %8d %8d   %-12s%s"
              % (k, a["n"], b["n_scored"], a["n_scored"], rng, mark))
        if b["n"] != a["n"]:
            print("      row count moved %d -> %d" % (b["n"], a["n"]))


def do_backup(cur):
    cur.execute("""
        INSERT INTO %s (pmid, score, sample_size, run_id, backed_up_at)
        SELECT pmid, score, sample_size, %%s, now()
        FROM endo_papers_rag
        WHERE pmid = ANY(%%s) AND score IS NOT NULL
    """ % SCORE_BACKUP, (RUN_ID, sorted(NULL_SCORE)))
    n_score = cur.rowcount
    # ON CONFLICT DO NOTHING, and it is not cosmetic. `pmid` is the primary
    # key of the quarantine backup, so an apply -> restore -> apply round trip
    # raised UniqueViolation and aborted the whole transaction. Found by doing
    # exactly that round trip to mutation-check the invariant test.
    #
    # DO NOTHING rather than an upsert: the row records the state BEFORE the
    # first quarantine, and after a restore that state is the same ('' — not
    # quarantined). Overwriting it would be replacing an original observation
    # with a re-derived one, which is the weaker of the two.
    cur.execute("""
        INSERT INTO %s (pmid, title, year, level_key, score, impact_factor,
                        prior_quarantine_reason, backed_up_at)
        SELECT pmid, title, year, level_key, score, impact_factor,
               COALESCE(quarantine_reason, ''), now()
        FROM endo_papers_rag
        WHERE pmid = ANY(%%s)
        ON CONFLICT (pmid) DO NOTHING
    """ % QUAR_BACKUP, (sorted(QUARANTINE_DUPLICATE),))
    return n_score, cur.rowcount


def main():
    apply_ = "--apply" in sys.argv
    restore = "--restore" in sys.argv
    conn = connect()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    print("=" * 78)
    print("A49 ENDGAME — NULL THE SCORES ON CITEABLE GUIDELINE ROWS")
    print("=" * 78)
    print("mode: %s\n" % ("RESTORE" if restore else
                          "APPLY" if apply_ else "DRY RUN (nothing written)"))

    if restore:
        cur.execute("""
            UPDATE endo_papers_rag t
            SET score = b.score
            FROM (SELECT DISTINCT ON (pmid) pmid, score
                  FROM %s WHERE run_id LIKE 'null_guideline_scores_%%'
                  ORDER BY pmid, backed_up_at DESC) b
            WHERE t.pmid = b.pmid
        """ % SCORE_BACKUP)
        print("  restored %d score(s)" % cur.rowcount)
        cur.execute("""
            UPDATE endo_papers_rag SET quarantine_reason = ''
            WHERE pmid = ANY(%s) AND quarantine_reason LIKE 'duplicate_of:%%'
        """, (sorted(QUARANTINE_DUPLICATE),))
        print("  un-quarantined %d row(s)" % cur.rowcount)
        conn.commit()
        conn.close()
        return 0

    before_census = guideline_score_census(cur)
    before = state(cur)

    print("  THE ROWS")
    missing = [p for p in NULL_SCORE if p not in before]
    for pmid in sorted(NULL_SCORE):
        r = before.get(pmid)
        if r is None:
            print("    %-20s NOT FOUND" % pmid)
            continue
        print("    %-20s tier=%-10s score=%-7s q=%-6s %s"
              % (pmid, r["level_key"], r["score"],
                 r["quarantine_reason"][:6] or "-", (r["title"] or "")[:34]))
        print("        why: %s" % NULL_SCORE[pmid])
    if missing:
        print("\n  ABORT: %d row(s) named here are not in the table: %s"
              % (len(missing), missing))
        conn.close()
        return 2

    # Guard: never null a score on a row that is not at the guideline tier.
    # The whole justification is "a guideline row carries no score"; applied to
    # any other tier it would be deleting evidence.
    wrong_tier = [p for p, r in before.items() if r["level_key"] != "guideline"]
    if wrong_tier:
        print("\n  ABORT: not at level_key='guideline': %s" % wrong_tier)
        conn.close()
        return 2

    do_backup(cur)
    cur.execute("""
        UPDATE endo_papers_rag SET score = NULL
        WHERE pmid = ANY(%s) AND score IS NOT NULL
    """, (sorted(NULL_SCORE),))
    n_nulled = cur.rowcount
    for pmid, reason in QUARANTINE_DUPLICATE.items():
        cur.execute("""
            UPDATE endo_papers_rag SET quarantine_reason = %s
            WHERE pmid = %s AND COALESCE(quarantine_reason, '') = ''
        """, (reason, pmid))

    after_census = guideline_score_census(cur)
    after = state(cur)

    print("\n  DELTA BY TIER (citeable rows only; 'scored' = non-NULL score)")
    print_census_delta(before_census, after_census)

    print("\n  AFTER")
    for pmid in sorted(NULL_SCORE):
        r = after[pmid]
        print("    %-20s score=%-7s q=%s"
              % (pmid, r["score"], r["quarantine_reason"] or "-"))

    g = after_census.get("guideline", {})
    print("\n  INVARIANT: citeable guideline rows carrying a score: %d"
          % g.get("n_scored", 0))
    print("  scores nulled: %d   quarantined as duplicate: %d"
          % (n_nulled, len(QUARANTINE_DUPLICATE)))

    if apply_:
        conn.commit()
        print("\n  COMMITTED. run_id=%s" % RUN_ID)
        print("  undo: python scripts/null_guideline_scores.py --restore")
    else:
        conn.rollback()
        print("\n  ROLLED BACK — dry run. Re-run with --apply to write.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
