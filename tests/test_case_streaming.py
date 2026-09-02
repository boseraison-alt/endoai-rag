"""
Streaming, checks-after-display, and carried candidates on the case path
(`case-v3` Item E).

MEASURED FIRST (`scripts/measure_case_latency.py`, the DE two-turn fixture).
Before, all three timings on a turn were IDENTICAL, because nothing reached
the job record until the answer, both guardrails and the support check had all
finished:

  turn 2   first papers 56.6s   first text 56.6s   checks done 56.6s

After streaming:

  turn 2   first papers 11.1s   first text 14.4s   checks done 55.3s

The clinician starts reading at 14 s instead of 57 s, and the 41-second
guardrail tail happens underneath a readable answer instead of a spinner. Wall
time barely moved, which is the point: an answer that takes 55 s but is
readable at 14 s is a different product from one that shows nothing for 55 s,
and they have the same wall time.

THE GUARDRAIL INVARIANT is what these tests mostly exist to protect. Partial
text must never reach `validate_evidence_mapping` or `verify_citation_support`
— a half-written "[[PMID:312" reads as a fabrication — and it must never reach
`answer`, because the UI derives its trust chips from `answer` alone. Both are
asserted below, the same way `tests/test_streaming.py` asserts them for
Review.
"""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai
from endo_ai import case_prior_pmids


# ── the synthesiser's contract ────────────────────────────

# -- a streaming client and spied guardrails ---------------
#
# Modelled on `tests/test_streaming.py`'s `wired` fixture, which asserts the
# same invariant for the Review path. Everything here is offline: the SDK seam,
# both guardrails and the two log writers are stubbed, so what is being
# measured is the ORDER `ask_case_question` calls them in.

CASE_MD = ("**Assessment:** necrotic #20 in a 20-year-old, likely "
           "dens evaginatus [[PMID:111]].\n\n"
           "**Recommendation:** regenerative endodontics [[PMID:222]].\n")

SAW = []          # every string a guardrail was handed


class _Delta:
    def __init__(self, text):
        self.type, self.text = "text_delta", text


class _Event:
    def __init__(self, type_, delta=None):
        self.type, self.delta = type_, delta


class _Usage:
    input_tokens = 100
    output_tokens = 200


class _Message:
    def __init__(self, text):
        self.content = [type("B", (), {"text": text})()]
        self.usage = _Usage()


class _Stream:
    def __init__(self, text, chunk=2):
        # Small chunks on purpose: the cadence rule only publishes a
        # mid-stream partial once STREAM_PARTIAL_MIN_DELTAS deltas have
        # gone by, and a test with no truncated partial in it proves
        # nothing about what the guardrails were protected from.
        self._text = text
        self._chunks = [text[i:i + chunk] for i in range(0, len(text), chunk)]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        yield _Event("message_start")
        for c in self._chunks:
            yield _Event("content_block_delta", _Delta(c))
        yield _Event("message_stop")

    def get_final_message(self):
        return _Message(self._text)


class _Messages:
    def __init__(self, text):
        self.text = text

    def stream(self, **kw):
        return _Stream(self.text)

    def create(self, **kw):
        return _Message(self.text)


class _Client:
    def __init__(self, text=CASE_MD, **kw):
        self.messages = _Messages(text)


