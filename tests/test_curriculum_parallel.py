"""
Deep-Learning curriculum modules run in parallel — and nothing else changes.

Steps B (per-module retrieval) and C (per-module writing) used to run once per
module, one after the other. They are independent until the stitcher, so the
phase cost sum(module_time) when it only needed max(module_time). Measured on
the laser curriculum (real run 2026-08-30 10:45, reconstructed from
pubmed_audit.jsonl + cost_log.jsonl and recorded in the fixture):

    module   retrieval   writing    total
      1        44.7s     145.1s    189.8s
      2       107.9s     138.6s    246.5s
      3        70.7s     131.7s    202.4s
      4        63.5s     137.4s    200.9s
    serial     286.8s    552.7s    839.5s     critical path 246.5s

Parallelism is only safe if four things survive it, and each has a test here:

  1. CONCURRENCY   — the phase really overlaps; a stubbed 4-module run finishes
                     far short of the serial sum.
  2. ORDER         — module order in the output is syllabus order, whatever
                     order the workers happen to finish in. Completion order
                     must never reach the document.
  3. THE GATES     — a module below MIN_MODULE_PAPERS, and a module that states
                     numeric clinical parameters with no citations, still get
                     the "Module not generated" block. Parallelism must not
                     become a way past the evidence floor.
  4. ABORT         — a cancelled job stops instead of running to completion and
                     billing for it.

Everything is stubbed: no Anthropic call, no PubMed call, no database. The
syllabus, the search queries and the scored papers are all real data from that
laser run (tests/fixtures/curriculum_laser_run.json).

Run:  pytest tests/test_curriculum_parallel.py -v
"""

import json
import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai
from endo_ai import (
    build_deep_learning_module,
    CURRICULUM_MAX_WORKERS,
    MIN_MODULE_PAPERS,
    _CurriculumProgress,
    _is_cancellation,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "curriculum_laser_run.json")
    .read_text(encoding="utf-8")
)

QUESTION = FIXTURE["question"]
SYLLABUS = FIXTURE["syllabus"]
PAPERS   = FIXTURE["papers_by_tier"]

NOT_GENERATED = "Module not generated — insufficient evidence retrieved."


# ── helpers ───────────────────────────────────────────────────────────────

def evidence_for(n_papers: int) -> dict:
    """A tier-organised evidence dict holding `n_papers` REAL scored papers.

    Shape matches build_evidence_base()'s return: per-tier blocks plus a
    _summary whose all_scored is what module_has_usable_evidence counts.
    """
    flat = [p for tier in ("cochrane", "level1", "level2", "level3a",
                           "level3b", "level4", "level5")
            for p in PAPERS.get(tier, [])]
    chosen = flat[:n_papers]
    ev = {}
    for tier in ("cochrane", "level1", "level2", "level3a", "level3b",
                 "level4", "level5"):
        picked = [p for p in chosen if p.get("level_key") == tier]
        ev[tier] = {"text": "", "ids": [p["pmid"] for p in picked],
                    "scored": picked}
    ev["_summary"] = {
        "total_scored": len(chosen),
        "avg_score": (round(sum(p.get("score", 0) for p in chosen) / len(chosen), 1)
                      if chosen else 0),
        "all_scored": sorted(chosen, key=lambda x: x.get("score", 0), reverse=True),
        "synthesis_order": [],
    }
    return ev


def cited_script(title: str, evidence: dict) -> str:
    """A module body that cites real PMIDs from its own evidence, so it passes
    validate_module_output the way a healthy module does."""
    pmids = [p["pmid"] for p in evidence["_summary"]["all_scored"][:2]]
    marks = " ".join(f"[[PMID:{p}]]" for p in pmids)
    return (f"## Module — {title}\n\n"
            f"Er:YAG at 20 mJ, 15 Hz reduces intracanal E. faecalis {marks}.\n")


