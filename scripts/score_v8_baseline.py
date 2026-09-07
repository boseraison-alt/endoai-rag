"""Item D — score the three v8 runs and build `eval/baseline_v8.json`.

The runs are already done and their stdout is on disk. This reads those logs
and NOTHING ELSE: no retrieval is repeated, no case is re-run, no expectation
is touched. A failing criterion is quoted verbatim from the run that produced
it rather than paraphrased.

TWO ROUTE READINGS, side by side, which is the whole point of the exercise:

  inferred   what `run_eval` printed — derived from tier `source` values, a
             proxy that predates the library union's third source
  recorded   what the ROUTER decided, read from the router's own printed
             statement, not re-derived from the pools

The recorded reading is recoverable from these logs because the decision has
exactly three values and each leaves its own distinct mark:

  live             `[rag_gate] ... actual=LIVE` with no force_route=library,
                   or `[rag_gate] force_route=live — library skipped`
  library-forced   `[force_route=library]` on the rag_gate line
  library-fallback `_log_library_fallback` appends to
                   eval/logs/library_fallback.jsonl before the fallback build
                   runs — the two are adjacent statements, so no fallback can
                   happen without a line

That last one is checked by MTIME, not by content: the file must not have been
written during the run window. Reading a result file without its mtime is how a
fixed leak read as open earlier tonight.

    python scripts/score_v8_baseline.py /tmp/v8_run1.log /tmp/v8_run2.log ...
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BAR = "=" * 70
COMMIT = re.compile(r"Serving git ([0-9a-f]{7,40}) \(imported ([^)]+)\)")
HEAD = re.compile(r"^(\S+)\s+\[(pinned: \w+|route not pinned)\]\s*$")
ROUTE = re.compile(r"^  route\s+(\S+)\s*$")
PAPERS = re.compile(r"^  papers (\d+)\s+(\{.*\})\s*$")
ESEARCH = re.compile(
    r"^  esearch\s+(\d+) hits over (\d+) queries = ([\d.]+)/query "
    r"\((\d+) returned nothing, (\d+) search terms")
GUIDE = re.compile(r"^  guideline\s+(\d+) lane quer\(ies\), (\d+) returned")
UNION = re.compile(r"\[union\] library contributed (\d+) row")
DROPPED = re.compile(
    r"\[guideline_status\] dropped (\d+) non-current guideline\(s\) "
    r"from ([\w-]+): (.+)$")
GATE_UNPINNED = re.compile(r"\[rag_gate\] would-have-routed=(\w+) \| actual=(\w+)")
GATE_PINNED = re.compile(r"\[rag_gate\] force_route=(\w+) — library skipped")
CACHE_HIT = "[search_terms] cache hit"
FAILLINE = re.compile(r"^  FAIL\s+(.*)$")
# Any of these means this run's esearch numbers describe something other than
# the queries, and run_eval skips its esearch assertions accordingly.
CONTAM = ("search terms in the audit window", "never reached NCBI")


def parse(path):
    """One log -> {case_id: {...}}, plus run-level facts."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")
    m = COMMIT.search(text)
    run = {"log": str(path),
           "commit": m.group(1) if m else None,
           "imported": m.group(2) if m else None,
           "mode": "SYNTHESIS" if "mode: SYNTHESIS" in text else "RETRIEVAL-ONLY",
           "term_cache_hits": text.count(CACHE_HIT),
           "cases": {}}

    cur = None
    for i, ln in enumerate(lines):
        if ln.startswith(BAR) and i + 1 < len(lines):
            h = HEAD.match(lines[i + 1])
            if h:
                pin = (h.group(2).split(": ")[1]
                       if h.group(2).startswith("pinned") else None)
                cur = {"id": h.group(1), "force_route": pin,
                       "route": None, "route_decision": None,
                       "gate_says_library": None,
                       "papers": None, "per_tier": None,
                       "esearch_hits": None, "esearch_queries": None,
                       "hits_per_query": None, "esearch_empty": None,
                       "search_terms": None,
                       "guideline_queries": None, "guideline_empty": None,
                       "union_rows": None, "guideline_dropped": [],
                       "contaminated": False,
                       "passed": None, "failures": []}
                run["cases"][h.group(1)] = cur
                continue
        if cur is None:
            continue

        g = GATE_PINNED.search(ln)
        if g:
            # A pin of `live` IS the router's decision; nothing else runs.
            cur["route_decision"] = ("library-forced" if g.group(1) == "library"
                                     else "live")
        g = GATE_UNPINNED.search(ln)
        if g:
            cur["gate_says_library"] = (g.group(1) == "LIBRARY")
            cur["route_decision"] = ("library-forced"
                                     if "[force_route=library]" in ln else "live")

        if any(c in ln for c in CONTAM):
            cur["contaminated"] = True

        m2 = ROUTE.match(ln)
        if m2:
            cur["route"] = m2.group(1)
        m2 = PAPERS.match(ln)
        if m2:
            cur["papers"] = int(m2.group(1))
            try:
                cur["per_tier"] = json.loads(m2.group(2).replace("'", '"'))
            except Exception:
                cur["per_tier"] = {}
        m2 = ESEARCH.match(ln)
        if m2:
            cur["esearch_hits"] = int(m2.group(1))
            cur["esearch_queries"] = int(m2.group(2))
            cur["hits_per_query"] = float(m2.group(3))
            cur["esearch_empty"] = int(m2.group(4))
            cur["search_terms"] = int(m2.group(5))
        m2 = GUIDE.match(ln)
        if m2:
            cur["guideline_queries"] = int(m2.group(1))
            cur["guideline_empty"] = int(m2.group(2))
        m2 = UNION.search(ln)
        if m2:
            cur["union_rows"] = int(m2.group(1))
        m2 = DROPPED.search(ln)
        if m2:
            cur["guideline_dropped"].append(
                {"n": int(m2.group(1)), "where": m2.group(2),
                 "ids": m2.group(3).strip()})
        m2 = FAILLINE.match(ln)
        if m2:
            cur["failures"].append(m2.group(1).strip())
            cur["passed"] = False
        if ln.strip() == "PASS" and cur["passed"] is None:
            cur["passed"] = True
    return run


