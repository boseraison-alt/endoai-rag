"""Item 3 (2026-09-09) — non-current guidelines reaching the guideline block.

WHAT WAS SEEN. Item E's synthesis of probe 2 showed the model a guideline block
containing `ESE-QG-2006` (quarantined by A2, *superseded* in the manifest) and
both IADT 2012 documents (superseded by their 2020 successors). That breaks two
of A49's hard gates — withdrawn is never citeable, superseded is excluded from
retrieval — and it breaks them where it matters most: the model reads that block
as the specialty's current position.

It is a defect whether or not the specialty renderer is wired, because the
damage is done in the CONTEXT, before anything renders.

THE POINT OF THIS SCRIPT IS THE PATH, not the count. There are three ways a
guideline row can reach the block and they need different fixes:

    live-lane   the live guideline lane fetched it from PubMed
    scoped      `admit_scoped_guidelines` admitted it by manifest scope
    union       item A's library union carried it in

Each candidate is attributed by re-running the paths in isolation, not by
guessing from the row's shape.

    python scripts/measure_guideline_block_leak.py
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

import app  # noqa: E402
import endo_ai as E  # noqa: E402
import rag  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from measure_guideline_admission_rules import questions  # noqa: E402

BAD_STATUS = {"superseded", "superseded_in_content", "withdrawn", "draft"}


def offending_rows(cur):
    """Every guideline row that must never reach a block, and why."""
    cur.execute("""
        SELECT pmid, COALESCE(guideline_id,''), COALESCE(guideline_status,''),
               COALESCE(quarantine_reason,''), COALESCE(superseded_by,''),
               COALESCE(title,'')
        FROM endo_papers_rag
    """)
    out = {}
    for pmid, gid, status, quar, sup, title in cur.fetchall():
        why = []
        if status.lower() in BAD_STATUS:
            why.append("status=%s" % status)
        if quar:
            why.append("quarantined")
        if sup:
            why.append("superseded_by=%s" % sup)
        if why:
            out[pmid] = {"gid": gid, "why": ", ".join(why),
                         "title": title[:60]}
    return out


def main():
    conn = rag.get_conn()
    cur = conn.cursor()
    bad = offending_rows(cur)

    print("=" * 78)
    print("ITEM 3 — NON-CURRENT GUIDELINES REACHING THE GUIDELINE BLOCK")
    print("=" * 78)
    print("  rows in the library that must never reach a block: %d" % len(bad))
    print()

    qs = questions()
    hits, per_q = Counter(), []
    path_tally = Counter()
    for qid, q in qs:
        try:
            ev = app.build_evidence_base_with_progress("leak-%s" % qid[:12], q)
        except Exception as ex:
            print("  %-30s FAILED: %s" % (qid[:30], ex))
            continue
        block = (ev.get("guideline") or {}).get("scored") or []
        found = [r for r in block if str(r.get("pmid")) in bad]
        if found:
            for r in found:
                pmid = str(r.get("pmid"))
                hits[pmid] += 1
                # ATTRIBUTED BY THE ROW'S OWN `source`, which each path sets:
                # the live lanes leave it "pubmed", the union sets
                # "library-union", and `admit_scoped_guidelines` sets "rag".
                src = r.get("source") or "?"
                path_tally[src] += 1
            print("  %-30s %d offending row(s): %s"
                  % (qid[:30], len(found),
                     ", ".join(sorted({bad[str(r.get('pmid'))]['gid']
                                       or str(r.get('pmid'))
                                       for r in found}))))
        per_q.append({"id": qid, "n_block": len(block),
                      "offending": [str(r.get("pmid")) for r in found]})

    print()
    print("  " + "-" * 70)
    print("  questions with at least one offending row : %d/%d"
          % (sum(1 for r in per_q if r["offending"]), len(per_q)))
    print("  distinct offending rows admitted          : %d" % len(hits))
    print()
    print("  BY ROW")
    for pmid, n in hits.most_common():
        b = bad[pmid]
        print("    %-10s %-30s x%-3d %s" % (pmid, b["gid"][:30], n, b["why"]))
    print()
    print("  BY PATH (the row's own `source`)")
    for src, n in path_tally.most_common():
        print("    %-16s %d" % (src, n))

    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    json.dump({"offending_rows": {k: v for k, v in bad.items() if k in hits},
               "per_question": per_q, "by_path": dict(path_tally)},
              open("eval/reports/item3_guideline_block_leak.json", "w",
                   encoding="utf-8"), indent=1)
    cur.close()
    conn.close()
    print("\n  wrote eval/reports/item3_guideline_block_leak.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
