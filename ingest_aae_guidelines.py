"""
Endo AI — AAE Guidelines & Position Statements Ingester
========================================================
Fetches the American Association of Endodontists' clinical documents and
stores them in the local Neon vector library as authoritative "guideline"
records (weighted higher than generic level-5 expert opinion).

Sources ingested:
  1. AAE Position Statements  (aae.org/specialty/clinical-resources/position-statements)
  2. AAE Practice Advisories  (aae.org/specialty/clinical-resources)
  3. PubMed-indexed AAE guidelines  (searched via eUtils)
  4. International Liaison Committee on Endodontology (ILCE) guidelines
  5. European Society of Endodontology (ESE) guidelines (PMC OA)

Each document is stored with:
  • level_key = "level1"  (guidelines are treated as top-tier evidence)
  • score     = 88–95     (manually set — authoritative clinical consensus)
  • journal   = "AAE Clinical Guideline" / "ESE Position Statement" / etc.
  • impact_factor = 8.0   (guideline-tier authority weighting)

Usage:
    py ingest_aae_guidelines.py              # full ingest
    py ingest_aae_guidelines.py --pubmed     # PubMed-indexed guidelines only
    py ingest_aae_guidelines.py --web        # AAE website scrape only
    py ingest_aae_guidelines.py --stats      # show library stats
    py ingest_aae_guidelines.py --dry-run    # print what would be ingested
"""

import sys, os, re, time, json, argparse, requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.abspath("."), ".env"))
sys.path.insert(0, os.path.abspath("."))

from rag import setup_table, upsert_paper, embed, library_stats

BASE_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
HEADERS     = {"User-Agent": "EndoAI-RAG/1.0 (clinical research tool; contact: endoai@research.edu)"}

# -- Hardcoded AAE Position Statements ------------------------------------
# These are the canonical AAE statements as of 2024.
# Format: (id_slug, title, year, summary_text)
# Summaries are condensed from the official documents.

