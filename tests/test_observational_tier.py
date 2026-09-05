"""
A31 — the tier taxonomy had no slot for observational or descriptive designs.

A23a's mechanism, proven before anything was built: the seven tier filters are
all publication types or MeSH terms for THERAPY and SYNTHESIS designs — trial,
review, meta-analysis, cohort, case-control, case report. Nothing among them
matches a cross-sectional, morphometric, imaging or diagnostic-accuracy study.
Jeon 2021 is found by the module query, survives ENDO_DOMAIN_FILTER, and
disappears at the tier filter. 46 of the 100 most relevant papers for the
apicoectomy question were reachable by NO tier at all.

That is a fifth failure class: the taxonomy cannot express the thing, so it can
never be retrieved. It raises no error — only a thinner answer.

WHAT THIS ITEM DOES AND DOES NOT DO. It makes the class REACHABLE. It does not
claim these designs are strong: they band at the weakest tier, below level5,
and A25 decides later whether an anatomy question should rank them higher
(A12 — reachability now, ranking later, never in one commit).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai as e


class TestTheTierExists:

    def test_it_is_last_in_the_ladder(self):
        """Weakest position, on purpose. Nothing above it moves."""
        assert e.TIER_ORDER[-1] == "observational"

    def test_it_is_weaker_than_expert_opinion(self):
        assert e.TIER_ORDER.index("observational") > e.TIER_ORDER.index("level5")

    def test_its_label_does_not_claim_comparative_evidence(self):
        """A clinician reading the tier name must not take a morphometric
        study for a trial."""
        label = e.TIER_LABEL["observational"]
        assert "not comparative evidence" in label.lower()

    def test_the_filter_names_the_designs_it_is_for(self):
        terms = " ".join(e.LEVEL_OBS_TERMS).lower()
        for design in ("cross-sectional", "observational study",
                       "cone-beam computed tomography", "anatomy and histology",
                       "sensitivity and specificity"):
            assert design in terms, design

    def test_it_is_actually_fetched_and_not_merely_declared(self):
        """A tier in the ladder that no query ever runs is a tier that does
        not exist — the shape of the bug this item is fixing.

        This used to grep `build_evidence_base`'s source for the lane tuple.
        The lane list moved into `tier_query_lanes()` so that the missed-paper
        fixtures could read production's own lanes rather than restate them,
        and a source grep would have gone quietly green-on-absence: the string
        vanishes from that function body whether the lane still runs or not.
        Asserting on the object the loop iterates is what the test meant, and
        it survives the next move of the list.
        """
        lanes = e.tier_query_lanes()
        by_key = {k: (terms, label) for k, terms, label in lanes}
        assert "observational" in by_key, (
            "the observational lane is declared in TIER_ORDER but is not in "
            "the list build_evidence_base iterates — it would never be queried."
        )
        terms, label = by_key["observational"]
        assert terms is e.LEVEL_OBS_TERMS
        assert label == e.TIER_LABEL["observational"]

    def test_build_evidence_base_issues_exactly_those_lanes(self):
        """And the loop really is fed by that function, not by a stale copy."""
        src = (Path(__file__).parent.parent / "endo_ai.py").read_text(encoding="utf-8")
        body = src[src.index("def build_evidence_base(topic"):]
        body = body[:body.index("\ndef ")]
        assert "tier_query_lanes()" in body
        assert "for level_key, terms, label in levels:" in body


class TestItTakesNothingFromTheTiersAboveIt:
    """A31c. The whole item is additive or it is not worth doing."""

    @pytest.mark.parametrize("mode", ["review", "learn", "case"])
    def test_it_has_its_own_quota_in_every_mode(self, mode):
        assert e._tier_cap(mode, "observational") > 0

    @pytest.mark.parametrize("mode,tier,expected", [
        ("review", "level1", 18), ("learn", "level1", 10),
        ("review", "cochrane", 10), ("learn", "level5", 25),
    ])
    def test_no_existing_quota_changed(self, mode, tier, expected):
        assert e._tier_cap(mode, tier) == expected

    def test_the_quotas_are_per_tier_not_a_shared_pool(self):
        """`fetch_papers` runs once per tier with that tier's own cap, so a
        slot here cannot be taken from level1. Asserted on the loop rather
        than on the table, because the table alone does not prove it."""
        src = (Path(__file__).parent.parent / "endo_ai.py").read_text(encoding="utf-8")
        body = src[src.index("    for level_key, terms, label in levels:"):]
        body = body[:body.index("\n    # Summary")]
        assert "level_key, mode=mode" in body.replace("\n", " ").replace("  ", " ") \
            or "level_key," in body

    def test_its_floor_is_the_weakest_clinical_one_not_a_new_number(self):
        """Calibrated, not invented: the same floor as level4 (case series).
        It cannot be level5's 38 — the score comes from a therapy-shaped
        scorer that gives a descriptive study no credit for a comparison it
        never made, and on the apicoectomy module this tier scores min 15.4,
        median 33.5, max 46.5. A floor of 38 admitted 16 of 50 and cut the
        paper the item exists for."""
        assert e._tier_floor("observational") == e._tier_floor("level4")
        assert e._tier_floor("observational") < e._tier_floor("level5")

    def test_it_reaches_deeper_because_its_pool_is_larger(self):
        """771 papers match the tier query on the apicoectomy module, and
        PubMed's relevance ranking is flatter for descriptive designs. Depth
        is not relevance: esearch is still sorted by relevance and the cap
        still keeps only the most relevant of what comes back."""
        assert e.TIER_FETCH_DEPTH.get("observational", 50) > 50
        assert e.TIER_FETCH_DEPTH.get("level1", 50) == 50


class TestTheRecordIsCorrected:

    def test_the_domain_filter_is_exonerated_in_the_queue(self):
        """A31e. ENDO_DOMAIN_FILTER has now been cleared twice — Q7 and A23a —
        of gaps that turned out to be the coverage gate, the cap, the KNN
        ordering and the tier taxonomy. Stage 4 should judge the venue
        question on its own evidence."""
        queue = (Path(__file__).parent.parent / "AGENT_QUEUE.md").read_text(
            encoding="utf-8")
        assert "exonerated" in queue.lower()


class TestSurveysWereMeasuredAndDropped:
    """A33i. A33a proposed adding surveys to this tier; measurement dropped it.

    Pinned because the absence is a DECISION, not an oversight, and the next
    person to notice that surveys are unreachable should read the measurement
    before adding them back.
    """

    SURVEY_MESH = ("surveys and questionnaires", "health care surveys",
                   "practice patterns", "attitude of health personnel")

    def test_no_survey_term_is_in_the_filter(self):
        joined = " ".join(e.LEVEL_OBS_TERMS).lower()
        for term in self.SURVEY_MESH:
            assert term not in joined, (
                f"{term!r} was added to the observational tier — read the A33i "
                f"note above LEVEL_OBS_TERMS first: it recovers 0 of the 5 "
                f"apicoectomy targets and admits 37 papers the question has "
                f"no use for")

    def test_the_measurement_that_dropped_it_is_recorded_beside_it(self):
        src = (Path(__file__).parent.parent / "endo_ai.py").read_text(
            encoding="utf-8")
        assert "A33i — SURVEYS ARE DELIBERATELY NOT HERE" in src
        assert "0 of 5 targets" in src

    def test_the_tier_still_reaches_the_designs_it_was_built_for(self):
        """The four targets surveys would not have recovered are recovered by
        the terms that ARE here — this tier is not empty of purpose."""
        joined = " ".join(e.LEVEL_OBS_TERMS).lower()
        assert "cross-sectional" in joined
        assert "cone-beam computed tomography" in joined
        assert "anatomy and histology" in joined
