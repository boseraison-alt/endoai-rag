"""
Save real PubMed efetch responses to disk so tests can run offline.

This script does TWO things:

1. For each PMID in your VERIFIED_FIXTURES list, fetches a batch XML response
   that contains that PMID alongside 4 other UNRELATED PMIDs (a meta-analysis,
   an in vitro study, an RCT, etc.). This batch is what gets fed to the
   extractor in tests, so the test proves per-PMID isolation.

2. Prints the abstract for each fetched paper, so you can manually verify
   the metadata claims in your fixture file.

Usage:
    python scripts/fetch_and_save_fixtures.py
    python scripts/fetch_and_save_fixtures.py --verify-only 30174103

Prerequisites:
    pip install requests
    Set NCBI_API_KEY in env (optional, raises rate limit from 3/sec to 10/sec)
"""

import argparse
import os
import sys
import time
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

# Force UTF-8 output on Windows so abstracts containing Unicode (thin spaces,
# en dashes, etc.) never crash the verification printout on a cp1252 console.
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "pubmed_xml"

# A diverse "filler" set that surrounds each target PMID in the saved batch.
# These are the "noise" papers — chosen to span study types and n magnitudes
# so a per-batch extraction bug (values bleeding across PMIDs) would be visible.
# All verified against PubMed abstracts 2026-05-01.
FILLER_PMIDS = [
    "40886932",  # Gomez-Sosa 2025 — NMR of 21 RCTs on VPT, large SR (n=1733 across trials)
    "34854987",  # Asgary 2022 — full pulpotomy vs RCT, n=157 teeth, 2-year FU
    "36414881",  # Chalcone irrigant vs E.faecalis/C.albicans — in vitro, no patients
    "39119855",  # NaOCl vs saline for VPT — RCT, n=125 teeth, 12-month FU
]

# PMIDs that are TARGETS of the test (i.e., we make per-PMID assertions on them).
# Must match VERIFIED_FIXTURES in tests/test_metadata_extraction.py exactly.
TARGET_PMIDS = [
    "30174103",  # El Baz PRF revascularisation — n=15 patients, 12mo FU
    "33932297",  # Blome NaOCl biofilm — in vitro, n=unknown, FU=unknown
    "32202965",  # Alghutaimel cell-based REP RCT — n=36 patients, 12mo FU
    "28917577",  # Rajasekharan DPC RCT — n=169 patients, 12mo FU
    "37254176",  # Al-Haddad pulpotomy SR/MA — n=unknown (16 studies), FU=12mo
    "35750220",  # Lage apexification case series — n=14 patients, FU=264mo (22yr)
]


def fetch_efetch_text_batch(pmids: list[str]) -> str:
    """Fetch the efetch abstract *text* dump for a list of PMIDs, comma-joined.

    This MUST use rettype=abstract, retmode=text to match production exactly
    (endo_ai.py fetches this format and feeds it to _parse_efetch_batch). The
    saved fixture is what the tests run through the same text parser, so the
    fixture format has to be identical to what production sees at runtime.
    """
    api_key = os.environ.get("NCBI_API_KEY", "")
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "rettype": "abstract",
        "retmode": "text",
    }
    if api_key:
        params["api_key"] = api_key

    resp = requests.get(f"{EUTILS_BASE}/efetch.fcgi", params=params, timeout=30)
    resp.raise_for_status()
    return resp.text


def fetch_efetch_xml(pmids: list[str]) -> str:
    """Fetch the efetch XML for a list of PMIDs — used ONLY for the structured
    human-verification printout, never for the saved test fixture."""
    api_key = os.environ.get("NCBI_API_KEY", "")
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
    }
    if api_key:
        params["api_key"] = api_key

    resp = requests.get(f"{EUTILS_BASE}/efetch.fcgi", params=params, timeout=30)
    resp.raise_for_status()
    return resp.text


def print_abstract_for_verification(xml_text: str, target_pmid: str) -> None:
    """Print the title and abstract for a target PMID so the user can verify."""
    root = ET.fromstring(xml_text)
    for article in root.findall(".//PubmedArticle"):
        pmid_node = article.find(".//PMID")
        if pmid_node is None or pmid_node.text != target_pmid:
            continue

        title_node = article.find(".//ArticleTitle")
        title = title_node.text if title_node is not None else "(no title)"

        abstract_parts = []
        for abst in article.findall(".//AbstractText"):
            label = abst.attrib.get("Label", "")
            text = "".join(abst.itertext()).strip()
            if label:
                abstract_parts.append(f"[{label}] {text}")
            else:
                abstract_parts.append(text)
        abstract = "\n\n".join(abstract_parts) if abstract_parts else "(no abstract)"

        print("=" * 78)
        print(f"PMID: {target_pmid}")
        print(f"URL:  https://pubmed.ncbi.nlm.nih.gov/{target_pmid}/")
        print(f"TITLE: {title}")
        print("-" * 78)
        print(abstract)
        print("=" * 78)
        print()
        print("VERIFICATION CHECKLIST:")
        print("  [ ] Sample size — what is the actual n in THIS study?")
        print("  [ ] Follow-up — what is the longest stated follow-up in months?")
        print("  [ ] Study type — RCT? in vitro? meta-analysis? case series?")
        print("  [ ] If meta-analysis: is the n the patient total or study count?")
        print()
        return

    print(f"PMID {target_pmid} not found in returned XML.")


def save_batch_for_target(target_pmid: str) -> Path:
    """
    Build a batch containing the target PMID surrounded by FILLER_PMIDS,
    fetch it, save to disk, and return the path.
    """
    if not FILLER_PMIDS:
        print(
            "ERROR: FILLER_PMIDS is empty. Edit this script and add 4-5 verified "
            "filler PMIDs spanning study types before running."
        )
        sys.exit(1)

    batch_pmids = FILLER_PMIDS + [target_pmid]
    print(f"Fetching batch of {len(batch_pmids)} PMIDs for target {target_pmid}...")
    batch_text = fetch_efetch_text_batch(batch_pmids)

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = FIXTURE_DIR / f"batch_{target_pmid}.txt"
    out_path.write_text(batch_text, encoding="utf-8")
    print(f"Saved {out_path} ({len(batch_text)} bytes)")
    return out_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify-only",
        metavar="PMID",
        help="Just print the abstract for one PMID (don't save anything)",
    )
    args = parser.parse_args()

    if args.verify_only:
        xml_text = fetch_efetch_xml([args.verify_only])
        print_abstract_for_verification(xml_text, args.verify_only)
        return

    if not TARGET_PMIDS:
        print("ERROR: TARGET_PMIDS is empty. Add at least one verified PMID.")
        sys.exit(1)

    for pmid in TARGET_PMIDS:
        save_batch_for_target(pmid)

        # Fetch a structured XML copy of just this PMID for the human-readable
        # verification printout. The saved fixture stays in production text
        # format; this XML is only for eyeballing the abstract.
        xml_text = fetch_efetch_xml([pmid])
        print_abstract_for_verification(xml_text, pmid)

        # NCBI rate limit: 3/sec without key, 10/sec with key
        time.sleep(0.4)


if __name__ == "__main__":
    main()
