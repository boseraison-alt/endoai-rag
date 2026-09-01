"""
The eval harness itself.

Two failure modes matter here and neither shows up as a red test elsewhere:

  * The harness reports "passed" while evaluating nothing. `--synthesis-subset`
    initially only FILTERED the case list — it printed a synthesis-mode banner
    and ran the retrieval-only checks. That is bug class (d) applied to the
    thing whose whole job is catching bug class (d).

  * The harness mutates what it measures. Write-back turned every eval run into
    a library-modifying operation, so run 2 could not be compared with run 1.

Both are asserted below.
"""
import inspect
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "eval"))

import pytest

import run_eval


class TestWriteBackIsDisabled:
    """An eval run must be read-only against the library."""

    def test_run_case_disables_write_back(self, monkeypatch):
        import endo_ai
        monkeypatch.setattr(endo_ai, "LIBRARY_WRITE_BACK", True, raising=False)
        seen = {}

        def _fake_builder(job_id, question, force_route=None, mode="review",
                          context_block="", prior_pmids=None):
            seen["write_back"] = endo_ai.LIBRARY_WRITE_BACK
            return {}

        monkeypatch.setattr("app.build_evidence_base_with_progress", _fake_builder)
        run_eval.run_case({"id": "probe", "question": "q", "expect": {}})
        assert seen["write_back"] is False, \
            "eval run would write its own results into the library it measures"


class TestSynthesisAssertions:
    """These only run in --synthesis-subset. If the wiring regresses to
    filter-only, `has_banner` disappears from the result and these fail."""

    def _run(self, monkeypatch, answer, expect, mode="review"):
        import app as app_mod
        import endo_ai

        class _Resp:
            status_code = 200
            data = b""
            def get_json(self):
                return self._j
        class _Client:
            def post(self, *a, **k):
                r = _Resp(); r._j = {"job_id": "j1"}; return r
            def get(self, *a, **k):
                r = _Resp()
                r._j = {"status": "complete", "answer": answer,
                        "papers": [{"pmid": "1"}], "cost_usd": 0.99}
                return r

        monkeypatch.setattr(app_mod.app, "test_client", lambda: _Client())
        monkeypatch.setattr(endo_ai, "LIBRARY_WRITE_BACK", True, raising=False)
        return run_eval.run_case_with_synthesis(
            {"id": "c", "question": "q", "mode": mode,
             "force_route": "library", "expect": expect})

    def test_must_contain_fails_when_absent(self, monkeypatch):
        _m, f = self._run(monkeypatch, "An answer with no citation of note.",
                          {"must_contain": ["Cochrane"]})
        assert any("must_contain" in x for x in f)

    def test_must_contain_passes_when_present(self, monkeypatch):
        _m, f = self._run(monkeypatch, "A Cochrane review found no difference.",
                          {"must_contain": ["Cochrane"]})
        assert f == []

    def test_must_not_contain_fails_when_present(self, monkeypatch):
        _m, f = self._run(monkeypatch, "This is contraindicated in all cases.",
                          {"must_not_contain": ["contraindicated"]})
        assert any("must_not_contain" in x for x in f)

    def test_divided_banner_required_and_missing(self, monkeypatch):
        _m, f = self._run(monkeypatch, "Both protocols perform similarly.",
                          {"banner": "divided"})
        assert any("divided-literature banner" in x for x in f)

    def test_divided_banner_detected(self, monkeypatch):
        m, f = self._run(monkeypatch,
                         "**The literature is currently divided on this topic.** Both...",
                         {"banner": "divided"})
        assert f == [] and m["has_banner"] is True

    def test_ungenerated_module_is_caught(self, monkeypatch):
        _m, f = self._run(monkeypatch,
                          "## Module 1\ntext\n\n> **Module not generated — insufficient evidence retrieved.**",
                          {"modules_non_empty": True}, mode="learn")
        assert any("not generated" in x for x in f)

    def test_unsourced_numeric_protocol_is_caught(self, monkeypatch):
        """The original failure: Er:YAG settings invented with zero citations."""
        answer = ("## Recommendation\nSee below [[PMID:123]].\n\n"
                  "## Protocol\nUse Er:YAG at 20 mJ, 15 Hz with 5.25% NaOCl for 60 s.")
        _m, f = self._run(monkeypatch, answer,
                          {"max_unsourced_numeric_modules": 0})
        assert any("numeric clinical" in x for x in f)

    def test_numeric_section_with_a_citation_passes(self, monkeypatch):
        answer = ("## Protocol\nUse 5.25% NaOCl for 60 s [[PMID:123]].")
        _m, f = self._run(monkeypatch, answer,
                          {"max_unsourced_numeric_modules": 0})
        assert f == []


class TestNumericParamRegex:
    @pytest.mark.parametrize("text,hit", [
        ("Er:YAG 20 mJ, 15 Hz", True),
        ("5.25% NaOCl", True),
        ("irrigate for 60 s", True),
        ("followed for 24 month", True),
        ("no numeric clinical parameters at all", False),
        ("the 2019 guideline", False),
    ])
    def test_matches(self, text, hit):
        assert bool(run_eval.NUMERIC_PARAM_RE.search(text)) is hit


