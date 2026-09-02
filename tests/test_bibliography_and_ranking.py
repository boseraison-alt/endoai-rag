"""
The bibliography, the ranking, and the impact factor (`trust-surface-v1`
Q5, Q6, Q3).

Three defects on the same fixture, all of them presentation asserting more than
the engine does.

Q5 — THE BIBLIOGRAPHY WAS THE RETRIEVAL POOL. The apixaban Review answer listed
29 papers under "Full bibliography" and cited 7 of them. Among the 22 was
Sjögren 1990 — the same uncited boilerplate the anesthesia curriculum carries,
which is what shows the defect is STRUCTURAL rather than a truncation artifact,
and that it affects Review as well as Deep Learning. The browser built that
list from `job.papers`, which is `evidence["_summary"]["all_scored"]`. A
bibliography is what an answer drew on; a pool is what a search returned.
Presenting the second as the first inflated the apparent evidence base
fourfold. The deck path already had this right —
`webdeck.plan.build_reference_slides` takes `cited_pmids` — which is why the
defect was visible on one surface and not the other.

Q6 — THE TABLE SORTED ACROSS TIERS. Measured on the pool this answer actually
had, reconstructed in `tests/fixtures/apixaban_papers.json` from the answer's
own table and bibliography:

    score-only rank of the ESE position statement       1 of 29
    score-only rank of the Cochrane review             29 of 29

In a table headed "Top papers by evidence score", in an answer whose clinical
recommendation rests on that Cochrane review. Invariant 1: a score ranks only
WITHIN a tier. The engine has always been right about this; a table is a
ranking claim whatever its column header says.

(The fixture's transcribed table stops at 28 of the 29 rows — the Cochrane
review, lowest-scoring under the flat sort, is the row it stops one short of.
Its row here is taken from the fixture's own bibliography line.)

Q3 — IMPACT FACTOR ON A RENDERED SURFACE. "Cochrane Database Syst Rev (IF:
12.0)", "Int Endod J (IF: 4.5)" in the reference list. IF was removed from
scoring by decision (invariant 11); rendering it beside an evidence score says
it is an input to one. The mechanism was upstream of the renderer: the number
was in the model's context line and the REFERENCES template asked for
"Journal (IF: X.X)", so the model wrote what it was asked for.
"""

import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from js_harness import extract_js, run_node

import endo_ai
from endo_ai import (assemble_bibliography, finalise_answer_text,
                     format_paper_context_line, strip_impact_factor)

ROOT       = Path(__file__).parent.parent
INDEX_HTML = ROOT / "templates" / "index.html"
FIXTURE    = ROOT / "eval" / "fixtures" / "review_apixaban_apicectomy.md"
POOL       = json.loads((ROOT / "tests" / "fixtures" / "apixaban_papers.json")
                        .read_text(encoding="utf-8"))
CURRICULUM = (ROOT / "eval" / "fixtures" / "curricula" /
              "laser_disinfection_after.txt")


def fixture_answer():
    raw  = FIXTURE.read_text(encoding="utf-8")
    body = re.search(r"^## Body\s*\n(.*?)\n---\n\n## Full bibliography",
                     raw, re.S | re.M).group(1).strip()
    return re.sub(r"\[PMID (\d+)\]", r"[[PMID:\1]]", body)


# ── Q5: bibliography == citation set ──────────────────────

