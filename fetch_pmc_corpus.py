"""
Endo AI — PMC Open-Access Bulk Fetcher
======================================
Downloads freely available endodontic papers directly from PubMed Central
and adds them to the local Neon vector library.

Why PMC instead of generic PubMed?
  • All results are open-access (no Elsevier paywall)
  • PMC provides richer abstracts and sometimes full-text sections
  • The 'free full text[sb]' filter guarantees free public availability

Usage:
    py fetch_pmc_corpus.py                  # full fetch across all topics
    py fetch_pmc_corpus.py --stats          # show current library stats
    py fetch_pmc_corpus.py --topic "NaOCl"  # single topic
    py fetch_pmc_corpus.py --dry-run        # count results, don't write
    py fetch_pmc_corpus.py --max 50         # papers per topic (default 40)
    py fetch_pmc_corpus.py --year 2015      # only papers >= this year
"""

import sys, os, time, json, re, argparse, requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.abspath("."), ".env"))

sys.path.insert(0, os.path.abspath("."))

from rag import setup_table, upsert_paper, embed, library_stats
from endo_ai import (
    extract_sample_size, extract_followup_period,
    get_impact_factor, score_paper,
)

# -- PMC-specific topics (expanded beyond build_library.py) ---------------
PMC_TOPICS = [
    # Vital pulp therapy
    "vital pulp therapy MTA mineral trioxide aggregate",
    "direct pulp cap calcium silicate cement",
    "Biodentine pulpotomy permanent teeth",
    "calcium hydroxide pulp capping outcomes",
    "partial pulpotomy Cvek technique",

    # Root canal outcomes & prognosis
    "root canal treatment success periapical healing",
    "endodontic treatment long-term prognosis systematic review",
    "single-visit root canal treatment randomized controlled trial",
    "multi-visit root canal calcium hydroxide interappointment",
    "root canal retreatment outcomes prognosis",
    "periapical periodontitis healing outcome CBCT",

    # Instruments & shaping
    "nickel-titanium rotary files shaping ability",
    "WaveOne Gold reciprocating endodontics",
    "ProTaper Universal rotary instrumentation",
    "glide path endodontics instrument separation",
    "instrument fracture retrieval root canal",
    "heat-treated NiTi files flexibility cyclic fatigue",
    "self-adjusting file SAF endodontics",

    # Irrigation
    "sodium hypochlorite concentration antimicrobial root canal",
    "EDTA smear layer irrigation protocol",
    "ultrasonic passive irrigation endodontics",
    "chlorhexidine gluconate irrigation comparison",
    "photodynamic therapy disinfection root canal",
    "apical negative pressure irrigation EndoVac",
    "final rinse EDTA NaOCl protocol",

    # Sealers & obturation
    "bioceramic sealer iRoot BC Sealer endodontics",
    "AH Plus epoxy resin sealer apical seal",
    "warm vertical compaction continuous wave obturation",
    "single cone technique bioceramic sealer",
    "cold lateral condensation comparison outcomes",
    "gutta-percha sealer bond strength push-out",

    # Diagnosis & imaging
    "CBCT cone beam CT endodontic diagnosis sensitivity",
    "periapical index radiographic healing",
    "irreversible pulpitis diagnosis accuracy pulp testing",
    "cracked tooth syndrome diagnosis treatment",
    "pulp vitality testing electric pulp test",
    "endodontic flare-up incidence prevention",

    # Periapical surgery
    "endodontic microsurgery apicoectomy retrograde filling",
    "MTA retrograde fill root end surgery outcomes",
    "periapical surgery success rate meta-analysis",
    "guided tissue regeneration periapical surgery",

    # Resorption
    "external inflammatory root resorption treatment",
    "internal root resorption management MTA",
    "invasive cervical resorption Heithersay classification",
    "replacement resorption ankylosis replantation",

    # Regenerative endodontics
    "regenerative endodontic procedures immature permanent teeth",
    "revascularization pulp regeneration blood clot scaffold",
    "apexification apical barrier MTA calcium hydroxide",
    "stem cells dental pulp regeneration",
    "platelet-rich plasma PRP endodontic regeneration",

    # Dental trauma
    "dental trauma avulsion replantation prognosis",
    "luxation injury pulp necrosis pulp canal obliteration",
    "crown fracture composite restoration pulp",
    "horizontal root fracture healing prognosis",
    "intrusion extrusion luxation treatment outcomes",

    # Implant vs endodontic decision
    "implant versus endodontic treatment cost-effectiveness",
    "tooth retention root canal treatment survival analysis",
    "endodontic implant decision patient-reported outcomes",

    # Antibiotics & pharmacology
    "antibiotics prophylaxis endodontic treatment",
    "triple antibiotic paste regenerative endodontics",
    "NSAIDs pain management endodontic treatment",
    "opioid prescribing endodontics acute pain",

    # Rubber dam & infection control
    "rubber dam isolation outcomes infection control",
    "working length determination electronic apex locator accuracy",
    "magnification operating microscope endodontics",

    # Special populations
    "endodontic treatment elderly patients outcomes",
    "endodontic treatment diabetes mellitus healing",
    "immunocompromised patients root canal treatment",

    # Biofilm & microbiology
    "Enterococcus faecalis root canal resistance",
    "polymicrobial biofilm endodontic infection",
    "apical microbiome culture-independent analysis",

    # Materials
    "mineral trioxide aggregate MTA properties clinical",
    "calcium silicate cement biocompatibility",
    "glass ionomer cement endodontic use",
]

