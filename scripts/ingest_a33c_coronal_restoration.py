"""
A33c — the 2026 Cochrane review on direct coronal restoration is absent from the
library. It was filed as "an ordinary ingestion gap, not a taxonomy or ranking
one". Measured, it is neither: **`ENDO_DOMAIN_FILTER` excludes it.**

    42444634[uid]                                   1 record
    42444634[uid] AND ("Cochrane Database Syst Rev"[jour])   1
    42444634[uid] AND ENDO_DOMAIN_FILTER            0
    ... and 0 against every one of the eleven domain clauses individually.

"Restorative materials for direct coronal restoration of permanent posterior
teeth" (Cochrane Database Syst Rev, 2026 Jul 14) is a RESTORATIVE review. It
never says root canal, pulp, periapical or endodontic. The domain filter is
appended to every live query unconditionally, so no live query can reach it at
any pool size, under any relaxation, ever — the filter is not one of the
droppable topic groups.

**This is the domain filter's first conviction.** A31e records that it had been
exonerated twice (Q7, A23a) of gaps that turned out to be the coverage gate, the
cap, the KNN ordering and the tier taxonomy. This one is really it, and it is
A33f's point as a mechanism: the fixture asks a RESTORATIVE question of an
endodontic assistant, and the domain boundary answers before the evidence does.

Widening the filter is NOT done here. That is Stage 4's scope question (S3,
"what would widening actually admit"), it changes every live query on every
path, and it needs its own measurement. What this script does is ingest the
paper, which is additive and reversible: the LIBRARY route has no domain filter
— `rag.search` is cosine KNN plus the retracted/withdrawn exclusions — so an
ingested paper is reachable by similarity even while the live route cannot see
it.

Because the domain filter blocks it, this cannot go through `fetch_papers` like
the sibling ingest scripts. It uses the same hand-ingest path
`ingest_classics.py` uses — esummary + efetch, the shared abstract selector, the
shared scorer, the shared upsert — with the tier taken from the PubMed record
rather than assumed.

Two papers, and they are NOT the same kind of gap:

  42444634  the Cochrane review above. Genuine Cochrane journal, correctly
            typed, squarely on the fixture's topic. INGESTED.

  35097115  de Araujo 2022, intraorifice barrier (A33b). Also absent, but it
            passes the domain filter perfectly well and its banding is
            contested BEFORE it is written: it is a systematic review OF IN
            VITRO STUDIES and PubMed types it "Systematic Review", which bands
            it level1, alongside randomised trials in patients. A12 says
            reachability and banding are never decided in one change, so this
            reports the tier it would land in and writes it only under
            --apply-contested.

APPLIED 2026-09-03, and the outcome is not what the item expected.

  library 3,035 -> 3,036 rows
  + 42444634  2026  cochrane  score 80.0  abstract 6,929 chars, uncapped

The paper is in, banded correctly, and reachable — but NOT for the fixture that
asked for it. Measured against the A33 question ("glass ionomer as permanent
access restoration ... through a ceramic crown"), its cosine similarity is
**0.505**, below the 0.55 floor, rank worse than 200. Against its own subject it
is 0.814, and against "which restorative material for a posterior tooth after
endodontic treatment" 0.686.

So A33c is closed as an INGESTION gap and the review is now available to
restorative-material questions, but it does not close the A33 fixture's gap. A
Cochrane overview of restorative materials for posterior teeth is simply not
about restoring an access cavity through a ceramic crown, and the competitor
citing it was reaching wider than the question. Reported rather than tuned
around: lowering the floor to admit it would admit everything at 0.50.

    python scripts/ingest_a33c_coronal_restoration.py                     # dry run
    python scripts/ingest_a33c_coronal_restoration.py --apply             # 42444634 only
    python scripts/ingest_a33c_coronal_restoration.py --apply --apply-contested
"""

import argparse
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import endo_ai  # noqa: E402
from endo_ai import (ncbi_get, NCBI_EUTILS_BASE, ENDO_DOMAIN_FILTER,  # noqa: E402
                     extract_sample_size, extract_followup_period,
                     get_impact_factor, score_paper, _select_abstract_paragraph)
from rag import get_conn, embed, upsert_paper  # noqa: E402

