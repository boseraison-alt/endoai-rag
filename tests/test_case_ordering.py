"""
The ordering rule, and the mutation that proves it is load-bearing
(`case-v2.1` Item 3).

The fixture:

> 20-year-old, no response to cold testing on tooth #20, well-defined
> periapical lesion, no filling, no cracks, Asian ethnicity.

What it did before `case-v2.1`: raised dens evaginatus only in Key
Considerations, AFTER an Assessment that opened "a straightforward endodontic
diagnosis… Proceed with non-surgical root canal treatment". Tooth #20 is the
mandibular second premolar and the patient is 20 and of Asian ethnicity — the
textbook DE presentation — and the answer reached management before it named a
cause.

The eval case `dens-evaginatus-premolar-diagnostic` asserts the ordering
end to end, live. These tests pin the two mechanisms that make it hold, offline
and in the normal suite, so that breaking either fails in seconds rather than
after a $0.22 eval run:

  1. the prompt's ordering rule exists and says the differential comes first;
  2. `must_precede` — the harness operator that expresses it — actually
     detects a reversal. An assertion that cannot fail is the one thing worse
     than no assertion, and this repo has shipped one before (`--diff`,
     declared in argparse and never read).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "eval"))

import pytest

import endo_ai

FIXTURE_ID = "dens-evaginatus-premolar-diagnostic"


def _case():
    import run_eval
    _doc, cases = run_eval.load_cases()
    for c in cases:
        if c["id"] == FIXTURE_ID:
            return c
    pytest.fail(f"{FIXTURE_ID} is not in questions.json")


class TestTheFixtureIsPinned:

    def test_the_case_exists_and_is_a_case_turn(self):
        c = _case()
        assert c["mode"] == "case"
        assert c["force_route"] == "library"
        assert "tooth #20" in c["question"]
        assert "Asian ethnicity" in c["question"]

    def test_it_asserts_the_ordering(self):
        pairs = _case()["expect"]["must_precede"]
        flat = [[a.lower(), b.lower()] for a, b in pairs]
        assert ["dens evaginatus", "root canal treatment"] in flat, (
            "the case no longer asserts that the cause precedes the treatment")
        assert any(a == "differential" for a, _b in flat)

    def test_it_forbids_the_bisphosphonate_follow_up(self):
        clar = _case()["expect"]["clarify"]
        assert "bisphosphonate" in clar["must_not_ask_about"]

    def test_it_caps_support_flags_at_the_top_of_the_observed_range(self):
        """2, not the 0 the brief asked for. Measured across eight runs of
        this fixture: 2, 2, 1, 3 before the per-candidate attribution list,
        then 0, 1, 2 after. Zero is a point target on a stochastic judge, and
        WORKLIST §0 says assertions are floors and forbidden conditions, never
        points. The cap is the top of the observed post-fix range, so it
        catches a blow-up and not the judge's noise.

        It is still meaningfully tight: the OTHER two case cases cap at 3 and
        4, and this one is the only case in the file that has ever measured 0.
        """
        assert _case()["expect"]["max_support_flags"] == 2


class TestMustPrecedeActuallyFails:
    """The harness operator, exercised directly. `must_precede` was added in
    `case-v2` and this is the test that it is not decorative."""

    def _check(self, answer, pairs):
        """Calls THE HARNESS's own function, not a copy of it.

        The first version of this test re-implemented the comparison here and
        passed happily while `run_eval`'s copy was mutated to `elif False:`.
        That is this repo's documented bug class — a test asserting on a
        private copy instead of the code actually used — and it is why
        `check_precedence` is a top-level function.
        """
        import run_eval
        return run_eval.check_precedence(answer, pairs)

    def test_the_right_order_passes(self):
        answer = ("**Differential — most likely first**\n\n1. Dens evaginatus "
                  "…\n\nThen, briefly: management. Proceed with root canal "
                  "treatment.")
        assert self._check(answer, [["dens evaginatus",
                                     "root canal treatment"]]) == []

    def test_the_reversed_order_FAILS(self):
        """THE mutation the brief asks for, expressed as data rather than by
        editing the prompt: an answer that opens with the treatment plan and
        mentions the cause afterwards. If this passes, the eval case is
        decorative."""
        answer = ("**Assessment:** a straightforward endodontic diagnosis.\n\n"
                  "**Recommendation:** Proceed with non-surgical root canal "
                  "treatment.\n\n**Key Considerations:** consider dens "
                  "evaginatus as the underlying cause.")
        failures = self._check(answer, [["dens evaginatus",
                                         "root canal treatment"]])
        assert failures, "a reversed answer passed must_precede"
        assert "leads with the wrong thing" in failures[0]

    def test_an_absent_term_fails_too(self):
        """Silence must not read as order. An answer that never names the
        cause has not put it first."""
        answer = "Proceed with root canal treatment."
        failures = self._check(answer, [["dens evaginatus",
                                         "root canal treatment"]])
        assert failures, "an answer that never names the cause passed"
        assert "absent from the answer" in failures[0]


class TestThePromptCarriesTheOrderingRule:
    """`case-v2.1` Item 1's actual enforcement point. Asserted on the PROMPT
    STRING, not on a docstring: a rule that lives only in a docstring survives
    a mutation that deleted it from the prompt, and this repo has been caught
    by exactly that."""

    def test_the_differential_comes_first(self):
        f = endo_ai._CASE_FORMAT_DIAGNOSTIC
        assert "Do not open with management" in f
        assert "The first thing on the page is the differential" in f

    def test_management_is_last_and_bounded(self):
        f = endo_ai._CASE_FORMAT_DIAGNOSTIC
        assert "only after the differential" in f
        assert "longer than the differential" in f

    def test_tooth_identity_and_demographics_are_priors(self):
        """Dens evaginatus is only the lead candidate once the tooth is known.
        Before this clause it was candidate 3 of 6, or absent."""
        p = endo_ai.DIFFERENTIAL_PROMPT
        assert "WHICH TOOTH IT IS" in p
        assert "dens evaginatus in mandibular premolars" in p

    def test_the_scaffold_attributes_papers_to_candidates(self):
        """The structural fix behind max_support_flags. Without it a paper
        retrieved for one candidate was equally available to every other, and
        a paper about cystic lesions carried three dens invaginatus prevalence
        claims."""
        import inspect
        src = inspect.getsource(endo_ai.ask_case_question)
        assert "WHICH PAPERS WERE RETRIEVED FOR WHICH CANDIDATE" in src

    def test_a_negative_claim_takes_no_marker(self):
        """The artifact_negative class from `guardrails-v1`: no abstract can
        state what it omits."""
        assert "does NOT contain" in endo_ai._MARKERS_DIAGNOSTIC
        assert "takes NO marker" in endo_ai._MARKERS_DIAGNOSTIC
