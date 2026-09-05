"""Item 1d, definitive — design extraction across ALL 29 questions.

WHY THIS EXISTS AND NOT JUST measure_design_extraction.py. That script ran on
three questions collected in their own pass, and `generate_multi_search_terms`
is a model call: two runs of the same question produce different topic groups
and therefore different pools. `case-opening-sparse` returned 482 untyped
papers in the collection pass and 138 in the 4a pass. Comparing a design count
from one draw against a distribution from another is comparing two different
samples and calling the difference a finding.

So this reads 4a's OWN stored untyped PMID lists -- the exact papers that run
counted -- fetches their abstracts, and extracts designs from those. One
measurement, one draw, 29 questions.

THRESHOLD, unchanged and declared before this run as it was before the last:
<=60 level2-or-above papers per query means build 4b; >60 means stop.

Usage:  python scripts/measure_design_all29.py [--json out.json]
"""
import collections
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
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests                   # noqa: E402
import endo_ai as E               # noqa: E402

SRC = ROOT / "eval" / "reports" / "a49_untyped_recent_4a.json"
CACHE = ROOT / "eval" / "reports" / "untyped_abstract_cache" / "_all29_abstracts.json"
THRESHOLD = 60


def fetch_abstracts(pmids, cache):
    """{pmid: {title, abstract}} with a disk cache so re-runs are free."""
    need = [p for p in pmids if p not in cache]
    for i in range(0, len(need), 150):
        chunk = need[i:i + 150]
        for attempt in range(5):
            try:
                r = requests.get(
                    f"{E.NCBI_EUTILS_BASE}/efetch.fcgi",
                    params=E._ncbi_params({"db": "pubmed", "id": ",".join(chunk),
                                           "retmode": "xml"}),
                    timeout=120)
                r.raise_for_status()
                root = ET.fromstring(r.text)
                break
            except Exception as e:
                root = None
                time.sleep(2.0 * (attempt + 1))
        if root is None:
            print("      batch failed, skipping %d ids" % len(chunk))
            continue
        for art in root.findall(".//PubmedArticle"):
            pmid = art.findtext(".//PMID") or ""
            parts = []
            for ab in art.findall(".//Abstract/AbstractText"):
                label = ab.get("Label") or ab.get("NlmCategory") or ""
                txt = "".join(ab.itertext()).strip()
                parts.append(("%s: %s" % (label, txt)) if label else txt)
            title_el = art.find(".//ArticleTitle")
            cache[pmid] = {
                "title": "".join(title_el.itertext()).strip() if title_el is not None else "",
                "abstract": "\n".join(parts),
            }
        print("      fetched %d/%d" % (min(i + 150, len(need)), len(need)))
        time.sleep(0.4)
    return cache


def main():
    data = json.loads(SRC.read_text(encoding="utf-8"))
    rows = data["rows"]

    cache = {}
    if CACHE.exists():
        cache = json.loads(CACHE.read_text(encoding="utf-8"))

    all_pmids = sorted({p for r in rows for p in r.get("untyped_pmids", [])})
    print("untyped PMIDs across 29 questions: %d (cached %d)"
          % (len(all_pmids), sum(1 for p in all_pmids if p in cache)))
    cache = fetch_abstracts(all_pmids, cache)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache), encoding="utf-8")

    print()
    print("=" * 78)
    print("ITEM 1d — DESIGN DISTRIBUTION, ALL 29 QUESTIONS, ONE DRAW")
    print("=" * 78)
    print("threshold declared before the run: <=%d level2-or-above per query\n"
          % THRESHOLD)

    out, totals = [], collections.Counter()
    for r in rows:
        pmids = r.get("untyped_pmids", [])
        by_rung = collections.Counter()
        admitted, no_abstract = [], 0
        for p in pmids:
            rec = cache.get(p)
            if not rec or not (rec.get("abstract") or "").strip():
                no_abstract += 1
                by_rung["(no abstract)"] += 1
                continue
            res = E.extract_stated_design(rec["abstract"], rec.get("title", ""))
            rung = res.get("rung") or "(none stated)"
            by_rung[rung] += 1
            if rung in E.DESIGN_RUNGS_AT_OR_ABOVE_LEVEL2:
                admitted.append(p)
        totals.update(by_rung)
        out.append({"id": r["id"], "n_untyped": len(pmids),
                    "no_abstract": no_abstract,
                    "by_rung": dict(by_rung),
                    "n_level2_or_above": len(admitted),
                    "admitted": admitted})
        print("  %-38s untyped=%-4d level2+=%-4d %s"
              % (r["id"][:38], len(pmids), len(admitted),
                 "" if len(admitted) <= THRESHOLD else "  <-- OVER"))

    counts = sorted(x["n_level2_or_above"] for x in out)
    print()
    print("  DISTRIBUTION of level2-or-above per query")
    print("    min %d | p25 %d | MEDIAN %d | p75 %d | max %d | total %d"
          % (counts[0], counts[len(counts) // 4], statistics.median(counts),
             counts[3 * len(counts) // 4], counts[-1], sum(counts)))
    print("    %s" % counts)
    print()
    print("  RUNG TOTALS across all 29 questions (%d papers)"
          % sum(totals.values()))
    for rung, n in totals.most_common():
        print("    %-18s %5d  (%.1f%%)"
              % (rung, n, 100.0 * n / max(1, sum(totals.values()))))

    over = [x for x in out if x["n_level2_or_above"] > THRESHOLD]
    print()
    print("=" * 78)
    if not over:
        print("  VERDICT: every one of the 29 questions is at or under %d."
              % THRESHOLD)
        print("  BUILD 4b.")
    else:
        print("  VERDICT: %d question(s) EXCEED %d: %s"
              % (len(over), THRESHOLD, [x["id"] for x in over]))
        print("  STOP — do not build 4b.")

    if "--json" in sys.argv:
        p = sys.argv[sys.argv.index("--json") + 1]
        Path(p).write_text(json.dumps(
            {"threshold": THRESHOLD, "rows": out,
             "distribution": counts, "rung_totals": dict(totals)}, indent=1),
            encoding="utf-8")
        print("\nwrote %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