class TestNetworkFailuresAreNotMisreadAsBadQueries:
    """A real DNS outage mid-baseline made 62 esearch calls fail. Because
    failures were not logged, the harness saw only the handful that got
    through and reported "1.0 hits/query — the laser regression's real
    signature" for queries that were never sent. A wrong diagnosis is worse
    than no diagnosis: it points the next engineer at the query generator."""

    def _log(self, tmp_path, monkeypatch, records):
        import json as _json
        f = tmp_path / "audit.jsonl"
        f.write_text("".join(_json.dumps(r) + "\n" for r in records), encoding="utf-8")
        monkeypatch.setattr(run_eval, "AUDIT_LOG", f)
        return run_eval._esearch_hits_since(0)

    def test_failed_calls_are_excluded_from_query_counts(self, tmp_path, monkeypatch):
        recs = ([{"http_status": 0, "n_returned": 0, "level_key": "level1"}] * 8 +
                [{"http_status": 200, "n_returned": 50, "level_key": "level1"}] * 2)
        total, n, empty, terms, failed = self._log(tmp_path, monkeypatch, recs)
        assert failed == 8
        assert n == 2, "never-sent calls must not count as queries"
        assert empty == 0, "a call that never left the machine did not 'return nothing'"
        assert total == 100

    def test_hits_per_query_reflects_only_real_responses(self, tmp_path, monkeypatch):
        recs = ([{"http_status": 0, "n_returned": 0, "level_key": "level1"}] * 9 +
                [{"http_status": 200, "n_returned": 40, "level_key": "level1"}])
        total, n, _e, _t, failed = self._log(tmp_path, monkeypatch, recs)
        assert total / n == 40.0, "outage must not drag the per-query average down"
        assert failed == 9

    def test_healthy_log_reports_no_failures(self, tmp_path, monkeypatch):
        recs = [{"http_status": 200, "n_returned": 30, "level_key": "level1"}] * 5
        _t, n, _e, terms, failed = self._log(tmp_path, monkeypatch, recs)
        assert (failed, n, terms) == (0, 5, 5)


class TestSynthesisModeIsActuallyWired:
    """Testing the assertion functions directly is not enough: the first
    version of --synthesis-subset only FILTERED the case list and still called
    the retrieval-only path, so every answer-level check was dead code behind a
    banner that said SYNTHESIS. These tests drive main() and assert which
    executor it chose."""

    def _spy_main(self, monkeypatch, argv):
        called = []
        monkeypatch.setattr(run_eval, "run_case_with_synthesis",
                            lambda c: (called.append(("synthesis", c["id"])),
                                       ({"route": "library", "papers": 1, "per_tier": {},
                                         "esearch_queries": 0}, []))[1])
        monkeypatch.setattr(run_eval, "run_case",
                            lambda c: (called.append(("retrieval", c["id"])),
                                       ({"route": "library", "papers": 1, "per_tier": {},
                                         "esearch_queries": 0}, []))[1])
        monkeypatch.setattr(sys, "argv", ["run_eval.py"] + argv)
        run_eval.main()
        return called

    def test_synthesis_subset_uses_the_synthesis_executor(self, monkeypatch):
        called = self._spy_main(monkeypatch, ["--synthesis-subset"])
        assert called, "no cases ran"
        assert {kind for kind, _ in called} == {"synthesis"}, \
            f"--synthesis-subset ran the retrieval-only path: {called}"

    def test_synthesis_subset_runs_exactly_the_named_cases(self, monkeypatch):
        called = self._spy_main(monkeypatch, ["--synthesis-subset"])
        assert sorted(cid for _, cid in called) == sorted(run_eval.SYNTHESIS_SUBSET)

    def test_default_run_uses_the_retrieval_executor(self, monkeypatch):
        called = self._spy_main(monkeypatch, ["--id", "laser-root-canal-disinfection-library"])
        assert {kind for kind, _ in called} == {"retrieval"}, \
            f"a default run must never spend synthesis money: {called}"


class TestPinnedBuilderSignature:
    def test_wrapper_accepts_everything_the_real_builder_does(self):
        """The synthesis wrapper replaces build_evidence_base_with_progress for
        the duration of a case. When the real builder grew a mode= kwarg, the
        wrapper silently didn't — and three of five synthesis cases ERRORED on
        an unexpected keyword argument. The wiring tests missed it because they
        stub run_case_with_synthesis wholesale. Compare signatures instead."""
        import inspect
        import app
        real = set(inspect.signature(app.build_evidence_base_with_progress).parameters)
        src = inspect.getsource(run_eval.run_case_with_synthesis)
        for param in real - {"job_id", "question"}:
            assert f"{param}=" in src.split("def _pinned_builder")[1].split("return")[1], \
                f"_pinned_builder does not forward {param!r} to the real builder"


