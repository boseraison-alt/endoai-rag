"""
Diagnostic case turns answer with a differential (`case-v2` Item 5).

"What could the cause be?" and "what should I do?" are different questions and
were being answered by one pipeline. Item 1 measured what that cost, on the
reported case — a 20-year-old with a necrotic, unrestored, caries-free tooth:

  - the follow-up generator asked a NON-DISCRIMINATING question in 8 runs of
    15 (bisphosphonates, of a 20-year-old, in 7), and asked about tooth
    identity, developmental anomaly, sinus tract, discoloration or orthodontic
    history in ZERO;
  - the search-term generators put trauma in 8 runs of 8 and dens invaginatus
    in 2, the palatogingival groove in 0 — so WHICH candidate causes got any
    literature was a coin flip;
  - and the answer had nowhere to put a differential regardless, because the
    case prompt mandates Assessment / Recommendation / Evidence / Key
    Considerations and nothing else.

The three properties these tests pin, in the order the failure happens:

  1. the intent split FAILS OPEN TO TREATMENT — every failure mode, always;
  2. the treatment path is BYTE-IDENTICAL to what shipped;
  3. a diagnostic answer is formatted differential-first, and a candidate with
     no literature stays in the differential rather than being dropped.

The live end-to-end assertions are opt-in via RUN_CASE_TESTS=1, like the rest
of this suite's scripted-case tests; everything else runs offline.
"""

import inspect
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai
from endo_ai import (CASE_INTENT_DIAGNOSTIC, CASE_INTENT_TREATMENT,
                     classify_case_intent, generate_case_differential,
                     _CASE_FORMAT_DIAGNOSTIC, _CASE_FORMAT_TREATMENT,
                     DIFFERENTIAL_MIN, DIFFERENTIAL_MAX)

YOUNG_CASE = ("20-year-old, necrotic tooth, no restoration, no caries — what "
              "could the cause be?")


# ── 1. The router fails open to treatment ─────────────────

class TestIntentFailsOpenToTreatment:
    """Treatment is the path that shipped and is measured. A router that
    failed to `diagnostic` would send a routine follow-up down a new and more
    expensive path on a Haiku hiccup, which is the wrong direction to be wrong
    in."""

    def _stub(self, monkeypatch, text=None, raises=None):
        class _C:
            def __init__(self, *a, **kw):
                pass

        def fake(client, function_name=None, **kw):
            if raises:
                raise raises
            class R:
                content = [type("T", (), {"text": text})()]
                usage = type("U", (), {"input_tokens": 1, "output_tokens": 1,
                                       "cache_creation_input_tokens": 0,
                                       "cache_read_input_tokens": 0})()
            return R()

        monkeypatch.setattr(endo_ai, "_invoke_claude", fake)
        monkeypatch.setattr(endo_ai.anthropic, "Anthropic", _C)
        monkeypatch.setattr(endo_ai, "_get_api_key", lambda: "test")
        monkeypatch.setattr(endo_ai, "log_llm_call",
                            lambda *a, **kw: 0.0)

    def test_empty_input_is_treatment(self):
        assert classify_case_intent("", "") == CASE_INTENT_TREATMENT

    def test_an_api_error_is_treatment(self, monkeypatch):
        self._stub(monkeypatch, raises=RuntimeError("boom"))
        assert classify_case_intent(YOUNG_CASE) == CASE_INTENT_TREATMENT

    def test_an_unrecognised_answer_is_treatment(self, monkeypatch):
        self._stub(monkeypatch, text="maybe both, hard to say")
        assert classify_case_intent(YOUNG_CASE) == CASE_INTENT_TREATMENT

    def test_a_diagnostic_answer_is_honoured(self, monkeypatch):
        self._stub(monkeypatch, text="diagnostic")
        assert classify_case_intent(YOUNG_CASE) == CASE_INTENT_DIAGNOSTIC

    def test_punctuation_does_not_send_a_diagnostic_turn_to_treatment(
            self, monkeypatch):
        """A model that answers "diagnostic." despite being told one word is
        still telling you the answer. Treating that as a parse failure would
        cost a differential for a full stop."""
        self._stub(monkeypatch, text="diagnostic.\n")
        assert classify_case_intent(YOUNG_CASE) == CASE_INTENT_DIAGNOSTIC

    def test_the_prompt_tells_it_which_way_to_lean(self):
        """Asserted on the PROMPT, not on the docstring. A rule that lives
        only in a docstring passes a mutation check that deleted it from the
        prompt — this repo has done exactly that once."""
        assert "answer treatment" in endo_ai.CASE_INTENT_PROMPT.lower()


