"""Item E (2026-09-09) — the crown-fracture probe, with the scopes corrected.

WHAT THIS RE-SCORES. On 2026-09-08 item C change 4 measured three guideline
admission rules and shipped none of them: all three failed probe 2 at 0/3. The
report's diagnosis was that the failure was in the MANIFEST, not the matcher —
`AAE-TRAUMA-2026` was scoped `[dental trauma, avulsion, luxation, root
fracture]` and probe 2 asks about a **crown** fracture, so no scope rule could
admit a document whose own declaration said it was not about this question.

RB corrected the scopes in `3224b76`: both trauma guidelines now carry the full
injury spectrum. That makes the 2026-09-08 verdict a measurement against a
manifest that no longer exists, and this is the re-run.

If the two documents are now admitted 3/3, the diagnosis was right and the
"ship nothing" verdict was a fact about the data rather than about the rules.
If they still are not, the diagnosis was wrong and the report says so.

Retrieval only, three runs, cold terms.

    python scripts/e_crown_fracture_probe.py --runs 3
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

sys.path.insert(0, str(ROOT / "scripts"))
from measure_guideline_admission_rules import (citeable, manifest,  # noqa: E402
                                               rule_a, rule_b)
from run_trauma_probes import PROBES, WATCH  # noqa: E402

PROBE = "probe2-crown-fracture"
WANT = ["AAE-TRAUMA-2026", "IADT-FRACTURES-LUXATIONS-2020"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()

    q = dict(PROBES)[PROBE]
    man = manifest()

    print("=" * 78)
    print("ITEM E — THE CROWN-FRACTURE PROBE, SCOPES CORRECTED")
    print("=" * 78)
    print("  question: %s" % q)
    print("  watched : %s" % ", ".join(WATCH[PROBE]))
    print()
    print("  SCOPES AS THEY NOW STAND (RB, 3224b76)")
    for gid in WATCH[PROBE]:
        print("    %-34s %s" % (gid, man.get(gid, {}).get("scope")))
    print()

    prev = E.TERM_CACHE_ENABLED
    E.TERM_CACHE_ENABLED = False           # cold terms every run
    runs = []
    try:
        for r in range(args.runs):
            terms = [E.generate_search_terms(q, mode="review")]
            a = citeable(rule_a(q, terms=terms))
            b2 = citeable(rule_b(q, need=2))
            b1 = citeable(rule_b(q, need=1))
            runs.append({"run": r + 1,
                         "a": sorted(a), "b_need2": sorted(b2),
                         "b_need1": sorted(b1),
                         "union": sorted(a | b2)})
            print("  run %d: (a) %d  (b>=2) %d  (c) %d   watched admitted by "
                  "scope: %s"
                  % (r + 1, len(a), len(b2), len(a | b2),
                     ", ".join(w for w in WANT if w in b2) or "none"))
    finally:
        E.TERM_CACHE_ENABLED = prev

    print()
    print("  " + "-" * 70)
    for w in WANT:
        n_b = sum(1 for x in runs if w in x["b_need2"])
        n_a = sum(1 for x in runs if w in x["a"])
        n_c = sum(1 for x in runs if w in x["union"])
        print("  %-34s scope %d/%d   similarity %d/%d   union %d/%d"
              % (w, n_b, args.runs, n_a, args.runs, n_c, args.runs))
    both = sum(1 for x in runs if all(w in x["b_need2"] for w in WANT))
    print()
    print("  BOTH admitted by scope on %d/%d runs : %s"
          % (both, args.runs, "PASS" if both == args.runs else "FAIL"))
    print()
    if both == args.runs:
        print("  The 2026-09-08 diagnosis holds: the manifest was the blocker,")
        print("  not the matcher. Rule (b) admits both once the documents'")
        print("  declared scope names what they cover.")
    else:
        print("  The 2026-09-08 diagnosis does NOT hold — correcting the scopes")
        print("  was not sufficient, so something else blocks admission.")

    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    json.dump({"probe": PROBE, "question": q, "want": WANT,
               "scopes": {g: man.get(g, {}).get("scope") for g in WATCH[PROBE]},
               "runs": runs, "both_by_scope": both},
              open("eval/reports/e_crown_fracture_probe.json", "w",
                   encoding="utf-8"), indent=1)
    print("\n  wrote eval/reports/e_crown_fracture_probe.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
