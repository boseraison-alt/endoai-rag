"""
A5b — the per-tier cap decided membership with the score, and the score does
not know what was asked.

WHAT A5b ASSUMED, AND WHAT IS TRUE. The item names three papers the retreatment
answer missed and puts it down to their being absent from the library. Measured
before changing anything, that is right for one of three:

    35488883  Karaoglan 2022, Int Endod J   PRESENT, retrieved, similarity 0.648
    28148534  Schwendicke 2017, BMJ Open    PRESENT, in NO query's top 100
    34555421  Toia 2022, J Endod            ABSENT   (ingested, see scripts/)

So two thirds of the "missing" evidence was already in the library and still
did not reach the answer, by two mechanisms and neither of them ingestion.
This file is about the first: 60 level1 papers cleared the similarity floor,
the cap kept 25 BY SCORE, Karaoglan ranked 54th of 60 by score, and 20 of the
25 that were kept were LESS similar to the question than the one that was cut.
The answer then said no prospective study directly compares the two protocols.

Schwendicke is the second mechanism — a recall miss, not a cap — and belongs
with query breadth (A14/A24). It is asserted here only as the thing this fix
does NOT claim to solve, so nobody later reads A5b as closed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import app as app_mod


def paper(pmid, sim, score, tier="level1", title=""):
    return {"pmid": str(pmid), "similarity": sim, "score": score,
            "level_key": tier, "title": title}


class TestTheCapChoosesByRelevance:

    def test_the_most_relevant_survive_not_the_highest_scoring(self):
        """The retreatment case in miniature: a position statement scores 90
        and is barely on topic; the trial that answers the question scores 68
        and is the closest paper in the tier."""
        bucket = [paper("guideline-%d" % i, 0.57, 90.0) for i in range(25)]
        bucket.append(paper("35488883", 0.648, 67.8, title="Karaoglan 2022"))
        kept = {p["pmid"] for p in app_mod.cap_by_relevance(bucket, 25, "level1")}
        assert "35488883" in kept, (
            "the single most relevant paper in the tier was cut for scoring low")
        assert len(kept) == 25

    def test_a_bucket_within_the_cap_is_returned_whole(self):
        bucket = [paper(i, 0.9 - i / 100, 50 + i) for i in range(10)]
        assert len(app_mod.cap_by_relevance(bucket, 25, "level1")) == 10

    def test_it_does_not_mutate_the_caller_s_list(self):
        """The caller sorts the result by score afterwards. A cap that sorted
        in place would silently reorder the tier it was handed."""
        bucket = [paper(i, 0.5 + i / 100, 90 - i) for i in range(30)]
        before = [p["pmid"] for p in bucket]
        app_mod.cap_by_relevance(bucket, 25, "level1")
        assert [p["pmid"] for p in bucket] == before

    def test_ties_on_relevance_break_on_score(self):
        """Two equally relevant papers are separated by the better one, and
        the order is deterministic — a bare sort on a repeated float is not."""
        bucket = [paper("low", 0.70, 40.0), paper("high", 0.70, 80.0)]
        bucket += [paper("f-%d" % i, 0.60, 99.0) for i in range(24)]
        kept = [p["pmid"] for p in app_mod.cap_by_relevance(bucket, 25, "level1")]
        assert kept.index("high") < kept.index("low")
        assert "low" not in kept[:1]

    def test_a_missing_similarity_is_treated_as_zero_not_as_an_error(self):
        """Live write-back rows have reached the tier loop without one."""
        bucket = [paper(i, 0.8, 50) for i in range(25)]
        odd = {"pmid": "no-sim", "score": 99.0, "level_key": "level1"}
        kept = {p["pmid"] for p in app_mod.cap_by_relevance(bucket + [odd], 25)}
        assert "no-sim" not in kept

    def test_it_says_what_it_dropped(self, capsys):
        """Standing rule 5. A silent cap is exactly how the retreatment RCT
        vanished without leaving a trace to find it by."""
        bucket = [paper(i, 0.9 - i / 100, 50) for i in range(30)]
        app_mod.cap_by_relevance(bucket, 25, "level1")
        out = capsys.readouterr().out
        assert "level1" in out
        assert "30 above the floor" in out
        assert "dropped 5" in out
        assert "0.650" in out, "the log does not say how close the closest cut was"

    def test_a_cap_that_drops_nothing_says_nothing(self, capsys):
        """Its counterpart, so the line cannot become noise that is always
        there and therefore never read."""
        app_mod.cap_by_relevance([paper(i, 0.8, 50) for i in range(5)], 25)
        assert "[cap]" not in capsys.readouterr().out


class TestTheProductionPathUsesIt:
    """Standing rule 14 — the function is only worth having if the tier loop
    calls it, and a mutation removing it must fail a test."""

    def _tier_loop(self):
        src = (Path(__file__).parent.parent / "app.py").read_text(encoding="utf-8")
        i = src.index("            for tier in TIER_ORDER:")
        return src[i:src.index("all_scored.extend(bucket)", i)]

    def test_the_tier_loop_caps_by_relevance(self):
        body = self._tier_loop()
        assert "cap_by_relevance(bucket, MAX_RAG_PAPERS_PER_TIER, tier)" in body

    def test_the_tier_loop_still_orders_by_score(self):
        """Invariant 1 is untouched: the cap decides membership, the score
        still ranks within the tier and never across it."""
        body = self._tier_loop()
        assert 'bucket.sort(key=lambda x: x["score"], reverse=True)' in body

    def test_nothing_slices_the_bucket_behind_the_cap_s_back(self):
        body = self._tier_loop()
        assert "bucket[:MAX_RAG_PAPERS_PER_TIER]" not in body


class TestWhatA5bDoesAndDoesNotClose:

    def test_toia_2022_is_in_the_library(self):
        """A5b's done-when is both 2022 RCTs. This is the one that really was
        absent; the ingest script is scripts/ingest_retreatment_visits.py."""
        from rag import get_conn
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT pmid, year, level_key FROM endo_papers_rag "
                        "WHERE pmid = %s", ("34555421",))
            row = cur.fetchone()
        finally:
            cur.close()
            conn.close()
        assert row, "Toia 2022 (J Endod, 1-visit vs 2-visit RCT) is not ingested"
        assert row[2] == "level1", "an RCT banded as %r" % row[2]

    def test_karaoglan_2022_was_never_the_ingestion_problem(self):
        from rag import get_conn
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT pmid FROM endo_papers_rag WHERE pmid = %s",
                        ("35488883",))
            assert cur.fetchone(), (
                "Karaoglan 2022 has gone missing — A5b's mechanism has changed")
        finally:
            cur.close()
            conn.close()

    def test_the_schwendicke_miss_is_recorded_as_still_open(self):
        """It is below the floor on every generated query, so no cap change
        reaches it. Naming that here stops A5b being read as closed when the
        third paper is still missing for a different reason."""
        queue = (Path(__file__).parent.parent / "AGENT_QUEUE.md").read_text(
            encoding="utf-8")
        assert "Schwendicke" in queue
