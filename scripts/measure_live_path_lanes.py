"""What the live-path lane fix costs, measured on the path it fixed.

`app.build_evidence_base_with_progress` is the LIVE retrieval path for Review
and Case. It carried a second, hardcoded copy of the lane list that had fallen
three lanes behind `endo_ai.tier_query_lanes()`: observational (A31),
guideline (A49 item 5) and provisional (A49 item 4b) never reached a Review or
Case answer.

Deriving the list from the shared helper closes that, and it necessarily adds
queries to a path that previously issued fewer. This measures the real cost on
the real function, with the lanes restricted to the old set in the "before"
arm.

Usage:  python scripts/measure_live_path_lanes.py
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E                # noqa: E402
import app as A                    # noqa: E402

QUESTION = ("Single-visit versus multiple-visit root canal treatment for "
            "necrotic teeth with apical periodontitis")
OUT = ROOT / "eval" / "reports" / "a49_provisional_lane"

OLD_LANES = ["level1", "level2", "level3a", "level3b", "level4", "level5"]
_REAL_LANES = E.tier_query_lanes
_REAL_UNTYPED = E.fetch_untyped_recent


def make_job(jid):
    with A.jobs_lock:
        A.jobs[jid] = {"status": "running", "abort": False}


def run(arm):
    """arm='before' restores the old hardcoded lane set and disables the
    provisional lane; arm='after' is production as it now stands."""
    if arm == "before":
        E.tier_query_lanes = lambda: [t for t in _REAL_LANES()
                                      if t[0] in OLD_LANES]
        E.fetch_untyped_recent = lambda *a, **kw: ("", [], [])
    else:
        E.tier_query_lanes = _REAL_LANES
        E.fetch_untyped_recent = _REAL_UNTYPED

    jid = "measure-%s" % arm
    make_job(jid)
    t0 = time.perf_counter()
    try:
        ev = A.build_evidence_base_with_progress(
            jid, QUESTION, force_route="live", mode="review")
    finally:
        E.tier_query_lanes = _REAL_LANES
        E.fetch_untyped_recent = _REAL_UNTYPED
    elapsed = time.perf_counter() - t0

    per_lane = {}
    for k, block in ev.items():
        if k.startswith("_") or not isinstance(block, dict):
            continue
        per_lane[k] = len(block.get("scored") or [])
    summary = ev.get("_summary", {}) or {}
    prov = (ev.get(E.PROVISIONAL_KEY) or {}).get("scored") or []
    return {
        "arm": arm,
        "elapsed_s": round(elapsed, 1),
        "lanes_present": sorted(per_lane),
        "per_lane": per_lane,
        "tiered_pool": len(summary.get("all_scored") or []),
        "provisional_pool": len(prov),
        "provisional": [{"pmid": p["pmid"], "year": p.get("year"),
                         "design": p.get("stated_design")} for p in prov],
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("=" * 78)
    print("LIVE-PATH LANE PARITY — app.build_evidence_base_with_progress")
    print("=" * 78)
    arms = {}
    for arm in ("before", "after"):
        print("\n--- ARM: %s ---" % arm)
        arms[arm] = run(arm)

    a, b = arms["before"], arms["after"]
    print()
    print("  %-22s %14s %14s" % ("", "before", "after"))
    print("  %-22s %14d %14d" % ("lanes issued", len(a["lanes_present"]),
                                 len(b["lanes_present"])))
    print("  %-22s %14d %14d" % ("tiered pool", a["tiered_pool"], b["tiered_pool"]))
    print("  %-22s %14d %14d" % ("provisional pool", a["provisional_pool"],
                                 b["provisional_pool"]))
    print("  %-22s %14.1f %14.1f" % ("elapsed s", a["elapsed_s"], b["elapsed_s"]))
    print()
    print("  lanes gained: %s"
          % sorted(set(b["lanes_present"]) - set(a["lanes_present"])))
    print("  per-lane papers AFTER:")
    for k in sorted(b["per_lane"]):
        mark = "  <-- new" if k not in a["lanes_present"] else ""
        print("      %-16s %4d%s" % (k, b["per_lane"][k], mark))
    if b["provisional"]:
        print("  provisional admitted:")
        for p in b["provisional"]:
            print("      %-10s %-6s %s" % (p["pmid"], p["year"], p["design"]))

    (OUT / "live_path_lanes.json").write_text(
        json.dumps({"question": QUESTION, "arms": arms}, indent=1),
        encoding="utf-8")
    print("\nwrote %s" % (OUT / "live_path_lanes.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
