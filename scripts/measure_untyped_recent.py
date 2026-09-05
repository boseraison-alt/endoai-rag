"""Item 4a — HOW BIG IS THE UNTYPED-RECENT BLIND SPOT? Measure only.

A paper MEDLINE has not yet indexed carries only `Journal Article`. Every
generated query ANDs a tier filter, and no tier filter admits a bare
`Journal Article`, so there is a rolling window -- MEDLINE's indexing lag --
in which no new paper on any topic can enter the pool. Sulaiman 42388091 is
one instance; the question this answers is how many there are.

WHAT IS COUNTED, per eval question: the papers a query on that question's own
topic terms returns, published in the last 18 months, whose ONLY publication
type is `Journal Article`. That is exactly the set a separate untyped lane
would admit, so the distribution IS the affordability question.

PER-QUERY DISTRIBUTION, not the mean. A mean over 29 questions would hide the
shape that decides the design: a median of 5 with one question at 300 needs a
cap, not a relevance gate; a uniform median of 60 needs a gate or nothing.

The threshold declared BEFORE running, so the result cannot be rationalised
afterwards: if the median exceeds ~40 per query, the lane needs a relevance
gate to be affordable, and this script says so rather than the next one
quietly building something unaffordable.

Nothing is changed. Usage:
    python scripts/measure_untyped_recent.py [--limit N] [--json out.json]
"""
import json
import os
import statistics
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import requests                   # noqa: E402
import endo_ai as E               # noqa: E402

MONTHS = 18
RETMAX = 200
MEDIAN_AFFORDABILITY_THRESHOLD = 40


def esearch(term, retmax=RETMAX):
    url = f"{E.NCBI_EUTILS_BASE}/esearch.fcgi"
    p = E._ncbi_params({"db": "pubmed", "term": term, "retmax": retmax,
                        "retmode": "json", "sort": "relevance"})
    r = requests.get(url, params=p, timeout=45)
    r.raise_for_status()
    j = r.json().get("esearchresult", {})
    return j.get("idlist", []), int(j.get("count", 0))


def pubtypes(pmids):
    """{pmid: [publication types]} in batches."""
    out = {}
    for i in range(0, len(pmids), 100):
        chunk = pmids[i:i + 100]
        url = f"{E.NCBI_EUTILS_BASE}/efetch.fcgi"
        p = E._ncbi_params({"db": "pubmed", "id": ",".join(chunk),
                            "retmode": "xml"})
        r = requests.get(url, params=p, timeout=60)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        for art in root.findall(".//PubmedArticle"):
            pmid = art.findtext(".//PMID") or ""
            types = [(n.text or "").strip()
                     for n in art.findall(".//PublicationTypeList/PublicationType")]
            out[pmid] = types
        time.sleep(0.35)
    return out


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    cases = json.load(open("eval/questions.json", encoding="utf-8"))["cases"]
    if limit:
        cases = cases[:limit]

    # The date window production would apply. Expressed the way PubMed reads
    # it, and the same string the lane itself would use.
    window = f'"last {MONTHS} months"[dp]'

    print("=" * 78)
    print("ITEM 4a — UNTYPED RECENT PAPERS PER EVAL QUESTION (measure only)")
    print("=" * 78)
    print("window: %s   retmax: %d   questions: %d" % (window, RETMAX, len(cases)))
    print("declared threshold: median > %d per query means the lane needs a "
          "relevance gate\n" % MEDIAN_AFFORDABILITY_THRESHOLD)

    rows = []
    for n, c in enumerate(cases, 1):
        q = c["question"]
        try:
            terms = E.generate_search_terms(q)
        except Exception as e:
            print("  %2d. %-34s TERM GENERATION FAILED: %s" % (n, c["id"][:34], e))
            continue

        # One query per topic group, each ANDed with the window and NO tier
        # filter -- which is exactly what the untyped lane would issue.
        seen, total_hits = {}, 0
        for t in terms[:4]:
            term = "(%s) AND %s" % (t, window)
            try:
                ids, count = esearch(term)
            except Exception as e:
                print("      esearch failed: %s" % str(e)[:60])
                continue
            total_hits += count
            time.sleep(0.35)
            if ids:
                for pmid, types in pubtypes(ids).items():
                    seen[pmid] = types

        untyped = sorted(p for p, t in seen.items()
                         if [x.lower() for x in t] == ["journal article"])
        rows.append({
            "id": c["id"], "question": q, "mode": c.get("mode", ""),
            "terms": terms[:4],
            "recent_returned": len(seen),
            "untyped_recent": len(untyped),
            "untyped_pmids": untyped[:50],
        })
        print("  %2d. %-38s recent=%-5d untyped=%-4d"
              % (n, c["id"][:38], len(seen), len(untyped)))

    counts = sorted(r["untyped_recent"] for r in rows)
    if not counts:
        print("\nno rows measured")
        return 1

    med = statistics.median(counts)
    print()
    print("=" * 78)
    print("DISTRIBUTION — untyped recent papers per query")
    print("=" * 78)
    print("  n questions      %d" % len(counts))
    print("  min              %d" % counts[0])
    print("  p25              %d" % counts[max(0, len(counts) // 4)])
    print("  MEDIAN           %d" % med)
    print("  p75              %d" % counts[min(len(counts) - 1, 3 * len(counts) // 4)])
    print("  max              %d" % counts[-1])
    print("  mean             %.1f   (reported for completeness; the median "
          "decides)" % statistics.fmean(counts))
    print("  total distinct   %d" % sum(counts))
    print()
    print("  full sorted distribution: %s" % counts)
    print()
    buckets = {"0": 0, "1-5": 0, "6-20": 0, "21-40": 0, "41-100": 0, ">100": 0}
    for c in counts:
        k = ("0" if c == 0 else "1-5" if c <= 5 else "6-20" if c <= 20
             else "21-40" if c <= 40 else "41-100" if c <= 100 else ">100")
        buckets[k] += 1
    for k, v in buckets.items():
        print("    %-8s %s" % (k, "#" * v + (" %d" % v if v else "")))

    print()
    if med > MEDIAN_AFFORDABILITY_THRESHOLD:
        print("  VERDICT: median %d EXCEEDS the declared %d. The lane needs a "
              "relevance\n  gate to be affordable. Reporting that rather than "
              "building it unguarded." % (med, MEDIAN_AFFORDABILITY_THRESHOLD))
    else:
        print("  VERDICT: median %d is at or under the declared %d. A separate "
              "lane is\n  affordable without a relevance gate; a per-query cap "
              "still bounds the tail\n  (max %d)."
              % (med, MEDIAN_AFFORDABILITY_THRESHOLD, counts[-1]))

    payload = {"window_months": MONTHS, "retmax": RETMAX,
               "threshold": MEDIAN_AFFORDABILITY_THRESHOLD,
               "median": med, "distribution": counts, "rows": rows}
    if "--json" in sys.argv:
        p = sys.argv[sys.argv.index("--json") + 1]
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).write_text(json.dumps(payload, indent=1), encoding="utf-8")
        print("\nwrote %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
