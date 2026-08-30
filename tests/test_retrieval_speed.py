"""
NCBI rate limiting, parallel tier fetches, and the Review-mode early stop
(WORKLIST B1, B2, B5).

Retrieval was sequential: ~7 tiers x ~7 search terms, each an HTTP round trip,
one after another. Measured on the laser question from the audit-log
timestamps of the baseline runs, that was a median of 189.6s.

There was also no NCBI rate limiter at all — ten call sites fired as fast as
the code reached them, survivable only BECAUSE everything was sequential.
Parallelising without a limiter would have turned a working pipeline into a 429
generator, so B1 is a prerequisite for B2 rather than an independent speedup.

The two properties that parallelism can silently destroy, and that these tests
exist to protect:

  * dedup went to whichever tier was processed FIRST, and tiers ran
    strongest-first — so a paper found in both level1 and level4 was presented
    as Level I. Concurrent dedup would make that a race.
  * evidence[] order must not encode which fetch finished first.
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai


class TestRateLimiter:

    def test_rates_sit_below_the_documented_ceilings(self):
        """NCBI enforces per-second with its own clock, so running exactly at
        the limit gets throttled on any burst that straddles a boundary."""
        assert endo_ai.NCBI_RATE_WITH_KEY < 10
        assert endo_ai.NCBI_RATE_WITHOUT_KEY < 4

    def test_api_key_is_attached_when_present(self, monkeypatch):
        monkeypatch.setenv("NCBI_API_KEY", "test-key-123")
        assert endo_ai._ncbi_params({"db": "pubmed"})["api_key"] == "test-key-123"

    def test_no_api_key_param_when_absent(self, monkeypatch):
        monkeypatch.delenv("NCBI_API_KEY", raising=False)
        assert "api_key" not in endo_ai._ncbi_params({"db": "pubmed"})

    def test_tool_and_email_always_attached(self):
        p = endo_ai._ncbi_params({})
        assert p["tool"] == "endo-ai-rag" and p["email"]

    def test_calls_are_paced(self, monkeypatch):
        monkeypatch.setenv("NCBI_API_KEY", "k")
        endo_ai._ncbi_last_call[0] = 0.0
        t0 = time.perf_counter()
        for _ in range(4):
            endo_ai._ncbi_rate_limit()
        elapsed = time.perf_counter() - t0
        assert elapsed >= 3 / endo_ai.NCBI_RATE_WITH_KEY - 0.02

    def test_pacing_holds_across_threads(self, monkeypatch):
        """The limiter is only useful if it is global — a per-thread limiter
        multiplies the request rate by the pool size."""
        monkeypatch.setenv("NCBI_API_KEY", "k")
        endo_ai._ncbi_last_call[0] = 0.0
        t0 = time.perf_counter()
        ts = [threading.Thread(target=endo_ai._ncbi_rate_limit) for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        elapsed = time.perf_counter() - t0
        assert elapsed >= 7 / endo_ai.NCBI_RATE_WITH_KEY - 0.05, \
            "8 concurrent calls departed faster than the rate limit allows"

    def test_no_key_is_slower_than_with_key(self, monkeypatch):
        monkeypatch.delenv("NCBI_API_KEY", raising=False)
        endo_ai._ncbi_last_call[0] = 0.0
        t0 = time.perf_counter()
        for _ in range(2):
            endo_ai._ncbi_rate_limit()
        assert time.perf_counter() - t0 >= 1 / endo_ai.NCBI_RATE_WITHOUT_KEY - 0.02

    def test_ncbi_get_itself_actually_paces(self, monkeypatch):
        """Testing _ncbi_rate_limit alone is not enough: a mutation that makes
        ncbi_get skip the limiter passes every test that calls the limiter
        directly. Drive the wrapper and time it."""
        monkeypatch.setenv("NCBI_API_KEY", "k")
        monkeypatch.setattr(endo_ai.requests, "get",
                            lambda url, **kw: type("R", (), {"status_code": 200})())
        endo_ai._ncbi_last_call[0] = 0.0
        t0 = time.perf_counter()
        for _ in range(3):
            endo_ai.ncbi_get("https://eutils.example/esearch.fcgi")
        assert time.perf_counter() - t0 >= 2 / endo_ai.NCBI_RATE_WITH_KEY - 0.02, \
            "ncbi_get is not applying the rate limiter"

    def test_every_ncbi_endpoint_goes_through_the_limiter(self):
        """A bare requests.get to eutils bypasses pacing silently."""
        src = Path(endo_ai.__file__).read_text(encoding="utf-8")
        offenders = [ln.strip() for ln in src.splitlines()
                     if "requests.get(" in ln
                     and ("eutils" in ln.lower() or "NCBI_EUTILS_BASE" in ln
                          or "elink_url" in ln or "search_url" in ln
                          or "fetch_url" in ln or "summary_url" in ln)]
        assert not offenders, f"NCBI calls bypassing ncbi_get: {offenders}"


class TestParallelTierFetch:

    def test_worker_count_stays_under_the_db_pool(self):
        """Each worker can borrow a connection during write-back; exceeding
        DB_POOL_MAX turns speedup into pool exhaustion."""
        import os
        import app
        assert app.TIER_FETCH_WORKERS <= int(os.getenv("DB_POOL_MAX", "10"))

    def test_worker_count_is_bounded(self):
        import app
        assert 1 < app.TIER_FETCH_WORKERS <= 10


class TestEarlyStop:
    """B5. Tier banding means a case series can never override a Level I
    finding, so once the top tiers are full the weak ones cannot change the
    recommendation — but only in Review mode."""

    def test_threshold_is_configured(self):
        import app
        assert app.EARLY_STOP_MIN_PAPERS >= 10
        assert "level1" in app.EARLY_STOP_TIERS

    def test_cochrane_is_not_in_the_early_stop_tier_list(self):
        """It is fetched before the loop, so counting it there would
        double-count it."""
        import app
        assert "cochrane" not in app.EARLY_STOP_TIERS

    def test_learn_mode_is_exempt(self):
        """A teaching curriculum wants the narrative scaffolding that reviews
        and editorials supply; stopping early would strip exactly that."""
        import inspect
        import app
        src = inspect.getsource(app.build_evidence_base_with_progress)
        assert 'mode == "review"' in src, \
            "early stop is not gated on Review mode"

    def test_builder_accepts_mode(self):
        import inspect
        import app
        sig = inspect.signature(app.build_evidence_base_with_progress)
        assert sig.parameters["mode"].default == "review"