# ── 2. The treatment path did not move ────────────────────

class TestTheTreatmentPathIsUnchanged:

    def test_no_differential_means_the_treatment_format(self):
        assert "**Assessment:**" in _CASE_FORMAT_TREATMENT
        assert "**Recommendation:**" in _CASE_FORMAT_TREATMENT
        assert "**Key Considerations:**" in _CASE_FORMAT_TREATMENT

    def test_the_diagnostic_format_is_a_different_document(self):
        assert "Differential" in _CASE_FORMAT_DIAGNOSTIC
        assert "What would discriminate" in _CASE_FORMAT_DIAGNOSTIC
        assert "**Assessment:**" not in _CASE_FORMAT_DIAGNOSTIC

    def test_run_case_chat_only_builds_a_differential_for_diagnostic(self):
        import app
        src = inspect.getsource(app.run_case_chat)
        m = re.search(r"if intent == CASE_INTENT_DIAGNOSTIC:", src)
        assert m, "the differential is no longer gated on the intent"
        gen = src.index("generate_case_differential(")
        assert m.start() < gen, (
            "generate_case_differential runs before the intent is checked — "
            "every treatment turn would pay for a differential it discards")

    def test_a_treatment_turn_still_uses_the_single_query_builder(self):
        import app
        src = inspect.getsource(app.run_case_chat)
        assert "build_evidence_base_with_progress(job_id, search_q," in src
        assert 'mode="case"' in src


# ── 3. The differential ───────────────────────────────────

class TestTheDifferentialPrompt:

    def test_it_asks_for_causes_not_treatments(self):
        p = endo_ai.DIFFERENTIAL_PROMPT.lower()
        assert "aetiology" in p or "etiology" in p
        assert "never a treatment" in p

    def test_it_asks_what_would_discriminate(self):
        assert "discriminator" in endo_ai.DIFFERENTIAL_PROMPT

    def test_it_asks_about_the_absences(self):
        """A necrotic tooth with no caries and no restoration is a different
        differential from a necrotic tooth with a deep filling, and the
        absence is the informative part."""
        assert "ABSENCES" in endo_ai.DIFFERENTIAL_PROMPT

    def test_it_refuses_a_differential_of_only_common_things(self):
        assert "uncommon cause" in endo_ai.DIFFERENTIAL_PROMPT


class TestTheDifferentialParser:

    def _stub(self, monkeypatch, text):
        class _C:
            def __init__(self, *a, **kw):
                pass

        def fake(client, function_name=None, **kw):
            class R:
                content = [type("T", (), {"text": text})()]
                usage = type("U", (), {"input_tokens": 1, "output_tokens": 1,
                                       "cache_creation_input_tokens": 0,
                                       "cache_read_input_tokens": 0})()
            return R()

        monkeypatch.setattr(endo_ai, "_invoke_claude", fake)
        monkeypatch.setattr(endo_ai.anthropic, "Anthropic", _C)
        monkeypatch.setattr(endo_ai, "_get_api_key", lambda: "test")
        monkeypatch.setattr(endo_ai, "log_llm_call", lambda *a, **kw: 0.0)

    ONE = json.dumps([{"candidate": "Dens invaginatus",
                       "supports": "caries-free maxillary lateral",
                       "against": "none",
                       "discriminator": "periapical radiograph",
                       "search_topic": "dens invaginatus pulp necrosis"}])

    def test_a_clean_array_parses(self, monkeypatch):
        self._stub(monkeypatch, self.ONE)
        got, _c = generate_case_differential(YOUNG_CASE)
        assert [c["candidate"] for c in got] == ["Dens invaginatus"]

    def test_a_prose_wrapper_still_parses(self, monkeypatch):
        """The JSON-only instruction is followed almost always, and "almost"
        is what put +/-50% noise under every eval number once."""
        self._stub(monkeypatch, "Here is the differential:\n" + self.ONE +
                   "\nHope that helps.")
        got, _c = generate_case_differential(YOUNG_CASE)
        assert len(got) == 1

    def test_a_fence_still_parses(self, monkeypatch):
        self._stub(monkeypatch, "```json\n" + self.ONE + "\n```")
        assert len(generate_case_differential(YOUNG_CASE)[0]) == 1

    def test_failure_returns_EMPTY_never_an_invented_differential(
            self, monkeypatch):
        """An empty differential falls back to the ordinary case path — the
        answer that shipped before this existed. A fabricated one would drive
        SIX retrievals from topics no clinician proposed."""
        self._stub(monkeypatch, "I could not determine a differential.")
        got, _c = generate_case_differential(YOUNG_CASE)
        assert got == []

    def test_it_is_capped(self, monkeypatch):
        many = json.dumps([{"candidate": f"cause {i}"} for i in range(20)])
        self._stub(monkeypatch, many)
        got, _c = generate_case_differential(YOUNG_CASE)
        assert len(got) == DIFFERENTIAL_MAX

    def test_a_nameless_candidate_is_dropped(self, monkeypatch):
        self._stub(monkeypatch, json.dumps(
            [{"candidate": "", "supports": "x"}, {"candidate": "Trauma"}]))
        got, _c = generate_case_differential(YOUNG_CASE)
        assert [c["candidate"] for c in got] == ["Trauma"]

    def test_search_topic_falls_back_to_the_candidate_name(self, monkeypatch):
        self._stub(monkeypatch, json.dumps([{"candidate": "Cracked tooth"}]))
        got, _c = generate_case_differential(YOUNG_CASE)
        assert got[0]["search_topic"] == "Cracked tooth"


