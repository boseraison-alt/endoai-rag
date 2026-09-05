"""Item 4a — HOW BIG IS THE UNTYPED-RECENT BLIND SPOT? Measure only.

CORRECTED 2026-09-04 (second batch). The first version of this script was
WRONG IN TWO WAYS AT ONCE and its published median of 426 is withdrawn.

  1. It called `generate_search_terms(q)`, which returns a STRING -- the single
     primary PubMed query -- and then sliced it as `terms[:4]`, which takes the
     first FOUR CHARACTERS. The queries actually issued were `("(") AND "last
     18 months"[dp]`, `("l") AND ...` and so on. The list of topic groups comes
     from `generate_multi_search_terms(question, primary_term)`, a different
     function.
  2. It omitted `ENDO_DOMAIN_FILTER`. Production ANDs it into every query
     (`fetch_papers`), and without it nothing constrains results to dentistry.

Together those made the "untyped recent papers on this topic" count into
"recent papers in all of PubMed matching a single character". The pool it was
measuring contained celery genomics, vanadium-oxide catalysis, Fusarium
fungal genetics and Chinese health policy in Africa. The retmax cap of 200
per group hid the absurdity by holding the totals near 600.

The error was found by reading the abstracts the extractor could not classify
rather than by trusting the count -- which is the only reason it was found at
all. Eighth instrument error in this project; the first of them mine.

This version issues PRODUCTION'S OWN QUERY SHAPE, built by the same
expression `fetch_papers` uses, so the thing measured is the thing that runs.

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
RETMAX = 500
MEDIAN_AFFORDABILITY_THRESHOLD = 40


def topic_groups(question):
    """The topic groups production would issue for this question.

    Two calls, not one, and this is where the first version went wrong:
    `generate_search_terms` returns the single primary query STRING, and
    `generate_multi_search_terms` expands it into the list of groups. Slicing
    the string gave four one-character queries.
    """
    primary = E.generate_search_terms(question)
    groups = E.generate_multi_search_terms(question, primary)
    if isinstance(groups, str):          # defensive: never slice a string
        groups = [groups]
    out, seen = [], set()
    for g in [primary] + list(groups or []):
        g = (g or "").strip()
        if g and g not in seen:
            seen.add(g)
            out.append(g)
    return out


def untyped_lane_query(topic, months=MONTHS):
    """Exactly what the untyped lane would issue: production's own query with
    the tier filter replaced by the date window, domain filter and retraction
    exclusions intact (`fetch_papers`)."""
    return (f'({topic}) AND ("last {months} months"[dp]) '
            f'AND {E.ENDO_DOMAIN_FILTER} '
            f'NOT "Retracted Publication"[pt] NOT "Retraction of Publication"[pt]')


def _get(url, params, timeout, what):
    """One NCBI call with backoff.

    At retmax=500 across seven topic groups and 29 questions this issues a few
    thousand efetch batches, and NCBI resets the connection partway through
    ("An existing connection was forcibly closed by the remote host"). A
    measurement that dies at question 14 is a measurement that does not exist,
    so every call retries with widening backoff rather than the run failing.
    """
    last = None
    for attempt in range(5):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError("%s failed after 5 attempts: %s" % (what, last))


def esearch(term, retmax=RETMAX):
    url = f"{E.NCBI_EUTILS_BASE}/esearch.fcgi"
    p = E._ncbi_params({"db": "pubmed", "term": term, "retmax": retmax,
                        "retmode": "json", "sort": "relevance"})
    r = _get(url, p, 45, "esearch")
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
        try:
            r = _get(url, p, 60, "efetch")
        except Exception as e:
            print("      efetch batch skipped: %s" % str(e)[:70])
            continue
        try:
            root = ET.fromstring(r.text)
        except Exception:
            continue
        for art in root.findall(".//PubmedArticle"):
            pmid = art.findtext(".//PMID") or ""
            types = [(n.text or "").strip()
                     for n in art.findall(".//PublicationTypeList/PublicationType")]
            out[pmid] = types
        time.sleep(0.5)
    return out


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    cases = json.load(open("eval/questions.json", encoding="utf-8"))["cases"]
    if limit:
        cases = cases[:limit]

    print("=" * 78)
    print("ITEM 4a — UNTYPED RECENT PAPERS PER EVAL QUESTION (measure only)")
    print("=" * 78)
    print("window: last %d months   retmax: %d   questions: %d"
          % (MONTHS, RETMAX, len(cases)))
    print("query shape: production's own — topic AND window AND domain filter "
          "NOT retracted")
    print("declared threshold: median > %d per query means the lane needs a "
          "relevance gate\n" % MEDIAN_AFFORDABILITY_THRESHOLD)

    rows = []
    for n, c in enumerate(cases, 1):
        q = c["question"]
        try:
            groups = topic_groups(q)
        except Exception as e:
            print("  %2d. %-34s TERM GENERATION FAILED: %s" % (n, c["id"][:34], e))
            continue

        seen, total_hits = {}, 0
        for t in groups:
            try:
                ids, count = esearch(untyped_lane_query(t))
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
            "n_groups": len(groups), "terms": groups,
            "total_hits_reported": total_hits,
            "recent_returned": len(seen),
            "untyped_recent": len(untyped),
            "untyped_pmids": untyped,
        })
        print("  %2d. %-34s groups=%d recent=%-5d untyped=%-4d"
              % (n, c["id"][:34], len(groups), len(seen), len(untyped)))

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
