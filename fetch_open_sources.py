"""
Endo AI -- Elsevier-Free Open Source Fetcher
============================================
Supplements the endo corpus with papers from open-access sources that do
NOT require an Elsevier subscription. Designed to be run after
build_library.py to fill gaps with freely available high-quality evidence.

Sources targeted:
  +---------------------------------+---------------------------------------+
  | Source                          | Notes                                 |
  +---------------------------------┼---------------------------------------+
  | PMC Open Access subset          | 'free full text[sb]' filter            |
  | MDPI (Dentistry Journal etc.)   | MDPI[Publisher] -- fully free          |
  | Frontiers in Dental Medicine    | Fully OA, Nature portfolio            |
  | BMC Oral Health                 | BioMed Central -- fully OA             |
  | StatPearls (NCBI Bookshelf)     | NBK articles, clinical overviews      |
  | Dental Traumatology (Wiley OA)  | ISSN 1600-9657, trauma focus          |
  | International Journal of        |                                       |
  |   Environmental Research &      | MDPI, OA, some dental content         |
  |   Public Health                 |                                       |
  | Brazilian Dental Journal        | SciELO OA, strong endo content        |
  | Journal of Oral Science         | J-STAGE OA, Nihon University          |
  | European Journal of Dentistry   | Thieme OA                             |
  | Journal of Clinical &           |                                       |
  |   Experimental Dentistry        | Medicina Oral -- OA                    |
  | Medicina Oral Patologia Oral    | OA, Spanish/international             |
  +---------------------------------┴---------------------------------------+

Usage:
    py fetch_open_sources.py                     # all sources
    py fetch_open_sources.py --source mdpi        # MDPI only
    py fetch_open_sources.py --source statpearls  # StatPearls only
    py fetch_open_sources.py --source frontiers   # Frontiers only
    py fetch_open_sources.py --source bmc         # BMC Oral Health only
    py fetch_open_sources.py --source trauma      # Dental Traumatology only
    py fetch_open_sources.py --source brazil      # Brazilian / J Oral Sci
    py fetch_open_sources.py --stats              # library stats only
    py fetch_open_sources.py --dry-run            # count, no writes
    py fetch_open_sources.py --max 30             # papers per query (default 25)
    py fetch_open_sources.py --year 2010          # min publication year
"""

import sys, os, re, time, json, argparse, requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.abspath("."), ".env"))
sys.path.insert(0, os.path.abspath("."))

from rag import setup_table, upsert_paper, embed, library_stats
from endo_ai import (
    extract_sample_size, extract_followup_period,
    get_impact_factor, score_paper,
)

BASE_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
HEADERS     = {"User-Agent": "EndoAI-RAG/1.0 (research tool; non-commercial)"}

# -- Source definitions ----------------------------------------------------
# Each source is a dict:
#   name       : display name
#   key        : CLI --source key
#   pubmed_filter : string appended to topic query
#   queries    : list of standalone search strings (no topic needed)
#   level_key  : default evidence level (overridden by abstract inference)
#   if_default : default impact factor if journal not in lookup dict

