"""
Endo AI — San Antonio Guide / College of Diplomates Classics Ingester
=====================================================================
Parses the "Guide to the Endodontic Literature" PDF (College of Diplomates,
San Antonio Guide v2.34) for canonical foundational citations, resolves each
"Author Year" entry to a real PubMed PMID via esearch, fetches abstracts,
and inserts them into the local Neon vector library tagged
`level_key='classic'`.

Why a separate ingester:
  The standard build_evidence_base() pipeline scores by recency (15% of
  total). Foundational papers from the 1960s-1990s (Kakehashi 1965,
  Sundqvist 1976, Vertucci 1984, Bystrom 1981, Sjogren 1991, etc.) rank
  near zero on recency and never surface in the live PubMed retrieval
  even though every modern endo paper cites them. This ingester gives
  them a permanent home in the RAG library, scored as `classic` (baseline
  design weight 55, mid-tier) so semantic retrieval can pull them when
  a question asks about anatomy / microbiology / pulp biology / healing.

Resolution heuristic:
  esearch with `Surname[au] AND <year>[dp] AND endo-domain-filter` →
  if hits, take the first (relevance-sorted) result and fetch its
  abstract via efetch. Multi-author entries ("Smith & Jones 1985") query
  with both authors AND'd. Entries that don't resolve are logged.

Usage:
    python ingest_classics.py --dry-run            # parse + resolve, no DB write
    python ingest_classics.py --limit 20           # ingest first 20 only (sanity check)
    python ingest_classics.py                      # full ingest
    python ingest_classics.py --pdf <path>         # custom PDF location

Realistic resolution rates: 70-85% (older surnames + name collisions +
de-indexed pre-1970s papers leave a residue that won't resolve cleanly).
"""

import sys, os, re, time, json, argparse
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.abspath("."), ".env"))
sys.path.insert(0, os.path.abspath("."))

# Lazy import — only required for ingestion, not for app runtime
try:
    from pypdf import PdfReader
except ImportError:
    print("ERROR: pypdf not installed. Run: pip install pypdf")
    sys.exit(1)

import requests

from endo_ai import (
    score_paper, get_impact_factor, score_impact_factor,
    extract_sample_size, extract_followup_period,
    _ncbi_params, NCBI_EUTILS_BASE,
)
from rag import setup_table, upsert_paper, embed, library_stats, get_conn

DEFAULT_PDF = os.path.join(
    os.path.expanduser("~"), "Downloads",
    "A Guide to the Endodontic Literature Success - College of Diplomates.pdf",
)

# Endo domain filter — same intent as endo_ai.ENDO_DOMAIN_FILTER but a bit
# looser since we're matching by author/year, not topic, and many classics
# pre-date the precise MeSH heading conventions.
ENDO_FILTER = (
    '("endodontics"[MeSH] OR "endodontic"[tw] OR "root canal therapy"[MeSH] '
    'OR "root canal"[tw] OR "dental pulp"[MeSH] OR "pulp"[tw] OR '
    '"periapical"[tw] OR "apexification"[tw] OR "apicoectomy"[tw] OR '
    '"odontology"[tw] OR "dental"[tw])'
)

# Throttle to stay well within NCBI rate limits.
# Without API key: 3 req/sec → 0.34s sleep
# With    API key: 10 req/sec → 0.10s sleep
SLEEP_PER_REQUEST = 0.12 if os.getenv("NCBI_API_KEY") else 0.40


# ── PDF citation parsing ──────────────────────────────────────────

# Handles: Smith 1985 | Smith, 1985 | Smith & Jones 1985 | Smith and Jones 1985
# | Smith et al 1985 | Smith et al. 1985
# Surnames are 3+ letters, capitalised, no internal digits.
_CITATION_RE = re.compile(
    r"\b([A-Z][a-zA-Z'\-]{2,})"                                    # primary surname
    r"(?:\s*(?:&|and|et\s+al\.?)\s*([A-Z][a-zA-Z'\-]{2,}))?"        # optional 2nd
    r"\s*,?\s*"                                                     # optional comma
    r"(19[5-9]\d|20[0-2]\d)\b"                                      # year 1950-2029
)

# Surnames that are common English words and trigger massive false positives.
_SURNAME_BLOCKLIST = {
    "Page", "Table", "Figure", "Vol", "Volume", "Chapter", "Section",
    "Note", "Notes", "Other", "Some", "Using", "Most", "Both", "Each",
    "When", "Where", "Which", "What", "Then", "After", "Before",
    "Patient", "Patients", "Study", "Result", "Results", "Method",
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
    "Endodontic", "Endodontics", "Dental", "Apical", "Pulp", "Root",
    "Tooth", "Teeth", "Canal", "Caries", "Treatment", "Therapy",
    "International", "American", "European", "Journal", "British",
}


