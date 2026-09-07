"""Re-score a baseline's route criterion against the router's own decision.

WHY THIS EXISTS. `run_eval` INFERS the route from tier `source` values — "live"
if any tier says `pubmed`, "library" if they all say `rag`. That was a fair
proxy while there were two sources. Item A's library union added a third,
`library-union`, which the derivation cannot classify: a question whose tiers
were filled only by the union scores as neither.

The derivation was deliberately NOT changed before v8 ran. Changing an
instrument in the middle of the measurement it is taking is how a baseline stops
meaning anything. Instead the router records what it actually decided, and this
re-reads the SAME STORED OUTPUTS through the corrected reading.

Re-reading stored data through a fixed instrument is not tuning. Changing the
data would be, and nothing here writes to the baseline.

    python scripts/rescore_v8_route.py eval/baseline_v8.json
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


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1
                else "eval/baseline_v8.json")
    if not path.exists():
        print("  no baseline at %s" % path)
        return 1
    doc = json.loads(path.read_text(encoding="utf-8"))
    cases = doc.get("cases") or {}

    print("=" * 78)
    print("V8 ROUTE — INFERRED vs THE ROUTER'S RECORDED DECISION")
    print("=" * 78)
    print("  baseline : %s" % path)
    print("  cases    : %d" % len(cases))
    print()

    rows, disagree = [], []
    inferred_c, recorded_c = Counter(), Counter()
    for cid, c in sorted(cases.items()):
        base = c.get("baseline") or c
        inferred = base.get("route")
        recorded = base.get("route_decision")
        inferred_c[str(inferred)] += 1
        recorded_c[str(recorded)] += 1
        rows.append((cid, inferred, recorded))
        if recorded and inferred != _normalise(recorded):
            disagree.append((cid, inferred, recorded))

    print("  %-40s %-16s %s" % ("case", "inferred", "recorded"))
    for cid, inferred, recorded in rows:
        flag = "" if (not recorded or _normalise(recorded) == inferred) \
            else "   <-- disagree"
        print("  %-40s %-16s %s%s" % (cid[:40], inferred, recorded, flag))

    print()
    print("  INFERRED : %s" % dict(inferred_c))
    print("  RECORDED : %s" % dict(recorded_c))
    print()
    print("  cases where the two readings disagree: %d" % len(disagree))
    for cid, inferred, recorded in disagree:
        print("    %-40s inferred=%-14s recorded=%s"
              % (cid[:40], inferred, recorded))
    if not disagree:
        print("    none — the inferred derivation happened to agree "
              "everywhere, which is worth knowing but was not guaranteed")

    out = ROOT / "eval" / "reports" / "v8_route_rescore.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"baseline": str(path),
               "inferred": dict(inferred_c), "recorded": dict(recorded_c),
               "disagree": [{"id": c, "inferred": i, "recorded": r}
                            for c, i, r in disagree]},
              open(out, "w", encoding="utf-8"), indent=1)
    print("\n  wrote %s" % out)
    return 0


def _normalise(recorded):
    """The router says `live`, `library-forced` or `library-fallback`; the
    inferred derivation only ever says `live` or `library`."""
    return "library" if str(recorded).startswith("library") else "live"


if __name__ == "__main__":
    sys.exit(main())
