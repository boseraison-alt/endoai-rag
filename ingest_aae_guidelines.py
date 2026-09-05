"""
Endo AI — guideline FETCH machinery (narrowed, A49 item 4a)
===========================================================

WHAT THIS FILE USED TO DO, AND WHY IT NO LONGER DOES IT
-------------------------------------------------------
It ingested sixteen hardcoded "AAE/ESE position statement" records and a
PubMed guideline sweep, and its own module docstring stated the design:

    level_key      = "level1"   guidelines treated as top-tier evidence
    score          = 88-95      manually set
    impact_factor  = 8.0        "guideline-tier authority weighting"
    abstract       = "Summaries are condensed from the official documents."

Every one of those four is now known to be wrong, and three of them were
wrong in ways that reached clinicians:

  * The A2 audit checked all sixteen against `data/guidelines_seed.json`.
    FOUR verified. SIX were dated to an edition that does not exist. SIX
    named no document at all. Twelve are quarantined (commit c7d7540).
  * A hand-set 90.0 outranked 100% of the 3,192 real evidence rows -- no
    genuine paper in the library scores above 85.9.
  * `impact_factor` is a forbidden signal, hardcoded here as an authority
    weight.
  * The "summaries" are paraphrases, not abstracts, so
    `verify_citation_support` was checking claims against model-written text
    -- a hole directly under the grounding guarantee.

WHY IT EXISTED AT ALL, and why that reason is gone. The live retrieval path
could not reach a guideline: `practice guideline[pt]`, `guideline[pt]` and
`consensus development conference[pt]` appeared in no tier filter, so the
sixteen records were a WORKAROUND for a retrieval hole. A49 item 5 added the
guideline lane (commit fb80cfc), so PubMed-indexed guidelines now arrive
through retrieval like everything else, and hardcoding them would only
duplicate what the lane returns.

WHAT REMAINS HERE
-----------------
The fetch machinery, which is genuinely useful and was always the good part
of this file: eUtils search, batched abstract fetch (sharing
`endo_ai._parse_efetch_batch` rather than carrying a third variant of the
text-dump parse), and esummary metadata.

WHAT WRITES GUIDELINES NOW
--------------------------
`scripts/ingest_guidelines_seed.py`, from the 60-record verified manifest in
`data/guidelines_seed.json`. It stores NO hand-set score, NO impact factor and
NO model-written summary; where PubMed does not index a document the record is
a POINTER -- organisation, title, year, status, jurisdiction, URL -- which a
clinician can follow. A link is worth more than a paraphrase Curo cannot
verify.

`upsert_guideline` below is kept as a GUARDED writer: it refuses any record
carrying a score, an impact factor or the `level1` tier, so this file cannot
reintroduce what it was narrowed for. Nothing in the repo calls it today.

Usage:
    py ingest_aae_guidelines.py --stats      # library stats
    py ingest_aae_guidelines.py --probe Q    # eUtils probe, prints only
"""

import sys, os, re, time, json, argparse, requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.abspath("."), ".env"))
sys.path.insert(0, os.path.abspath("."))

from rag import setup_table, upsert_paper, embed, library_stats

BASE_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
HEADERS     = {"User-Agent": "EndoAI-RAG/1.0 (clinical research tool; contact: endoai@research.edu)"}


# -- Helpers --------------------------------------------------------------

def _get(url: str, params: dict = None, retries: int = 3) -> requests.Response | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params or {}, headers=HEADERS, timeout=25)
            r.raise_for_status()
            return r
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
            else:
                print(f"    ! HTTP error: {e}")
    return None


def pubmed_search(query: str, max_results: int = 20) -> list[str]:
    r = _get(f"{BASE_EUTILS}/esearch.fcgi", {
        "db": "pubmed", "term": query,
        "retmax": max_results, "retmode": "json",
    })
    if not r:
        return []
    try:
        return r.json()["esearchresult"].get("idlist", [])
    except Exception:
        return []


def pubmed_fetch_abstracts(pmids: list[str]) -> dict[str, str]:
    if not pmids:
        return {}
    r = _get(f"{BASE_EUTILS}/efetch.fcgi", {
        "db": "pubmed", "id": ",".join(pmids),
        "rettype": "abstract", "retmode": "text",
    })
    if not r:
        return {}
    # This was a THIRD variant of the text-dump parse, and the worst of them:
    # it joined the entire entry — citation line, authors, every affiliation,
    # the DOI/PMID footer — into one string and stored that as the abstract.
    # `endo_ai._parse_efetch_batch` already splits a batch into per-PMID
    # entries and picks the abstract paragraph with the shared selector, and a
    # guideline record is not a different shape of PubMed record.
    #
    # Note the numbering: this matched `^12345678.` — a PMID followed by a dot
    # at the start of a line — where the entry separator PubMed actually emits
    # is an ORDINAL, "1. ", "2. ". It happened to work because the PMID footer
    # line is `PMID: 12345678 [...]`, not `12345678.`, so nothing matched and
    # every abstract in a batch landed under whichever id matched first.
    from endo_ai import _parse_efetch_batch
    return {pmid: parts.get("abstract") or ""
            for pmid, parts in _parse_efetch_batch(r.text).items()}


