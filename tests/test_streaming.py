"""WORKLIST B4 — streaming the clinical answer.

What these tests are actually defending:

1. Partial markdown reaches the job record while the model is still writing,
   at a throttled cadence rather than once per token.
2. The guardrails (`validate_evidence_mapping`, `verify_citation_support`) see
   the COMPLETE text exactly once. A half-streamed `[[PMID:312` would read as
   a fabricated citation and produce a false warning about a good answer.
3. The header chips never report a pass state for text nobody has checked.
   That is bug class (d) in its worst form — not a check that fails open and
   shows nothing, but a check that has not run and shows a tick.
4. Abort stops a streaming job promptly instead of paying out the whole
   completion.

The chip tests run the REAL JavaScript out of `templates/index.html` under
node, because the honesty rule lives in that function and asserting on a
Python re-implementation of it would prove nothing.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import endo_ai  # noqa: E402


# ── Fake Anthropic streaming client ───────────────────────

ANSWER_MD = """## CLINICAL RECOMMENDATION

Based on Level I evidence, MTA and Biodentine perform comparably for full
pulpotomy in mature permanent teeth [[PMID:31543236]].

---

## EVIDENCE SUMMARY

**Level I — RCTs and Systematic Reviews**

Two randomised trials report equivalent success at 24 months
[[PMID:31543236]] [[PMID:34234567]].

---

## REFERENCES

