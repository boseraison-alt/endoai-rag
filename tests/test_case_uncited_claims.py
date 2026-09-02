"""
Uncited clinical claims on the case path (`case-v3` Item B).

WHAT THE MEASUREMENT FOUND. Both turns of a real DE case conversation, run
through the product's own detectors (`scripts/analyze_case_uncited.py`,
`eval/logs/case_uncited.json`):

  claims carrying a marker, lost only in the browser copy   26   -> Item A
  claims with no marker at all                              58
    ... the validator already flagged                        4
    ... it MISSED, and they are real clinical instructions   6   <- this file
    ... background and *Fits because:* lines, no marker
        wanted                                              48

The six it missed all have the same shape, and it is a shape the original
patterns could not see. Those patterns catch a claim by its NUMBERS — a
percentage, an n, a p-value, a dose. A chairside protocol is an INSTRUCTION,
and an instruction can be entirely uncited and entirely actionable without
containing a statistic:

  "Reduce occlusal contact on the tubercle — selective equilibration…"
  "This is the single most impactful step."
  "Calcium hydroxide or MTA liner placement … is advocated in the literature."
  "Screen the entire mouth for DE."

FOUR PATTERNS, and a fifth rule for named authors. Plus the escape hatch that
makes the whole thing survivable: a claim that says out loud it is NOT from
the evidence base counts as attributed. Without that, the prompt offers
"label it", the model labels it, the detector flags it anyway, and the honest
move fails identically to the silent one.

The thresholds are NOT case-specific and this file asserts that too:
`validate_evidence_mapping` is not mode-aware, `_EVMAP_MAX_UNATTRIBUTED` is
one constant, and the case path calls the same function Review does.
"""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai
from endo_ai import (_detect_unattributed_claims, _detect_uncited_author_mentions,
                     validate_evidence_mapping, _build_corrective_message)


def flag(text):
    """The sentences the detector would flag in a one-section answer."""
    return [f["sentence"] for f in
            _detect_unattributed_claims("## Recommendation\n" + text + "\n")]


# ── the four shapes the detector used to miss ─────────────

class TestProtocolDirectivesAreClaims:
    """Every string here is verbatim from the DE conversation."""

    @pytest.mark.parametrize("sentence", [
        "3. **Gradual elective reduction of the tubercle over multiple visits** "
        "— performed in small increments (0.5 mm per visit) with 6-8 week "
        "intervals, allowing secondary dentine deposition to track ahead.",
        "Monitor with cold test and periapical radiographs every 6 months to "
        "detect early periapical change.",
        "Recall the patient every 3 months for the first year after treatment.",
    ])
    def test_a_dose_or_interval_written_as_a_protocol(self, sentence):
        assert flag(sentence), f"not flagged: {sentence[:80]}"

    def test_a_bare_interval_range_is_the_shape_only_this_pattern_catches(self):
        """The measurement, made when a mutation of the interval pattern
        survived every test above: three of the four shapes the item listed
        were ALREADY covered by the original unit pattern — "0.5 mm per visit"
        matches `\\d+ mm`, "every 6 months" matches `\\d+ months`. Only a bare
        RANGE is new, because "6-8 week" is singular and the original list has
        only the plural.

        This sentence is constructed to match nothing else: it does not open
        with an imperative, carries no percentage or n or p-value, no
        superlative, and no appeal to the literature.
        """
        s = ("The tubercle is taken down at 6-8 week intervals so that "
             "dentine can track ahead of the reduction.")
        assert flag(s), (
            "the interval-range pattern no longer catches the one shape it "
            "was added for, and every other test here would still pass")

    @pytest.mark.parametrize("sentence", [
        "Calcium hydroxide or MTA liner placement after each reduction step is "
        "advocated in the literature for deeper reductions.",
        "Studies have shown that immediate coronal restoration improves "
        "outcomes substantially.",
        "The literature supports staged reduction over a single-visit approach.",
    ])
    def test_an_appeal_to_the_literature_that_cites_nothing(self, sentence):
        """The sharpest of the four: the sentence explicitly claims a body of
        evidence exists and declines to name it."""
        assert flag(sentence), f"not flagged: {sentence[:80]}"

    @pytest.mark.parametrize("sentence", [
        "1. **Reduce occlusal contact on the tubercle** — selective "
        "equilibration to eliminate traumatic occlusal loading on the cusp.",
        "Screen the entire mouth for DE — mandibular second premolars are the "
        "classic site but first premolars can also be affected.",
        "Refer promptly for vital pulp therapy rather than waiting for frank "
        "necrosis in an adjacent affected tooth.",
    ])
    def test_an_imperative_clinical_instruction(self, sentence):
        assert flag(sentence), f"not flagged: {sentence[:80]}"

    @pytest.mark.parametrize("sentence", [
        "This is the single most impactful step; gradual attrition of an "
        "unloaded tubercle allows reparative dentine to wall off the pulp horn.",
        "Patient education is critical — the patient must understand not to "
        "bite hard foods that could fracture the remaining tubercle.",
    ])
    def test_a_superlative_about_clinical_importance(self, sentence):
        assert flag(sentence), f"not flagged: {sentence[:80]}"


