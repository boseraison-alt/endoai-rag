"""
Reconstruct a baseline file from one or more eval run logs.

`run_eval.py --update-baseline` writes into questions.json, which the next run
overwrites — so a sequence of runs launched as one batch leaves only the last.
This reads the logs instead, which are the durable record, and lets a baseline
be labelled by WHAT CODE IT MEASURED rather than by when it happened to run.

That distinction is the reason this exists: WORKLIST wants baseline_v2 (after
the in vitro tier) kept separate from baseline_v3 (after the per-tier quality
floors), and a batch of runs straddled the moment 1.5 landed.

    python eval/baseline_from_log.py --out eval/baseline_v2.json \
        --label "post-1.4 in vitro tier, pre-1.5" run1.log [run2.log ...]
"""
import argparse
import json
import re
import sys
from pathlib import Path

CASE_RE = re.compile(r"^(\S+)\s+\[pinned: (\w+)\]")
ROUTE_RE = re.compile(r"^  route\s+(\S*)")
PAPERS_RE = re.compile(r"^  papers (\d+)\s+(\{.*\})")
ESEARCH_RE = re.compile(
    r"^  esearch\s+(\d+) hits over (\d+) queries = ([\d.]+)/query "
    r"\((\d+) returned nothing, (\d+) search terms")


# The provisional lane, recovered from the log body rather than the summary.
#
# `run_eval.py` looped TIER_ORDER when these logs were written, and
# PROVISIONAL_KEY is not in TIER_ORDER, so the `papers N {...}` summary line
# EXCLUDES every provisional paper. The lane still ran and still printed what
# it admitted, so the number is recoverable:
#
#     [provisional] 43 of 400 recent papers are unclassified by MEDLINE;
#                   43 state a level2-or-above design, 0 state none or weaker
#     [provisional] cap 40: dropped 3 admitted paper(s) beyond the cap
#
# The admitted count is the SECOND number, and the cap line (when present) is
# what actually reached the evidence base.
PROV_RE = re.compile(r"^\s*\[provisional\].*?; (\d+) state a level2-or-above")
PROV_CAP_RE = re.compile(r"^\s*\[provisional\] cap (\d+): dropped (\d+)")


def parse(path):
    """Return {case_id: measurement} for one run log."""
    out, cur = {}, None
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        m = CASE_RE.match(line)
        if m:
            cur = {"id": m.group(1), "force_route": m.group(2)}
            out[cur["id"]] = cur
            continue
        if cur is None:
            continue
        m = PROV_RE.match(line)
        if m:
            cur["_prov_admitted"] = cur.get("_prov_admitted", 0) + int(m.group(1))
        m = PROV_CAP_RE.match(line)
        if m:
            cur["_prov_admitted"] = int(m.group(1))
        m = ROUTE_RE.match(line)
        if m:
            cur["route"] = m.group(1) or None
        m = PAPERS_RE.match(line)
        if m:
            cur["papers"] = int(m.group(1))
            try:
                cur["per_tier"] = json.loads(m.group(2).replace("'", '"'))
            except json.JSONDecodeError:
                pass
            # ONLY when the summary does not already carry the lane. Logs
            # written after run_eval.py was fixed include `provisional` in
            # per_tier, and adding the recovered number to those would double
            # count it. Self-correcting rather than dated: the condition is
            # "does this log already say", not "is this log old".
            n = cur.pop("_prov_admitted", 0)
            if n and "provisional" not in (cur.get("per_tier") or {}):
                cur.setdefault("per_tier", {})["provisional"] = n
                cur["papers"] += n
                cur["_provisional_recovered"] = n
        m = ESEARCH_RE.match(line)
        if m:
            cur.update(esearch_hits=int(m.group(1)), esearch_queries=int(m.group(2)),
                       hits_per_query=float(m.group(3)), esearch_empty=int(m.group(4)),
                       search_terms=int(m.group(5)))
    return out


NUMERIC = ("papers", "esearch_hits", "esearch_queries", "esearch_empty",
           "hits_per_query", "search_terms")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", required=True,
                    help="what code this baseline measured, not when it ran")
    args = ap.parse_args()

    runs = [parse(p) for p in args.logs]
    runs = [r for r in runs if r]
    if not runs:
        sys.exit("no cases parsed — are these eval run logs?")

    cases = {}
    for run in runs:
        for cid, m in run.items():
            dst = cases.setdefault(cid, {"force_route": m.get("force_route")})
            dst.setdefault("routes_observed", [])
            if m.get("route") and m["route"] not in dst["routes_observed"]:
                dst["routes_observed"].append(m["route"])
            for k in NUMERIC:
                if m.get(k) is not None:
                    dst.setdefault(k, {"runs": []})["runs"].append(m[k])
            if m.get("per_tier"):
                dst.setdefault("per_tier_runs", []).append(m["per_tier"])
    for c in cases.values():
        for k in NUMERIC:
            if k in c:
                r = c[k]["runs"]
                c[k].update(min=min(r), max=max(r))

    doc = {
        "_README": [
            f"Baseline: {args.label}",
            f"Folded from {len(runs)} run log(s): {', '.join(Path(p).name for p in args.logs)}.",
            "",
            "Retrieval-only — no answers were generated, so must_contain, banner,"
            " modules_non_empty and max_unsourced_numeric_modules were NOT"
            " evaluated. A green run here is not evidence that they hold.",
            "",
            "Search terms are LLM-generated: live-route counts move up to 3x"
            " between runs on the same question. Compare shape, not digits.",
        ],
        "label": args.label,
        "n_runs": len(runs),
        "provisional": len(runs) < 2,
        "cases": cases,
    }
    Path(args.out).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    prov = " (PROVISIONAL — single run)" if doc["provisional"] else ""
    print(f"{args.out}: {len(cases)} cases from {len(runs)} run(s){prov}")
    for cid, c in cases.items():
        p = (c.get("papers") or {}).get("runs", [])
        print(f"  {cid:<38} {str(c.get('force_route')):<8} papers={p}")


if __name__ == "__main__":
    main()
