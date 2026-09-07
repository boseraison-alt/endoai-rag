"""A55 item 3 — ingest the A54 fixtures F1-F8 through the normal write-back path.

THE POINT OF GOING THROUGH `learn_from_live_results` rather than writing rows
directly: the tier must come from PUBLICATION TYPE (the A48 guard), not from a
lane and not from my opinion. A hand-written INSERT here would set `level_key`
by hand — the exact defect A49 exists to undo — and would bypass the animal
labelling and provenance columns that now ride on that path.

This is the PATCH. Item 2 is the fix: ingesting eight papers helps one question,
while the intersection gate stops the library answering alone on every question
it does not hold.

PREDICTIONS, from the titles alone and committed before the pubtypes were read
(reading them first would make the prediction an echo of the mechanism):

    F1  31078325  clinical outcome comparison        -> level1 or level2
    F2  27986096  clinical comparison                -> level1 or level2
    F3  34499889  already in the library at level3a  -> unchanged
    F4  38430316  clinical outcome                   -> level2 or level3a
    F5  42634020  clinical follow-up                 -> level3a
    F6  42004800  guided vs non-guided assessment    -> level3a or invitro
    F7  41555359  "sealing ability, marginal adaptation" -> invitro
    F8  38849637  "an ex vivo study"                 -> invitro

That already overturns my own A55 prediction 6, which said none would land at
`invitro`. F7 and F8 are bench studies by their own titles. **That is a finding
about A54, not about this ingest**: two of the eight "head-to-head papers" the
A54 fixture set was built from are not clinical evidence at all, and a question
about what to use in a patient cannot be answered from a sealing-ability bench
test. A54's recall target was partly the wrong target.

    python scripts/a55_ingest_fixtures.py            # DRY RUN
    python scripts/a55_ingest_fixtures.py --apply
"""
import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E  # noqa: E402
import rag           # noqa: E402

FIX = ROOT / "eval" / "reports" / "a54_fixtures.json"

# HELD BACK FROM THE WRITE, WITH THE EVIDENCE, NOT SILENTLY DROPPED.
#
# The pubtype writer derives a tier for F7 and the tier is wrong in exactly the
# way item D measured a few hours earlier: NLM tags 41555359 `Meta-Analysis`,
# which derives `level1`, but its own abstract says it "compared the SEALING
# ABILITY and MARGINAL ADAPTATION of premixed versus manually mixed bioceramic
# materials". That is a meta-analysis of BENCH outcomes. Writing it at level1
# puts laboratory evidence at the top of the human clinical ladder — the same
# defect as 28068207 and 36862198, which item D found sitting there already.
#
# Ingesting it would be knowingly repeating a defect documented the same night.
# It is reported instead, for RB, with the sentence that decides it.
HELD_BACK = {
    "41555359": (
        "derives level1 from pubtype:meta-analysis, but its abstract says it "
        "\"compared the sealing ability and marginal adaptation\" — a "
        "meta-analysis of BENCH outcomes, not of clinical trials. Writing it "
        "at level1 repeats the item D defect (see 28068207, 36862198)."),
}


