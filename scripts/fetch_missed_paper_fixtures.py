"""Capture the real PubMed record for each regression-fixture target.

The regression tests in `tests/test_missed_paper_fixtures.py` must run in the
DEFAULT suite — a strict xfail that is skipped for want of a network is not a
record of anything. So the papers' PubMed metadata is fetched ONCE, here, and
committed as JSON.

Two things are captured per paper.

1. The record itself — publication types, MeSH headings, MeSH subheadings,
   journal. These are the field types the production filter strings query
   (`[pt]`, `[mh]`/`[sh]`, `[jour]`).

2. An ADMISSION MAP: for each production tier filter, and for each candidate
   filter this batch might add, whether PubMed itself returns the paper for
   `<pmid>[uid] AND (<filter>)`.

The map exists because the obvious offline instrument is wrong. A simulator
that string-matches the paper's publication types against the `[pt]` terms in
a filter reports that NO tier admits PMID 42018467, whose only types are
`Journal Article` and `Practice Guideline`. PubMed disagrees: `review[pt]`
EXPLODES down the publication-type tree and admits `Practice Guideline`, which
is why the diagnostic found that guideline buried at rank 521 of level5's 608
rather than absent. Measured, not reasoned about — this project has now had
five instruments be wrong rather than the thing they measured.

So the map is ground truth, and a filter string absent from it is a hard error
in the tests rather than a default. Add a filter, re-run this script.

Usage:  python scripts/fetch_missed_paper_fixtures.py
"""
import json
import os
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, os.getcwd())

import requests                      # noqa: E402
import endo_ai as E                  # noqa: E402

OUT_DIR = os.path.join("tests", "fixtures", "missed_papers")

# Only the three the diagnostic VERIFIED as real. Hoang is deliberately absent
# — see the module docstring of the test file.
TARGETS = {
    "42388091": "Sulaiman 2026 — haemostasis time / partial pulpotomy, Int Endod J",
    "39117767": "Komora 2024 — network meta-analysis, bioactive materials, Sci Rep",
    "42018467": "EFCD-ESE-ORCA S3 deep caries guideline, Caries Res",
}


def tier_filters():
    """Every filter string the admission map must cover.

    Production's own, read from the module so a change to a tier filter shows
    up here as a stale-fixture failure rather than silently going unmeasured.
    Plus the candidates items 4 and 5 of this batch may introduce.
    """
    filters = {
        "cochrane": E.COCHRANE_TERM,
        "level1": " OR ".join(E.LEVEL_1_TERMS),
        "level2": " OR ".join(E.LEVEL_2_TERMS),
        "level3a": " OR ".join(E.LEVEL_3A_TERMS),
        "level3b": " OR ".join(E.LEVEL_3B_TERMS),
        "level4": " OR ".join(E.LEVEL_4_TERMS),
        "level5": " OR ".join(E.LEVEL_5_TERMS),
        "observational": " OR ".join(E.LEVEL_OBS_TERMS),
    }
    # Item 5's guideline rung, if it has landed.
    if hasattr(E, "LEVEL_GUIDELINE_TERMS"):
        filters["guideline"] = " OR ".join(E.LEVEL_GUIDELINE_TERMS)
    else:
        filters["guideline"] = ("practice guideline[pt] OR guideline[pt] OR "
                                "consensus development conference[pt]")
    return filters


def admits(pmid, filt):
    url = f"{E.NCBI_EUTILS_BASE}/esearch.fcgi"
    p = E._ncbi_params({"db": "pubmed", "term": "%s[uid] AND (%s)" % (pmid, filt),
                        "retmax": 5, "retmode": "json"})
    r = requests.get(url, params=p, timeout=30)
    r.raise_for_status()
    return pmid in (r.json().get("esearchresult", {}).get("idlist", []) or [])


def efetch(pmid):
    url = f"{E.NCBI_EUTILS_BASE}/efetch.fcgi"
    p = E._ncbi_params({"db": "pubmed", "id": pmid, "retmode": "xml"})
    r = requests.get(url, params=p, timeout=30)
    r.raise_for_status()
    return r.text


def parse(pmid, xml_text):
    root = ET.fromstring(xml_text)
    art = root.find(".//PubmedArticle")
    if art is None:
        raise SystemExit("no PubmedArticle for %s" % pmid)

    def txt(node):
        return "".join(node.itertext()).strip() if node is not None else ""

    pubtypes = [txt(n) for n in art.findall(".//PublicationTypeList/PublicationType")]
    mesh, subheads = [], []
    for mh in art.findall(".//MeshHeadingList/MeshHeading"):
        d = mh.find("DescriptorName")
        if d is not None:
            mesh.append(txt(d))
        for q in mh.findall("QualifierName"):
            subheads.append(txt(q))

    return {
        "pmid": pmid,
        "title": txt(art.find(".//ArticleTitle")),
        "journal": txt(art.find(".//Journal/Title")),
        "journal_iso": txt(art.find(".//Journal/ISOAbbreviation")),
        "year": txt(art.find(".//JournalIssue/PubDate/Year"))
                or txt(art.find(".//JournalIssue/PubDate/MedlineDate")),
        "publication_types": sorted(set(pubtypes)),
        "mesh_headings": sorted(set(mesh)),
        "mesh_subheadings": sorted(set(subheads)),
        "fetched_by": "scripts/fetch_missed_paper_fixtures.py",
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    filters = tier_filters()
    for pmid, label in TARGETS.items():
        rec = parse(pmid, efetch(pmid))
        rec["label"] = label
        time.sleep(0.4)

        amap = {}
        for name, filt in sorted(filters.items()):
            amap[name] = {"filter": filt, "admits": admits(pmid, filt)}
            time.sleep(0.35)
        rec["admission_map"] = amap

        path = os.path.join(OUT_DIR, "%s.json" % pmid)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=2, ensure_ascii=False)
        yes = [k for k, v in sorted(amap.items()) if v["admits"]]
        print("%s  pubtypes=%s" % (pmid, rec["publication_types"]))
        print("        mesh=%d subheadings=%d  journal=%s"
              % (len(rec["mesh_headings"]), len(rec["mesh_subheadings"]),
                 rec["journal_iso"] or rec["journal"]))
        print("        admitted by: %s" % (", ".join(yes) or "NOTHING"))
        print("        wrote %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
