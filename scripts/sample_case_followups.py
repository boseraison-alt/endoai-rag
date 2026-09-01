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

# RELEVANCE IS A PROPERTY OF THE TOPIC *AND THIS PATIENT*, so the classifier is
# per case. The first version of this script used one IRRELEVANT set for both
# and reported the 68-year-old at 90% non-discriminating — because restorability
# and prior-endodontic-treatment, the two questions that actually decide
# extraction versus retreatment at 68, were on a list written for a 20-year-old
# with a virgin tooth. The measurement was wrong, not the product. Encoding the
# distinction is also exactly what the contrast case exists to prove.
PROFILES = {
    "young": {
        # 20-year-old, caries-free, unrestored. Every medical red flag is a
        # near-certain no, and restorability is not in question on a virgin
        # tooth.
        "irrelevant": {
            "bisphosphonate": r"bisphosphonate|alendronate|antiresorptive|denosumab|zoledron",
            "radiation":      r"head[- ]and[- ]neck radiation|radiotherapy",
            "immunosuppress": r"immunosuppress|immunocompromis",
            "anticoagulation": r"anticoagul|warfarin|apixaban",
            "diabetes":       r"\bdiabet",
            "endocarditis":   r"endocarditis",
            "restorability":  r"ferrule|restorab|crown[- ]root ratio|post and core|post-core",
        },
        "discriminating": {
            "trauma":      r"trauma|injur|luxat|avuls|concussion|blow|impact",
            "orthodontic": r"orthodontic|braces|aligner",
            "tooth id":    r"which tooth|tooth (number|type)|anterior|incisor|premolar|molar|position",
            "sinus tract": r"sinus tract|fistula|swelling|draining|isolated deep|narrow pocket",
            "imaging":     r"radiograph|cbct|imaging|x-ray|periapical film",
            "vitality":    r"vitality|cold test|ept|pulp test|sensibilit",
            "anomaly":     r"invaginat|evaginat|groove|talon|anomal|developmental|unusual anatomy",
            "discoloration": r"discolo|darken",
        },
    },
    "elderly": {
        # 68-year-old on alendronate, extraction versus root canal. Here
        # restorability, prior treatment and the antiresorptive DETAIL are the
        # deciding facts; the young-tooth developmental differential is not.
        "irrelevant": {
            "orthodontic":   r"orthodontic|braces|aligner",
            "anomaly":       r"invaginat|evaginat|talon|dens in dente",
            "apex maturity": r"open apex|immature apex|apexogenesis",
        },
        "discriminating": {
            "bisphosphonate": r"bisphosphonate|alendronate|antiresorptive|denosumab|zoledron|mronj|drug holiday",
            "restorability":  r"ferrule|restorab|crown[- ]root ratio|post and core|post-core|remaining (coronal )?(tooth )?structure",
            "prior endo":     r"previous(ly)? root[- ]?filled|prior endodontic|retreat|treated endodontically|virgin tooth",
            "periodontal":    r"periodont|bone (loss|support)|mobility|furcation",
            "sinus tract":    r"sinus tract|fistula|swelling|draining|isolated deep|narrow pocket",
            "lesion":         r"lesion size|how large|extent of the lesion",
            "vitality":       r"vitality|cold test|ept|pulp test|sensibilit",
        },
    },
}

PROFILE = {"name": "young"}


def classify(question: str) -> tuple:
    """Classify the QUESTION, not the reason clause after the em dash.

    Every question is emitted as `<question> — <why it matters>`, and matching
    the whole line called this one non-discriminating:

      "Which tooth is affected, and does it have any visible crack, infraction,
       or isolated deep pocket? — this identifies the mechanism of pulp death
       and whether it is restorable"

    That is a textbook discriminating question. "restorab" appears only in its
    justification. Splitting on the dash is the second correction to this
    classifier in one batch, both in the same direction: a keyword list is a
    blunt instrument and the measurement it produces has to be read before it
    is believed.
    """
    prof = PROFILES[PROFILE["name"]]
    text = (question or "")
    for dash in ("—", "–", " - "):
        if dash in text:
            text = text.split(dash, 1)[0]
            break
    low = text.lower()
    bad = [k for k, pat in prof["irrelevant"].items() if re.search(pat, low)]
    good = [k for k, pat in prof["discriminating"].items() if re.search(pat, low)]
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
    PROFILE["name"] = "elderly" if args.contrast else "young"
    print(f"CASE [{PROFILE['name']}]: {case}\n")

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
