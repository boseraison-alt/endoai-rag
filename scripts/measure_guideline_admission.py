"""Item C (2026-09-07) — how many current guidelines are ADMITTED vs ELIGIBLE.

TWO FINDINGS FROM 2026-09-06 WITH ONE SUSPECTED CAUSE.

  (1) Probe 3's guideline pool held the ACP extraction statement ALONE.
      ESE-S3-2023 and AAE-TREATMENTSTANDARDS-2018 never reached it, so there
      was no divergence to show and the answer's only mention of AAE/ESE was
      the model's own knowledge, which the citation checker flagged.
  (2) AAE-TRAUMA-2026 dropped out of probe 2's pool between states 2 and 3
      while probe 1 gained ESE-TRAUMA-2021.

The hypothesis is top-k by similarity: a broad flagship guideline whose
embedding covers all of endodontics loses to any narrow document on any
specific question, and a trauma question with five current guidelines loses one
when k is smaller than five.

THE TWO ROUTES HAVE DIFFERENT CAPS, and this is the first thing to establish
rather than assume:

    live / curriculum   MODE_TIER_QUOTAS['review']['guideline'] = 4
    library route       app.py RAG_GATE 'max_per_tier' = 25, and NO per-tier
                        quality floor at all

So a probe that routes to the library is not capped at 4, and finding (2) may
have nothing to do with k. This script measures BOTH numbers per question:
how many current, non-quarantined guideline rows sit above the similarity
floor, and how many are admitted.

RETRIEVAL ONLY. No synthesis.

    python scripts/measure_guideline_admission.py --arm before
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

PROBES = [
    ("probe1-avulsion",
     "Avulsed maxillary central incisor with a closed apex, replanted after "
     "40 minutes of extra-oral dry time. How should it be managed and what is "
     "the prognosis?"),
    ("probe2-crown-fracture",
     "Complicated crown fracture with pulp exposure in a mature premolar, "
     "6 hours old. What is the management?"),
    ("probe3-retreat-implant",
     "Mature molar with a failed root canal retreatment. The patient asks for "
     "extraction and an implant. How should this be decided?"),
]

FLAGSHIP_WATCH = ["ESE-S3-2023", "AAE-TREATMENTSTANDARDS-2018",
                  "BES-GOODPRACTICE-2022", "AAE-TRAUMA-2026",
                  "ESE-TRAUMA-2021", "ACP-ASYMPTOMATIC-EXTRACTION-2016",
                  "IADT-AVULSION-2020", "IADT-FRACTURES-LUXATIONS-2020"]


def guideline_rows_above_floor(question, floor):
    """Every CURRENT, non-quarantined guideline row above the similarity floor,
    ranked. This is the ELIGIBLE set — what admission is choosing from."""
    vec = rag.embed(question)
    conn = rag.get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT pmid, COALESCE(guideline_id,''), COALESCE(guideline_org,''),
                   COALESCE(guideline_status,''), title,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM endo_papers_rag
            WHERE level_key = 'guideline'
              AND COALESCE(quarantine_reason,'') = ''
              AND COALESCE(superseded_by,'') = ''
              AND embedding IS NOT NULL
            ORDER BY similarity DESC
        """, (vec,))
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()
    out = []
    for pmid, gid, org, status, title, sim in rows:
        if status in ("superseded", "withdrawn", "draft",
                      "superseded_in_content"):
            continue
        out.append({"pmid": pmid, "guideline_id": gid, "org": org,
                    "status": status, "title": (title or "")[:80],
                    "similarity": round(float(sim), 4)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="before")
    ap.add_argument("--floor", type=float, default=None)
    args = ap.parse_args()

    cases = [(c["id"], c["question"])
             for c in json.load(open("eval/questions.json"))["cases"]] + PROBES

    floor = args.floor
    if floor is None:
        # Read from where production reads it, not from a constant retyped
        # here. app.RELEVANCE_GATE['similarity_floor'] is the shipped 0.55.
        try:
            import app
            floor = float(app.RELEVANCE_GATE["similarity_floor"])
        except Exception as ex:
            raise SystemExit("cannot read the shipped similarity floor: %s" % ex)

    live_k = E._tier_cap("review", "guideline")
    try:
        import app
        lib_k = (app.RAG_GATE or {}).get("max_per_tier")
    except Exception as ex:
        lib_k = "unavailable (%s)" % ex

    print("=" * 78)
    print("ITEM C — GUIDELINE ADMISSION,  ARM = %s" % args.arm.upper())
    print("=" * 78)
    print("  similarity floor                       %.2f" % floor)
    print("  live / curriculum cap (MODE_TIER_QUOTAS)  %s" % live_k)
    print("  library route cap (RAG_GATE max_per_tier) %s" % lib_k)
    print("  current non-quarantined guideline rows in the library:", end=" ")
    conn = rag.get_conn(); cur = conn.cursor()
    cur.execute("""SELECT COUNT(*) FROM endo_papers_rag
                   WHERE level_key='guideline'
                     AND COALESCE(quarantine_reason,'')=''
                     AND COALESCE(superseded_by,'')=''""")
    n_total = cur.fetchone()[0]
    cur.close(); conn.close()
    print(n_total)
    print()

    rows = []
    for i, (cid, q) in enumerate(cases, 1):
        elig = guideline_rows_above_floor(q, floor)
        above = [r for r in elig if r["similarity"] >= floor]
        admitted_live = above[:live_k] if isinstance(live_k, int) else above
        gap = len(above) - len(admitted_live)
        watch = {}
        for w in FLAGSHIP_WATCH:
            hit = next((k for k, r in enumerate(above)
                        if r["guideline_id"] == w), None)
            if hit is not None:
                watch[w] = {"rank": hit + 1,
                            "similarity": above[hit]["similarity"],
                            "admitted_at_live_k": hit < live_k}
        rows.append({"id": cid, "eligible_above_floor": len(above),
                     "admitted_live_k": len(admitted_live), "gap": gap,
                     "top": [r["guideline_id"] or r["pmid"]
                             for r in above[:6]],
                     "watch": watch})
        print("[%2d/%d] %-44s above_floor=%-3d admitted@k=%-3d gap=%d"
              % (i, len(cases), cid[:44], len(above), len(admitted_live), gap))
        if watch:
            for w, d in sorted(watch.items(), key=lambda x: x[1]["rank"]):
                print("        %-34s rank %-3d sim %.3f  %s"
                      % (w, d["rank"], d["similarity"],
                         "ADMITTED" if d["admitted_at_live_k"] else "cut by k"))

    n = len(rows)
    with_gap = [r for r in rows if r["gap"] > 0]
    print()
    print("=" * 78)
    print("RESULT")
    print("=" * 78)
    print("  questions measured                      %d" % n)
    print("  questions where k CUTS an eligible row  %d  (%.0f%%)"
          % (len(with_gap), 100.0 * len(with_gap) / max(1, n)))
    print("  total eligible rows cut by k            %d"
          % sum(r["gap"] for r in rows))
    print("  median eligible above floor             %d"
          % sorted(r["eligible_above_floor"] for r in rows)[n // 2])

    print()
    print("  ESE-S3-2023 (the only flagship: true record) on probe 3:")
    p3 = next(r for r in rows if r["id"] == "probe3-retreat-implant")
    w = p3["watch"].get("ESE-S3-2023")
    if w:
        print("    rank %d of %d above the floor, similarity %.3f, %s"
              % (w["rank"], p3["eligible_above_floor"], w["similarity"],
                 "ADMITTED at k=%s" % live_k if w["admitted_at_live_k"]
                 else "CUT by k=%s" % live_k))
    else:
        print("    NOT above the floor at all — the flagship rule would not")
        print("    rescue it, and the cause is similarity, not admission.")

    out = "eval/reports/night9_item_c_%s.json" % args.arm
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    json.dump({"floor": floor, "live_k": live_k, "library_k": lib_k,
               "guideline_rows": n_total, "rows": rows},
              open(out, "w"), indent=1)
    print("\n  wrote %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
