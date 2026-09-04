"""Why four known papers never reached the VPT pool. MEASURE ONLY.

Replays the EXACT 36 esearch calls the 2026-09-04 18:13 curriculum made
(recovered verbatim from pubmed_audit.jsonl), with production's own parameters
(sort=relevance), and reports for each target PMID: RETURNED or NOT RETURNED,
by which query, and at what RANK — because a paper returned at rank 78 of a
query capped at retmax=50 was reached by the query and cut by the cap, which is
a completely different defect from a query that never matches it.

Step 4 first: confirm the four PMIDs are real and correctly attributed. Two
records in the A2 audit described documents that do not exist; the same
scepticism applies in this direction.

Usage:  python scripts/diagnose_missed_papers.py [--json out.json]
"""
import json
import os
import sys
import time

sys.path.insert(0, os.getcwd())

import endo_ai as E  # noqa: E402

AUDIT = "pubmed_audit.jsonl"
WINDOW = ("2026-09-04T17:51", "2026-09-04T17:56")

# What we are looking for, as the batch describes them.
TARGETS = [
    ("Sulaiman 2026 haemostasis time / partial pulpotomy, Int Endod J",
     "Sulaiman[au] AND (haemostasis OR hemostasis) AND pulpotomy"),
    ("Hoang 2026 SR/MA 23 RCTs, mature posterior irreversible pulpitis",
     "Hoang[au] AND pulpitis AND (systematic review[pt] OR meta-analysis[pt])"),
    ("Komora 2024 network meta-analysis, bioactive materials",
     "Komora[au] AND (pulp OR pulpotomy OR pulpitis)"),
    ("EFCD-ESE-ORCA S3 deep caries (PMID 42018467)", "42018467[uid]"),
]


def esearch(term, retmax):
    """Production's own call: sort=relevance, same base, same params."""
    import requests
    url = f"{E.NCBI_EUTILS_BASE}/esearch.fcgi"
    p = E._ncbi_params({"db": "pubmed", "term": term, "retmax": retmax,
                        "retmode": "json", "sort": "relevance"})
    r = requests.get(url, params=p, timeout=30)
    r.raise_for_status()
    j = r.json().get("esearchresult", {})
    return j.get("idlist", []), int(j.get("count", 0))


def esummary(pmids):
    import requests
    if not pmids:
        return {}
    url = f"{E.NCBI_EUTILS_BASE}/esummary.fcgi"
    p = E._ncbi_params({"db": "pubmed", "id": ",".join(pmids),
                        "retmode": "json"})
    r = requests.get(url, params=p, timeout=30)
    r.raise_for_status()
    return r.json().get("result", {})


def step4_verify():
    print("=" * 74)
    print("STEP 4  ARE THE FOUR PAPERS REAL? (verify before concluding anything)")
    print("=" * 74)
    found = {}
    for label, probe in TARGETS:
        ids, n = esearch(probe, 5)
        time.sleep(0.4)
        if not ids:
            print("  %-58s NOT FOUND ON PUBMED" % label[:58])
            found[label] = None
            continue
        meta = esummary(ids[:3])
        time.sleep(0.4)
        best = ids[0]
        d = meta.get(best, {})
        print("  %-58s pmid=%s" % (label[:58], best))
        print("      %s" % (d.get("title") or "")[:96])
        print("      %s | %s" % ((d.get("source") or ""),
                                 (d.get("pubdate") or "")))
        if len(ids) > 1:
            print("      (%d candidates; using the top-ranked)" % len(ids))
        found[label] = best
    return found


def load_queries():
    rows = []
    with open(AUDIT, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            ts = str(r.get("ts", ""))
            if WINDOW[0] <= ts <= WINDOW[1]:
                rows.append(r)
    return rows


def main():
    targets = step4_verify()
    live = {v: k for k, v in targets.items() if v}
    if not live:
        print("\nNo target resolved; stopping rather than guessing.")
        return 1

    queries = load_queries()
    print()
    print("=" * 74)
    print("STEPS 1-2  REPLAY THE %d GENERATED QUERIES" % len(queries))
    print("=" * 74)
    print("Each is replayed at retmax=200 so a paper the query REACHES but the "
          "production\nretmax cut is visible as a rank, not as an absence.\n")

    hits = {p: [] for p in live}
    for i, r in enumerate(queries, 1):
        term = r.get("search_term")
        prod_retmax = r.get("n_returned")
        try:
            ids, total = esearch(term, 200)
        except Exception as e:
            print("  %2d. [%s] ERROR %s" % (i, r.get("level_key"), e))
            continue
        time.sleep(0.4)
        for pmid in live:
            if pmid in ids:
                rank = ids.index(pmid) + 1
                hits[pmid].append({"query": i, "tier": r.get("level_key"),
                                   "rank": rank,
                                   "prod_returned": prod_retmax,
                                   "total": total})
        if i % 6 == 0:
            print("    ...replayed %d/%d" % (i, len(queries)))

    print()
    print("=" * 74)
    print("STEP 3  THE BRANCH, PER TARGET")
    print("=" * 74)
    out = {}
    for pmid, label in live.items():
        h = hits[pmid]
        print("\n  %s" % label)
        print("  pmid %s" % pmid)
        if not h:
            print("    NOT RETURNED by any of the %d generated queries."
                  % len(queries))
            print("    -> the query never reached it. This is a QUERY defect.")
            out[pmid] = {"branch": "NOT RETURNED", "label": label, "hits": []}
            continue
        reachable = [x for x in h if x["rank"] <= (x["prod_returned"] or 0)]
        print("    RETURNED by %d quer%s:" % (len(h), "y" if len(h) == 1 else "ies"))
        for x in h:
            verdict = ("within production's retmax" if x["rank"] <= (x["prod_returned"] or 0)
                       else "BELOW THE CAP — production took %d, it ranked %d"
                            % (x["prod_returned"] or 0, x["rank"]))
            print("      q%-2d [%-12s] rank %-4d of %-6d  %s"
                  % (x["query"], x["tier"], x["rank"], x["total"], verdict))
        out[pmid] = {"branch": "RETURNED", "label": label, "hits": h,
                     "within_retmax": len(reachable)}
        if not reachable:
            print("    -> reached by the query but CUT BY THE RETMAX every "
                  "time. This is a CAP defect, not a query defect.")
        else:
            print("    -> inside production's retmax, so it entered the "
                  "candidate set and a LATER stage dropped it.")

    if "--json" in sys.argv:
        p = sys.argv[sys.argv.index("--json") + 1]
        json.dump({"targets": targets, "results": out},
                  open(p, "w", encoding="utf-8"), indent=1)
        print("\nwrote %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