@pytest.fixture
def stub(monkeypatch):
    """Replace every paid/network stage of the curriculum builder.

    Returns a controller whose `.retrieval_delay` / `.writing_delay` (seconds,
    keyed by 0-based module index) shape the timing, `.paper_counts` shapes the
    evidence gate, and `.scripts` overrides what a module writes.
    """

    class Stub:
        def __init__(self):
            self.retrieval_delay = {}
            self.writing_delay   = {}
            self.paper_counts    = {}
            self.scripts         = {}
            self.default_papers  = 8
            self.default_delay   = 0.0
            self.write_cost      = 0.25
            self.stitched        = None       # what the stitcher was handed
            self.writes_done     = []         # module indices that finished step C
            self.writes_at_stitch = None      # how many had finished when D ran
            self.concurrent_peak = 0
            self._live           = 0
            self._lock           = threading.Lock()
            self.queries_seen    = []

        # -- instrumentation shared by both stubbed stages --
        def _enter(self):
            with self._lock:
                self._live += 1
                self.concurrent_peak = max(self.concurrent_peak, self._live)

        def _leave(self):
            with self._lock:
                self._live -= 1

        def _index_for(self, query):
            for i, m in enumerate(SYLLABUS):
                if m["search_query"] == query:
                    return i
            return None

        def build_evidence_base(self, topic, mode="review"):
            i = self._index_for(topic)
            self._enter()
            try:
                time.sleep(self.retrieval_delay.get(i, self.default_delay))
            finally:
                self._leave()
            with self._lock:
                self.queries_seen.append(topic)
            return evidence_for(self.paper_counts.get(i, self.default_papers))

        def write_curriculum_module(self, module, evidence, parent_question,
                                    idx, total):
            i = idx - 1
            self._enter()
            try:
                time.sleep(self.writing_delay.get(i, self.default_delay))
            finally:
                self._leave()
            script = self.scripts.get(i)
            if script is None:
                script = cited_script(module["title"], evidence)
            with self._lock:
                self.writes_done.append(i)
            return script, self.write_cost

        def stitch_curriculum(self, parent_question, modules_with_scripts,
                              all_evidence):
            self.writes_at_stitch = len(self.writes_done)
            self.stitched = list(modules_with_scripts)
            body = "\n\n".join(m["script"] for m in modules_with_scripts)
            return f"# {parent_question}\n\n{body}\n", 0.30

    s = Stub()
    monkeypatch.setattr(endo_ai, "generate_curriculum_syllabus",
                        lambda q, n_modules=4: ([dict(m) for m in SYLLABUS], 0.002))
    monkeypatch.setattr(endo_ai, "build_evidence_base", s.build_evidence_base)
    monkeypatch.setattr(endo_ai, "write_curriculum_module",
                        s.write_curriculum_module)
    monkeypatch.setattr(endo_ai, "stitch_curriculum", s.stitch_curriculum)
    # generate_search_terms is only reached by the broadening retry; if a test
    # exercises it, it must not hit Haiku.
    monkeypatch.setattr(endo_ai, "generate_search_terms",
                        lambda t, *a, **k: "broadened " + str(t)[:40])
    return s


# ── 1. concurrency ────────────────────────────────────────────────────────

class TestModulesRunConcurrently:

    def test_wall_time_is_far_under_the_serial_sum(self, stub):
        """Four modules, 0.4 s of work each in each stage — 3.2 s serial.

        On four workers the phase should cost about one module (0.8 s). The
        assertion is deliberately loose (< half the serial sum) so it pins
        "concurrent" without pinning machine speed.
        """
        for i in range(4):
            stub.retrieval_delay[i] = 0.4
            stub.writing_delay[i]   = 0.4
        serial = 4 * (0.4 + 0.4)

        t0 = time.perf_counter()
        answer, cost, evidence = build_deep_learning_module(QUESTION)
        elapsed = time.perf_counter() - t0

        assert elapsed < serial / 2, (
            f"module phase took {elapsed:.2f}s; serial sum is {serial:.2f}s — "
            "modules are not overlapping")
        assert answer
        assert stub.stitched is not None and len(stub.stitched) == 4

    def test_peak_concurrency_reaches_the_pool_bound(self, stub):
        """More than one module is genuinely in flight at the same time."""
        for i in range(4):
            stub.retrieval_delay[i] = 0.3
        build_deep_learning_module(QUESTION)
        assert stub.concurrent_peak >= min(4, CURRICULUM_MAX_WORKERS), (
            f"peak concurrency was {stub.concurrent_peak}")

    def test_pool_is_bounded(self, stub, monkeypatch):
        """The pool never runs more modules at once than CURRICULUM_MAX_WORKERS.

        Four concurrent NCBI retrieval streams and four concurrent DB borrowers
        is the ceiling this pipeline was sized for (DB_POOL_MAX defaults to 10).
        """
        monkeypatch.setattr(endo_ai, "CURRICULUM_MAX_WORKERS", 2)
        for i in range(4):
            stub.retrieval_delay[i] = 0.2
        build_deep_learning_module(QUESTION)
        assert stub.concurrent_peak <= 2, (
            f"peak concurrency {stub.concurrent_peak} exceeded the bound of 2")

    def test_stitcher_runs_only_after_every_module_completes(self, stub):
        """Step D must never see a partial curriculum.

        The staggered writing delays mean the modules settle 0.1 s apart, so a
        stitcher that started on the first completion would run with one or two
        writes done.
        """
        for i in range(4):
            stub.writing_delay[i] = 0.1 * (i + 1)
        build_deep_learning_module(QUESTION)
        assert stub.writes_at_stitch == 4, (
            f"stitcher ran with {stub.writes_at_stitch}/4 modules written")
        assert len(stub.stitched) == 4
        assert all(m.get("script") for m in stub.stitched)
        assert not any(m.get("not_generated") for m in stub.stitched)