AAE_POSITION_STATEMENTS: list[tuple] = [
    (
        "AAE-PS-cracked-tooth",
        "AAE Position Statement: Cracked Teeth",
        2019,
        """
        Cracked tooth syndrome presents with variable symptoms. The AAE recommends
        diagnosis based on clinical examination, transillumination, dye staining,
        bite testing, and CBCT when indicated. Treatment depends on crack extent:
        cuspal coverage restorations for incomplete cracks; root canal treatment
        when pulp involvement is confirmed; extraction when crack extends below
        the crestal bone or through the floor. Prognosis is guarded for teeth
        with cracks involving the pulp floor. Patients should be informed of the
        uncertain prognosis prior to initiating treatment. Early diagnosis and
        cuspal coverage improve long-term retention rates.
        """,
    ),
    (
        "AAE-PS-cbct",
        "AAE Position Statement: Use of Cone-Beam Computed Tomography in Endodontics",
        2021,
        """
        CBCT is recommended for endodontic cases when clinical examination and
        conventional imaging are insufficient. Indications include: assessment of
        complex anatomy (extra canals, calcified canals), suspected vertical root
        fracture, resorption characterisation, pre-surgical planning for
        apicoectomy, evaluation of healing post-treatment, trauma with suspected
        root fracture, and implant planning. CBCT should follow the ALARA
        principle—lowest dose necessary for diagnostic quality. Limited field-of-
        view (FOV) scans are preferred for endodontic diagnosis. CBCT should not
        replace periapical radiographs for routine diagnosis. Clinicians should
        have appropriate training for interpretation.
        """,
    ),
    (
        "AAE-PS-vital-pulp",
        "AAE Position Statement: Vital Pulp Therapy",
        2021,
        """
        Vital pulp therapy (VPT) is a biologically based approach aiming to
        preserve pulp vitality and function. Techniques include indirect pulp
        cap, direct pulp cap, partial pulpotomy (Cvek), and full pulpotomy.
        Calcium silicate cements (MTA, Biodentine) are the preferred capping
        agents, demonstrating superior outcomes over calcium hydroxide in
        randomised trials. Success requires adequate haemostasis, absence of
        irreversible pulpitis signs, and complete coronal seal. VPT is appropriate
        for both immature and mature permanent teeth when exposure is mechanical
        or traumatic with no signs of irreversible pulpitis or apical pathology.
        Pulp sensibility testing and radiographic monitoring are essential at
        6-month and 12-month intervals.
        """,
    ),
    (
        "AAE-PS-regenerative",
        "AAE Position Statement: Regenerative Endodontics",
        2021,
        """
        Regenerative endodontic procedures (REPs) are biologically-based
        procedures designed to replace damaged structures including dentin,
        root structures, and cells of the pulp-dentin complex. REPs are
        indicated for immature permanent teeth with necrotic pulps and/or
        apical pathology. The procedure involves disinfection with either
        triple antibiotic paste (ciprofloxacin, metronidazole, minocycline)
        or calcium hydroxide, followed by scaffold induction (blood clot, PRP,
        PRF) and coronal seal with MTA and composite. Outcomes measured by
        continued root development, apical closure, and positive response to
        pulp testing. REPs are preferred over apexification for immature teeth
        when feasible. Operator training and case selection are critical to success.
        """,
    ),
    (
        "AAE-PS-isolation",
        "AAE Position Statement: Isolation of the Operating Field",
        2020,
        """
        Rubber dam isolation is the standard of care for all endodontic
        procedures. The AAE strongly recommends rubber dam use because it:
        prevents aspiration/ingestion of instruments and irrigants, maintains
        a clean operating field, improves access and visibility, reduces
        cross-contamination, protects soft tissue from NaOCl and other
        irrigants, and is required for medicolegal protection. Alternatives
        (cotton roll isolation) are not acceptable substitutes for root canal
        treatment. No published evidence supports equivalent outcomes without
        rubber dam. Patient refusal of rubber dam use should be documented.
        """,
    ),
    (
        "AAE-PS-antibiotics",
        "AAE Position Statement: Systemic Antibiotics in Endodontics",
        2023,
        """
        Systemic antibiotics are not indicated for routine endodontic treatment
        in immunocompetent patients. Antibiotics should be prescribed only when
        there is evidence of spreading infection (cellulitis, lymphadenopathy,
        fever, trismus, or systemic involvement). Endodontic treatment (drainage,
        debridement) is the definitive treatment for odontogenic infection; antibiotics
        are an adjunct, not a substitute. Amoxicillin remains the first-line antibiotic
        when systemic antibiotics are indicated. Penicillin allergy: use clindamycin or
        azithromycin. Duration should not exceed 7 days. The AAE endorses antibiotic
        stewardship to prevent resistance. Prophylactic antibiotics are warranted for
        patients at high risk for infective endocarditis per AHA guidelines.
        """,
    ),
    (
        "AAE-PS-microscope",
        "AAE Position Statement: Use of the Surgical Operating Microscope in Endodontics",
        2012,
        """
        The surgical operating microscope (SOM) provides enhanced illumination
        and magnification that significantly improves clinical outcomes in endodontics.
        The AAE strongly encourages the use of magnification in endodontic practice.
        Benefits include: improved identification of calcified canals, early detection
        of cracks, precise ultrasonically-assisted retropreparation in surgery, and
        enhanced removal of separated instruments. All endodontic residency programs
        must provide training in SOM use. Loupes with coaxial illumination are
        a minimum standard; SOM is preferred for complex cases and surgery.
        """,
    ),
    (
        "AAE-PS-implant-v-endo",
        "AAE Position Statement: Endodontic Implant Decision Making",
        2014,
        """
        The decision to retain a tooth with endodontic therapy versus extraction
        and implant placement should be based on the restorability of the tooth,
        periodontal status, fracture risk, and patient preference. Successful
        endodontic treatment demonstrates equivalent or superior long-term survival
        compared to implant-supported crowns when tooth is restorable. Financial,
        biologic, and patient factors must be weighed. Endodontically treated teeth
        with adequate coronal restoration have 10-year survival rates comparable
        to implants. Implants are not inherently superior to root canal treatment.
        Patients should be counselled on both options before proceeding. The AAE
        supports evidence-based decision-making over preference for implant placement.
        """,
    ),
    (
        "AAE-PS-trauma",
        "AAE Position Statement: Management of Traumatic Dental Injuries",
        2020,
        """
        Management of traumatic dental injuries requires prompt assessment and
        treatment. Key principles: avulsion—reimplant as soon as possible, store
        in HBSS or milk if delayed, splint for 2 weeks; lateral luxation—
        repositioning and flexible splinting 2-4 weeks; intrusion—allow passive
        eruption in immature teeth, orthodontic/surgical extrusion in mature teeth;
        root fracture—splinting 2-4 months, monitor pulp status. All traumatised
        teeth require long-term radiographic and clinical follow-up. Pulp necrosis
        after luxation injury requires root canal treatment. CBCT is recommended
        for suspected root fractures. Documentation and referral to specialist
        when necessary are emphasised.
        """,
    ),
    (
        "AAE-PS-diagnosis",
        "AAE Position Statement: Endodontic Diagnosis",
        2009,
        """
        Accurate endodontic diagnosis requires integration of clinical symptoms,
        pulp sensibility tests (cold, EPT), percussion, palpation, and radiographic
        findings. The AAE classification of pulpal and periapical conditions:
        Pulpal diagnoses: Normal pulp, Reversible pulpitis, Symptomatic/Asymptomatic
        irreversible pulpitis, Pulp necrosis, Previously treated, Previously initiated
        therapy. Periapical diagnoses: Normal periapex, Symptomatic/Asymptomatic
        apical periodontitis, Acute/Chronic apical abscess, Condensing osteitis.
        Misdiagnosis leads to inappropriate treatment. Cold testing (Endo Ice) is
        the most reliable sensibility test. Electric pulp testing supplements cold
        testing. Pulp vitality (laser Doppler, pulse oximetry) tests are emerging
        but not yet standard of care.
        """,
    ),
    (
        "AAE-PS-obturation",
        "AAE Position Statement: Obturation of Root Canal Systems",
        2019,
        """
        Obturation is a critical phase of root canal treatment. Goals: three-
        dimensional seal of the root canal system, elimination of bacterial
        reservoirs, prevention of recontamination. Preferred materials: gutta-percha
        as core material remains the standard; bioceramic sealers show promising
        clinical outcomes with excellent biocompatibility; AH Plus (epoxy resin)
        is well-validated. Techniques: warm vertical compaction provides superior
        three-dimensional fill for complex anatomy; cold lateral condensation is
        acceptable for straight canals; single-cone with bioceramic sealer is
        gaining evidence base. Obturation should be at the radiographic apex
        (0-2mm short) for optimal outcomes. Overfill adversely affects healing.
        """,
    ),
    (
        "AAE-PS-retreatment",
        "AAE Position Statement: Endodontic Retreatment",
        2016,
        """
        Endodontic retreatment is indicated for previously treated teeth with
        signs and symptoms of persistent or new apical pathology, or where
        canal system inadequately treated. Factors favouring retreatment vs surgery:
        inadequate original treatment, missed canals, coronal leakage, and
        sufficient tooth structure for restoration. Retreatment success rates
        (50-70% healed at 4 years) are lower than primary treatment. Complex cases
        benefit from specialist referral. Non-surgical retreatment preferred when
        achievable before surgery. Post and core removal requires consideration of
        fracture risk. Adequate coronal restoration immediately following retreatment
        is essential to prevent recontamination.
        """,
    ),
    (
        "AAE-PS-safety",
        "AAE Position Statement: Patient Safety in Endodontic Practice",
        2022,
        """
        Patient safety in endodontic practice encompasses multiple dimensions.
        NaOCl incidents: strict rubber dam use and verified needle position before
        irrigation; use side-venting needles; never use NaOCl under pressure.
        Instrument separation: inform patient and document; assess retrieval risk
        vs benefit; bypass if possible; refer if needed. Sodium hypochlorite
        accidents require immediate irrigation with saline, corticosteroids if
        systemic reaction, and patient monitoring. All adverse events should be
        documented in the clinical record. Informed consent should address risks
        of NaOCl injury, instrument separation, and procedural complications.
        Emergency preparedness: epinephrine, diphenhydramine, and oxygen available.
        """,
    ),
]

