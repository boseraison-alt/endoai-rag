"""
A42 — the routing floor and the evidence floor are two questions, so they are
two constants.

WHAT WAS MEASURED. Across the ten A38d runs, 181 cited paper-instances scored on
the similarity the floor actually sees:

    lowest cited 0.587   p05 0.628   p10 0.637   median 0.713

    floor   pool cut   cited cut
    0.55          0%    0  (0.0%)
    0.58          9%    0  (0.0%)
    0.60         18%    2  (1.1%)   <- shipped
    0.62         33%    8  (4.4%)
    0.65         51%   29 (16.0%)

18% of the pool was being carried into every synthesis prompt and cited 1.1% of
the time.

WHY TWO CONSTANTS AND NOT ONE RAISED. `similarity_floor` also gates ROUTING, and
app.py's own note says it and `min_relevant` are one setting to be tuned as a
pair. Raising it to 0.60 pushes 2 of 29 eval questions onto the LIVE route,
which costs MORE. Separating the constants is what makes this a single-variable
change.

A CORRECTION WORTH KEEPING. The first measurement scored cited papers with
question-only similarity and reported a lowest cited value of 0.4633 — below a
floor that demonstrably works. `multi_query_search` keeps the MAX similarity
across the question and every generated term (the A4 fix), and that maximum is
what the floor sees. Question-only similarity is a lower bound, and using it
would have reported 17 cited papers lost at 0.60 instead of 2 — a worse trade
than the real one, on the wrong quantity.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import app as app_mod

GATE = app_mod.RELEVANCE_GATE


class TestTheTwoFloorsAreDistinct:

    def test_both_constants_exist(self):
        assert "similarity_floor" in GATE and "evidence_floor" in GATE

    def test_the_evidence_floor_is_at_or_above_the_routing_floor(self):
        """The evidence floor filters what the ROUTING floor already admitted.
        Below it, it would filter nothing and the constant would be inert —
        which is the shape of the three dead checks Q1 and A32 found."""
        assert GATE["evidence_floor"] >= GATE["similarity_floor"]

    def test_the_routing_floor_did_not_move(self):
        """Raising it changes which questions go live, and live costs more.
        If this ever changes, min_relevant is re-read in the same commit."""
        assert GATE["similarity_floor"] == 0.55
        assert GATE["min_relevant"] == 12

    def test_the_evidence_floor_is_where_the_measurement_put_it(self):
        assert GATE["evidence_floor"] == 0.60


class TestTheProductionPathAppliesIt:
    """Standing rule 14 — the test drives the expression production evaluates,
    not a restatement of it. Two mutations survived while this was four lines
    inline in the library branch and the tests inspected source text."""

    def test_the_library_branch_calls_it(self):
        src = (Path(__file__).parent.parent / "app.py").read_text(encoding="utf-8")
        assert "rag_results_to_scored(apply_evidence_floor(relevant))" in src

    def test_the_unfiltered_list_no_longer_reaches_the_model(self):
        src = (Path(__file__).parent.parent / "app.py").read_text(encoding="utf-8")
        assert "rag_results_to_scored(relevant)" not in src, (
            "the routing list is reaching synthesis again — A42 measured that "
            "18% of it is cited 1.1% of the time")

    def test_the_gate_still_counts_at_the_routing_floor(self):
        """The whole point of two constants: the gate's arithmetic is
        unchanged, so no question changes route."""
        src = (Path(__file__).parent.parent / "app.py").read_text(encoding="utf-8")
        i = src.index("has_high_tier = any(")
        window = src[i - 400:i]
        assert "RAG_SIMILARITY_FLOOR" in window
        assert "evidence_floor" not in window


class TestTheFloorIsAppliedToTheRightNumber:
    """The floor sees the MAX similarity across the question and every
    generated term, not the question alone."""

    def _one_paper(self, monkeypatch, sims):
        import rag

        def fake(q, level_key=None, limit=100, **kw):
            return [{"pmid": "P1", "similarity": sims.get(q, 0.0),
                     "level_key": "level1", "score": 60, "year": 2020,
                     "title": "t", "abstract": "a"}]
        monkeypatch.setattr(rag, "search", fake)

    def test_the_best_similarity_wins_when_the_term_scores_higher(self, monkeypatch):
        self._one_paper(monkeypatch, {"the question": 0.46, "(a OR b) AND (c)": 0.71})
        out = app_mod.multi_query_search("the question", ["(a OR b) AND (c)"])
        assert float(out[0]["similarity"]) == pytest.approx(0.71), (
            "a paper the question alone scores below the floor can still be "
            "well above it for a generated term — that is the A4 fix, and it "
            "is the number the floor must be applied to")

    def test_the_best_similarity_wins_when_the_QUESTION_scores_higher(self, monkeypatch):
        """The mirror case, and the one that catches 'keep the last' — the
        question is embedded FIRST, so a merge that simply overwrites would
        return the boolean's lower score and quietly re-create the bug A4
        fixed (Cochrane CD005296 at 0.680 for the question, 0.546 for the
        compliant boolean that cut it)."""
        self._one_paper(monkeypatch, {"the question": 0.71, "(a OR b) AND (c)": 0.46})
        out = app_mod.multi_query_search("the question", ["(a OR b) AND (c)"])
        assert float(out[0]["similarity"]) == pytest.approx(0.71)

    def test_the_measurement_is_recorded_beside_the_constant(self):
        src = (Path(__file__).parent.parent / "app.py").read_text(encoding="utf-8")
        assert "lowest cited similarity 0.587" in src
        assert "0.4633" in src, (
            "the wrong-quantity correction must stay next to the number it "
            "corrects, or it will be made again")


class TestAFloorNeedsAFloor:
    """The A42a table was measured on the five A38d questions, and those are
    the ones where the library is DEEP. Across all 29 eval questions the same
    floor guts the thin ones:

        case-opening-sparse                 103 -> 6
        dens-evaginatus-premolar-diagnostic  56 -> 6
        pregnancy                           100 -> 12

    A pool of 6 manufactures the false evidence gap A5 was about. Generalising
    "the floor is free" from five deep-pool questions to all 29 was the error;
    the guard is the correction, and it costs 4 points of context saving
    (37% -> 33%) while being unable to cost a citation, because it only ever
    adds papers back.
    """

    def test_the_guard_exists_and_is_above_a33j_s_arithmetic_floor(self):
        """A33j: ~20 references is impossible below a pool of ~24, at the best
        citation rate ever observed. 40 leaves headroom above a bound that
        assumed a rate never seen twice."""
        assert GATE["min_evidence_papers"] >= 24
        assert GATE["min_evidence_papers"] == 40

    def _papers(self, sims):
        return [{"pmid": f"P{i}", "similarity": s} for i, s in enumerate(sims)]

    def test_a_deep_pool_is_cut_at_the_floor(self):
        papers = self._papers([0.70] * 50 + [0.56] * 30)
        out = app_mod.apply_evidence_floor(papers)
        assert len(out) == 50
        assert all(float(p["similarity"]) >= 0.60 for p in out)

    def test_a_thin_pool_is_not_cut_at_all(self, capsys):
        """20 papers, every one below the evidence floor. The floor would leave
        zero; the guard keeps all 20 — and says so."""
        papers = self._papers([0.56 + i * 0.001 for i in range(20)])
        out = app_mod.apply_evidence_floor(papers)
        assert len(out) == 20, "the guard must not cut a pool this thin"
        assert "[evidence_floor] only 0 of 20" in capsys.readouterr().out

    def test_the_guard_tops_up_to_exactly_the_minimum(self, capsys):
        papers = self._papers([0.70] * 10 + [0.56] * 60)
        out = app_mod.apply_evidence_floor(papers)
        assert len(out) == GATE["min_evidence_papers"]
        assert "keeping the 40 most similar instead" in capsys.readouterr().out

    def test_the_guard_only_ever_adds_papers_back(self):
        """It selects from the routing-admitted set, so it can never introduce
        a paper the old code excluded."""
        papers = self._papers([0.70] * 10 + [0.56] * 60)
        out = app_mod.apply_evidence_floor(papers)
        ids = {p["pmid"] for p in papers}
        assert {p["pmid"] for p in out} <= ids

    def test_the_top_up_is_by_similarity_not_by_order(self):
        """Standing rule 19: which papers survive is a relevance question. The
        input is deliberately shuffled so a top-up that trusted list order
        would keep the wrong ones."""
        papers = self._papers([0.56, 0.59, 0.57, 0.58])
        out = app_mod.apply_evidence_floor(papers, min_papers=2)
        assert [p["pmid"] for p in out] == ["P1", "P3"]

    def test_a_pool_smaller_than_the_minimum_is_returned_whole(self):
        papers = self._papers([0.56, 0.57, 0.58])
        assert len(app_mod.apply_evidence_floor(papers)) == 3

    def test_an_empty_pool_does_not_explode(self):
        assert app_mod.apply_evidence_floor([]) == []

    def test_the_cut_is_logged(self, capsys):
        """Standing rule 5. A silent cut is how the retreatment RCT vanished."""
        app_mod.apply_evidence_floor(self._papers([0.70] * 50 + [0.56] * 30))
        out = capsys.readouterr().out
        assert "[evidence_floor]" in out and "best dropped 0.560" in out

    def test_nothing_is_logged_when_nothing_is_cut(self, capsys):
        app_mod.apply_evidence_floor(self._papers([0.70] * 50))
        assert "[evidence_floor]" not in capsys.readouterr().out

    def test_the_measurement_that_forced_the_guard_is_recorded(self):
        src = (Path(__file__).parent.parent / "app.py").read_text(encoding="utf-8")
        assert "case-opening-sparse" in src
        assert "103 papers ->   6" in src