class TestModeLabelling:
    def test_subset_ids_all_exist_in_questions(self):
        """A typo'd id would silently shrink the subset to nothing."""
        _doc, cases = run_eval.load_cases()
        ids = {c["id"] for c in cases}
        missing = [i for i in run_eval.SYNTHESIS_SUBSET if i not in ids]
        assert not missing, f"synthesis subset references unknown case ids: {missing}"


# ── The conversational and case-mode assertions (CURO_HANDOVER §5[A]) ────────

class _Builder:
    """Records what the harness handed the real builder, and returns a
    pre-baked evidence dict shaped like the real one."""

    def __init__(self, evidence=None):
        self.evidence = evidence or {}
        self.seen = {}

    def __call__(self, job_id, question, force_route=None, mode="review",
                 context_block="", prior_pmids=None):
        self.seen = {"question": question, "force_route": force_route,
                     "mode": mode, "context_block": context_block,
                     "prior_pmids": prior_pmids}
        return self.evidence


def _evidence(**tiers):
    """{tier: [(pmid, title), ...]} -> the evidence dict shape run_case reads."""
    out = {}
    for tier, papers in tiers.items():
        out[tier] = {"source": "rag",
                     "scored": [{"pmid": p, "title": t} for p, t in papers]}
    return out


LASER_THREAD = {"exchanges": [{
    "question": "Use of lasers in root canal disinfection",
    "recommendation": "Laser-activated irrigation is a reasonable adjunct.",
    "pmids": ["41833582", "41063319"],
}]}


class TestTheThreadReachesTheBuilder:
    """A follow-up case whose context is dropped tests nothing: 'What about in
    immature teeth?' names no subject, so the queries would be built from five
    words. The block and the seeds must be built with the app's OWN helpers,
    not re-implemented in the harness."""

    def _run(self, monkeypatch, case):
        b = _Builder(_evidence(level1=[("1", "Laser irrigation in immature teeth")]))
        monkeypatch.setattr("app.build_evidence_base_with_progress", b)
        run_eval.run_case(case)
        return b.seen

    def test_context_block_is_built_from_the_exchanges(self, monkeypatch):
        import endo_ai
        seen = self._run(monkeypatch, {
            "id": "probe", "question": "What about in immature teeth?",
            "context": LASER_THREAD, "expect": {}})
        assert seen["context_block"], "the thread never reached the builder"
        assert seen["context_block"] == endo_ai.build_context_block(
            LASER_THREAD["exchanges"]), \
            "the harness built its own block instead of the app's"
        assert "lasers in root canal disinfection" in seen["context_block"]

    def test_prior_pmids_are_forwarded(self, monkeypatch):
        seen = self._run(monkeypatch, {
            "id": "probe", "question": "q", "context": LASER_THREAD,
            "expect": {}})
        assert seen["prior_pmids"] == ["41833582", "41063319"]

    def test_a_case_with_no_thread_sends_no_context(self, monkeypatch):
        """"" must keep meaning "no context" — it is the cache partition every
        standalone question lives in."""
        seen = self._run(monkeypatch, {"id": "probe", "question": "q",
                                       "expect": {}})
        assert seen["context_block"] == ""
        assert seen["prior_pmids"] is None

    def test_case_mode_is_forwarded(self, monkeypatch):
        seen = self._run(monkeypatch, {"id": "probe", "question": "q",
                                       "mode": "case", "expect": {}})
        assert seen["mode"] == "case"


class TestEvidenceLevelContextAssertions:
    """The assertion is on the EVIDENCE, not on the prompt. A prompt-string
    check passes while the block is assembled and then dropped."""

    def _fail(self, monkeypatch, evidence, expect):
        b = _Builder(evidence)
        monkeypatch.setattr("app.build_evidence_base_with_progress", b)
        _, failures = run_eval.run_case(
            {"id": "probe", "question": "q", "expect": expect})
        return failures

    def test_off_topic_evidence_fails_the_follow_up(self, monkeypatch):
        ev = _evidence(level1=[("1", "Sealer heat properties"),
                               ("2", "Apex locator accuracy")])
        f = self._fail(monkeypatch, ev, {"evidence_must_mention": ["laser"]})
        assert any("did not reach the search-term generators" in x for x in f)

    def test_on_topic_evidence_passes(self, monkeypatch):
        ev = _evidence(level1=[("1", "Er:YAG LASER irrigation of immature teeth")])
        f = self._fail(monkeypatch, ev, {"evidence_must_mention": ["laser"]})
        assert not f

    def test_a_new_topic_dominated_by_the_old_one_fails(self, monkeypatch):
        ev = _evidence(level1=[("1", "Laser disinfection"),
                               ("2", "Laser activated irrigation"),
                               ("3", "NaOCl concentration")])
        f = self._fail(monkeypatch, ev,
                       {"evidence_must_not_be_dominated_by": ["laser"]})
        assert any("inherited the previous thread's topic" in x for x in f)

    def test_a_minority_of_the_old_topic_is_allowed(self, monkeypatch):
        """A few genuine laser-irrigation papers legitimately discuss NaOCl."""
        ev = _evidence(level1=[("1", "Laser activated irrigation with NaOCl"),
                               ("2", "NaOCl concentration and outcome"),
                               ("3", "Hypochlorite accident management")])
        f = self._fail(monkeypatch, ev,
                       {"evidence_must_not_be_dominated_by": ["laser"]})
        assert not f