def extract_citations(pdf_path: str) -> list[dict]:
    """Return a list of unique {primary, secondary, year, page} citation dicts."""
    print(f"[1/4] Parsing PDF: {pdf_path}")
    reader = PdfReader(pdf_path)
    n_pages = len(reader.pages)
    print(f"      pages: {n_pages}")

    seen: set = set()
    citations: list[dict] = []

    for page_idx, page in enumerate(reader.pages):
        text = (page.extract_text() or "")
        for m in _CITATION_RE.finditer(text):
            primary, secondary, year = m.group(1), m.group(2), m.group(3)
            if primary in _SURNAME_BLOCKLIST:
                continue
            if secondary and secondary in _SURNAME_BLOCKLIST:
                secondary = None
            key = (primary.lower(), (secondary or "").lower(), year)
            if key in seen:
                continue
            seen.add(key)
            citations.append({
                "primary":   primary,
                "secondary": secondary,
                "year":      year,
                "page":      page_idx + 1,
            })

    print(f"      {len(citations)} unique (author,year) candidates extracted")
    return citations


# ── PubMed resolution ─────────────────────────────────────────────

def _eutils_get(url: str, params: dict, retries: int = 3) -> requests.Response | None:
    for attempt in range(retries):
        try:
            time.sleep(SLEEP_PER_REQUEST)
            r = requests.get(url, params=_ncbi_params(params), timeout=20)
            r.raise_for_status()
            return r
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(0.6 * (attempt + 1))
            else:
                print(f"      ! eutils error: {e}")
    return None


def resolve_pmid(citation: dict) -> str | None:
    """esearch the citation against PubMed; return best PMID or None."""
    primary = citation["primary"]
    secondary = citation.get("secondary")
    year = citation["year"]

    # Build the term: surname AS author, year AS publication date
    if secondary:
        term = f'{primary}[au] AND {secondary}[au] AND {year}[dp] AND {ENDO_FILTER}'
    else:
        term = f'{primary}[au] AND {year}[dp] AND {ENDO_FILTER}'

    r = _eutils_get(f"{NCBI_EUTILS_BASE}/esearch.fcgi", {
        "db": "pubmed", "term": term, "retmax": 5,
        "retmode": "json", "sort": "relevance",
    })
    if not r:
        return None
    try:
        ids = (r.json().get("esearchresult", {}) or {}).get("idlist", [])
    except Exception:
        return None
    if not ids:
        return None
    return ids[0]   # most relevant


# ── Metadata + abstract fetch ─────────────────────────────────────

def fetch_paper_data(pmid: str) -> dict | None:
    """Fetch esummary + efetch for a single PMID; return paper dict or None."""
    # esummary for structured metadata
    r_meta = _eutils_get(f"{NCBI_EUTILS_BASE}/esummary.fcgi", {
        "db": "pubmed", "id": pmid, "retmode": "json",
    })
    if not r_meta:
        return None
    try:
        meta = (r_meta.json().get("result", {}) or {}).get(pmid, {}) or {}
    except Exception:
        return None
    if not meta:
        return None

    title = meta.get("title", "") or ""
    pubdate = meta.get("pubdate", "") or ""
    year_m = re.search(r"\b(19|20)\d{2}\b", pubdate)
    year = year_m.group(0) if year_m else None
    journal = meta.get("fulljournalname", "") or meta.get("source", "") or ""
    raw_authors = meta.get("authors", []) or []
    author_names = [a.get("name", "") for a in raw_authors if a.get("name")]
    if len(author_names) > 5:
        authors_str = ", ".join(author_names[:5]) + ", et al."
    else:
        authors_str = ", ".join(author_names)

    # efetch for abstract body
    r_abs = _eutils_get(f"{NCBI_EUTILS_BASE}/efetch.fcgi", {
        "db": "pubmed", "id": pmid,
        "rettype": "abstract", "retmode": "text",
    })
    raw = r_abs.text if r_abs else ""

    # Same paragraph-collapse heuristic as /api/abstract: longest paragraph >= 200 chars
    paragraphs, current = [], []
    for line in raw.split("\n"):
        line = line.rstrip()
        if line.strip():
            current.append(line.strip())
        else:
            if current:
                paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    candidates = [p for p in paragraphs if len(p) >= 200]
    abstract = max(candidates, key=len) if candidates else (
        max(paragraphs, key=len) if paragraphs else "")

    return {
        "pmid":     pmid,
        "title":    title.rstrip("."),
        "abstract": abstract,
        "journal":  journal,
        "year":     year,
        "authors":  authors_str,
    }


# ── Score + upsert ────────────────────────────────────────────────

