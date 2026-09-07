"""Item C (2026-09-09) — an animal study says so in the sentence that cites it.

THE MEASURED DEFECT. 86 library rows report a non-human subject. Across the
stored archive on 2026-09-08: 205 documents, 60 citations of one of those rows,
53 of them prose claims, and **48 of those never said the subjects were
animals** anywhere in the citing sentence. A clinician would have had to open
the reference to find out the finding came from a rat.

WHY THIS IS AT RENDER TIME AND NOT A REWRITE. The 2026-09-08 fix was upstream —
a context-line marker and a prompt sentence — and it changes what Curo writes
NEXT. It does nothing for 171 stored answers that are served again on every
archive read. Stored text is not rewritten: the archive is a record of what was
said, and it is corrected on the way out, exactly as the redirect rewrite
corrects a retired citation without touching the file.

After: **0 of 53 prose claims unlabelled**, denominator unchanged.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import endo_ai as E  # noqa: E402
import rag  # noqa: E402

# Real rows, from the 2026-09-08 backfill.
DOG = "25146016"        # pulpal responses to pulpotomy in dogs, level2
RABBIT = "39754111"     # pulpal response to direct capping, rabbit, level2
HUMAN = "27759881"      # Cochrane, single vs multiple visit
MAP = {DOG: "dog", RABBIT: "rabbit"}


class TestTheLabelIsApplied:

    def test_a_plain_claim_gets_the_species(self):
        out, n = E.label_animal_citations(
            "Pulpal healing was complete at six months [[PMID:%s]]." % DOG,
            mapping=MAP)
        assert n == 1
        assert "(animal study: dog)" in out

    def test_the_label_goes_inside_the_sentence(self):
        """Before the full stop, so the sentence still reads as one sentence
        rather than as a claim followed by a fragment."""
        out, _n = E.label_animal_citations(
            "Healing was complete [[PMID:%s]]." % DOG, mapping=MAP)
        assert out.rstrip().endswith("(animal study: dog).")

    def test_two_species_in_one_sentence_are_both_named(self):
        out, n = E.label_animal_citations(
            "Both performed similarly [[PMID:%s]] [[PMID:%s]]." % (DOG, RABBIT),
            mapping=MAP)
        assert n == 1
        assert "(animal study: dog, rabbit)" in out

    def test_a_human_row_is_untouched(self):
        text = "Single-visit was equivalent [[PMID:%s]]." % HUMAN
        out, n = E.label_animal_citations(text, mapping=MAP)
        assert (out, n) == (text, 0)

    def test_a_sentence_that_already_names_the_species_is_left_alone(self):
        """The upstream prompt fix makes new answers say it themselves.
        Labelling again would produce "in a dog model … (animal study: dog)"."""
        text = "In a dog model, healing was complete [[PMID:%s]]." % DOG
        out, n = E.label_animal_citations(text, mapping=MAP)
        assert (out, n) == (text, 0)

    def test_the_reference_list_form_is_deliberately_not_labelled(self):
        """`[PMID: n]` is the BIBLIOGRAPHY form, and a bibliography entry is
        not a claim — it already names the paper's title and authors, where a
        species belongs to the paper rather than to an assertion about a
        patient. The harm measurement classifies those 7 lines as "not a
        claim" and this must agree with it, or the two numbers stop meaning
        the same thing.

        This was written the other way round first, asserting the reference
        form SHOULD be labelled. It fails against `_extract_cited_pmids`, which
        matches only the inline form — and the measurement settles which is
        right: after rendering, 0 of 53 prose claims are unlabelled, so no
        prose claim in the archive uses the bibliography form.
        """
        text = "1. [PMID: %s] Smith J et al. — pulpotomy in dogs." % DOG
        assert E.label_animal_citations(text, mapping=MAP) == (text, 0)

    def test_an_empty_map_changes_nothing(self):
        text = "Healing was complete [[PMID:%s]]." % DOG
        assert E.label_animal_citations(text, mapping={}) == (text, 0)


class TestItRunsInTheFinaliser:
    """`finalise_answer_text` is what every path calls, fresh and cached alike.
    A labeller nobody calls is the defect rule 14 exists for."""

    def test_the_finaliser_calls_it(self):
        import inspect
        assert "label_animal_citations" in inspect.getsource(
            E.finalise_answer_text)

    def test_it_runs_after_the_citation_detectors(self):
        """It appends prose next to a citation. Running before the quarantine
        pass or the banner would let a labelled claim be counted differently
        from an unlabelled one — the failure that made GL rendering last."""
        import inspect
        src = inspect.getsource(E.finalise_answer_text)
        assert (src.index("quarantine_unsourced_content")
                < src.index("label_animal_citations"))
        assert (src.index("render_gl_citations")
                < src.index("label_animal_citations"))

    def test_a_real_answer_comes_out_labelled(self, tmp_path):
        """End to end through the finaliser, on the real map."""
        E._reset_animal_map()
        if not rag.DATABASE_URL:
            pytest.skip("DATABASE_URL not set")
        if DOG not in E._animal_map():
            pytest.skip("%s is not labelled in this library" % DOG)
        out, _blocks = E.finalise_answer_text(
            "## CLINICAL RECOMMENDATION\n\n"
            "Pulpal healing was complete at six months [[PMID:%s]].\n" % DOG)
        assert "(animal study: dog)" in out


class TestTheMutation:

    def test_removing_the_label_leaves_the_claim_unmarked(self):
        """MUTATION CHECK, by running the real function with an empty map —
        which is what a build without the labeller produces. If the assertions
        above still passed with no label applied, they would be testing the
        fixture rather than the code."""
        text = "Pulpal healing was complete [[PMID:%s]]." % DOG
        labelled, n = E.label_animal_citations(text, mapping=MAP)
        unlabelled, n0 = E.label_animal_citations(text, mapping={})
        assert n == 1 and n0 == 0
        assert "(animal study" in labelled
        assert "(animal study" not in unlabelled

    def test_the_already_labelled_guard_is_actually_consulted(self,
                                                             monkeypatch):
        """Disable the guard and watch a sentence that already names the
        species get a second label."""
        text = "In a dog model, healing was complete [[PMID:%s]]." % DOG
        assert E.label_animal_citations(text, mapping=MAP)[1] == 0
        import re as _re
        monkeypatch.setattr(E, "_ANIMAL_ALREADY_RE",
                            _re.compile(r"(?!x)x"))     # matches nothing
        out, n = E.label_animal_citations(text, mapping=MAP)
        assert n == 1 and "(animal study: dog)" in out, (
            "the already-labelled guard is not consulted at call time")