def fallback_window(runs):
    """Did the router fall back during the runs? Asked of the file's MTIME."""
    p = ROOT / "eval" / "logs" / "library_fallback.jsonl"
    if not p.exists():
        return "no fallback log exists", True
    mt = datetime.fromtimestamp(p.stat().st_mtime)
    starts = [r["imported"] for r in runs if r.get("imported")]
    first = min(starts) if starts else None
    quiet = bool(first) and mt.isoformat() < first
    return ("%s last written %s; first run imported %s"
            % (p, mt.isoformat(timespec="seconds"), first)), quiet


def main():
    logs = sys.argv[1:] or ["/tmp/v8_run1.log", "/tmp/v8_run2.log",
                            "/tmp/v8_run3.log"]
    runs = [parse(p) for p in logs]

    print("=" * 78)
    print("ITEM D — V8 BASELINE, THREE RUNS")
    print("=" * 78)
    commits = {r["commit"] for r in runs}
    print("  commit(s)      : %s" % ", ".join(sorted(c or "?" for c in commits)))
    print("  mode           : %s" % ", ".join(sorted({r["mode"] for r in runs})))
    for r in runs:
        n = len(r["cases"])
        p = sum(1 for c in r["cases"].values() if c["passed"])
        print("  %-18s %2d/%2d passed   term-cache hits %d   imported %s"
              % (Path(r["log"]).name, p, n, r["term_cache_hits"], r["imported"]))
    print()

    ids = sorted({i for r in runs for i in r["cases"]})
    contam = [(r["log"], c["id"]) for r in runs for c in r["cases"].values()
              if c["contaminated"]]
    print("  CONTAMINATION (rule: a run whose esearch numbers describe another")
    print("  process cannot be scored on them)")
    print("    cases flagged contaminated : %d" % len(contam))
    for lg, cid in contam:
        print("      %s  %s" % (Path(lg).name, cid))
    print()

    # ── per-question 3-run table ────────────────────────────────────────────
    print("  PER-QUESTION, THREE RUNS   (P=pass F=fail)")
    print("  %-44s %-7s %-17s %s" % ("case", "pass", "papers", "hits/query"))
    always, sometimes = [], []
    for cid in ids:
        cs = [r["cases"].get(cid) for r in runs]
        marks = "".join("P" if c and c["passed"] else
                        ("F" if c else "-") for c in cs)
        pap = "/".join(str(c["papers"]) if c and c["papers"] is not None else "-"
                       for c in cs)
        hpq = "/".join(("%.1f" % c["hits_per_query"])
                       if c and c["hits_per_query"] is not None else "-"
                       for c in cs)
        print("  %-44s %-7s %-17s %s" % (cid[:44], marks, pap, hpq))
        if marks == "FFF":
            always.append(cid)
        elif "F" in marks:
            sometimes.append(cid)
    print()

    print("  FAILED 3 OF 3 — the criterion, quoted, and the evidence base")
    if not always:
        print("    none")
    for cid in always:
        print("    %s" % cid)
        for ri, r in enumerate(runs, 1):
            c = r["cases"].get(cid) or {}
            print("      run %d  papers=%s  %s" % (ri, c.get("papers"),
                                                   c.get("per_tier")))
            for f in c.get("failures", []):
                print("        FAIL  %s" % f)
    print()
    print("  FAILED INTERMITTENTLY (%d)" % len(sometimes))
    for cid in sometimes:
        print("    %s" % cid)
        for ri, r in enumerate(runs, 1):
            c = r["cases"].get(cid) or {}
            for f in c.get("failures", []):
                print("      run %d  FAIL  %s" % (ri, f))
    print()

    # ── the two route readings ──────────────────────────────────────────────
    print("=" * 78)
    print("  ROUTE — INFERRED vs THE ROUTER'S RECORDED DECISION")
    print("=" * 78)
    msg, quiet = fallback_window(runs)
    print("  fallback log   : %s" % msg)
    print("  fell back      : %s" % ("NO — not written during the runs" if quiet
                                     else "POSSIBLY — written inside the window"))
    inferred_c, recorded_c, disagree = Counter(), Counter(), []
    for r in runs:
        for c in r["cases"].values():
            inferred_c[str(c["route"])] += 1
            recorded_c[str(c["route_decision"])] += 1
            if c["route"] != _norm(c["route_decision"]):
                disagree.append((Path(r["log"]).name, c["id"],
                                 c["route"], c["route_decision"]))
    print("  INFERRED : %s" % dict(inferred_c))
    print("  RECORDED : %s" % dict(recorded_c))
    print("  case-runs where the two disagree: %d of %d"
          % (len(disagree), sum(inferred_c.values())))
    for lg, cid, i, rec in disagree[:20]:
        print("    %-14s %-40s inferred=%-14s recorded=%s"
              % (lg, cid[:40], i, rec))
    print()

    # `library-union` as a tier source is the artefact the inferred derivation
    # cannot name. Reported, not patched.
    artefacts = [(Path(r["log"]).name, c["id"], c["route"])
                 for r in runs for c in r["cases"].values()
                 if c["route"] and c["route"] not in ("live", "library")]
    print("  ROUTE ARTEFACTS (a route string the derivation cannot classify)")
    if artefacts:
        for lg, cid, rt in artefacts:
            print("    %-14s %-40s route=%s" % (lg, cid[:40], rt))
    else:
        print("    none — every case-run inferred cleanly as live or library")
    print()

    # ── the guard, observed in production ───────────────────────────────────
    drops = defaultdict(Counter)
    for r in runs:
        for c in r["cases"].values():
            for d in c["guideline_dropped"]:
                drops[d["where"]][d["ids"]] += d["n"]
    print("  NON-CURRENT GUIDELINES DROPPED DURING THE BASELINE (item 3's guard")
    print("  firing on live traffic, not in a fixture)")
    total = 0
    for where, ids_ in sorted(drops.items()):
        for gid, n in ids_.most_common():
            print("    %-16s %-34s %d" % (where, gid, n))
            total += n
    print("    %-16s %-34s %d" % ("", "TOTAL", total))
    print()

    # ── the baseline file ───────────────────────────────────────────────────
    cases = {}
    for cid in ids:
        cs = [r["cases"].get(cid) for r in runs]
        e = {"force_route": next((c["force_route"] for c in cs if c), None),
             "routes_observed": sorted({c["route"] for c in cs if c and c["route"]}),
             "route_decisions": sorted({c["route_decision"] for c in cs
                                        if c and c["route_decision"]}),
             "passed_runs": [bool(c and c["passed"]) for c in cs],
             "per_tier_runs": [c["per_tier"] if c else None for c in cs]}
        for field in ("papers", "esearch_hits", "esearch_queries",
                      "esearch_empty", "hits_per_query", "search_terms",
                      "union_rows"):
            vals = [c[field] for c in cs if c and c[field] is not None]
            if vals:
                e[field] = {"runs": [c[field] if c else None for c in cs],
                            "min": min(vals), "max": max(vals)}
        fails = sorted({f for c in cs if c for f in c["failures"]})
        if fails:
            e["failing_criteria"] = fails
        cases[cid] = e

    doc = {
        "_README": (
            "v8 — the first baseline taken with routing LIVE BY DEFAULT "
            "(2026-09-09). Every `force_route: library` pin was removed from "
            "questions.json before this ran, and 14 `expect.route` values were "
            "flipped library->live because that criterion was the routing pin "
            "wearing a different hat. Every other criterion — the 36512807 "
            "expectation, every min_papers floor — was left untouched, so a "
            "case failing one of those is a FINDING, not a tuning target. "
            "RETRIEVAL-ONLY: answer-level assertions (must_contain, banner, "
            "modules_non_empty) were NOT evaluated, exactly as in v7, which is "
            "what makes the two comparable."),
        "label": "v8",
        "routing_mode": "live-default",
        "commit": sorted(c for c in commits if c)[0] if commits else None,
        "n_runs": len(runs),
        "mode": sorted({r["mode"] for r in runs}),
        "runs": [{"log": Path(r["log"]).name, "imported": r["imported"],
                  "passed": sum(1 for c in r["cases"].values() if c["passed"]),
                  "n": len(r["cases"]),
                  "term_cache_hits": r["term_cache_hits"]} for r in runs],
        "route_readings": {"inferred": dict(inferred_c),
                           "recorded": dict(recorded_c),
                           "disagreements": len(disagree),
                           "fallback_log": msg,
                           "fell_back_during_runs": not quiet},
        "failed_3_of_3": always,
        "failed_intermittently": sometimes,
        "cases": cases,
    }
    out = ROOT / "eval" / "baseline_v8.json"
    out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print("  wrote %s  (%d cases)" % (out, len(cases)))
    return 0


def _norm(recorded):
    if not recorded:
        return None
    return "library" if str(recorded).startswith("library") else "live"


if __name__ == "__main__":
    sys.exit(main())
