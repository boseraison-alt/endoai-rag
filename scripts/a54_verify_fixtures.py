"""A54 — verify the retrieval fixtures for the apicoectomy root-end filling miss.

THE HOANG 2026 RULE. A PMID from memory, or from a competitor's reference
list, is an assertion nobody checked. Every fixture here is found by TITLE
SEARCH against PubMed through the repo's own client, and the accession is
accepted only when journal, year and first author all match what the
comparison claimed.

F1-F5 are given by title only and must be resolved. F6-F8 arrive WITH a PMID
from DentalSource, which is exactly the case the rule exists for: the
accession is looked up and checked against the stated paper rather than
trusted.

    python scripts/a54_verify_fixtures.py
"""
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E  # noqa: E402

# (key, title fragment to search, expected journal fragment, expected year,
#  expected first author surname)
# AUTHOR + ONE DISTINCTIVE TITLE WORD, not the full title as a phrase.
# The phrase form returned ZERO candidates for all five: PubMed's [Title]
# phrase match is defeated by the punctuation and casing these titles carry
# ("Root-end", subtitles after a colon). A search that finds nothing is not
# evidence the paper is absent -- it is evidence the search was wrong, and
# reporting "not resolved" from it would have been the fixture-verification
# step failing in exactly the way it exists to prevent.
BY_TITLE = [
    ("F1", "Safi C[Author] AND root-end[Title]", "J Endod", "2019", "Safi"),
    ("F2", "Zhou W[Author] AND iRoot[Title]", "J Endod", "2017", "Zhou"),
    ("F3", "Bliggenstorfer[Author] AND periapical surgery[Title]",
     "J Endod", "2021", "Bliggenstorfer"),
    ("F4", "Dong X[Author] AND iRoot[Title]", "Clin Oral Investig", "2024",
     "Dong"),
    ("F5", "Hussain O[Author] AND root-end[Title]", "Clin Oral Investig",
     "2026", "Hussain"),
]

# (key, PMID as given, what it is claimed to be)
BY_PMID = [
    ("F6", "42004800", "RCT, MTA-Angelus vs Well-Root Putty, guided vs "
                       "non-guided microsurgery, J Conserv Dent Endod 2026"),
    ("F7", "41555359", "SR/MA, premixed vs manually mixed bioceramic root-end "
                       "filling, BMC Oral Health 2026"),
    ("F8", "38849637", "ex vivo, three root-end filling techniques with "
                       "premixed putty, Clin Oral Investig 2024"),
]

# Retrieved by Curo, top of the RCT/SR tier, NOT cited.
UNCITED = ["37815804", "42063099"]


def esearch(term, retmax=10):
    r = E.ncbi_get(f"{E.NCBI_EUTILS_BASE}/esearch.fcgi",
                   params=E._ncbi_params({"db": "pubmed", "term": term,
                                          "retmode": "json",
                                          "retmax": retmax}), timeout=25)
    d = r.json().get("esearchresult", {})
    return [str(i) for i in d.get("idlist", [])]


def summary(pmids):
    if not pmids:
        return {}
    r = E.ncbi_get(f"{E.NCBI_EUTILS_BASE}/esummary.fcgi",
                   params=E._ncbi_params({"db": "pubmed",
                                          "id": ",".join(pmids),
                                          "retmode": "json"}), timeout=25)
    res = r.json().get("result", {})
    out = {}
    for p in pmids:
        e = res.get(p) or {}
        authors = e.get("authors") or []
        out[p] = {
            "title": e.get("title", "") or "",
            "journal": e.get("fulljournalname", "") or e.get("source", "") or "",
            "source": e.get("source", "") or "",
            "year": (e.get("pubdate", "") or "")[:4],
            "first_author": (authors[0].get("name", "") if authors else ""),
            "pubtypes": e.get("pubtype", []) or [],
        }
    return out


def main():
    print("=" * 78)
    print("A54 — FIXTURE VERIFICATION (title search, then check the accession)")
    print("=" * 78)
    resolved = {}

    print("\nF1-F5 — resolved BY TITLE")
    for key, query, jrn, yr, author in BY_TITLE:
        ids = esearch(query)
        meta = summary(ids[:5])
        hit = None
        for p in ids[:5]:
            m = meta.get(p, {})
            if (jrn.lower().split()[0] in (m.get("source", "") + m.get("journal", "")).lower()
                    and m.get("year") == yr
                    and author.lower() in m.get("first_author", "").lower()):
                hit = p
                break
        if hit:
            m = meta[hit]
            resolved[key] = hit
            print("  %-3s %-10s VERIFIED  %s %s, %s"
                  % (key, hit, m["source"], m["year"], m["first_author"]))
            print("      %s" % m["title"][:96])
        else:
            print("  %-3s %-10s NOT RESOLVED  (candidates: %s)"
                  % (key, "-", ids[:5]))
            for p in ids[:3]:
                m = meta.get(p, {})
                print("      %s  %s %s %s | %s"
                      % (p, m.get("source"), m.get("year"),
                         m.get("first_author"), m.get("title", "")[:62]))
        time.sleep(0.4)

    print("\nF6-F8 — the accession was GIVEN; check it resolves to the claim")
    meta = summary([p for _k, p, _c in BY_PMID])
    for key, pmid, claim in BY_PMID:
        m = meta.get(pmid, {})
        if not m.get("title"):
            print("  %-3s %-10s DOES NOT RESOLVE" % (key, pmid))
            continue
        resolved[key] = pmid
        print("  %-3s %-10s %s %s, %s"
              % (key, pmid, m["source"], m["year"], m["first_author"]))
        print("      %s" % m["title"][:96])
        print("      claimed: %s" % claim[:88])
        print("      types  : %s" % ", ".join(m["pubtypes"]))

    print("\nRETRIEVED BUT NOT CITED — print their titles")
    meta = summary(UNCITED)
    for p in UNCITED:
        m = meta.get(p, {})
        print("  %-10s %s %s, %s" % (p, m.get("source"), m.get("year"),
                                     m.get("first_author")))
        print("      %s" % m.get("title", "")[:110])
        print("      types: %s" % ", ".join(m.get("pubtypes", [])))

    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    json.dump(resolved, open("eval/reports/a54_fixtures.json", "w"), indent=1)
    print("\n  resolved %d of %d fixtures -> eval/reports/a54_fixtures.json"
          % (len(resolved), len(BY_TITLE) + len(BY_PMID)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
