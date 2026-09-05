"""Item 1a — collect the FULL untyped-recent set and its abstracts, for 3 questions.

4a stored only the first 50 PMIDs per question, which is enough to size the
problem and not enough to answer the threshold test in absolute terms: "how
many level2-or-above papers per query" needs the whole set, not a sample of it.

So this re-collects, for three questions chosen to span 4a's distribution:

    diabetes-outcomes      243   the minimum
    case-opening-sparse    426   the median
    sonic-vs-ultrasonic    621   the maximum

If even the maximum clears the threshold the lane is affordable everywhere; if
the minimum fails it, it is affordable nowhere. Three points at the extremes
and the middle answer the question that 29 points at the middle would not.

Abstracts are cached to disk so the extractor can be iterated without
re-fetching 1,300 records from PubMed.

Usage:  python scripts/collect_untyped_abstracts.py
"""
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import requests                   # noqa: E402
import endo_ai as E               # noqa: E402
sys.path.insert(0, str(ROOT / "scripts"))
import measure_untyped_recent as MU   # noqa: E402  (shared query builders)

CACHE = ROOT / "eval" / "reports" / "untyped_abstract_cache"
TARGETS = ["diabetes-outcomes", "case-opening-sparse", "sonic-vs-ultrasonic"]
MONTHS = 18
RETMAX = 500          # above 4a's 200, so the set is closer to complete


def esearch(term, retmax=RETMAX):
    url = f"{E.NCBI_EUTILS_BASE}/esearch.fcgi"
    p = E._ncbi_params({"db": "pubmed", "term": term, "retmax": retmax,
                        "retmode": "json", "sort": "relevance"})
    r = requests.get(url, params=p, timeout=60)
    r.raise_for_status()
    j = r.json().get("esearchresult", {})
    return j.get("idlist", []), int(j.get("count", 0))


def efetch_records(pmids):
    """{pmid: {pubtypes, title, abstract, journal, year}} in batches of 100."""
    out = {}
    for i in range(0, len(pmids), 100):
        chunk = pmids[i:i + 100]
        for attempt in range(4):
            try:
                url = f"{E.NCBI_EUTILS_BASE}/efetch.fcgi"
                p = E._ncbi_params({"db": "pubmed", "id": ",".join(chunk),
                                    "retmode": "xml"})
                r = requests.get(url, params=p, timeout=120)
                r.raise_for_status()
                root = ET.fromstring(r.text)
                break
            except Exception as e:
                if attempt == 3:
                    print("      efetch batch failed: %s" % str(e)[:70])
                    root = None
                time.sleep(2 * (attempt + 1))
        if root is None:
            continue
        for art in root.findall(".//PubmedArticle"):
            pmid = art.findtext(".//PMID") or ""
            types = [(n.text or "").strip() for n in
                     art.findall(".//PublicationTypeList/PublicationType")]
            # AbstractText comes in labelled sections (BACKGROUND, METHODS...).
            # The LABEL matters -- "METHODS: A randomised..." -- so keep them.
            parts = []
            for ab in art.findall(".//Abstract/AbstractText"):
                label = ab.get("Label") or ab.get("NlmCategory") or ""
                txt = "".join(ab.itertext()).strip()
                parts.append(("%s: %s" % (label, txt)) if label else txt)
            out[pmid] = {
                "pmid": pmid,
                "publication_types": sorted(set(types)),
                "title": "".join((art.find(".//ArticleTitle") or ET.Element("x")).itertext()).strip(),
                "abstract": "\n".join(parts),
                "journal": art.findtext(".//Journal/ISOAbbreviation") or "",
                "year": (art.findtext(".//JournalIssue/PubDate/Year")
                         or art.findtext(".//JournalIssue/PubDate/MedlineDate") or ""),
            }
        print("      fetched %d/%d" % (min(i + 100, len(pmids)), len(pmids)))
        time.sleep(0.4)
    return out


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    cases = {c["id"]: c for c in
             json.load(open("eval/questions.json", encoding="utf-8"))["cases"]}
    window = f'"last {MONTHS} months"[dp]'

    for qid in TARGETS:
        out_path = CACHE / ("%s.json" % qid)
        if out_path.exists():
            print("%s already collected, skipping" % qid)
            continue
        q = cases[qid]["question"]
        print("\n=== %s ===" % qid)
        print("  %s" % q[:80])
        # Production's own two-step term generation and query shape. The first
        # version called generate_search_terms alone -- which returns the
        # primary query STRING -- and sliced it as a list, issuing four
        # one-character queries with no domain filter. See the correction note
        # in scripts/measure_untyped_recent.py.
        terms = MU.topic_groups(q)

        allids = set()
        for t in terms:
            ids, count = esearch(MU.untyped_lane_query(t, MONTHS))
            print("    group -> %d returned of %d total" % (len(ids), count))
            allids.update(ids)
            time.sleep(0.4)
        print("    %d distinct recent PMIDs" % len(allids))

        recs = efetch_records(sorted(allids))
        untyped = {p: r for p, r in recs.items()
                   if [x.lower() for x in r["publication_types"]] == ["journal article"]}
        print("    %d untyped (Journal Article only)" % len(untyped))
        with_abs = {p: r for p, r in untyped.items() if r["abstract"].strip()}
        print("    %d of those carry an abstract" % len(with_abs))

        out_path.write_text(json.dumps({
            "id": qid, "question": q, "terms": terms[:4],
            "n_recent": len(allids), "n_untyped": len(untyped),
            "n_untyped_with_abstract": len(with_abs),
            "records": untyped,
        }, indent=1), encoding="utf-8")
        print("    wrote %s" % out_path)

    # The negative control's own record, cached the same way.
    ctrl = CACHE / "control_42388091.json"
    if not ctrl.exists():
        print("\n=== negative control: Sulaiman 42388091 ===")
        rec = efetch_records(["42388091"])
        ctrl.write_text(json.dumps(rec, indent=1), encoding="utf-8")
        print("  wrote %s" % ctrl)
    return 0


if __name__ == "__main__":
    sys.exit(main())
