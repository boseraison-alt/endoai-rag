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


class TestKnobsTheSharedHelperReadsAreForwarded:
    """Same class as the hardcoded lane list: a setting added to
    `endo_ai.fetch_papers` that one of its two callers never passed."""

    def test_the_live_path_forwards_the_per_tier_fetch_depth(self):
        """`TIER_FETCH_DEPTH` gives `observational` a depth of 100 because A31
        measured that the designs it admits sit deeper in the result list. The
        live path was fetching 50, so half that depth never existed on Review
        or Case."""
        body = _live_path_body()
        assert "TIER_FETCH_DEPTH.get(level_key, 50)" in body, (
            "the live path fetches a flat depth and ignores TIER_FETCH_DEPTH")
        assert E.TIER_FETCH_DEPTH.get("observational") == 100

    def test_the_live_path_forwards_the_mode(self):
        """`mode` selects MODE_TIER_QUOTAS. Review and case are identical
        today, so this is hygiene -- but eval/run_eval.py can pass
        mode='learn', where they are not."""
        body = _live_path_body()
        assert "mode=mode, question=question" in body

    def test_review_and_case_quotas_are_still_identical(self):
        """The reason the dropped `mode` was harmless in production. If this
        ever fails, the omission it excuses has become a real defect."""
        review = E.MODE_TIER_QUOTAS["review"]
        case = E.MODE_TIER_QUOTAS.get("case")
        if case is None:
            pytest.skip("no case quota table")
        assert review == case, (
            "review and case quotas have diverged, so forwarding `mode` now "
            "changes behaviour -- check every caller passes it")

    def test_the_provisional_lane_has_no_dead_parameter(self):
        """`question` was accepted and never read, implying a question-level
        relevance gate on the lane that does not exist."""
        import inspect
        params = list(inspect.signature(E.fetch_untyped_recent).parameters)
        assert "question" not in params, (
            "a parameter that names a safety property but is never read is "
            "worse than no parameter")


