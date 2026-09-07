"""Item C (2026-09-08) — how much does `generate_search_terms` vary run to run?

WHY THIS IS MEASURED BEFORE ANYTHING IS CHANGED. Every A/B in this repo
compares two retrieval pools. If the query string itself changes between the
two runs, the comparison measures the term generator's mood, not the change.
2026-09-06 spent a whole item discovering this the expensive way: a
"confinement proof" reported 61/256 pools changed, and two runs of the
IDENTICAL build also gave 61. That became rule 38.

A54 then measured three runs of one probe returning three different guideline
pools. This script puts a number on it across a real question set, so the
temperature-0 change and the term cache can be judged against a baseline
instead of against an impression.

`generate_search_terms` is a Haiku call that passes NO temperature, so the API
default applies. Nothing else is exercised here — no PubMed, no embeddings, no
scoring. The unit is the query STRING (rule 38: query-construction changes
compare query strings).

    python scripts/measure_term_variance.py                  # 10 x 5
    python scripts/measure_term_variance.py --runs 3 --n 5
    python scripts/measure_term_variance.py --tag after      # names the output
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E  # noqa: E402

OUT = ROOT / "eval" / "reports"


def groups(q):
    """The AND-groups of a PubMed query string, normalised for comparison.

    Splitting on top-level AND is what makes two orderings of the same three
    groups compare equal — the generator reorders them freely, and an ordering
    difference is not a retrieval difference.
    """
    depth, cur, out = 0, [], []
    tokens = re.split(r"(\(|\)|\bAND\b)", q or "")
    for t in tokens:
        if t == "(":
            depth += 1
        elif t == ")":
            depth -= 1
        if t == "AND" and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(t)
    out.append("".join(cur))
    return frozenset(" ".join(g.split()).strip("() ").lower()
                     for g in out if g.strip())


def jaccard(a, b):
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b) if (a | b) else 1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--tag", default="before")
    args = ap.parse_args()

    cases = json.loads(
        (ROOT / "eval" / "questions.json").read_text(encoding="utf-8"))["cases"]
    seen, questions = set(), []
    for c in cases:
        q = c["question"] if isinstance(c, dict) else c
        if q not in seen:
            seen.add(q)
            questions.append(q)
        if len(questions) >= args.n:
            break

    print("=" * 78)
    print("ITEM C — TERM-GENERATION VARIANCE  (%s)" % args.tag)
    print("=" * 78)
    print("  questions: %d   runs each: %d   calls: %d"
          % (len(questions), args.runs, len(questions) * args.runs))
    print("  model    : %s" % E.MODELS["structured_fast"])
    print()

    rows, all_identical, group_j = [], 0, []
    for qi, q in enumerate(questions, 1):
        outs = []
        for _r in range(args.runs):
            try:
                outs.append(E.generate_search_terms(q) or "")
            except Exception as ex:
                print("  call failed: %s" % ex)
                outs.append("")
        exact = len(set(outs)) == 1
        gsets = [groups(o) for o in outs]
        pairs = [jaccard(gsets[i], gsets[j])
                 for i in range(len(gsets)) for j in range(i + 1, len(gsets))]
        mean_j = sum(pairs) / len(pairs) if pairs else 1.0
        same_groups = len(set(gsets)) == 1
        all_identical += 1 if exact else 0
        group_j.append(mean_j)
        rows.append({"question": q, "outputs": outs, "exact": exact,
                     "same_groups": same_groups, "mean_group_jaccard": mean_j,
                     "distinct_strings": len(set(outs)),
                     "distinct_groupsets": len(set(gsets))})
        print("  %2d. %-58s" % (qi, q[:58]))
        print("      distinct strings %d/%d   distinct group-sets %d   "
              "mean group Jaccard %.2f%s"
              % (len(set(outs)), args.runs, len(set(gsets)), mean_j,
                 "   IDENTICAL" if exact else ""))
        if not exact:
            for o in sorted(set(outs)):
                print("        - %s" % " ".join(o.split())[:96])

    n = len(rows)
    same_groups_n = sum(1 for r in rows if r["same_groups"])
    print()
    print("  " + "-" * 74)
    print("  identical query string across all %d runs : %d/%d  (%.0f%%)"
          % (args.runs, all_identical, n, 100.0 * all_identical / max(n, 1)))
    print("  identical AND-group SET (order ignored)   : %d/%d  (%.0f%%)"
          % (same_groups_n, n, 100.0 * same_groups_n / max(n, 1)))
    print("  mean pairwise group Jaccard              : %.3f"
          % (sum(group_j) / max(len(group_j), 1)))
    print("  worst question                           : %.2f"
          % min(group_j or [1.0]))
    spread = Counter(r["distinct_strings"] for r in rows)
    print("  distinct strings per question            : %s"
          % dict(sorted(spread.items())))

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / ("night10_term_variance_%s.json" % args.tag)
    json.dump({"tag": args.tag, "runs": args.runs,
               "model": E.MODELS["structured_fast"],
               "identical_rate": all_identical / max(n, 1),
               "same_group_rate": same_groups_n / max(n, 1),
               "mean_group_jaccard": sum(group_j) / max(len(group_j), 1),
               "rows": rows}, open(path, "w", encoding="utf-8"), indent=1)
    print("\n  wrote %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
