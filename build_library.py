"""
Endo AI -- RAG Library Builder
Run once to pre-populate the Neon vector database with endodontic papers.
After that, Endo AI searches locally and only hits PubMed for gaps.

Usage:
    py build_library.py           -- full build (~500 papers, 20-30 min)
    py build_library.py --stats   -- show library stats
    py build_library.py --update  -- add new papers for existing topics
"""

import sys
import time
import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.abspath('.'), '.env'))
from rag import setup_table, upsert_paper, embed, library_stats
from endo_ai import (
    fetch_papers, fetch_cochrane, generate_search_terms,
    fetch_metadata, extract_sample_size, extract_followup_period,
    get_impact_factor, score_paper,
    COCHRANE_TERM, LEVEL_1_TERMS, LEVEL_2_TERMS,
    LEVEL_3_TERMS, LEVEL_4_TERMS, LEVEL_5_TERMS,
)

# -- Core endodontic topics to pre-load --
CORE_TOPICS = [
    # Vital pulp therapy
    "vital pulp therapy MTA mature teeth",
    "pulp capping success rate",
    "calcium hydroxide vs MTA pulpotomy",
    "biodentine vital pulp therapy",
    "partial pulpotomy permanent teeth",

    # Root canal treatment outcomes
    "root canal treatment success rate",
    "endodontic treatment long term prognosis",
    "single visit vs multiple visit root canal",
    "root canal retreatment outcomes",
    "periapical healing after root canal",

    # Instrumentation
    "nickel titanium rotary instrumentation",
    "reciprocating instrumentation WaveOne",
    "rotary vs reciprocating curved canals",
    "glide path endodontics",
    "instrument fracture root canal",

    # Irrigation
    "sodium hypochlorite irrigation concentration",
    "EDTA smear layer removal",
    "ultrasonic irrigation endodontics",
    "chlorhexidine root canal irrigation",
    "apical patency root canal",

    # Sealers and obturation
    "bioceramic sealer root canal",
    "AH Plus epoxy resin sealer",
    "warm vertical compaction obturation",
    "single cone obturation technique",
    "cold lateral condensation gutta percha",

    # Diagnosis and pain
    "irreversible pulpitis diagnosis",
    "apical periodontitis pain management",
    "CBCT endodontic diagnosis",
    "cracked tooth syndrome diagnosis",
    "endodontic flare up prevention",

    # Periapical surgery
    "endodontic microsurgery apicoectomy",
    "retrograde filling MTA surgery",
    "endodontic surgery success rate",

    # Resorption
    "external root resorption treatment",
    "internal root resorption management",
    "invasive cervical resorption",

    # Regeneration
    "regenerative endodontics immature teeth",
    "revascularization necrotic immature",
    "apexification MTA apical barrier",

    # Trauma
    "dental trauma pulp necrosis",
    "replantation avulsion prognosis",
    "luxation injury pulp survival",

    # Implant vs endodontics
    "implant vs endodontic treatment comparison",
    "tooth retention root canal vs extraction",

    # Special topics
    "endodontic retreatment vs surgery",
    "post space preparation risk",
    "rubber dam endodontics outcomes",
    "working length determination apex locator",
    "cone beam CT vs periapical radiograph endodontics",

    # Advanced irrigation and disinfection
    "GentleWave multisonic irrigation endodontics",
    "PIPS photon-initiated photoacoustic streaming laser irrigation",
    "ozone therapy root canal disinfection",

    # Canal anatomy and missed canals
    "maxillary molar MB2 canal prevalence treatment",
    "mandibular molar middle mesial canal anatomy",
    "missed canals retreatment detection CBCT",

    # Complications and management
    "root perforation MTA repair prognosis",
    "ledge formation bypass management root canal",
    "sodium hypochlorite accident extrusion management",
    "separated instrument bypass retrieval outcomes",

    # Anesthesia and pain
    "inferior alveolar nerve block failure supplemental anesthesia",
    "preoperative NSAID ibuprofen endodontic pain reduction",

    # Restoration and tooth survival
    "coronal restoration quality endodontic outcome",
    "fiber post composite core endodontically treated teeth",
    "endodontically treated molar cusp coverage crown survival",

    # Endo-perio and systemic
    "endo-perio lesion classification treatment prognosis",
    "diabetes mellitus periapical healing endodontic outcome",
    "cardiovascular disease endodontic focal infection",

    # Newer technologies
    "guided endodontics navigation system calcified canals",
    "cone beam CT preoperative planning endodontic outcome",
]