class TestEnrichmentPresentOnOnePathOnly:
    """Three behaviours that existed on one retrieval path and not the other.
    Same class as the hardcoded lane list."""

    def test_the_live_path_seeds_dedup_with_the_cochrane_tier(self):
        """`seen_pmids` was created AFTER the Cochrane fetch, so a Cochrane
        review re-found by level1 appeared in both blocks and was counted
        twice -- a hole inside the one invariant this function's own comment
        calls load-bearing, hitting the highest-authority papers in the base.
        """
        body = _live_path_body()
        i_set = body.index("seen_pmids: set")
        seg = body[i_set:i_set + 400]
        assert 'evidence.get("cochrane")' in seg, (
            "seen_pmids starts empty, so a Cochrane review re-found by level1 "
            "is rendered twice")

    def test_outlier_detection_runs_on_the_curriculum_path(self):
        """`fetch_papers` hard-sets is_outlier=False with the comment 'set
        later by detect_outliers()'. On this path there was no later -- the
        only callers were in app.py -- so every curriculum module reached the
        model with no outlier information while the prompt instructs it never
        to present an outlier finding as established fact."""
        src = (ROOT / "endo_ai.py").read_text(encoding="utf-8")
        i = src.index("def build_evidence_base(topic")
        j = src.index("\ndef ", i + 1)
        assert "detect_outliers(all_scored)" in src[i:j], (
            "detect_outliers never runs on the curriculum path")

    def test_outliers_are_actually_flagged(self, monkeypatch):
        """Behavioural: one clear outlier among peers must be tagged, and the
        assembled context must carry the warning line."""
        scores = [70, 71, 72, 69, 73, 70, 71, 72, 70, 15]

        def paper(pmid, sc):
            return {"pmid": pmid, "score": sc, "level_key": "level1",
                    "title": "T", "abstract": "A", "authors": "X",
                    "year": 2024, "journal": "J", "citations": 1,
                    "sample_size": None, "followup_months": None,
                    "impact_factor": None, "has_coi": False,
                    "is_old": False, "is_outlier": False}

        def fake(topic, filt, label, level_key, **kw):
            if level_key != "level1":
                return "", [], []
            return ("txt", [str(i) for i in range(len(scores))],
                    [paper(str(i), s) for i, s in enumerate(scores)])

        monkeypatch.setattr(E, "fetch_papers", fake)
        monkeypatch.setattr(E, "fetch_cochrane", lambda t: None)
        monkeypatch.setattr(E, "generate_search_terms", lambda q, **k: "(t)")
        monkeypatch.setattr(E, "label_and_expand", lambda q, t: t)
        monkeypatch.setattr(E, "fetch_untyped_recent", lambda *a, **k: ("", [], []))

        ev = E.build_evidence_base("q")
        flagged = [p["pmid"] for p in ev["_summary"]["all_scored"]
                   if p.get("is_outlier")]
        assert flagged == ["9"], f"expected the score-15 paper flagged, got {flagged}"
        assert "OUTLIER PAPERS" in E._build_evidence_context(ev)

    def test_a_live_guideline_carries_its_status(self):
        """Only the library path set guideline_*, so a guideline retrieved
        LIVE rendered 'NOT SCORED -- ...' with an EMPTY detail. Two
        consequences, the second clinical: the prompt orders the model to name
        the issuing body, so with `org` absent it had to infer one from the
        title; and a SUPERSEDED-but-not-withdrawn guideline was
        indistinguishable from the current edition."""
        fields = E._manifest_guideline_fields("17180780")   # ESE-QG-2006
        assert fields.get("guideline_status") == "superseded"
        assert fields.get("guideline_org") == "ESE"
        line = E.format_paper_context_line({
            "pmid": "17180780", "authors": "A", "year": 2006, "citations": 0,
            "level_key": "guideline", "score": None,
            "sample_size": None, "followup_months": None, **fields})
        assert "superseded" in line, (
            "a superseded guideline retrieved live reads as current")

    def test_an_unconfirmed_accession_is_never_matched_by_pmid(self):
        """Ten manifest records have an UNCONFIRMED PubMed accession. Matching
        one by PMID would use the exact field nobody has verified."""
        import json
        seed = json.loads((ROOT / "data" / "guidelines_seed.json")
                          .read_text(encoding="utf-8"))["guidelines"]
        unconfirmed = [g for g in seed
                       if g.get("confidence") == "unconfirmed_pmid" and g.get("pmid")]
        for g in unconfirmed:
            assert not E._manifest_guideline_fields(g["pmid"]), (
                f"{g['id']} matched by an unconfirmed accession")

    def test_an_ordinary_paper_gets_nothing(self):
        assert E._manifest_guideline_fields("27759881") == {}
        assert E._manifest_guideline_fields("99999999") == {}

    def test_fetch_papers_actually_attaches_it(self):
        """Rule 14, caught by a mutation that survived: the tests above all
        exercise the HELPER. Deleting the call from `fetch_papers` left them
        green, which is the same shape as the bug this whole file is about --
        a correct helper that one caller does not call."""
        src = (ROOT / "endo_ai.py").read_text(encoding="utf-8")
        i = src.index("def fetch_papers(topic, filter_term")
        j = src.index("\ndef ", i + 1)
        assert "**_manifest_guideline_fields(pmid)" in src[i:j], (
            "fetch_papers does not attach guideline identity, so a guideline "
            "retrieved live carries no org, status or jurisdiction")