def pubmed_fetch_meta(pmids: list[str]) -> dict[str, dict]:
    if not pmids:
        return {}
    r = _get(f"{BASE_EUTILS}/esummary.fcgi", {
        "db": "pubmed", "id": ",".join(pmids), "retmode": "json",
    })
    if not r:
        return {}
    try:
        result = r.json().get("result", {})
        out: dict[str, dict] = {}
        for pid in pmids:
            item = result.get(pid, {})
            title = item.get("title", "")
            source = item.get("source", "")
            pub_date = item.get("pubdate", "2010")
            year_m = re.search(r"\b(19|20)\d{2}\b", pub_date)
            year = year_m.group(0) if year_m else "2010"
            authors_raw = item.get("authors", [])
            authors = "; ".join(a.get("name", "") for a in authors_raw[:5])
            out[pid] = {"title": title, "journal": source, "year": year, "authors": authors}
        return out
    except Exception:
        return {}


# -- Guarded writer -------------------------------------------------------

class GuidelineRecordRejected(ValueError):
    """Raised when a record would reintroduce what A49 removed."""


def upsert_guideline(record: dict, dry_run: bool = False) -> bool:
    """Store a guideline record, refusing the four things that made the
    original sixteen unusable.

    The guard is here rather than in a comment because a comment did not stop
    it the first time: the module docstring described the score and the impact
    factor openly, as design, for months.

    Nothing in the repo calls this today -- `scripts/ingest_guidelines_seed.py`
    writes guidelines from the verified manifest. It is kept so that a future
    fetch path has a writer that cannot repeat the mistake.
    """
    if record.get("score") is not None:
        raise GuidelineRecordRejected(
            "a guideline carries no hand-set score. The original sixteen were "
            "written at 85-95, which outranked all 3,192 real evidence rows; "
            "no genuine paper in the library scores above 85.9.")
    if record.get("impact_factor") is not None:
        raise GuidelineRecordRejected(
            "impact_factor is a forbidden signal (invariant 22). It was "
            "hardcoded here at 4.5-8.0 as an 'authority weighting'.")
    if record.get("level_key") not in (None, "", "guideline"):
        raise GuidelineRecordRejected(
            "a guideline is not on the study-design ladder. level_key must be "
            "'guideline'; %r is the score-as-membership category error."
            % record.get("level_key"))
    if record.get("summary_is_model_written"):
        raise GuidelineRecordRejected(
            "model-written summaries must not be stored as source text — "
            "verify_citation_support would be checking claims against a "
            "paraphrase. Store a pointer (org, title, year, status, URL).")

    text = f"{record.get('title', '')} {record.get('abstract', '')}"
    if len(text.strip()) < 30:
        return False
    if dry_run:
        print(f"    [DRY] Would ingest: {record['pmid']} — {record.get('title','')[:60]}")
        return True
    try:
        record = dict(record)
        record["level_key"] = "guideline"
        record["score"] = None
        record["impact_factor"] = None
        vec = embed(text[:600])
        upsert_paper(record, vec)
        return True
    except Exception as e:
        print(f"    ! Ingest error ({record['pmid']}): {e}")
        return False


# -- CLI ------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--stats", action="store_true", help="library stats")
    ap.add_argument("--probe", metavar="QUERY",
                    help="run one eUtils guideline probe and print what "
                         "comes back; writes nothing")
    args = ap.parse_args()

    if args.stats:
        setup_table()
        print(json.dumps(library_stats(), indent=1, default=str))
        return 0

    if args.probe:
        ids = pubmed_search(args.probe, max_results=10)
        print("%d hit(s)" % len(ids))
        meta = pubmed_fetch_meta(ids)
        for pid in ids:
            m = meta.get(pid, {})
            print("  %-10s %s (%s, %s)" % (pid, (m.get("title") or "")[:70],
                                           m.get("journal"), m.get("year")))
        return 0

    print(__doc__)
    print("\nThis file no longer ingests guideline records.")
    print("Use:  python scripts/ingest_guidelines_seed.py --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
