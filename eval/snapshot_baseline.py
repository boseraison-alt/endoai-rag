"""
Capture eval/baseline.json from one or more eval runs.

`run_eval.py --update-baseline` writes a POINT measurement into each case in
questions.json. A point is the wrong shape for this system: search terms are
LLM-generated and PubMed results move, so a single number reads as a hard
threshold and the next run "regresses" against it for no reason.

This tool accumulates runs and stores RANGES. Until at least two runs exist the
file is marked `provisional: true`, so nobody mistakes one observation for a
tracked metric — which is the exact mistake this whole eval set was created to
stop the project making about itself.

    python eval/snapshot_baseline.py --add        # fold questions.json into baseline.json
    python eval/snapshot_baseline.py --show       # print the current state
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
QUESTIONS = HERE / "questions.json"
BASELINE = HERE / "baseline.json"

# Metrics worth tracking as ranges. Anything else in a case baseline is prose.
NUMERIC = ("papers", "esearch_hits", "esearch_queries", "esearch_empty",
           "hits_per_query", "search_terms", "esearch_failed")


def _fold(existing, value):
    """Merge one observation into a {min,max,runs:[...]} record."""
    if value is None:
        return existing
    obs = list((existing or {}).get("runs", []))
    obs.append(value)
    return {"min": min(obs), "max": max(obs), "runs": obs}


def add_run(stamp):
    if not QUESTIONS.exists():
        sys.exit("questions.json missing")
    qdoc = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    base = (json.loads(BASELINE.read_text(encoding="utf-8"))
            if BASELINE.exists() else {"_README": [], "runs": [], "cases": {}})

    base.setdefault("cases", {})
    base.setdefault("runs", [])
    base["runs"].append(stamp)
    n_runs = len(base["runs"])

    for case in qdoc.get("cases", []):
        cid = case["id"]
        src = case.get("baseline") or {}
        dst = base["cases"].setdefault(cid, {"force_route": case.get("force_route")})
        dst["force_route"] = case.get("force_route")
        if src.get("route"):
            routes = set(dst.get("routes_observed", []))
            routes.add(src["route"])
            dst["routes_observed"] = sorted(routes)
        for m in NUMERIC:
            if src.get(m) is not None:
                dst[m] = _fold(dst.get(m), src[m])
        if src.get("per_tier"):
            dst.setdefault("per_tier_runs", []).append(src["per_tier"])

    base["provisional"] = n_runs < 2
    base["_README"] = [
        f"Eval baselines, folded over {n_runs} run(s): {', '.join(base['runs'])}.",
        "",
        "PROVISIONAL — a single run is an observation, not a baseline. Do not"
        " treat these numbers as thresholds." if base["provisional"] else
        "Ranges over multiple runs. Assertions in questions.json are FLOORS;"
        " these ranges are for spotting drift, not for gating.",
        "",
        "Every number is retrieval-only unless a run was made with"
        " --synthesis-subset. Search terms are LLM-generated, so counts move"
        " between runs; compare the shape, not the digits.",
        "",
        "Regenerate: python eval/run_eval.py --update-baseline"
        " && python eval/snapshot_baseline.py --add",
    ]
    BASELINE.write_text(json.dumps(base, indent=2) + "\n", encoding="utf-8")
    flag = "PROVISIONAL" if base["provisional"] else "ranges over %d runs" % n_runs
    print(f"baseline.json updated — {len(base['cases'])} cases, {flag}")
    return base


def show():
    if not BASELINE.exists():
        sys.exit("no baseline.json yet")
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    print(f"runs: {base.get('runs')}   provisional={base.get('provisional')}")
    print(f"{'case':<38} {'route':<9} {'papers':<16}")
    for cid, c in base.get("cases", {}).items():
        p = c.get("papers") or {}
        rng = (f"{p['min']}-{p['max']}" if p and p["min"] != p["max"]
               else (str(p.get("min")) if p else "-"))
        print(f"  {cid:<36} {str(c.get('force_route')):<9} {rng:<16}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--add", action="store_true", help="fold questions.json in")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--stamp", default=None, help="label for this run")
    args = ap.parse_args()
    if args.add:
        add_run(args.stamp or datetime.now().strftime("%Y-%m-%dT%H:%M"))
    if args.show or not args.add:
        show()


if __name__ == "__main__":
    main()
