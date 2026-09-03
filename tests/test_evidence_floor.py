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
    """Standing rule 14 — the constant is only worth having if the retrieval
    path reads it, and a mutation removing it must fail a test."""

    def _library_branch(self):
        src = (Path(__file__).parent.parent / "app.py").read_text(encoding="utf-8")
        i = src.index("            all_rag = rag_results_to_scored(")
        j = src.rindex('_ev_floor = RELEVANCE_GATE', 0, i)
        return src[j:i + 120]

    def test_the_model_sees_the_evidence_floor_not_the_routing_floor(self):
        body = self._library_branch()
        assert 'RELEVANCE_GATE["evidence_floor"]' in body
        assert "rag_results_to_scored(_for_model)" in body

    def test_the_unfiltered_list_no_longer_reaches_the_model(self):
        body = self._library_branch()
        assert "rag_results_to_scored(relevant)" not in body, (
            "the routing list is reaching synthesis again — A42 measured that "
            "18% of it is cited 1.1% of the time")

    def test_it_logs_what_it_dropped(self):
        """Standing rule 5. A silent cut is how the retreatment RCT vanished."""
        assert "[evidence_floor]" in self._library_branch()

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