# ── 2. deterministic order ────────────────────────────────────────────────

class TestOutputOrderIsDeterministic:

    def _titles_in(self, text):
        return re.findall(r"^## Module — (.+)$", text, re.MULTILINE)

    def test_order_is_syllabus_order_when_module_1_finishes_last(self, stub):
        """Invert the completion order: module 1 slowest, module 4 fastest.

        If completion order leaked into the document this is the run that would
        show it — the output would open with module 4.
        """
        stub.writing_delay = {0: 0.5, 1: 0.3, 2: 0.15, 3: 0.0}
        answer, _, _ = build_deep_learning_module(QUESTION)

        assert [m["title"] for m in stub.stitched] == \
               [m["title"] for m in SYLLABUS]
        assert self._titles_in(answer) == [m["title"] for m in SYLLABUS]

    def test_order_identical_across_two_opposite_completion_orders(self, stub):
        """Same syllabus, two mirrored timing profiles, one document order."""
        stub.writing_delay = {0: 0.4, 1: 0.25, 2: 0.1, 3: 0.0}
        first, _, _ = build_deep_learning_module(QUESTION)
        order_a = self._titles_in(first)

        stub.writing_delay = {0: 0.0, 1: 0.1, 2: 0.25, 3: 0.4}
        second, _, _ = build_deep_learning_module(QUESTION)
        order_b = self._titles_in(second)

        assert order_a == order_b == [m["title"] for m in SYLLABUS]

    def test_module_index_in_the_prompt_matches_syllabus_position(self, stub):
        """write_curriculum_module's idx is what the model is told it is writing
        ("module 3 of 4"). It must be the syllabus position, not a counter that
        increments in completion order."""
        seen = {}

        original = stub.write_curriculum_module

        def spy(module, evidence, parent_question, idx, total):
            seen[module["title"]] = (idx, total)
            return original(module, evidence, parent_question, idx, total)

        endo_ai.write_curriculum_module = spy
        stub.writing_delay = {0: 0.4, 1: 0.2, 2: 0.05, 3: 0.0}
        build_deep_learning_module(QUESTION)

        for pos, mod in enumerate(SYLLABUS):
            assert seen[mod["title"]] == (pos + 1, 4)

    def test_cost_is_the_same_regardless_of_completion_order(self, stub):
        """Cost is summed in index order, so it does not drift with scheduling."""
        stub.writing_delay = {0: 0.3, 1: 0.15, 2: 0.05, 3: 0.0}
        _, cost_a, _ = build_deep_learning_module(QUESTION)
        stub.writing_delay = {0: 0.0, 1: 0.05, 2: 0.15, 3: 0.3}
        _, cost_b, _ = build_deep_learning_module(QUESTION)
        assert cost_a == cost_b
        # syllabus 0.002 + 4 writes at 0.25 + stitch 0.30
        assert cost_a == pytest.approx(0.002 + 4 * 0.25 + 0.30)


# ── 3. the per-module gates still fail ────────────────────────────────────

