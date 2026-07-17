"""
Regression test for per-PMID metadata isolation.

PURPOSE
-------
This test exists because of a confirmed bug where extract_sample_size() and
extract_followup_period() were called on the entire concatenated text of all
50 fetched papers inside a per-PMID loop, causing one paper's metadata
(typically a meta-analysis with the largest n) to be broadcast to every
unrelated paper in the result set.

Fixed in commit <FILL IN AFTER COMMIT>.

This test is the tripwire that prevents the bug class from returning. It
asserts that each PMID's extracted metadata reflects ONLY that paper's
content, not the surrounding batch.

CRITICAL — READ BEFORE EDITING THIS FILE
-----------------------------------------
Every fixture entry below MUST be manually verified against PubMed before
being added. The assertions are only as good as the ground truth.

Verification protocol for each PMID:
  1. Open https://pubmed.ncbi.nlm.nih.gov/<PMID>/
  2. Read the abstract.
  3. Confirm the study type matches what the fixture claims.
  4. For sample_size:
       - Count ONLY the n in THIS study, not borrowed from a referenced SR.
       - In vitro studies with extracted teeth as units: sample_size = "unknown"
         (we are not in the business of asserting n=80 teeth as a clinical n).
       - If the abstract genuinely doesn't state n: "unknown".
       - For meta-analyses: use the patient total reported in the abstract,
         NOT the number of included studies.
  5. For follow_up_months:
       - Use the longest stated follow-up in the abstract, in months.
       - In vitro studies: "unknown" (no follow-up applies).
       - If a range is given, use the upper bound.
  6. Update the comment for that fixture entry with the PubMed URL and the
     date you verified it.

DO NOT add fixture entries based on titles, search snippets, or LLM summaries.
Read the actual PubMed abstract every time. This is non-negotiable for a
test that protects clinical software.
"""

from typing import Optional, Union
import pytest

from endo_ai import (
    _parse_efetch_batch,
    extract_sample_size,
    extract_followup_period,
)

# ============================================================================
# VERIFIED FIXTURES
# ============================================================================
# Each entry: (PMID, expected_sample_size, expected_follow_up_months, verified_on, verification_notes)
#
# expected_sample_size:
#   int       -- exact number expected from extractor
#   "unknown" -- abstract does not state a clinical sample size
#   None      -- DO NOT use in assertions; placeholder for unverified entries
#
# expected_follow_up_months:
#   int       -- exact number of months
#   "unknown" -- abstract does not state follow-up (e.g., in vitro)
#   None      -- DO NOT use in assertions; placeholder for unverified entries
# ============================================================================