class TestCaseModeSweepsEveryTier:
    """`EARLY_STOP_MIN_PAPERS` skips level2..level5 once cochrane+level1 clear
    15 papers. Case mode is exempt, and the only way to see that from outside
    is to count the tiers populated BELOW level1."""

    def _run(self, monkeypatch, evidence, floor):
        b = _Builder(evidence)
        monkeypatch.setattr("app.build_evidence_base_with_progress", b)
        _, failures = run_eval.run_case(
            {"id": "probe", "question": "q", "mode": "case",
             "expect": {"min_tiers_below_level1": floor}})
        return failures

    def test_top_tiers_only_fails(self, monkeypatch):
        ev = _evidence(cochrane=[("1", "A")], level1=[("2", "B")])
        f = self._run(monkeypatch, ev, 1)
        assert any("early stop" in x for x in f)

    def test_a_lower_tier_satisfies_the_floor(self, monkeypatch):
        ev = _evidence(cochrane=[("1", "A")], level1=[("2", "B")],
                       level4=[("3", "C")])
        assert not self._run(monkeypatch, ev, 1)

    def test_the_floor_counts_tiers_not_papers(self, monkeypatch):
        """Ten case reports in one tier is one tier, not ten."""
        ev = _evidence(level1=[("0", "B")],
                       level4=[(str(i), "C") for i in range(10)])
        f = self._run(monkeypatch, ev, 2)
        assert any("early stop" in x for x in f)


class TestTheClarifyGateAssertions:
    """Case mode's opening is the half retrieval cannot see."""

    def _run(self, monkeypatch, questions, clarify):
        import endo_ai
        b = _Builder(_evidence(level1=[("1", "A")]))
        monkeypatch.setattr("app.build_evidence_base_with_progress", b)
        monkeypatch.setattr(endo_ai, "generate_case_followups",
                            lambda desc: questions)
        _, failures = run_eval.run_case(
            {"id": "probe", "question": "Tooth 36 hurts.", "mode": "case",
             "expect": {"clarify": clarify}})
        return failures

    def test_too_many_questions_is_an_interrogation(self, monkeypatch):
        f = self._run(monkeypatch, [f"Q{i} — reason" for i in range(6)],
                      {"count_between": [1, 3]})
        assert any("expected 1-3" in x for x in f)

    def test_asking_nothing_of_a_sparse_description_fails(self, monkeypatch):
        f = self._run(monkeypatch, [], {"count_between": [1, 3]})
        assert any("expected 1-3" in x for x in f)

    def test_re_asking_a_stated_fact_fails(self, monkeypatch):
        f = self._run(monkeypatch,
                      ["Is the tooth restorable — it decides extraction"],
                      {"count_between": [0, 3],
                       "must_not_ask_about": ["restorab"]})
        assert any("re-asked facts" in x for x in f)

    def test_a_question_without_its_reason_fails(self, monkeypatch):
        f = self._run(monkeypatch, ["Is the tooth vital?"],
                      {"count_between": [0, 3],
                       "every_question_states_its_reason": True})
        assert any("no reason clause" in x for x in f)

    def test_a_well_formed_opening_passes(self, monkeypatch):
        f = self._run(monkeypatch,
                      ["Is the tooth vital — it decides the treatment path"],
                      {"count_between": [1, 3],
                       "must_not_ask_about": ["bisphosphonate"],
                       "every_question_states_its_reason": True})
        assert not f

    def test_a_raised_clarify_gate_is_reported_not_swallowed(self, monkeypatch):
        """Fail-open here would make a broken opening indistinguishable from a
        good one — bug class (d), in the harness that exists to catch it."""
        import endo_ai
        b = _Builder(_evidence(level1=[("1", "A")]))
        monkeypatch.setattr("app.build_evidence_base_with_progress", b)

        def _boom(desc):
            raise RuntimeError("no api key")

        monkeypatch.setattr(endo_ai, "generate_case_followups", _boom)
        _, failures = run_eval.run_case(
            {"id": "probe", "question": "q", "mode": "case",
             "expect": {"clarify": {"count_between": [1, 3]}}})
        assert any("clarify gate raised RuntimeError" in x for x in failures)


class TestTheNewCasesAreWellFormed:
    """The four cases added in this batch, checked against the harness that
    has to run them — a case naming a field the harness ignores is a case that
    silently tests nothing."""

    IDS = ["case-opening-sparse", "case-opening-full",
           "review-followup-immature-teeth", "review-newtopic-reset"]

    def _cases(self):
        _, cases = run_eval.load_cases()
        return {c["id"]: c for c in cases}

    def test_all_four_are_present(self):
        have = self._cases()
        assert not [i for i in self.IDS if i not in have]

    def test_every_case_pins_its_route(self):
        for cid, case in self._cases().items():
            assert case.get("force_route"), f"{cid} does not pin force_route"

    def test_the_thread_cases_carry_a_thread(self):
        have = self._cases()
        for cid in ("review-followup-immature-teeth", "review-newtopic-reset"):
            ex = (have[cid].get("context") or {}).get("exchanges") or []
            assert ex and ex[0].get("pmids"), f"{cid} has no prior exchange"

    def test_the_case_mode_cases_declare_case_mode(self):
        have = self._cases()
        for cid in ("case-opening-sparse", "case-opening-full"):
            assert have[cid].get("mode") == "case"
            assert have[cid]["expect"].get("clarify")