class TestGatesSurviveParallelism:

    def test_module_below_the_evidence_floor_is_not_generated(self, stub):
        """Module 3 retrieves one paper — below MIN_MODULE_PAPERS — and the
        broadening retry finds no more. It must render the gap block, and the
        other three modules must be unaffected."""
        stub.paper_counts = {2: MIN_MODULE_PAPERS - 1}
        # the broadening retry re-queries with a different string; keep it thin
        stub.default_papers = 8
        original = stub.build_evidence_base

        def thin_retry(topic, mode="review"):
            if str(topic).startswith("broadened"):
                return evidence_for(MIN_MODULE_PAPERS - 1)
            return original(topic, mode=mode)

        endo_ai.build_evidence_base = thin_retry

        answer, _, _ = build_deep_learning_module(QUESTION)

        gap = stub.stitched[2]
        assert gap.get("not_generated") is True
        assert NOT_GENERATED in gap["script"]
        assert gap["title"] == SYLLABUS[2]["title"]
        assert NOT_GENERATED in answer
        for i in (0, 1, 3):
            assert not stub.stitched[i].get("not_generated")
            assert NOT_GENERATED not in stub.stitched[i]["script"]

    def test_numeric_parameters_without_citations_are_rejected(self, stub):
        """The original incident: a module emits "Er:YAG 20 mJ, 15 Hz" and
        "5.25% NaOCl, 2 mL, 60 s" with zero [[PMID:N]] markers. Evidence was
        present, so the floor does not catch it — validate_module_output must."""
        stub.scripts = {1: (
            "## Module — Laser Systems and Clinical Application Techniques\n\n"
            "Irradiate with Er:YAG at 20 mJ, 15 Hz for 30 s, then irrigate with "
            "5.25% NaOCl, 2 mL per canal for 60 s. Prepare to ISO #30/.04.\n"
        )}
        answer, _, _ = build_deep_learning_module(QUESTION)

        rejected = stub.stitched[1]
        assert rejected.get("not_generated") is True
        assert NOT_GENERATED in rejected["script"]
        assert "20 mJ" not in rejected["script"]
        assert "5.25%" not in answer

    def test_two_failing_modules_both_render_their_own_block(self, stub):
        """Concurrent failures must not collide — each gap block names its own
        module and its own search string."""
        stub.paper_counts = {0: 0, 3: 1}

        def thin_retry(topic, mode="review"):
            if str(topic).startswith("broadened"):
                return evidence_for(0)
            i = stub._index_for(topic)
            return evidence_for(stub.paper_counts.get(i, stub.default_papers))

        endo_ai.build_evidence_base = thin_retry

        build_deep_learning_module(QUESTION)

        assert stub.stitched[0].get("not_generated") is True
        assert stub.stitched[3].get("not_generated") is True
        assert SYLLABUS[0]["title"] in stub.stitched[0]["script"]
        assert SYLLABUS[3]["title"] in stub.stitched[3]["script"]
        assert stub.stitched[0]["script"] != stub.stitched[3]["script"]
        for i in (1, 2):
            assert not stub.stitched[i].get("not_generated")

    def test_a_failed_module_is_not_billed_for_writing(self, stub):
        """A module that never reaches step C must not add a writing cost."""
        stub.paper_counts = {2: 0}

        def thin_retry(topic, mode="review"):
            if str(topic).startswith("broadened"):
                return evidence_for(0)
            i = stub._index_for(topic)
            return evidence_for(stub.paper_counts.get(i, stub.default_papers))

        endo_ai.build_evidence_base = thin_retry

        _, cost, _ = build_deep_learning_module(QUESTION)
        assert cost == pytest.approx(0.002 + 3 * 0.25 + 0.30)


# ── 4. abort ──────────────────────────────────────────────────────────────

