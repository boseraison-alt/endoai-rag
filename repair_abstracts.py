"""
Endo AI -- Abstract Repair Script
===================================
Finds all papers in the RAG database with missing/empty abstracts,
re-fetches their MEDLINE records from PubMed, and updates them in-place.

These papers were added by the original build_library.py run which used
a broken fetch_abstracts() parser. They have valid PMIDs and embeddings
but no abstract or title text.

Usage:
    py repair_abstracts.py            -- fix all missing abstracts
    py repair_abstracts.py --dry-run  -- show what would be fixed
    py repair_abstracts.py --limit 50 -- fix first N papers only
"""

import sys, os, re, time, argparse, requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.abspath("."), ".env"), override=True)
sys.path.insert(0, os.path.abspath("."))

from rag import setup_table, upsert_paper, embed, get_conn, library_stats
from endo_ai import get_impact_factor, score_paper, extract_sample_size, extract_followup_period

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
BATCH    = 200   # PMIDs per MEDLINE fetch (PubMed max is ~500)


# ── HTTP helper ────────────────────────────────────────────────────────────

def _get(url, params, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=25)
            r.raise_for_status()
            return r
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
            else:
                print(f"    ! HTTP error: {e}")
    return None


# ── MEDLINE fetcher (same logic as fetch_pmc_corpus.py) ───────────────────

def fetch_medline(pmids: list) -> dict:
    """Batch-fetch MEDLINE records. Returns {pmid: {title, abstract, journal, year, authors}}."""
    if not pmids:
        return {}
    r = _get(f"{BASE_URL}/efetch.fcgi", {
        "db":      "pubmed",
        "id":      ",".join(pmids),
        "rettype": "medline",
        "retmode": "text",
    })
    if not r:
        return {}

    out: dict = {}
    cur: dict = {}
    cur_field: str = ""

    def _save():
        pid = cur.get("pmid")
        if pid:
            cur["authors"] = "; ".join(cur.pop("_authors", [])[:6])
            out[pid] = cur.copy()

    for line in r.text.split("\n"):
        m = re.match(r'^([A-Z]{2,4})\s*-\s(.*)', line)
        if m:
            tag, val = m.group(1), m.group(2).strip()
            cur_field = tag
            if tag == "PMID":
                _save()
                cur = {"pmid": val, "_authors": [], "abstract": "",
                       "title": "", "journal": "", "year": "2010"}
            elif tag == "TI":
                cur["title"] = val
            elif tag == "AB":
                cur["abstract"] = val
            elif tag == "AU":
                cur.setdefault("_authors", []).append(val)
            elif tag in ("JT", "TA") and not cur.get("journal"):
                cur["journal"] = val
            elif tag == "DP":
                ym = re.search(r'\b(19|20)\d{2}\b', val)
                if ym:
                    cur["year"] = ym.group(0)
        elif line.startswith("      ") and cur_field:
            cont = line.strip()
            if cur_field == "TI":
                cur["title"] = cur.get("title", "") + " " + cont
            elif cur_field == "AB":
                cur["abstract"] = cur.get("abstract", "") + " " + cont
    _save()
    return out


# ── Pull PMIDs with missing abstracts from DB ──────────────────────────────