class TestTheDetectorStaysConservative:
    """A detector that flags everything fails an answer for having prose in
    it, and the retry is a full Opus regeneration. These are the sentences it
    must keep letting through."""

    @pytest.mark.parametrize("sentence", [
        "The appropriate intervention depends entirely on the current state of "
        "the tubercle at the time of examination.",
        "*Fits because:* Tooth #20 is the mandibular left second premolar and "
        "the patient is of Asian origin.",
        "*Argues against:* No fractured or worn occlusal tubercle was "
        "specifically mentioned in the case description.",
        "There are three clinical scenarios, and which one applies changes the "
        "answer completely.",
        "Preventive window has partially closed but the pulp may still be "
        "salvageable in this presentation.",
    ])
    def test_background_and_case_reading_are_not_flagged(self, sentence):
        assert not flag(sentence), f"wrongly flagged: {sentence[:80]}"

    def test_a_verb_mid_sentence_is_not_an_instruction(self):
        """The imperative pattern is anchored to the start of the unit. A
        sentence that merely CONTAINS "reduce" is describing, not directing."""
        assert not flag("Unloading the cusp would reduce the risk of an abrupt "
                        "fracture, which is the mechanism of interest here.")


class TestTheLabelledEscapeHatch:
    """`case-v3` Item B(b): a numeric directive the evidence base cannot
    support must be CUT, CITED, or LABELLED. The label has to actually work,
    or the prompt is offering a move that fails anyway."""

    LABELS = [
        "Reduce the tubercle in 0.5 mm increments at 6-8 week intervals "
        "(standard practice, not from the retrieved evidence base).",
        "Recall every 6 months — standard practice, not supported by a paper "
        "in this evidence base.",
        "Monitor every 3 months; no paper in this evidence base addresses the "
        "recall interval for this anomaly.",
        "Staged reduction is conventional, from the wider literature, which "
        "this search did not return.",
    ]

    @pytest.mark.parametrize("sentence", LABELS)
    def test_a_labelled_directive_is_not_flagged(self, sentence):
        assert not flag(sentence), (
            "the model labelled its claim honestly and was flagged anyway — "
            "the honest move and the silent one now fail identically")

    def test_the_same_directive_unlabelled_IS_flagged(self):
        """The pair is the test. Remove the label and it must flag, or the
        escape hatch is just a way through."""
        bare = "Reduce the tubercle in 0.5 mm increments at 6-8 week intervals."
        assert flag(bare)

    def test_the_prompt_offers_all_three_endings(self):
        src = inspect.getsource(endo_ai.ask_case_question)
        assert "THREE HONEST ENDINGS" in src
        for move in ("CITE it", "CUT it", "LABEL it"):
            assert move in src, f"the prompt does not offer: {move}"
        assert "Silent confidence is the failure" in src


# ── named authors ─────────────────────────────────────────