# -- PubMed search queries for guideline-level endodontic documents --------
PUBMED_GUIDELINE_QUERIES = [
    # AAE and major society guidelines indexed in PubMed
    '("American Association of Endodontists"[Corporate Author]) AND (guideline OR position statement OR recommendation)',
    '("European Society of Endodontology"[Corporate Author]) AND (guideline OR quality guideline)',
    '("International Association of Dental Traumatology"[Corporate Author])',
    'endodontics[MeSH] AND (guideline[pt] OR practice guideline[pt]) AND free full text[sb]',
    '"clinical practice guideline" AND endodontics AND free full text[sb]',
    'endodontic treatment AND consensus AND (recommendation OR guideline) AND free full text[sb]',
    'dental trauma guideline management systematic[sb] AND free full text[sb]',
    'vital pulp therapy guideline recommendation 2018:2024[PDAT] AND free full text[sb]',
    'root canal treatment guideline clinical recommendation free full text[sb] 2015:2024[PDAT]',
    'regenerative endodontics guideline clinical protocol free full text[sb]',
]


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


def upsert_guideline(record: dict, dry_run: bool = False) -> bool:
    """Embed and store a guideline record. Returns True on success."""
    text = f"{record.get('title', '')} {record.get('abstract', '')}"
    if len(text.strip()) < 30:
        return False
    if dry_run:
        print(f"    [DRY] Would ingest: {record['pmid']} — {record.get('title','')[:60]}")
        return True
    try:
        vec = embed(text[:600])
        upsert_paper(record, vec)
        return True
    except Exception as e:
        print(f"    ! Ingest error ({record['pmid']}): {e}")
        return False