class TestTheDiagnosticAnswerIsDifferentialFirst:

    def test_the_prompt_forbids_opening_with_management(self):
        f = _CASE_FORMAT_DIAGNOSTIC
        assert "Do not open with management" in f
        assert "The first thing on the page is the differential" in f

    def test_management_is_capped_and_comes_last(self):
        f = _CASE_FORMAT_DIAGNOSTIC
        assert "only after the differential" in f
        assert "longer than the differential" in f

    def test_a_candidate_with_no_literature_stays_in_the_list(self):
        """Dropping it would hide a cause worth considering behind the
        accident of what has been published. Saying so keeps the clinician's
        differential intact and keeps the claim unmarked, which is what the
        grounding rule wants."""
        f = _CASE_FORMAT_DIAGNOSTIC
        assert "keep the candidate in the list" in f
        assert "no paper in this evidence base addresses" in f

    def test_markers_are_not_invited_onto_the_case_reading_lines(self):
        """*Fits because* and *Argues against* are the model's reading of THIS
        case, not claims about a paper. A marker there asserts something no
        paper says — which is the exact failure `_GROUNDING_RULE` exists to
        prevent, arriving through a format instruction."""
        assert "Do NOT mark the" in endo_ai._MARKERS_DIAGNOSTIC

    def test_the_format_is_selected_by_the_differential_argument(self):
        src = inspect.getsource(endo_ai.ask_case_question)
        assert "_CASE_FORMAT_DIAGNOSTIC if diagnostic else _CASE_FORMAT_TREATMENT" \
            in src.replace("\n", " ").replace("        ", " ")

    def test_the_scaffold_is_labelled_as_revisable(self):
        """A differential the model cannot argue with is one the retrieval step
        has quietly made final, and the retrieval step never read the papers."""
        src = inspect.getsource(endo_ai.ask_case_question)
        assert "revise it against" in src


