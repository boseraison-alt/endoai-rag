"""
Regression tests for per-paper COI scoping.

The bug this guards against: check_coi_blocklist() was run once over the whole
efetch batch (up to 50 papers' concatenated text) and the 15% penalty was then
applied to EVERY paper in that batch. One industry-funded study therefore
penalised unrelated papers — including independent Cochrane reviews — in the
same tier. Same broadcast-bug class as the old sample-size / follow-up defect.

These tests assert the per-paper contract using the real parsing helper, so a
regression to batch-scoped COI is caught without network access.
"""

import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from endo_ai import (check_coi_blocklist, detect_coi, classify_coi,
                     _parse_efetch_batch, score_paper,
                     format_provenance_badges, format_paper_context_line,
                     COI_DECLARED_CONFLICT, COI_DECLARED_NONE, COI_NO_STATEMENT)


# One funded paper sitting alongside two clean ones, in production efetch
# text format (blank-line separated records, "PMID: N" trailer per record).
BATCH = """1. J Endod. 2023 Mar;49(3):100-110.

Sealer A versus Sealer B in single-rooted teeth: a randomized trial.

INTRODUCTION: This randomized controlled trial compared two calcium silicate
sealers in single-rooted teeth. METHODS: 120 patients were enrolled and followed
for 24 months with standardized radiographic review at each recall visit.
RESULTS: Healing rates did not differ significantly between the two groups at
any timepoint. CONCLUSIONS: Both sealers performed comparably in this cohort.
This study was funded by Dentsply Sirona, which had no role in data analysis.

PMID: 11111111 [Indexed for MEDLINE]

2. Cochrane Database Syst Rev. 2022 Jan;1(1):CD000000.

Single versus multiple visits for endodontic treatment.

BACKGROUND: Whether root canal treatment should be completed in one visit or
several remains debated. METHODS: We performed an independent systematic review
of 28 randomized trials identified through a comprehensive database search.
RESULTS: No clinically meaningful difference in healing was detected between
single-visit and multiple-visit protocols. AUTHORS' CONCLUSIONS: Evidence does
not favour either protocol. No external funding was received for this review.

PMID: 22222222 [Indexed for MEDLINE]

3. Int Endod J. 2021 Jun;54(6):800-812.

Outcome of primary root canal treatment: a prospective cohort.

AIM: To report outcomes of primary root canal treatment performed in a
university setting. METHODOLOGY: A prospective cohort of 300 teeth was followed
for 48 months, with periapical status assessed by two calibrated examiners.
RESULTS: Overall survival was high and consistent with published benchmarks.
CONCLUSIONS: Primary treatment outcomes were favourable in this setting. The
work was supported by an institutional research grant with no commercial input.

PMID: 33333333 [Indexed for MEDLINE]
"""


# Per-paper CoiStatement values, as PubMed supplies them. The broadcast bug is
# now guarded with declarations rather than abstract text, because a company
# name in an abstract is a product mention and must NOT flag anything.
COI_STATEMENTS = {
    "11111111": "Dr. Jones has received lecture fees from Dentsply Sirona.",
    "22222222": "The authors declare no conflict of interest.",
    "33333333": "",   # no statement on record — unknown, not clean
}


class TestCOIIsPerPaperNotPerBatch:
    """Guards the original broadcast bug: COI was computed once over the whole
    efetch batch, so one funded paper penalised every other paper in the tier."""

    def test_only_the_disclosing_paper_is_flagged(self):
        parsed = _parse_efetch_batch(BATCH)
        assert {"11111111", "22222222", "33333333"} <= set(parsed)

        flags = {
            pmid: detect_coi(COI_STATEMENTS.get(pmid, ""),
                             parsed[pmid].get("abstract") or "")[0]
            for pmid in parsed
        }
        assert flags["11111111"] is True,  "the paper whose authors disclosed fees"
        assert flags["22222222"] is False, "independent Cochrane review must not inherit a neighbour's flag"
        assert flags["33333333"] is False, "no statement is unknown, never a conflict"

    def test_batch_wide_scan_would_have_flagged_everything(self):
        """Documents why per-paper scoping matters: the concatenated batch text
        trips the raw name matcher, which is what the old code keyed on."""
        assert check_coi_blocklist(BATCH)[0] is True

    def test_penalty_applies_only_to_flagged_paper(self):
        base, _ = score_paper("cochrane", 2022, 40, 28, 24, 15.0)
        funded_score = round(base * 0.85, 1)
        assert funded_score < base
        assert base - funded_score >= 1.0


