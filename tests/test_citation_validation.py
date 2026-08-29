"""
Citation-validation test suite — the product's core safety thesis.

Endo AI's entire value proposition is: *every clinical claim is anchored to a
real paper in the retrieved evidence base, and the model cannot invent PMIDs.*
`validate_evidence_mapping()` is the gate that enforces this before an answer is
ever shown to a clinician, so it is the single most important function to lock
down with tests.

These tests assert the CONTRACT of the validator and its helpers, grouped by the
three failure modes it exists to catch:

  1. FABRICATION      — a [[PMID:N]] the evidence base never contained
  2. UNATTRIBUTED     — a clinical/numeric claim with no [[PMID:N]] at all
  3. GAP SECTIONS     — a substantive section with zero attribution

Plus the supporting machinery: PMID extraction, section splitting, exempt-section
handling, failure precedence, scoring, and the corrective re-prompt.

Run:  pytest tests/test_citation_validation.py -v
"""

import pytest

from endo_ai import (
    validate_evidence_mapping,
    _extract_evidence_pmids,
    _extract_cited_pmids,
    _detect_unattributed_claims,
    _detect_gap_sections,
    _split_sections,
    _is_exempt_section,
    _build_corrective_message,
    _extract_claim_citation_pairs,
    _append_support_warnings,
    _EVMAP_MAX_UNATTRIBUTED,
    _EVMAP_MAX_GAP_RATIO,
)


# ─────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────

def make_evidence(*tier_ids, scored=None, summary=None):
    """Build a minimal evidence dict shaped like build_evidence_base() output.

    tier_ids  -> PMIDs exposed via a tier block's `ids` list
    scored    -> PMIDs exposed via a tier block's `scored` [{pmid}] list
    summary   -> PMIDs exposed only via _summary.all_scored
    """
    ev = {"cochrane": {"ids": [str(p) for p in tier_ids]}}
    if scored:
        ev["level1"] = {"scored": [{"pmid": str(p)} for p in scored]}
    if summary:
        ev["_summary"] = {"all_scored": [{"pmid": str(p)} for p in summary]}
    return ev


# ═════════════════════════════════════════════════════════════
# 1. FABRICATION — the thesis. A cited PMID not in the evidence
#    base must ALWAYS fail, and must dominate every other signal.
# ═════════════════════════════════════════════════════════════

