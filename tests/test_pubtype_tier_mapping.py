"""
Publication type -> evidence tier must be DERIVED, and must refuse to guess.

Two bugs of this shape have now shipped:

  * "Cochrane Review[pt]" — a publication type PubMed does not have. It
    translated to ("cochran" OR "cochrane") AND "Review"[pt], so every review
    that mentioned searching the Cochrane Library reached the top tier.
  * The repair for it, fix_cochrane_tier.py, demoted all 109 of those rows to
    `level1` in one blanket UPDATE — assuming every one was a systematic
    review. A narrative review at a false Level I is still a clinician being
    told weak evidence is strong.

scripts/reclassify_by_pubtype.py replaces both guesses with PubMed's
PublicationTypeList. These tests pin the mapping as a PURE function: no
network, no database.

The invariant that matters most is the MEDLINE authority gate. NLM assigns
"Systematic Review"/"Meta-Analysis" only when it indexes a record for
MEDLINE. A publisher-supplied record carries just ["Journal Article",
"Review"] however good the paper is — on this library that describes 53 rows,
45 of whose titles literally read "... : A Systematic Review". Demoting those
to Level V on a bare "Review" tag would destroy real Level I evidence, so the
mapping must decline rather than guess.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from endo_ai import TIER_ORDER
from scripts.reclassify_by_pubtype import (GUIDELINE_TITLE_RE,
                                           map_pubtypes_to_tier)

JA = "Journal Article"


def tier(pubtypes, journal="Int Endod J", medline=True, title="A paper."):
    return map_pubtypes_to_tier(pubtypes, journal, medline, title)[0]


def reason(pubtypes, journal="Int Endod J", medline=True, title="A paper."):
    return map_pubtypes_to_tier(pubtypes, journal, medline, title)[1]


class TestEvidenceSynthesisMapsToLevel1:

    @pytest.mark.parametrize("pubtypes", [
        [JA, "Systematic Review"],
        [JA, "Meta-Analysis"],
        [JA, "Meta-Analysis", "Systematic Review"],
        [JA, "Network Meta-Analysis", "Systematic Review"],
        [JA, "Network Meta-Analysis"],
        [JA, "Comparative Study", "Systematic Review"],
        [JA, "Research Support, Non-U.S. Gov't", "Systematic Review"],
    ])
    def test_sr_and_ma_are_level1(self, pubtypes):
        assert tier(pubtypes) == "level1"

    @pytest.mark.parametrize("pubtypes", [
        [JA, "systematic review"],
        [JA, "SYSTEMATIC REVIEW"],
        [JA, "  Meta-Analysis  "],
    ])
    def test_matching_is_case_and_whitespace_insensitive(self, pubtypes):
        assert tier(pubtypes) == "level1"

    def test_a_review_tag_alongside_sr_does_not_demote(self):
        """PubMed routinely tags an SR with both. Order of checks must put the
        stronger type first or every SR falls to level5."""
        assert tier([JA, "Review", "Systematic Review"]) == "level1"
        assert tier([JA, "Review", "Meta-Analysis"]) == "level1"


class TestNarrativeReviewIsDemoted:
    """The actual bug being fixed: an ordinary journal review must not sit at
    Level I."""

    def test_review_only_is_level5(self):
        assert tier([JA, "Review"]) == "level5"

    def test_reason_names_it_a_narrative_review(self):
        assert "narrative" in reason([JA, "Review"])

    def test_review_plus_comparative_study_is_still_narrative(self):
        """"Comparative Study" is a content descriptor, not a synthesis
        design — it must not rescue a narrative review."""
        assert tier([JA, "Comparative Study", "Review"]) == "level5"


class TestMedlineAuthorityGate:
    """A bare "Review" on a publisher-supplied record proves nothing, because
    NLM had not yet had the chance to tag it "Systematic Review"."""

    def test_non_medline_review_is_not_demoted(self):
        assert tier([JA, "Review"], medline=False) is None

    def test_non_medline_review_reason_says_why(self):
        assert "MEDLINE" in reason([JA, "Review"], medline=False)

    def test_medline_review_is_demoted(self):
        assert tier([JA, "Review"], medline=True) == "level5"

    @pytest.mark.parametrize("pubtypes", [
        [JA, "Systematic Review"],
        [JA, "Meta-Analysis"],
        [JA, "Randomized Controlled Trial"],
        [JA, "Practice Guideline"],
    ])
    def test_positively_asserted_strong_types_survive_the_gate(self, pubtypes):
        """An incomplete publisher list OMITS types, it does not invent them —
        so a strong type that IS present is still trustworthy."""
        assert tier(pubtypes, medline=False) == "level1"

    def test_the_shipped_false_positive_shape(self):
        """PMID 40941501, Healthcare (Basel), not MEDLINE-indexed:
        ["Journal Article", "Review"], title "Dynamic Navigation in Endodontic
        Surgery: A Systematic Review." Demoting this to Level V is the exact
        error this gate exists to prevent."""
        assert tier([JA, "Review"], journal="Healthcare (Basel)", medline=False,
                    title="Dynamic Navigation in Endodontic Surgery: "
                          "A Systematic Review.") is None


class TestGuidelinesUseTheProjectsExistingTier:
    """There is no separate guideline tier and one must not be invented: a key
    absent from TIER_ORDER is invisible to _build_evidence_context(), so those
    papers would never reach Claude. ingest_aae_guidelines.py and
    backfill_pubmed_metadata.py both already map guidelines to level1."""

    @pytest.mark.parametrize("pubtypes", [
        [JA, "Practice Guideline"],
        [JA, "Guideline"],
        [JA, "Practice Guideline", "Review"],
        [JA, "Consensus Development Conference"],
        [JA, "Consensus Statement", "Meta-Analysis", "Systematic Review"],
    ])
    def test_guidelines_are_level1(self, pubtypes):
        assert tier(pubtypes) == "level1"

    def test_guideline_tier_is_a_real_tier(self):
        assert tier([JA, "Practice Guideline"]) in TIER_ORDER


class TestGuidelineTitleGuardOnlyDeclines:
    """NLM omits "Guideline"[pt] from most dental society guidelines: the IADT
    trauma guidelines (PMID 32472740) carry only ["Journal Article",
    "Review"]. The guard must stop the demotion — and must never promote."""

    IADT = ("International Association of Dental Traumatology guidelines for "
            "the management of traumatic dental injuries: General introduction.")

    def test_iadt_guideline_is_not_demoted(self):
        assert tier([JA, "Review"], journal="Dent Traumatol", title=self.IADT) is None

    @pytest.mark.parametrize("title", [
        "European Society of Endodontology position statement: antibiotics.",
        "AAE consensus statement on regenerative endodontics.",
        "Clinical recommendations for a regenerative procedure.",
    ])
    def test_guard_covers_the_authority_document_shapes(self, title):
        assert tier([JA, "Review"], title=title) is None

    def test_guard_never_promotes(self):
        """It only ever returns None — a guideline-shaped title on a case
        report must not become level1."""
        assert tier([JA, "Case Reports"], title=self.IADT) == "level4"

    @pytest.mark.parametrize("title", [
        "The Calcium Hydroxide Controversy: Does Calcium Hydroxide Weaken Teeth?",
        "Antibiotics in Dentistry: A Narrative Review of the Evidence.",
        "Intraoral Scanners in Orthodontics: A Critical Review.",
    ])
    def test_ordinary_review_titles_are_still_demoted(self, title):
        assert tier([JA, "Review"], title=title) == "level5"

    def test_regex_does_not_fire_on_unrelated_prose(self):
        assert not GUIDELINE_TITLE_RE.search("Guided endodontic access in "
                                             "calcified canals.")


class TestCochraneIsIdentifiedByJournalNotPubtype:
    """A Cochrane review's pubtypes look like any other SR's, so a
    pubtype-only mapping would demote all 38 genuine ones out of the top
    tier."""

    @pytest.mark.parametrize("journal", [
        "Cochrane Database Syst Rev",
        "cochrane database of systematic reviews",
        "Cochrane Db Syst Rev",
    ])
    def test_cochrane_journal_wins(self, journal):
        assert tier([JA, "Systematic Review"], journal=journal) == "cochrane"

    def test_cochrane_journal_wins_even_with_thin_pubtypes(self):
        """Recent Cochrane records are often still just ["Journal Article"]."""
        assert tier([JA], journal="Cochrane Database Syst Rev") == "cochrane"

    def test_word_cochrane_in_another_journal_does_not_qualify(self):
        """The original bug was matching the WORD cochrane. Only the journal
        counts."""
        assert tier([JA, "Review"], journal="J Endod (cites Cochrane)") == "level5"

    def test_an_sr_in_an_ordinary_journal_is_level1_not_cochrane(self):
        assert tier([JA, "Systematic Review"], journal="J Endod") == "level1"


class TestCaseReportsOutrankReview:
    """"A case report and literature review" is a case report. Mirrors the
    precedence already in backfill_pubmed_metadata.py::PUBTYPE_TO_LEVEL."""

    def test_case_report_with_review_is_level4(self):
        assert tier([JA, "Case Reports", "Review"]) == "level4"

    def test_case_report_alone_is_level4(self):
        assert tier([JA, "Case Reports"]) == "level4"

    def test_case_report_does_not_outrank_a_systematic_review(self):
        assert tier([JA, "Case Reports", "Systematic Review"]) == "level1"


class TestRandomizedTrialsKeepLevel1:
    """Level I is RCTs *and* SRs (endo_ai.LEVEL_1_TERMS). An RCT that also
    carries "Review" must not be read as a narrative review."""

    def test_rct_is_level1(self):
        assert tier([JA, "Randomized Controlled Trial"]) == "level1"

    def test_rct_plus_review_is_level1(self):
        assert tier([JA, "Randomized Controlled Trial", "Review"]) == "level1"


class TestRefusesToGuess:
    """Returning None means "leave the row alone and report it". Every one of
    these would otherwise be a silent, unreviewable tier assignment."""

    @pytest.mark.parametrize("pubtypes", [
        [],
        [JA],
        [JA, "Research Support, Non-U.S. Gov't"],
        [JA, "Observational Study"],
        [JA, "Retracted Publication"],
        ["", "   "],
    ])
    def test_unmappable_records_return_none(self, pubtypes):
        assert tier(pubtypes) is None

    def test_empty_list_says_no_publication_types(self):
        assert "no publication types" in reason([])

    def test_scoping_review_is_not_guessed_at(self):
        """A scoping review charts a literature without effect estimates or
        quality appraisal — neither Level I nor plainly Level V, and this
        project has never assigned it a tier."""
        t, why = map_pubtypes_to_tier([JA, "Scoping Review"], "J Endod", True, "x")
        assert t is None
        assert "scoping review" in why.lower()

    def test_scoping_review_alongside_an_sr_is_still_level1(self):
        assert tier([JA, "Scoping Review", "Systematic Review"]) == "level1"

    def test_every_reason_is_non_empty(self):
        for pubtypes in ([], [JA], [JA, "Review"], [JA, "Systematic Review"]):
            assert reason(pubtypes).strip()


class TestNeverInventsATier:

    @pytest.mark.parametrize("pubtypes", [
        [], [JA], [JA, "Review"], [JA, "Systematic Review"], [JA, "Meta-Analysis"],
        [JA, "Case Reports"], [JA, "Practice Guideline"], [JA, "Scoping Review"],
        [JA, "Randomized Controlled Trial"], [JA, "Network Meta-Analysis"],
    ])
    def test_result_is_none_or_a_known_tier(self, pubtypes):
        for journal in ("J Endod", "Cochrane Database Syst Rev"):
            for medline in (True, False):
                t = tier(pubtypes, journal=journal, medline=medline)
                assert t is None or t in TIER_ORDER, \
                    f"{pubtypes} -> {t!r} is not a tier in TIER_ORDER"


class TestPurity:
    """No network, no database, no hidden state — the mapping must be safe to
    reason about and safe to re-run."""

    def test_repeated_calls_agree(self):
        args = ([JA, "Review"], "Dent Traumatol", True, "A Critical Review.")
        assert map_pubtypes_to_tier(*args) == map_pubtypes_to_tier(*args)

    def test_input_list_is_not_mutated(self):
        pubtypes = [JA, "Review"]
        map_pubtypes_to_tier(pubtypes, "J Endod", True, "x")
        assert pubtypes == [JA, "Review"]

    def test_tolerates_none_inputs(self):
        assert map_pubtypes_to_tier(None, None, True, None)[0] is None