1. [PMID: 31543236] Smith AB et al. — MTA vs Biodentine. J Endod, 2020.
2. [PMID: 34234567] Jones CD et al. — Pulpotomy outcomes. Int Endod J, 2021.
"""


class FakeUsage:
    input_tokens = 100
    output_tokens = 200


class FakeBlock:
    def __init__(self, text):
        self.text = text


class FakeMessage:
    def __init__(self, text):
        self.content = [FakeBlock(text)]
        self.usage = FakeUsage()


class _Delta:
    def __init__(self, text):
        self.type = "text_delta"
        self.text = text


class _Event:
    def __init__(self, type_, delta=None):
        self.type = type_
        self.delta = delta


def _tokenise(text, size=8):
    return [text[i:i + size] for i in range(0, len(text), size)]


class FakeStream:
    """Mimics the SDK's MessageStreamManager well enough for the helper.

    `delay` is per event, so a test can make the stream slow enough for the
    interval branch of the cadence rule to fire, or fast enough for the
    delta-count branch.
    """

    def __init__(self, text, chunk=8, delay=0.0, recorder=None):
        self._text = text
        self._chunks = _tokenise(text, chunk)
        self._delay = delay
        self.closed = False
        self.events_consumed = 0
        self.recorder = recorder

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False

    def __iter__(self):
        # A message_start with no delta first — the helper must skip it.
        yield _Event("message_start")
        for c in self._chunks:
            if self._delay:
                time.sleep(self._delay)
            self.events_consumed += 1
            yield _Event("content_block_delta", _Delta(c))
        yield _Event("message_stop")

    def get_final_message(self):
        return FakeMessage(self._text)


class FakeMessages:
    def __init__(self, text, chunk=8, delay=0.0):
        self.text = text
        self.chunk = chunk
        self.delay = delay
        self.streams = []
        self.create_calls = []

    def stream(self, **kwargs):
        s = FakeStream(self.text, self.chunk, self.delay)
        s.kwargs = kwargs
        self.streams.append(s)
        return s

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return FakeMessage(self.text)


class FakeClient:
    def __init__(self, text=ANSWER_MD, chunk=8, delay=0.0):
        self.messages = FakeMessages(text, chunk, delay)


# ── 1. Partial updates, at a throttled cadence ────────────

class TestPartialsArriveThrottled:

    def test_partials_are_prefixes_of_the_final_text(self):
        client = FakeClient()
        seen = []
        msg = endo_ai._invoke_claude(
            client, function_name="t", stream=True, on_partial=seen.append,
            model="m", max_tokens=10, messages=[])

        assert msg.content[0].text == ANSWER_MD
        assert seen, "no partial was ever published"
        for p in seen:
            assert ANSWER_MD.startswith(p), "a partial was not a prefix of the answer"
        assert seen == sorted(seen, key=len), "partials went backwards"
        assert seen[-1] == ANSWER_MD, "the tail of the stream was never flushed"

    def test_publishes_far_less_often_than_once_per_delta(self):
        """The /status endpoint is polled; a job write per token floods it."""
        client = FakeClient(chunk=1)          # one char per delta — many events
        seen = []
        endo_ai._invoke_claude(
            client, function_name="t", stream=True, on_partial=seen.append,
            model="m", max_tokens=10, messages=[])

        deltas = len(ANSWER_MD)
        assert deltas > 400, "fixture too small to prove throttling"
        # Fast local stream: the delta-count branch governs. Allow the interval
        # branch to add a few extra publishes on a slow machine.
        assert len(seen) <= deltas / (endo_ai.STREAM_PARTIAL_MIN_DELTAS / 2), (
            f"published {len(seen)} times for {deltas} deltas — cadence is not throttled")

    def test_slow_stream_still_publishes_on_the_interval(self):
        """A model that emits fewer than 40 deltas must still show something."""
        short = "## CLINICAL RECOMMENDATION\n\nShort answer.\n"
        client = FakeClient(text=short, chunk=len(short) // 3 + 1, delay=0.30)
        seen = []
        endo_ai._invoke_claude(
            client, function_name="t", stream=True, on_partial=seen.append,
            model="m", max_tokens=10, messages=[])
        assert len(seen) >= 2, (
            "a slow stream published only at the end — the interval branch is dead")

    def test_no_callback_is_harmless(self):
        client = FakeClient()
        msg = endo_ai._invoke_claude(
            client, function_name="t", stream=True, model="m", max_tokens=10, messages=[])
        assert msg.content[0].text == ANSWER_MD


class TestTheSeamHoldsOffline:
    """`_invoke_claude` is the ONLY place this module talks to Anthropic.

    Streaming was originally added as a second entry point that called
    `client.messages.stream()` directly, which silently took the synthesis path
    out from under every test that stubs `_invoke_claude` — the offline suite
    started making real 401'ing API calls. These two tests pin the seam.
    """

    def test_no_network_escapes_when_the_seam_is_stubbed(self, monkeypatch):
        class ExplodingClient:
            class messages:
                @staticmethod
                def create(**kw):
                    raise AssertionError("client.messages.create escaped the seam")

                @staticmethod
                def stream(**kw):
                    raise AssertionError("client.messages.stream escaped the seam")

        monkeypatch.setattr(endo_ai.anthropic, "Anthropic", lambda **kw: ExplodingClient())
        monkeypatch.setattr(endo_ai, "_get_api_key", lambda: "test-key")
        monkeypatch.setattr(endo_ai, "log_llm_call", lambda *a, **k: 0.0)
        monkeypatch.setattr(endo_ai, "_log_evidence_mapping", lambda *a, **k: None)
        monkeypatch.setattr(endo_ai, "_build_evidence_context", lambda ev: "CONTEXT")
        monkeypatch.setattr(endo_ai, "validate_evidence_mapping",
                            lambda a, e: {"passed": True, "score": 100, "cited_pmids": [],
                                          "fabricated_pmids": [], "unattributed_claims": [],
                                          "gap_sections": [], "failure_reason": ""})
        monkeypatch.setattr(endo_ai, "verify_citation_support",
                            lambda a, e: {"cost": 0.0, "flagged": []})
        monkeypatch.setattr(endo_ai, "_append_support_warnings", lambda a, s: a)

        # The one stub the offline suites install.
        monkeypatch.setattr(endo_ai, "_invoke_claude",
                            lambda client, **kw: FakeMessage(ANSWER_MD))

        answer, _cost = endo_ai.ask_clinical_question("q", {"_summary": {}})
        assert answer == ANSWER_MD

    def test_the_module_never_calls_the_sdk_outside_the_seam(self):
        """Static guard: a future edit that reaches for messages.stream/create
        somewhere else re-opens the hole the test above closes."""
        src = (Path(__file__).parent.parent / "endo_ai.py").read_text(encoding="utf-8")
        # Real call sites forward **kwargs; prose mentions do not.
        hits = [(n, line.strip()) for n, line in enumerate(src.split("\n"), 1)
                if re.search(r"\bclient\.messages\.(create|stream)\s*\(\s*\*\*", line)]
        assert len(hits) == 2, f"expected exactly 2 SDK call sites, found: {hits}"
        for _n, line in hits:
            assert line.startswith("return client.messages.create") or \
                   line.startswith("with client.messages.stream"), line


# ── 2. Guardrails see the complete text, once ─────────────

class TestGuardrailsOnlySeeCompleteText:

    @pytest.fixture
    def wired(self, monkeypatch):
        """ask_clinical_question with a streaming client and spied guardrails."""
        client = FakeClient()
        monkeypatch.setattr(endo_ai.anthropic, "Anthropic", lambda **kw: client)
        monkeypatch.setattr(endo_ai, "_get_api_key", lambda: "test-key")
        monkeypatch.setattr(endo_ai, "log_llm_call", lambda *a, **k: 0.0)
        monkeypatch.setattr(endo_ai, "_log_evidence_mapping", lambda *a, **k: None)
        monkeypatch.setattr(endo_ai, "_build_evidence_context", lambda ev: "CONTEXT")

        validator_calls = []
        support_calls = []

        def fake_validate(answer, evidence):
            validator_calls.append(answer)
            return {"passed": True, "score": 100, "cited_pmids": [],
                    "fabricated_pmids": [], "unattributed_claims": [],
                    "gap_sections": [], "failure_reason": ""}

        def fake_support(answer, evidence):
            support_calls.append(answer)
            return {"cost": 0.0, "checked": 2, "flagged": []}

        monkeypatch.setattr(endo_ai, "validate_evidence_mapping", fake_validate)
        monkeypatch.setattr(endo_ai, "verify_citation_support", fake_support)
        monkeypatch.setattr(endo_ai, "_append_support_warnings",
                            lambda answer, support: answer + "\n\n---\n\n> ✓ **Citation support: verified**")
        return client, validator_calls, support_calls

    def test_validator_called_exactly_once_with_the_full_string(self, wired):
        _client, validator_calls, _support = wired
        partials = []
        answer, _cost = endo_ai.ask_clinical_question(
            "q", {"_summary": {}}, stream_cb=partials.append)

        assert len(validator_calls) == 1, (
            f"validate_evidence_mapping ran {len(validator_calls)} times — "
            "it must run once, on the finished answer")
        assert validator_calls[0] == ANSWER_MD
        assert answer.startswith(ANSWER_MD)

    def test_support_check_called_exactly_once_with_the_full_string(self, wired):
        _client, _validator, support_calls = wired
        endo_ai.ask_clinical_question("q", {"_summary": {}}, stream_cb=lambda t: None)
        assert len(support_calls) == 1
        assert support_calls[0] == ANSWER_MD

    def test_no_guardrail_ever_sees_a_partial(self, wired):
        """The failure this prevents: a truncated [[PMID: reading as a
        fabrication and warning the clinician about a good answer."""
        _client, validator_calls, support_calls = wired
        partials = []
        endo_ai.ask_clinical_question("q", {"_summary": {}}, stream_cb=partials.append)

        truncated = [p for p in partials if p != ANSWER_MD]
        assert truncated, "fixture produced no truncated partial to test against"
        for seen_by_guard in validator_calls + support_calls:
            assert seen_by_guard not in truncated, (
                "a guardrail was handed partial markdown")

    def test_stream_cb_never_sees_guardrail_output(self, wired):
        """The reverse direction: the appended citation-support blockquote must
        not leak into the streamed text, or the chip logic would parse a
        pass marker out of an unchecked partial."""
        partials = []
        answer, _ = endo_ai.ask_clinical_question(
            "q", {"_summary": {}}, stream_cb=partials.append)
        assert "Citation support" in answer
        for p in partials:
            assert "Citation support" not in p

    def test_phase_callback_fires_before_the_guardrails(self, wired):
        _client, validator_calls, _s = wired
        order = []
        monkey_partials = []

        def phase(label):
            order.append(("phase", label, len(validator_calls)))

        endo_ai.ask_clinical_question("q", {"_summary": {}},
                                      stream_cb=monkey_partials.append,
                                      phase_cb=phase)
        assert order and order[0][1] == "checking"
        assert order[0][2] == 0, "phase_cb fired after validation had already run"

    def test_a_failing_stream_cb_does_not_fail_the_answer(self, wired):
        def boom(_text):
            raise ValueError("UI went away")
        answer, _ = endo_ai.ask_clinical_question(
            "q", {"_summary": {}}, stream_cb=boom)
        assert answer.startswith(ANSWER_MD)


# ── 3. Abort stops a streaming job ────────────────────────

class TestAbortStopsTheStream:

    def test_abort_raises_and_closes_the_stream_early(self):
        client = FakeClient(chunk=4)
        calls = {"n": 0}

        def abort_cb():
            calls["n"] += 1
            return calls["n"] > 3      # true from the 4th event onwards

        with pytest.raises(endo_ai.StreamAborted):
            endo_ai._invoke_claude(
                client, function_name="t", stream=True, abort_cb=abort_cb,
                model="m", max_tokens=10, messages=[])

        stream = client.messages.streams[0]
        assert stream.closed, "the stream context manager was not exited"
        assert stream.events_consumed < len(_tokenise(ANSWER_MD, 4)), (
            "the whole completion was consumed after abort — abort is not prompt")

    def test_stream_aborted_is_a_runtime_error_saying_cancelled(self):
        """Existing handlers match on RuntimeError + 'Cancelled'."""
        err = endo_ai.StreamAborted()
        assert isinstance(err, RuntimeError)
        assert "Cancelled" in str(err)

    def test_abort_after_the_stream_skips_the_guardrail_calls(self, monkeypatch):
        client = FakeClient()
        monkeypatch.setattr(endo_ai.anthropic, "Anthropic", lambda **kw: client)
        monkeypatch.setattr(endo_ai, "_get_api_key", lambda: "test-key")
        monkeypatch.setattr(endo_ai, "log_llm_call", lambda *a, **k: 0.0)
        monkeypatch.setattr(endo_ai, "_build_evidence_context", lambda ev: "CONTEXT")

        seen = []
        monkeypatch.setattr(endo_ai, "validate_evidence_mapping",
                            lambda a, e: seen.append(a) or {"passed": True})
        # abort goes true only once the stream is finished
        state = {"done": False}

        def abort_cb():
            return state["done"]

        def mark_done(_t):
            if _t == ANSWER_MD:
                state["done"] = True

        with pytest.raises(endo_ai.StreamAborted):
            endo_ai.ask_clinical_question("q", {"_summary": {}},
                                          stream_cb=mark_done, abort_cb=abort_cb)
        assert seen == [], "guardrails ran on an aborted job"


# ── 4. The job record, end to end through Flask ───────────

@pytest.fixture
def flask_client(monkeypatch):
    import rag
    import app as app_mod

    fake = FakeClient(chunk=6, delay=0.02)   # ~3 s of stream
    monkeypatch.setattr(endo_ai.anthropic, "Anthropic", lambda **kw: fake)
    monkeypatch.setattr(endo_ai, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(endo_ai, "log_llm_call", lambda *a, **k: 0.0)
    monkeypatch.setattr(endo_ai, "_log_evidence_mapping", lambda *a, **k: None)
    monkeypatch.setattr(endo_ai, "_build_evidence_context", lambda ev: "CONTEXT")
    monkeypatch.setattr(endo_ai, "validate_evidence_mapping",
                        lambda a, e: {"passed": True, "score": 100, "cited_pmids": [],
                                      "fabricated_pmids": [], "unattributed_claims": [],
                                      "gap_sections": [], "failure_reason": ""})
    monkeypatch.setattr(endo_ai, "verify_citation_support",
                        lambda a, e: {"cost": 0.0, "checked": 2, "flagged": []})
    monkeypatch.setattr(endo_ai, "_append_support_warnings",
                        lambda a, s: a + "\n\n---\n\n> ✓ **Citation support: verified** for the 2 cited claims")

    monkeypatch.setattr(app_mod, "get_cached_answer", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(app_mod, "save_query_cache", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(app_mod, "save_answer", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(app_mod, "write_citation_audit", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(app_mod, "classify_question_intent",
                        lambda q: {"kind": "standard", "needs_clarify": False,
                                   "retrieval": "local", "reason": "x", "cost": 0.0},
                        raising=False)
    monkeypatch.setattr(app_mod, "build_evidence_base_with_progress",
                        lambda job_id, question, **kw: {
                            "_summary": {"all_scored": [
                                {"pmid": "31543236", "score": 88, "level_key": "level1",
                                 "authors": "Smith AB", "journal": "J Endod", "year": "2020"}]}},
                        raising=False)
    monkeypatch.setattr(rag, "embed", lambda text: [0.01] * 384, raising=False)

    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client(), app_mod


def _poll_until(client, job_id, pred, timeout=25.0, interval=0.05):
    samples = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = client.get(f"/status/{job_id}").get_json()
        samples.append(s)
        if pred(s):
            return samples
        time.sleep(interval)
    return samples


class TestJobRecordDuringStreaming:

    def test_partial_answer_reaches_the_job_record(self, flask_client):
        client, _app = flask_client
        r = client.post("/ask", json={"question": "MTA versus Biodentine?",
                                      "mode": "review", "skip_clarify": True})
        job_id = r.get_json()["job_id"]

        samples = _poll_until(client, job_id,
                              lambda s: s.get("status") in ("complete", "error"))
        streaming = [s for s in samples if s.get("partial_answer")]
        assert streaming, "no partial_answer was ever visible on /status"
        assert samples[-1]["status"] == "complete", samples[-1].get("error")
        for s in streaming:
            assert ANSWER_MD.startswith(s["partial_answer"])

    def test_answer_stays_null_and_checks_pending_while_streaming(self, flask_client):
        """THE bug-class-(d) invariant. The UI derives every pass/fail chip from
        `answer` and only when `checks_status == 'complete'`; if either leaks
        early, a green chip can appear over unchecked text."""
        client, _app = flask_client
        r = client.post("/ask", json={"question": "MTA versus Biodentine?",
                                      "mode": "review", "skip_clarify": True})
        job_id = r.get_json()["job_id"]

        samples = _poll_until(client, job_id,
                              lambda s: s.get("status") in ("complete", "error"))
        saw_partial = False
        for s in samples:
            if s.get("status") == "complete":
                continue
            if s.get("partial_answer"):
                saw_partial = True
            assert not s.get("answer"), (
                "the job exposed a finished `answer` before it was complete")
            assert s.get("checks_status") != "complete", (
                "checks_status said 'complete' before the guardrails had run")
        assert saw_partial
        final = samples[-1]
        assert final["checks_status"] == "complete"
        assert final["answer"].startswith(ANSWER_MD)
        assert final["partial_answer"] == ""
        assert final["streaming"] is False

    def test_papers_are_published_before_the_answer(self, flask_client):
        """Inline citation pills must resolve to author names mid-stream."""
        client, _app = flask_client
        r = client.post("/ask", json={"question": "MTA versus Biodentine?",
                                      "mode": "review", "skip_clarify": True})
        job_id = r.get_json()["job_id"]
        samples = _poll_until(client, job_id,
                              lambda s: s.get("status") in ("complete", "error"))
        mid = [s for s in samples if s.get("partial_answer")]
        assert mid and mid[0]["papers"], "papers were not published before synthesis"

    def test_abort_mid_stream_stops_the_job(self, flask_client):
        client, _app = flask_client
        r = client.post("/ask", json={"question": "MTA versus Biodentine?",
                                      "mode": "review", "skip_clarify": True})
        job_id = r.get_json()["job_id"]

        _poll_until(client, job_id, lambda s: bool(s.get("partial_answer")), timeout=15)
        client.post(f"/abort/{job_id}")

        samples = _poll_until(client, job_id,
                              lambda s: s.get("status") in ("aborted", "complete", "error"),
                              timeout=15)
        final = samples[-1]
        assert final["status"] == "aborted", (
            f"abort mid-stream left the job at {final['status']}")
        assert not final.get("answer")
        assert final.get("checks_status") != "complete"


# ── 5. The chips, running the real JavaScript ─────────────

INDEX_HTML = Path(__file__).parent.parent / "templates" / "index.html"


def _extract_js(names):
    """Pull named top-level declarations out of index.html so the tests
    exercise the SHIPPED source rather than a Python copy of it.

    Every declaration in that script block starts at column 0; a function ends
    at the first line that is exactly `}`, and a `var` at the first line ending
    in `;`. Brace counting is not usable here — the renderers are full of
    regex literals like /\\n{2,}/ that would unbalance it.
    """
    src = INDEX_HTML.read_text(encoding="utf-8").split("\n")
    out = []
    for name in names:
        start = None
        is_fn = False
        for i, line in enumerate(src):
            if line.startswith(f"function {name}("):
                start, is_fn = i, True
                break
            if line.startswith(f"var {name} ") or line.startswith(f"var {name}="):
                start, is_fn = i, False
                break
        assert start is not None, f"{name} not found as a top-level declaration"
        j = start
        while j < len(src):
            if is_fn and j > start and src[j] == "}":
                break
            if not is_fn and src[j].rstrip().endswith(";"):
                break
            j += 1
        assert j < len(src), f"could not find the end of {name}"
        out.append("\n".join(src[start:j + 1]))
    return "\n\n".join(out)


def _run_node(js_body):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available — cannot exercise the shipped JS")
    harness = _extract_js([
        "CHIPS_CHECKING", "buildTrustChips", "_stripSupportBlockquote",
        "_citeEsc", "pmidMeta", "formatCite", "renderAnswer",
        "_recommendationTier", "renderAnswerWithBox",
    ])
    prog = "var mode = 'review';\nvar trunc = function(s){return s;};\n" + harness + "\n" + js_body
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(prog)
        path = f.name
    try:
        r = subprocess.run([node, path], capture_output=True, text=True,
                           encoding="utf-8", timeout=30)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout.strip().splitlines()[-1])
    finally:
        os.unlink(path)


PASS_MARKERS = ("atag-ok", "✓", "consistent", "passed")


class TestChipsAreHonestWhileStreaming:

    def test_no_pass_state_before_the_checks_have_run(self):
        """The single most important assertion in this file. Feed the chip
        builder an answer that WOULD produce green chips, but with the job
        still streaming, and prove nothing green comes out."""
        checked_answer = (ANSWER_MD +
                          "\n\n---\n\n> ✓ **Citation support: verified** for the 2 cited claims")
        out = _run_node("""
        var cases = [
          {status:'running', checks_status:'pending', partial_answer:'x', answer:null},
          {status:'running', checks_status:'pending', partial_answer:'x', answer:%s},
          {status:'running', checks_status:'complete', answer:%s},
          {status:'complete', checks_status:'pending', answer:%s}
        ];
        console.log(JSON.stringify(cases.map(buildTrustChips)));
        """ % (json.dumps(checked_answer), json.dumps(checked_answer),
               json.dumps(checked_answer)))

        for i, html in enumerate(out):
            assert "checking…" in html, f"case {i} did not say checking…"
            for marker in PASS_MARKERS:
                assert marker not in html, (
                    f"case {i} rendered a pass marker {marker!r} before the "
                    f"checks completed: {html}")

    def test_chips_resolve_to_real_values_when_complete(self):
        verified = (ANSWER_MD +
                    "\n\n---\n\n> ✓ **Citation support: verified** for the 2 cited claims")
        flagged = ANSWER_MD + "\n\n> Citation support: 1 of 5 flagged"
        warned = "> ⚠ **VALIDATION WARNING** — nope\n\n" + verified
        out = _run_node("""
        console.log(JSON.stringify([
          buildTrustChips({status:'complete', checks_status:'complete', answer:%s}),
          buildTrustChips({status:'complete', checks_status:'complete', answer:%s}),
          buildTrustChips({status:'complete', checks_status:'complete', answer:%s}),
          buildTrustChips({status:'complete', checks_status:'complete', answer:'no markers here'})
        ]));
        """ % (json.dumps(verified), json.dumps(flagged), json.dumps(warned)))
        ok, flag, warn, bare = out

        assert "checking…" not in "".join(out)
        assert "2/2 consistent" in ok and "Evidence mapping: passed" in ok
        assert "4/5 consistent" in flag and "atag-warn" in flag
        assert "Evidence mapping: warning" in warn and "atag-bad" in warn
        # Fail-open guard: no marker at all must still say something explicit.
        assert "not available" in bare

    def test_missing_fields_do_not_fall_through_to_a_pass(self):
        out = _run_node("""
        console.log(JSON.stringify([
          buildTrustChips({}),
          buildTrustChips({status:'complete'}),
          buildTrustChips({checks_status:'complete'})
        ]));
        """)
        for html in out:
            assert "checking…" in html
            assert "atag-ok" not in html


class TestRecommendationBoxDuringStreaming:

    def test_box_is_withheld_until_the_section_is_complete(self):
        """A half-written recommendation must not be lifted into the box, then
        silently rewritten under the clinician."""
        half = "## CLINICAL RECOMMENDATION\n\nBased on Level I evidence, MTA and Biod"
        out = _run_node("""
        console.log(JSON.stringify({
          half: renderAnswerWithBox(%s, true).box,
          halfBody: renderAnswerWithBox(%s, true).body
        }));
        """ % (json.dumps(half), json.dumps(half)))
        assert out["half"] == "", "a truncated recommendation was boxed"
        assert "Biod" in out["halfBody"], "the partial text was dropped entirely"

    def test_box_appears_as_soon_as_the_separator_arrives(self):
        """...and before the rest of the answer has streamed in."""
        upto_sep = ANSWER_MD.split("## EVIDENCE SUMMARY")[0]
        assert "EVIDENCE SUMMARY" not in upto_sep
        out = _run_node("""
        var parts = renderAnswerWithBox(%s, true);
        console.log(JSON.stringify({box: parts.box, body: parts.body}));
        """ % json.dumps(upto_sep))
        assert "rec-box" in out["box"], "the box did not render once the section closed"
        assert "Based on Level I evidence" in out["box"]
        assert "EVIDENCE SUMMARY" not in out["box"]

    def test_complete_text_behaviour_is_unchanged(self):
        out = _run_node("""
        console.log(JSON.stringify({
          box: renderAnswerWithBox(%s).box,
          body: renderAnswerWithBox(%s).body
        }));
        """ % (json.dumps(ANSWER_MD), json.dumps(ANSWER_MD)))
        assert "rec-box" in out["box"]
        assert "Based on Level I evidence" in out["box"]
        assert "EVIDENCE SUMMARY" in out["body"]