class TestFabrication:

    def test_clean_answer_passes(self):
        ev = make_evidence(111, 222)
        answer = (
            "## Findings\n"
            "Biodentine outperformed calcium hydroxide for direct pulp capping "
            "in pooled analysis [[PMID:111]]. Reported success reached 92% at "
            "24 months of follow-up [[PMID:222]].\n"
        )
        r = validate_evidence_mapping(answer, ev)
        assert r["passed"] is True
        assert r["fabricated_pmids"] == []
        assert r["score"] == 100
        assert r["failure_reason"] is None

    def test_single_fabricated_pmid_fails(self):
        ev = make_evidence(111, 222)
        answer = (
            "## Findings\n"
            "MTA showed superior sealing ability in laboratory testing "
            "[[PMID:999]].\n"
        )
        r = validate_evidence_mapping(answer, ev)
        assert r["passed"] is False
        assert r["fabricated_pmids"] == ["999"]
        assert r["failure_reason"].startswith("FABRICATED_PMIDS")

    def test_fabrication_dominates_an_otherwise_perfect_answer(self):
        """Even one invented PMID sinks an answer that is otherwise flawless."""
        ev = make_evidence(111, 222, 333)
        answer = (
            "## Findings\n"
            "Calcium silicate cements improve pulp-capping outcomes [[PMID:111]]. "
            "Success was durable at five years [[PMID:222]]. A newer cohort "
            "agreed [[PMID:333]]. One extra reference was invented [[PMID:404]].\n"
        )
        r = validate_evidence_mapping(answer, ev)
        assert r["passed"] is False
        assert r["failure_reason"].startswith("FABRICATED_PMIDS")
        assert r["score"] <= 70          # 100 - 30 for one fabrication

    def test_multiple_fabricated_pmids_all_reported(self):
        ev = make_evidence(111)
        answer = "## Findings\nClaims here [[PMID:777]] and here [[PMID:888]].\n"
        r = validate_evidence_mapping(answer, ev)
        assert set(r["fabricated_pmids"]) == {"777", "888"}
        assert r["valid_pmids"] == []

    def test_pmid_only_in_summary_is_valid_evidence(self):
        """A PMID present solely in _summary.all_scored is NOT fabrication."""
        ev = make_evidence(111, summary=[555])
        answer = "## Findings\nA summary-tier paper supports this [[PMID:555]].\n"
        r = validate_evidence_mapping(answer, ev)
        assert r["fabricated_pmids"] == []
        assert "555" in r["valid_pmids"]

    def test_pmid_only_in_scored_block_is_valid_evidence(self):
        ev = make_evidence(111, scored=[444])
        answer = "## Findings\nA scored-tier paper supports this [[PMID:444]].\n"
        r = validate_evidence_mapping(answer, ev)
        assert r["fabricated_pmids"] == []
        assert "444" in r["valid_pmids"]

    def test_whitespace_inside_marker_still_matches_evidence(self):
        ev = make_evidence(111)
        answer = "## Findings\nSpacing should not matter [[PMID: 111 ]].\n"
        r = validate_evidence_mapping(answer, ev)
        assert r["cited_pmids"] == {"111"}
        assert r["fabricated_pmids"] == []

    def test_empty_evidence_makes_every_citation_fabricated(self):
        r = validate_evidence_mapping(
            "## Findings\nUnsupported by any base [[PMID:111]].\n", {}
        )
        assert r["fabricated_pmids"] == ["111"]
        assert r["passed"] is False

    def test_invented_non_numeric_marker_is_fabrication(self):
        """A non-numeric identifier NOT in the evidence base is a fabrication —
        the numeric regex can't see it, so it must be caught explicitly."""
        ev = make_evidence(111)
        answer = (
            "## Findings\n"
            "Consult current guidelines for shaping recommendations "
            "[[PMID:AAE-PS-obturation]] alongside the trial data [[PMID:111]].\n"
        )
        r = validate_evidence_mapping(answer, ev)
        assert r["passed"] is False
        assert "AAE-PS-obturation" in r["fabricated_pmids"]
        assert "111" in r["valid_pmids"]

    def test_synthetic_id_present_in_evidence_base_is_valid(self):
        """Hand-ingested authority documents (AAE position statements) carry
        synthetic PMIDs like 'AAE-PS-obturation'. Citing one is legitimate and
        must NOT be reported as fabrication."""
        ev = make_evidence(111, "AAE-PS-obturation")
        answer = (
            "## Findings\n"
            "Obturation technique follows the position statement "
            "[[PMID:AAE-PS-obturation]] and is supported by trial data "
            "[[PMID:111]].\n"
        )
        r = validate_evidence_mapping(answer, ev)
        assert r["fabricated_pmids"] == []
        assert "AAE-PS-obturation" in r["valid_pmids"]
        assert r["passed"] is True


# ═════════════════════════════════════════════════════════════
# 2. UNATTRIBUTED CLAIMS — numeric / comparative / recommendation
#    language with no [[PMID:N]] anywhere in the sentence.
# ═════════════════════════════════════════════════════════════