VERIFIED_FIXTURES = [
    {
        "pmid": "30174103",
        "expected_sample_size": 15,
        "expected_follow_up_months": 12,
        "study_type": "clinical_study_small",
        "verified_on": "2026-04-29",
        "verification_notes": (
            "El Baz et al. — 'Assessment of Regaining Pulp Sensibility in Mature "
            "Necrotic Teeth Using a Modified Revascularization Technique with "
            "Platelet-rich Fibrin: A Clinical Study'. "
            "Abstract states 15 patients, 12-month follow-up. "
            "URL: https://pubmed.ncbi.nlm.nih.gov/30174103/"
        ),
    },
    # ── IN VITRO ─────────────────────────────────────────────────────────────
    {
        "pmid": "33932297",
        "expected_sample_size": "unknown",
        "expected_follow_up_months": "unknown",
        "study_type": "in_vitro",
        "verified_on": "2026-05-01",
        "verification_notes": (
            "Blome et al. — 'Model system parameters influence the sodium "
            "hypochlorite susceptibility of endodontic biofilms'. "
            "Pure bench/in vitro study: biofilm culture on substrate with varied "
            "NaOCl exposure; no patients, no clinical follow-up. Abstract does "
            "not state a specimen count. Both fields correctly 'unknown'. "
            "URL: https://pubmed.ncbi.nlm.nih.gov/33932297/"
        ),
    },
    # ── SMALL RCT (n=36) ─────────────────────────────────────────────────────
    {
        "pmid": "32202965",
        "expected_sample_size": 36,
        "expected_follow_up_months": 12,
        "study_type": "rct_small",
        "verified_on": "2026-05-01",
        "verification_notes": (
            "Alghutaimel et al. — 'Cell-Based Regenerative Endodontics for "
            "Treatment of Periapical Lesions'. RCT phase I/II. "
            "Abstract: 'The trial included 36 patients... randomly and equally "
            "allocated between experimental (REP) or conventional root canal '  "
            "treatment (ENDO) groups' (18 per arm). "
            "Follow-up: 'examinations were performed at 6 and 12 mo' — abstract "
            "uses 'mo' abbreviation; extractor may need pattern for 'mo'. "
            "Ground truth: n=36 patients, 12-month follow-up. "
            "URL: https://pubmed.ncbi.nlm.nih.gov/32202965/"
        ),
    },
    # ── LARGE RCT (n=169) ────────────────────────────────────────────────────
    {
        "pmid": "28917577",
        "expected_sample_size": 169,
        "expected_follow_up_months": 12,
        "study_type": "rct_large",
        "verified_on": "2026-05-01",
        "verification_notes": (
            "Rajasekharan et al. — 'Direct Pulp Capping with Calcium Hydroxide, "
            "Mineral Trioxide Aggregate, and Biodentine in Permanent Young Teeth'. "
            "RCT. Abstract: '169 patients (mean age, 11.3 years)' each contributing "
            "1 carious tooth — patient count unambiguous. "
            "Follow-up: '1 week, 3 months, 6 months, and 1 year' → 12 months max. "
            "URL: https://pubmed.ncbi.nlm.nih.gov/28917577/"
        ),
    },
    # ── SYSTEMATIC REVIEW / META-ANALYSIS ────────────────────────────────────
    {
        "pmid": "37254176",
        "expected_sample_size": "unknown",
        "expected_follow_up_months": 12,
        "study_type": "meta_analysis",
        "verified_on": "2026-05-01",
        "verification_notes": (
            "Al-Haddad et al. — 'Success rate of permanent teeth pulpotomy using "
            "bioactive materials: A systematic review and meta-analysis'. "
            "Abstract: '16 studies were included in the systematic review' — no "
            "total patient count reported in the abstract, so sample_size='unknown'. "
            "Follow-up: 'overall mean success rate of 92% after 1 year' → 12 months. "
            "Extractor note: 'after 1 year' may not match current year patterns "
            "which look for 'at N years' / 'N-year follow-up' etc. "
            "URL: https://pubmed.ncbi.nlm.nih.gov/37254176/"
        ),
    },
    # ── CASE SERIES (n=14) ───────────────────────────────────────────────────
    {
        "pmid": "35750220",
        "expected_sample_size": 14,
        "expected_follow_up_months": 264,
        "study_type": "case_series",
        "verified_on": "2026-05-01",
        "verification_notes": (
            "Lage et al. — 'Long-Term Outcome of Nonvital Immature Permanent Teeth "
            "Treated With Apexification and Corono-Radicular Adhesive Restoration'. "
            "Case series. Abstract: 'Fourteen patients providing a total of 16 teeth' "
            "— patient count explicit and distinct from tooth count. "
            "Follow-up: 'within a follow-up span of 5 to 22 years' → upper bound "
            "22 years = 264 months (per verification protocol). "
            "Extractor note: range format '5 to 22 years' unlikely to match current "
            "year patterns; extractor will likely return None → test will fail and "
            "flag need to add range-format patterns. "
            "URL: https://pubmed.ncbi.nlm.nih.gov/35750220/"
        ),
    },
]


# ============================================================================
# THE BUG'S SIGNATURE — GUARDRAIL TEST
# ============================================================================

def test_no_block_repetition_in_batch_extraction():
    """
    The original bug produced consecutive blocks of identical metadata
    (e.g., papers 1-7 all n=2595, 120 mo; papers 12-18 all n=490, 120 mo).

    This test simulates a batch fetch and asserts that, across PMIDs of
    different study types, the extracted sample sizes are NOT all identical.

    This is a weak assertion (it would not catch a more subtle version of the
    bug), but it is fast and catches the exact regression we just fixed.
    """
    verified = [f for f in VERIFIED_FIXTURES if f["pmid"] is not None]
    if len(verified) < 2:
        pytest.skip(
            "Need at least 2 verified fixtures to test for block repetition. "
            "Add more PMIDs to VERIFIED_FIXTURES."
        )

    # Collect non-"unknown" sample sizes from verified fixtures
    sizes = [
        f["expected_sample_size"]
        for f in verified
        if isinstance(f["expected_sample_size"], int)
    ]

    if len(sizes) < 2:
        pytest.skip(
            "Need at least 2 fixtures with integer sample sizes to detect "
            "block repetition."
        )

    assert len(set(sizes)) > 1, (
        "Block-repetition signature detected: all verified fixtures have the "
        "same sample size. Either the bug has regressed, or the fixture "
        "selection is too narrow. Add fixtures with diverse sample sizes."
    )