class TestAskCaseQuestionStreams:

    @pytest.fixture
    def wired(self, monkeypatch):
        """`ask_case_question` against the fake stream, recording the order in
        which the guardrails actually ran."""
        del SAW[:]
        order = []

        def fake_validate(answer, evidence):
            order.append("validate")
            SAW.append(answer)
            return {"passed": True, "score": 100, "cited_pmids": ["111", "222"],
                    "fabricated_pmids": [], "unattributed_claims": [],
                    "author_mentions": [], "gap_sections": [],
                    "recommendation": {"present": True, "traceable": True,
                                       "issues": []},
                    "failure_reason": ""}

        def fake_support(answer, evidence):
            order.append("support")
            SAW.append(answer)
            return {"cost": 0.0, "checked": 2, "flagged": [], "flags": []}

        monkeypatch.setattr(endo_ai.anthropic, "Anthropic",
                            lambda **kw: _Client())
        monkeypatch.setattr(endo_ai, "_get_api_key", lambda: "test-key")
        monkeypatch.setattr(endo_ai, "log_llm_call", lambda *a, **k: 0.0)
        monkeypatch.setattr(endo_ai, "_log_evidence_mapping", lambda *a, **k: None)
        monkeypatch.setattr(endo_ai, "_build_evidence_context", lambda ev: "CONTEXT")
        monkeypatch.setattr(endo_ai, "validate_evidence_mapping", fake_validate)
        monkeypatch.setattr(endo_ai, "verify_citation_support", fake_support)
        monkeypatch.setattr(endo_ai, "_append_support_warnings",
                            lambda answer, support: answer)
        return _Client, order

    def test_it_takes_the_same_three_callbacks_review_does(self):
        sig = inspect.signature(endo_ai.ask_case_question)
        for name in ("stream_cb", "abort_cb", "phase_cb"):
            assert name in sig.parameters, f"missing {name}"
            assert sig.parameters[name].default is None, (
                f"{name} must default to None so every existing caller is "
                f"unchanged")

    def test_the_answer_is_read_off_the_final_message(self):
        """Not off the accumulated stream chunks, and not off anything
        `stream_cb` was handed."""
        src = inspect.getsource(endo_ai.ask_case_question)
        assert "answer = resp.content[0].text" in src

    def test_the_validator_runs_after_the_phase_callback(self, wired):
        """BEHAVIOURAL, not a source-order check.

        The first version of this test compared `src.index(...)` positions,
        and a mutant that replaced `if phase_cb is not None:` with `if False:`
        passed it -- the call still appeared in the source, above the
        validator, and never ran. Reading the source can prove the code is
        WRITTEN; only running it proves the code EXECUTES.

        `phase_cb` fires when the model stops writing and the guardrails have
        NOT run. If it fired after them, the chips would claim to be checking
        for a window in which nothing was being checked, and would show
        nothing at all for the window in which everything was.
        """
        _client, order = wired
        endo_ai.ask_case_question(
            [{"role": "user", "content": "a case"}], {"_summary": {}},
            stream_cb=lambda _t: None,
            phase_cb=lambda _label: order.append("phase"))

        assert "phase" in order, "phase_cb never fired"
        assert order.index("phase") < order.index("validate"), (
            f"the guardrails ran before the phase callback: {order}")

    def test_the_guardrails_see_the_finished_text_exactly_once(self, wired):
        """THE GUARDRAIL INVARIANT, run rather than read. A half-written
        "[[PMID:312" reads as a fabrication and would warn the clinician about
        a perfectly good answer."""
        _client, order = wired
        partials = []
        answer, _cost = endo_ai.ask_case_question(
            [{"role": "user", "content": "a case"}], {"_summary": {}},
            stream_cb=partials.append)

        assert partials, "nothing was streamed"
        truncated = [p for p in partials if p != answer]
        assert truncated, "fixture produced no partial to test against"
        assert order.count("validate") == 1, f"validator ran {order.count('validate')}x"
        assert order.count("support") == 1
        for seen_by_guard in SAW:
            assert seen_by_guard == answer, (
                "a guardrail was handed something other than the final answer")

    def test_a_throwing_stream_cb_does_not_fail_the_answer(self):
        src = inspect.getsource(endo_ai.ask_case_question)
        block = src[src.index("def _publish_partial"):][:400]
        assert "except Exception" in block

    def test_an_abort_skips_the_guardrail_calls(self):
        """Cancelled mid-stream must not spend two more LLM calls validating
        an answer nobody will read."""
        src = inspect.getsource(endo_ai.ask_case_question)
        assert src.index("raise StreamAborted()") < \
            src.index("result = validate_evidence_mapping(answer, evidence)")

    def test_streaming_is_off_when_no_callback_is_given(self):
        """Every existing caller — the eval harness, the capture scripts —
        passes nothing and must keep the non-streaming path."""
        src = inspect.getsource(endo_ai.ask_case_question)
        assert '"stream":     stream_cb is not None' in src


class TestComparisonModeDropsStreaming:
    """`tier2_invoke` can run two models concurrently. Streaming both into one
    callback would interleave them into nonsense, so the debug mode drops the
    kwargs rather than every caller having to know which mode it is in."""

    def test_the_comparison_path_strips_the_stream_kwargs(self):
        src = inspect.getsource(endo_ai.tier2_invoke)
        head, tail = src.split("if not LOG_TIER2_COMPARISON:", 1)
        assert 'create_kwargs.pop(_k, None)' in tail
        assert '"stream", "on_partial"' in tail


# ── the job record ────────────────────────────────────────