def census(cur):
    cur.execute("""SELECT COALESCE(level_key,'(none)'), COUNT(*)
                   FROM endo_papers_rag
                   WHERE COALESCE(quarantine_reason,'') = ''
                   GROUP BY 1""")
    return dict(cur.fetchall())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    fixtures = json.loads(FIX.read_text(encoding="utf-8"))
    ids = [str(v) for v in fixtures.values()]

    conn = rag.get_conn()
    cur = conn.cursor()
    before = census(cur)
    cur.execute("SELECT pmid FROM endo_papers_rag WHERE pmid = ANY(%s)", (ids,))
    already = {r[0] for r in cur.fetchall()}

    print("=" * 78)
    print("A55 ITEM 3 — INGEST F1-F8  (%s)"
          % ("APPLY" if args.apply else "DRY RUN"))
    print("=" * 78)
    print("  fixtures: %d   already in the library: %d"
          % (len(ids), len(already)))

    meta = E.fetch_metadata(ids)
    parts = E._fetch_pubtypes_and_abstracts(ids)

    scored, rows = [], []
    for fid, pmid in fixtures.items():
        pmid = str(pmid)
        m = meta.get(pmid) or {}
        pt = parts.get(pmid) or {}
        pubtypes = m.get("pubtypes") or pt.get("pubtypes") or []
        journal = m.get("journal") or ""
        tier, why = E.tier_from_pubtypes(pubtypes, journal)
        rows.append({"id": fid, "pmid": pmid, "tier": tier or "(none)",
                     "why": why, "pubtypes": pubtypes,
                     "present": pmid in already,
                     "title": (pt.get("title") or "")[:70]})
        print()
        print("  %-3s %-10s %s" % (fid, pmid, "ALREADY PRESENT"
                                   if pmid in already else "new"))
        print("      %s" % (pt.get("title") or "")[:88])
        print("      pubtypes : %s" % (pubtypes or "none"))
        print("      derives  : %-10s (%s)" % (tier or "(none)", why or "-"))

        if pmid in HELD_BACK:
            print("      HELD BACK — %s" % HELD_BACK[pmid])
            continue
        if pmid in already or not tier:
            if not tier and pmid not in already:
                print("      NOT INGESTED — the pubtype writer derives nothing "
                      "and there is no lane to fall back to.")
            continue
        # SHAPED FOR THE WRITE-BACK PATH, which is what decides the tier.
        #
        # THE SCORE IS COMPUTED, NOT STUBBED. `learn_from_live_results` applies
        # a quality floor of 50, and the first version of this script passed
        # score=0.0 — so all three RCTs were silently filtered out and the
        # "applied" run wrote nothing while reporting success. The fix is to
        # score them the way the live path does, NOT to lower the floor:
        # A55 puts lowering any floor out of scope, and a floor lowered to let
        # a specific paper through is not a floor.
        # `score_paper` returns (score, breakdown) — the first version took the
        # tuple as a number.
        score, _breakdown = E.score_paper(
            tier, m.get("year"), m.get("citations", 0),
            m.get("sample_size"), m.get("followup_months"),
            m.get("impact_factor"),
            is_review=any("review" in t.lower() for t in pubtypes))
        p = dict(m)
        p.update({
            "pmid": pmid, "level_key": tier, # `why` already carries its own "pubtype:" prefix.
            "level_key_source": why,
            "score": float(score), "title": pt.get("title") or "",
            "abstract": pt.get("abstract") or "",
        })
        print("      score    : %.1f  (write-back floor is 50)" % float(score))
        scored.append(p)

    print()
    print("  PREDICTED TIER DISTRIBUTION FOR THE NEW ROWS")
    for k, v in Counter(r["tier"] for r in rows if not r["present"]).most_common():
        print("    %-12s %d" % (k, v))

    if args.apply and scored:
        per = {p["pmid"]: {"title": p["title"], "abstract": p["abstract"]}
               for p in scored}
        rag.learn_from_live_results(scored, per_pmid=per)
        after = census(cur)
        conn.commit()
        print()
        print("  DELTA BY TIER")
        for t in sorted(set(before) | set(after)):
            b, a = before.get(t, 0), after.get(t, 0)
            if a != b:
                print("    %-12s %4d -> %4d  %+d" % (t, b, a, a - b))
        cur.execute("SELECT pmid, level_key, COALESCE(level_key_source,'') "
                    "FROM endo_papers_rag WHERE pmid = ANY(%s) ORDER BY pmid",
                    (ids,))
        print()
        print("  IN THE LIBRARY NOW")
        for pmid, lk, src in cur.fetchall():
            print("    %-10s %-10s %s" % (pmid, lk, src))
        print("\n  APPLIED.")
    elif not args.apply:
        print("\n  DRY RUN — nothing written.")

    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    json.dump({"rows": rows}, open("eval/reports/a55_item3_fixtures.json", "w",
                                   encoding="utf-8"), indent=1)
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