class TestNoPaperAppearsInTwoTiersAtOnce:
    """A paper can carry several MEDLINE publication types -- a systematic
    review is both `Systematic Review[pt]` and `Review[pt]` -- so the same
    PMID comes back from several lanes.

    `app.build_evidence_base_with_progress` has always carried a `seen_pmids`
    set and its comment calls the property load-bearing.
    `endo_ai.build_evidence_base` never did, so the same paper was rendered in
    TWO tier blocks under two contradictory grades in one prompt, while the
    system prompt tells Claude to trust the tier label absolutely -- and it
    double-counted in `total_scored` and skewed `avg_score`.
    """

    @pytest.fixture
    def evidence(self, monkeypatch):
        def paper(pmid, lk, sc):
            return {"pmid": pmid, "score": sc, "level_key": lk, "title": "T",
                    "abstract": "A", "authors": "X", "year": 2024,
                    "journal": "J", "citations": 1, "sample_size": None,
                    "followup_months": None, "impact_factor": None,
                    "has_coi": False, "is_old": False, "is_outlier": False}

        def fake(topic, filt, label, level_key, **kw):
            if level_key in ("level1", "level4"):
                return "txt", ["111"], [
                    paper("111", level_key, 80.0 if level_key == "level1" else 20.0)]
            return "", [], []

        monkeypatch.setattr(E, "fetch_papers", fake)
        monkeypatch.setattr(E, "fetch_cochrane", lambda t: None)
        monkeypatch.setattr(E, "generate_search_terms", lambda q, **k: "(t)")
        monkeypatch.setattr(E, "label_and_expand", lambda q, t: t)
        monkeypatch.setattr(E, "fetch_untyped_recent", lambda *a, **k: ("", [], []))
        return E.build_evidence_base("q")

    def test_it_appears_once(self, evidence):
        order = [(p["pmid"], p["tier_key"])
                 for p in evidence["_summary"]["synthesis_order"]]
        assert order == [("111", "level1")], (
            f"the same paper reached synthesis under two tier labels: {order}")

    def test_the_strongest_tier_wins(self, evidence):
        assert [p["pmid"] for p in evidence["level1"]["scored"]] == ["111"]
        assert evidence["level4"]["scored"] == []

    def test_it_is_not_double_counted(self, evidence):
        assert evidence["_summary"]["total_scored"] == 1


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