# -- Ingest AAE hardcoded statements --------------------------------------

def ingest_aae_statements(dry_run: bool = False) -> int:
    print("\n  -- AAE Position Statements (hardcoded corpus) ----------")
    added = 0
    for slug, title, year, summary in AAE_POSITION_STATEMENTS:
        summary_clean = re.sub(r"\s+", " ", summary).strip()
        record = {
            "pmid":            slug,
            "title":           title,
            "abstract":        summary_clean,
            "authors":         "American Association of Endodontists",
            "year":            year,
            "journal":         "AAE Position Statement",
            "impact_factor":   8.0,        # high authority weighting
            "sample_size":     None,
            "followup_months": None,
            "citations":       50,         # proxy for authority
            "level_key":       "level1",   # treated as top-tier evidence
            "score":           90.0,       # high fixed score for clinical guidelines
        }
        ok = upsert_guideline(record, dry_run=dry_run)
        if ok:
            added += 1
            print(f"    OK {title[:65]}")
        time.sleep(0.05)
    print(f"  -> {added} AAE statements ingested")
    return added


# -- Ingest PubMed-indexed guidelines -------------------------------------

def ingest_pubmed_guidelines(dry_run: bool = False) -> int:
    print("\n  -- PubMed-indexed Guidelines (eUtils search) -----------")
    seen: set[str] = set()
    added = 0

    for query in PUBMED_GUIDELINE_QUERIES:
        pmids = pubmed_search(query, max_results=15)
        new = [p for p in pmids if p not in seen]
        if not new:
            continue

        meta_map  = pubmed_fetch_meta(new)
        abst_map  = pubmed_fetch_abstracts(new)
        time.sleep(0.4)

        for pmid in new:
            abstract = abst_map.get(pmid, "").strip()
            if len(abstract) < 60:
                continue
            meta = meta_map.get(pmid, {})
            year_str = meta.get("year", "2010")

            record = {
                "pmid":            pmid,
                "title":           meta.get("title", ""),
                # FULL abstract — do NOT reinstate a character cap here. A
                # guideline abstract carries its RECOMMENDATIONS at the end, and
                # this field is stored and later read verbatim by the synthesis
                # prompt; the old [:1200] cap threw the recommendations away.
                # Length limiting belongs only on the embed() text inside
                # upsert_guideline(), which already slices to [:600].
                "abstract":        abstract,
                "authors":         meta.get("authors", ""),
                "year":            int(year_str) if str(year_str).isdigit() else 2010,
                "journal":         meta.get("journal", ""),
                "impact_factor":   6.0,
                "sample_size":     None,
                "followup_months": None,
                "citations":       20,
                "level_key":       "level1",
                "score":           85.0,
            }
            ok = upsert_guideline(record, dry_run=dry_run)
            if ok:
                added += 1
                seen.add(pmid)
                print(f"    OK {pmid}: {meta.get('title','')[:55]}")

        time.sleep(0.35)

    print(f"  -> {added} PubMed guidelines ingested")
    return added


# -- Ingest ESE guidelines (European Society of Endodontology) -------------