SOURCES: list[dict] = [
    {
        "name":          "MDPI -- Dentistry Journal & Applied Sciences",
        "key":           "mdpi",
        "pubmed_filter": '"Dentistry Journal"[journal]',
        "level_key":     "level3",
        "if_default":   2.5,
        "queries": [
            '"Dentistry Journal"[journal] AND (endodont* OR "root canal" OR pulp)',
            '"J Clin Med"[journal] AND (endodontics OR "root canal" OR "pulp therapy") AND free full text[sb]',
            '"Int J Environ Res Public Health"[journal] AND (dental OR endodontics) AND free full text[sb] AND 2015:2024[PDAT]',
            '"Healthcare (Basel)"[journal] AND (endodontics OR root canal) AND free full text[sb]',
            '"Applied Sciences"[journal] AND endodontics AND free full text[sb]',
        ],
    },
    {
        "name":          "Frontiers in Dental Medicine",
        "key":           "frontiers",
        "pubmed_filter": '"Frontiers in Dental Medicine"[journal]',
        "level_key":     "level3",
        "if_default":   2.8,
        "queries": [
            '"Frontiers in Dental Medicine"[journal] AND (endodontics OR "root canal")',
            '"Frontiers in Dental Medicine"[journal] AND (pulp OR periapical OR obturation)',
            '"Frontiers in Dental Medicine"[journal] AND (irrigation OR instrumentation OR sealer)',
        ],
    },
    {
        "name":          "BMC Oral Health",
        "key":           "bmc",
        "pubmed_filter": '"BMC Oral Health"[journal]',
        "level_key":     "level2",
        "if_default":   3.0,
        "queries": [
            '"BMC Oral Health"[journal] AND (endodontics OR "root canal treatment")',
            '"BMC Oral Health"[journal] AND (pulp therapy OR periapical OR canal shaping)',
            '"BMC Oral Health"[journal] AND (randomized OR systematic review OR meta-analysis) AND endodont*',
            '"BMC Oral Health"[journal] AND (vital pulp OR MTA OR bioceramic OR NaOCl)',
        ],
    },
    {
        "name":          "StatPearls -- NCBI Bookshelf Clinical Overviews",
        "key":           "statpearls",
        "pubmed_filter": 'StatPearls[Publisher]',
        "level_key":     "level5",
        "if_default":   0.0,
        "queries": [
            'StatPearls[Publisher] AND (endodontics OR "root canal" OR "dental pulp")',
            'StatPearls[Publisher] AND (pulpitis OR periapical periodontitis OR dental abscess)',
            'StatPearls[Publisher] AND (dental trauma OR avulsion OR luxation)',
            'StatPearls[Publisher] AND (pulp necrosis OR apical abscess OR dental pain)',
            'StatPearls[Publisher] AND (tooth resorption OR ankylosis OR replantation)',
        ],
    },
    {
        "name":          "Dental Traumatology (Wiley OA articles)",
        "key":           "trauma",
        "pubmed_filter": '"Dent Traumatol"[journal]',
        "level_key":     "level2",
        "if_default":   2.4,
        "queries": [
            '"Dent Traumatol"[journal] AND (avulsion replantation prognosis)',
            '"Dent Traumatol"[journal] AND (luxation pulp necrosis survival)',
            '"Dent Traumatol"[journal] AND (root fracture healing prognosis)',
            '"Dent Traumatol"[journal] AND (intrusion extrusion treatment outcome)',
            '"Dent Traumatol"[journal] AND (immature tooth pulp regeneration)',
            '"Dent Traumatol"[journal] AND (systematic review OR meta-analysis)',
            '"Dent Traumatol"[journal] AND (IADT guideline OR recommendation)',
        ],
    },
    {
        "name":          "Brazilian Dental Journal + Journal of Oral Science",
        "key":           "brazil",
        "pubmed_filter": '("Brazilian Dental Journal"[journal] OR "Journal of Oral Science"[journal]) AND free full text[sb]',
        "level_key":     "level3",
        "if_default":   1.8,
        "queries": [
            '"Brazilian Dental Journal"[journal] AND (endodontics OR "root canal") AND free full text[sb]',
            '"Brazilian Dental Journal"[journal] AND (MTA OR calcium silicate OR bioceramic) AND free full text[sb]',
            '"Journal of Oral Science"[journal] AND endodontics AND free full text[sb]',
            '"Journal of Oral Science"[journal] AND ("root canal" OR pulp OR periapical) AND free full text[sb]',
        ],
    },
    {
        "name":          "European Journal of Dentistry + Medicina Oral",
        "key":           "euro",
        "pubmed_filter": '("European Journal of Dentistry"[journal] OR "Medicina Oral Patologia Oral y Cirugia Bucal"[journal]) AND free full text[sb]',
        "level_key":     "level3",
        "if_default":   1.5,
        "queries": [
            '"European Journal of Dentistry"[journal] AND endodontics AND free full text[sb]',
            '"European Journal of Dentistry"[journal] AND ("root canal" OR pulp) AND free full text[sb]',
            '"Medicina Oral Patologia Oral y Cirugia Bucal"[journal] AND endodontics AND free full text[sb]',
        ],
    },
    {
        "name":          "Broad PMC OA -- High-Level Endo Evidence",
        "key":           "pmc-hl",
        "pubmed_filter": 'free full text[sb]',
        "level_key":     "level1",
        "if_default":   3.5,
        "queries": [
            # Systematic reviews & meta-analyses, PMC OA only
            '(systematic review[pt] OR meta-analysis[pt]) AND endodontics[MeSH] AND free full text[sb] AND 2015:2024[PDAT]',
            '(systematic review[pt] OR meta-analysis[pt]) AND ("root canal treatment" OR "vital pulp therapy") AND free full text[sb] AND 2015:2024[PDAT]',
            '(randomized controlled trial[pt]) AND endodontics[MeSH] AND free full text[sb] AND 2015:2024[PDAT]',
            '(randomized controlled trial[pt]) AND ("root canal" OR "pulp capping" OR obturation) AND free full text[sb] AND 2015:2024[PDAT]',
            # Cochrane-adjacent
            '"Cochrane Database Syst Rev"[journal] AND (endodontics OR "root canal" OR "dental pulp")',
        ],
    },
]

# -- Endodontic topic queries to combine with source filters ---------------
ENDO_TOPIC_QUERIES = [
    "vital pulp therapy",
    "root canal treatment outcomes",
    "canal instrumentation NiTi",
    "root canal irrigation NaOCl",
    "bioceramic sealer obturation",
    "periapical surgery microsurgery",
    "dental trauma avulsion",
    "regenerative endodontics",
    "root resorption management",
    "endodontic retreatment",
    "cracked tooth syndrome",
    "CBCT endodontic diagnosis",
]