# -- PubMed eUtils constants ----------------------------------------------
BASE_URL  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PMC_OA    = "free full text[sb]"          # free full-text in PMC
ENDO_MESH = "endodontics[MeSH]"          # scope to endodontics
NOT_RETR  = 'NOT "Retracted Publication"[pt]'

# Known open-access endodontic/dental journals (prioritise these)
OA_JOURNALS = [
    "BMC Oral Health",
    "Dentistry Journal",                  # MDPI
    "Frontiers in Dental Medicine",
    "International Journal of Dentistry",  # Hindawi
    "Brazilian Dental Journal",
    "Journal of Clinical and Experimental Dentistry",
    "European Journal of Dentistry",
    "Dental and Medical Problems",
    "International Endodontic Journal",
    "Journal of Oral Science",
    "Acta Odontologica Scandinavica",
    "Medicina Oral Patologia Oral y Cirugia Bucal",
    "Journal of Conservative Dentistry",
    "Nigerian Journal of Clinical Practice",
]

LEVEL_MAP = {
    # PubMed publication type -> evidence level key + score boost
    "systematic review[pt]":           ("level1", 80),
    "meta-analysis[pt]":               ("level1", 80),
    "randomized controlled trial[pt]": ("level1", 75),
    "clinical trial[pt]":              ("level2", 55),
    "comparative study[pt]":           ("level2", 50),
    "case-control studies[pt]":        ("level3", 40),
    "retrospective studies[pt]":       ("level3", 35),
    "case reports[pt]":                ("level4", 20),
    "review[pt]":                      ("level5", 15),
}


# -- Helpers --------------------------------------------------------------

def _get(url: str, params: dict, retries: int = 3) -> requests.Response | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=20)
            r.raise_for_status()
            return r
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
            else:
                print(f"      ! HTTP error: {e}")
    return None


def search_pmc(query: str, max_results: int = 40, min_year: int = 2000) -> list[str]:
    """Search PubMed with PMC OA filter. Returns list of PMIDs."""
    full_query = (
        f"({query}) AND {PMC_OA} AND {NOT_RETR}"
        f' AND ("{min_year}"[PDAT] : "3000"[PDAT])'
    )
    params = {
        "db":      "pubmed",
        "term":    full_query,
        "retmax":  max_results,
        "retmode": "json",
        "sort":    "relevance",
    }
    r = _get(f"{BASE_URL}/esearch.fcgi", params)
    if not r:
        return []
    try:
        return r.json()["esearchresult"].get("idlist", [])
    except Exception:
        return []