UNCONTESTED = {
    "42444634": "Cochrane 2026 — restorative materials for direct coronal "
                "restoration of permanent posterior teeth (A33c)",
}
CONTESTED = {
    "35097115": "de Araujo 2022, Biomed Res Int — intraorifice barrier; an SR "
                "OF IN VITRO studies, so level1 overstates it (A33b -> A25)",
}
EXPECTED_PRESENT = {
    "36661351": "Aust Dent J 2023 — orifice barriers, level1",
    "27542693": "The effect of endodontic access on all-ceramic crowns",
}

# Mirrors scripts/backfill_pubmed_metadata.py::PUBTYPE_TO_LEVEL. Highest
# evidence first; the journal decides `cochrane` because PubMed has no
# "Cochrane Review" publication type (see COCHRANE_TERM in endo_ai).
PUBTYPE_TO_LEVEL = [
    ("meta-analysis", "level1"), ("systematic review", "level1"),
    ("randomized controlled trial", "level1"), ("practice guideline", "level1"),
    ("guideline", "level1"), ("consensus development conference", "level1"),
    ("controlled clinical trial", "level2"), ("clinical trial", "level2"),
    ("multicenter study", "level2"),
    ("observational study", "level3a"), ("comparative study", "level3a"),
    ("evaluation study", "level3b"),
    ("case reports", "level4"),
    ("review", "level5"), ("editorial", "level5"),
    ("comment", "level5"), ("letter", "level5"),
]
_COCHRANE_JOURNALS = ("cochrane database", "cochrane db syst")


def _count(term):
    r = ncbi_get(f"{NCBI_EUTILS_BASE}/esearch.fcgi",
                 params={"db": "pubmed", "term": term, "retmax": 0,
                         "retmode": "json"}, timeout=25)
    return int(r.json()["esearchresult"]["count"])


def _rows(pmids):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT pmid, year, level_key, score, journal, left(title, 70) "
            "FROM endo_papers_rag WHERE pmid = ANY(%s)", (list(pmids),))
        return {r[0]: r for r in cur.fetchall()}
    finally:
        cur.close()
        conn.close()


def _fetch(pmid):
    """esummary + efetch for one PMID. Same shape ingest_classics builds."""
    r = ncbi_get(f"{NCBI_EUTILS_BASE}/esummary.fcgi",
                 params={"db": "pubmed", "id": pmid, "retmode": "json"},
                 timeout=25)
    meta = (r.json().get("result", {}) or {}).get(pmid, {}) or {}
    if not meta or meta.get("error"):
        return None
    ra = ncbi_get(f"{NCBI_EUTILS_BASE}/efetch.fcgi",
                  params={"db": "pubmed", "id": pmid,
                          "rettype": "abstract", "retmode": "text"}, timeout=25)
    paragraphs, cur = [], []
    for line in (ra.text if ra else "").split("\n"):
        if line.strip():
            cur.append(line.strip())
        elif cur:
            paragraphs.append(" ".join(cur)); cur = []
    if cur:
        paragraphs.append(" ".join(cur))

    ym = re.search(r"\b(19|20)\d{2}\b", meta.get("pubdate", "") or "")
    names = [a.get("name", "") for a in (meta.get("authors") or []) if a.get("name")]
    return {
        "pmid": pmid,
        "title": (meta.get("title") or "").rstrip("."),
        "abstract": _select_abstract_paragraph(paragraphs) or "",
        "journal": meta.get("fulljournalname") or meta.get("source") or "",
        "year": ym.group(0) if ym else None,
        "authors": ", ".join(names[:5]) + (", et al." if len(names) > 5 else ""),
        "pubtypes": [str(p).strip().lower() for p in (meta.get("pubtype") or [])],
    }


