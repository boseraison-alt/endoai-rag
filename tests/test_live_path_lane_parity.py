"""The two retrieval implementations must issue the same lanes.

WHAT WENT WRONG, AND WHY NO TEST CAUGHT IT.

There are two evidence-base builders:

    endo_ai.build_evidence_base                 the CURRICULUM path
    app.build_evidence_base_with_progress       the LIVE path for Review and
                                                Case, with job progress

Both looped over a list of (level_key, terms, label). One read
`endo_ai.tier_query_lanes()`; the other had the list written out longhand. So
every lane added to the ladder reached the curriculum and nothing else:

    observational   A31 -- added so cross-sectional, morphometric, imaging and
                    diagnostic-accuracy designs would be REACHABLE at all.
                    Never reached a Review or Case answer.
    guideline       A49 item 5 -- the entire point was that a clinical
                    practice guideline had no query that could reach it. On
                    this path it still had none.
    provisional     A49 item 4b.

Every existing test of those lanes passed, and each was correct about what it
asserted: `test_observational_tier` and `test_guideline_lane` check
`tier_query_lanes()`, and `test_provisional_lane` drives
`endo_ai.build_evidence_base`. The helper was right; one of its two callers
did not call it. That is standing rule 14 in its purest form -- assert on the
thing the product runs, and note that "the product" here was two things.

It was found by asking which call sites reach `fetch_untyped_recent`, not by
a test. This file is that question, written down.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import endo_ai as E

ROOT = Path(__file__).parent.parent
APP = (ROOT / "app.py").read_text(encoding="utf-8")


def _live_path_body():
    i = APP.index("def build_evidence_base_with_progress(")
    j = APP.index("\ndef ", i + 1)
    return APP[i:j]


class TestTheLivePathDerivesItsLanes:

    def test_it_does_not_hardcode_a_second_lane_list(self):
        """The specific shape of the bug: a longhand copy that drifts."""
        body = _live_path_body()
        assert "tier_query_lanes()" in body, (
            "the live path must derive its lanes from "
            "endo_ai.tier_query_lanes(); a second hardcoded list is how "
            "observational, guideline and provisional went missing from "
            "Review and Case for months")
        # The old list named each tier's constant inline. If those reappear in
        # a list literal, someone has re-forked it.
        assert not re.search(r'\(\s*"level3a"\s*,\s*LEVEL_3A_TERMS', body), (
            "a hardcoded lane list has come back")

    def test_every_declared_lane_is_reachable_on_the_live_path(self):
        """Derived, so this is really a guard on the derivation surviving."""
        body = _live_path_body()
        assert "for lk, terms, label in tier_query_lanes()" in body

    @pytest.mark.parametrize("lane", ["guideline", "observational"])
    def test_the_lanes_that_were_missing_are_in_the_shared_list(self, lane):
        assert lane in [k for k, _t, _l in E.tier_query_lanes()]


class TestTheProvisionalLaneReachesTheLivePath:

    def test_the_live_path_calls_it(self):
        body = _live_path_body()
        assert "fetch_untyped_recent(" in body, (
            "the provisional lane never reaches Review or Case")
        assert "PROVISIONAL_KEY" in body

    def test_it_is_outside_the_early_stop(self):
        """The early stop skips weak tiers once cochrane+level1 have supplied
        enough, because tier banding means a case series cannot override a
        Level I finding. That reasoning does not transfer: a new trial is most
        valuable precisely when there IS established evidence to contradict,
        so skipping the lane on well-covered questions skips it exactly where
        it matters."""
        body = _live_path_body()
        i_else = body.index("_run_tiers([l for l in levels if l[0] not in EARLY_STOP_TIERS])")
        i_prov = body.index("fetch_untyped_recent(")
        assert i_prov > i_else, "provisional lane is inside the early-stop branch"
        # ...and not indented under the `else:` that guards the weak tiers.
        line = body[:i_prov].rsplit("\n", 1)[-1]
        assert len(line) - len(line.lstrip()) <= 16, (
            "the provisional call is nested too deeply to run when the early "
            "stop fires")

    def test_the_guideline_lane_also_survives_the_early_stop(self):
        """A guideline is not weak evidence.

        The early stop's reasoning is that tier banding means a case series
        cannot override a Level I finding, so once the top tiers have supplied
        enough the weak ones cannot change the recommendation. A guideline is
        a specialty's stated POSITION -- a different axis. Measured: on the
        Review question used for the lane A/B the early stop fired at 59
        papers, so without this the guideline lane would have been skipped on
        exactly the well-covered questions a clinician is most likely to ask.
        """
        body = _live_path_body()
        i_early = body.index("[early_stop]")
        seg = body[i_early:body.index("else:", i_early)]
        assert '_run_tiers([l for l in levels if l[0] == "guideline"])' in seg, (
            "the guideline lane is skipped when the early stop fires")

    def test_a_lane_failure_cannot_take_the_answer_down(self):
        body = _live_path_body()
        seg = body[body.index("fetch_untyped_recent("):]
        seg = seg[:400]
        assert "except Exception" in seg, (
            "the newest-literature lane must never be able to fail an answer")

    def test_the_case_differential_merge_does_not_drop_it(self):
        """A THIRD place the lane could vanish, and the subtlest.

        `build_differential_evidence` calls the live path once per candidate
        and merges the results with `for tier in TIER_ORDER`. PROVISIONAL_KEY
        is deliberately NOT in TIER_ORDER -- that absence is what stops it
        competing for a tier slot -- and the same absence made this merge drop
        every provisional paper the retrieval had just found. They would have
        been fetched, paid for and discarded; and because this merge also
        BUILDS the evidence base, citing one would then have scored as a
        fabrication.
        """
        i = APP.index("def build_differential_evidence(")
        j = APP.index("\ndef ", i + 1)
        body = APP[i:j]
        assert "list(TIER_ORDER) + [PROVISIONAL_KEY]" in body, (
            "the differential merge iterates TIER_ORDER alone, which silently "
            "drops every provisional paper")
        assert 'evidence[PROVISIONAL_KEY]' in body, (
            "the differential path never rebuilds a provisional block, so the "
            "papers cannot reach synthesis")

    def test_the_differential_merge_really_carries_it(self, monkeypatch):
        """Behavioural, not source-shape: drive the real function.

        The test above asserts the merge iterates the right keys. This one
        asserts what comes OUT, which is what the source-shape check is a
        proxy for — and the two failure modes differ: a merge could iterate
        the key and still drop the block when rebuilding `evidence`.
        """
        import app as A

        tiered = {"pmid": "111", "score": 80.0, "level_key": "level1",
                  "title": "A trial", "year": 2020, "authors": "X Y",
                  "journal": "J Endod", "citations": 5}
        prov = {"pmid": "999", "score": None, "level_key": E.PROVISIONAL_KEY,
                "title": "A 2026 trial MEDLINE has not typed", "year": 2026,
                "authors": "Z A", "journal": "Int Endod J", "citations": 0,
                "is_provisional": True,
                "stated_design": "randomised controlled trial",
                "stated_design_quote": "randomised controlled trial"}

        def fake_build(job_id, query, mode="case", prior_pmids=None, **kw):
            return {
                "level1": {"text": "t", "ids": ["111"], "scored": [dict(tiered)]},
                E.PROVISIONAL_KEY: {"text": "p", "ids": ["999"],
                                    "scored": [dict(prov)]},
                "_summary": {"total_scored": 1, "avg_score": 80.0,
                             "all_scored": [dict(tiered)],
                             "synthesis_order": []},
            }

        monkeypatch.setattr(A, "build_evidence_base_with_progress", fake_build)
        with A.jobs_lock:
            A.jobs["parity-probe"] = {"status": "running", "abort": False}

        ev = A.build_differential_evidence(
            "parity-probe", "a case",
            [{"name": "candidate one", "query": "q1"},
             {"name": "candidate two", "query": "q2"}])

        prov_out = (ev.get(E.PROVISIONAL_KEY) or {}).get("scored") or []
        assert [p["pmid"] for p in prov_out] == ["999"], (
            "the provisional paper was dropped by the differential merge")
        assert "NOT YET CLASSIFIED BY MEDLINE" in (
            (ev.get(E.PROVISIONAL_KEY) or {}).get("text") or "")
        # out of the scored list, in the evidence base
        assert [p["pmid"] for p in ev["_summary"]["all_scored"]] == ["111"]
        assert ev["_summary"]["avg_score"] == 80.0
        assert {"111", "999"} <= E._extract_evidence_pmids(ev), (
            "a provisional paper cited on the differential path would be "
            "scored as a fabrication")

    def test_the_differential_keeps_provisional_out_of_all_scored(self):
        i = APP.index("def build_differential_evidence(")
        j = APP.index("\ndef ", i + 1)
        body = APP[i:j]
        seg = body[body.index("prov_bucket = merged.get"):]
        seg = seg[:seg.index("detect_outliers")]
        assert "all_scored.extend" not in seg, (
            "provisional papers with score=None entered all_scored; "
            "`sum(p['score'] for p in all_scored)` raises on the first one")

    def test_provisional_papers_do_not_enter_all_scored(self):
        """`all_scored` is summed and averaged. A provisional paper carries
        score=None, and one None in that list raises on every consumer."""
        body = _live_path_body()
        seg = body[body.index("fetch_untyped_recent("):]
        seg = seg[:600]
        assert "all_scored.extend" not in seg, (
            "provisional papers were added to all_scored; their score is None "
            "and `sum(p['score'] for p in all_scored)` will raise")