class TestTheDiffFlagActuallyDiffs:
    """`--diff` was declared with argparse and then never read: the flag ran an
    ordinary eval, printed no table and exited 0. A reviewer running it saw a
    clean result from a comparison that never happened — bug class (d), inside
    the harness written to catch bug class (d)."""

    BASE = {"cases": {"a-case": {
        "force_route": "library",
        "routes_observed": ["library"],
        "papers": {"min": 38, "max": 39, "runs": [38, 39, 38]},
        "search_terms": {"min": 6, "max": 9, "runs": [6, 9, 7]},
    }}}

    def _baseline(self, tmp_path, monkeypatch, doc=None):
        f = tmp_path / "b.json"
        f.write_text(json.dumps(doc if doc is not None else self.BASE),
                     encoding="utf-8")
        return str(f)

    def test_the_flag_is_read_at_all(self):
        """The regression itself: the parser knows --diff and main() uses it."""
        src = inspect.getsource(run_eval.main)
        assert "args.diff" in src, "--diff is declared but never read"

    def test_a_value_inside_the_range_is_not_reported(self):
        rows = run_eval._diff_case("a-case", {"papers": 39, "route": "library"},
                                   self.BASE["cases"]["a-case"])
        assert rows == []

    def test_a_value_below_the_range_is_reported(self):
        rows = run_eval._diff_case("a-case", {"papers": 12, "route": "library"},
                                   self.BASE["cases"]["a-case"])
        assert rows and rows[0][1] == "papers" and rows[0][4] == "BELOW"

    def test_a_value_above_the_range_is_reported(self):
        rows = run_eval._diff_case("a-case", {"papers": 99, "route": "library"},
                                   self.BASE["cases"]["a-case"])
        assert rows and rows[0][4] == "ABOVE"

    def test_a_changed_route_is_reported(self):
        rows = run_eval._diff_case("a-case", {"papers": 38, "route": "live"},
                                   self.BASE["cases"]["a-case"])
        assert any(r[1] == "route" and r[4] == "CHANGED" for r in rows)

    def test_a_case_with_no_baseline_is_named_not_skipped(self):
        """A silently skipped new case is the same fail-open one layer down."""
        rows = run_eval._diff_case("new-case", {"papers": 5}, None)
        assert rows and rows[0][4] == "NEW CASE"

    def test_a_missing_baseline_file_says_so(self, capsys):
        assert run_eval._load_baseline("definitely-not-here.json") == {}
        assert "not found" in capsys.readouterr().out

    def test_an_unreadable_baseline_says_so(self, tmp_path, capsys):
        f = tmp_path / "bad.json"
        f.write_text("{not json", encoding="utf-8")
        assert run_eval._load_baseline(str(f)) == {}
        assert "unreadable" in capsys.readouterr().out

    def test_drift_does_not_change_the_exit_code(self, monkeypatch, tmp_path,
                                                 capsys):
        """Ranges spot drift; the floors gate. A run whose papers drifted but
        whose floors held must still exit 0, or every LLM-variance wobble
        becomes a red build and the signal is lost."""
        import app as app_mod

        monkeypatch.setattr(run_eval, "QUESTIONS", tmp_path / "q.json")
        run_eval.QUESTIONS.write_text(json.dumps({"cases": [
            {"id": "a-case", "question": "q", "force_route": "library",
             "expect": {"min_papers": 1}}]}), encoding="utf-8")

        def _builder(job_id, question, force_route=None, mode="review",
                     context_block="", prior_pmids=None):
            return {"level1": {"source": "rag",
                               "scored": [{"pmid": str(i), "title": "t"}
                                          for i in range(99)]}}

        monkeypatch.setattr(app_mod, "build_evidence_base_with_progress", _builder)
        monkeypatch.setattr(sys, "argv",
                            ["run_eval.py", "--diff",
                             "--baseline", self._baseline(tmp_path, monkeypatch)])
        rc = run_eval.main()
        out = capsys.readouterr().out
        assert "ABOVE" in out, "the drift was not reported"
        assert rc == 0, "drift must not gate the run; the floors do that"

    def test_a_floor_breach_still_exits_non_zero(self, monkeypatch, tmp_path,
                                                 capsys):
        import app as app_mod

        monkeypatch.setattr(run_eval, "QUESTIONS", tmp_path / "q.json")
        run_eval.QUESTIONS.write_text(json.dumps({"cases": [
            {"id": "a-case", "question": "q", "force_route": "library",
             "expect": {"min_papers": 50}}]}), encoding="utf-8")

        def _builder(job_id, question, force_route=None, mode="review",
                     context_block="", prior_pmids=None):
            return {"level1": {"source": "rag",
                               "scored": [{"pmid": "1", "title": "t"}]}}

        monkeypatch.setattr(app_mod, "build_evidence_base_with_progress", _builder)
        monkeypatch.setattr(sys, "argv",
                            ["run_eval.py", "--diff",
                             "--baseline", self._baseline(tmp_path, monkeypatch)])
        assert run_eval.main() == 1