def fetch_medline(pmids: list[str]) -> dict[str, dict]:
    """
    Fetch papers in MEDLINE format — gets title, abstract, journal, year,
    authors all in one API call. Much more reliable than text/abstract format.

    MEDLINE record structure:
        PMID- 12345678
        TI  - Title of the paper
        AB  - Abstract first line
              continuation lines indented by 6 spaces
        AU  - Author Name
        JT  - Journal full title
        TA  - Journal abbreviation
        DP  - 2023 Jan
    """
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

    out: dict[str, dict] = {}
    cur: dict = {}
    cur_field: str = ""

    def _save():
        pid = cur.get("pmid")
        if pid:
            cur["authors"] = "; ".join(cur.pop("_authors", [])[:6])
            out[pid] = cur.copy()

    for line in r.text.split("\n"):
        # New field: "AB  - " pattern (code + spaces + dash + space)
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
            # Continuation line (6-space indent)
            cont = line.strip()
            if cur_field == "TI":
                cur["title"] = cur.get("title", "") + " " + cont
            elif cur_field == "AB":
                cur["abstract"] = cur.get("abstract", "") + " " + cont

    _save()
    return out


def infer_level(abstract_text: str, title: str = "") -> tuple[str, int]:
    """Guess evidence level from abstract keywords. Returns (level_key, base_score)."""
    combined = (abstract_text + " " + title).lower()
    if any(k in combined for k in ["cochrane", "cochrane review"]):
        return "cochrane", 90
    if any(k in combined for k in ["meta-analysis", "meta analysis", "systematic review"]):
        return "level1", 78
    if any(k in combined for k in ["randomized", "randomised", "rct", "double-blind"]):
        return "level1", 72
    if any(k in combined for k in ["prospective", "controlled trial", "clinical trial"]):
        return "level2", 52
    if any(k in combined for k in ["retrospective", "case-control", "cohort"]):
        return "level3", 38
    if any(k in combined for k in ["case series", "case report"]):
        return "level4", 22
    return "level5", 15


def build_paper_record(pmid: str, abstract_text: str, meta: dict) -> dict:
    """Construct a paper dict ready for rag.upsert_paper()."""
    sample_size     = extract_sample_size(abstract_text)
    followup        = extract_followup_period(abstract_text)
    followup_months = followup[0] if followup else None
    journal_name    = meta.get("journal", "")
    if_val, if_pts  = get_impact_factor(journal_name)
    year            = meta.get("year", "2010")

    level_key, _ = infer_level(abstract_text, meta.get("title", ""))

    score, _ = score_paper(
        level_key,
        year,
        meta.get("citations", 0),
        sample_size,
        followup_months,
        if_pts,
    )

    return {
        "pmid":            pmid,
        "title":           meta.get("title", ""),
        # FULL abstract — do NOT reinstate a character cap here. The stored
        # abstract is what the synthesis prompt reads, and PubMed abstracts put
        # CONCLUSIONS last, so the old [:1200] cap stored papers that stop
        # before their findings. The sentence-transformer's 256-token window is
        # respected by the [:400] slice on the embed() text in fetch_topic();
        # that one is deliberate, this one was a bug.
        "abstract":        abstract_text,
        "authors":         meta.get("authors", ""),
        "year":            int(year) if str(year).isdigit() else 2010,
        "journal":         journal_name,
        "impact_factor":   if_val,
        "sample_size":     sample_size,
        "followup_months": followup_months,
        "citations":       meta.get("citations", 0),
        "level_key":       level_key,
        "score":           score,
    }


# -- Main fetch routine ---------------------------------------------------

