"""
Case discussion: the evidence engine and the opening prompts.

Item 1 measured the problem before anything was changed. Case answers cited a
median of 2 papers from a median-100 evidence base — retrieval was never the
bottleneck (it is the same engine Review uses), and the validator was already
running with a corrective retry. The loss was in three specific places, and
these tests pin all three plus the reworked opening prompt.

The scripted-case tests hit the live API and are opt-in via RUN_CASE_TESTS=1;
everything else is offline and runs in the normal suite.
"""
import inspect
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


class TestCaseGetsTheFullEvidenceEngine:
    """Item 2. Each assertion names a measured defect."""

    def test_case_does_not_inherit_the_review_early_stop(self):
        """run_case_chat called the builder with no mode=, so it defaulted to
        "review" and the early stop skipped level2-level5 and invitro once
        cochrane+level1 cleared 15 papers. Those are exactly the tiers a case
        needs — a case series is often the only literature on an unusual
        presentation."""
        import app
        src = inspect.getsource(app.run_case_chat)
        m = re.search(r"build_evidence_base_with_progress\([^)]*\)", src, re.S)
        assert m, "run_case_chat no longer calls the evidence builder"
        assert 'mode="case"' in m.group(0), (
            "case retrieval must pass mode='case' or the review early stop "
            "silently drops the weaker tiers")

    def test_case_mode_is_exempt_from_the_early_stop(self):
        """The other half: the builder must actually honour mode='case'."""
        import app
        src = inspect.getsource(app.build_evidence_base_with_progress)
        assert 'mode == "review"' in src, (
            "the early stop must be scoped to review; if it fires on any mode "
            "the case sweep is lost again")

    def test_case_answers_run_the_citation_support_check(self):
        """verify_citation_support ran only inside ask_clinical_question, so
        chairside advice — the output most likely to be acted on immediately —
        was the one place it was missing."""
        import endo_ai
        src = inspect.getsource(endo_ai.ask_case_question)
        assert "verify_citation_support" in src

    def test_case_answers_still_run_the_mapping_validator(self):
        """This one always ran. Asserted so a refactor cannot drop it while
        adding the support check."""
        import endo_ai
        src = inspect.getsource(endo_ai.ask_case_question)
        assert "validate_evidence_mapping" in src

    def test_case_has_room_to_cite(self):
        """max_tokens was 2000 against Review's 8000. An answer that must be
        conversational AND carry citations cannot spend what it has not got."""
        import endo_ai
        src = inspect.getsource(endo_ai.ask_case_question)
        budgets = [int(n) for n in re.findall(r"max_tokens\s*=\s*(\d+)", src)]
        assert budgets, "no max_tokens found in ask_case_question"
        assert min(budgets) >= 4000, f"case token budget too small: {budgets}"


class TestOpeningPrompt:
    """Item 3. The case path must NOT use the Review clarifier."""

    def test_case_uses_its_own_generator(self):
        import app
        src = inspect.getsource(app.case_chat)
        assert "generate_case_followups(" in src
        # Check for a CALL, not a mention: the comment above the call names the
        # Review clarifier to explain why it is not used, and an
        # `in src` test on the bare name flags that comment as the bug.
        assert "generate_clarifying_questions(" not in src, (
            "the shared Review clarifier asks 2-3 questions on principle, "
            "which is what produced the interrogation")

    def test_scaffold_is_one_open_invitation_not_a_form(self):
        from endo_ai import CASE_OPENING_SCAFFOLD
        s = CASE_OPENING_SCAFFOLD
        assert "in your own words" in s.lower()
        # A form would be numbered or bulleted; a scaffold is one sentence.
        assert "\n" not in s.strip(), "the scaffold must read as prose, not a checklist"
        for cue in ("age", "history", "clinical", "imaging", "symptoms"):
            assert cue in s.lower(), f"scaffold does not hint at {cue}"

    def test_prompt_instructs_rereading_before_asking(self):
        """The 'never re-ask' rule has to be IN the prompt; there is no
        post-hoc filter that could enforce it."""
        import endo_ai
        src = inspect.getsource(endo_ai.generate_case_followups)
        low = src.lower()
        assert "read the description again" in low or "re-read" in low
        assert "already" in low, "prompt must forbid asking for stated facts"

    def test_prompt_requires_a_reason_clause(self):
        import endo_ai
        src = inspect.getsource(endo_ai.generate_case_followups)
        assert "why it matters" in src.lower()

    def test_a_complete_description_can_return_nothing(self):
        """Returning [] must be reachable — a thorough description has earned
        an answer, not another round trip."""
        import endo_ai
        src = inspect.getsource(endo_ai.generate_case_followups)
        assert "return []" in src.lower().replace("[ ]", "[]")

    def test_generation_failure_does_not_block_the_case(self):
        """Fail-open: a clarify step that errors must not stop the answer."""
        import endo_ai
        src = inspect.getsource(endo_ai.generate_case_followups)
        assert "except Exception" in src and src.rstrip().endswith("return []")


# ── Live checks (opt-in) ─────────────────────────────────────────────────
FULL_CASE = (
    "62-year-old female, well-controlled type 2 diabetes, no other medical "
    "history, no bisphosphonates. Tooth 26, previously root treated 8 years "
    "ago, now tender to percussion for 3 weeks. Periapical radiograph and CBCT "
    "show a 6mm periapical radiolucency on the MB root with an untreated MB2. "
    "Tooth is non-vital (previously treated), restorable with an adequate "
    "ferrule and existing crown is sound. No sinus tract. Patient has taken "
    "amoxicillin from her GP with partial relief."
)

# Facts the FULL description states outright. Asking for any of these is the
# failure this item exists to fix.
ALREADY_STATED = ["bisphosphonate", "ferrule", "restorab", "diabet"]


@pytest.mark.skipif(os.environ.get("RUN_CASE_TESTS") != "1",
                    reason="hits the live API; set RUN_CASE_TESTS=1")
class TestScriptedOpenings:

    def test_a_full_description_gets_at_most_one_followup(self):
        from endo_ai import generate_case_followups
        qs = generate_case_followups(FULL_CASE)
        assert len(qs) <= 1, f"interrogating a complete description: {qs}"

    def test_a_sparse_description_gets_the_deciding_questions(self):
        from endo_ai import generate_case_followups
        qs = generate_case_followups("Tooth 36 hurts.")
        assert 1 <= len(qs) <= 3

    def test_never_asks_for_something_already_stated(self):
        """The rule that matters most. Every question is checked against facts
        the description gives outright."""
        from endo_ai import generate_case_followups
        qs = generate_case_followups(FULL_CASE)
        blob = " ".join(qs).lower()
        offenders = [t for t in ALREADY_STATED if t in blob]
        assert not offenders, (
            f"re-asked facts the description already states: {offenders} in {qs}")

    def test_every_question_carries_its_reason(self):
        from endo_ai import generate_case_followups
        qs = generate_case_followups("45-year-old, tooth 36, large periapical lesion.")
        for q in qs:
            assert "—" in q or " - " in q, (
                f"question gives no reason it matters: {q}")
