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


# ── the over-block the v8 baseline found ─────────────────────────────────────
# The guard above shipped reading `quarantine_reason <> ''` as disqualifying.
# One quarantine reason is not a verdict: when a document is re-keyed from its
# manifest slug to its real PMID, the old row stays behind as a forwarding stub
# carrying `re-keyed: this document is <pmid>` — and status `current`. Read as
# a disqualification, the stub put its own SLUG into the block set, and the
# guard then dropped the only row carrying that slug: the current document.
#
# The v8 baseline measured the cost: 215 of 778 drop events (28%) were current
# guidelines. `COCHRANE-CD005296` — PMID 36512807, the row
# `single-vs-multiple-visit` pins with must_include_pmid — was blocked 80
# times, and `AAE-TRAUMA-2026`, the document item E's crown-fracture probe
# watches, three times.
#
# These run on FIXTURES, not the database. The over-block existed for hours in
# a guard whose tests all passed, because every one of them asked the database
# what it thought rather than asking the rule what it does.
ROW = ("pmid", "gid", "status", "quar", "sup")


def row(pmid, gid="", status="current", quar="", sup=""):
    return (pmid, gid, status, quar, sup)


class TestAPointerIsNotADocument:

    def test_a_rekey_stub_does_not_block_its_own_slug(self):
        """The defect, minimally: stub alone, target current and elsewhere."""
        rows = [row("COCHRANE-CD005296", "",
                    quar="re-keyed: this document is 36512807")]
        lookup = [row("36512807", "COCHRANE-CD005296")]
        keys = E._disqualified_keys(rows, lookup)
        assert "COCHRANE-CD005296" not in keys, (
            "the forwarding stub blocked the current document it points at")
        assert "36512807" not in keys

    def test_the_target_may_live_on_another_ladder(self):
        """CD005296 re-keys onto `cochrane`, not `guideline`. The first fix
        looked for targets among the guideline rows only, could not find it,
        and treated the unresolvable pointer as disqualifying — so it still
        blocked the two Cochrane reviews it was written to release."""
        rows = [row("COCHRANE-CD005296", "",
                    quar="re-keyed: this document is 36512807")]
        assert "COCHRANE-CD005296" in E._disqualified_keys(rows, []), (
            "an unresolvable pointer must stay blocked — a pointer into "
            "nothing is not evidence the document is fine")
        assert "COCHRANE-CD005296" not in E._disqualified_keys(
            rows, [row("36512807", "COCHRANE-CD005296")])

    def test_a_stub_pointing_at_a_superseded_document_still_blocks(self):
        """THE OTHER HALF, and the one that makes this safe. The
        `ESE-PS-VPT-2019` stub says `duplicate_of:30664240`, and 30664240 is
        superseded_in_content — so the old slug must stay refused."""
        rows = [row("ESE-PS-VPT-2019", "", status="",
                    quar="duplicate_of:30664240"),
                row("30664240", "ESE-DEEPCARIES-2019",
                    status="superseded_in_content",
                    sup="EFCD-ESE-ORCA-DEEPCARIES-2026")]
        keys = E._disqualified_keys(rows)
        assert "ESE-PS-VPT-2019" in keys
        assert "30664240" in keys
        assert "ESE-DEEPCARIES-2019" in keys

    def test_a_current_stub_pointing_at_a_superseded_document_blocks(self):
        """Status `current` on the stub must not rescue it: the stub is not
        the document, so the target's supersession is what counts."""
        rows = [row("OLD-SLUG-2001", "", status="current",
                    quar="re-keyed: this document is 17180780"),
                row("17180780", "ESE-QG-2006", status="superseded",
                    sup="ESE-S3-2023")]
        assert "OLD-SLUG-2001" in E._disqualified_keys(rows)

    def test_a_real_quarantine_is_still_a_verdict(self):
        """Only the two forwarding forms are pointers. Everything else in
        `quarantine_reason` disqualifies exactly as before."""
        for reason in ("withdrawn: the publisher has retracted it",
                       "no_such_document: A2: no AAE document",
                       "wrong_year: A2: stored as 2021",
                       "draft: not a published guideline"):
            keys = E._disqualified_keys([row("X-2020", "", quar=reason)])
            assert "X-2020" in keys, "%r stopped disqualifying" % reason

    def test_status_and_supersession_still_disqualify_alone(self):
        assert "A" in E._disqualified_keys([row("A", "", status="superseded")])
        assert "B" in E._disqualified_keys([row("B", "", status="withdrawn")])
        assert "C" in E._disqualified_keys([row("C", "", sup="D-2025")])
        assert "E" in E._disqualified_keys([row("E", "", status="")])

    def test_a_clean_current_row_is_never_blocked(self):
        """The control arm. Without it every assertion here could be passing
        because the function blocks nothing at all."""
        assert E._disqualified_keys([row("37772327", "ESE-S3-2023")]) == set()

    def test_a_pointer_cycle_terminates_and_blocks(self):
        """Two stubs pointing at each other must not recurse forever, and an
        unresolvable chain is disqualifying rather than silently clean."""
        rows = [row("SLUG-A", "", quar="re-keyed: this document is SLUG-B"),
                row("SLUG-B", "", quar="re-keyed: this document is SLUG-A")]
        keys = E._disqualified_keys(rows)
        assert "SLUG-A" in keys and "SLUG-B" in keys

    def test_the_pointer_parser_reads_both_stored_forms(self):
        assert E._pointer_target(
            "re-keyed: this document is 36512807") == "36512807"
        assert E._pointer_target("duplicate_of:30664240") == "30664240"
        assert E._pointer_target(
            "re-keyed: this document is AAE-TRAUMA-2026") == "AAE-TRAUMA-2026"
        assert E._pointer_target("withdrawn: the publisher pulled it") is None
        assert E._pointer_target("") is None
        assert E._pointer_target(None) is None