class TestSynthesisBypassesTheAnswerCache:
    """The 2026-08-31 run printed "3/5 cases passed [SYNTHESIS]" having
    generated ONE answer. The other four were served from `query_cache` rows
    written the previous day, so the answer-level assertions were checked
    against text the code under test never produced — at $0, in seconds, and
    indistinguishable in the output from five clean runs."""

    def _run(self, monkeypatch, answer="An answer.", cost=0.99):
        import app as app_mod
        import endo_ai
        seen = {}

        class _Resp:
            status_code = 200
            data = b""
            def get_json(self):
                return self._j

        class _Client:
            def post(self, *a, **k):
                # Read the module attributes at the moment the request runs —
                # that is the only window in which the bypass is in force.
                seen["get"] = app_mod.get_cached_answer("q")
                seen["save"] = app_mod.save_query_cache("q", "a", [])
                r = _Resp(); r._j = {"job_id": "j1"}; return r

            def get(self, *a, **k):
                r = _Resp()
                r._j = {"status": "complete", "answer": answer,
                        "papers": [{"pmid": "1"}], "cost_usd": cost}
                return r

        monkeypatch.setattr(app_mod, "get_cached_answer",
                            lambda *a, **k: {"answer": "STALE", "papers": []})
        monkeypatch.setattr(app_mod, "save_query_cache",
                            lambda *a, **k: "WROTE")
        monkeypatch.setattr(app_mod.app, "test_client", lambda: _Client())
        monkeypatch.setattr(endo_ai, "LIBRARY_WRITE_BACK", True, raising=False)
        measured, failures = run_eval.run_case_with_synthesis(
            {"id": "c", "question": "q", "mode": "review",
             "force_route": "library", "expect": {}})
        return seen, measured, failures, app_mod

    def test_the_cache_returns_nothing_during_a_case(self, monkeypatch):
        seen, _m, _f, _app = self._run(monkeypatch)
        assert seen["get"] is None, \
            "a stored answer would be evaluated instead of a generated one"

    def test_the_cache_is_not_written_during_a_case(self, monkeypatch):
        """An eval answer served to a clinician later is the same mistake as
        write-back: the run mutating what it measures."""
        seen, _m, _f, _app = self._run(monkeypatch)
        assert seen["save"] is None

    def test_both_are_restored_afterwards(self, monkeypatch):
        _seen, _m, _f, app_mod = self._run(monkeypatch)
        assert app_mod.get_cached_answer("q") == {"answer": "STALE", "papers": []}
        assert app_mod.save_query_cache("q", "a", []) == "WROTE"

    def test_they_are_restored_even_when_the_case_raises(self, monkeypatch):
        import app as app_mod

        class _Client:
            def post(self, *a, **k):
                raise RuntimeError("boom")

        monkeypatch.setattr(app_mod, "get_cached_answer",
                            lambda *a, **k: {"answer": "STALE"})
        monkeypatch.setattr(app_mod, "save_query_cache", lambda *a, **k: "WROTE")
        monkeypatch.setattr(app_mod.app, "test_client", lambda: _Client())
        with pytest.raises(RuntimeError):
            run_eval.run_case_with_synthesis(
                {"id": "c", "question": "q", "force_route": "library",
                 "expect": {}})
        assert app_mod.get_cached_answer("q") == {"answer": "STALE"}
        assert app_mod.save_query_cache("q", "a", []) == "WROTE"

    def test_a_free_answer_is_a_failure_not_a_pass(self, monkeypatch):
        """Belt and braces on the bypass: if a cached answer reaches the
        assertions by some other route, the $0 cost gives it away."""
        _seen, _m, failures, _app = self._run(monkeypatch, cost=0.0)
        assert any("no synthesis happened" in f for f in failures)

    def test_a_paid_answer_is_not_flagged(self, monkeypatch):
        _seen, _m, failures, _app = self._run(monkeypatch, cost=0.42)
        assert not any("no synthesis happened" in f for f in failures)