class TestNamedAuthorsNeedMarkers:
    """Item B(c). Naming an author asserts that a particular paper says this
    and hands the clinician nothing to click — the same failure as a bare
    PMID, which the prompt already forbids."""

    def test_an_author_with_no_marker_is_detected(self):
        got = _detect_uncited_author_mentions(
            "## Evidence\nSjogren et al. demonstrated that pulp status at the "
            "time of treatment is the dominant determinant of outcome.\n")
        assert len(got) == 1
        assert "Sjogren et al" in got[0]["name"]

    def test_two_authors_joined_by_and(self):
        got = _detect_uncited_author_mentions(
            "## Evidence\nSenia and Regezi described bilateral periapical "
            "pathology in caries-free premolars as a hallmark presentation.\n")
        assert len(got) == 1

    def test_an_author_WITH_a_marker_is_fine(self):
        assert _detect_uncited_author_mentions(
            "## Evidence\nSjogren et al. demonstrated that pulp status is the "
            "dominant determinant [[PMID:2084204]].\n") == []

    def test_a_marker_elsewhere_in_the_same_claim_counts(self):
        """Scoped to the claim unit, not the clause. A name in the same unit
        as a marker is attributed even if the marker sits on the neighbouring
        clause — being stricter would flag the normal, correct form."""
        assert _detect_uncited_author_mentions(
            "## Evidence\nThe biological rationale for staged reduction is "
            "established [[PMID:2084204]] (Sjogren et al. showed pulp status "
            "dominates outcome).\n") == []

    @pytest.mark.parametrize("phrase", [
        "Scenario A and Scenario B differ in whether the tubercle has "
        "fractured yet, which changes everything.",
        "Cochrane and PubMed were both searched for this question, with no "
        "relevant result returned.",
        "Level I and Level II evidence disagree on this point in the "
        "retrieved set.",
    ])
    def test_capitalised_non_authors_are_not_mistaken_for_names(self, phrase):
        assert _detect_uncited_author_mentions("## E\n" + phrase + "\n") == []

    def test_the_validator_fails_the_answer(self):
        """One is enough — no tolerance count, unlike unattributed claims. An
        unattributed claim can be a background sentence read too eagerly; a
        named author is unambiguous."""
        r = validate_evidence_mapping(
            "## CLINICAL RECOMMENDATION\nBased on Level I evidence, treat "
            "[[PMID:111]].\n\n## EVIDENCE\nSjogren et al. demonstrated that "
            "pulp status dominates the outcome of treatment.\n",
            {"level1": {"ids": ["111"], "scored": [{"pmid": "111"}]}})
        assert r["passed"] is False
        assert "UNCITED_AUTHOR_MENTION" in r["failure_reason"]

    def test_the_corrective_message_says_what_to_do(self):
        msg = _build_corrective_message({
            "author_mentions": [{"name": "Sjogren et al.",
                                 "sentence": "Sjogren et al. demonstrated X."}]})
        assert "NAMED AUTHORS WITH NO MARKER" in msg
        assert "remove the name" in msg
        assert "attach the nearest PMID" in msg, (
            "the corrective message must forbid the cheap fix, or the retry "
            "will take it")

    def test_the_prompt_forbids_it_up_front(self):
        """Catching it on the retry is the fallback; the prompt is the fix."""
        src = inspect.getsource(endo_ai.ask_case_question)
        assert "NEVER name an author without a marker" in src


# ── the thresholds are shared, not case-specific ──────────

class TestTheCasePathUsesReviewsThresholds:

    def test_the_validator_is_not_mode_aware(self):
        sig = inspect.signature(validate_evidence_mapping)
        assert list(sig.parameters) == ["answer", "evidence"], (
            "validate_evidence_mapping grew a mode parameter — the case path "
            "can now be held to a different standard than Review")

    def test_the_limit_is_one_constant(self):
        src = inspect.getsource(endo_ai)
        assert src.count("_EVMAP_MAX_UNATTRIBUTED =") == 1

    def test_the_case_path_calls_the_same_validator(self):
        src = inspect.getsource(endo_ai.ask_case_question)
        assert "validate_evidence_mapping(answer, evidence)" in src
