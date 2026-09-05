"""
Shared audit logs, and the two properties that keep a measurement honest
(`guardrails-v1` Item 4).

THE GENERAL RULE, from HANDOVER.md: any file in the repo root that a running
process appends to is shared mutable state, and any measurement taken as an
offset window into one has this bug until it identifies its own writer.

It has now been hit once for real. `run_eval` computes a case's
citation-support flag rate from a byte-offset window of
`evidence_mapping.jsonl`. A `pytest` run of `tests/test_end_to_end.py`,
started while an eval was in flight, put nine rows of `checked: 3` inside one
curriculum's window and reported 16/146 = 11.0% for what was 16/119 = 13.4%.
The fix landed with no regression test, and `pubmed_audit.jsonl` — same shape,
same exposure, read the same way by `_esearch_hits_since` — had no guard at
all.

THE TWO PROPERTIES, and they pull against each other, which is the whole
difficulty:

  EXCLUDE a row written by another process inside the window.
  KEEP     four curriculum modules landing in the same second.

A timing heuristic was written for the original incident and thrown away
because it cannot do both: the contaminating burst was 1.3 s apart, which is
also what a thread pool finishing four modules looks like. Threads share a
pid; separate processes do not. Both tests below are here because either one
alone admits a wrong fix — exclude-everything-clustered passes the first and
fails the second.

A row with no `pid` predates the field and is COUNTED. "We cannot tell" has to
mean "in the window", or every historical comparison silently loses rows.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "eval"))

import pytest

import endo_ai


def _write(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _esearch_row(pid=None, n=7, level_key="level1", ts="2026-09-01T01:00:00"):
    r = {"ts": ts, "label": "Level I", "level_key": level_key,
         "search_term": "laser", "n_returned": n,
         "pmid_sample": [str(i) for i in range(n)],
         "http_status": 200, "latency_ms": 120}
    if pid is not None:
        r["pid"] = pid
    return r


def _support_row(pid=None, checked=3, flagged=0, ts="2026-09-01T01:00:00"):
    r = {"ts": ts, "function": "verify_citation_support",
         "checked": checked, "total_pairs": checked, "n_requests": 1,
         "n_flagged": flagged, "flags": []}
    if pid is not None:
        r["pid"] = pid
    return r


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """`run_eval` with both audit logs pointed at a tmp directory."""
    import run_eval
    monkeypatch.setattr(run_eval, "AUDIT_LOG", tmp_path / "pubmed_audit.jsonl")
    monkeypatch.setattr(run_eval, "EVMAP_LOG", tmp_path / "evidence_mapping.jsonl")
    return run_eval


# ── pubmed_audit.jsonl — the log that had no guard ────────

class TestEsearchWindowIdentifiesItsWriter:

    def test_a_foreign_row_inside_the_window_is_excluded(self, harness):
        """The 16/119-vs-16/146 incident class, on the other log. Two of this
        process's queries and one from somebody else's; the count is two."""
        mine = os.getpid()
        _write(harness.AUDIT_LOG, [
            _esearch_row(pid=mine, n=40),
            _esearch_row(pid=mine + 99999, n=500),   # another process
            _esearch_row(pid=mine, n=60),
        ])
        total, n, empty, terms, failed, _g, _ge = harness._esearch_hits_since(0)
        assert n == 2, "the foreign query was counted as one of ours"
        assert total == 100, f"a foreign process's 500 PMIDs leaked in: {total}"

    def test_four_modules_in_the_same_second_all_count(self, harness):
        """Curriculum modules retrieve on a thread pool. They share this
        process's pid and they are the eval's own work. A guard that dropped
        them would silently halve the retrieval a Learn case is credited
        with — and a timing rule cannot tell them from the case above."""
        mine = os.getpid()
        _write(harness.AUDIT_LOG, [
            _esearch_row(pid=mine, n=10, ts="2026-09-01T01:00:00.100000"),
            _esearch_row(pid=mine, n=10, ts="2026-09-01T01:00:00.400000"),
            _esearch_row(pid=mine, n=10, ts="2026-09-01T01:00:01.100000"),
            _esearch_row(pid=mine, n=10, ts="2026-09-01T01:00:01.400000"),
        ])
        total, n, empty, terms, failed, _g, _ge = harness._esearch_hits_since(0)
        assert n == 4, "concurrent modules from THIS process were dropped"
        assert total == 40

    def test_a_row_without_a_pid_is_counted(self, harness):
        """Historical rows predate the field. Dropping them would rewrite
        every before/after comparison that spans the change."""
        _write(harness.AUDIT_LOG, [_esearch_row(pid=None, n=25)])
        total, n, _e, _t, _f, _g, _ge = harness._esearch_hits_since(0)
        assert n == 1 and total == 25

    def test_a_failed_request_is_still_not_a_query(self, harness):
        """The pre-existing http_status==0 rule must survive the pid rule: a
        network outage must not read as 'every query matched nothing', which
        is the malformed-query signature."""
        mine = os.getpid()
        _write(harness.AUDIT_LOG, [
            _esearch_row(pid=mine, n=0), _esearch_row(pid=mine, n=5)])
        rows = [json.loads(l) for l in
                harness.AUDIT_LOG.read_text(encoding="utf-8").splitlines()]
        rows[0]["http_status"] = 0
        _write(harness.AUDIT_LOG, rows)
        total, n, empty, _t, failed, _g, _ge = harness._esearch_hits_since(0)
        assert (n, empty, failed) == (1, 0, 1)


class TestTheEsearchLogRecordsItsWriter:

    def test_the_writer_stamps_its_pid(self, tmp_path, monkeypatch):
        monkeypatch.setattr(endo_ai, "_PUBMED_AUDIT_LOG_PATH",
                            str(tmp_path / "pubmed_audit.jsonl"))
        endo_ai._pubmed_audit_log("Level I", "level1", "laser", ["1", "2"],
                                  200, 130)
        rec = json.loads((tmp_path / "pubmed_audit.jsonl")
                         .read_text(encoding="utf-8").strip())
        assert rec["pid"] == os.getpid()

    def test_the_path_is_a_module_constant(self, tmp_path, monkeypatch):
        """It used to be built inside the writer, which made this the one
        audit log `tests/conftest.py` could not redirect — so a suite run
        appended to the product's proof-of-fetch record."""
        monkeypatch.setattr(endo_ai, "_PUBMED_AUDIT_LOG_PATH",
                            str(tmp_path / "redirected.jsonl"))
        endo_ai._pubmed_audit_log("L", "level1", "q", [], 200, 1)
        assert (tmp_path / "redirected.jsonl").exists(), \
            "the writer ignored the redirect and wrote somewhere else"


