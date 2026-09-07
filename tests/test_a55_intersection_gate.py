"""A55 — the library must not answer alone what it does not hold.

THE CASUALTY THIS STARTS FROM. A54's question, "MTA versus bioceramic as
retrograde filling after apicoectomy", routed to the LIBRARY on 200 hits and no
PubMed lane ran. The library held **0 of the 8** head-to-head papers. The
coverage gate read 149 hits for the material concept and 24 for the surgery
concept against `min_concept_papers = 3`, and passed.

The gate was not broken. It was reading a number that cannot answer the question
being asked of it: `question_coverage` asks each concept SEPARATELY, so 149
papers about MTA and 24 about apical surgery can be 173 papers of which none is
about MTA in apical surgery. Only the INTERSECTION distinguishes "the library
knows about each of these subjects" from "the library holds papers about this
question".

WHAT THE MEASUREMENT SAID ABOUT THE FIX, and it is not flattering. Over the 27
LIBRARY-routed questions of the 32-question set, the correlation between the
intersection and the fraction of the live result set the library is missing is
**r = -0.22**. All 27 are missing live papers — a median of 80% of what the live
path fetches. There is no threshold that re-routes exactly the bad ones. The
gate ships anyway because it is ONE-DIRECTIONAL: everything failing it goes
live, which is a superset, so an unnecessary re-route costs ~$0.006 and 40-75 s
while a wrongly-kept question costs a clinician the papers that answer them.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import endo_ai as E  # noqa: E402
from app import RELEVANCE_GATE  # noqa: E402

# The A54 question's REAL concept counts, from `eval/reports/a55_false_coverage.json`
# as it stood before item 3 ingested the fixtures. Per-group counts that pass the
# gate comfortably; an intersection that does not.
A54_PER_GROUP = [87, 12, 26]
A54_INTERSECTION = 6


class TestTheGateHasAnIntersectionFloor:

    def test_the_threshold_exists_and_is_declared(self):
        assert "min_intersection_papers" in RELEVANCE_GATE
        assert RELEVANCE_GATE["min_intersection_papers"] > 0

    def test_the_a54_question_fails_it_on_its_real_numbers(self):
        """THE FIXTURE IS THE REAL CASE. Every concept group clears
        `min_concept_papers = 3` — the weakest is 12 — and the intersection is
        6. Under the old gate this routed LIBRARY with none of the 8 papers."""
        assert min(A54_PER_GROUP) >= RELEVANCE_GATE["min_concept_papers"], (
            "the old condition passed; that is the premise of this test")
        assert A54_INTERSECTION < RELEVANCE_GATE["min_intersection_papers"], (
            "the intersection floor no longer catches the case it was written "
            "for")

    def test_restoring_the_old_decision_routes_library(self):
        """MUTATION CHECK, as the item specifies: restore the concepts-only
        decision and watch the A54 numbers route LIBRARY again."""
        old_decision = min(A54_PER_GROUP) >= RELEVANCE_GATE["min_concept_papers"]
        new_decision = (old_decision and A54_INTERSECTION
                        >= RELEVANCE_GATE["min_intersection_papers"])
        assert old_decision is True, "the old gate would have routed LIBRARY"
        assert new_decision is False, "the new gate must re-route it"


class TestTheIntersectionItself:

    def test_it_counts_papers_matching_every_group(self):
        groups = [["mta", "mineral trioxide"], ["apicoectomy", "apical surgery"]]
        papers = [
            {"title": "MTA in apicoectomy outcomes", "abstract": ""},
            {"title": "MTA in pulpotomy", "abstract": ""},
            {"title": "Apical surgery: a review", "abstract": ""},
        ]
        assert E.question_intersection(groups, papers) == 1

    def test_it_is_never_greater_than_the_weakest_group(self):
        """A structural property: a paper in the intersection is in every
        group, so the intersection cannot exceed the smallest group count. If
        it ever does, the two are not being matched the same way — and the
        whole value of the number is that it is commensurable with the
        per-group counts the gate already prints."""
        groups = [["mta", "mineral trioxide"], ["apicoectomy", "apical surgery"],
                  ["retrograde", "root-end"]]
        papers = [
            {"title": "MTA retrograde filling in apicoectomy", "abstract": ""},
            {"title": "MTA and root-end sealing", "abstract": ""},
            {"title": "Apical surgery outcomes", "abstract": ""},
            {"title": "Unrelated pulpotomy paper", "abstract": ""},
        ]
        cov = E.question_coverage(groups, papers)
        weakest = min(c["hits"] for c in cov)
        assert E.question_intersection(groups, papers) <= weakest

    def test_it_abstains_when_there_is_no_discriminating_concept(self):
        """Same abstention the concept condition makes: with no groups there is
        nothing to intersect, and blocking on that would send every plain
        endodontic question live."""
        papers = [{"title": "anything", "abstract": ""}] * 5
        assert E.question_intersection([], papers) == len(papers)

    def test_it_reads_the_abstract_as_well_as_the_title(self):
        groups = [["mta"], ["apicoectomy"]]
        papers = [{"title": "A surgical outcome study",
                   "abstract": "We compared MTA after apicoectomy."}]
        assert E.question_intersection(groups, papers) == 1

    def test_it_is_wired_into_the_gate_not_just_defined(self):
        """A helper nothing calls is the defect rule 14 exists for."""
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "app.py"), encoding="utf-8").read()
        # REPAIRED TO IDENTITY 2026-09-09 (rule 39): the conditions moved
        # from the routing decision to the fallback decision when item A
        # made routing live-by-default. See test_coverage_gate.py.
        i = src.index("gate_says_library = (")
        j = src.index(")", src.index("force_route", i))
        assert "covers_intersection" in src[i:j + 200], (
            "the intersection is computed but not part of the decision")


class TestProcedureSynonyms:
    """A54 showed the SURGERY group was the point of failure, not the material
    group: `"endodontic microsurgery"` alone recovers F1, F2, F4 and F7."""

    APICAL = ["apicoectomy", "apicectomy", "root-end resection",
              "root-end filling", "retrograde filling", "periradicular surgery",
              "endodontic microsurgery", "apical microsurgery"]

    def test_the_prompt_asks_for_procedure_nomenclature(self):
        t = E._TERM_PROMPT_TEMPLATE
        assert "PROCEDURE" in t
        assert "microsurgery" in t.lower(), (
            "the instruction does not mention the modern name, which is the "
            "half A54 measured as missing")

    def test_the_instruction_is_general_not_a_lookup_table(self):
        """The item asks for one sentence, general in form. An illustration is
        allowed — the prompt already teaches by example for lasers — but it
        must tell the model to do the same for whatever procedure the question
        names, or it is a hard-coded list for one topic."""
        # WHITESPACE-NORMALISED: the prompt is hard-wrapped, so the phrase
        # spans a line break and a flat substring search misses it.
        t = " ".join(E._TERM_PROMPT_TEMPLATE.lower().split())
        assert "whatever procedure the question actually names" in t

    @pytest.mark.skipif(os.environ.get("CURO_SKIP_LLM") == "1",
                        reason="live model call")
    def test_the_a54_surgery_group_carries_at_least_three_synonyms(self):
        """THE PIN THE ITEM ASKS FOR. Measured before the change: 3 of 8, and
        none of them in the surgery group — they came from the material and
        filling groups. After: 8 of 8, including both microsurgery names."""
        prev = E.TERM_CACHE_ENABLED
        E.TERM_CACHE_ENABLED = False
        try:
            terms = E.generate_search_terms(
                "MTA versus bioceramic as retrograde filling after apicoectomy",
                mode="review")
        finally:
            E.TERM_CACHE_ENABLED = prev
        hits = [s for s in self.APICAL if s in terms.lower()]
        assert len(hits) >= 3, "only %d of 8 procedure synonyms: %s" % (
            len(hits), terms)


class TestTheSpecialtyBlockIsRenderedFromData:
    """A54's synthesis admitted three guidelines, showed all three to the model,
    and the model listed two. Which two is not the model's decision to make."""

    ROWS = [
        {"guideline_id": "ESE-S3-2023", "guideline_org": "ESE",
         "guideline_jurisdiction": "EU", "guideline_status": "current",
         "year": 2023, "title": "ESE S3-level clinical practice guideline",
         "abstract": "Full text of the ESE recommendations."},
        {"guideline_id": "AAE-TREATMENTSTANDARDS-2018", "guideline_org": "AAE",
         "guideline_jurisdiction": "US", "guideline_status": "current",
         "year": 2018, "title": "AAE Treatment Standards White Paper",
         "abstract": "Full text of the AAE standards."},
        {"guideline_id": "FDSRCS-PERIRADICULAR-2020", "guideline_org": "FDSRCS",
         "guideline_jurisdiction": "UK", "guideline_status": "current",
         "year": 2020, "title": "Guidelines for Periradicular Surgery",
         "guideline_url": "https://example.org/fdsrcs",
         "abstract": "GUIDELINE RECORD — pointer only; Curo has not stored "
                     "this document's text."},
    ]

    def test_every_admitted_guideline_appears(self):
        out = E.render_specialty_block(self.ROWS)
        for r in self.ROWS:
            assert r["guideline_org"] in out, (
                "%s was admitted and does not appear in the rendered section"
                % r["guideline_id"])

    def test_dropping_one_from_the_renderer_fails(self):
        """MUTATION CHECK, exactly as the item specifies."""
        out = E.render_specialty_block(self.ROWS[:2])
        assert "FDSRCS" not in out
        with pytest.raises(AssertionError):
            for r in self.ROWS:
                assert r["guideline_org"] in out

    def test_each_row_names_org_jurisdiction_status_and_year(self):
        out = E.render_specialty_block(self.ROWS)
        for token in ("ESE", "EU", "current", "2023", "AAE", "US", "2018",
                      "FDSRCS", "UK", "2020"):
            assert token in out, "the rendered section omits %r" % token

    def test_a_pointer_row_declares_that_its_position_is_not_quoted(self):
        """The one thing the model must never do for a pointer is state a
        position. The renderer says so instead, and offers the URL."""
        out = E.render_specialty_block(self.ROWS)
        assert "position not quoted" in out
        assert "https://example.org/fdsrcs" in out

    def test_a_pointer_row_ignores_a_model_sentence_for_it(self):
        """If the model writes a position for a pointer anyway — which is the
        hallucination the pointer mechanism exists to prevent — the renderer
        must not print it."""
        out = E.render_specialty_block(
            self.ROWS,
            {"FDSRCS-PERIRADICULAR-2020": "FDSRCS recommends immediate surgery."})
        assert "recommends immediate surgery" not in out
        assert "position not quoted" in out

    def test_a_quoted_row_carries_the_models_sentence(self):
        out = E.render_specialty_block(
            self.ROWS, {"ESE-S3-2023": "ESE recommends orthograde retreatment "
                                       "first where feasible."})
        assert "ESE recommends orthograde retreatment first where feasible." in out

    def test_the_order_is_by_jurisdiction_not_by_admission(self):
        """Declared and stable, so a missing jurisdiction reads as a gap in a
        list rather than an absence nobody can see."""
        out = E.render_specialty_block(self.ROWS)
        assert out.index("(EU)") < out.index("(UK)") < out.index("(US)")
        # and reversing the input does not change the rendering
        assert E.render_specialty_block(list(reversed(self.ROWS))) == out

    def test_no_rows_renders_nothing(self):
        assert E.render_specialty_block([]) == ""
        assert E.render_specialty_block(None) == ""
