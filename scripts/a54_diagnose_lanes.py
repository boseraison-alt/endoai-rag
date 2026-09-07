"""A54 — fixture x lane diagnosis. Does the query match the paper, or not?

THE TABLE DECIDES THE FIX. For each fixture and each lane, the shipped lane
query for THIS question is ANDed with `<pmid>[uid]` and sent to PubMed.

  1 hit   the query CAN express the paper -> it was lost to ranking or the
          per-lane cap. The fix is retrieval depth or snowballing.
  0 hits  the query CANNOT express the paper -> vocabulary or a filter. The
          fix is the term generator or the filter, and no amount of depth
          would have recovered it.

Each zero is then narrowed by re-running without the domain filter and
without the publication-type filter, so "does not match" is separated from
"excluded by the domain filter" and "excluded by the tier filter".

TERMS ARE FROZEN. `generate_search_terms` is non-deterministic (rule 38), so
one generation is captured to `eval/logs/a54_terms.json` and reused by every
arm and every re-run. Diagnosing against terms that move would produce a
table that cannot be reproduced.

    python scripts/a54_diagnose_lanes.py
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

import endo_ai as E  # noqa: E402

QUESTION = ("MTA versus bioceramic as retrograde filling after apicoectomy")
TERMS_CACHE = Path("eval/logs/a54_terms.json")

FIXTURES = {
    "F1": "31078325", "F2": "27986096", "F3": "34499889",
    "F4": "38430316", "F5": "42634020",
    "F6": "42004800", "F7": "41555359", "F8": "38849637",
}


def esearch_count(term):
    try:
        r = E.ncbi_get(f"{E.NCBI_EUTILS_BASE}/esearch.fcgi",
                       params=E._ncbi_params({"db": "pubmed", "term": term,
                                              "retmode": "json",
                                              "retmax": 1}), timeout=25)
        return int(r.json().get("esearchresult", {}).get("count", 0))
    except Exception as ex:
        print("      esearch failed: %s" % ex)
        return -1


def frozen_terms():
    if TERMS_CACHE.exists():
        return json.loads(TERMS_CACHE.read_text(encoding="utf-8"))["terms"]
    t = E.generate_search_terms(QUESTION)
    TERMS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    TERMS_CACHE.write_text(json.dumps({"question": QUESTION, "terms": t},
                                      indent=1), encoding="utf-8")
    return t


def main():
    terms = frozen_terms()
    print("=" * 78)
    print("A54 — FIXTURE x LANE DIAGNOSIS")
    print("=" * 78)
    print("  question: %s" % QUESTION)
    print("  FROZEN TERMS (%s):" % TERMS_CACHE)
    print("    %s" % terms)
    print()

    groups = E.parse_search_term_groups(terms)
    print("  AND-GROUPS the generator produced: %d" % len(groups))
    for i, g in enumerate(groups):
        print("    g%d: %s" % (i, " | ".join(g)))
    print()

    filters = E.live_path_filters()
    lanes = ["cochrane"] + [k for k, _t, _l in E.tier_query_lanes()]

    # THE SHIPPED QUERY PER LANE, built the way fetch_papers builds it.
    lane_query = {}
    for lane in lanes:
        topic = terms
        guard = ""
        if lane == "guideline":
            topic = E.guideline_topic(terms)
            guard = getattr(E, "GUIDELINE_SPECIES_GUARD", "")
        lane_query[lane] = (
            f"({topic}) AND ({filters[lane]}) AND {E.ENDO_DOMAIN_FILTER} "
            f'NOT "Retracted Publication"[pt] '
            f'NOT "Retraction of Publication"[pt]{guard}')

    print("  LANE QUERIES — does the SUBJECT group appear alongside the")
    print("  MATERIAL group, or does any lane run the material alone?")
    for lane in lanes:
        q = lane_query[lane]
        topic = q.split(") AND (")[0].lstrip("(")
        print("    %-14s topic = %s" % (lane, topic[:150]))
    print()

    rows = {}
    for key, pmid in FIXTURES.items():
        rows[key] = {}
        print("  %s  PMID %s" % (key, pmid))
        for lane in lanes:
            n = esearch_count("(%s) AND %s[uid]" % (lane_query[lane], pmid))
            verdict = "MATCH" if n and n > 0 else "no"
            rows[key][lane] = verdict
            time.sleep(0.2)
        matched = [l for l, v in rows[key].items() if v == "MATCH"]
        print("      lanes that MATCH: %s" % (matched or "NONE"))

        if not matched:
            # narrow the zero: which clause excludes it?
            topic_only = esearch_count("(%s) AND %s[uid]" % (terms, pmid))
            dom_only = esearch_count("%s AND %s[uid]"
                                     % (E.ENDO_DOMAIN_FILTER, pmid))
            l1 = esearch_count("(%s) AND %s[uid]"
                               % (filters["level1"], pmid))
            rows[key]["_topic_alone"] = topic_only
            rows[key]["_domain_alone"] = dom_only
            rows[key]["_level1_filter_alone"] = l1
            print("      topic terms alone      : %s"
                  % ("matches" if topic_only else "DOES NOT MATCH"))
            print("      domain filter alone    : %s"
                  % ("passes" if dom_only else "EXCLUDED BY DOMAIN FILTER"))
            print("      level1 pubtype filter  : %s"
                  % ("matches" if l1 else "not a level1 design"))
            time.sleep(0.3)
        print()

    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    json.dump({"question": QUESTION, "terms": terms,
               "lane_query": lane_query, "rows": rows},
              open("eval/reports/a54_lane_diagnosis.json", "w"), indent=1)

    print("=" * 78)
    print("TABLE — fixture x lane")
    print("=" * 78)
    hdr = "  %-4s %-9s " % ("fx", "pmid") + " ".join(
        "%-7s" % l[:7] for l in lanes)
    print(hdr)
    for key, pmid in FIXTURES.items():
        line = "  %-4s %-9s " % (key, pmid) + " ".join(
            "%-7s" % ("YES" if rows[key].get(l) == "MATCH" else "-")
            for l in lanes)
        print(line)
    print()
    lost_to_rank = [k for k in FIXTURES
                    if any(v == "MATCH" for kk, v in rows[k].items()
                           if not kk.startswith("_"))]
    print("  matched by at least one lane (lost to RANKING or the CAP): %s"
          % (lost_to_rank or "none"))
    print("  matched by no lane (the QUERY cannot express them)      : %s"
          % ([k for k in FIXTURES if k not in lost_to_rank] or "none"))
    print("\n  wrote eval/reports/a54_lane_diagnosis.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
