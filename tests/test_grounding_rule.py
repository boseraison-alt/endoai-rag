"""The grounding rule reaches the model, on every synthesis path.

Every synthesis prompt in this codebase mandates a `[[PMID:N]]` marker on every
standalone clinical claim, and none of them said what to do when no retrieved
paper supports one. `_build_corrective_message` pushed the same way. That is
the remaining known mechanism for a decorative citation, and unlike the
missing-abstracts bug it applies on the LIVE path too.

These tests assert on the SYSTEM PROMPT ACTUALLY SENT, captured off
`_invoke_claude`, not on the source of the prompt string. HANDOVER's fourth
lesson is about tests that grep source instead of asserting on the data the
model was given: a prompt built by `str.replace` on a placeholder is exactly
the shape where the string can be present and the substitution absent, and a
source grep passes either way.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai

MARKER = "GROUNDING — WHAT A CITATION MARKER ASSERTS"


class FakeUsage:
    input_tokens = 10
    output_tokens = 10


class FakeResponse:
    def __init__(self, text):
        self.content = [type("B", (), {"text": text})()]
        self.usage = FakeUsage()


@pytest.fixture
def captured(monkeypatch):
    """Capture every system prompt `_invoke_claude` is handed."""
    seen = []

    def _fake(client_, function_name="", **kwargs):
        seen.append({"function": function_name,
                     "system": kwargs.get("system") or ""})
        if "citation_support" in function_name:
            return FakeResponse("[]")
        return FakeResponse("## CLINICAL RECOMMENDATION\n\nSee the evidence "
                            "[[PMID:1]].\n\n## EVIDENCE SUMMARY\n\nText.\n\n"
                            "## REFERENCES\n\n1. [PMID: 1] A B.")

    monkeypatch.setattr(endo_ai, "_invoke_claude", _fake)
    monkeypatch.setattr(endo_ai, "log_llm_call", lambda *a, **k: 0.0)
    monkeypatch.setattr(endo_ai, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(endo_ai, "verify_citation_support",
                        lambda *a, **k: {"flags": [], "checked": 0,
                                         "cost": 0.0, "status": "not_run",
                                         "detail": "stubbed"})
    monkeypatch.setattr(endo_ai, "_log_evidence_mapping", lambda *a, **k: None)
    return seen


EVIDENCE = {
    "level1": {"source": "rag", "scored": [{
        "pmid": "1", "title": "A trial of something",
        "abstract": "BACKGROUND: x. CONCLUSIONS: y.",
        "authors": "A B", "year": 2024, "journal": "J Endod",
        "score": 70.0, "citations": 3, "level_key": "level1"}]},
}


class TestTheRuleReachesEachPrompt:

    def test_review_synthesis(self, captured):
        endo_ai.ask_clinical_question("q?", EVIDENCE)
        systems = [c["system"] for c in captured
                   if "ask_clinical_question" in c["function"]]
        assert systems, "the synthesiser was never invoked"
        assert all(MARKER in s for s in systems)

    def test_curriculum_module(self, captured, monkeypatch):
        monkeypatch.setattr(endo_ai, "validate_evidence_mapping",
                            lambda *a, **k: {"passed": True, "score": 100,
                                             "cited_pmids": ["1"],
                                             "fabricated_pmids": [],
                                             "unattributed_claims": [],
                                             "gap_sections": [],
                                             "failure_reason": None})
        endo_ai.write_curriculum_module({"title": "M"}, EVIDENCE, "parent", 1, 4)
        systems = [c["system"] for c in captured
                   if "write_curriculum_module" in c["function"]]
        assert systems
        assert all(MARKER in s for s in systems)

    def test_case_discussion(self, captured, monkeypatch):
        monkeypatch.setattr(endo_ai, "validate_evidence_mapping",
                            lambda *a, **k: {"passed": True, "score": 100,
                                             "cited_pmids": ["1"],
                                             "fabricated_pmids": [],
                                             "unattributed_claims": [],
                                             "gap_sections": [],
                                             "failure_reason": None})
        # The case path goes through `tier2_invoke`, not `_invoke_claude`
        # directly, so it needs its own seam — and that difference is itself
        # worth pinning: a rule spliced only into the two prompts that share a
        # seam would look complete from `_invoke_claude`.
        def _fake_tier2(name, **kw):
            captured.append({"function": name,
                             "system": kw.get("system") or ""})
            return FakeResponse("**Assessment:** ok [[PMID:1]]"), 0.0

        monkeypatch.setattr(endo_ai, "tier2_invoke", _fake_tier2)
        endo_ai.ask_case_question([{"role": "user", "content": "case"}], EVIDENCE)
        systems = [c["system"] for c in captured
                   if "ask_case_question" in c["function"]]
        assert systems
        assert all(MARKER in s for s in systems)

    def test_no_placeholder_survives_into_a_sent_prompt(self, captured):
        """The failure mode a source grep cannot see: the rule text is in the
        file, the `replace` call is not, and the model is sent the literal
        token instead of the rule."""
        endo_ai.ask_clinical_question("q?", EVIDENCE)
        for c in captured:
            assert "__GROUNDING_RULE__" not in c["system"], \
                f"{c['function']} was sent an unsubstituted placeholder"


class TestWhatTheRuleActuallySays:
    """The rule's job is to supply the option the prompt was missing. If it
    only repeated the marker mandate it would change nothing, and if it
    relaxed the mandate it would trade one defect for another."""

    def test_it_permits_an_unmarked_claim(self):
        r = endo_ai._GROUNDING_RULE
        assert "no marker" in r.lower() or "NO marker" in r
        assert "correct outcome" in r

    def test_it_still_forbids_a_decorative_marker(self):
        assert "worse than no marker" in endo_ai._GROUNDING_RULE

    def test_it_names_the_traps_the_hand_judgement_found(self):
        """Four mechanisms, each read off a real flagged pair: a mechanism
        claim cited to an outcomes review, a numeric parameter cited to a
        paper that does not report it, an argument from silence, and a
        finding generalised past the paper's scope."""
        r = endo_ai._GROUNDING_RULE.lower()
        for trap in ("mechanism", "numeric", "silence", "generalised"):
            assert trap in r, f"the rule does not name the {trap} trap"

    def test_one_constant_not_three_copies(self):
        """Three copies of a rule about what a citation means will drift, and
        the drift is invisible — each path would still look correct alone."""
        import re
        src = Path(endo_ai.__file__).read_text(encoding="utf-8")
        assert len(re.findall(r"^_GROUNDING_RULE = ", src, re.M)) == 1
        assert src.count(MARKER) == 1