# -- Helpers --------------------------------------------------------------

def _get(url: str, params: dict, retries: int = 3) -> requests.Response | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=20)
            r.raise_for_status()
            return r
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1.2 * (attempt + 1))
            else:
                print(f"      ! HTTP {e}")
    return None


def esearch(query: str, max_results: int) -> list[str]:
    r = _get(f"{BASE_EUTILS}/esearch.fcgi", {
        "db": "pubmed", "term": query,
        "retmax": max_results, "retmode": "json",
        "sort": "relevance",
    })
    if not r:
        return []
    try:
        return r.json()["esearchresult"].get("idlist", [])
    except Exception:
        return []


def fetch_medline(pmids: list[str]) -> dict[str, dict]:
    """
    Fetch papers in MEDLINE format -- returns {pmid: {title, abstract, journal, year, authors}}.
    Single API call replaces separate efetch + esummary + elink calls.
    Parses MEDLINE tagged format:
        PMID- 12345678
        TI  - Title
        AB  - Abstract (continuation lines indented 6 spaces)
        AU  - Author
        JT  - Journal Title
        DP  - 2023 Jan
    """
    if not pmids:
        return {}
    r = _get(f"{BASE_EUTILS}/efetch.fcgi", {
        "db": "pubmed", "id": ",".join(pmids),
        "rettype": "medline", "retmode": "text",
    })
    if not r:
        return {}

    out: dict[str, dict] = {}
    cur: dict = {}
    cur_field: str = ""

    def _save():
        pid = cur.get("pmid")
        if pid:
            cur["authors"] = "; ".join(cur.pop("_au", [])[:6])
            out[pid] = cur.copy()

    for line in r.text.split("\n"):
        m = re.match(r'^([A-Z]{2,4})\s*-\s(.*)', line)
        if m:
            tag, val = m.group(1), m.group(2).strip()
            cur_field = tag
            if tag == "PMID":
                _save()
                cur = {"pmid": val, "_au": [], "abstract": "",
                       "title": "", "journal": "", "year": "2010", "citations": 0}
            elif tag == "TI":
                cur["title"] = val
            elif tag == "AB":
                cur["abstract"] = val
            elif tag == "AU":
                cur.setdefault("_au", []).append(val)
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


def infer_level(text: str, default: str = "level3") -> tuple[str, float]:
    """Infer evidence level and base score from abstract text."""
    t = text.lower()
    if "cochrane" in t:
        return "cochrane", 92.0
    if any(k in t for k in ["meta-analysis", "meta analysis", "systematic review"]):
        return "level1", 80.0
    if any(k in t for k in ["randomized", "randomised", "rct", "double-blind", "double blind"]):
        return "level1", 73.0
    if any(k in t for k in ["prospective", "clinical trial", "controlled trial"]):
        return "level2", 55.0
    if any(k in t for k in ["retrospective", "cohort", "case-control"]):
        return "level3", 40.0
    if any(k in t for k in ["case series", "case report"]):
        return "level4", 23.0
    return default, 18.0


def build_record(pmid: str, abstract: str, meta: dict, source: dict) -> dict:
    """Build a paper record dict from metadata + source config."""
    sample_size     = extract_sample_size(abstract)
    followup        = extract_followup_period(abstract)
    followup_months = followup[0] if followup else None
    journal_name    = meta.get("journal", "")
    if_val, if_pts  = get_impact_factor(journal_name)
    if if_val == 0:
        if_val  = source["if_default"]
        if_pts  = if_val * 1.5          # approx pts from IF

    year_str = meta.get("year", "2010")
    level_key, base_score = infer_level(abstract, default=source["level_key"])

    score, _ = score_paper(
        level_key,
        year_str,
        meta.get("citations", 0),
        sample_size,
        followup_months,
        if_pts,
    )

    return {
        "pmid":            pmid,
        "title":           meta.get("title", ""),
        "abstract":        abstract[:1200],
        "authors":         meta.get("authors", ""),
        "year":            int(year_str) if str(year_str).isdigit() else 2010,
        "journal":         journal_name,
        "impact_factor":   if_val,
        "sample_size":     sample_size,
        "followup_months": followup_months,
        "citations":       meta.get("citations", 0),
        "level_key":       level_key,
        "score":           score,
    }