class TestTheBibliographyIsTheCitationSet:

    def test_the_split_on_the_apixaban_answer(self):
        out = assemble_bibliography(fixture_answer(), POOL)
        assert len(POOL) == 29
        assert len(out["cited"]) == 7
        assert len(out["uncited"]) == 22

    def test_set_equality_forwards_every_cited_paper_is_in_the_bibliography(self):
        answer = fixture_answer()
        out    = assemble_bibliography(answer, POOL)
        in_text = set(endo_ai._extract_cited_pmids(answer))
        listed  = {p["pmid"] for p in out["cited"]}
        assert in_text - listed == set(), "an answer cited a paper the bibliography omits"

    def test_set_equality_backwards_every_listed_paper_is_cited(self):
        answer = fixture_answer()
        out    = assemble_bibliography(answer, POOL)
        in_text = set(endo_ai._extract_cited_pmids(answer))
        listed  = {p["pmid"] for p in out["cited"]}
        assert listed - in_text == set(), "the bibliography lists a paper nothing cited"

    def test_the_uncited_boilerplate_is_no_longer_in_the_bibliography(self):
        """Sjögren 1990 is the specific paper that made this findable."""
        out = assemble_bibliography(fixture_answer(), POOL)
        assert "2084204" not in {p["pmid"] for p in out["cited"]}
        assert "2084204" in {p["pmid"] for p in out["uncited"]}

    def test_a_pool_only_paper_cannot_reach_the_bibliography(self):
        """The mutation the item asks for, as a test: inject one pool-only
        paper and prove it lands on the disclosure side."""
        pool = POOL + [{"pmid": "99999999", "score": 99.0, "level_key": "cochrane"}]
        out  = assemble_bibliography(fixture_answer(), pool)
        assert "99999999" not in {p["pmid"] for p in out["cited"]}
        assert "99999999" in {p["pmid"] for p in out["uncited"]}

    def test_a_synthetic_key_is_cited_like_any_other(self):
        out = assemble_bibliography(fixture_answer(), POOL)
        assert "ESE-QG-2023" in {p["pmid"] for p in out["cited"]}

    def test_a_paper_that_only_appears_in_the_reference_list_is_not_cited(self):
        """The numbered REFERENCES list is supposed to BE the citation set, so
        it cannot also be an input to it — a padded reference list would then
        re-inflate the bibliography it mirrors, which is this same defect one
        layer along. Found by a mutation that dropped the in-text scan and
        survived, because the fixture's reference list reproduced all seven."""
        answer = ("## Evidence summary\n\nPRF reduces pain [[PMID:42652796]].\n\n"
                  "## References\n\n1. [PMID: 42652796] Valdivieso Del Pueblo C.\n"
                  "2. [PMID: 2084204] Sjogren U et al.\n")
        pool = [{"pmid": "42652796"}, {"pmid": "2084204"}]
        out = assemble_bibliography(answer, pool)
        assert [p["pmid"] for p in out["cited"]] == ["42652796"]
        assert [p["pmid"] for p in out["uncited"]] == ["2084204"]

    def test_a_cited_paper_missing_from_the_pool_is_still_reported(self):
        """Dropping it silently would hide a real defect — an answer citing
        something the payload does not carry."""
        out = assemble_bibliography(
            "## Evidence summary\n\nX [[PMID:11111111]].", [])
        assert out["cited_pmids"] == ["11111111"]
        assert out["cited"] == []

    def test_the_status_payload_carries_the_cited_set(self, monkeypatch):
        """The browser cannot compute this — it never sees which markers the
        answer carries once they are rendered as pills."""
        import app as app_mod
        app_mod.app.config["TESTING"] = True
        job_id = "trust-surface-v1-test"
        with app_mod.jobs_lock:
            app_mod.jobs[job_id] = {
                "status": "complete", "checks_status": "complete",
                "answer": fixture_answer(), "papers": POOL,
            }
        try:
            body = app_mod.app.test_client().get("/status/%s" % job_id).get_json()
        finally:
            with app_mod.jobs_lock:
                app_mod.jobs.pop(job_id, None)
        assert set(body["cited_pmids"]) == set(endo_ai._extract_cited_pmids(fixture_answer()))
        assert len(body["papers"]) == 29, "the pool itself is still disclosed"

    def test_the_browser_splits_the_pool_on_that_set(self):
        cited, uncited = run_node(
            "var s = citedPapersFor(J);"
            "console.log(JSON.stringify([s.cited.map(function(p){return p.pmid;}),"
            "s.uncited.map(function(p){return p.pmid;})]));",
            names=["citedPapersFor"],
            preamble="var J = %s;\n" % json.dumps({
                "papers": POOL,
                "cited_pmids": assemble_bibliography(fixture_answer(),
                                                     POOL)["cited_pmids"]}))
        assert len(cited) == 7
        assert len(uncited) == 22
        assert "2084204" in uncited

    def test_a_payload_without_the_field_shows_the_pre_fix_view(self):
        """An old cached job or a history record written before this change
        must show its papers, not an empty bibliography."""
        cited, uncited = run_node(
            "var s = citedPapersFor(J);"
            "console.log(JSON.stringify([s.cited.length, s.uncited.length]));",
            names=["citedPapersFor"],
            preamble="var J = %s;\n" % json.dumps({"papers": POOL}))
        assert (cited, uncited) == (29, 0)

    def test_the_same_assembler_holds_on_the_curriculum_fixture(self):
        """The second document Q5 asks for. The Deep Learning path shares the
        assembler, so the property is the same one.

        (Stage 2's regenerated anesthesia curriculum joins this test at item M;
        the laser curriculum is the post-fix document that exists today.)"""
        answer = CURRICULUM.read_text(encoding="utf-8")
        cited  = set(endo_ai._extract_cited_pmids(answer))
        assert len(cited) > 20, "fixture too thin to prove anything"
        pool = ([{"pmid": p, "score": 70.0, "level_key": "level1"} for p in cited] +
                [{"pmid": "2084204", "score": 74.0, "level_key": "classic"}])
        out = assemble_bibliography(answer, pool)
        assert {p["pmid"] for p in out["cited"]} == cited
        assert [p["pmid"] for p in out["uncited"]] == ["2084204"]