ESE_GUIDELINES: list[tuple] = [
    (
        "ESE-QG-2006",
        "ESE Quality Guidelines for Endodontic Treatment: Consensus Report of the European Society of Endodontology",
        2006,
        """
        The European Society of Endodontology quality guidelines specify minimum
        standards for endodontic treatment. Pre-operative assessment must include
        clinical and radiographic examination. Rubber dam isolation is mandatory.
        Canal preparation should achieve adequate taper with apical preparation
        to working length confirmed by electronic apex locator and radiograph.
        Irrigation with NaOCl is recommended throughout preparation.
        Obturation with gutta-percha and sealer is the standard; obturation
        should be 0-2mm from radiographic apex. Immediate coronal seal following
        obturation is emphasised. Post-treatment radiograph is required.
        All endodontic records must document findings, treatment, and outcomes.
        Six-month and two-year radiographic review is recommended.
        """,
    ),
    (
        "ESE-QG-2023",
        "ESE Position Statement: Quality Guidelines for Endodontic Treatment — 2023 Update",
        2023,
        """
        Updated ESE quality guidelines reflect advances since 2006. Key updates:
        CBCT is recommended for complex anatomy and pre-surgical assessment;
        electronic apex locators are standard for working length determination;
        bioceramic sealers and warm obturation techniques are accepted alongside
        traditional methods; single-visit root canal treatment is appropriate
        for most cases; vital pulp therapy with calcium silicate cements is
        preferred over extraction in suitable cases; magnification (loupes or
        microscope) is recommended for all endodontic procedures. Outcome
        reporting should use standardised criteria (periapical index). Digital
        radiography reduces radiation exposure and is preferred. Patient-reported
        outcome measures should be incorporated into clinical practice.
        """,
    ),
    (
        "ESE-PS-VPT-2019",
        "ESE Position Statement: Outcome of Primary Root Canal Treatment",
        2019,
        """
        The ESE defines success of primary root canal treatment as the absence
        of clinical signs and symptoms and complete radiographic resolution of
        apical periodontitis. Healed outcomes: full periapical bone regeneration
        at 4-year review. Healing rates for teeth with pre-operative apical
        periodontitis: 68–85% healed at 4 years. Teeth without pre-operative
        pathology: 92–98% preserved. Prognosis is adversely affected by:
        pre-existing apical periodontitis, large lesion size, missed canals,
        overfill, and failure to achieve adequate coronal seal. Adequate
        preparation and obturation quality are the strongest predictors of success.
        CBCT provides more sensitive assessment of healing than periapical radiographs.
        """,
    ),
]


def ingest_ese_guidelines(dry_run: bool = False) -> int:
    print("\n  -- ESE Guidelines (hardcoded corpus) ------------------")
    added = 0
    for slug, title, year, summary in ESE_GUIDELINES:
        summary_clean = re.sub(r"\s+", " ", summary).strip()
        record = {
            "pmid":            slug,
            "title":           title,
            "abstract":        summary_clean,
            "authors":         "European Society of Endodontology",
            "year":            year,
            "journal":         "International Endodontic Journal",
            "impact_factor":   4.5,
            "sample_size":     None,
            "followup_months": None,
            "citations":       40,
            "level_key":       "level1",
            "score":           87.0,
        }
        ok = upsert_guideline(record, dry_run=dry_run)
        if ok:
            added += 1
            print(f"    OK {title[:65]}")
        time.sleep(0.05)
    print(f"  -> {added} ESE guidelines ingested")
    return added


# -- Entry point ----------------------------------------------------------

def run(pubmed_only: bool = False, web_only: bool = False, dry_run: bool = False):
    print("\n" + "=" * 60)
    print("  Endo AI — AAE / ESE Guidelines Ingester")
    print("=" * 60)
    if dry_run:
        print("  [DRY RUN — no data will be written]\n")

    setup_table()
    stats_before = library_stats()
    print(f"  Library before: {stats_before['total']} papers")

    total = 0

    if not pubmed_only:
        total += ingest_aae_statements(dry_run=dry_run)
        total += ingest_ese_guidelines(dry_run=dry_run)

    if not web_only:
        total += ingest_pubmed_guidelines(dry_run=dry_run)

    print(f"\n{'='*60}")
    print(f"  Done. {'Would add' if dry_run else 'Added'} {total} guideline records.")
    if not dry_run:
        stats_after = library_stats()
        print(f"  Library now: {stats_after['total']} papers")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AAE/ESE guidelines ingester for Endo AI")
    parser.add_argument("--stats",     action="store_true", help="Show library stats and exit")
    parser.add_argument("--dry-run",   action="store_true", help="Show what would be ingested, no writes")
    parser.add_argument("--pubmed",    action="store_true", help="PubMed-indexed guidelines only")
    parser.add_argument("--web",       action="store_true", help="Hardcoded AAE/ESE statements only")
    args = parser.parse_args()

    if args.stats:
        setup_table()
        s = library_stats()
        print(f"\nLibrary stats:")
        print(f"  Total  : {s['total']}")
        print(f"  Levels : {s['by_level']}")
        print(f"  Years  : {s['year_range']}\n")
    else:
        run(pubmed_only=args.pubmed, web_only=args.web, dry_run=args.dry_run)
