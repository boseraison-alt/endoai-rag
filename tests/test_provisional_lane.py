"""A49 item 4b — the untyped-recent (provisional) lane.

THE DEFECT IT CLOSES. A paper MEDLINE has not yet indexed carries only
`Journal Article`. Every tier lane ANDs a publication-type filter and none of
them admits a bare `Journal Article`, so there was a rolling window -- the
width of MEDLINE's indexing lag -- in which no new paper on any topic could
enter the pool. Sulaiman 42388091 carries five of a VPT question's own terms
in its title and was structurally unreachable.

THE SHAPE OF THE FIX, and every part of it is load-bearing:

  separate lane   PROVISIONAL_KEY is NOT in TIER_ORDER. That is this
                  codebase's mechanism for "never competes for a tier slot",
                  and it is why these papers cannot displace a classified one.
  no tier         assigning a rung would be asserting a classification the
                  indexer has not made.
  no score        same reason, one step further.
  design is the   admitted only if the ABSTRACT states a level2-or-above
  gate            design, in the authors' own words. Measured: this removes
                  87.6% of the untyped-recent pool.
  no floor        `evidence_floor` 0.60 already loses Komora, a Level I paper
                  on the exact topic, at 0.5807. It is not the instrument for
                  selecting untyped papers.
  rendered        year, "not yet classified by MEDLINE", and the stated
  honestly        design -- visible without asking.

The lane is exercised through `build_evidence_base` with the network stubbed,
so what is asserted is what production assembles, not a restatement of it
(standing rule 14).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import endo_ai as E

FIXTURES = Path(__file__).parent / "fixtures" / "missed_papers"


@pytest.fixture(scope="module")
def sulaiman():
    return json.loads((FIXTURES / "42388091.json").read_text(encoding="utf-8"))


class TestItIsASeparateLaneAndNotATier:
    """A12 — reachability now, ranking later, never in one commit."""

    def test_it_is_not_on_the_tier_ladder(self):
        assert E.PROVISIONAL_KEY not in E.TIER_ORDER, (
            "membership of TIER_ORDER is what lets a key compete for a tier "
            "slot and be read as a rung; the provisional lane must not be in it")

    def test_it_has_no_tier_score(self):
        assert E.PROVISIONAL_KEY not in E.LEVEL_SCORES

    def test_no_existing_tier_was_changed(self):
        assert E.TIER_ORDER == [
            "cochrane", "level1", "classic", "level2", "level3a", "level3",
            "level3b", "level4", "invitro", "guideline", "level5",
            "observational"]

    def test_no_existing_lane_was_removed(self):
        keys = [k for k, _t, _l in E.tier_query_lanes()]
        assert keys == ["level1", "level2", "level3a", "level3b", "level4",
                        "guideline", "level5", "observational"]
        assert E.PROVISIONAL_KEY not in keys, (
            "the provisional lane must not be a tier lane — it has its own "
            "query with no publication-type filter at all")

    def test_the_label_says_it_is_not_classified(self):
        label = E.PROVISIONAL_LABEL.lower()
        assert "provisional" in label
        assert "not yet classified" in label or "not yet" in label


class TestTheQuery:

    def test_it_ands_no_publication_type_filter(self):
        """The whole point: a tier filter is what makes an untyped paper
        unreachable, so this lane must not carry one."""
        q = E.untyped_recent_query("(pulpotomy)")
        assert "[pt]" not in q.replace('"Retracted Publication"[pt]', "") \
                                .replace('"Retraction of Publication"[pt]', "")

    def test_it_carries_the_eighteen_month_window(self):
        assert '"last 18 months"[dp]' in E.untyped_recent_query("(x)")
        assert E.PROVISIONAL_WINDOW_MONTHS == 18

    def test_it_keeps_the_domain_filter(self):
        """Without it the lane returns celery genomics — measured, not
        hypothetical (see eval/reports/a49_design_extraction.md)."""
        assert E.ENDO_DOMAIN_FILTER in E.untyped_recent_query("(x)")

    def test_it_keeps_the_retraction_exclusion(self):
        q = E.untyped_recent_query("(x)")
        assert 'NOT "Retracted Publication"[pt]' in q
        assert 'NOT "Retraction of Publication"[pt]' in q


class TestWhatItAdmits:

    def test_it_admits_sulaiman(self, sulaiman):
        assert E.untyped_recent_admits(sulaiman)

    def test_it_admits_on_the_stated_design_not_on_a_guess(self, sulaiman):
        d = E.extract_stated_design(sulaiman["abstract"], sulaiman["title"])
        assert d["rung"] == "level2"
        assert "one-arm clinical trial" in d["matched"]
        assert "randomis" not in (sulaiman["abstract"] or "").lower()
        assert "randomly" not in (sulaiman["abstract"] or "").lower()

    def test_it_declines_a_paper_medline_has_classified(self):
        """Komora carries Systematic Review / Network Meta-Analysis, so the
        TIER lanes own it. The provisional lane must not double-admit it."""
        rec = json.loads((FIXTURES / "39117767.json").read_text(encoding="utf-8"))
        assert not E.untyped_recent_admits(rec)

    def test_it_declines_a_classified_guideline(self):
        rec = json.loads((FIXTURES / "42018467.json").read_text(encoding="utf-8"))
        assert not E.untyped_recent_admits(rec)

    def test_it_declines_an_untyped_paper_stating_no_design(self):
        assert not E.untyped_recent_admits({
            "publication_types": ["Journal Article"],
            "title": "Some thoughts on modern endodontics",
            "abstract": "This piece discusses developments in the field."})

    def test_it_declines_an_untyped_bench_study(self):
        """Even one that randomises its specimens."""
        assert not E.untyped_recent_admits({
            "publication_types": ["Journal Article"],
            "title": "Sealing ability of three materials",
            "abstract": "Sixty extracted human premolars were randomly "
                        "divided into three groups and sectioned for "
                        "stereomicroscopic evaluation of specimens."})

    def test_it_declines_a_weaker_design(self):
        assert not E.untyped_recent_admits({
            "publication_types": ["Journal Article"],
            "title": "Outcomes after retreatment",
            "abstract": "We retrospectively reviewed the records of 200 "
                        "patients treated between 2019 and 2023."})


class TestItRendersHonestly:

    @pytest.fixture
    def line(self, sulaiman):
        d = E.extract_stated_design(sulaiman["abstract"], sulaiman["title"])
        return E._provisional_context_line({
            "pmid": "42388091", "title": sulaiman["title"],
            "abstract": sulaiman["abstract"], "authors": "Sulaiman S",
            "year": 2026, "journal": "Int Endod J",
            "stated_design": d["design"], "stated_design_quote": d["matched"]})

    def test_it_says_medline_has_not_classified_it(self, line):
        assert "NOT YET CLASSIFIED BY MEDLINE" in line

    def test_it_says_the_paper_has_no_tier(self, line):
        assert "no evidence tier" in line

    def test_it_gives_the_year(self, line):
        assert "2026" in line

    def test_it_gives_the_stated_design_and_attributes_it(self, line):
        assert "DESIGN AS STATED BY THE AUTHORS" in line
        assert "clinical trial" in line
        assert "one-arm clinical trial" in line   # the quoted phrase

    def test_it_carries_no_score_and_no_tier_label(self, line):
        assert "/100" not in line
        assert "Level I" not in line and "Level II" not in line
        assert "Evidence Score" not in line


class TestThroughBuildEvidenceBase:
    """Rule 14 — assert on what production assembles.

    The network is stubbed at `fetch_untyped_recent` and `fetch_papers`, so
    this exercises the real `build_evidence_base` wiring and the real
    `_build_evidence_context`.
    """

    @pytest.fixture
    def evidence(self, monkeypatch, sulaiman):
        d = E.extract_stated_design(sulaiman["abstract"], sulaiman["title"])
        prov = [{
            "pmid": "42388091", "title": sulaiman["title"],
            "abstract": sulaiman["abstract"], "authors": "Sulaiman S",
            "year": 2026, "journal": "Int Endod J", "citations": 0,
            "level_key": E.PROVISIONAL_KEY, "score": None,
            "is_provisional": True, "medline_unclassified": True,
            "stated_design": d["design"], "stated_design_quote": d["matched"],
            "stated_design_rung": d["rung"], "stated_design_basis": d["basis"],
            "sample_size": None, "followup_months": None,
            "impact_factor": None, "has_coi": False, "is_old": False,
            "is_outlier": False,
        }]

        tiered = [{
            "pmid": "27759881", "title": "A Cochrane review", "abstract": "x",
            "authors": "A B", "year": 2016, "journal": "Cochrane Database Syst Rev",
            "citations": 40, "level_key": "cochrane", "score": 73.3,
            "sample_size": 100, "followup_months": 12, "impact_factor": None,
            "has_coi": False, "is_old": False, "is_outlier": False,
        }]

        def fake_fetch_papers(topic, filt, label, level_key, **kw):
            if level_key == "cochrane":
                return "PMID: 27759881 | ...", ["27759881"], list(tiered)
            return "", [], []

        monkeypatch.setattr(E, "fetch_papers", fake_fetch_papers)
        monkeypatch.setattr(E, "fetch_cochrane", lambda t: None)
        monkeypatch.setattr(E, "generate_search_terms", lambda q, **k: "(topic)")
        monkeypatch.setattr(E, "label_and_expand", lambda q, t: t)
        monkeypatch.setattr(
            E, "fetch_untyped_recent",
            lambda topic, question=None, **kw: (
                "".join(E._provisional_context_line(p) for p in prov),
                ["42388091"], list(prov)))
        return E.build_evidence_base("vital pulp therapy in adult teeth")

    def test_the_lane_lands_in_its_own_block(self, evidence):
        assert E.PROVISIONAL_KEY in evidence
        assert evidence[E.PROVISIONAL_KEY]["ids"] == ["42388091"]

    def test_provisional_papers_stay_out_of_all_scored(self, evidence):
        """`all_scored` is the score-bearing list every average and 'top
        paper' reads. A None score in it is how a null-safety bug reaches six
        call sites at once."""
        scored = evidence["_summary"]["all_scored"]
        assert all(p["pmid"] != "42388091" for p in scored)
        assert all(p.get("score") is not None for p in scored)

    def test_provisional_papers_stay_out_of_the_synthesis_order(self, evidence):
        order = evidence["_summary"]["synthesis_order"]
        assert all(p["pmid"] != "42388091" for p in order)
        assert all(p["tier_key"] in E.TIER_ORDER for p in order)

    def test_they_are_still_citeable(self, evidence):
        """Out of the ranking, in the evidence base. If they were not in it,
        citing one would be scored as a FABRICATION."""
        pmids = E._extract_evidence_pmids(evidence)
        assert "42388091" in pmids

    def test_the_context_carries_the_block_after_every_tier(self, evidence):
        ctx = E._build_evidence_context(evidence)
        assert E.PROVISIONAL_LABEL in ctx
        assert ctx.index("Cochrane Reviews") < ctx.index(E.PROVISIONAL_LABEL)

    def test_the_context_tells_claude_not_to_rank_them(self, evidence):
        ctx = E._build_evidence_context(evidence)
        block = ctx[ctx.index(E.PROVISIONAL_LABEL):]
        assert "no evidence tier" in block
        assert "DO NOT" in block
        assert "Level I" in block          # named as the thing not to call it
        assert "override a systematic review" in block

    def test_merge_evidence_bases_carries_the_lane(self):
        """The FOURTH place the lane could vanish, and it did.

        The curriculum builder retrieves per module and then merges with
        `merge_evidence_bases`, which keyed off TIER_ORDER alone. Each
        module's own evidence DID contain provisional papers and they DID
        reach that module's synthesis, but the combined dict handed to the
        stitcher and the reference list had none of them. Measured: a
        curriculum A/B reported provisional_pool 0 in BOTH arms while the
        per-module logs showed the lane admitting papers.

        It matters beyond the bibliography: `_extract_evidence_pmids` reads
        the combined dict, so a module citing a provisional paper would have
        had that citation scored as a FABRICATION against evidence it was
        never given.
        """
        m1 = {"level1": {"text": "A", "ids": ["1"],
                         "scored": [{"pmid": "1", "score": 80.0}]},
              E.PROVISIONAL_KEY: {"text": "P1", "ids": ["9"],
                                  "scored": [{"pmid": "9", "score": None}]}}
        m2 = {"level1": {"text": "B", "ids": ["2"],
                         "scored": [{"pmid": "2", "score": 70.0}]},
              E.PROVISIONAL_KEY: {"text": "P2", "ids": ["8"],
                                  "scored": [{"pmid": "8", "score": None}]}}
        combined = E.merge_evidence_bases([m1, m2])

        assert combined[E.PROVISIONAL_KEY]["ids"] == ["9", "8"]
        # ...and citation validation can see them, which is the property that
        # stops a legitimate citation being called a fabrication.
        assert {"8", "9"} <= E._extract_evidence_pmids(combined)

    def test_the_stitcher_reference_list_includes_them(self):
        """FIFTH site. `stitch_curriculum` builds the REFERENCES metadata from
        `_summary.all_scored`, which provisional papers are deliberately kept
        out of. Without an explicit pass they reach a module's synthesis, get
        cited, and then have no entry in the reference list -- a citation the
        reader cannot follow."""
        src = (Path(__file__).parent.parent / "endo_ai.py").read_text(encoding="utf-8")
        i = src.index("def stitch_curriculum(")
        j = src.index("\ndef ", i + 1)
        body = src[i:j]
        assert "all_evidence.get(PROVISIONAL_KEY)" in body, (
            "the stitcher's reference list never sees provisional papers")
        assert "NOT SCORED" in body, (
            "a provisional paper must not be given a score in the reference "
            "list; it has none")
        assert "PROVISIONAL_LABEL" in body

    def test_the_merge_keeps_null_scores_out_of_the_average(self):
        """`avg_score` sums all_scored. One None raises."""
        m = {"level1": {"text": "A", "ids": ["1"],
                        "scored": [{"pmid": "1", "score": 80.0}]},
             E.PROVISIONAL_KEY: {"text": "P", "ids": ["9"],
                                 "scored": [{"pmid": "9", "score": None}]}}
        combined = E.merge_evidence_bases([m])
        assert [p["pmid"] for p in combined["_summary"]["all_scored"]] == ["1"]
        assert combined["_summary"]["avg_score"] == 80.0

    def test_the_bibliography_handles_a_null_score(self, evidence):
        """A provisional paper carries score=None, and the bibliography sorts
        and splits papers. It must survive that without a coercion error and
        must list a cited provisional paper as CITED, not as surplus."""
        answer = ("## X\n\nA recent trial supports this [[PMID:42388091]] "
                  "and so does the review [[PMID:27759881]].\n")
        papers = [
            {"pmid": "27759881", "score": 73.3, "level_key": "cochrane",
             "title": "A review", "year": 2016},
            {"pmid": "42388091", "score": None,
             "level_key": E.PROVISIONAL_KEY, "title": "Sulaiman",
             "year": 2026, "is_provisional": True},
            {"pmid": "99999999", "score": 50.0, "level_key": "level2",
             "title": "Uncited", "year": 2020},
        ]
        split = E.assemble_bibliography(answer, papers)
        assert {p["pmid"] for p in split["cited"]} == {"27759881", "42388091"}
        assert [p["pmid"] for p in split["uncited"]] == ["99999999"]

    def test_the_top_paper_per_tier_block_never_names_one(self, evidence):
        ctx = E._build_evidence_context(evidence)
        if "Top paper per tier" not in ctx:
            pytest.skip("no per-tier block in this fixture")
        block = ctx[ctx.index("Top paper per tier"):]
        assert "42388091" not in block, (
            "a provisional paper reached the per-tier ranking block")