def get_empty_pmids(limit: int = None) -> list:
    """Return PMIDs of real papers (not COCHRANE_/AAE-/ESE- fake IDs) with no abstract."""
    conn = get_conn()
    cur  = conn.cursor()
    try:
        sql = """
            SELECT pmid FROM endo_papers_rag
            WHERE (abstract IS NULL OR LENGTH(abstract) < 50)
              AND pmid NOT LIKE 'COCHRANE_%%'
              AND pmid NOT LIKE 'AAE-%%'
              AND pmid NOT LIKE 'ESE-%%'
              AND pmid ~ '^[0-9]+$'
            ORDER BY pmid
        """
        if limit:
            sql += f" LIMIT {limit}"
        cur.execute(sql)
        return [row[0] for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


# ── Update one paper record in DB ──────────────────────────────────────────

def update_paper(pmid: str, med: dict, dry_run: bool) -> bool:
    """Re-embed and upsert a paper with its newly fetched abstract/title."""
    abstract = med.get("abstract", "").strip()
    title    = med.get("title", "").strip()
    journal  = med.get("journal", "")
    year_str = med.get("year", "2000")
    authors  = med.get("authors", "")

    if len(abstract) < 50:
        return False   # MEDLINE didn't have an abstract either -- skip

    try:
        year = int(year_str) if str(year_str).isdigit() else 2000
    except Exception:
        year = 2000

    if_val, if_pts = get_impact_factor(journal)
    sample_size    = extract_sample_size(abstract)
    followup       = extract_followup_period(abstract)
    followup_months = followup[0] if followup else None

    # Re-score with full data
    score, _ = score_paper(
        "",          # level_key unknown for old records
        year,
        0,           # citations unknown
        sample_size,
        followup_months,
        if_pts,
    )

    paper = {
        "pmid":            pmid,
        "title":           title,
        "abstract":        abstract[:1000],
        "authors":         authors,
        "year":            year,
        "journal":         journal,
        "impact_factor":   if_val,
        "sample_size":     sample_size,
        "followup_months": followup_months,
        "citations":       0,
        "level_key":       "",
        "score":           score,
    }

    if dry_run:
        return True

    # Re-embed with title + abstract for better semantic coverage
    vec = embed(f"{title} {abstract[:400]}")
    upsert_paper(paper, vec)
    return True


# ── Main ───────────────────────────────────────────────────────────────────

def run(dry_run: bool = False, limit: int = None):
    print("\n" + "=" * 60)
    print("  Endo AI -- Abstract Repair Script")
    print("=" * 60)

    setup_table()

    stats = library_stats()
    print(f"\n  Library: {stats['total']} papers total")

    pmids = get_empty_pmids(limit=limit)
    print(f"  Papers with missing abstracts: {len(pmids)}")

    if not pmids:
        print("  Nothing to fix!")
        return

    if dry_run:
        print(f"  DRY RUN -- would attempt to repair {len(pmids)} papers")
        return

    print(f"\n  Fetching MEDLINE in batches of {BATCH}...")
    print()

    repaired  = 0
    no_abstract = 0
    errors    = 0

    # Load embedding model once
    print("  Loading embedding model...")
    _ = embed("test")
    print("  Embedding model ready.\n")

    for i in range(0, len(pmids), BATCH):
        batch = pmids[i : i + BATCH]
        batch_end = min(i + BATCH, len(pmids))
        print(f"  Batch {i+1}-{batch_end} / {len(pmids)} ...", end=" ", flush=True)

        medline = fetch_medline(batch)

        batch_repaired = 0
        batch_skip     = 0
        for pmid in batch:
            med = medline.get(pmid, {})
            if not med:
                no_abstract += 1
                batch_skip  += 1
                continue
            try:
                ok = update_paper(pmid, med, dry_run)
                if ok:
                    repaired      += 1
                    batch_repaired += 1
                else:
                    no_abstract += 1
                    batch_skip  += 1
            except Exception as e:
                errors  += 1
                batch_skip += 1
                print(f"\n    ! Error on PMID {pmid}: {e}")

        print(f"repaired {batch_repaired}, skipped {batch_skip}")
        time.sleep(0.4)   # PubMed rate limit

    print()
    print("=" * 60)
    print(f"  Done.")
    print(f"  Repaired:            {repaired}")
    print(f"  No abstract on PubMed: {no_abstract}")
    print(f"  Errors:              {errors}")
    stats = library_stats()
    print(f"  Library now:         {stats['total']} papers")
    print(f"  By level:            {stats['by_level']}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Repair missing abstracts in RAG library")
    parser.add_argument("--dry-run", action="store_true", help="Count what would be fixed without writing")
    parser.add_argument("--limit",   type=int, default=None, help="Fix only first N papers")
    args = parser.parse_args()
    run(dry_run=args.dry_run, limit=args.limit)
