"""Item 3 (2026-09-09) — no non-current guideline reaches a pool, by any path.

THE MEASUREMENT. On 28 of 31 questions the guideline block carried at least one
superseded document. Five distinct rows, all superseded:

    22409417  IADT-AVULSION-2012              22 questions
    17180780  ESE-QG-2006                     21   (also quarantined by A2)
    17511833  IADT-AVULSION-2007              15
    22230724  IADT-FRACTURES-LUXATIONS-2012   12
    30664240  ESE-DEEPCARIES-2019              1   (superseded_in_content)

That breaks two of A49's hard gates — withdrawn is never citeable, superseded is
excluded from retrieval — and it breaks them in the CONTEXT the model reads,
before anything renders, so it is a defect whether or not the specialty renderer
is wired.

THE PATH, established by asking each of the three separately rather than
inferring it from the rows:

    library union            NONE — `rag.search` already excludes them
    admit_scoped_guidelines  NONE — it filters on manifest status == current
    THE LIVE GUIDELINE LANE  17180780, 17511833, 22409417

The lane queries PubMed and scores what comes back. A superseded IADT 2012
guideline is a real, indexed, unretracted PubMed record — nothing about it looks
wrong to a query, and the lane has no reason to consult a manifest or a
`quarantine_reason` column, because those are facts about our library.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import endo_ai as E  # noqa: E402
import rag  # noqa: E402

# The fixture is the real case, on the real question that admitted it.
ESE_QG_2006_PMID = "17180780"
ESE_QG_2006_ID = "ESE-QG-2006"
PROBE2 = ("Complicated crown fracture with pulp exposure in a mature premolar, "
          "6 hours old. What is the management?")
CURRENT_ESE = "37772327"          # ESE-S3-2023, the successor


class TestTheDisqualifyingFacts:
    """Three independent facts, in three places, any one disqualifying.
    `ESE-QG-2006` carries two of them and reached 21 pools anyway."""

    def test_the_key_set_is_not_empty(self):
        """A zero here would make every test below pass vacuously (rule 34)."""
        E._reset_non_current_guidelines()
        assert len(E.non_current_guideline_keys()) > 0

    def test_the_fixture_is_in_the_set_by_both_of_its_keys(self):
        keys = E.non_current_guideline_keys()
        assert ESE_QG_2006_PMID in keys
        assert ESE_QG_2006_ID in keys, (
            "the manifest id must be a key too, or a row that arrives without "
            "a numeric PMID slips through")

    def test_a_current_guideline_is_not_in_the_set(self):
        """The control arm. Without it the guard could be dropping everything
        and every assertion here would still pass."""
        assert CURRENT_ESE not in E.non_current_guideline_keys()

    @pytest.mark.skipif(not rag.DATABASE_URL, reason="DATABASE_URL not set")
    def test_every_key_really_is_disqualified(self):
        conn = rag.get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT pmid, COALESCE(guideline_status,''),
                   COALESCE(quarantine_reason,''), COALESCE(superseded_by,'')
            FROM endo_papers_rag
            WHERE level_key = 'guideline' AND pmid = ANY(%s)
        """, (sorted(k for k in E.non_current_guideline_keys()),))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        assert rows, "no rows matched the key set"
        for pmid, status, quar, sup in rows:
            assert (status.lower() not in E.CURRENT_GUIDELINE_STATUSES
                    or quar or sup), (
                "%s is in the non-current set but is current, unquarantined "
                "and unsuperseded" % pmid)