class TestTheTwoBuildersIssueTheSameLaneSet:
    """THE AGREEMENT TEST — item 3, 2026-09-05.

    Every other test in this file asserts something about ONE builder, or
    about the source shape of one. That is what let the original defect
    through: `test_observational_tier` and `test_guideline_lane` were correct
    about `tier_query_lanes()`, `test_provisional_lane` was correct about
    `endo_ai.build_evidence_base`, and the live path had its own hardcoded
    list three lanes behind while all three stayed green.

    This asserts the thing none of them did: that the two builders, actually
    RUN, request the same set of lanes. Not a test of each — a test of their
    agreement. A source-shape test cannot do this; the previous list was
    hardcoded and looked perfectly well-formed.

    Both are driven offline with every fetcher stubbed, so what is compared is
    the lane keys each builder asked for, not what PubMed returned.
    """

    @pytest.fixture
    def lanes_issued(self, monkeypatch):
        """Run both builders with the fetchers recording, and return
        {"curriculum": set, "live": set}."""
        import app as A

        seen = {"curriculum": set(), "live": set()}
        current = {"which": None}

        def fake_fetch_papers(topic, filter_term, label, level_key,
                              max_results=50, mode="review", question=None):
            seen[current["which"]].add(level_key)
            return "", [], []

        def fake_fetch_cochrane(topic):
            seen[current["which"]].add("cochrane:direct")
            return ""

        def fake_untyped(topic, max_admitted=E.PROVISIONAL_MAX_ADMITTED):
            seen[current["which"]].add(E.PROVISIONAL_KEY)
            return "", [], []

        monkeypatch.setattr(E, "fetch_papers", fake_fetch_papers)
        monkeypatch.setattr(E, "fetch_cochrane", fake_fetch_cochrane)
        monkeypatch.setattr(E, "fetch_untyped_recent", fake_untyped)
        monkeypatch.setattr(E, "generate_search_terms",
                            lambda q, context_block="": "topic")
        monkeypatch.setattr(E, "generate_multi_search_terms",
                            lambda q, s, context_block="": ["topic"])
        monkeypatch.setattr(E, "label_and_expand", lambda terms, *a, **k: terms)
        monkeypatch.setattr(E, "LIBRARY_WRITE_BACK", False)

        current["which"] = "curriculum"
        E.build_evidence_base("a topic", mode="review")

        current["which"] = "live"
        job = "lane-parity"
        A.jobs[job] = {"status": "running", "steps": [], "progress": 0}
        A.build_evidence_base_with_progress(job, "a question",
                                            force_route="live", mode="review")
        return seen

    def test_the_two_builders_request_the_same_lanes(self, lanes_issued):
        curriculum = lanes_issued["curriculum"] - {"cochrane:direct"}
        live = lanes_issued["live"] - {"cochrane:direct"}
        assert curriculum == live, (
            "the two evidence-base builders issue DIFFERENT lane sets.\n"
            f"  only on the curriculum path: {sorted(curriculum - live)}\n"
            f"  only on the live path      : {sorted(live - curriculum)}\n"
            "This is the defect this whole file exists for: a lane added to "
            "the ladder that reaches one path and not the other.")

    def test_the_agreed_set_is_the_declared_set(self, lanes_issued):
        """Rule 4 — the assertion above goes vacuous if both builders issue
        nothing (a stub that silently stopped matching, an early return). This
        fails when that happens."""
        declared = {lk for lk, _t, _l in E.tier_query_lanes()}
        declared |= {"cochrane", E.PROVISIONAL_KEY}
        live = lanes_issued["live"] - {"cochrane:direct"}
        assert live == declared, (
            f"issued {sorted(live)} but tier_query_lanes declares "
            f"{sorted(declared)}")
        assert len(live) >= 10, "lane set implausibly small — stub not firing?"


