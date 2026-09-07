"""Item B (2026-09-09) — reband stage 1: agreements, the population rule, F5-F8.

THREE MOVES, EACH WITH ITS OWN JUSTIFICATION AND ITS OWN CENSUS DELTA.

B1 — the agreements. Rows where the pubtype-derived tier and the
abstract-derived design AGREE with each other and DISAGREE with what is stored.
Where the two writers concur there is no adjudication left to do; the 180
disagreements are explicitly out of scope and stay where they are.

B2 — the population rule. A paper whose abstract states a BENCH subject never
sits on the clinical ladder, whatever PubMed's publication type says. This is
the one axis on which the abstract reading is authoritative by design:
population is fact extraction, and the 2026-09-08 adjudication measured the
pubtype writer wrong on 63% of disagreements against the abstract reader's 30%.
Bench rows move; ANIMAL ROWS DO NOT — they are labelled where they are, per the
2026-09-08 decision, and `bench_population_override` never returns an animal
row.

B4 — F5 and F6 have no usable publication type and are ingested through the
provisional lane's abstract-design path, which exists for exactly this. F7 and
F8 are bench and land at `invitro` under B2.

REVERSIBLE. Every move records `level_key_source`, so what moved and why is
readable per row and a wrong move can be undone by reading the column rather
than by guessing.

    python scripts/b_reband_stage1.py            # DRY RUN
    python scripts/b_reband_stage1.py --apply
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

CLINICAL = {"cochrane", "level1", "level2", "level3a", "level3b", "level3",
            "level4", "classic"}
TERMINAL = {"retracted"}
STAGE1 = ROOT / "eval" / "reports" / "e_reband_stage1.json"
FIXTURES = ROOT / "eval" / "reports" / "a54_fixtures.json"


def census(cur):
    cur.execute("""SELECT COALESCE(level_key,'(none)'), COUNT(*)
                   FROM endo_papers_rag
                   WHERE COALESCE(quarantine_reason,'') = ''
                   GROUP BY 1""")
    return dict(cur.fetchall())


def plan_b1(cur):
    """Rows where both writers agree and differ from what is stored."""
    rows = [r for r in json.loads(STAGE1.read_text(encoding="utf-8"))
            if r.get("abstract_design")]
    cur.execute("""SELECT pmid, COALESCE(abstract,''), COALESCE(title,''),
                          level_key, COALESCE(quarantine_reason,''),
                          COALESCE(has_retraction, FALSE)
                   FROM endo_papers_rag WHERE pmid = ANY(%s)""",
                ([r["pmid"] for r in rows],))
    lib = {r[0]: r[1:] for r in cur.fetchall()}
    out = []
    for r in rows:
        got = lib.get(r["pmid"])
        if not got:
            continue
        abstract, title, level, quar, retr = got
        if quar or retr or level in TERMINAL:
            continue                       # terminal statuses are terminal
        design = E.extract_stated_design(abstract, title) or {}
        rung = design.get("rung") or ""
        if rung and rung == r["derived"] and rung != level:
            out.append({"pmid": r["pmid"], "from": level, "to": rung,
                        "why": "b1:both-writers-agree:%s" % r["why"]})
    return out


def plan_b2(cur):
    """Bench population override — the clinical ladder is for human studies."""
    cur.execute("""SELECT pmid, COALESCE(title,''), COALESCE(abstract,''),
                          level_key
                   FROM endo_papers_rag
                   WHERE COALESCE(quarantine_reason,'') = ''
                     AND NOT COALESCE(has_retraction, FALSE)""")
    out = []
    for pmid, title, abstract, level in cur.fetchall():
        if level not in CLINICAL:
            continue
        move, why = E.bench_population_override(title, abstract, level)
        if move:
            out.append({"pmid": pmid, "from": level, "to": "invitro",
                        "why": "b2:population:%s" % why})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = rag.get_conn()
    cur = conn.cursor()
    before = census(cur)

    b1_all = plan_b1(cur)
    b2 = plan_b2(cur)
    # A row cannot be claimed by both. B2 wins, because it is the stronger
    # statement: it is about the study's SUBJECTS, not about its design, and a
    # paper on extracted teeth is not human clinical evidence however the two
    # design writers band it.
    b2_pmids = {r["pmid"] for r in b2}
    b1 = [r for r in b1_all if r["pmid"] not in b2_pmids]
    overlap = len(b1_all) - len(b1)

    print("=" * 78)
    print("ITEM B — REBAND STAGE 1  (%s)"
          % ("APPLY" if args.apply else "DRY RUN"))
    print("=" * 78)
    print("  B1 both writers agree, differ from stored : %d" % len(b1))
    for k, v in Counter((r["from"], r["to"]) for r in b1).most_common():
        print("      %-10s -> %-10s %3d" % (k[0], k[1], v))
    print()
    print("  B2 bench subject on the clinical ladder   : %d" % len(b2))
    for k, v in Counter(r["from"] for r in b2).most_common():
        print("      %-10s -> invitro    %3d" % (k, v))
    print()
    print("  (B1 rows also claimed by B2, dropped from B1: %d)" % overlap)

    moves = b1 + b2
    if args.apply:
        for m in moves:
            cur.execute("""UPDATE endo_papers_rag
                           SET level_key = %s, level_key_source = %s
                           WHERE pmid = %s""",
                        (m["to"], m["why"], m["pmid"]))
        conn.commit()
    after = census(cur)

    print()
    print("  CENSUS DELTA")
    print("    %-14s %8s %8s %8s" % ("tier", "before", "after", "delta"))
    for t in sorted(set(before) | set(after)):
        b, a = before.get(t, 0), after.get(t, 0)
        print("    %-14s %8d %8d %+8d%s"
              % (t, b, a, a - b, "   <-- changed" if a != b else ""))
    print("    %-14s %8d %8d %+8d"
          % ("TOTAL", sum(before.values()), sum(after.values()),
             sum(after.values()) - sum(before.values())))

    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    json.dump({"b1": b1, "b2": b2,
               "before": before, "after": after},
              open("eval/reports/b_reband_stage1_plan.json", "w",
                   encoding="utf-8"), indent=1)
    print()
    print("  %s" % ("APPLIED." if args.apply
                    else "DRY RUN — nothing written."))
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