class TestSynthesisModeDoesNotInventARoute:
    """`measured["route"]` was `pinned or "?"` — the REQUESTED route echoed
    back into a field named like a measurement, printed as "route  library".
    Read as evidence the case had been served from the library, it was only
    evidence that the case had ASKED to be. HANDOVER: routes are measured, not
    assumed."""

    def _run(self, monkeypatch, case):
        import app as app_mod
        import endo_ai

        class _Resp:
            status_code = 200
            data = b""
            def get_json(self):
                return self._j

        class _Client:
            def post(self, *a, **k):
                r = _Resp(); r._j = {"job_id": "j1"}; return r
            def get(self, *a, **k):
                r = _Resp()
                r._j = {"status": "complete", "answer": "text",
                        "papers": [{"pmid": "1"}], "cost_usd": 0.5}
                return r

        monkeypatch.setattr(app_mod.app, "test_client", lambda: _Client())
        monkeypatch.setattr(endo_ai, "LIBRARY_WRITE_BACK", True, raising=False)
        return run_eval.run_case_with_synthesis(case)

    def test_the_pin_is_not_reported_as_the_route(self, monkeypatch):
        measured, _f = self._run(monkeypatch, {
            "id": "c", "question": "q", "mode": "review",
            "force_route": "library", "expect": {}})
        assert measured["route"] is None, \
            "the requested route was reported as the measured one"

    def test_an_unmeasured_route_is_not_diffed(self):
        """None must not read as 'the route changed' against every baseline."""
        base = {"routes_observed": ["library"], "papers": {"min": 1, "max": 9}}
        rows = run_eval._diff_case("c", {"route": None, "papers": 5}, base)
        assert not any(r[1] == "route" for r in rows)

    def test_a_learn_case_says_its_pin_is_inert(self, monkeypatch, capsys):
        """/ask sends learn mode to build_deep_learning_module, which does its
        own per-module retrieval and never calls the pinned builder. The two
        laser cases — same question, pinned live and library — therefore run
        the identical pipeline under --synthesis-subset."""
        self._run(monkeypatch, {"id": "c", "question": "q", "mode": "learn",
                                "force_route": "library", "expect": {}})
        assert "ignores force_route" in capsys.readouterr().out

    def test_a_review_case_gets_no_such_note(self, monkeypatch, capsys):
        self._run(monkeypatch, {"id": "c", "question": "q", "mode": "review",
                                "force_route": "library", "expect": {}})
        assert "ignores force_route" not in capsys.readouterr().out


class TestTheFlagRateIsReadFromTheAuditLog:
    """The citation-support flag rate is the number this project has moved
    39.4% -> 8.5% -> 4.3%, and until now it was read by hand out of console
    scrollback. Two properties have to hold for the harness's version to be
    worth anything.

    First, the denominator must come from the audit log rather than the
    rendered answer: `_append_support_warnings` prints at most FIVE flags and
    never prints `checked`, and a curriculum runs the checker once per module
    against one stitched answer. Counting the rendered block would report
    5/unknown on a 24-flag curriculum.

    Second, 0 checked must not render as 0.0%. A checker that did not run and
    a checker that found nothing are the same shape in the data and opposite
    in meaning — this repo's bug class (d) exactly.
    """

    def _log(self, tmp_path, monkeypatch, records):
        p = tmp_path / "evidence_mapping.jsonl"
        p.write_text("".join(json.dumps(r) + "\n" for r in records),
                     encoding="utf-8")
        monkeypatch.setattr(run_eval, "EVMAP_LOG", p)
        return p

    def test_sums_every_check_since_the_offset(self, tmp_path, monkeypatch):
        self._log(tmp_path, monkeypatch, [
            {"function": "verify_citation_support", "checked": 10, "n_flagged": 2},
            {"function": "verify_citation_support", "checked": 8,  "n_flagged": 1},
        ])
        assert run_eval._support_since(0) == (18, 3, 2)

    def test_records_before_the_offset_are_not_counted(self, tmp_path, monkeypatch):
        """Case N+1 must not inherit case N's flags."""
        p = self._log(tmp_path, monkeypatch, [
            {"function": "verify_citation_support", "checked": 10, "n_flagged": 9},
        ])
        offset = p.stat().st_size
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"function": "verify_citation_support",
                                 "checked": 4, "n_flagged": 0}) + "\n")
        assert run_eval._support_since(offset) == (4, 0, 1)

    def test_the_fabrication_validator_is_not_counted(self, tmp_path, monkeypatch):
        """validate_evidence_mapping writes to the same stream and has no
        `checked` field of this meaning. Counting it would inflate the
        denominator with a different check's records."""
        self._log(tmp_path, monkeypatch, [
            {"function": "ask_clinical_question", "mode": "review",
             "attempt": 1, "passed": True, "score": 100},
            {"function": "verify_citation_support", "checked": 6, "n_flagged": 1},
        ])
        assert run_eval._support_since(0) == (6, 1, 1)

    def test_a_check_that_never_ran_reports_zero_checked(self, tmp_path, monkeypatch):
        """Zero pairs reached the checker. The caller prints NOT RUN for this;
        the one thing it must not be is 0/0 rendered as a clean 0.0%."""
        self._log(tmp_path, monkeypatch, [])
        assert run_eval._support_since(0) == (0, 0, 0)

    def test_a_truncated_last_line_does_not_kill_the_run(self, tmp_path, monkeypatch):
        """The log is appended to from several threads under a lock, but a
        crash mid-write leaves a partial line. Losing the eval to it would be
        worse than losing one record."""
        p = self._log(tmp_path, monkeypatch, [
            {"function": "verify_citation_support", "checked": 5, "n_flagged": 1},
        ])
        with p.open("a", encoding="utf-8") as fh:
            fh.write('{"function": "verify_citation_sup')
        assert run_eval._support_since(0) == (5, 1, 1)

    def test_a_missing_log_is_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(run_eval, "EVMAP_LOG", tmp_path / "nope.jsonl")
        assert run_eval._support_since(0) == (0, 0, 0)