class TestEveryTierOrderLoopAccountsForTheProvisionalLane:
    """`grep -n "in TIER_ORDER"` is the checklist, written down.

    PROVISIONAL_KEY's absence from TIER_ORDER is what makes the lane safe — it
    can never take a tier slot — and is exactly what makes it invisible to
    every `for tier in TIER_ORDER` loop. The safety property and the failure
    mode are the same fact, which is why five wiring sites dropped the lane
    while every test of the lane passed.

    So every such loop must either handle the lane or say in a comment why it
    need not. This test is the grep, so a SIXTH site cannot be added silently.

    2026-09-05 — IT SCANS THE WHOLE REPOSITORY NOW, and that is the point of
    standing rule 36. The first version listed `("app.py", "endo_ai.py")`,
    which were the two files I happened to be looking at. It passed while
    `eval/run_eval.py` dropped every provisional paper from `per_tier` AND
    from the `papers` total, in every baseline the harness had ever produced —
    the v7 run logs show the lane admitting up to `147 of 400` against a
    recorded zero. A checklist that enumerates a set has to enumerate it
    everywhere, or it certifies the files the author already had open.
    """

    # Everything except the virtualenv, git internals and caches. Listing
    # DIRECTORIES to skip rather than files to scan is the load-bearing choice:
    # a new module under eval/ or scripts/ is covered the day it is written,
    # which an allow-list would not have been.
    SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules",
                 ".pytest_cache", "site-packages"}

    @classmethod
    def _sources(cls):
        out = []
        for path in ROOT.rglob("*.py"):
            if any(part in cls.SKIP_DIRS for part in path.parts):
                continue
            out.append(path)
        return sorted(out)

    def _loops(self, src, text):
        """(line_no, window) per TIER_ORDER loop, scoped TIGHTLY to that loop.

        The window is the contiguous comment block DIRECTLY ABOVE the loop,
        plus the loop statement and the few lines it governs. Two earlier
        scopes were both wrong and both let a real bug through:

          a fixed 22-line window   called a correct site a defect, because the
                                   differential merge handles the lane 26
                                   lines after its loop starts.

          the enclosing function   let a mutation SURVIVE. `run_case` in
                                   eval/run_eval.py holds three TIER_ORDER
                                   sites with three different dispositions, so
                                   one site's comment satisfied the check for
                                   the site that had none — which is exactly
                                   the bug this test exists to catch, passing
                                   its own mutation check.

        Per-site is the only granularity that means anything here: the question
        is whether THIS loop accounted for the lane, and a neighbour's reason
        is not this loop's reason.
        """
        lines = text.splitlines()

        def is_site(l):
            return (not l.strip().startswith('#')
                    and 'for ' in l and ' in TIER_ORDER' in l)

        def stmt_start(i):
            # A comprehension's `for ... in TIER_ORDER` is often the
            # SECOND line of its statement, and the comment explaining
            # the site sits above the FIRST. Walk up to the statement
            # start before looking for the comment, or every multi-line
            # comprehension reads as unjustified.
            lo = i
            while lo > 0:
                prev = lines[lo - 1].rstrip()
                cur = lines[lo].strip()
                if (prev.endswith(('(', '[', '{', ',', '=')) or
                        cur.startswith(('for ', 'if ', 'in ', 'and ',
                                        'or ', ')', ']', '}'))):
                    lo -= 1
                    continue
                break
            return lo

        def block_start(i):
            lo = stmt_start(i)
            while lo > 0 and lines[lo - 1].strip().startswith('#'):
                lo -= 1
            return lo

        sites = [i for i, l in enumerate(lines) if is_site(l)]
        starts = [block_start(i) for i in sites]
        out = []
        for n, i in enumerate(sites):
            # This site OWNS from its own comment block down to the start of
            # the next site's comment block. That boundary is the whole point:
            # a neighbour's reason belongs to the neighbour, so one justified
            # loop cannot vouch for an unjustified one three lines later --
            # which is precisely how a mutation of eval/run_eval.py SURVIVED
            # when this window was the enclosing function.
            hi = starts[n + 1] if n + 1 < len(sites) else min(len(lines), i + 40)
            out.append((i + 1, chr(10).join(lines[starts[n]:hi])))
        return out

    def test_every_loop_handles_the_lane_or_says_why_not(self):
        checked, offenders = 0, []
        for path in self._sources():
            if path.name == Path(__file__).name:
                continue          # this file quotes the construct in prose
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(ROOT).as_posix()
            for lineno, window in self._loops(rel, text):
                checked += 1
                # Case-insensitive: "the provisional lane is always
                # fetched from PubMed" is a perfectly good reason and
                # should not have to shout to be accepted.
                if "provisional" not in window.lower():
                    offenders.append(f"{rel}:{lineno}")
        assert not offenders, (
            "these loop over TIER_ORDER and never mention PROVISIONAL_KEY — "
            "each either drops the provisional lane silently, or needs a "
            "comment saying why it need not:\n  " + "\n  ".join(offenders))
        # Rule 4: if the regex stops matching, this test passes vacuously and
        # the checklist it encodes is gone. The floor is well above the six
        # that the two-file version saw.
        assert checked >= 20, (
            f"expected at least 20 TIER_ORDER loops repo-wide, found {checked} "
            f"— the scanner has stopped matching")

    def test_it_actually_scans_beyond_the_two_original_files(self):
        """Rule 36, pinned. The bug was the SCOPE, so the scope is asserted."""
        rels = {p.relative_to(ROOT).as_posix() for p in self._sources()}
        for expected in ("eval/run_eval.py", "scripts/probe_retrieval.py",
                         "presentations/chart_data.py"):
            assert expected in rels, f"{expected} is not being scanned"
        assert len(rels) > 50, f"only {len(rels)} python files found"