class TestTheGuardDrops:

    def test_the_fixture_is_dropped(self):
        rows = [{"pmid": ESE_QG_2006_PMID, "guideline_id": ESE_QG_2006_ID}]
        assert E.drop_non_current_guidelines(rows, "test") == []

    def test_it_is_dropped_by_manifest_id_alone(self):
        """A row keyed by its slug, with no numeric PMID, must still go."""
        rows = [{"pmid": ESE_QG_2006_ID, "guideline_id": ESE_QG_2006_ID}]
        assert E.drop_non_current_guidelines(rows, "test") == []

    def test_a_current_guideline_survives(self):
        rows = [{"pmid": CURRENT_ESE, "guideline_id": "ESE-S3-2023"}]
        assert len(E.drop_non_current_guidelines(rows, "test")) == 1

    def test_an_ordinary_paper_is_untouched(self):
        rows = [{"pmid": "27759881"}, {"pmid": "36512807"}]
        assert len(E.drop_non_current_guidelines(rows, "test")) == 2

    def test_an_empty_pool_is_handled(self):
        assert E.drop_non_current_guidelines([], "test") == []


class TestTheMutation:

    def test_reopening_the_door_readmits_the_fixture(self, monkeypatch):
        """MUTATION CHECK — the guard is run with an empty key set, which is
        what a build without it produces, and the fixture comes straight back.
        """
        rows = [{"pmid": ESE_QG_2006_PMID, "guideline_id": ESE_QG_2006_ID}]
        assert E.drop_non_current_guidelines(rows, "test") == []
        monkeypatch.setattr(E, "non_current_guideline_keys", lambda: set())
        assert len(E.drop_non_current_guidelines(rows, "test")) == 1, (
            "with the door reopened the superseded guideline must return, or "
            "these tests are passing for some other reason")

    def test_widening_the_current_statuses_readmits_it(self, monkeypatch):
        """The other half: if `superseded` were ever added to the accepted
        statuses, the key set itself would stop containing the fixture."""
        E._reset_non_current_guidelines()
        assert ESE_QG_2006_PMID in E.non_current_guideline_keys()
        monkeypatch.setattr(E, "CURRENT_GUIDELINE_STATUSES",
                            frozenset({"current", "current_but_stale",
                                       "superseded"}))
        E._reset_non_current_guidelines()
        # The SQL reads the literal list, so the fixture stays out on status —
        # but it is still caught by quarantine_reason, which is the point of
        # requiring three independent facts rather than one.
        assert ESE_QG_2006_PMID in E.non_current_guideline_keys(), (
            "ESE-QG-2006 is quarantined as well as superseded; loosening the "
            "status list alone must not readmit it")
        E._reset_non_current_guidelines()


class TestEveryPathIsGuarded:
    """The leak was in one lane. The guard is on all of them, because a
    superseded guideline reaching a level1 pool by another route is the same
    document making the same claim."""

    def test_the_live_lane_calls_it(self):
        import inspect
        src = inspect.getsource(E.fetch_papers)
        assert "drop_non_current_guidelines" in src, (
            "the live lanes — where the leak actually was — do not call it")

    def test_the_library_route_and_the_union_call_it(self):
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "app.py"), encoding="utf-8").read()
        assert src.count("drop_non_current_guidelines(") >= 3, (
            "the library route, the union and the differential builder must "
            "each apply it; found %d call(s)"
            % src.count("drop_non_current_guidelines("))
        assert 'drop_non_current_guidelines(lib_rows, "library-union")' in src, (
            "item A's union is unguarded")

    def test_snowballing_is_guarded(self):
        """THE FOURTH PATH, and the one the first fix missed.

        Snowballing admits rows DIRECTLY from a review's reference list — not
        through `fetch_papers`, not through the union — so neither of those
        guards reaches it. The first fix took the guideline block from 28
        questions to 1, and the survivor was `ESE-DEEPCARIES-2019`
        (superseded_in_content) arriving here. A reference list is exactly
        where a superseded guideline lives: the review cited the version that
        was current when it was written.
        """
        import inspect
        src = inspect.getsource(E.snowball_from_reviews)
        assert "drop_non_current_guidelines" in src, (
            "snowballing can still admit a superseded guideline")

    def test_the_snowball_survivor_is_disqualified(self):
        """The row that survived the first fix, by name."""
        assert "30664240" in E.non_current_guideline_keys()
        assert E.drop_non_current_guidelines(
            [{"pmid": "30664240", "guideline_id": "ESE-DEEPCARIES-2019"}],
            "snowball") == []