class TestUnattributedClaims:

    @pytest.mark.parametrize("sentence", [
        "Reported success reached 92% at final review across the cohort.",
        "The difference was significant at p<0.05 in the primary analysis.",
        "Irrigation used 5.25% NaOCl throughout the disinfection phase here.",
        "The recommended working length was set at 19 mm for this molar.",
        "Biodentine was superior to calcium hydroxide in the pooled result.",
        "A single-visit approach is recommended for these mature cases.",
        "The overall failure rate was notably higher in the control arm.",
    ])
    def test_claim_shapes_are_flagged_without_a_marker(self, sentence):
        answer = f"## Findings\n{sentence}\n"
        flagged = _detect_unattributed_claims(answer)
        assert len(flagged) == 1, f"expected a flag for: {sentence!r}"

    def test_same_claim_with_marker_is_not_flagged(self):
        answer = (
            "## Findings\n"
            "Reported success reached 92% at final review [[PMID:111]].\n"
        )
        assert _detect_unattributed_claims(answer) == []

    def test_plain_background_prose_is_not_flagged(self):
        answer = (
            "## Background\n"
            "The dental pulp is a richly innervated connective tissue that "
            "responds to injury through inflammation and repair.\n"
        )
        assert _detect_unattributed_claims(answer) == []

    def test_under_the_limit_still_passes(self):
        """Up to the limit of unattributed claims is tolerated (not a hard fail)."""
        ev = make_evidence(111)
        answer = (
            "## Findings\n"
            "Context anchoring the section [[PMID:111]]. "
            "Success reached 92% at review. "
            "Biodentine was superior to calcium hydroxide.\n"
        )
        r = validate_evidence_mapping(answer, ev)
        assert len(r["unattributed_claims"]) <= _EVMAP_MAX_UNATTRIBUTED
        assert r["passed"] is True

    def test_over_the_limit_fails(self):
        ev = make_evidence(111)
        answer = (
            "## Findings\n"
            "Context anchoring the section [[PMID:111]]. "
            "Success reached 92% at 24 months. "
            "Biodentine was superior to calcium hydroxide. "
            "The odds ratio clearly favoured the treatment group. "
            "The failure rate was 8% over the study period.\n"
        )
        r = validate_evidence_mapping(answer, ev)
        assert len(r["unattributed_claims"]) > _EVMAP_MAX_UNATTRIBUTED
        assert r["passed"] is False
        assert r["failure_reason"].startswith("UNATTRIBUTED_CLAIMS")

    def test_claims_inside_exempt_section_are_ignored(self):
        """Exempt sections (Key Takeaways, References, ...) are closing prose and
        are skipped by the unattributed-claim detector.

        NOTE: Clinical Recommendation used to be on that list and no longer is —
        it is the text a clinician acts on, so it is now the most-checked
        section rather than the least. See
        test_review_scoring_and_recommendation.py.
        """
        ev = make_evidence(111)
        answer = (
            "## Findings\nA supported point [[PMID:111]] anchors this section.\n\n"
            "## Key Takeaways\n"
            "Success reached 92% at 24 months. "
            "Biodentine was superior to calcium hydroxide. "
            "The material set within 12 minutes. "
            "The failure rate was 8% over the study period.\n"
        )
        r = validate_evidence_mapping(answer, ev)
        assert r["unattributed_claims"] == []
        assert r["passed"] is True


# ═════════════════════════════════════════════════════════════
# 3. GAP SECTIONS — a substantive section with zero attribution.
# ═════════════════════════════════════════════════════════════

class TestGapSections:

    def test_substantive_section_without_pmids_is_a_gap(self):
        answer = (
            "## Obturation\n"
            "Warm vertical compaction adapts gutta-percha to canal irregularities "
            "and is widely taught as a core technique in graduate programs today.\n"
        )
        assert _detect_gap_sections(answer) == ["Obturation"]

    def test_short_section_is_not_a_gap(self):
        answer = "## Note\nBrief aside.\n"
        assert _detect_gap_sections(answer) == []

    def test_exempt_section_without_pmids_is_not_a_gap(self):
        answer = (
            "## Key Takeaways\n"
            "Calcium silicate cements are now the default for vital pulp therapy, "
            "and coronal seal quality drives long-term success in daily practice.\n"
        )
        assert _detect_gap_sections(answer) == []

    def test_gap_ratio_over_threshold_fails(self):
        ev = make_evidence(111)
        answer = (
            "## Section One\n"
            "A substantial paragraph on irrigation dynamics and disinfection that "
            "runs well beyond eighty characters yet cites nothing at all here.\n\n"
            "## Section Two\n"
            "Another substantial paragraph discussing obturation and coronal seal "
            "that also runs well past eighty characters with no citation present.\n\n"
            "## Section Three\n"
            "Calcium silicate materials improve outcomes [[PMID:111]] across "
            "several controlled studies of pulp capping and pulpotomy reported.\n"
        )
        r = validate_evidence_mapping(answer, ev)
        assert len(r["gap_sections"]) == 2
        assert r["total_cite_required"] == 3
        assert (len(r["gap_sections"]) / r["total_cite_required"]) > _EVMAP_MAX_GAP_RATIO
        assert r["passed"] is False
        assert r["failure_reason"].startswith("GAP_SECTIONS")

    def test_single_gap_section_does_not_trip_the_ratio_rule(self):
        """The gap rule needs >=2 cite-required sections; a lone section can't."""
        ev = make_evidence(111)
        answer = (
            "## Only Section\n"
            "A lone substantial paragraph on canal disinfection that comfortably "
            "exceeds eighty characters but happens to carry no citation marker.\n"
        )
        r = validate_evidence_mapping(answer, ev)
        assert r["gap_sections"] == ["Only Section"]
        assert r["total_cite_required"] == 1
        assert r["failure_reason"] != "GAP_SECTIONS" or r["passed"] is True
        # With a single section the gap rule cannot fire:
        assert not (r["failure_reason"] or "").startswith("GAP_SECTIONS")