def _infer_tier(paper):
    if any(h in (paper["journal"] or "").lower() for h in _COCHRANE_JOURNALS):
        return "cochrane", "journal:cochrane"
    for tag, level in PUBTYPE_TO_LEVEL:
        if tag in paper["pubtypes"]:
            return level, tag
    return "level5", "unmapped — banded weakest"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--apply-contested", action="store_true")
    ap.add_argument("--out", default="eval/logs/a33c_ingest.json")
    args = ap.parse_args()
    print("APPLY\n" if args.apply else "DRY RUN\n")

    everything = list(UNCONTESTED) + list(CONTESTED) + list(EXPECTED_PRESENT)
    before = _rows(everything)

    print("before:")
    for pmid, label in (list(EXPECTED_PRESENT.items())
                        + list(UNCONTESTED.items()) + list(CONTESTED.items())):
        r = before.get(pmid)
        print("  %s  %-56s %s" % (pmid, label[:56],
              "PRESENT (%s, score %s)" % (r[2], r[3]) if r else "ABSENT"))
    gone = [p for p in EXPECTED_PRESENT if p not in before]
    if gone:
        print("\n  !! %s expected present and is not." % gone)

    print("\nwhy the live route cannot reach these (standing rule 5 — say what "
          "was excluded and by what):")
    for pmid in list(UNCONTESTED) + list(CONTESTED):
        bare = _count(f"{pmid}[uid]")
        dom = _count(f"{pmid}[uid] AND {ENDO_DOMAIN_FILTER}")
        print("  %s  exists %d   passes ENDO_DOMAIN_FILTER %d %s"
              % (pmid, bare, dom,
                 "  <-- EXCLUDED BY THE DOMAIN FILTER" if bare and not dom else ""))

    found, report = {}, {}
    for pmid, label in list(UNCONTESTED.items()) + list(CONTESTED.items()):
        if pmid in before:
            print("\n%s already present — nothing to do." % pmid)
            continue
        paper = _fetch(pmid)
        if not paper:
            print("\n%s NOT RETURNED BY PUBMED — nothing written." % pmid)
            continue
        tier, why = _infer_tier(paper)
        n = extract_sample_size(paper["abstract"])
        fu = extract_followup_period(paper["abstract"])
        if_val, if_pts = get_impact_factor(paper["journal"])
        score, _breakdown = score_paper(
            level_key=tier, year=paper["year"] or "2020", citations=0,
            sample_size=n, followup_months=(fu[0] if fu else None),
            if_score=if_pts)
        paper.update({"level_key": tier, "score": score, "why_tier": why,
                      "impact_factor": if_val, "sample_size": n,
                      "followup_months": (fu[0] if fu else None)})
        found[pmid] = paper
        report[pmid] = {k: paper[k] for k in
                        ("title", "journal", "year", "level_key", "score",
                         "why_tier", "pubtypes")}
        report[pmid]["abstract_chars"] = len(paper["abstract"])

        print("\n%s  would band %-10s score %s   (%s)"
              % (pmid, tier, score, why))
        print("     %s" % paper["title"][:88])
        print("     %s %s   abstract %d chars"
              % (paper["journal"], paper["year"] or "?", len(paper["abstract"])))
        if not paper["abstract"]:
            print("     !! NO ABSTRACT — it would embed on the title alone and "
                  "the synthesis would see a name with no finding. NOT WRITTEN.")
            found.pop(pmid)
            continue
        if pmid in CONTESTED:
            print("     CONTESTED banding — written only under --apply-contested")

    to_write = {p: v for p, v in found.items()
                if p in UNCONTESTED or args.apply_contested}
    held = [p for p in found if p not in to_write]
    if held:
        print("\nHELD BACK (banding contested, A12): %s" % ", ".join(held))

    if args.apply and to_write:
        for pmid, paper in to_write.items():
            record = {
                "pmid": pmid, "title": paper["title"],
                # Whole abstract, uncapped. The sibling scripts that sliced
                # this field stored papers that stop before their conclusions.
                "abstract": paper["abstract"], "authors": paper["authors"],
                "year": int(paper["year"]) if (paper["year"] or "").isdigit() else None,
                "journal": paper["journal"], "impact_factor": paper["impact_factor"],
                "sample_size": paper["sample_size"],
                "followup_months": paper["followup_months"], "citations": 0,
                "level_key": paper["level_key"], "score": paper["score"],
            }
            upsert_paper(record, embed(f"{paper['title']} {paper['abstract']}"))
            print("  wrote %s" % pmid)

    after = _rows(everything)
    added = [p for p in after if p not in before]
    print("\ndelta: %d row(s) added" % len(added))
    for pmid in added:
        r = after[pmid]
        print("  + %s  %s  %-10s score %s  %s" % (r[0], r[1], r[2], r[3], r[5]))
    if not args.apply:
        print("\n(dry run — nothing was written; re-run with --apply)")

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    io.open(out, "w", encoding="utf-8").write(json.dumps({
        "uncontested": UNCONTESTED, "contested": CONTESTED,
        "expected_present": EXPECTED_PRESENT,
        "before": {k: list(v) for k, v in before.items()},
        "after": {k: list(v) for k, v in after.items()},
        "fetched": report, "added": added, "held_back": held,
        "applied": bool(args.apply),
        "applied_contested": bool(args.apply_contested),
    }, indent=2))
    print("\nreport: %s" % args.out)


if __name__ == "__main__":
    main()