def score_and_upsert(paper: dict, dry_run: bool = False) -> tuple[int, dict]:
    """Score the paper as 'classic' tier, embed, upsert. Returns (score, breakdown)."""
    sample_size  = extract_sample_size(paper.get("abstract") or "")
    fu           = extract_followup_period(paper.get("abstract") or "")
    fu_months    = fu[0] if fu else None
    if_val, if_pts = get_impact_factor(paper.get("journal", ""))

    # Citation count is unknown without an extra elink call — skip for the
    # ingester and let the score reflect "old paper, citation_velocity=0".
    score, breakdown = score_paper(
        level_key       = "classic",
        year            = paper.get("year") or "1980",
        citations       = 0,
        sample_size     = sample_size,
        followup_months = fu_months,
        if_score        = if_pts,
    )

    record = {
        "pmid":            paper["pmid"],
        "title":           paper.get("title", ""),
        # Whole abstract, uncapped — the sibling ingest scripts all sliced this
        # field and stored papers that stop before their conclusions. This one
        # never did; keep it that way. Embedding text is built separately below,
        # which is the only place a length limit belongs.
        "abstract":        paper.get("abstract", ""),
        "authors":         paper.get("authors", ""),
        "year":            int(paper["year"]) if (paper.get("year") and str(paper["year"]).isdigit()) else None,
        "journal":         paper.get("journal", ""),
        "impact_factor":   if_val,
        "sample_size":     sample_size,
        "followup_months": fu_months,
        "citations":       0,
        "level_key":       "classic",
        "score":           score,
    }

    if dry_run:
        return score, breakdown

    # Build embed text from title + abstract
    embed_text = (record["title"] or "") + " " + (record["abstract"] or "")
    if not embed_text.strip():
        embed_text = paper["pmid"]
    vector = embed(embed_text)

    upsert_paper(record, vector)
    return score, breakdown


def already_in_library(pmid: str) -> bool:
    """Skip PMIDs already present (in any level_key)."""
    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM endo_papers_rag WHERE pmid = %s LIMIT 1;", (pmid,))
        return cur.fetchone() is not None
    finally:
        cur.close()
        conn.close()


# ── Main ──────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf",    default=DEFAULT_PDF, help="Path to the San Antonio Guide PDF")
    ap.add_argument("--limit",  type=int, default=None, help="Only ingest the first N citations (for sanity-check)")
    ap.add_argument("--dry-run", action="store_true", help="Parse + resolve only; do not write to DB")
    args = ap.parse_args()

    if not os.path.exists(args.pdf):
        print(f"ERROR: PDF not found at {args.pdf}")
        sys.exit(1)

    setup_table()
    print()

    # 1. Parse
    citations = extract_citations(args.pdf)
    if args.limit:
        citations = citations[:args.limit]
        print(f"      --limit {args.limit}: trimming to first {len(citations)} citations")

    # 2. Resolve + 3. Fetch + 4. Score/upsert
    print(f"\n[2/4] Resolving citations to PMIDs (rate-limit sleep={SLEEP_PER_REQUEST}s)")
    if os.getenv("NCBI_API_KEY"):
        print("      NCBI_API_KEY detected — using prioritised quota (10 req/sec)")
    else:
        print("      NCBI_API_KEY NOT SET — using public quota (3 req/sec); set it to speed up")

    n_resolved   = 0
    n_unresolved = 0
    n_skipped    = 0   # already in library
    n_inserted   = 0
    n_failed     = 0
    unresolved_log: list[str] = []
    inserted_log:   list[dict] = []

    for i, c in enumerate(citations, 1):
        label = f"{c['primary']}{(' & ' + c['secondary']) if c['secondary'] else ''} {c['year']}"
        prefix = f"  [{i:>3}/{len(citations)}] {label:<40}"

        pmid = resolve_pmid(c)
        if not pmid:
            n_unresolved += 1
            unresolved_log.append(label)
            print(f"{prefix} → not found")
            continue
        n_resolved += 1

        if already_in_library(pmid):
            n_skipped += 1
            print(f"{prefix} → PMID {pmid} (already in library, skip)")
            continue

        paper = fetch_paper_data(pmid)
        if not paper or not (paper.get("abstract") or "").strip():
            n_failed += 1
            print(f"{prefix} → PMID {pmid} (no abstract — skip)")
            continue

        try:
            score, _ = score_and_upsert(paper, dry_run=args.dry_run)
            n_inserted += 1
            inserted_log.append({
                "pmid":  pmid, "label": label,
                "title": (paper.get("title") or "")[:80],
                "score": score,
            })
            mode_tag = "DRY-RUN" if args.dry_run else "INSERTED"
            print(f"{prefix} → PMID {pmid}  score={score}  {mode_tag}")
        except Exception as e:
            n_failed += 1
            print(f"{prefix} → PMID {pmid} (upsert failed: {e})")

    # 5. Report
    print()
    print("=" * 60)
    print("INGEST REPORT")
    print("=" * 60)
    total = len(citations)
    pct = lambda n: f"{n} ({(100*n/total):.1f}%)" if total else f"{n}"
    print(f"  total candidates:   {total}")
    print(f"  resolved to PMID:   {pct(n_resolved)}")
    print(f"  not resolved:       {pct(n_unresolved)}")
    print(f"  already in library: {pct(n_skipped)}")
    print(f"  inserted:           {pct(n_inserted)}")
    print(f"  failed:             {pct(n_failed)}")

    if unresolved_log:
        print()
        print(f"  Sample unresolved (first 15 of {len(unresolved_log)}):")
        for label in unresolved_log[:15]:
            print(f"    - {label}")

    if not args.dry_run and inserted_log:
        print()
        try:
            stats = library_stats()
            print(f"  Library now: total={stats['total']}  by_level={stats['by_level']}")
        except Exception as e:
            print(f"  (stats unavailable: {e})")


if __name__ == "__main__":
    main()
