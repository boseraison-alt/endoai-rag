"""The maintenance composer.

`scripts/monthly_maintenance.py` runs three stages that each rewrite or read
the whole library. Two properties are load-bearing and neither is visible from
reading the script's output:

  * a run without `--apply` must not pass `--apply` to ANY sub-script. The
    dry-run guarantee lives in the sub-scripts, and this script's only job is
    not to defeat it.
  * the order is backfill -> rescore -> eval, because the COI penalty is
    applied at rescore FROM the `coi_status` the backfill writes. Rescoring
    first scores the new rows against provenance they do not have yet.

Both are asserted by capturing the argv of every stage rather than by reading
the source, so a refactor that keeps the strings and loses the behaviour still
fails.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest

import monthly_maintenance as mm


class _Proc:
    def __init__(self, stdout="", code=0):
        self.stdout, self.stderr, self.returncode = stdout, "", code


@pytest.fixture
def calls(monkeypatch):
    """Capture every stage's argv; run nothing."""
    seen = []

    def _fake_run(argv, **kw):
        seen.append(list(argv))
        return _Proc("[pubmed] 3 papers with numeric PMIDs\n0/0 cases passed\n")

    monkeypatch.setattr(mm.subprocess, "run", _fake_run)
    return seen


def _main(monkeypatch, tmp_path, *args):
    monkeypatch.setattr(sys, "argv", ["monthly_maintenance.py",
                                      "--out", str(tmp_path), *args])
    return mm.main()


class TestTheDryRunGuarantee:
    def test_a_dry_run_passes_apply_to_nothing(self, calls, monkeypatch, tmp_path):
        _main(monkeypatch, tmp_path)
        assert calls, "no stages ran"
        for argv in calls:
            assert "--apply" not in argv, f"dry run passed --apply to {argv}"

    def test_apply_reaches_the_writing_stages(self, calls, monkeypatch, tmp_path):
        _main(monkeypatch, tmp_path, "--apply")
        writers = [a for a in calls
                   if any("backfill" in str(x) or "rescore" in str(x) for x in a)]
        assert len(writers) == 2
        for argv in writers:
            assert "--apply" in argv

    def test_the_eval_never_gets_apply_even_under_apply(self, calls, monkeypatch,
                                                        tmp_path):
        """`--apply` is a write flag for the migrations. run_eval has no such
        flag, and handing it one would be a crash at 3am rather than a no-op."""
        _main(monkeypatch, tmp_path, "--apply")
        ev = [a for a in calls if any("run_eval" in str(x) for x in a)]
        assert ev and "--apply" not in ev[0]

    def test_the_report_says_it_was_a_dry_run(self, calls, monkeypatch, tmp_path):
        _main(monkeypatch, tmp_path)
        report = (tmp_path / "report.md").read_text(encoding="utf-8")
        assert "DRY RUN" in report and "Nothing was written" in report


class TestStageOrder:
    def test_backfill_runs_before_rescore(self, calls, monkeypatch, tmp_path):
        """Provenance feeds scoring: the COI penalty is applied at rescore from
        the stored coi_status the backfill has just written."""
        _main(monkeypatch, tmp_path)
        joined = [" ".join(str(x) for x in a) for a in calls]
        i_back = next(i for i, s in enumerate(joined) if "backfill" in s)
        i_score = next(i for i, s in enumerate(joined) if "rescore" in s)
        assert i_back < i_score

    def test_the_eval_runs_last(self, calls, monkeypatch, tmp_path):
        _main(monkeypatch, tmp_path)
        joined = [" ".join(str(x) for x in a) for a in calls]
        assert "run_eval" in joined[-1]

    def test_skip_eval_drops_only_the_eval(self, calls, monkeypatch, tmp_path):
        _main(monkeypatch, tmp_path, "--skip-eval")
        joined = [" ".join(str(x) for x in a) for a in calls]
        assert len(joined) == 2
        assert not any("run_eval" in s for s in joined)