# ── evidence_mapping.jsonl — the guard that landed untested ──

class TestSupportWindowIdentifiesItsWriter:

    def test_a_foreign_row_inside_the_window_is_excluded(self, harness):
        """The incident verbatim: nine rows of checked=3 from a concurrent
        pytest run turned 16/119 into 16/146."""
        mine = os.getpid()
        rows = [_support_row(pid=mine, checked=119, flagged=16)]
        rows += [_support_row(pid=mine + 99999, checked=3, flagged=0)
                 for _ in range(9)]
        _write(harness.EVMAP_LOG, rows)
        checked, flagged, n = harness._support_since(0)
        assert (checked, flagged) == (119, 16), \
            f"foreign rows leaked in: {flagged}/{checked}"
        assert n == 1

    def test_four_modules_in_the_same_second_all_count(self, harness):
        mine = os.getpid()
        _write(harness.EVMAP_LOG, [
            _support_row(pid=mine, checked=30, flagged=3,
                         ts="2026-09-01T01:00:00.100000"),
            _support_row(pid=mine, checked=30, flagged=4,
                         ts="2026-09-01T01:00:01.400000"),
            _support_row(pid=mine, checked=30, flagged=2,
                         ts="2026-09-01T01:00:02.700000"),
            _support_row(pid=mine, checked=29, flagged=5,
                         ts="2026-09-01T01:00:03.900000"),
        ])
        checked, flagged, n = harness._support_since(0)
        assert (checked, flagged, n) == (119, 14, 4)

    def test_a_row_without_a_pid_is_counted(self, harness):
        _write(harness.EVMAP_LOG, [_support_row(pid=None, checked=12, flagged=1)])
        assert harness._support_since(0) == (12, 1, 1)


