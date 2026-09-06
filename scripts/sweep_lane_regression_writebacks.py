"""Item B hygiene — rows the lane regression wrote into the library.

The guideline lane has been selecting the wrong concept group since d38be9d
(2026-09-05 16:30:38 -0500). Every live run since then has had
`rag.learn_from_live_results` write what that lane returned back into the
library. So the regression did not only degrade answers as they were served —
it deposited rows.

This lists every row added since that commit, applies the SAME off-domain
judgement used in the precision measurement, and quarantines the off-domain
ones reversibly. Nothing is deleted: `quarantine_reason` is the undo.

Rule 34 first: the input is counted before any zero is reported. If nothing was
written back at all in the window, the sweep's zero means "no live traffic",
not "no contamination", and those are different findings.

    python scripts/sweep_lane_regression_writebacks.py            # dry run
    python scripts/sweep_lane_regression_writebacks.py --apply
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import rag  # noqa: E402
sys.path.insert(0, str(ROOT / "scripts"))
from measure_guideline_lane_precision import judge_off_domain  # noqa: E402

REGRESSION_HASH = "d38be9d"
# The commit's own timestamp, in the column's frame. `added_at` is
# `timestamp without time zone`; the range check below prints the window's
# endpoints so the frame is visible rather than assumed.
SINCE = "2026-09-05 21:30:38"          # 16:30:38 -0500 as UTC
QUARANTINE = ("off-domain guideline admitted by lane regression %s"
              % REGRESSION_HASH)


def stored_answers():
    out = []
    conn = rag.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, answer, papers FROM query_cache")
    for r in cur.fetchall():
        out.append(("query_cache#%s" % r[0],
                    (r[1] or "") + "\n" + json.dumps(r[2] or {})))
    cur.close()
    conn.close()
    for pat in ("answers/*.txt", "eval/logs/case_answers/*.md"):
        for p in sorted(Path(".").glob(pat)):
            try:
                out.append((str(p), p.read_text(encoding="utf-8",
                                                errors="replace")))
            except Exception:
                pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = rag.get_conn()
    cur = conn.cursor()

    print("=" * 78)
    print("ITEM B HYGIENE — write-backs since %s" % REGRESSION_HASH)
    print("=" * 78)

    # ── the input, measured before any zero ──
    cur.execute("SELECT min(added_at), max(added_at), count(*) "
                "FROM endo_papers_rag WHERE added_at IS NOT NULL")
    lo, hi, n_dated = cur.fetchone()
    print("  rows carrying an added_at            %d" % n_dated)
    print("  added_at range                       %s .. %s" % (lo, hi))
    print("  window start (regression commit)     %s" % SINCE)

    cur.execute("SELECT count(*) FROM endo_papers_rag WHERE added_at >= %s",
                (SINCE,))
    n_window_all = cur.fetchone()[0]
    print("  rows added in the window (all)       %d" % n_window_all)

    # TONIGHT'S INGEST IS NOT A WRITE-BACK, and the first version of this
    # script counted it as one. `scripts/ingest_guidelines_seed.py` inserted 30
    # manifest records at 05:02:24, every one carrying a `guideline_id`, and
    # the sweep judged them with a detector built for LIVE PubMed results.
    # It convicted two:
    #
    #   AAOP-GUIDELINES-2023  American Academy of Orofacial Pain guidelines.
    #                         Orofacial pain IS head-and-neck medicine.
    #   16702591              Woo 2006, bisphosphonates and osteonecrosis of
    #                         the JAWS.
    #
    # Both are in-domain, and both were convicted for the same reason: a
    # manifest record that PubMed does not index is stored as a POINTER
    # (org, title, year, status, URL) with a synthetic journal string like
    # "AAOP guideline" and no abstract at all. The judge's second half asks
    # what the abstract says; on a pointer there is nothing to read, so every
    # pointer fails it. Quarantining those two would have removed two real
    # guidelines from the library to clean up a regression that never touched
    # them.
    #
    # So the sweep is scoped to what it is actually about: rows the LIVE PATH
    # wrote back, which carry no guideline_id.
    cur.execute("""SELECT pmid, journal, title, level_key, added_at,
                          COALESCE(quarantine_reason,'')
                   FROM endo_papers_rag
                   WHERE added_at >= %s
                     AND COALESCE(guideline_id,'') = ''
                   ORDER BY added_at""", (SINCE,))
    rows = cur.fetchall()
    print("  of those, from tonight's ingest      %d" % (n_window_all - len(rows)))
    print("  LIVE WRITE-BACKS in the window       %d" % len(rows))
    if not rows:
        print()
        print("  ZERO ROWS IN THE WINDOW. That is a statement about live")
        print("  traffic, not about contamination: nothing has been written")
        print("  back since the regression shipped, so the lane deposited")
        print("  nothing to clean up. The degradation was to answers served,")
        print("  which this sweep cannot reach.")

    guideline_rows = [r for r in rows if r[3] == "guideline"]
    print("  of those, banded 'guideline'         %d" % len(guideline_rows))
    print()

    if rows:
        print("  EVERY ROW IN THE WINDOW")
        print("  %-10s %-11s %-22s %-19s %s"
              % ("pmid", "level_key", "journal", "added_at", "title"))
        for pmid, journal, title, lk, added, qr in rows:
            print("  %-10s %-11s %-22s %-19s %s"
                  % (pmid, lk or "-", (journal or "-")[:22],
                     str(added)[:19], (title or "-")[:44]))
        print()

    # ── judge ──
    offenders = []
    for pmid, journal, title, lk, added, qr in rows:
        cur.execute("SELECT abstract FROM endo_papers_rag WHERE pmid=%s",
                    (pmid,))
        ab = (cur.fetchone() or [""])[0] or ""
        off, reason = judge_off_domain(title or "", journal or "", ab)
        if off:
            offenders.append((pmid, journal, title, lk, added, qr, reason))

    print("  OFF-DOMAIN among them                %d" % len(offenders))
    for pmid, journal, title, lk, added, qr, reason in offenders:
        print("    %-10s %-11s %s" % (pmid, lk, (title or "")[:56]))
        print("               journal: %s" % (journal or "")[:60])
        print("               reason : %s" % reason[:100])
        print("               already quarantined: %s" % (qr or "no"))

    # ── how many stored answers cite them (input counted first) ──
    answers = stored_answers()
    print()
    print("  stored answers scanned               %d" % len(answers))
    n_cited = 0
    for pmid, _j, _t, _lk, _a, _qr, _r in offenders:
        hits = [name for name, t in answers if re.search(r"\b%s\b" % pmid, t)]
        if hits:
            n_cited += len(hits)
            print("    %s cited in %d: %s" % (pmid, len(hits), hits[:4]))
    print("  stored answers citing an offender    %d" % n_cited)

    if offenders and args.apply:
        for pmid, _j, _t, _lk, _a, qr, _r in offenders:
            if qr:
                continue
            cur.execute("UPDATE endo_papers_rag SET quarantine_reason=%s "
                        "WHERE pmid=%s", (QUARANTINE, pmid))
        conn.commit()
        print("\n  APPLIED — %d row(s) quarantined, reversibly." % len(offenders))
    elif offenders:
        print("\n  DRY RUN — re-run with --apply to quarantine.")
    else:
        print("\n  Nothing to quarantine.")

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