# ── Q6: a score ranks only within its tier ────────────────

def _sorted_pmids(papers):
    return run_node(
        "console.log(JSON.stringify([sortPapersByTierThenScore(P)"
        ".map(function(p){return p.pmid;})]));",
        names=["TIER_DISPLAY", "TIER_SHORT", "tierShortLabel", "_tierRank",
               "sortPapersByTierThenScore"],
        preamble="var P = %s;\n" % json.dumps(papers))[0]


TIER_RANK = {k: i for i, k in enumerate(
    ["cochrane", "level1", "classic", "level2", "level3a", "level3",
     "level3b", "level4", "invitro", "level5"])}


class TestTheTableRanksWithinTierNotAcrossIt:

    def test_the_measured_inversion(self):
        """Stated as a fact about the pool, before any ordering is applied."""
        by_score = sorted(POOL, key=lambda p: -p["score"])
        ids = [p["pmid"] for p in by_score]
        assert ids.index("ESE-QG-2023") == 0
        assert ids.index("27759881") == len(POOL) - 1

    def test_the_cochrane_review_ranks_first_despite_the_lowest_score(self):
        order = _sorted_pmids(POOL)
        assert order[0] == "27759881"

    def test_no_lower_tier_paper_renders_above_a_higher_tier_one(self):
        """The property, over the whole pool, regardless of score."""
        by_pmid = {p["pmid"]: p for p in POOL}
        ranks = [TIER_RANK[by_pmid[pid]["level_key"]] for pid in _sorted_pmids(POOL)]
        assert ranks == sorted(ranks), "a weaker tier rendered above a stronger one"

    def test_score_still_orders_papers_inside_one_tier(self):
        """Standing rule 4's pair — the fix must not throw the score away.

        The pool is REVERSED first, deliberately. It arrives already ordered by
        score (it was read off a score-sorted table), and Array.prototype.sort
        is stable, so a tier-only comparator would preserve that order and this
        assertion would hold over a mutant that had discarded the score
        entirely. The mutation run found exactly that."""
        shuffled = list(reversed(POOL))
        by_pmid = {p["pmid"]: p for p in POOL}
        level1 = [by_pmid[pid]["score"] for pid in _sorted_pmids(shuffled)
                  if by_pmid[pid]["level_key"] == "level1"]
        assert level1 == sorted(level1, reverse=True)
        assert len(level1) == 25

    def test_an_unknown_tier_sorts_last_rather_than_first(self):
        """A tier the UI has never heard of must not silently outrank
        Cochrane by being absent from the ladder."""
        pool = POOL + [{"pmid": "88888888", "score": 100.0, "level_key": "brand_new"}]
        assert _sorted_pmids(pool)[-1] == "88888888"

    def test_the_column_says_the_score_is_within_tier(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        head = re.search(r'<thead>.*?</thead>', html, re.S).group(0)
        assert "within tier" in head
        assert "<th>Tier</th>" in head

    def test_the_table_is_no_longer_titled_as_a_cross_tier_ranking(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert "Top Papers by Evidence Score" not in html
        assert "grouped by evidence tier" in html


# ── Q3: no impact factor on any rendered surface ──────────

class TestImpactFactorIsGone:

    REAL_REFERENCE_LINES = [
        ("1. [PMID: 27759881] Del Fabbro M et al. — Cochrane review. "
         "Cochrane Database Syst Rev (IF: 12.0), 2016. (Score: 73.3/100)",
         "1. [PMID: 27759881] Del Fabbro M et al. — Cochrane review. "
         "Cochrane Database Syst Rev, 2016. (Score: 73.3/100)"),
        ("4. [PMID: 35762859] Bucchi C et al. — review. Int Endod J (IF: 4.5), "
         "2023. n=529. (Score: 80.9/100)",
         "4. [PMID: 35762859] Bucchi C et al. — review. Int Endod J, "
         "2023. n=529. (Score: 80.9/100)"),
    ]

    @pytest.mark.parametrize("line,expected", REAL_REFERENCE_LINES)
    def test_it_is_stripped_and_the_reference_stays_readable(self, line, expected):
        assert strip_impact_factor(line) == expected

    def test_the_fixtures_own_reference_block_comes_out_clean(self):
        refs = FIXTURE.read_text(encoding="utf-8").split("## References")[1] \
                      .split("## Full bibliography")[0]
        assert "(IF:" in refs, "the fixture is supposed to contain the defect"
        assert "IF:" not in strip_impact_factor(refs)

    def test_a_cached_answer_is_cleaned_on_the_way_out(self):
        """Every answer in the query cache was written under the old template.
        A cached answer is a rendered surface."""
        answer = ("## References\n\n1. [PMID: 27759881] Del Fabbro M et al. — "
                  "Cochrane Database Syst Rev (IF: 12.0), 2016.\n")
        out, _ = finalise_answer_text(answer)
        assert "(IF:" not in out
        assert "27759881" in out

    def test_the_prompt_no_longer_asks_the_model_for_one(self):
        """Scoped to the REFERENCES templates themselves — the numbered example
        line each prompt gives the model — rather than to the whole file, which
        also contains prose explaining the defect."""
        src = (ROOT / "endo_ai.py").read_text(encoding="utf-8")
        examples = re.findall(r"^1\. \[PMID: 12345678\].*$", src, re.M)
        assert len(examples) >= 2, "the REFERENCES templates moved"
        for line in examples:
            assert "IF" not in line, "a REFERENCES template still requests it: %s" % line

    def test_the_model_is_not_shown_one(self):
        """The number was in the context line, which is why the model had one
        to write. Stripping only at the renderer would leave it free to appear
        in prose, a table caption or a speaker note."""
        line = format_paper_context_line({
            "pmid": "27759881", "authors": "Del Fabbro M", "year": "2016",
            "citations": 400, "sample_size": None, "followup_months": 120,
            "impact_factor": 12.0, "score": 73.3})
        assert "IF" not in line
        assert "12.0" not in line
        assert "27759881" in line and "Evidence Score: 73.3" in line

    def test_the_abstract_popover_does_not_render_one(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        assert "'IF ' + _provEscape" not in html
        assert "impact_factor" not in html, \
            "the template still reads an impact factor onto a surface"

    def test_a_decision_tree_IF_row_is_not_eaten(self):
        """Standing rule 4's pair, and a real shape: curriculum decision trees
        are written as IF / THEN / BECAUSE rows. A strip aggressive enough to
        catch a bare "IF 4.5" would corrupt them, which is why only the
        punctuated forms are removed."""
        row = "IF 4 or more canals are present, THEN allow 45 minutes."
        assert strip_impact_factor(row) == row


class TestTheRenderedAnswerCarriesNone:
    """Asserted on rendered output, not only on a grep of the template."""

    def test_no_impact_factor_survives_to_the_page(self):
        answer = ("## References\n\n1. [PMID: 27759881] Del Fabbro M et al. — "
                  "Cochrane Database Syst Rev (IF: 12.0), 2016.\n"
                  "2. [PMID: 35762859] Bucchi C et al. — Int Endod J (IF: 4.5), 2023.\n")
        clean, _ = finalise_answer_text(answer)
        html, = run_node("console.log(JSON.stringify([renderAnswer(%s)]));"
                         % json.dumps(clean))
        assert "IF:" not in html
        assert "12.0" not in html and "4.5" not in html
        assert "Cochrane Database Syst Rev" in html