# ── cost_log.jsonl — the third one, and its own kind of guard ──

class TestCostRowsNameTheirSource:
    """`cost_log.jsonl` cannot use a pid window — nothing reads it as one —
    but it has the same problem in a slower form: the suite wrote $5.70 of
    stubbed TTS into the record of what the PRODUCT spent, and after the fact
    a stubbed row and a real one were indistinguishable. `source` is the field
    that makes them distinguishable. The historical rows are NOT edited."""

    def test_a_test_run_labels_itself(self):
        """This assertion runs under pytest, so it IS the case under test."""
        assert endo_ai.cost_log_source() == "test"

    def test_the_env_var_overrides(self, monkeypatch):
        monkeypatch.setenv("COST_LOG_SOURCE", "script")
        assert endo_ai.cost_log_source() == "script"

    def test_an_unrecognised_override_does_not_win(self, monkeypatch):
        """A typo must not invent a fourth bucket that nothing filters on."""
        monkeypatch.setenv("COST_LOG_SOURCE", "prodcut")
        assert endo_ai.cost_log_source() in endo_ai.COST_SOURCES

    @pytest.mark.parametrize("argv0,expected", [
        ("scripts/capture_attempt1.py",              "script"),
        (r"scripts\capture_attempt1.py",             "script"),
        ("C:/Users/x/endo-ai-rag/scripts/rescore.py", "script"),
        ("eval/run_eval.py",                         "script"),
        ("run_eval.py",                              "script"),
        ("app.py",                                   "product"),
        ("",                                         "product"),
    ])
    def test_a_script_is_recognised_however_it_was_invoked(
            self, argv0, expected, monkeypatch):
        """`python scripts/x.py` gives argv[0] with NO leading slash, so a
        substring test for "/scripts/" misses the ordinary invocation — and
        the rest of this class cannot catch that, because under pytest the
        detector returns "test" before it ever looks at argv. This is the bug
        the first real script run exposed by writing rows that said
        `product`."""
        monkeypatch.setattr(endo_ai.sys, "argv", [argv0])
        monkeypatch.delenv("COST_LOG_SOURCE", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setitem(sys.modules, "pytest", None)
        monkeypatch.delitem(sys.modules, "pytest")
        assert endo_ai.cost_log_source() == expected

    def test_the_field_is_written(self, tmp_path, monkeypatch):
        monkeypatch.setattr(endo_ai, "_COST_LOG_PATH",
                            str(tmp_path / "cost_log.jsonl"))

        class U:
            input_tokens = 1000
            output_tokens = 100
        endo_ai.log_llm_call("ask_clinical_question", "claude-opus-4-7", U(),
                             mode="review")
        rec = json.loads((tmp_path / "cost_log.jsonl")
                         .read_text(encoding="utf-8").strip())
        assert rec["source"] == "test"

    def test_tts_rows_carry_it_too(self, tmp_path, monkeypatch):
        """The $5.70 was TTS. A guard that covered only log_llm_call would
        miss the exact rows that caused the problem."""
        monkeypatch.setattr(endo_ai, "_COST_LOG_PATH",
                            str(tmp_path / "cost_log.jsonl"))
        endo_ai.log_tts_call("test_deck_narration", "tts-1-hd", 12000)
        rec = json.loads((tmp_path / "cost_log.jsonl")
                         .read_text(encoding="utf-8").strip())
        assert rec["source"] == "test" and rec["kind"] == "tts"


class TestAdminCostsFiltersOnSource:

    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        import app as app_mod
        rows = [
            {"ts": "2026-09-01T12:00:00", "function": "ask_clinical_question",
             "model": "claude-opus-4-7", "mode": "review", "input_tokens": 10,
             "output_tokens": 1, "cost_usd": 1.00, "source": "product"},
            {"ts": "2026-09-01T12:00:01", "function": "test_deck_narration",
             "model": "tts-1-hd", "mode": "export", "input_tokens": 0,
             "output_tokens": 0, "cost_usd": 5.70, "source": "test"},
            # No source: written before the field existed. Reads as product.
            {"ts": "2026-09-01T12:00:02", "function": "ask_clinical_question",
             "model": "claude-opus-4-7", "mode": "review", "input_tokens": 10,
             "output_tokens": 1, "cost_usd": 0.50},
        ]
        p = tmp_path / "cost_log.jsonl"
        _write(p, rows)
        monkeypatch.setattr(endo_ai, "_COST_LOG_PATH", str(p))
        monkeypatch.setenv("ADMIN_TOKEN", "t")
        app_mod.app.config["TESTING"] = True
        return app_mod.app.test_client()

    def _get(self, client, qs=""):
        r = client.get(f"/admin/costs?days=3650{qs}",
                       headers={"X-Admin-Token": "t"})
        assert r.status_code == 200, r.data
        return r.get_json()

    def test_product_is_the_default_and_excludes_the_stubbed_spend(self, client):
        body = self._get(client)
        assert body["source"] == "product"
        assert body["total_cost_usd"] == 1.50, \
            "the $5.70 of stubbed TTS is still in the product total"
        assert body["excluded_calls"] == 1

    def test_a_row_without_a_source_reads_as_product(self, client):
        assert self._get(client)["total_calls"] == 2

    def test_all_reproduces_the_contaminated_number(self, client):
        body = self._get(client, "&source=all")
        assert body["total_cost_usd"] == 7.20
        assert body["excluded_calls"] == 0

    def test_by_source_counts_every_row_regardless_of_the_filter(self, client):
        """A filter that hides rows without saying so is bug class (d) — a
        check that fails open and shows nothing — wearing a different hat."""
        by = self._get(client)["by_source"]
        assert by["product"]["calls"] == 2
        assert by["test"]["calls"] == 1
        assert by["test"]["total_cost"] == 5.7

    def test_test_only_view_isolates_the_imaginary_spend(self, client):
        body = self._get(client, "&source=test")
        assert body["total_cost_usd"] == 5.70


# ── prior_pmids seeds AFTER the routing gate ──────────────
#
# NOT TESTED HERE, and the item that asked for it was working from a stale
# premise. `prior_pmids` seeds the live candidate set only AFTER
# `library_covers_question` has been computed, and that ordering IS the safety
# property: seeding first would let papers carried from the previous answer
# push a thin topic onto the library route, so context would substitute for
# retrieval.
#
# CURO_HANDOVER.md records this as "correct today, load-bearing, written down
# in one docstring and asserted nowhere". The last clause is wrong. It is
# asserted, end to end and behaviourally, by
#
#   tests/test_review_context.py
#     ::TestSeedsDoNotDecideTheRoute
#       ::test_a_thin_library_still_goes_live_with_seeds_available
#
# which drives `build_evidence_base_with_progress` with a 21-hit library whose
# 4 relevant rows plus 8 carried papers reach exactly
# RELEVANCE_GATE["min_relevant"], and asserts the run still trips the live
# tripwire. Mutation-checked in `guardrails-v1`: moving the seeding block above
# the gate and recomputing coverage after it makes that test fail with
# `-> LIVE PUBMED` becoming a library run, while the other four tests in its
# two classes still pass.
#
# A second, weaker test asserting the same thing by reading line numbers out of
# the source was written here and deleted. Two guards on one property, one of
# them worse, is how the worse one ends up being the one that gets maintained.