class TestTheNineReleasedRows:
    """By name, against the live database. These are the documents the guard
    was blocking, and each one is current."""

    RELEASED = ["AAE-MRONJ-2026", "AAE-TRAUMA-2026", "AAE-VPT-2021",
                "ACP-PARAMETERS-OF-CARE-2020", "COCHRANE-CD004969",
                "COCHRANE-CD005296", "ESE-ECR-2018",
                "ESE-EXTRUSION-REPLANT-2021", "ESE-TRAUMA-2021"]

    @pytest.mark.skipif(not rag.DATABASE_URL, reason="DATABASE_URL not set")
    def test_none_of_the_nine_is_blocked(self):
        E._reset_non_current_guidelines()
        keys = E.non_current_guideline_keys()
        assert keys, "empty block set would make this pass vacuously"
        still = [k for k in self.RELEASED if k in keys]
        assert not still, "still blocking current guideline(s): %s" % still

    @pytest.mark.skipif(not rag.DATABASE_URL, reason="DATABASE_URL not set")
    def test_the_pinned_cochrane_review_survives_the_guard(self):
        """PMID 36512807 is `single-vs-multiple-visit`'s must_include_pmid and
        the batch named it as a criterion to leave alone. The guard was
        dropping the library's copy of it 80 times across the v8 runs."""
        kept = E.drop_non_current_guidelines(
            [{"pmid": "36512807", "guideline_id": "COCHRANE-CD005296"}],
            "test")
        assert len(kept) == 1

    @pytest.mark.skipif(not rag.DATABASE_URL, reason="DATABASE_URL not set")
    def test_the_five_leaked_rows_are_still_blocked(self):
        """Item 3's whole point, re-asserted after loosening the rule."""
        E._reset_non_current_guidelines()
        keys = E.non_current_guideline_keys()
        for pmid in ("22409417", "17180780", "17511833", "22230724",
                     "30664240"):
            assert pmid in keys, "%s came back" % pmid