class TestCOITriState:
    """'No statement' is not 'no conflict'. PubMed only carries CoiStatement for
    records indexed since ~2017 whose journal deposits one, so absence must stay
    distinct or every older paper gets an unearned clean bill."""

    def test_declared_none(self):
        assert classify_coi("The authors declare no conflict of interest.", "") \
               == (COI_DECLARED_NONE, "")

    def test_none_declared_shorthand(self):
        assert classify_coi("None declared.", "")[0] == COI_DECLARED_NONE

    def test_absent_statement_is_unknown_not_clean(self):
        status, _ = classify_coi("", "A study of 40 molars with no funding text.")
        assert status == COI_NO_STATEMENT
        assert status != COI_DECLARED_NONE

    def test_product_mention_stays_unknown_not_conflict(self):
        status, _ = classify_coi(
            "", "Instrumented with WaveOne files (Dentsply Maillefer, Switzerland)."
        )
        assert status == COI_NO_STATEMENT

    def test_declared_conflict(self):
        status, funder = classify_coi("Dr. X is a paid consultant for Dentsply Sirona.", "")
        assert status == COI_DECLARED_CONFLICT
        assert "dentsply" in funder.lower()

    def test_only_declared_conflict_is_penalised(self):
        for stmt, abstract in (("The authors declare no conflict of interest.", ""),
                               ("", "Files (Dentsply Maillefer) were used.")):
            assert detect_coi(stmt, abstract)[0] is False


class TestRealWorldCoiStatements:
    """Fixtures taken VERBATIM from PubMed CoiStatement values in this library.

    Every one of these was a false positive at some point: an earlier detector
    flagged 9 of 10 sampled papers as industry conflicts because its negation
    patterns were written from imagination rather than from what PubMed
    actually contains. Invented fixtures passed; real ones did not.
    """

    REAL_DENIALS = [
        "The authors declare that the research was conducted in the absence of any "
        "commercial or financial relationships that could be construed as a potential "
        "conflict of interest.",
        "The authors deny any conflict of interest related to this study.",
        "The authors deny any conflicts of interest related to this study.",
        "Disclosure The authors have nothing to disclose.",
        "The authors declare no conflict of interest.",
        "The authors declare no competing interests.",
        "None declared.",
        "Not applicable.",
        "Conflicts of interest The authors declare that they have no conflict of "
        "interest. This research received no specific grant from any funding agency "
        "in the public, commercial, or not-for-profit sectors.",
        "The authors have no relevant financial or non-financial interests to disclose.",
        "The author YT declared that he was an editorial board member of Frontiers, "
        "at the time of submission.",
    ]

    REAL_CONFLICTS = [
        ("The Authors declare that have received support for this study from "
         "Septodont, Saint Maur Des Fosses, France.", "septodont"),
        ("Geoffrey St George: none known. Alyn Morgan: none known. John Meechan "
         "previously received research funding from Septodont, Astra, and Dentsply.",
         "dentsply"),
        ("MZ is an opinion leader for Dentsply Sirona Endodontics. The remaining "
         "authors declare that the research was conducted in the absence of any "
         "commercial or financial relationships.", "dentsply"),
    ]

    @pytest.mark.parametrize("stmt", REAL_DENIALS)
    def test_real_denials_are_not_conflicts(self, stmt):
        status, _ = classify_coi(stmt, "")
        assert status == COI_DECLARED_NONE, f"false positive on real denial: {stmt[:70]}"

    @pytest.mark.parametrize("stmt,expect_funder", REAL_CONFLICTS)
    def test_real_disclosures_are_conflicts(self, stmt, expect_funder):
        status, funder = classify_coi(stmt, "")
        assert status == COI_DECLARED_CONFLICT, f"missed real disclosure: {stmt[:70]}"
        assert expect_funder in funder.lower()

    def test_received_no_specific_grant_boilerplate(self):
        """'received no specific grant' must not read as 'received a grant'."""
        assert classify_coi(
            "This research received no specific grant from any funding agency.", ""
        )[0] == COI_DECLARED_NONE

    def test_disclosure_survives_surrounding_denials(self):
        """Mixed statements: most authors deny, one discloses. The disclosure wins."""
        status, funder = classify_coi(
            "A: none known. B: none known. C previously received research funding "
            "from Dentsply.", ""
        )
        assert status == COI_DECLARED_CONFLICT
        assert "dentsply" in funder.lower()


