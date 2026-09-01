"""
Sample the case follow-up generator N times on one case (`case-v2` Item 1).

WHY SAMPLING AND NOT ONE RUN. The reported failure — a bisphosphonate question
asked of a 20-year-old — did not reproduce on the first trace. That is not
evidence it does not happen: `generate_case_followups` is one Haiku call, and
this repo has already been bitten once by treating a stochastic generator's
single sample as its behaviour (WORKLIST §1.1, the search-term generator that
returned 1 term and 8 terms for the same question minutes apart, and put ±50%
noise under every eval number until it was fixed).

The mechanism is visible in the prompt without running anything.
`_CASE_DECIDING_FACTS` is a CHECKLIST, and it names
"MEDICAL RED FLAGS — bisphosphonates/antiresorptives, …". The prompt asks which
of those facts are "genuinely MISSING". For a 20-year-old with a necrotic
tooth, bisphosphonate status IS missing from the description — literally, and
uselessly. Whether the model applies clinical judgement on top of the checklist
is left to it, so the answer is a rate, not a yes or no.

At ~$0.0007 a call this is the cheapest measurement in the batch, so run enough
samples to see a rate rather than an anecdote.

    python scripts/sample_case_followups.py -n 15
    python scripts/sample_case_followups.py -n 15 --case "<other case>" \\
        --out eval/logs/x.json
"""

import argparse
import collections
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import endo_ai  # noqa: E402

YOUNG_CASE = ("20-year-old, necrotic tooth, no restoration, no caries — what "
              "could the cause be?")

# The contrast case from the brief. Here the same question is the RIGHT
# question, which is the point: the fix must filter by relevance, not delete
# the topic.
ELDERLY_CASE = ("68-year-old with osteoporosis on alendronate, needs a "
                "decision between extraction and root canal treatment on a "
                "lower molar with a large periapical lesion")

# Non-discriminating for a 20-year-old with no caries and no restoration.
IRRELEVANT = {
    "bisphosphonate": r"bisphosphonate|alendronate|antiresorptive|denosumab|zoledron",
    "radiation":      r"head[- ]and[- ]neck radiation|radiotherapy",
    "immunosuppress": r"immunosuppress|immunocompromis",
    "anticoagulation": r"anticoagul|warfarin|apixaban",
    "diabetes":       r"\bdiabet",
    "endocarditis":   r"endocarditis",
    "restorability":  r"ferrule|restorab|crown[- ]root ratio",
    "prior endo":     r"previous(ly)? root[- ]?filled|prior endodontic|retreat",
}
# Questions that genuinely narrow the differential for this presentation.
DISCRIMINATING = {
    "trauma":      r"trauma|injur|luxat|avuls|concussion|blow|impact",
    "orthodontic": r"orthodontic|braces|aligner",
    "tooth id":    r"which tooth|tooth (number|type)|anterior|incisor|premolar|molar|position",
    "sinus tract": r"sinus tract|fistula|swelling|draining",
    "imaging":     r"radiograph|cbct|imaging|x-ray|periapical film",
    "vitality":    r"vitality|cold test|ept|pulp test|sensibilit",
    "anomaly":     r"invaginat|evaginat|groove|talon|anomal|developmental",
    "discoloration": r"discolo|darken",
}


def classify(question: str) -> tuple:
    low = (question or "").lower()
    bad = [k for k, pat in IRRELEVANT.items() if re.search(pat, low)]
    good = [k for k, pat in DISCRIMINATING.items() if re.search(pat, low)]
    return bad, good


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=15)
    ap.add_argument("--case", default=YOUNG_CASE)
    ap.add_argument("--contrast", action="store_true",
                    help="use the 68-year-old alendronate case instead")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    case = ELDERLY_CASE if args.contrast else args.case
    print(f"CASE: {case}\n")

    runs = []
    bad_runs = 0
    counts = collections.Counter()
    good_counts = collections.Counter()
    for i in range(args.n):
        qs = endo_ai.generate_case_followups(case)
        flagged = []
        for q in qs:
            bad, good = classify(q)
            for b in bad:
                counts[b] += 1
            for g in good:
                good_counts[g] += 1
            if bad:
                flagged.append((q, bad))
        if flagged:
            bad_runs += 1
        runs.append({"i": i + 1, "questions": qs,
                     "non_discriminating": [{"q": q, "why": b}
                                            for q, b in flagged]})
        mark = "  <-- non-discriminating" if flagged else ""
        print(f"run {i + 1:2}/{args.n}  {len(qs)} question(s){mark}")
        for q in qs:
            bad, good = classify(q)
            tag = ("!" + ",".join(bad)) if bad else ("+" + ",".join(good) if good else " ?")
            print(f"     [{tag}] {q[:150]}")

    print(f"\nRUNS WITH A NON-DISCRIMINATING QUESTION: {bad_runs}/{args.n} = "
          f"{100.0 * bad_runs / args.n:.0f}%")
    print(f"  by kind: {dict(counts) or 'none'}")
    print(f"  discriminating topics seen: {dict(good_counts) or 'none'}")

    if args.out:
        p = ROOT / args.out
        p.parent.mkdir(parents=True, exist_ok=True)
        io.open(p, "w", encoding="utf-8").write(json.dumps(
            {"case": case, "n": args.n, "runs_with_non_discriminating": bad_runs,
             "by_kind": dict(counts), "discriminating": dict(good_counts),
             "runs": runs}, indent=1, ensure_ascii=False))
        print(f"wrote {p}")


if __name__ == "__main__":
    main()