# ═════════════════════════════════════════════════════════════
# 4. FAILURE PRECEDENCE & SCORING
# ═════════════════════════════════════════════════════════════

class TestPrecedenceAndScoring:

    def test_fabrication_precedence_over_unattributed_and_gaps(self):
        ev = make_evidence(111)
        answer = (
            "## Section One\n"
            "A long uncited paragraph about disinfection that easily clears the "
            "eighty-character bar while making no reference to any source here.\n\n"
            "## Section Two\n"
            "Success reached 92% at 24 months. Biodentine was superior to calcium "
            "hydroxide. The set time was 12 minutes. Failure was 8% overall. "
            "An invented citation appears here [[PMID:999]].\n"
        )
        r = validate_evidence_mapping(answer, ev)
        assert r["fabricated_pmids"] == ["999"]
        assert r["failure_reason"].startswith("FABRICATED_PMIDS")

    def test_score_is_monotonic_in_fabrication_count(self):
        ev = make_evidence(111)
        one = validate_evidence_mapping(
            "## F\nClaim [[PMID:900]] here to anchor a real sentence body.\n", ev)
        two = validate_evidence_mapping(
            "## F\nClaims [[PMID:900]] and [[PMID:901]] in one sentence body.\n", ev)
        assert two["score"] < one["score"]

    def test_score_clamped_to_zero_floor(self):
        ev = make_evidence(111)
        fabs = " ".join(f"[[PMID:{9000+i}]]" for i in range(10))
        r = validate_evidence_mapping(f"## F\nMany invented refs {fabs} appear.\n", ev)
        assert r["score"] == 0
        assert r["passed"] is False


# ═════════════════════════════════════════════════════════════
# 5. PMID EXTRACTION HELPERS
# ═════════════════════════════════════════════════════════════

class TestExtractionHelpers:

    def test_extract_evidence_pmids_unions_all_sources(self):
        ev = {
            "cochrane": {"ids": ["111", "222"]},
            "level1":   {"scored": [{"pmid": "333"}, {"pmid": 444}]},  # int coerced
            "_summary": {"all_scored": [{"pmid": "555"}]},
            "_meta":    {"ignored": True},
        }
        assert _extract_evidence_pmids(ev) == {"111", "222", "333", "444", "555"}

    def test_extract_evidence_pmids_handles_non_dict(self):
        assert _extract_evidence_pmids(None) == set()
        assert _extract_evidence_pmids("nonsense") == set()

    def test_extract_cited_pmids_preserves_order_and_duplicates(self):
        text = "a [[PMID:111]] b [[PMID:222]] c [[PMID:111]]"
        assert _extract_cited_pmids(text) == ["111", "222", "111"]

    def test_extract_cited_pmids_empty(self):
        assert _extract_cited_pmids("") == []
        assert _extract_cited_pmids("no markers here") == []


# ═════════════════════════════════════════════════════════════
# 6. SECTION SPLITTING & EXEMPTION
# ═════════════════════════════════════════════════════════════

class TestSectionsAndExemption:

    def test_split_captures_intro_before_first_heading(self):
        answer = "Some preamble text.\n\n## First\nBody text here.\n"
        sections = dict(_split_sections(answer))
        assert "(intro)" in sections
        assert "First" in sections

    def test_split_no_headings_returns_single_intro(self):
        secs = _split_sections("Just a blob of text with no markdown headings.")
        assert secs == [("(intro)", "Just a blob of text with no markdown headings.")]

    @pytest.mark.parametrize("title", [
        "**References**",
        "Key Takeaways",
        "Assessment",
        "Summary of Evidence",   # prefix match on "summary"
        "Table of Contents",
    ])
    def test_exempt_titles(self, title):
        assert _is_exempt_section(title) is True

    @pytest.mark.parametrize("title", [
        "Findings", "Background", "Obturation", "Materials & Instrumentation",
        # No longer exempt — it is the text acted on, so it is now validated
        # for an evidence tier and at least one citation.
        "Clinical Recommendation", "clinical recommendation",
    ])
    def test_non_exempt_titles(self, title):
        assert _is_exempt_section(title) is False