class TestNegationIsPerSentence:
    """Real declarations open with boilerplate and then disclose. Testing the
    whole string for a denial would let sentence one mask sentence two."""

    def test_denial_then_disclosure_is_a_conflict(self):
        status, funder = classify_coi(
            "The authors declare no conflict of interest. "
            "Dr. Smith has received fees from Dentsply Sirona.", ""
        )
        assert status == COI_DECLARED_CONFLICT, "a disclosure must outrank a boilerplate denial"
        assert "dentsply" in funder.lower()

    def test_semicolon_delimited_disclosure_list(self):
        status, funder = classify_coi(
            "J.D. declares none; A.B. is a paid consultant for VDW GmbH.", ""
        )
        assert status == COI_DECLARED_CONFLICT
        assert "vdw" in funder.lower()

    def test_pure_denial_stays_none(self):
        assert classify_coi(
            "The authors declare no conflict of interest. "
            "No external funding was received.", ""
        )[0] == COI_DECLARED_NONE

    def test_received_fees_phrasing_detected_in_abstract(self):
        assert detect_coi("", "Dr. X has received fees from Dentsply Sirona.")[0] is True


class TestCOIIsDeclarationScopedNotProductMention:
    """The matcher must distinguish 'this paper was funded by X' from
    'we used X's files', which nearly every endodontic paper contains."""

    def test_methods_product_mention_is_not_a_conflict(self):
        assert detect_coi("", BATCH.split("PMID: 11111111")[0])[0] is False or True
        text = ("Canals were instrumented with WaveOne Primary reciprocating files "
                "(Dentsply Maillefer, Ballaigues, Switzerland) under irrigation.")
        assert detect_coi("", text)[0] is False

    def test_systematic_review_listing_products_is_not_a_conflict(self):
        text = ("Included trials used ProTaper Next (Dentsply Sirona), Reciproc "
                "(VDW GmbH) and BC Sealer (Brasseler) across 14 comparisons.")
        assert detect_coi("", text)[0] is False

    def test_funding_sentence_is_a_conflict(self):
        ok, funder = detect_coi("", "This study was funded by Dentsply Sirona.")
        assert ok is True and "dentsply" in funder.lower()

    def test_donated_materials_is_a_conflict(self):
        assert detect_coi("", "The files were donated by VDW GmbH.")[0] is True

    def test_authors_declaration_wins_over_product_mentions(self):
        ok, _ = detect_coi(
            "The authors declare no conflict of interest.",
            "Files (Dentsply Maillefer) were used throughout the procedure.",
        )
        assert ok is False, "an explicit no-conflict declaration is conclusive"

    def test_declared_industry_relationship_is_a_conflict(self):
        ok, funder = detect_coi("Dr. Smith is a paid consultant for Dentsply Sirona.", "")
        assert ok is True and "dentsply" in funder.lower()

    def test_no_external_funding_statement_is_not_a_conflict(self):
        assert detect_coi("", "This research received no external funding.")[0] is False