class TestTheEvalStageCannotSynthesise:
    """A maintenance run must never generate an answer. Cost is one reason; the
    other is that an eval answer must not be left anywhere a clinician could be
    served it, which is why run_case_with_synthesis neutralises the cache."""

    @pytest.mark.parametrize("flag", ["--synthesis-subset", "--live-subset"])
    def test_no_synthesis_flag_is_ever_passed(self, calls, monkeypatch,
                                              tmp_path, flag):
        _main(monkeypatch, tmp_path)
        for argv in calls:
            assert flag not in argv

    def test_the_eval_is_explicitly_cheap(self, calls, monkeypatch, tmp_path):
        """--cheap is the default in run_eval, so passing it changes nothing at
        runtime. It is passed anyway: the flag is the record of intent, and a
        future default flip must not silently turn this into a $25 job."""
        _main(monkeypatch, tmp_path)
        ev = next(a for a in calls if any("run_eval" in str(x) for x in a))
        assert "--cheap" in ev


class TestTheProvenanceWindow:
    def test_the_window_is_passed_to_the_backfill(self, calls, monkeypatch,
                                                  tmp_path):
        _main(monkeypatch, tmp_path, "--since-days", "45")
        back = next(a for a in calls if any("backfill" in str(x) for x in a))
        assert "--since-days" in back
        assert back[back.index("--since-days") + 1] == "45"

    def test_the_default_window_overlaps_a_month(self, monkeypatch, tmp_path,
                                                 calls):
        """35 days, not 30. A monthly job that slips by a week must re-examine
        the days it already saw rather than skip them — a retraction found in
        the gap is found by nobody."""
        _main(monkeypatch, tmp_path)
        back = next(a for a in calls if any("backfill" in str(x) for x in a))
        assert int(back[back.index("--since-days") + 1]) > 30


class TestFailuresAreReported:
    def test_a_failing_stage_sets_the_exit_code_and_the_report(
            self, monkeypatch, tmp_path):
        def _fake_run(argv, **kw):
            bad = any("rescore" in str(x) for x in argv)
            return _Proc("boom" if bad else "ok", 3 if bad else 0)

        monkeypatch.setattr(mm.subprocess, "run", _fake_run)
        rc = _main(monkeypatch, tmp_path)
        assert rc == 1
        report = (tmp_path / "report.md").read_text(encoding="utf-8")
        assert "did not exit 0" in report
        assert "RESCORE" in report

    def test_stage_json_records_every_stage(self, calls, monkeypatch, tmp_path):
        _main(monkeypatch, tmp_path)
        rows = json.loads((tmp_path / "stages.json").read_text(encoding="utf-8"))
        assert len(rows) == 3
        assert all("exit" in r and "seconds" in r for r in rows)
        assert not any("output" in r for r in rows), \
            "stages.json should hold the index, not a copy of every log"


class TestTheReportReadsTheStagesOwnOutput:
    def test_nothing_to_change_is_reported_as_zero(self):
        """A rescore with no changes prints no number. Reporting nothing there
        leaves the report silent about a stage that ran clean, which reads the
        same as a stage that did not run."""
        got = dict(mm._extract("RESCORE",
                               "[rescore] 2336 papers eligible for faithful "
                               "rescoring\n[rescore] nothing to change\n"))
        assert got["scores changing"] == "0"
        assert got["papers rescored"] == "2336"

    def test_a_real_change_count_wins_over_the_fallback(self):
        got = dict(mm._extract("RESCORE",
                               "[rescore] 100 papers eligible\n"
                               "[rescore] changed: 17   unchanged: 83\n"))
        assert got["scores changing"] == "17"

    def test_a_retraction_among_new_arrivals_is_escalated(self, monkeypatch,
                                                          tmp_path):
        def _fake_run(argv, **kw):
            if any("backfill" in str(x) for x in argv):
                return _Proc("[pubmed] 40 papers with numeric PMIDs\n"
                             "      2   RETRACTED\n"
                             "      1   SUPERSEDED by a newer version\n")
            return _Proc("ok")

        monkeypatch.setattr(mm.subprocess, "run", _fake_run)
        _main(monkeypatch, tmp_path)
        report = (tmp_path / "report.md").read_text(encoding="utf-8")
        assert "Needs a human" in report
        assert "still being served" in report

    def test_a_clean_backfill_escalates_nothing(self, calls, monkeypatch, tmp_path):
        _main(monkeypatch, tmp_path)
        report = (tmp_path / "report.md").read_text(encoding="utf-8")
        assert "Needs a human" not in report