class TestAbortStopsTheRun:

    def test_cancelled_job_raises_and_never_reaches_the_stitcher(self, stub):
        """app.py's learn callback raises RuntimeError("Cancelled by user") when
        is_aborted(job_id) goes true. That must abort the build — the old _tick
        swallowed it into `except Exception: pass` and the run carried on to a
        full-price stitch."""
        for i in range(4):
            stub.retrieval_delay[i] = 0.2
            stub.writing_delay[i]   = 0.2

        state = {"aborted": False, "calls": 0}

        def cb(pct, msg):
            state["calls"] += 1
            if state["calls"] >= 3:
                state["aborted"] = True
            if state["aborted"]:
                raise RuntimeError("Cancelled by user")

        with pytest.raises(RuntimeError, match="Cancel"):
            build_deep_learning_module(QUESTION, progress_cb=cb)

        assert stub.stitched is None, "stitcher ran after the job was cancelled"

    def test_abort_stops_the_remaining_modules_early(self, stub, monkeypatch):
        """Modules that have not started yet must bail at their checkpoint
        instead of each paying for a retrieval and a write.

        Two workers, four modules: the first pair is in flight when the abort
        lands, so modules 3 and 4 are still queued and must never retrieve.
        """
        monkeypatch.setattr(endo_ai, "CURRICULUM_MAX_WORKERS", 2)
        stub.default_delay = 0.15
        started = []
        original = stub.build_evidence_base

        def counting(topic, mode="review"):
            started.append(topic)
            return original(topic, mode=mode)

        monkeypatch.setattr(endo_ai, "build_evidence_base", counting)

        def cb(pct, msg):
            # Let the phase get going, then cancel: the first two callbacks are
            # the syllabus tick and the "0 of 4" tick, before any module runs.
            if started:
                raise RuntimeError("Cancelled by user")

        with pytest.raises(RuntimeError, match="Cancel"):
            build_deep_learning_module(QUESTION, progress_cb=cb)

        assert len(started) <= 2, (
            f"{len(started)}/4 modules still retrieved after the abort")
        assert stub.stitched is None

    def test_a_hard_failure_in_one_module_stops_the_others(self, stub, monkeypatch):
        """Not every abort comes from the user. If one module dies outright, the
        run is already lost — the queued modules must bail at their abort_evt
        checkpoint rather than each paying for a retrieval and a write.
        """
        monkeypatch.setattr(endo_ai, "CURRICULUM_MAX_WORKERS", 1)
        stub.default_delay = 0.05
        started = []
        original = stub.build_evidence_base

        def exploding(topic, mode="review"):
            started.append(topic)
            if len(started) == 1:
                raise ValueError("Neon connection pool exhausted")
            return original(topic, mode=mode)

        monkeypatch.setattr(endo_ai, "build_evidence_base", exploding)

        with pytest.raises(ValueError, match="pool exhausted"):
            build_deep_learning_module(QUESTION)

        assert len(started) == 1, (
            f"{len(started)} modules retrieved after module 1 died")
        assert stub.stitched is None

    def test_a_broken_progress_callback_does_not_kill_a_paid_run(self, stub):
        """Cancellation propagates; a UI callback that merely throws does not.
        A run that has already spent money must not die because a status update
        failed."""
        def cb(pct, msg):
            raise ValueError("job store went away")

        answer, cost, _ = build_deep_learning_module(QUESTION, progress_cb=cb)
        assert answer and cost > 0
        assert stub.stitched is not None


# ── 5. progress reporting ─────────────────────────────────────────────────

class TestProgressStaysCoherent:

    def test_percentage_is_never_decreasing(self, stub):
        stub.writing_delay = {0: 0.4, 1: 0.2, 2: 0.05, 3: 0.0}
        seen = []
        build_deep_learning_module(QUESTION,
                                   progress_cb=lambda p, m: seen.append(p))
        assert seen == sorted(seen), f"progress went backwards: {seen}"

    def test_module_phase_reports_n_of_m_complete(self, stub):
        msgs = []
        build_deep_learning_module(QUESTION,
                                   progress_cb=lambda p, m: msgs.append(m))
        completions = [m for m in msgs if re.fullmatch(r"\d+ of 4 modules complete", m)]
        assert "4 of 4 modules complete" in completions
        counts = [int(m.split()[0]) for m in completions]
        assert counts == sorted(counts)
        assert counts[-1] == 4

    def test_reporter_clamps_a_backwards_percentage(self):
        seen = []
        p = _CurriculumProgress(lambda pct, msg: seen.append(pct))
        p.tick(50, "a")
        p.tick(20, "b")
        assert seen == [50, 50]

    def test_reporter_serialises_concurrent_callers(self):
        """The callback mutates jobs[job_id]; it must never run re-entrantly."""
        live = {"n": 0, "peak": 0}
        lock = threading.Lock()

        def cb(pct, msg):
            with lock:
                live["n"] += 1
                live["peak"] = max(live["peak"], live["n"])
            time.sleep(0.002)
            with lock:
                live["n"] -= 1

        p = _CurriculumProgress(cb)
        threads = [threading.Thread(target=p.module_complete, args=(8,))
                   for _ in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert live["peak"] == 1, "progress callback ran concurrently"

    def test_cancellation_detector(self):
        assert _is_cancellation(RuntimeError("Cancelled by user")) is True
        assert _is_cancellation(RuntimeError("cancel")) is True
        assert _is_cancellation(ValueError("Cancelled by user")) is False
        assert _is_cancellation(RuntimeError("connection reset")) is False
