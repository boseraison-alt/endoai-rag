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
did not reach the answer, and neither reason was ingestion. 60 level1 papers
cleared the similarity floor, the cap kept 25 BY SCORE, Karaoglan ranked 54th
of 60 by score, and 20 of the 25 that were kept were LESS similar to the
question than the one that was cut. The answer then said no prospective study
directly compares the two protocols.

CORRECTION, from A30a. Schwendicke was first written up here — and reported to
RB — as a recall miss belonging to query breadth. It is not. It sits at
similarity 0.635, rank 40 in the library by pure relevance and well above the
0.55 floor; what removed it was the SAME category error one layer up, in
`rag.search`'s `ORDER BY (score * 0.6 + similarity * 40) LIMIT 100`, where the
score carried 60 of the 100 available weight on a membership decision. All
three papers now enter the candidate pool. The lesson is the one A5b already
taught twice: measure the mechanism, do not infer it from the symptom.
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


class TestTheDifferentialMergeAlsoCapsByRelevance:
    """A30b, at a site A30a's enumeration missed — found while measuring A35k.

    The differential path retrieves once per candidate cause and merges the
    results into one per-tier union. That union was capped by SORTING ON SCORE
    and slicing, which is the same category error A5b found, in the one place
    where it costs most: the differential exists to carry evidence for the
    causes that are NOT the leading one, and the score does not know which
    candidate a paper was retrieved for.
    """

    def _merge_loop(self):
        src = (Path(__file__).parent.parent / "app.py").read_text(encoding="utf-8")
        i = src.index('"source": "differential"')
        j = src.rindex("for tier in TIER_ORDER:", 0, i)
        return src[j:i]

    def test_the_merge_caps_by_relevance(self):
        assert "cap_by_relevance(bucket, max_per_tier, tier)" in self._merge_loop()

    def test_the_merge_no_longer_slices_by_score(self):
        assert "bucket[:max_per_tier]" not in self._merge_loop()

    def test_the_merge_still_orders_by_score(self):
        """Invariant 1: the cap decides membership, the score ranks within."""
        body = self._merge_loop()
        assert 'bucket.sort(key=lambda x: x.get("score") or 0, reverse=True)' in body

    def test_a_live_route_paper_with_no_similarity_keeps_score_order(self):
        """Differential candidates can come back from the LIVE route, where no
        paper carries a similarity. The cap must then behave exactly as the
        score slice did, or this fix silently changes the live differential."""
        bucket = [{"pmid": str(i), "score": s, "level_key": "level1"}
                  for i, s in enumerate([10, 90, 50, 70, 30])]
        kept = app_mod.cap_by_relevance(bucket, 3, "level1")
        assert [p["score"] for p in kept] == [90, 70, 50]

    def test_similarity_beats_score_when_it_is_present(self):
        bucket = [paper("hi-sim-low-score", 0.80, 20),
                  paper("lo-sim-high-score", 0.56, 95)]
        kept = app_mod.cap_by_relevance(bucket, 1, "level1")
        assert kept[0]["pmid"] == "hi-sim-low-score"


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

    def test_all_three_named_papers_now_enter_the_candidate_pool(self):
        """A5b's done-when, plus the third paper A30b recovered. Asserted on
        the real KNN, which is the thing that was wrong: this test fails
        against the old score-weighted ORDER BY."""
        from rag import search as rag_search
        q = "retreatment in one visit versus two visits in endodontics"
        got = {str(r["pmid"]) for r in (rag_search(q, level_key=None, limit=100) or [])}
        for pmid, label in [("35488883", "Karaoglan 2022"),
                            ("34555421", "Toia 2022"),
                            ("28148534", "Schwendicke 2017")]:
            assert pmid in got, "%s is not in the top 100 by relevance" % label


# ── A30a — the rest of the sweep ──────────────────────────

