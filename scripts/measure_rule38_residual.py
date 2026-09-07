"""Item C, rule-38 extension (2026-09-08) — the residual, with term noise gone.

Rule 38 says a pool A/B must report the same-build noise floor. Until today
that floor could not be attributed: the 2026-09-06 confinement proof measured
61/256 pools changed between two runs of an IDENTICAL build, and there was no
way to say how much of that was PubMed's own ranking and how much was
`generate_search_terms` writing a different boolean each time.

Term noise is now removed at the source — temperature 0 took the generator from
0/10 to 10/10 identical across 5 runs — and the term cache pins the string
besides. So running the SAME query string twice and diffing the returned PMIDs
isolates what is left: PubMed's own ranking and index churn.

This measures the residual directly, at the esearch layer, rather than by
rebuilding whole evidence bases: the query is held byte-identical by
construction, so any difference is the source's, not ours.

    python scripts/measure_rule38_residual.py
"""
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
from measure_guideline_admission_rules import questions  # noqa: E402

RETMAX = 50


def esearch(term):
    r = E.ncbi_get(f"{E.NCBI_EUTILS_BASE}/esearch.fcgi",
                   params=E._ncbi_params({
                       "db": "pubmed", "term": term, "retmode": "json",
                       "retmax": RETMAX, "sort": "relevance"}), timeout=25)
    return [str(i) for i in
            r.json().get("esearchresult", {}).get("idlist", [])]


def main():
    qs = questions()
    print("=" * 78)
    print("RULE 38 RESIDUAL — identical query string, run twice")
    print("=" * 78)
    print("  questions: %d   retmax: %d" % (len(qs), RETMAX))
    print("  term noise is held at zero by construction: the SAME string is")
    print("  sent both times, so any difference is PubMed's own.")
    print()

    differ_set, differ_order, rows = 0, 0, []
    for qid, q in qs:
        try:
            term = E.generate_search_terms(q, mode="review")
            a = esearch(term)
            b = esearch(term)
        except Exception as ex:
            print("  %-28s FAILED: %s" % (qid[:28], ex))
            continue
        same_set = set(a) == set(b)
        same_order = a == b
        differ_set += 0 if same_set else 1
        differ_order += 0 if same_order else 1
        rows.append({"id": qid, "n": len(a), "same_set": same_set,
                     "same_order": same_order,
                     "only_a": sorted(set(a) - set(b)),
                     "only_b": sorted(set(b) - set(a))})
        flag = "" if same_set else "   SET DIFFERS"
        if same_set and not same_order:
            flag = "   order only"
        print("  %-28s %3d hits%s" % (qid[:28], len(a), flag))

    n = len(rows)
    print()
    print("  " + "-" * 70)
    print("  pools with a DIFFERENT MEMBER SET : %d/%d  (%.0f%%)"
          % (differ_set, n, 100.0 * differ_set / max(n, 1)))
    print("  pools differing in ORDER only     : %d/%d"
          % (differ_order - differ_set, n))
    print()
    print("  RULE 38 RESIDUAL = %.0f%% of pools." % (100.0 * differ_set / max(n, 1)))
    print("  Compare: 24%% (61/256) measured 2026-09-06, when term noise and")
    print("  source noise were both present and could not be separated.")

    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    json.dump({"retmax": RETMAX, "n": n, "differ_set": differ_set,
               "differ_order_only": differ_order - differ_set, "rows": rows},
              open("eval/reports/night10_rule38_residual.json", "w",
                   encoding="utf-8"), indent=1)
    print("\n  wrote eval/reports/night10_rule38_residual.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
