"""Item B4 (2026-09-09) — F5, F6, F7, F8.

PREDICTED BEFORE THE WRITE, from the abstract-design path:

    F5  42634020  already in the library at level3a   -> unchanged
    F6  42004800  "24 patients", RCT                  -> level1
    F7  41555359  meta-analysis of BENCH outcomes     -> invitro
    F8  38849637  "ninety root segments", ex vivo     -> invitro

TWO THINGS THE BATCH DID NOT ANTICIPATE, both worth recording.

**F5 and F7 arrived on their own.** Item A ran the live lanes over all 32
questions, and write-back ingested both — F5 at `level3a`, matching the
prediction, and F7 at `level1`. F7 is the row A55 deliberately held back from a
manual ingest for being a bench meta-analysis at the top of the clinical ladder.
Holding a row back from one path does not hold it back from another: the live
write-back has no knowledge of that decision, and a hold-back that only binds
the script you happen to be running is not a hold-back.

**B2 does not reach F7, and it is right not to.** B2 is a POPULATION rule — "a
paper whose abstract states a bench SUBJECT". F7's subjects are studies; it is a
systematic review, and `extract_stated_design` reads it correctly as one. Its
bench-ness is in its OUTCOMES: it compares "sealing ability and marginal
adaptation". Subjects and outcomes are different axes and B2 only covers the
first. So F7 is moved here, explicitly, with the reason in
`level_key_source` — not by widening a population rule until it catches an
outcome.

    python scripts/b4_fixtures.py            # DRY RUN
    python scripts/b4_fixtures.py --apply
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E  # noqa: E402
import rag           # noqa: E402

FIX = json.loads((ROOT / "eval" / "reports" / "a54_fixtures.json")
                 .read_text(encoding="utf-8"))

# F7 — moved by an explicit decision, because B2's axis does not reach it.
EXPLICIT = {
    FIX["F7"]: ("invitro",
                "b4:outcomes-are-bench:a meta-analysis of sealing ability and "
                "marginal adaptation is not human clinical evidence"),
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

    conn = rag.get_conn()
    cur = conn.cursor()
    before = census(cur)

    ids = [FIX[k] for k in ("F5", "F6", "F7", "F8")]
    cur.execute("SELECT pmid, level_key FROM endo_papers_rag "
                "WHERE pmid = ANY(%s)", (ids,))
    present = dict(cur.fetchall())
    recs = E._fetch_pubtypes_and_abstracts(ids)
    meta = E.fetch_metadata(ids)

    print("=" * 78)
    print("ITEM B4 — F5, F6, F7, F8  (%s)"
          % ("APPLY" if args.apply else "DRY RUN"))
    print("=" * 78)

    moves, ingests = [], []
    for k in ("F5", "F6", "F7", "F8"):
        pmid = FIX[k]
        r = recs.get(pmid) or {}
        design = E.extract_stated_design(r.get("abstract") or "",
                                         r.get("title") or "") or {}
        rung = design.get("rung") or ""
        now = present.get(pmid)
        print()
        print("  %-3s %-10s %s" % (k, pmid,
                                   "in the library at %s" % now if now
                                   else "ABSENT"))
        print("      design reads : %-30s -> %s"
              % (design.get("design") or "-", rung or "(none)"))
        if pmid in EXPLICIT:
            to, why = EXPLICIT[pmid]
            if now == to:
                print("      already at %s" % to)
            elif now:
                moves.append({"pmid": pmid, "from": now, "to": to, "why": why})
                print("      EXPLICIT MOVE %s -> %s" % (now, to))
                print("      %s" % why)
            continue
        if now:
            print("      unchanged — write-back already placed it")
            continue
        if not rung:
            print("      NOT INGESTED — the abstract states no design, and "
                  "guessing one is the defect A49 exists to undo")
            continue
        # THE DRY RUN MODELS THE WRITE-BACK'S QUALITY FLOOR.
        #
        # It did not, and so predicted +2 rows where the apply delivered +1:
        # F8 scores 41.8 at `invitro` against `learn_from_live_results`'
        # min_score of 50 and was refused. "applied == dry run" is the standing
        # rule, and a dry run that ignores a gate the apply will hit is not a
        # dry run of the apply. The floor is NOT lowered — it is the reason F8
        # stays out, and lowering it is out of scope.
        m = meta.get(pmid) or {}
        score, _bd = E.score_paper(rung, m.get("year"), m.get("citations", 0),
                                   m.get("sample_size"),
                                   m.get("followup_months"),
                                   m.get("impact_factor"))
        floor = rag.learn_from_live_results.__defaults__[1]
        if float(score) < floor:
            print("      NOT INGESTED — scores %.1f at %s, below the "
                  "write-back floor of %.0f" % (score, rung, floor))
            continue
        ingests.append({"pmid": pmid, "to": rung, "rec": r, "meta": m})
        print("      INGEST at %s, score %.1f (abstract-design path)"
              % (rung, score))

    print()
    print("  moves: %d   ingests: %d" % (len(moves), len(ingests)))

    if args.apply:
        for m in moves:
            cur.execute("""UPDATE endo_papers_rag
                           SET level_key = %s, level_key_source = %s
                           WHERE pmid = %s""",
                        (m["to"], m["why"], m["pmid"]))
        conn.commit()
        scored = []
        for g in ingests:
            m, r = g["meta"], g["rec"]
            score, _bd = E.score_paper(
                g["to"], m.get("year"), m.get("citations", 0),
                m.get("sample_size"), m.get("followup_months"),
                m.get("impact_factor"))
            p = dict(m)
            p.update({"pmid": g["pmid"], "level_key": g["to"],
                      "level_key_source": "b4:abstract-design",
                      "score": float(score),
                      "title": r.get("title") or "",
                      "abstract": r.get("abstract") or ""})
            scored.append(p)
        if scored:
            rag.learn_from_live_results(
                scored, per_pmid={p["pmid"]: {"title": p["title"],
                                              "abstract": p["abstract"]}
                                  for p in scored})
        after = census(cur)
    else:
        after = dict(before)
        for m in moves:
            after[m["from"]] = after.get(m["from"], 0) - 1
            after[m["to"]] = after.get(m["to"], 0) + 1
        for g in ingests:
            after[g["to"]] = after.get(g["to"], 0) + 1

    print()
    print("  CENSUS DELTA")
    for t in sorted(set(before) | set(after)):
        b, a = before.get(t, 0), after.get(t, 0)
        if a != b:
            print("    %-14s %5d -> %5d  %+d" % (t, b, a, a - b))
    print("    %-14s %5d -> %5d  %+d"
          % ("TOTAL", sum(before.values()), sum(after.values()),
             sum(after.values()) - sum(before.values())))
    print()
    print("  %s" % ("APPLIED." if args.apply else "DRY RUN — nothing written."))
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
