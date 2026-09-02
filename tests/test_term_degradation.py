"""
Term-generation degradation is counted, not just printed (A13c).

WHY THIS MATTERS RATHER THAN BEING TIDINESS. When `generate_search_terms`
cannot parse a usable boolean it falls back to the RAW QUESTION. That string
has no AND-groups, so A1's coverage condition abstains — and abstention sends
the run down the LIBRARY route, the less cautious of the two. A silent
downgrade decided on a silent signal is standing rule §1.5, the same class as
the module cap, the stitcher budget, the domain filter and A5a's per-tier cap.

WHAT A13a MEASURED FIRST, from `pubmed_audit.jsonl` (which stores the built
search term verbatim on every live esearch, so the generated topic is
recoverable for 1,790 topics across 155 real runs):

    healthy (2-3 AND-groups)   1,605   89.7%
    DEGRADED (<2 groups)         108    6.0%     92 of them raw prose
    over 3 groups (capped)        77    4.3%

    PRIMARY terms only — the one A1's condition reads:  0 of 149 runs.

So the 6% lives entirely in the EXTRA terms, where the cost is retrieval
breadth rather than routing, and A1's abstention path guards a state that has
not occurred in production. This counter is what keeps that claim checkable
instead of assumed.
"""

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai

ROOT = Path(__file__).parent.parent


@pytest.fixture
def degrade_log(tmp_path, monkeypatch):
    p = tmp_path / "term_degradation.jsonl"
    monkeypatch.setattr(endo_ai, "_TERM_DEGRADE_LOG_PATH", str(p))
    monkeypatch.setattr(endo_ai, "TERM_DEGRADE_COUNTS", {})
    return p


def rows(p):
    if not p.exists():
        return []
    return [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]


class TestADegradedRunLeavesARecord:

    def test_it_writes_a_row_and_increments_a_counter(self, degrade_log):
        endo_ai._log_term_degradation("primary_fallback", "eliquis and apicectomy",
                                      "no usable primary query", "eliquis and apicectomy")
        assert endo_ai.TERM_DEGRADE_COUNTS == {"primary_fallback": 1}
        (row,) = rows(degrade_log)
        assert row["kind"] == "primary_fallback"
        assert row["question"] == "eliquis and apicectomy"
        assert row["detail"]
        assert row["ts"]

    def test_the_two_kinds_are_counted_separately(self, degrade_log):
        """A fallback primary changes ROUTING; a thin term set changes
        BREADTH. Collapsing them would hide which one is happening."""
        endo_ai._log_term_degradation("primary_fallback", "q", "d")
        endo_ai._log_term_degradation("thin_term_set", "q", "d")
        endo_ai._log_term_degradation("thin_term_set", "q", "d")
        assert endo_ai.TERM_DEGRADE_COUNTS == {"primary_fallback": 1, "thin_term_set": 2}

    def test_the_produced_output_is_recorded(self, degrade_log):
        """A13a asks what the degraded output looks like. A count alone cannot
        answer that, and answering it is how the 6% was shown to be prose."""
        endo_ai._log_term_degradation("primary_fallback", "q",
                                      "no usable primary query",
                                      "vital pulp therapy MTA mineral trioxide")
        assert rows(degrade_log)[0]["produced"] == "vital pulp therapy MTA mineral trioxide"

    def test_telemetry_never_breaks_a_run(self, monkeypatch, capsys):
        """It is a log. A failure to write one must not lose the answer."""
        monkeypatch.setattr(endo_ai, "_TERM_DEGRADE_LOG_PATH",
                            "\x00/nonexistent/term_degradation.jsonl")
        monkeypatch.setattr(endo_ai, "TERM_DEGRADE_COUNTS", {})
        endo_ai._log_term_degradation("primary_fallback", "q", "d")   # must not raise
        assert "degradation log failed" in capsys.readouterr().out


class TestBothDegradationPathsAreWired:
    """Standing rule 14 — the counter is only worth having if the production
    paths call it."""

    def _fn(self, name):
        src = (ROOT / "endo_ai.py").read_text(encoding="utf-8")
        i = src.index("def %s(" % name)
        j = src.index("\ndef ", i + 10)
        return src[i:j]

    def test_the_primary_fallback_logs_before_falling_back(self):
        body = self._fn("generate_search_terms")
        i = body.index("could not parse a usable primary query")
        tail = body[i:]
        assert "_log_term_degradation(" in tail, \
            "the primary fallback still only prints"
        assert tail.index("_log_term_degradation(") < tail.index("search_string = question"), \
            "the fallback is taken before it is recorded"

    def test_the_thin_term_set_logs(self):
        body = self._fn("generate_multi_search_terms")
        i = body.index("retrieval breadth is degraded")
        assert "_log_term_degradation(" in body[i:], \
            "the thin-term-set path still only prints"

    def test_a_test_run_cannot_append_to_the_production_log(self):
        """The other four audit logs each had to be redirected AFTER a test run
        polluted the real record. This one was redirected the day it was
        written."""
        conftest = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
        assert "_TERM_DEGRADE_LOG_PATH" in conftest