# ═════════════════════════════════════════════════════════════
# 7. CORRECTIVE RE-PROMPT
# ═════════════════════════════════════════════════════════════

class TestCorrectiveMessage:

    def test_names_fabricated_pmids(self):
        msg = _build_corrective_message({"fabricated_pmids": ["999", "888"]})
        assert "FABRICATED" in msg.upper()
        assert "999" in msg and "888" in msg

    def test_includes_unattributed_samples(self):
        msg = _build_corrective_message({
            "unattributed_claims": [
                {"sentence": "Success reached 92% at 24 months.", "section": "Findings"},
            ]
        })
        assert "UNATTRIBUTED" in msg.upper()
        assert "92%" in msg

    def test_handles_empty_result(self):
        msg = _build_corrective_message({})
        assert isinstance(msg, str) and len(msg) > 0


# ═════════════════════════════════════════════════════════════
# 8. EDGE CASES
# ═════════════════════════════════════════════════════════════

class TestClaimCitationPairs:
    """The v2 citation-support verifier's claim extractor."""

    def test_single_claim_single_citation(self):
        answer = "## Findings\nMTA outperformed CaOH in pooled analysis [[PMID:111]].\n"
        pairs = _extract_claim_citation_pairs(answer)
        assert len(pairs) == 1
        claim, pmid = pairs[0]
        assert pmid == "111"
        assert "MTA outperformed CaOH" in claim
        assert "PMID" not in claim          # markers stripped from the claim text

    def test_one_claim_two_citations_yields_two_pairs(self):
        answer = "## Findings\nSuccess was durable at five years [[PMID:111]] [[PMID:222]].\n"
        pairs = _extract_claim_citation_pairs(answer)
        assert [p for _, p in pairs] == ["111", "222"]
        assert pairs[0][0] == pairs[1][0]   # same claim text for both

    def test_exempt_sections_skipped(self):
        answer = (
            "## References\n1. Something citable here [[PMID:333]] with enough length.\n\n"
            "## Findings\nA real claim in a checked section [[PMID:444]].\n"
        )
        pairs = _extract_claim_citation_pairs(answer)
        assert [p for _, p in pairs] == ["444"]

    def test_uncited_sentences_ignored(self):
        answer = "## Findings\nThis is plain background prose with no marker at all.\n"
        assert _extract_claim_citation_pairs(answer) == []


class TestSupportWarnings:

    def test_clean_check_reports_verified_rather_than_staying_silent(self):
        """Silence from a fail-open check reads as a pass, so every outcome is
        stated explicitly — including 'this did not run'."""
        out = _append_support_warnings("answer", {"status": "verified", "checked": 4, "flags": []})
        assert out.startswith("answer")
        assert "Citation support: verified" in out

    def test_skipped_check_says_so(self):
        out = _append_support_warnings("answer", {"flags": []})
        assert "not available" in out
        assert "was not verified" in out

    def test_flags_append_visible_block_with_pmids(self):
        out = _append_support_warnings("answer", {"status": "verified", "checked": 3, "flags": [
            {"pmid": "999", "claim": "Success was 92% at 24 months.", "verdict": "not_supported"},
        ]})
        assert "Citation support" in out
        assert "[[PMID:999]]" in out
        assert "92%" in out


class TestEdgeCases:

    def test_empty_answer_passes_trivially(self):
        r = validate_evidence_mapping("", make_evidence(111))
        assert r["passed"] is True
        assert r["cited_pmids"] == set()
        assert r["gap_sections"] == []

    def test_none_answer_does_not_crash(self):
        # _extract_cited_pmids tolerates None; validator should not raise.
        assert _extract_cited_pmids(None) == []

    def test_result_shape_is_stable(self):
        r = validate_evidence_mapping("## F\nText [[PMID:111]] body.\n",
                                      make_evidence(111))
        for key in ("passed", "score", "evidence_pmids", "cited_pmids",
                    "fabricated_pmids", "valid_pmids", "unattributed_claims",
                    "gap_sections", "total_cite_required", "failure_reason"):
            assert key in r