class TestTheCorrectiveMessageDoesNotPushTheOtherWay:
    """The retry message arrives after the model has been told its answer
    failed validation, which is the moment a decorative citation is cheapest
    to add. It used to lead with 'Add markers from the evidence base'."""

    def _msg(self, **result):
        base = {"fabricated_pmids": [], "unattributed_claims": [],
                "gap_sections": [], "recommendation": {}}
        base.update(result)
        return endo_ai._build_corrective_message(base)

    def test_unattributed_claims_lead_with_rephrasing(self):
        msg = self._msg(unattributed_claims=[{"sentence": "It works well."}])
        i_rephrase = msg.upper().index("REPHRASE")
        i_add = msg.index("Add a marker")
        assert i_rephrase < i_add, \
            "the retry still asks for a marker before it offers the alternative"

    def test_adding_a_marker_carries_the_grounding_condition(self):
        msg = self._msg(unattributed_claims=[{"sentence": "It works well."}])
        assert "ONLY where a paper in the evidence block actually states" in msg

    def test_the_closing_forbids_moving_a_marker_onto_a_wrong_claim(self):
        """`validate_evidence_mapping` only checks that a cited PMID was
        retrieved. Re-pointing a marker at any paper in the block clears it."""
        msg = self._msg(unattributed_claims=[{"sentence": "x"}])
        assert "do not MOVE a marker" in msg
        assert "clears this validator and fails the reader" in msg

    def test_the_fabrication_branch_is_unchanged(self):
        """Fabricated PMIDs are a different failure with a correct existing
        instruction; this change must not have touched it."""
        msg = self._msg(fabricated_pmids=["999"])
        assert "FABRICATED PMIDS" in msg
        assert "The evidence base does not address this point." in msg
