"""Item G(b) — how many animal-subject rows are in the library, and do they
reach a pool?

MEASURE ONLY. No fix. The paper lanes carry no species restriction at query
time — `animal_subjects.detect_animal_subject` is a LIBRARY classifier that
`scripts/classify_animal_subjects.py` runs, and the live path has never called
it. Adding one is a retrieval change and needs its own A/B, so the number is
what decides whether that A/B is worth running.

Rule 34 throughout: the detector's INPUT is counted first. A row with no
abstract cannot be classified, and reporting "N animal rows" without saying how
many abstracts the detector could actually read would be a zero dressed as a
finding.

    python scripts/count_animal_subjects.py
"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import rag  # noqa: E402
from animal_subjects import detect_animal_subject  # noqa: E402


def main():
    conn = rag.get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT pmid, COALESCE(title,''), COALESCE(abstract,''),
               COALESCE(level_key,''), COALESCE(quarantine_reason,'')
        FROM endo_papers_rag
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    print("=" * 78)
    print("ITEM G(b) — ANIMAL-SUBJECT ROWS IN THE LIBRARY")
    print("=" * 78)

    # ── THE INPUT, counted before any result ──
    n_total = len(rows)
    n_abs = sum(1 for r in rows if r[2].strip())
    n_readable = sum(1 for r in rows if len(r[2].split()) >= 20)
    print("  rows in endo_papers_rag                      %d" % n_total)
    print("  with any abstract text                       %d" % n_abs)
    print("  with >= 20 words (what the detector can read) %d" % n_readable)
    print("  the detector cannot classify the other       %d"
          % (n_total - n_readable))
    print()

    hits, by_tier, by_cue = [], Counter(), Counter()
    for pmid, title, abstract, level_key, quar in rows:
        if len(abstract.split()) < 20:
            continue
        try:
            res = detect_animal_subject(title, abstract, level_key)
        except Exception:
            continue
        is_animal = res[0] if isinstance(res, tuple) else bool(res)
        cue = ""
        if isinstance(res, tuple) and len(res) > 1:
            cue = str(res[1] or "")[:60]
        if is_animal:
            hits.append({"pmid": pmid, "level_key": level_key,
                         "title": title[:80], "cue": cue,
                         "quarantined": bool(quar.strip())})
            by_tier[level_key] += 1
            by_cue[cue] += 1

    print("  ANIMAL-SUBJECT ROWS DETECTED                 %d" % len(hits))
    print()
    print("  by tier")
    for t, n in by_tier.most_common():
        print("    %-16s %4d" % (t or "(none)", n))
    print()
    print("  by cue (top 10)")
    for c, n in by_cue.most_common(10):
        print("    %-52s %3d" % (c or "(none)", n))

    # ── do they reach a pool? ──
    print()
    print("  DO THEY REACH A POOL? (the 29 eval questions, library route)")
    from app import multi_query_search
    import endo_ai as E

    cases = json.load(open("eval/questions.json"))["cases"]
    animal_pmids = {h["pmid"] for h in hits}
    reached, per_q = set(), {}
    for i, c in enumerate(cases, 1):
        try:
            terms = [E.generate_search_terms(c["question"])]
        except Exception:
            terms = []
        got = multi_query_search(c["question"], terms, limit=100)
        floor = 0.55
        pool = {str(r.get("pmid")) for r in got
                if float(r.get("similarity") or 0) >= floor}
        hit = pool & animal_pmids
        per_q[c["id"]] = sorted(hit)
        reached |= hit
        print("  [%2d/%d] %-44s %d animal row(s) in the pool"
              % (i, len(cases), c["id"][:44], len(hit)))

    print()
    print("  distinct animal rows reaching any of the 29 pools   %d" % len(reached))
    for p in sorted(reached):
        h = next(x for x in hits if x["pmid"] == p)
        print("    %-10s %-12s %s" % (p, h["level_key"], h["title"][:56]))

    out = {"rows_total": n_total, "readable": n_readable,
           "animal_rows": len(hits), "by_tier": dict(by_tier),
           "reaching_a_pool": sorted(reached), "per_question": per_q,
           "hits": hits}
    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    json.dump(out, open("eval/reports/night9_animal_subjects.json", "w"),
              indent=1)
    print("\n  wrote eval/reports/night9_animal_subjects.json")
    print("\n  NO FIX. A species guard on the paper lanes is a retrieval")
    print("  change and needs its own A/B; this number decides whether that")
    print("  A/B is worth running.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
