"""A55 item 1 — how often does the library declare coverage it does not have?

WHAT A54 ESTABLISHED. "MTA versus bioceramic as retrograde filling after
apicoectomy" routed to the LIBRARY on 200 hits and no PubMed lane ran. The
library held **0 of the 8** head-to-head papers. The coverage gate counted 149
hits for the material concept and 24 for the surgery concept against
`min_concept_papers = 3`, and passed. Every retrieval fix A54 considered was
irrelevant: the paper-set was decided by the ROUTE, not by any query.

WHAT THE GATE ACTUALLY MEASURES, and why it passed. `question_coverage` asks,
per concept group, "how many candidate papers mention any term in this group?"
Three groups each answered independently. Nothing anywhere asks how many papers
mention ALL THREE — which is the only count that means "the library holds papers
about this question" rather than "the library holds papers about each of these
subjects separately".

149 papers about MTA and 24 about apical surgery can be 173 papers of which
none is about MTA in apical surgery. That is exactly what A54 found.

So this measures, per question: the route, the per-group counts the gate reads,
the INTERSECTION it does not, and — for the LIBRARY-routed — how many of the
papers the live path would have fetched are missing from the library entirely.

Terms are frozen through the item C cache, so two runs of this ask PubMed and
the embedding the same questions (rule 38).

    python scripts/a55_false_coverage.py
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
from app import (RELEVANCE_GATE, multi_query_search,  # noqa: E402
                 apply_evidence_floor)

sys.path.insert(0, str(ROOT / "scripts"))
from measure_guideline_admission_rules import questions  # noqa: E402

A54_Q = "MTA versus bioceramic as retrograde filling after apicoectomy"
FLOOR = RELEVANCE_GATE["similarity_floor"]
MIN_HITS = RELEVANCE_GATE["min_hits"]
MIN_RELEVANT = RELEVANCE_GATE["min_relevant"]
MIN_CONCEPT = RELEVANCE_GATE["min_concept_papers"]
MAX_AGE = RELEVANCE_GATE["max_topic_age_yr"]
LIVE_RETMAX = 40


def _text(p):
    return ("%s %s" % (p.get("title") or "", p.get("abstract") or "")).lower()


def intersection_count(groups, papers):
    """Papers mentioning a term from EVERY group — the count the gate lacks.

    Matched the same way `question_coverage` matches, so this number and the
    per-group numbers are commensurable. A different matcher here would make
    the comparison meaningless.
    """
    n = 0
    for p in papers:
        t = _text(p)
        if all(any(term.lower() in t for term in g) for g in groups):
            n += 1
    return n


def live_pmids(term):
    """What the live path would have fetched, retrieval only."""
    try:
        r = E.ncbi_get(f"{E.NCBI_EUTILS_BASE}/esearch.fcgi",
                       params=E._ncbi_params({
                           "db": "pubmed", "term": term, "retmode": "json",
                           "retmax": LIVE_RETMAX, "sort": "relevance"}),
                       timeout=25)
        return [str(i) for i in
                r.json().get("esearchresult", {}).get("idlist", [])]
    except Exception as ex:
        print("      live esearch failed: %s" % ex)
        return []


def in_library(pmids):
    import rag
    if not pmids:
        return set()
    conn = rag.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT pmid FROM endo_papers_rag WHERE pmid = ANY(%s)",
                (list(pmids),))
    out = {r[0] for r in cur.fetchall()}
    cur.close()
    conn.close()
    return out


def main():
    qs = questions()
    if not any(q == A54_Q for _i, q in qs):
        qs.append(("a54-retrograde", A54_Q))

    print("=" * 78)
    print("A55 ITEM 1 — FALSE COVERAGE")
    print("=" * 78)
    print("  questions: %d   similarity floor %.2f   min_concept_papers %d"
          % (len(qs), FLOOR, MIN_CONCEPT))
    print()

    rows = []
    for qid, q in qs:
        term = E.generate_search_terms(q, mode="review")
        groups = E.coverage_groups(term)
        cands = multi_query_search(q, [term], limit=100)
        relevant = [r for r in cands
                    if float(r.get("similarity") or 0) >= FLOOR]
        cov = E.question_coverage(groups, relevant) if groups else []
        per_group = [c["hits"] for c in cov]
        weakest = min(per_group) if per_group else None
        inter = intersection_count([c["terms"] for c in cov], relevant) \
            if cov else len(relevant)

        newest = max((int(r["year"]) for r in relevant
                      if str(r.get("year", "")).isdigit()), default=0)
        from datetime import datetime as _dt
        age = _dt.now().year - newest if newest else 99
        has_high = any((r.get("level_key") or "") in
                       ("cochrane", "level1", "level2") for r in relevant)
        covers = (weakest is None) or (weakest >= MIN_CONCEPT)
        route = ("LIBRARY" if (len(cands) >= MIN_HITS
                               and len(relevant) >= MIN_RELEVANT
                               and has_high and age <= MAX_AGE and covers)
                 else "LIVE")

        missing, n_live = None, None
        if route == "LIBRARY":
            lp = live_pmids(term)
            have = in_library(lp)
            n_live = len(lp)
            missing = len(lp) - len(have)

        rows.append({"id": qid, "question": q, "route": route,
                     "groups": len(groups), "per_group": per_group,
                     "weakest": weakest, "intersection": inter,
                     "candidates": len(cands), "relevant": len(relevant),
                     "live_fetched": n_live,
                     "missing_from_library": missing,
                     # THE FRACTION, not just the count. Almost every
                     # LIBRARY-routed question misses SOME live paper -- the
                     # live path fetches 40 fresh PMIDs against a 3,449-row
                     # library -- so "missing > 0" cannot separate anything.
                     # What distinguishes the A54 case is that the library held
                     # NONE of the defining papers.
                     "missing_frac": (round(missing / n_live, 3)
                                      if n_live else None)})
        print("  %-28s %-7s groups=%d per_group=%-22s weakest=%-4s "
              "intersection=%-4d%s"
              % (qid[:28], route, len(groups),
                 str(per_group)[:22], weakest, inter,
                 "   missing live: %d" % missing if missing is not None else ""))

    lib = [r for r in rows if r["route"] == "LIBRARY"]
    thin = [r for r in lib if r["intersection"] < 10]
    print()
    print("  " + "-" * 70)
    print("  routed LIBRARY                        : %d/%d" % (len(lib), len(rows)))
    print("  ...with intersection < 10             : %d  (%.0f%% of LIBRARY)"
          % (len(thin), 100.0 * len(thin) / max(len(lib), 1)))
    miss = [r for r in lib if (r["missing_from_library"] or 0) > 0]
    print("  ...missing live papers                : %d" % len(miss))
    thin_miss = [r for r in thin if (r["missing_from_library"] or 0) > 0]
    print("  thin AND missing live papers          : %d/%d" % (len(thin_miss),
                                                               len(thin)))
    fat_miss = [r for r in lib
                if r["intersection"] >= 10 and (r["missing_from_library"] or 0) > 0]
    print("  HEALTHY intersection but still missing: %d" % len(fat_miss))

    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    json.dump({"floor": FLOOR, "min_concept": MIN_CONCEPT, "rows": rows},
              open("eval/reports/a55_false_coverage.json", "w",
                   encoding="utf-8"), indent=1)
    print("\n  wrote eval/reports/a55_false_coverage.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
