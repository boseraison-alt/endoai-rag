"""
Did the Item 2 prompt change buy its pass rate with WORSE citations?

The retry that Item 2 removes was triggered by a missing marker. The cheapest
way to make that retry go away is to attach a marker the paper does not
support — which clears `validate_evidence_mapping` (the PMID is real and in
the evidence base) and fails the reader. That is the exact failure
`_GROUNDING_RULE` exists to prevent, and a fix that traded one for the other
would look like a success on every number Item 2 reports.

So the citations get checked. `verify_citation_support` is run over the stored
attempt-1 answers from both arms — the same judge, the same abstracts, the
same batching — and the flag rate is compared. The CLINICAL RECOMMENDATION is
deliberately not an exempt section, so its markers are among those judged.

  python scripts/check_attempt1_support.py \
      eval/logs/item2_attempt1_before_repro.json \
      eval/logs/item2_attempt1_after_repro.json
"""

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import endo_ai  # noqa: E402


def main():
    paths = [a for a in sys.argv[1:] if not a.startswith("--")] or [
        "eval/logs/item2_attempt1_before_repro.json",
        "eval/logs/item2_attempt1_after_repro.json",
    ]
    summary = []
    for p in paths:
        data = json.loads((ROOT / p).read_text(encoding="utf-8"))
        arm = data["arm"]
        checked = flagged = 0
        cost = 0.0
        shapes = collections.Counter()
        flag_shapes = collections.Counter()
        rec_flags = []
        only_passing = "--passing-only" in sys.argv
        for row in data["rows"]:
            answer = row.get("answer") or ""
            if not answer:
                continue
            if only_passing and not row.get("passed"):
                continue
            out = endo_ai.verify_citation_support(answer, {})
            print(f"    sample {row['sample']:2} passed={str(row['passed']):5} "
                  f"{len(out.get('flags') or [])}/{out.get('checked')}")
            checked += out.get("checked") or 0
            flagged += len(out.get("flags") or [])
            cost += out.get("cost") or 0.0
            for s, v in (out.get("by_shape") or {}).items():
                shapes[s] += v["checked"]
                flag_shapes[s] += v["flagged"]
            # A flagged claim inside the recommendation is the specific
            # failure this script exists to detect.
            rec = (row.get("rec_text") or "")[:400]
            for f in out.get("flags") or []:
                if f["claim"][:80] and f["claim"][:80] in rec:
                    rec_flags.append((row["sample"], f["pmid"],
                                      f["claim"][:120]))
        rate = 100.0 * flagged / checked if checked else 0.0
        print(f"\nARM {arm}  ({p})")
        print(f"  citation-support  {flagged}/{checked} = {rate:.1f}%  "
              f"(judge cost ${cost:.4f})")
        for s in endo_ai.CLAIM_SHAPES:
            if shapes.get(s):
                print(f"    {s:<14} {flag_shapes[s]}/{shapes[s]}")
        print(f"  flags inside the CLINICAL RECOMMENDATION: {len(rec_flags)}")
        for s, pmid, claim in rec_flags:
            print(f"    sample {s}  PMID {pmid}  {claim}")
        summary.append((arm, flagged, checked, rate, len(rec_flags)))

    print("\n" + "=" * 60)
    for arm, f, c, r, rf in summary:
        print(f"  {arm:<8} {f}/{c} = {r:.1f}%   recommendation flags: {rf}")
    print("  A HIGHER after-rate would mean the pass rate was bought with "
          "citations the papers do not support.")


if __name__ == "__main__":
    main()