class TestTheLiveSubsetIsLivePinned:
    """The whole citation-support history was measured on library-pinned cases.
    A 'live subset' that quietly contained a library case would report the same
    path again under a new name."""

    def test_every_live_subset_case_exists_and_is_pinned_live(self):
        _doc, cases = run_eval.load_cases()
        by_id = {c["id"]: c for c in cases}
        for cid in run_eval.LIVE_SUBSET:
            assert cid in by_id, f"{cid} is not in questions.json"
            assert by_id[cid].get("force_route") == "live", \
                f"{cid} is not pinned live"
            assert by_id[cid].get("mode", "review") == "review", \
                f"{cid} is not a Review case — force_route is inert in learn mode"

    def test_the_two_subsets_do_not_overlap(self):
        assert not (set(run_eval.LIVE_SUBSET) & set(run_eval.SYNTHESIS_SUBSET))


class TestTheFlagRateWindowExcludesOtherProcesses:
    """The window belongs to one case, and `evidence_mapping.jsonl` is one file
    shared by every process on the machine. A pytest run started while an eval
    was in flight put nine rows of `checked: 3, n_flagged: 0` inside one
    curriculum's window and reported 16/146 (11.0%) for what was 16/119
    (13.4%).

    A timing heuristic was tried first and rejected: the real burst was 1.3 s
    apart, which is also what four curriculum modules finishing on a thread
    pool look like. The pid is exact."""

    def _write(self, tmp_path, monkeypatch, rows):
        p = tmp_path / "evidence_mapping.jsonl"
        p.write_text("".join(json.dumps(
            {"function": "verify_citation_support", **r}) + "\n" for r in rows),
            encoding="utf-8")
        monkeypatch.setattr(run_eval, "EVMAP_LOG", p)

    def test_another_process_is_excluded_not_counted(self, tmp_path,
                                                     monkeypatch):
        """The exact shape of the contamination: nine foreign rows of 3 pairs
        each, alongside four real curriculum modules."""
        import os
        mine = os.getpid()
        rows = [{"checked": 3, "n_flagged": 0, "pid": mine + 1}] * 9
        rows += [{"checked": 30, "n_flagged": 4, "pid": mine}] * 4
        self._write(tmp_path, monkeypatch, rows)
        assert run_eval._support_since(0) == (120, 16, 4)

    def test_it_says_so_rather_than_silently_dropping_them(self, tmp_path,
                                                           monkeypatch, capsys):
        import os
        self._write(tmp_path, monkeypatch,
                    [{"checked": 3, "n_flagged": 0, "pid": os.getpid() + 1}])
        run_eval._support_since(0)
        out = capsys.readouterr().out
        assert "another process" in out and "EXCLUDED" in out

    def test_this_process_own_rows_are_kept(self, tmp_path, monkeypatch):
        import os
        self._write(tmp_path, monkeypatch,
                    [{"checked": 12, "n_flagged": 2, "pid": os.getpid()}])
        assert run_eval._support_since(0) == (12, 2, 1)

    def test_a_record_with_no_pid_is_counted(self, tmp_path, monkeypatch):
        """Rows written before the field existed. "We cannot tell" has to mean
        "in the window", or every historical comparison silently loses rows."""
        self._write(tmp_path, monkeypatch, [{"checked": 8, "n_flagged": 1}])
        assert run_eval._support_since(0) == (8, 1, 1)

    def test_four_modules_landing_together_are_not_treated_as_foreign(
            self, tmp_path, monkeypatch, capsys):
        """Curriculum modules run on a thread pool and their checks really do
        finish within a second of each other. Same pid, so nothing is dropped
        and nothing is warned about."""
        import os
        mine = os.getpid()
        self._write(tmp_path, monkeypatch,
                    [{"checked": 30, "n_flagged": 3, "pid": mine,
                      "ts": f"2026-09-01T01:38:24.{i}00000"} for i in range(4)])
        assert run_eval._support_since(0) == (120, 12, 4)
        assert "another process" not in capsys.readouterr().out


class TestTheSuiteDoesNotWriteToTheProductionAuditLog:
    def test_the_evmap_path_is_redirected_for_the_session(self):
        """Asserted on the live module attribute, not on conftest's source:
        the fixture is session-scoped and autouse, so if it stops applying
        this is the only thing that notices."""
        import endo_ai
        assert "evidence_mapping.jsonl" in endo_ai._EVMAP_LOG_PATH
        assert str(Path(endo_ai.__file__).parent) not in endo_ai._EVMAP_LOG_PATH

    def test_the_cost_log_is_redirected_too(self):
        import endo_ai
        assert str(Path(endo_ai.__file__).parent) not in endo_ai._COST_LOG_PATH