class TestTheUnionKeepsTheGates:

    def test_it_reuses_the_production_evidence_builder(self):
        """A second retrieval path is a second place for the quality floors,
        the retraction exclusions and the routing gate to be missing."""
        import app
        src = inspect.getsource(app.build_differential_evidence)
        assert "build_evidence_base_with_progress(" in src

    def test_it_reads_the_per_tier_cap_from_the_shared_config(self):
        import app
        src = inspect.getsource(app.build_differential_evidence)
        assert 'RELEVANCE_GATE["max_per_tier"]' in src, (
            "a cap copied rather than read would let the differential path "
            "drift from the single-query path with nothing saying so")

    def test_a_failed_candidate_does_not_sink_the_run(self):
        import app
        src = inspect.getsource(app.build_differential_evidence)
        assert "except Exception as e:" in src
        assert '"n_papers": 0' in src

    def test_an_empty_candidate_is_not_retried_or_broadened(self):
        """An empty result is information: it is the difference between "the
        literature disagrees" and "nobody has studied this in this
        presentation", and the answer has to be able to say which."""
        import app
        src = inspect.getsource(app.build_differential_evidence)
        assert "NOT retried and NOT broadened" in src

    def test_the_job_never_carries_the_evidence_base(self):
        """`case_convs` retained ~277 KB of annotated abstracts per
        client-supplied id. Invariant 13: abstract text never reaches a
        browser, and `_safe_papers` is the only enforcement point."""
        import app
        src = inspect.getsource(app.run_case_chat)
        assert "update_job(job_id, differential=" in src
        # Every update_job kwarg this function passes, checked by name. A
        # substring search for "_evidence" matches
        # `build_differential_evidence` and would pass forever.
        kwargs = set(re.findall(r"update_job\([^)]*?(\w+)\s*=", src, re.S))
        for call in re.finditer(r"update_job\((.*?)\)\n", src, re.S):
            kwargs |= set(re.findall(r"(\w+)\s*=", call.group(1)))
        assert not (kwargs & {"evidence", "_evidence", "context"}), (
            f"the evidence base is being published on the job dict again: "
            f"{sorted(kwargs)}")


# ── The follow-up relevance test ──────────────────────────

class TestFollowUpsFilterByRelevanceNotByTopic:
    """Measured, 15 samples per arm on the young case and 10 on the contrast
    case: a non-discriminating question in 8/15 runs before and 0/15 after,
    bisphosphonates 7/15 before and 0/15 after — while the SAME question is
    asked in 10/10 runs of the 68-year-old on alendronate. The topic was not
    deleted; the filter is by relevance."""

    def test_the_prompt_asks_whether_the_ANSWER_could_matter(self):
        p = endo_ai.CASE_FOLLOWUP_PROMPT
        assert "RELEVANCE TEST" in p
        assert "would change the differential or the plan" in p
        assert 'Not "is the fact missing"' in p

    def test_it_carries_both_the_worked_drop_and_the_worked_keep(self):
        """One worked example teaches "never ask about bisphosphonates". Two,
        with the same topic and different patients, teach the actual rule."""
        p = endo_ai.CASE_FOLLOWUP_PROMPT
        assert "Verdict: DROP." in p and "Verdict: KEEP." in p
        assert "Relevance is not a property of the topic" in p

    def test_the_facts_are_split_into_differential_and_plan(self):
        f = endo_ai._CASE_DECIDING_FACTS
        assert "FACTS THAT CHANGE THE DIFFERENTIAL" in f
        assert "FACTS THAT CHANGE THE PLAN" in f

    def test_the_differential_facts_name_what_was_never_asked(self):
        """Tooth identity, developmental anomaly, orthodontic history,
        discoloration and sinus tract were asked in 0 of 15 runs, because the
        checklist did not contain them."""
        f = endo_ai._CASE_DECIDING_FACTS.lower()
        for topic in ("which tooth", "developmental anomaly", "orthodontic",
                      "discoloration", "sinus tract", "crack"):
            assert topic in f, f"the deciding facts no longer name {topic!r}"

    def test_a_named_red_flag_makes_its_DETAIL_the_question(self):
        """"On alendronate" is not the answer — duration and route are. Without
        this the contrast case asked about the antiresorptive in only 2 runs
        of 10, because the drug was already named and so read as ticked."""
        assert "WHEN A RED FLAG IS ALREADY NAMED" in endo_ai._CASE_DECIDING_FACTS

    def test_the_never_re_ask_rule_survived(self):
        """Invariant 8. The relevance test is an addition, not a replacement."""
        p = endo_ai.CASE_FOLLOWUP_PROMPT
        assert "Never ask about anything the description states" in p