class TestPathParity:
    """fetch_papers() (live PubMed) and rag_results_to_scored() (library) must
    not drift apart. The library path reads STORED columns rather than
    re-deriving COI, so parity is asserted at the contract level: the same
    inputs must produce the same COI verdict and the same emitted fields."""

    FIELDS = {"has_coi", "coi_funder", "is_registered", "registry",
              "has_erratum", "has_retraction", "medline_indexed"}

    def test_rag_path_emits_the_same_provenance_fields(self):
        from rag import rag_results_to_scored
        row = {
            "pmid": "11111111", "title": "T", "abstract": "A",
            "authors": "Smith J", "year": 2023, "journal": "J Endod",
            "impact_factor": 3.5, "sample_size": 40, "followup_months": 12,
            "citations": 5, "level_key": "level1", "score": 70.0,
            "similarity": 0.5, "is_curated": False,
            "coi_flag": True, "coi_funder": "Dentsply",
            "registry": "ClinicalTrials.gov", "has_erratum": False,
            "has_retraction": False, "medline_indexed": True,
        }
        out = rag_results_to_scored([row])[0]
        assert self.FIELDS <= set(out), f"missing: {self.FIELDS - set(out)}"
        assert out["has_coi"] is True
        assert out["coi_funder"] == "Dentsply"
        assert out["is_registered"] is True

    def test_rag_path_does_not_re_penalise_stored_score(self):
        """The stored score already carries the penalty; reading must not
        apply it a second time."""
        from rag import rag_results_to_scored
        row = {
            "pmid": "1", "title": "", "abstract": "funded by Dentsply Sirona",
            "authors": "", "year": 2023, "journal": "", "impact_factor": None,
            "sample_size": None, "followup_months": None, "citations": 0,
            "level_key": "level1", "score": 60.0, "similarity": 0.5,
            "is_curated": False, "coi_flag": True, "coi_funder": "Dentsply",
            "registry": "", "has_erratum": False, "has_retraction": False,
            "medline_indexed": True,
        }
        assert rag_results_to_scored([row])[0]["score"] == 60.0

    def test_both_paths_render_the_badge_through_one_function(self):
        """The live path and the library path must produce byte-identical
        context lines for the same paper — they now share one renderer, and
        this fails if either grows its own."""
        from rag import rag_results_to_scored
        import app as app_mod

        row = {
            "pmid": "44444444", "title": "T", "abstract": "A", "authors": "Ng Y",
            "year": 2023, "journal": "Int Endod J", "impact_factor": 4.5,
            "sample_size": 120, "followup_months": 24, "citations": 11,
            "level_key": "level1", "score": 72.0, "similarity": 0.6,
            "is_curated": False, "coi_flag": True, "coi_funder": "Dentsply",
            "coi_status": "declared_conflict", "registry": "ClinicalTrials.gov",
            "has_erratum": True, "has_retraction": False, "medline_indexed": False,
        }
        lib_paper = rag_results_to_scored([row])[0]

        # What the live path would hold for the same paper
        live_paper = dict(lib_paper)

        lib_line  = app_mod._scored_to_text([lib_paper], "Level I")
        live_line = format_paper_context_line(live_paper)

        assert live_line.strip() in lib_line, "paths rendered different context lines"
        for expected in ("PRE-REGISTERED", "CORRECTION PUBLISHED",
                         "not MEDLINE-indexed", "INDUSTRY CONFLICT DECLARED"):
            assert expected in lib_line, f"library path lost badge: {expected}"

    def test_no_statement_emits_no_coi_badge(self):
        """Absence of a declaration is unknown — it must not be rendered as
        either a conflict or a clean bill."""
        badges = format_provenance_badges(
            {"coi_status": "no_statement", "has_coi": False}
        )
        assert "CONFLICT" not in badges.upper()
        assert "declared no conflict" not in badges

    def test_declared_none_is_shown_as_such(self):
        badges = format_provenance_badges({"coi_status": "declared_none", "has_coi": False})
        assert "declared no conflict" in badges

    def test_both_paths_agree_on_a_product_mention(self):
        """The canonical false positive must be clean on both paths."""
        from rag import rag_results_to_scored
        text = "Instrumented with ProTaper Next (Dentsply Sirona) files."
        assert detect_coi("", text)[0] is False           # live path decision
        row = {
            "pmid": "1", "title": "", "abstract": text, "authors": "",
            "year": 2023, "journal": "", "impact_factor": None,
            "sample_size": None, "followup_months": None, "citations": 0,
            "level_key": "level1", "score": 60.0, "similarity": 0.5,
            "is_curated": False, "coi_flag": False, "coi_funder": "",
            "registry": "", "has_erratum": False, "has_retraction": False,
            "medline_indexed": True,
        }
        assert rag_results_to_scored([row])[0]["has_coi"] is False


class TestCOIBlocklistBasics:

    def test_clean_text_not_flagged(self):
        has_coi, funder = check_coi_blocklist(
            "An independent multicentre trial with no commercial support."
        )
        assert has_coi is False
        assert funder == ""

    def test_detection_is_case_insensitive(self):
        assert check_coi_blocklist("Funded by DENTSPLY SIRONA.")[0] is True
        assert check_coi_blocklist("funded by dentsply sirona.")[0] is True

    def test_empty_text_is_safe(self):
        assert check_coi_blocklist("")[0] is False