class TestTheJobRecordNeverShowsUncheckedTextAsAnswer:

    def _src(self):
        import app
        return inspect.getsource(app.run_case_chat)

    def test_partials_go_to_partial_answer_never_to_answer(self):
        src = self._src()
        block = src[src.index("def _on_partial"):][:600]
        assert "partial_answer = text" in block
        assert "answer   =" not in block and "answer=" not in block

    def test_checks_status_stays_pending_while_streaming(self):
        src = self._src()
        block = src[src.index("def _on_partial"):][:600]
        assert 'checks_status  = "pending"' in block

    def test_the_phase_callback_stops_streaming_but_not_the_checks(self):
        src = self._src()
        block = src[src.index("def _on_phase"):][:400]
        assert "streaming=False" in block
        assert 'checks_status="pending"' in block

    def test_completion_clears_the_partial_and_marks_checks_complete(self):
        """Once a CHECKED answer exists, nothing downstream may read the
        unchecked text."""
        src = self._src()
        tail = src[src.index('status   = "complete"'):][:700]
        assert 'partial_answer = ""' in tail
        assert 'checks_status  = "complete"' in tail

    def test_papers_are_published_before_synthesis(self):
        """So the [[PMID:N]] pills rendered mid-stream resolve to author names
        rather than bare numbers."""
        src = self._src()
        assert src.index("papers    = evidence.get") < \
            src.index("ask_case_question(")

    def test_an_abort_mid_stream_clears_the_partial(self):
        src = self._src()
        tail = src[src.index("except StreamAborted:"):][:400]
        assert 'status="aborted"' in tail
        assert 'partial_answer=""' in tail


# ── carried candidates ────────────────────────────────────

class TestCasePriorPmids:
    """A follow-up rebuilt its evidence base from scratch, so the papers the
    clinician had just been reading about were re-found or not depending on
    how the combined query embedded. These SEED retrieval; they never bypass
    it."""

    MSGS = [
        {"role": "user", "content": "necrotic tooth #20, what is the cause?"},
        {"role": "assistant", "content": "Dens evaginatus [[PMID:111]] and "
                                         "trauma [[PMID:222]], see also "
                                         "[[PMID:111]] again."},
        {"role": "user", "content": "what about [[PMID:999]] though?"},
    ]

    def test_it_collects_the_assistants_citations(self):
        assert case_prior_pmids(self.MSGS) == ["111", "222"]

    def test_a_pmid_the_CLINICIAN_typed_is_not_carried(self):
        """It is not something this system retrieved, so it has no provenance
        here and must go through retrieval like anything else."""
        assert "999" not in case_prior_pmids(self.MSGS)

    def test_duplicates_collapse(self):
        assert case_prior_pmids(self.MSGS).count("111") == 1

    def test_newest_turn_first(self):
        msgs = [
            {"role": "assistant", "content": "old [[PMID:1]]"},
            {"role": "assistant", "content": "new [[PMID:2]]"},
        ]
        assert case_prior_pmids(msgs)[0] == "2"

    def test_a_first_turn_carries_nothing(self):
        assert case_prior_pmids([{"role": "user", "content": "a case"}]) == []

    def test_empty_input_is_safe(self):
        assert case_prior_pmids([]) == []
        assert case_prior_pmids(None) == []


class TestTheSeedsReachBothRetrievalPaths:

    def test_a_first_turn_seeds_nothing(self):
        import app
        src = inspect.getsource(app.run_case_chat)
        assert "case_prior_pmids(messages) if is_followup else []" in src

    def test_the_treatment_path_passes_them(self):
        import app
        src = inspect.getsource(app.run_case_chat)
        import re
        assert re.search(r"build_evidence_base_with_progress\(\s*\n?\s*job_id, "
                         r"search_q, mode=\"case\", prior_pmids=prior_pmids\)", src)

    def test_the_differential_path_passes_them_to_every_candidate(self):
        """A carried paper is judged against each candidate's own query, so it
        enters through whichever candidate it is actually relevant to. The
        union dedupes by pmid."""
        import app
        src = inspect.getsource(app.build_differential_evidence)
        assert "prior_pmids=prior_pmids" in src

    def test_it_is_NOT_a_cache(self):
        """Only the candidate SET carries over. Caching a turn-1 evidence base
        and serving it at turn 3 is the mistake `case_convs` made, and it
        would answer the follow-up from the wrong literature."""
        import app
        src = inspect.getsource(app.run_case_chat)
        assert "NOT a cache" in src
        # The evidence base is still rebuilt every turn.
        assert src.count("build_evidence_base_with_progress(") >= 1
        assert "build_differential_evidence(" in src

    def test_the_seeding_still_happens_after_the_routing_gate(self):
        """The safety property, inherited from Review and asserted there end
        to end by TestSeedsDoNotDecideTheRoute. Seeding before the gate would
        let papers carried from the previous turn push a thin topic onto the
        library route — context substituting for retrieval."""
        import app
        src = inspect.getsource(app.build_evidence_base_with_progress)
        gate = src.index("library_covers_question = (")
        seed = src.index("if prior_pmids:")
        assert gate < seed
