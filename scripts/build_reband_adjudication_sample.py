"""Item D (2026-09-08) — the adjudication worksheet for pubtype vs abstract.

`level_key` has two derivation writers and they disagree about 180 of the 272
rows where both can decide. The batch asks for 30 adjudicated BY HAND, with the
quote that decides each, and per-writer error rates.

This script only assembles the evidence: PMID, journal, title, the publication
types PubMed carries, what each writer concluded, and the sentences from the
abstract that mention a design. It makes no judgement — the judgement is written
into `eval/reports/d_reband_adjudication.md` by a human reader, because the
whole point is to find out which WRITER is wrong, and a third automated writer
adjudicating the first two would just be a third opinion with the same blind
spots.

Sampling is STRATIFIED and DETERMINISTIC: proportional across the disagreement
buckets, then by ascending PMID within each. No randomness, so the sample is
the same on every run and cannot be reshuffled until it says what one wants.

    python scripts/build_reband_adjudication_sample.py --n 30
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E  # noqa: E402
import rag           # noqa: E402

LADDER = ["cochrane", "level1", "level2", "level3a", "level3b", "level3",
          "level4", "level5"]
DESIGN_CUE = re.compile(
    r"(randomi[sz]|double-blind|placebo|in vitro|ex vivo|extracted (human )?"
    r"(teeth|tooth)|retrospectiv|prospectiv|cross-sectional|cohort|case report"
    r"|case series|systematic review|meta-analys|protocol|animal|rat |rats |"
    r"dog |dogs |sheep|bovine|porcine|simulated|resin block|micro-ct)",
    re.I)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    args = ap.parse_args()

    d = json.loads((ROOT / "eval" / "reports" / "e_reband_stage1.json")
                   .read_text(encoding="utf-8"))
    rows = [r for r in d if r.get("abstract_design")]

    conn = rag.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT pmid, abstract, title, journal FROM endo_papers_rag "
                "WHERE pmid = ANY(%s)", ([r["pmid"] for r in rows],))
    lib = {p: (a or "", t or "", j or "") for p, a, t, j in cur.fetchall()}

    disagree = []
    for r in rows:
        a, t, j = lib.get(r["pmid"], ("", "", ""))
        got = E.extract_stated_design(a, t) or {}
        rung = got.get("rung") or ""
        if rung != r["derived"]:
            disagree.append({**r, "abstract_rung": rung or "(none)",
                             "abstract": a, "lib_title": t, "lib_journal": j})

    buckets = defaultdict(list)
    for r in disagree:
        buckets[(r["derived"], r["abstract_rung"])].append(r)
    for k in buckets:
        buckets[k].sort(key=lambda r: int(r["pmid"]) if r["pmid"].isdigit()
                        else 0)

    # proportional allocation, at least one from every bucket that has any
    total = len(disagree)
    alloc, chosen = {}, []
    for k, v in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        alloc[k] = max(1, round(args.n * len(v) / total))
    while sum(alloc.values()) > args.n:
        k = max(alloc, key=lambda k: alloc[k])
        alloc[k] -= 1
    for k, n in alloc.items():
        chosen.extend(buckets[k][:n])

    cur.execute("""SELECT pmid FROM endo_papers_rag WHERE pmid = ANY(%s)""",
                ([r["pmid"] for r in chosen],))
    cur.close()
    conn.close()

    print("=" * 78)
    print("ITEM D — ADJUDICATION WORKSHEET  (%d of %d disagreements)"
          % (len(chosen), total))
    print("=" * 78)
    print("  decidable rows (both writers can decide) : %d" % len(rows))
    print("  writers disagree                         : %d" % total)
    print("  off-ladder among the disagreements       : %d"
          % sum(1 for r in disagree
                if r["derived"] not in LADDER
                or (r["abstract_rung"] not in LADDER
                    and r["abstract_rung"] != "(none)")))
    print()
    print("  BUCKETS")
    for k, v in Counter((r["derived"], r["abstract_rung"])
                        for r in disagree).most_common():
        print("    %-10s vs %-14s %3d   sampled %d"
              % (k[0], k[1], v, alloc.get(k, 0)))
    print()

    out = []
    for i, r in enumerate(chosen, 1):
        cues = [s.strip() for s in re.split(r"(?<=[.!?])\s+", r["abstract"])
                if DESIGN_CUE.search(s)][:3]
        out.append({"n": i, "pmid": r["pmid"], "journal": r["lib_journal"],
                    "title": r["lib_title"], "pubtype_says": r["derived"],
                    "pubtype_why": r["why"], "abstract_says": r["abstract_rung"],
                    "abstract_label": r["abstract_design"], "quotes": cues})
        print("  %2d. PMID %-9s  %s" % (i, r["pmid"], r["lib_journal"][:44]))
        print("      %s" % (r["lib_title"] or "")[:88])
        print("      pubtype  -> %-10s (%s)" % (r["derived"], r["why"]))
        print("      abstract -> %-10s (%s)" % (r["abstract_rung"],
                                                r["abstract_design"]))
        for q in cues:
            print("        \"%s\"" % " ".join(q.split())[:120])
        if not cues:
            print("        (no design sentence found — adjudicate on title)")
        print()

    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    json.dump({"decidable": len(rows), "disagree": total, "sample": out},
              open("eval/reports/night10_item_d_sample.json", "w",
                   encoding="utf-8"), indent=1)
    print("  wrote eval/reports/night10_item_d_sample.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