class TestTheFollowUpParserDoesNotFailSilent:
    """One contrast run in ten returned NO questions because the model emitted
    an unescaped quote and strict json.loads raised. Silence from a parse error
    is indistinguishable from "the description was sufficient" — bug class (d)
    arriving through a JSON delimiter."""

    def test_a_clean_array_parses(self):
        got = endo_ai._parse_question_array('["a question long enough to keep"]')
        assert got == ["a question long enough to keep"]

    def test_a_prose_wrapper_parses(self):
        got = endo_ai._parse_question_array(
            'Here you go:\n["a question long enough to keep"]\nthanks')
        assert got == ["a question long enough to keep"]

    def test_an_unescaped_quote_recovers_the_other_questions(self):
        raw = ('["Is there a "cracked tooth" sign on transillumination and '
               'does it reproduce pain?", "Was there any history of trauma to '
               'this tooth, and if so how long ago?"]')
        got = endo_ai._parse_question_array(raw)
        assert got, "a malformed array returned nothing at all"
        assert any("trauma" in q for q in got)

    def test_unparseable_returns_None_not_an_empty_list(self):
        """None and [] mean different things to the caller: [] is 'the
        description was sufficient', None is 'I could not read the reply'."""
        assert endo_ai._parse_question_array("complete gibberish") is None
        assert endo_ai._parse_question_array("") is None

    def test_the_GENERATOR_recovers_them_too(self, monkeypatch):
        """THE test. The three above prove the parser is tolerant; none of
        them proves `generate_case_followups` actually calls it — reverting
        the caller to `json.loads` left all three passing. Mutation-checked:
        this one fails, and it is the only one that does."""
        class _C:
            def __init__(self, *a, **kw):
                pass

        malformed = ('["Is there a "cracked tooth" sign on transillumination?", '
                     '"Was there any history of trauma to this tooth, and if '
                     'so how long ago?"]')

        def fake(client, function_name=None, **kw):
            class R:
                content = [type("T", (), {"text": malformed})()]
                usage = type("U", (), {"input_tokens": 1, "output_tokens": 1,
                                       "cache_creation_input_tokens": 0,
                                       "cache_read_input_tokens": 0})()
            return R()

        monkeypatch.setattr(endo_ai, "_invoke_claude", fake)
        monkeypatch.setattr(endo_ai.anthropic, "Anthropic", _C)
        monkeypatch.setattr(endo_ai, "_get_api_key", lambda: "test")
        monkeypatch.setattr(endo_ai, "log_llm_call", lambda *a, **kw: 0.0)

        got = endo_ai.generate_case_followups(YOUNG_CASE)
        assert got, ("a malformed reply produced NO questions — silence from a "
                     "parse error is indistinguishable from 'the description "
                     "was sufficient'")
        assert any("trauma" in q for q in got)


# ── Live, opt-in ──────────────────────────────────────────

pytestmark_live = pytest.mark.skipif(
    os.getenv("RUN_CASE_TESTS") != "1",
    reason="live case run; set RUN_CASE_TESTS=1")


@pytestmark_live
class TestTheReportedCaseEndToEnd:
    """The fixture is the reported case, verbatim. These are the assertions
    the eval case carries too; they live here as well so a change that breaks
    them fails the suite rather than waiting for an eval run."""

    @pytest.fixture(scope="class")
    def answered(self):
        import app as app_mod
        client = app_mod.app.test_client()
        r = client.post("/case_chat", json={
            "messages": [{"role": "user", "content": YOUNG_CASE}],
            "skip_clarify": True})
        assert r.status_code == 200, r.data
        job_id = r.get_json()["job_id"]
        import time
        for _ in range(900):
            st = client.get(f"/status/{job_id}").get_json()
            if st.get("status") in ("complete", "error", "aborted"):
                break
            time.sleep(2)
        assert st.get("status") == "complete", st.get("error")
        return st

    def test_the_turn_is_classified_diagnostic(self, answered):
        assert answered.get("case_intent") == CASE_INTENT_DIAGNOSTIC

    def test_a_differential_was_generated(self, answered):
        diff = answered.get("differential") or []
        assert DIFFERENTIAL_MIN <= len(diff) <= DIFFERENTIAL_MAX

    def test_dens_invaginatus_is_among_the_candidates(self, answered):
        blob = json.dumps(answered.get("differential") or []).lower()
        assert "invaginat" in blob, (
            "the differential for a caries-free necrotic tooth in a young "
            "adult omits the archetypal cause")

    def test_the_answer_leads_with_the_differential(self, answered):
        a = (answered.get("answer") or "").lower()
        first_diff = a.find("differential")
        first_mgmt = min([i for i in (a.find("root canal treatment"),
                                      a.find("endodontic treatment"))
                          if i >= 0] or [len(a)])
        assert 0 <= first_diff < first_mgmt, (
            "the answer reaches management before it names a differential")

    def test_no_bisphosphonate_follow_up(self):
        qs = endo_ai.generate_case_followups(YOUNG_CASE)
        blob = " ".join(qs).lower()
        assert not re.search(r"bisphosphonate|alendronate|antiresorptive",
                             blob), qs
