"""
A20 — Literature answers; it does not interview.

RB: "no need to ask questions back when a lit review question is asked."

WHAT WAS ACTUALLY WRONG, measured before changing anything. The review path
could put a question to the clinician in exactly one place, and it was not the
one the item guessed at:

  * the answer BODY was already clean. The synthesis prompt has forbidden
    ending on a question since `trust-surface-v1`, and 0 of 10 stored review
    answers contain a question addressed to the clinician.
  * the CLARIFY GATE in `/ask` was the interviewer. It ran before any
    retrieval and returned `{"needs_clarification": true, "questions": [...]}`,
    which the page rendered as a form the clinician had to answer or skip.
    Three of eleven cached rows still carry the answered block in their
    question text.
  * `/clarify` is a dead route — nothing calls it — and the router's own
    `needs_clarify` field is logged and never acted on. Neither needed
    touching, and neither is what was asking.

The gate is also NOT review-only, which A20's premise assumed. It fires for
`learn` too. Curriculum therefore keeps it here, deliberately: that is a
separate decision for RB rather than a side effect of this one, and
`test_curriculum_still_asks` pins the asymmetry so it cannot drift silently.

Case keeps its questions because there the question is the work — a different
generator (`generate_case_followups`), a different route, a different handler.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

ROOT = Path(__file__).parent.parent


@pytest.fixture
def client(monkeypatch):
    """A test client whose clarify generators BOTH want to ask something.

    That is the point: the gate is stubbed to be maximally chatty, so a route
    that still consults it cannot pass by accident."""
    import app as app_mod
    import endo_ai

    calls = {"review": 0, "case": 0}

    def fake_clarify(question, context_block=""):
        calls["review"] += 1
        return ["Which tooth?", "Vital or necrotic?"]

    def fake_case(question):
        calls["case"] += 1
        return ["How long has it hurt?"]

    monkeypatch.setattr(app_mod, "generate_clarifying_questions", fake_clarify)
    monkeypatch.setattr(endo_ai, "generate_case_followups", fake_case,
                        raising=False)
    # The answer itself is not under test here; nothing must reach the network.
    monkeypatch.setattr(app_mod, "run_question", lambda *a, **k: None)
    monkeypatch.setattr(app_mod, "run_case_chat", lambda *a, **k: None,
                        raising=False)

    app_mod.app.config["TESTING"] = True
    c = app_mod.app.test_client()
    c._clarify_calls = calls
    return c


class TestLiteratureNeverAsks:

    def test_a_literature_question_is_answered_not_interviewed(self, client):
        r = client.post("/ask", json={"question": "MTA versus calcium hydroxide"
                                                  " in vital pulp therapy",
                                      "mode": "review"})
        assert r.status_code == 200
        body = r.get_json()
        assert "needs_clarification" not in body, body
        assert body.get("job_id"), "the question was not answered at all"

    def test_the_generator_is_not_even_consulted(self, client):
        """Stronger than "no questions came back". A route that still asked the
        generator and then dropped its answer would be one refactor away from
        showing them again, and would still be paying Haiku to write them."""
        client.post("/ask", json={"question": "Bioceramic versus epoxy resin"
                                              " sealers", "mode": "review"})
        assert client._clarify_calls["review"] == 0

    def test_an_ambiguous_question_is_still_answered(self, client):
        """A20c — the reply to ambiguity is an assumption, not an interview.
        "Is it worth it?" is about as under-specified as a literature question
        gets and it still has to come back with an answer."""
        r = client.post("/ask", json={"question": "Is it worth it?",
                                      "mode": "review"})
        assert "needs_clarification" not in r.get_json()

    def test_curriculum_still_asks(self, client):
        """Deliberate asymmetry, pinned. A20's premise was that Curriculum
        asks none; measured, it does. Turning that off is RB's call, and this
        test is what will fail loudly when someone makes it."""
        r = client.post("/ask", json={"question": "Anesthesia for endodontics",
                                      "mode": "learn"})
        assert r.get_json().get("needs_clarification") is True
        assert client._clarify_calls["review"] == 1

    def test_the_case_path_is_untouched(self, client):
        """A20b — do not touch the case relevance gate. There the question IS
        the work: a differential the clinician has not been asked about is
        worth less than one turn of conversation."""
        r = client.post("/case_chat", json={
            "messages": [{"role": "user",
                          "content": "20-year-old, necrotic 45, buccal sinus tract"}]})
        assert r.get_json().get("needs_clarification") is True
        assert client._clarify_calls["case"] == 1


class TestTheAnswerBodyAsksNothing:
    """The other half. The gate decides whether the clinician is interrupted
    BEFORE the answer; this is the answer itself."""

    def _system_prompt(self, monkeypatch):
        """The prompt `ask_clinical_question` actually sends, captured off the
        call — not the function's source, which carries a docstring restating
        the same rules and would survive a mutant that deleted them."""
        import endo_ai
        seen = {}

        class _R:
            content = [type("T", (), {"text": "ok"})()]
            usage = type("U", (), {"input_tokens": 1, "output_tokens": 1,
                                   "cache_creation_input_tokens": 0,
                                   "cache_read_input_tokens": 0})()

        def fake_invoke(client_, function_name="", **kw):
            seen["system"] = kw.get("system", "")
            return _R()

        monkeypatch.setattr(endo_ai, "_invoke_claude", fake_invoke)
        monkeypatch.setattr(endo_ai, "log_llm_call", lambda *a, **k: 0.0)
        monkeypatch.setattr(endo_ai, "_get_api_key", lambda: "test-key")
        monkeypatch.setattr(endo_ai.anthropic, "Anthropic",
                            lambda **kw: object())
        try:
            endo_ai.ask_clinical_question("Single visit versus two visits?",
                                          {"cochrane": [], "level1": []})
        except Exception:
            # Everything downstream of the call (validators, cache, audit) is
            # someone else's test. All this needs is the prompt that went out.
            pass
        assert "system" in seen, "ask_clinical_question never called the model"
        return seen["system"]

    def test_the_model_is_told_not_to_ask(self, monkeypatch):
        p = self._system_prompt(monkeypatch)
        assert "NEVER end your response with a question" in p
        assert "NEVER ask the clinician for more information" in p

    def test_the_model_is_told_to_declare_the_assumption_instead(self, monkeypatch):
        """A20c. Forbidding the question without offering the alternative is
        how you get an answer that silently picks a reading and never says
        which — worse than the interview, because it is invisible."""
        p = self._system_prompt(monkeypatch)
        assert "Assumed:" in p
        assert "answer the most reasonable reading" in p

    def test_the_placeholder_is_substituted(self, monkeypatch):
        """The rule is spliced in like __GROUNDING_RULE__ and __SCORE_WEIGHTS__.
        A missing `.replace` would ship the literal token to the model, which
        reads as an instruction to nobody."""
        p = self._system_prompt(monkeypatch)
        assert "__NO_QUESTIONS_RULE__" not in p

    @pytest.mark.parametrize("fixture", [
        "eval/fixtures/review_apixaban_apicectomy.md",
        "eval/fixtures/review_retreatment_visits.md",
    ])
    def test_no_shipped_review_answer_asks_the_clinician_anything(self, fixture):
        """The rule, checked against real output rather than against itself.
        A question mark alone is not the test — a paper title may carry one —
        so this looks for an interrogative aimed at the reader."""
        text = (ROOT / fixture).read_text(encoding="utf-8")
        # The export HEADER is not the answer. On the retreatment fixture it
        # echoes the clarify gate's own interrogation back at the reader —
        # captured before A20, and left alone deliberately, because a fixture
        # is a before-state. What A20 is about is the prose the model wrote.
        body = text.split("=" * 60)[-1]
        addressed = re.compile(
            r"\b(you|your|please|could you|would you|do you|have you)\b", re.I)
        asked = [s.strip() for s in re.findall(r"[^.!?\n]*\?", body)
                 if addressed.search(s)]
        assert not asked, "the answer puts a question to the clinician: %r" % asked[:3]

    def test_no_clarification_block_is_appended_to_a_review_question(self, monkeypatch):
        """That header exists because the gate asked and the clinician
        answered: `/ask` then glued the Q&A onto the question, and it
        travelled into the stored title (A15f.1) and into the export header.
        With the gate off there is nothing to glue on."""
        import time

        import app as app_mod
        seen = {}
        monkeypatch.setattr(app_mod, "run_question",
                            lambda job_id, q, mode, **k: seen.update(q=q, mode=mode))
        monkeypatch.setattr(app_mod, "generate_clarifying_questions",
                            lambda *a, **k: ["Which tooth?"])
        app_mod.app.config["TESTING"] = True
        c = app_mod.app.test_client()
        q = "retreatment in one visit versus two visits in endodontics"
        c.post("/ask", json={"question": q, "mode": "review"})
        for _ in range(50):
            if seen:
                break
            time.sleep(0.02)
        assert seen.get("q") == q, seen
        assert "Additional clinical context" not in seen.get("q", "")
