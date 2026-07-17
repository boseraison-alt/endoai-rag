"""
Endo AI — PubMed Live-Fetch Verification
=========================================
Proof-of-fetch audit. Calls fetch_papers() against the live NCBI eutils API
for a known endodontic query, then independently verifies that every PMID
returned is a real, indexed PubMed record by re-querying esummary for each.

If fetch_papers were ever fabricating PMIDs, this script would catch them —
because the independent esummary verification would return empty metadata
for any synthesized ID. A real PMID always returns a title, year, journal.

Outputs:
  - Per-PMID line: "PMID 12345678 → 'Title' (Journal Year)" or "PMID xxx → NOT FOUND"
  - Summary: real / not-found counts
  - Sample of pubmed_audit.jsonl tail showing the audit trail entry written
    by the actual fetch_papers call

Usage:
    python verify_pubmed_live.py
    python verify_pubmed_live.py --query "vital pulp therapy MTA"
    python verify_pubmed_live.py --tier level1
"""

import sys, os, json, time, argparse, requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.abspath("."), ".env"))
sys.path.insert(0, os.path.abspath("."))

from endo_ai import (
    fetch_papers, _ncbi_params, NCBI_EUTILS_BASE,
    LEVEL_1_TERMS, LEVEL_2_TERMS, LEVEL_4_TERMS,
)

TIER_TERMS = {
    "level1": LEVEL_1_TERMS,
    "level2": LEVEL_2_TERMS,
    "level4": LEVEL_4_TERMS,
}


def independent_pmid_check(pmid: str) -> dict | None:
    """Independently verify a PMID is real. Tries esummary up to 3 times
    (NCBI occasionally returns an empty result block transiently), then falls
    back to efetch as a cross-check (efetch hits a different backend so a
    transient esummary glitch won't false-flag a real paper).

    Returns metadata dict if PMID is confirmed real, None only if BOTH
    services report no record across multiple attempts.
    """
    # Try esummary 3x with backoff
    for attempt in range(3):
        try:
            r = requests.get(
                f"{NCBI_EUTILS_BASE}/esummary.fcgi",
                params=_ncbi_params({"db": "pubmed", "id": pmid, "retmode": "json"}),
                timeout=15,
            )
            if r.status_code == 200:
                result = (r.json().get("result", {}) or {}).get(pmid, {}) or {}
                if result.get("title"):
                    return {
                        "title":   result.get("title", ""),
                        "journal": result.get("source", "") or result.get("fulljournalname", ""),
                        "year":    (result.get("pubdate", "") or "")[:4],
                        "via":     "esummary",
                    }
        except Exception:
            pass
        time.sleep(0.5 * (attempt + 1))

    # esummary kept coming up empty — cross-check with efetch (different backend)
    try:
        r = requests.get(
            f"{NCBI_EUTILS_BASE}/efetch.fcgi",
            params=_ncbi_params({"db": "pubmed", "id": pmid, "rettype": "abstract", "retmode": "text"}),
            timeout=15,
        )
        if r.status_code == 200 and len(r.text) > 100 and f"PMID: {pmid}" in r.text:
            # First non-citation paragraph after the journal line is the title
            lines = [ln.strip() for ln in r.text.split("\n") if ln.strip()]
            title = lines[1] if len(lines) > 1 else "(title in efetch text)"
            journal = lines[0].split(".")[0] if lines else ""
            return {"title": title, "journal": journal, "year": "", "via": "efetch"}
    except Exception:
        pass

    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--query", default="vital pulp therapy MTA mineral trioxide aggregate",
                    help="Topic to query PubMed for")
    ap.add_argument("--tier",  default="level1",
                    choices=sorted(TIER_TERMS.keys()),
                    help="Which evidence tier to query (controls the design filter)")
    ap.add_argument("--max",   type=int, default=10,
                    help="How many PMIDs fetch_papers should request")
    args = ap.parse_args()

    print("=" * 70)
    print(f"PubMed live-fetch verification")
    print(f"  query : {args.query}")
    print(f"  tier  : {args.tier}")
    print(f"  max   : {args.max}")
    print(f"  ts    : {datetime.now().isoformat()}")
    print("=" * 70)

    # 1. Call the production fetch_papers — same code path used by every
    #    Literature Review and Deep Learning request.
    filter_term = " OR ".join(TIER_TERMS[args.tier])
    label = f"VERIFY-{args.tier.upper()}"
    t0 = time.perf_counter()
    annotated_text, pmids, scored = fetch_papers(
        topic        = args.query,
        filter_term  = filter_term,
        label        = label,
        level_key    = args.tier,
        max_results  = args.max,
        mode         = "review",
    )
    fetch_ms = int((time.perf_counter() - t0) * 1000)
    print()
    print(f"fetch_papers returned {len(pmids)} PMIDs in {fetch_ms}ms")
    print()

    # 2. Independently verify EACH returned PMID against esummary.
    print("Independent esummary verification (each PMID re-queried fresh):")
    print("-" * 70)
    n_real = 0
    n_fake = 0
    for pmid in pmids:
        meta = independent_pmid_check(pmid)
        if meta:
            n_real += 1
            title = (meta["title"] or "")[:70]
            print(f"  OK    PMID {pmid:<10}  '{title}' ({meta['journal']} {meta['year']})")
        else:
            n_fake += 1
            print(f"  FAKE  PMID {pmid:<10}  NOT FOUND in PubMed independent check")
        # Be polite to NCBI
        time.sleep(0.1 if os.getenv("NCBI_API_KEY") else 0.35)

    print()
    print("=" * 70)
    print("VERIFICATION REPORT")
    print("=" * 70)
    print(f"  PMIDs returned by fetch_papers : {len(pmids)}")
    print(f"  Independently confirmed real    : {n_real}")
    print(f"  NOT found in PubMed (suspect)   : {n_fake}")
    if n_fake == 0 and n_real > 0:
        print()
        print("  >>> PASS: every PMID came from a real NCBI response <<<")
    elif n_fake > 0:
        print()
        print("  >>> FAIL: some PMIDs could not be verified — investigate immediately <<<")
    else:
        print()
        print("  (no PMIDs returned — query may be too narrow; try a broader --query)")

    # 3. Show the audit trail entry written by fetch_papers itself
    print()
    print("Audit trail entry (last line of pubmed_audit.jsonl):")
    print("-" * 70)
    audit_path = os.path.join(os.path.dirname(os.path.abspath("endo_ai.py")), "pubmed_audit.jsonl")
    if os.path.exists(audit_path):
        with open(audit_path, encoding="utf-8") as fh:
            tail = fh.readlines()
        if tail:
            try:
                rec = json.loads(tail[-1])
                print(json.dumps(rec, indent=2))
            except Exception:
                print(tail[-1].strip())
    else:
        print("  (pubmed_audit.jsonl not found — no fetch_papers calls have been audited yet)")


if __name__ == "__main__":
    main()
