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

        def _fake_builder(job_id, question, force_route=None):
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


class TestModeLabelling:
    def test_subset_ids_all_exist_in_questions(self):
        """A typo'd id would silently shrink the subset to nothing."""
        _doc, cases = run_eval.load_cases()
        ids = {c["id"] for c in cases}
        missing = [i for i in run_eval.SYNTHESIS_SUBSET if i not in ids]
        assert not missing, f"synthesis subset references unknown case ids: {missing}"
