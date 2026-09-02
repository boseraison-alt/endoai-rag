"""
Build the canonical Ohio State / Reader anesthesia corpus (`classics-v1` B1).

WHY THIS LIST EXISTS. RB expected the classic OSU anesthesia canon — Reader as
senior author, Nusstein / Fowler / Drum as first authors, mostly J Endod
c. 1990-2015 — to appear in an anesthesia curriculum. Two OSU papers are cited
(PMID 26831048, 25770038); the question is the deeper canon, and it cannot be
answered by opinion. This produces the denominator: the set of papers that
SHOULD have been reachable, so B2 can say of each one where it actually went.

The list is a FIXTURE, not a shopping list. Being on it does not mean a paper
belongs in any particular answer; it means that if the retrieval path never had
the chance to consider it, we know why.

NO JOURNAL WEIGHTING IS INTRODUCED ANYWHERE BY THIS SCRIPT (see `classics-v1`
[C]). The journal restriction below is a QUERY filter used once, to build a
list of candidates for a targeted audit. It never reaches scoring, and the
remedy for anything missing is retrieval or ingestion — never venue weight.

Usage:
    python scripts/build_osu_corpus.py            # query and write the fixture
    python scripts/build_osu_corpus.py --dry-run  # print, write nothing
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import endo_ai  # noqa: E402

OUT = ROOT / "eval" / "fixtures" / "osu_anesthesia_corpus.json"

# The authors RB named, plus the two other first authors who carry a large
# share of the OSU anesthesia output. Author-name queries are deliberately
# broad here: precision comes from the AND-ed anesthesia terms and the journal
# restriction, and a missed classic is a worse error for this audit than an
# extra row a human can drop.
AUTHORS = [
    "Reader A[Author]",
    "Nusstein J[Author]",
    "Drum M[Author]",
    "Fowler S[Author]",
    "Beck M[Author]",
]

# Anesthesia terms. These are the CANONICAL forms; part of what B3 may find is
# that the live retrieval vocabulary does not cover the terms these papers are
# actually indexed under, which is a synonym-group fix, not a scoring fix.
TERMS = [
    "anesthesia",
    "anaesthesia",
    "anesthetic",
    "inferior alveolar nerve block",
    "intraosseous injection",
    "intraligamentary injection",
    "periodontal ligament injection",
    "articaine",
    "lidocaine",
    "mepivacaine",
    "bupivacaine",
    "buccal infiltration",
    "irreversible pulpitis",
]

JOURNALS = [
    "J Endod[Journal]",
    "Journal of endodontics[Journal]",
    "Oral Surg Oral Med Oral Pathol[Journal]",
    "Oral Surg Oral Med Oral Pathol Oral Radiol Endod[Journal]",
    "Anesth Prog[Journal]",
]

YEAR_LO, YEAR_HI = 1985, 2020


def build_query() -> str:
    authors = " OR ".join(AUTHORS)
    terms = " OR ".join(f'"{t}"' for t in TERMS)
    journals = " OR ".join(JOURNALS)
    return (f"({authors}) AND ({terms}) AND ({journals}) "
            f"AND (\"{YEAR_LO}\"[Date - Publication] : \"{YEAR_HI}\"[Date - Publication])")


def esearch(term: str, retmax: int) -> list:
    """One esearch, using the module's own NCBI plumbing (key, rate limit,
    User-Agent) rather than a second copy of it."""
    url = f"{endo_ai.NCBI_EUTILS_BASE}/esearch.fcgi"
    params = endo_ai._ncbi_params({
        "db": "pubmed", "term": term, "retmax": retmax,
        "retmode": "json", "sort": "pub_date",
    })
    r = endo_ai.ncbi_get(url, params=params, timeout=25)
    r.raise_for_status()
    ids = r.json()["esearchresult"].get("idlist") or []
    return [i for i in ids if endo_ai._PMID_FORMAT_RE.match(str(i))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--retmax", type=int, default=300)
    args = ap.parse_args()

    query = build_query()
    print("QUERY:" + "\n  " + query + "\n")

    pmids = esearch(query, args.retmax)
    print(f"esearch returned {len(pmids)} pmid(s)")
    if not pmids:
        print("nothing returned — refusing to write an empty fixture over "
              "whatever is already there")
        return

    # `endo_ai.fetch_metadata` gives year / journal / authors / pubtypes /
    # MEDLINE status, which is what B2 needs — but it does not keep the TITLE,
    # and a corpus fixture nobody can read by eye is not reviewable. So the
    # titles come from a second, local esummary rather than by widening a
    # shared function for one audit.
    meta = {}
    for i in range(0, len(pmids), 100):
        meta.update(endo_ai.fetch_metadata(pmids[i:i + 100]))
        time.sleep(0.4)

    titles = {}
    for i in range(0, len(pmids), 100):
        chunk = pmids[i:i + 100]
        r = endo_ai.ncbi_get(
            f"{endo_ai.NCBI_EUTILS_BASE}/esummary.fcgi",
            params=endo_ai._ncbi_params({"db": "pubmed", "id": ",".join(chunk),
                                         "retmode": "json"}),
            timeout=30)
        res = r.json().get("result", {})
        for pmid in chunk:
            titles[pmid] = (res.get(pmid, {}) or {}).get("title", "") or ""
        time.sleep(0.4)

    rows = []
    for pmid in pmids:
        m = meta.get(pmid, {}) or {}
        rows.append({
            "pmid":     pmid,
            "title":    titles.get(pmid, ""),
            "authors":  m.get("authors", ""),
            "journal":  m.get("journal", ""),
            "journal_abbrev": m.get("journal_abbrev", ""),
            "year":     m.get("year"),
            "pubtypes": m.get("pubtypes", []),
            "medline_indexed": m.get("medline_indexed"),
        })
    rows.sort(key=lambda x: (str(x.get("year") or ""), str(x.get("pmid"))))

    print(f"resolved {sum(1 for r in rows if r['title'])} of {len(rows)} titles")
    decades = {}
    for r in rows:
        y = str(r.get("year") or "?")
        key = y[:3] + "0s" if y[:1].isdigit() else "?"
        decades[key] = decades.get(key, 0) + 1
    for k in sorted(decades):
        print(f"  {k}: {decades[k]}")

    payload = {
        "_README": (
            "The canonical OSU/Reader anesthesia corpus, built by "
            "scripts/build_osu_corpus.py for classics-v1 [B]. This is the "
            "DENOMINATOR for the audit in B2: for each pmid, where did it go? "
            "Membership here does not mean a paper belongs in any given "
            "answer. No journal weighting is derived from this file."),
        "query": query,
        "n": len(rows),
        "papers": rows,
    }

    if args.dry_run:
        print('--dry-run: not writing ' + str(OUT))
        for r in rows[:15]:
            print(f"  {r['pmid']}  {r['year']}  {(r['title'] or '')[:82]}")
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print('wrote ' + str(OUT))


if __name__ == "__main__":
    main()