def fetch_topic(topic: str, seen_pmids: set, max_per_topic: int = 40,
                min_year: int = 2000, dry_run: bool = False) -> int:
    """Fetch, score, embed, upsert papers for one topic. Returns count added."""
    pmids = search_pmc(topic, max_results=max_per_topic, min_year=min_year)
    new_pmids = [p for p in pmids if p not in seen_pmids]

    if not new_pmids:
        return 0
    if dry_run:
        seen_pmids.update(new_pmids)
        return len(new_pmids)

    # Single MEDLINE fetch — title + abstract + journal + year + authors in one call
    BATCH = 20
    records: dict[str, dict] = {}
    for i in range(0, len(new_pmids), BATCH):
        batch = new_pmids[i : i + BATCH]
        records.update(fetch_medline(batch))
        time.sleep(0.35)

    added = 0
    for pmid in new_pmids:
        rec      = records.get(pmid, {})
        abstract = rec.get("abstract", "").strip()
        if len(abstract) < 60:          # skip if almost no content
            continue
        paper = build_paper_record(pmid, abstract, rec)

        embed_text = f"{topic} {paper.get('title', '')} {abstract[:400]}"
        try:
            vec = embed(embed_text)
        except Exception as emb_err:
            print(f"      ! Embed error {pmid}: {emb_err}")
            continue

        try:
            upsert_paper(paper, vec)
            seen_pmids.add(pmid)
            added += 1
        except Exception as db_err:
            print(f"      ! DB error {pmid}: {db_err}")

    return added


# -- Entry point ----------------------------------------------------------

def run(topics=None, max_per_topic=40, min_year=2000, dry_run=False):
    print("\n" + "=" * 60)
    print("  Endo AI — PMC Open-Access Corpus Fetcher")
    print("=" * 60)
    if dry_run:
        print("  [DRY RUN — no data will be written]\n")

    setup_table()

    stats_before = library_stats()
    print(f"  Library before: {stats_before['total']} papers\n")

    topics_to_run = topics or PMC_TOPICS
    seen_pmids: set = set()
    total_added = 0

    for i, topic in enumerate(topics_to_run, 1):
        print(f"[{i:02d}/{len(topics_to_run):02d}] {topic[:70]}")
        try:
            n = fetch_topic(topic, seen_pmids,
                            max_per_topic=max_per_topic,
                            min_year=min_year,
                            dry_run=dry_run)
            total_added += n
            tag = "(dry-run)" if dry_run else "added"
            print(f"        -> {n} {tag}  |  running total: {total_added}")
        except Exception as e:
            print(f"        ! Topic error: {e}")
        time.sleep(0.4)

    print(f"\n{'='*60}")
    print(f"  Done.  {'Would add' if dry_run else 'Added'} {total_added} papers.")
    if not dry_run:
        stats_after = library_stats()
        print(f"  Library now: {stats_after['total']} papers")
        print(f"  By level:    {stats_after['by_level']}")
        print(f"  Year range:  {stats_after['year_range']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PMC Open-Access corpus fetcher for Endo AI")
    parser.add_argument("--stats",    action="store_true", help="Show library stats and exit")
    parser.add_argument("--dry-run",  action="store_true", help="Count results only, no DB writes")
    parser.add_argument("--topic",    type=str,  default=None, help="Single topic override")
    parser.add_argument("--max",      type=int,  default=40,   help="Max papers per topic (default 40)")
    parser.add_argument("--year",     type=int,  default=2000, help="Minimum publication year (default 2000)")
    args = parser.parse_args()

    if args.stats:
        setup_table()
        s = library_stats()
        print(f"\nLibrary stats:")
        print(f"  Total papers : {s['total']}")
        print(f"  By level     : {s['by_level']}")
        print(f"  Year range   : {s['year_range']}\n")
    else:
        topics = [args.topic] if args.topic else None
        run(topics=topics, max_per_topic=args.max,
            min_year=args.year, dry_run=args.dry_run)
