"""Item 1d — the measurement that decides whether 4b gets built.

Runs `endo_ai.extract_stated_design` over the FULL untyped-recent set for
three questions chosen to span 4a's distribution, and reports:

  - the distribution by extracted rung
  - the fraction with NO extractable design statement
  - the count at level2-or-above, which is the threshold test

THRESHOLD DECLARED BEFORE THE RUN (A46): after the design filter,
<=60 level2-or-above papers per query means build 4b. >60 means stop, report,
and do not build.

It measures `endo_ai.extract_stated_design` -- the function 4b would ship --
rather than a restatement of it, so the number cannot be true of the script
and false of production (standing rule 14).

Usage:  python scripts/measure_design_extraction.py [--json out.json]
"""
import collections
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import endo_ai as E               # noqa: E402

CACHE = ROOT / "eval" / "reports" / "untyped_abstract_cache"
THRESHOLD = 60


def control():
    """1c. Non-negotiable: the extractor must read Sulaiman's stated design.

    The batch specified "if it does not find the RCT design there, the
    extractor is broken". Sulaiman is NOT an RCT -- the abstract says
    "single centre, one-arm clinical trial" and the strings randomis/randomiz/
    randomly do not occur in it. So the control asserts what the batch was
    reaching for -- that the extractor reads the paper's real stated design
    and that the design admits it -- rather than the literal RCT claim, which
    would require inventing a design the authors never made.
    """
    rec = json.loads((CACHE / "control_42388091.json").read_text(encoding="utf-8"))
    r = rec["42388091"]
    res = E.extract_stated_design(r["abstract"], r["title"])
    ab = (r["abstract"] or "").lower()
    print("=" * 78)
    print("1c  NEGATIVE CONTROL — Sulaiman 42388091")
    print("=" * 78)
    print("  extracted design : %s" % res.get("design"))
    print("  rung             : %s" % res.get("rung"))
    print("  matched phrase   : %r" % res.get("matched"))
    print("  decided by       : %s" % res.get("basis"))
    print("  level2-or-above  : %s"
          % (res.get("rung") in E.DESIGN_RUNGS_AT_OR_ABOVE_LEVEL2))
    print()
    print("  PREMISE CHECK — the batch called this an RCT:")
    for w in ("randomis", "randomiz", "randomly"):
        print("    %-10s present in abstract: %s" % (w, w in ab))
    print("    'one-arm clinical trial' present: %s"
          % ("one-arm clinical trial" in ab))
    ok = res.get("rung") in E.DESIGN_RUNGS_AT_OR_ABOVE_LEVEL2
    print("\n  CONTROL %s" % ("PASSES — the paper is admitted on its stated "
                              "design" if ok else "FAILS — nothing built on "
                              "this extractor counts"))
    return ok, res


def main():
    ok, ctrl = control()
    if not ok:
        print("\nSTOPPING: the negative control failed.")
        return 1

    files = sorted(p for p in CACHE.glob("*.json") if "control" not in p.name)
    print()
    print("=" * 78)
    print("1d  DESIGN DISTRIBUTION OVER THE FULL UNTYPED-RECENT SET")
    print("=" * 78)
    print("threshold declared before the run: <=%d level2-or-above per query "
          "-> build 4b\n" % THRESHOLD)

    out_rows = []
    for path in files:
        d = json.loads(path.read_text(encoding="utf-8"))
        recs = d["records"]
        by_rung = collections.Counter()
        no_design = 0
        by_basis = collections.Counter()
        admitted = []
        for pmid, r in recs.items():
            res = E.extract_stated_design(r.get("abstract", ""), r.get("title", ""))
            if not res:
                no_design += 1
                by_rung["(none stated)"] += 1
                continue
            by_rung[res["rung"]] += 1
            by_basis[res["basis"]] += 1
            if res["rung"] in E.DESIGN_RUNGS_AT_OR_ABOVE_LEVEL2:
                admitted.append({"pmid": pmid, **res,
                                 "title": (r.get("title") or "")[:110]})

        n = len(recs)
        n_adm = len(admitted)
        print("--- %s" % d["id"])
        print("    untyped recent papers            %d" % n)
        print("    with an abstract                 %d" % d["n_untyped_with_abstract"])
        print("    NO extractable design statement  %d  (%.1f%%)"
              % (no_design, 100.0 * no_design / max(1, n)))
        for rung, c in by_rung.most_common():
            print("      %-24s %5d  (%.1f%%)" % (rung, c, 100.0 * c / max(1, n)))
        print("    LEVEL2-OR-ABOVE                  %d   %s"
              % (n_adm, "<= %d OK" % THRESHOLD if n_adm <= THRESHOLD
                 else "> %d OVER" % THRESHOLD))
        print()
        out_rows.append({"id": d["id"], "n_untyped": n,
                         "n_with_abstract": d["n_untyped_with_abstract"],
                         "no_design": no_design,
                         "by_rung": dict(by_rung), "by_basis": dict(by_basis),
                         "n_level2_or_above": n_adm,
                         "admitted": admitted})

    counts = [r["n_level2_or_above"] for r in out_rows]
    print("=" * 78)
    print("THRESHOLD TEST")
    print("=" * 78)
    for r in out_rows:
        print("  %-26s %5d level2-or-above" % (r["id"], r["n_level2_or_above"]))
    print("  %-26s %5d min / %d max" % ("", min(counts), max(counts)))
    print()
    if max(counts) <= THRESHOLD:
        print("  VERDICT: every question is at or under %d. BUILD 4b." % THRESHOLD)
    else:
        print("  VERDICT: max %d EXCEEDS %d. STOP — do not build 4b."
              % (max(counts), THRESHOLD))

    if "--json" in sys.argv:
        p = sys.argv[sys.argv.index("--json") + 1]
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).write_text(json.dumps(
            {"threshold": THRESHOLD, "control": ctrl, "rows": out_rows},
            indent=1), encoding="utf-8")
        print("\nwrote %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