def process_pmids(pmids: list[str], source: dict, seen: set,
                  max_per_topic: int, dry_run: bool) -> int:
    """Fetch, score, embed, and upsert a batch of PMIDs. Returns count added."""
    new_pmids = [p for p in pmids if p not in seen]
    if not new_pmids:
        return 0
    if dry_run:
        seen.update(new_pmids)
        return len(new_pmids)

    # Single MEDLINE fetch -- no separate metadata or elink calls needed
    BATCH = 20
    records: dict[str, dict] = {}
    for i in range(0, len(new_pmids), BATCH):
        records.update(fetch_medline(new_pmids[i : i + BATCH]))
        time.sleep(0.35)

    added = 0
    for pmid in new_pmids:
        rec      = records.get(pmid, {})
        abstract = rec.get("abstract", "").strip()
        if len(abstract) < 60:
            continue
        record = build_record(pmid, abstract, rec, source)
        text   = f"{record.get('title', '')} {abstract[:400]}"
        try:
            vec = embed(text)
            upsert_paper(record, vec)
            seen.add(pmid)
            added += 1
        except Exception as e:
            print(f"        ! {pmid}: {e}")

    return added


# -- Per-source fetch routine ----------------------------------------------

def fetch_source(source: dict, seen: set, max_per_query: int = 25,
                 min_year: int = 2000, dry_run: bool = False) -> int:
    """Run all queries for one source. Returns total papers added."""
    total = 0

    # 1. Standalone queries defined in the source
    for q in source.get("queries", []):
        full_q = q + f' AND "{min_year}"[PDAT]:"3000"[PDAT]'
        pmids  = esearch(full_q, max_per_query)
        n      = process_pmids(pmids, source, seen, max_per_query, dry_run)
        total += n
        if n > 0:
            print(f"      {n} papers  <- {q[:65]}")
        time.sleep(0.4)

    # 2. Cross-query: source filter × endo topics
    pf = source.get("pubmed_filter", "")
    if pf:
        for topic in ENDO_TOPIC_QUERIES:
            q = (
                f'({topic}) AND ({pf})'
                f' AND NOT "Retracted Publication"[pt]'
                f' AND "{min_year}"[PDAT]:"3000"[PDAT]'
            )
            pmids  = esearch(q, max_per_query)
            n      = process_pmids(pmids, source, seen, max_per_query, dry_run)
            total += n
            if n > 0:
                print(f"      {n} papers  <- {topic} × {source['key']}")
            time.sleep(0.35)

    return total


# -- Entry point ----------------------------------------------------------

def run(source_keys=None, max_per_query=25, min_year=2000, dry_run=False):
    print("\n" + "=" * 62)
    print("  Endo AI -- Elsevier-Free Open Source Fetcher")
    print("=" * 62)
    if dry_run:
        print("  [DRY RUN -- no data will be written]\n")

    setup_table()
    stats_before = library_stats()
    print(f"  Library before: {stats_before['total']} papers\n")

    sources_to_run = (
        [s for s in SOURCES if s["key"] in source_keys]
        if source_keys else SOURCES
    )

    seen: set = set()
    grand_total = 0

    for src in sources_to_run:
        print(f"\n  >> {src['name']}")
        n = fetch_source(src, seen,
                         max_per_query=max_per_query,
                         min_year=min_year,
                         dry_run=dry_run)
        grand_total += n
        tag = "would add" if dry_run else "added"
        print(f"    -> {n} papers {tag} from this source")

    print(f"\n{'='*62}")
    print(f"  Complete. {'Would add' if dry_run else 'Added'} {grand_total} papers total.")
    if not dry_run:
        stats_after = library_stats()
        print(f"  Library now : {stats_after['total']} papers")
        print(f"  By level    : {stats_after['by_level']}")
        print(f"  Year range  : {stats_after['year_range']}")
    print(f"{'='*62}\n")


if __name__ == "__main__":
    valid_keys = [s["key"] for s in SOURCES]

    parser = argparse.ArgumentParser(description="Elsevier-free open source fetcher for Endo AI")
    parser.add_argument("--stats",   action="store_true",
                        help="Show library stats and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="Count results only, no DB writes")
    parser.add_argument("--source",  type=str, default=None,
                        help=f"Single source key: {', '.join(valid_keys)}")
    parser.add_argument("--max",     type=int, default=25,
                        help="Max papers per query (default 25)")
    parser.add_argument("--year",    type=int, default=2000,
                        help="Minimum publication year (default 2000)")
    args = parser.parse_args()

    if args.stats:
        setup_table()
        s = library_stats()
        print(f"\nLibrary stats:")
        print(f"  Total  : {s['total']}")
        print(f"  Levels : {s['by_level']}")
        print(f"  Years  : {s['year_range']}\n")
    else:
        keys = [args.source] if args.source else None
        if keys and keys[0] not in valid_keys:
            print(f"Unknown source '{keys[0]}'. Valid: {', '.join(valid_keys)}")
            sys.exit(1)
        run(source_keys=keys, max_per_query=args.max,
            min_year=args.year, dry_run=args.dry_run)