LEVELS = [
    ("cochrane", None,          "Cochrane",       3),
    ("level1",   LEVEL_1_TERMS, "Level 1",        8),
    ("level2",   LEVEL_2_TERMS, "Level 2",        6),
    ("level3",   LEVEL_3_TERMS, "Level 3",        5),
    ("level4",   LEVEL_4_TERMS, "Level 4",        3),
    ("level5",   LEVEL_5_TERMS, "Level 5",        2),
]


def build_paper_record(pmid, abstract_text, meta, level_key):
    """Build a full paper dict ready for RAG storage."""
    sample_size     = extract_sample_size(abstract_text)
    followup        = extract_followup_period(abstract_text)
    followup_months = followup[0] if followup else None
    journal_name    = meta.get("journal", "")
    if_val, if_pts  = get_impact_factor(journal_name)

    score, _ = score_paper(
        level_key,
        meta.get("year", "2000"),
        meta.get("citations", 0),
        sample_size,
        followup_months,
        if_pts,
    )

    return {
        "pmid":            pmid,
        "title":           "",   # not easily available from efetch text mode
        "abstract":        abstract_text[:1000],
        "authors":         meta.get("authors", ""),
        "year":            int(meta.get("year", 2000)) if str(meta.get("year", "2000")).isdigit() else 2000,
        "journal":         journal_name,
        "impact_factor":   if_val,
        "sample_size":     sample_size,
        "followup_months": followup_months,
        "citations":       meta.get("citations", 0),
        "level_key":       level_key,
        "score":           score,
    }


def process_topic(topic: str, seen_pmids: set) -> int:
    """Fetch, score, embed, and store papers for one topic. Returns count added."""
    added = 0

    for level_key, terms, label, max_n in LEVELS:
        try:
            if level_key == "cochrane":
                cochrane_text = fetch_cochrane(topic)
                if cochrane_text:
                    # Cochrane direct -- embed the text block as one entry
                    fake_pmid = "COCHRANE_" + topic[:30].replace(" ", "_")
                    if fake_pmid not in seen_pmids:
                        vec = embed(topic + " " + cochrane_text[:400])
                        upsert_paper({
                            "pmid":      fake_pmid,
                            "abstract":  cochrane_text[:800],
                            "authors":   "Cochrane Collaboration",
                            "year":      2024,
                            "journal":   "Cochrane Database Syst Rev",
                            "level_key": "cochrane",
                            "score":     95.0,
                        }, vec)
                        seen_pmids.add(fake_pmid)
                        added += 1
                    continue

                filter_term = COCHRANE_TERM
            else:
                filter_term = " OR ".join(terms)

            _, ids, scored = fetch_papers(topic, filter_term, label, level_key, max_results=max_n)

            if not ids:
                continue

            # Fetch full metadata for authors
            metadata = fetch_metadata(ids)

            for p in scored:
                pmid = p["pmid"]
                if pmid in seen_pmids:
                    continue

                meta = metadata.get(pmid, {})
                p["authors"] = meta.get("authors", "")

                # Embed using title-like search string + abstract snippet
                embed_text = f"{topic} {p.get('abstract', '')[:300]}"
                try:
                    vec = embed(embed_text)
                except Exception:
                    continue

                upsert_paper(p, vec)
                seen_pmids.add(pmid)
                added += 1

            time.sleep(0.3)  # PubMed rate limit

        except Exception as e:
            print(f"    Error on {label}: {e}")
            continue

    return added


def run_build(update_mode: bool = False):
    print("\n" + "=" * 55)
    print("  Endo AI -- RAG Library Builder")
    print("=" * 55)

    setup_table()

    if not update_mode:
        stats = library_stats()
        if stats["total"] > 0:
            print(f"\n  Library already has {stats['total']} papers.")
            ans = input("  Rebuild from scratch? (y/n): ").strip().lower()
            if ans != "y":
                print("  Skipping -- use --update to add new papers.")
                return

    seen_pmids: set = set()
    total_added = 0

    for i, topic in enumerate(CORE_TOPICS):
        print(f"\n[{i+1}/{len(CORE_TOPICS)}] {topic}")
        n = process_topic(topic, seen_pmids)
        total_added += n
        print(f"  -> {n} papers added (total so far: {total_added})")
        time.sleep(0.5)

    print(f"\n{'='*55}")
    print(f"  Build complete. {total_added} papers added to library.")
    stats = library_stats()
    print(f"  Total in library: {stats['total']}")
    print(f"  By level: {stats['by_level']}")
    print(f"  Year range: {stats['year_range']}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    if "--stats" in sys.argv:
        setup_table()
        s = library_stats()
        print(f"\nLibrary stats:")
        print(f"  Total papers: {s['total']}")
        print(f"  By level:     {s['by_level']}")
        print(f"  Year range:   {s['year_range']}\n")
    elif "--update" in sys.argv:
        run_build(update_mode=True)
    else:
        run_build(update_mode=False)