class TestTheLivePathCapsByRelevanceToo:
    """`_apply_quality_threshold` is the live-path twin of the per-tier cap.
    The FLOOR is a quality bar and stays one — a paper below it is not good
    enough for any question. The CAP chooses among papers that have already
    cleared the bar, and that is a membership decision (rule 19)."""

    def _papers(self, n, floor_ok=True):
        # relevance order 1..n, score deliberately the inverse of relevance
        base = 60 if floor_ok else 10
        return [{"pmid": str(i), "pubmed_rank": i, "score": base + i}
                for i in range(1, n + 1)]

    def test_the_most_relevant_survive_not_the_highest_scoring(self):
        import endo_ai
        kept = endo_ai._apply_quality_threshold(self._papers(40), "review", "level1")
        ranks = sorted(p["pubmed_rank"] for p in kept)
        assert ranks[0] == 1, "the most relevant paper PubMed returned was cut"
        assert max(ranks) < 40, "it kept the tail, which is the score order"

    def test_survivors_come_back_ordered_by_score(self):
        """Membership by relevance, ranking by score — invariant 1 unchanged."""
        import endo_ai
        kept = endo_ai._apply_quality_threshold(self._papers(40), "review", "level1")
        scores = [p["score"] for p in kept]
        assert scores == sorted(scores, reverse=True)

    def test_a_paper_with_no_rank_sorts_last(self):
        """Absent evidence of relevance is not evidence of relevance. Live
        write-back rows have reached this function without one."""
        import endo_ai
        papers = self._papers(30) + [{"pmid": "no-rank", "score": 999}]
        kept = endo_ai._apply_quality_threshold(papers, "review", "level1")
        assert "no-rank" not in {p["pmid"] for p in kept}

    def test_a_sparse_tier_tops_up_by_relevance_not_by_score(self):
        """Below the floor we are saying quality is insufficient and taking
        what we can. Taking the best-SCORING of those fills a thin tier with
        whatever happened to score well rather than with what was asked.

        The fixture has to make the two orderings DISAGREE and give the top-up
        fewer slots than candidates — an earlier version had two papers and
        three slots, so both survived either way and the test proved nothing.
        MIN_PAPERS_KEPT is 3 and the level1 floor is 50."""
        import endo_ai
        papers = [{"pmid": "above", "pubmed_rank": 50, "score": 80}]
        # below the floor: the most relevant are the worst scoring
        papers += [{"pmid": "near-%d" % i, "pubmed_rank": i, "score": 10 + i}
                   for i in range(1, 4)]
        papers += [{"pmid": "far-%d" % i, "pubmed_rank": 90 + i, "score": 45 - i}
                   for i in range(1, 4)]
        kept = {p["pmid"] for p in
                endo_ai._apply_quality_threshold(papers, "review", "level1")}
        assert "above" in kept, "a paper over the quality floor was dropped"
        assert "near-1" in kept, (
            "the top-up took the best-scoring sub-floor papers, not the most "
            "relevant ones: kept %s" % sorted(kept))
        assert not {"far-1", "far-2", "far-3"} & kept, sorted(kept)

    def test_it_says_what_it_dropped(self, capsys):
        import endo_ai
        endo_ai._apply_quality_threshold(self._papers(40), "review", "level1")
        out = capsys.readouterr().out
        assert "[cap]" in out and "dropped" in out

    def test_it_stays_quiet_when_it_drops_nothing(self, capsys):
        import endo_ai
        endo_ai._apply_quality_threshold(self._papers(3), "review", "level1")
        assert "[cap]" not in capsys.readouterr().out

    def test_the_fetch_loop_records_pubmed_s_own_order(self):
        """The rank is the only relevance signal the live path has: these
        papers have no embedding yet, and esearch was asked for sort=relevance.
        Recorded BEFORE the score sort that used to destroy it."""
        src = (Path(__file__).parent.parent / "endo_ai.py").read_text(encoding="utf-8")
        body = src[src.index("def fetch_papers("):]
        body = body[:body.index("\ndef ")]
        assert "for _pm_rank, pmid in enumerate(ids, 1):" in body
        assert '"pubmed_rank":     _pm_rank,' in body
        assert body.index("enumerate(ids, 1)") < body.index(
            'scored_papers.sort(key=lambda x: x["score"]')


class TestTheAuthorityGuaranteeIsGone:
    """A30a found it inert; A32 deleted it. The protection it was supposed to
    provide is asserted in test_retrieval_consistency.py, on the union-of-max
    that actually provides it."""

    def test_it_is_not_in_the_module_any_more(self):
        assert not hasattr(app_mod, "ensure_authoritative")

    def test_the_retrieval_path_no_longer_calls_it(self):
        src = (Path(__file__).parent.parent / "app.py").read_text(encoding="utf-8")
        body = src[src.index("def build_evidence_base_with_progress("):]
        body = body[:body.index("    # ── Full PubMed fallback")]
        assert "ensure_authoritative" not in body

    def test_why_it_went_is_written_down_where_it_used_to_be(self):
        """A guarantee that cannot fire is worse than none because it gets
        described — it was, in three handover files. The note is what stops
        someone reinstating it without reading the measurement."""
        src = (Path(__file__).parent.parent / "app.py").read_text(encoding="utf-8")
        assert "A32 — `ensure_authoritative` was deleted here" in src
        assert "must NOT be fixed by reaching below the similarity" in src
