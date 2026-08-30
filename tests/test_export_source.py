"""
Exports must narrate the answer that is on screen (WORKLIST follow-up).

The bug: /generate_audio, /generate_slides and /generate_video all required a
live job in THIS process's memory. An answer opened from the history sidebar
has no such job — loadHistoryItem renders a client-side fakeJob — and every
entry in that sidebar is history-loaded. So the export button either failed
with "Job not found", or, if an earlier live question had left a job id in
`currentJob`, exported the PREVIOUS answer while the user looked at a
different one. The second failure is the dangerous one: it succeeds, and
produces a narration of the wrong clinical question.

The fix accepts client-supplied question+answer as a fallback source. That
makes the request body untrusted input flowing into a paid TTS pipeline, so
the size cap is part of the contract and is tested here too.

These are server-side; the browser half (that the page actually sends the
displayed answer, and clears a stale job id on history load) lives in
tests/test_export_client.py.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import app as app_mod
from app import (MAX_EXPORT_ANSWER_CHARS, MAX_EXPORT_QUESTION_CHARS,
                 ExportSourceTooLarge, _resolve_export_source)

EXPORT_ROUTES = ["/generate_audio", "/generate_slides", "/generate_video"]

ANSWER = "## CLINICAL RECOMMENDATION\n\nCBCT shows higher sensitivity [[PMID:123]]."
QUESTION = "CBCT versus periapical radiography for detecting apical periodontitis"


@pytest.fixture
def client(monkeypatch):
    """A test client with the export workers stubbed out — these tests are
    about which SOURCE the endpoint selects, not about TTS."""
    started = []
    for target in ("run_generate_audio", "run_generate_slides", "run_generate_video"):
        monkeypatch.setattr(app_mod, target,
                            lambda *a, **k: started.append(a), raising=False)

    class _Thread:
        def __init__(self, target=None, args=(), **kw):
            self._args = args
        def start(self):
            started.append(self._args)

    monkeypatch.setattr(app_mod.threading, "Thread", _Thread)
    c = app_mod.app.test_client()
    c._started = started
    return c


class TestResolver:
    """_resolve_export_source is the whole fix in one function."""

    def test_live_job_is_preferred(self):
        with app_mod.jobs_lock:
            app_mod.jobs["live-1"] = {"question": "live Q", "answer": "live A"}
        try:
            q, a = _resolve_export_source(
                {"job_id": "live-1", "question": "body Q", "answer": "body A"})
        finally:
            with app_mod.jobs_lock:
                app_mod.jobs.pop("live-1", None)
        assert (q, a) == ("live Q", "live A")

    def test_falls_back_to_the_body_when_no_job_matches(self):
        """The history-loaded case: no job exists at all."""
        assert _resolve_export_source(
            {"job_id": "", "question": QUESTION, "answer": ANSWER}) == (QUESTION, ANSWER)

    def test_stale_job_id_does_not_resolve_to_a_stale_job(self):
        """A job id the server has never heard of must not silently win or
        blank the request — it falls through to the supplied text."""
        assert _resolve_export_source(
            {"job_id": "does-not-exist", "question": QUESTION,
             "answer": ANSWER}) == (QUESTION, ANSWER)

    def test_a_job_without_an_answer_is_not_a_source(self):
        """A job still running has no answer yet; the body must win."""
        with app_mod.jobs_lock:
            app_mod.jobs["pending"] = {"question": "pending Q", "answer": ""}
        try:
            q, a = _resolve_export_source(
                {"job_id": "pending", "question": QUESTION, "answer": ANSWER})
        finally:
            with app_mod.jobs_lock:
                app_mod.jobs.pop("pending", None)
        assert (q, a) == (QUESTION, ANSWER)

    def test_neither_source_yields_nothing(self):
        assert _resolve_export_source({"job_id": "", "answer": ""}) == (None, None)
        assert _resolve_export_source({}) == (None, None)

    def test_whitespace_only_answer_is_not_a_source(self):
        assert _resolve_export_source({"answer": "   \n  "}) == (None, None)


class TestSizeCap:
    """Untrusted text into a paid TTS pipeline. Real answers measured across
    the library run 7.7k-11.5k characters; the cap is ~17x the largest."""

    def test_cap_is_generous_relative_to_real_answers(self):
        assert MAX_EXPORT_ANSWER_CHARS >= 100_000

    def test_oversized_answer_is_refused_not_truncated(self):
        """Truncating would narrate half an answer and look like success."""
        with pytest.raises(ExportSourceTooLarge):
            _resolve_export_source({"answer": "x" * (MAX_EXPORT_ANSWER_CHARS + 1)})

    def test_an_answer_at_the_cap_is_accepted(self):
        q, a = _resolve_export_source({"answer": "x" * MAX_EXPORT_ANSWER_CHARS})
        assert len(a) == MAX_EXPORT_ANSWER_CHARS

    def test_long_question_is_truncated_rather_than_refused(self):
        """The question is a label, not narrated content — clipping it is
        harmless, and refusing the whole export over it would not be."""
        q, _a = _resolve_export_source({"question": "q" * 50_000, "answer": ANSWER})
        assert len(q) == MAX_EXPORT_QUESTION_CHARS

    @pytest.mark.parametrize("route", EXPORT_ROUTES)
    def test_endpoints_return_413_not_500(self, client, route):
        r = client.post(route, json={"job_id": "",
                                     "answer": "x" * (MAX_EXPORT_ANSWER_CHARS + 1)})
        assert r.status_code == 413
        assert "too large" in r.get_json()["error"].lower()


class TestEndpoints:
    """The behaviour a user sees, across all three export types — the bug was
    identical in each because they shared the lookup."""

    @pytest.mark.parametrize("route", EXPORT_ROUTES)
    def test_history_loaded_export_is_accepted(self, client, route):
        """The exact path that was broken: no live job, answer from the body."""
        r = client.post(route, json={"job_id": "", "question": QUESTION,
                                     "answer": ANSWER})
        if r.status_code == 503:
            pytest.skip("optional backend for this export type not installed")
        assert r.status_code == 200, r.get_json()
        assert r.get_json().get("audio_id")

    @pytest.mark.parametrize("route", EXPORT_ROUTES)
    def test_export_with_neither_source_fails(self, client, route):
        r = client.post(route, json={"job_id": "nope"})
        if r.status_code == 503:
            pytest.skip("optional backend for this export type not installed")
        assert r.status_code == 404

    @pytest.mark.parametrize("route", EXPORT_ROUTES)
    def test_the_worker_receives_the_displayed_answer(self, client, route):
        """The wrong-answer failure mode, pinned: a stale job id must not
        cause a different answer to be narrated than the one supplied."""
        with app_mod.jobs_lock:
            app_mod.jobs["stale"] = {"question": "OLD question",
                                     "answer": "OLD answer text"}
        try:
            r = client.post(route, json={"job_id": "gone-from-memory",
                                         "question": QUESTION, "answer": ANSWER})
            if r.status_code == 503:
                pytest.skip("optional backend not installed")
            assert r.status_code == 200
            passed = client._started[-1]
            assert ANSWER in passed, "worker did not receive the displayed answer"
            assert "OLD answer text" not in passed
        finally:
            with app_mod.jobs_lock:
                app_mod.jobs.pop("stale", None)