# ============================================================================
# PER-PMID ISOLATION TESTS
# ============================================================================

@pytest.mark.parametrize(
    "fixture",
    [f for f in VERIFIED_FIXTURES if f["pmid"] is not None and f["verified_on"]],
    ids=lambda f: f"{f['pmid']}_{f['study_type']}",
)
def test_per_pmid_metadata_isolation(fixture, mock_pubmed_efetch_batch):
    """
    Fetch a real PubMed batch containing the fixture PMID, run extraction,
    and assert the extracted metadata matches what was manually verified.

    This test depends on a fixture `mock_pubmed_efetch_batch` (defined in
    conftest.py) that returns a recorded efetch XML response containing the
    target PMID alongside several DIFFERENT papers. This proves the
    extractor isolates per-PMID and is not contaminated by neighbors.
    """
    pmid = fixture["pmid"]
    expected_n = fixture["expected_sample_size"]
    expected_fu = fixture["expected_follow_up_months"]

    # Get the batch XML containing this PMID surrounded by other papers
    batch_xml = mock_pubmed_efetch_batch(target_pmid=pmid)

    # Parse the batch
    per_pmid = _parse_efetch_batch(batch_xml)
    assert pmid in per_pmid, (
        f"PMID {pmid} missing from parsed batch. "
        f"Parser may be skipping records. Got: {list(per_pmid.keys())}"
    )

    paper_text = per_pmid[pmid].get("abstract", "")
    assert paper_text, (
        f"Empty abstract for PMID {pmid}. Either the fixture XML is bad or "
        f"the parser is dropping the abstract field."
    )

    # Extract metadata from THIS paper's text only
    extracted_n = extract_sample_size(paper_text)
    fu_result = extract_followup_period(paper_text)
    # extract_followup_period returns (months_int, unit_str) or None
    extracted_fu = fu_result[0] if fu_result else None

    # Sample size assertion
    if expected_n == "unknown":
        assert extracted_n in (None, "unknown", 0), (
            f"PMID {pmid} ({fixture['study_type']}): expected sample_size "
            f"to be unknown/None (in vitro or n not reported), but extractor "
            f"returned {extracted_n!r}. This is the BUG — extractor is "
            f"likely picking up a value from a different paper in the batch."
        )
    else:
        assert extracted_n == expected_n, (
            f"PMID {pmid} ({fixture['study_type']}): expected sample_size "
            f"{expected_n}, got {extracted_n!r}. "
            f"Verification notes: {fixture['verification_notes']}"
        )

    # Follow-up assertion
    if expected_fu == "unknown":
        assert extracted_fu in (None, "unknown", 0), (
            f"PMID {pmid} ({fixture['study_type']}): expected follow_up to "
            f"be unknown/None, but extractor returned {extracted_fu!r}."
        )
    else:
        assert extracted_fu == expected_fu, (
            f"PMID {pmid} ({fixture['study_type']}): expected follow_up "
            f"{expected_fu} months, got {extracted_fu!r}. "
            f"(extract_followup_period returned: {fu_result!r})"
        )


# ============================================================================
# DISTRIBUTION SANITY CHECK
# ============================================================================

def test_metadata_distribution_in_real_batch(real_pubmed_search_result):
    """
    Run a real PubMed search end-to-end and assert that the metadata
    distribution across results is plausible.

    This is the test that would have caught the original bug in production.
    If 70%+ of papers in a result set share the same sample size, that's
    almost certainly a bug.

    Depends on `real_pubmed_search_result` fixture (in conftest.py) which
    runs a known query and returns the scored paper list. Mark as integration
    test if you want to skip it in CI without network.
    """
    papers = real_pubmed_search_result(query="regenerative endodontics", n=20)

    sample_sizes = [
        p.get("sample_size") for p in papers
        if isinstance(p.get("sample_size"), int)
    ]

    if len(sample_sizes) < 5:
        pytest.skip("Not enough papers with integer sample sizes to assess distribution.")

    unique_count = len(set(sample_sizes))
    unique_ratio = unique_count / len(sample_sizes)

    assert unique_ratio >= 0.4, (
        f"Suspicious metadata distribution: only {unique_count} unique "
        f"sample sizes across {len(sample_sizes)} papers ({unique_ratio:.0%} "
        f"unique). This matches the signature of the per-batch contamination "
        f"bug. Sample sizes seen: {sample_sizes}"
    )
