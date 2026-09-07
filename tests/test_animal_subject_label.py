"""Item E (2026-09-08) — whose teeth were these.

86 rows in the library report a non-human subject and 9 of them sit on the HUMAN
clinical ladder: a rat pulp-capping study at level2, a dog pulpotomy comparison
at level2, a rabbit direct-capping study at level2. Nothing in the context line
distinguished them from a human trial, so neither the clinician nor the model
writing the answer could tell.

MEASURED HARM, in the stored archive rather than in principle: 209 documents,
60 citations of an animal-subject row, 53 of them prose claims, and **48 of
those never say the subjects were animals**. That is the defect in its exact
form — not "an animal study was cited", which is legitimate and sometimes the
only evidence there is, but "cited as though it were clinical evidence".

Three things had to be true and none of them was: the row must know what it is
(`animal_subject`), the model must be told (`ANIMAL STUDY (<species>)` on the
context line, plus `ANIMAL_PROMPT_BLOCK`), and new rows must arrive already
labelled (`rag._animal_label` on the write-back). A label applied once by a
migration is a fact about the day someone ran a script.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import endo_ai as E  # noqa: E402
import rag  # noqa: E402
from animal_species import species_from_reason  # noqa: E402
from animal_subjects import detect_animal_subject  # noqa: E402


class TestTheSpeciesIsReadOffTheCueThatFired:

    def test_it_names_the_species(self):
        assert species_from_reason("title: in dogs") == "dog"
        assert species_from_reason("abstract: bovine pulp") == "bovine"
        assert species_from_reason("abstract: in monkeys") == "monkey"

    def test_it_never_invents_one(self):
        """A veterinary-journal hit names no species. "unspecified" is the
        honest label; a guessed species would be read as fact."""
        assert species_from_reason("veterinary journal: veterinar") == "unspecified"
        assert species_from_reason("title: an animal study") == "unspecified"

    def test_matching_is_word_bounded(self):
        """THE BUG THIS CAUGHT IN ITS OWN FIRST VERSION. Written through a
        shell heredoc, the `\\b` anchors became literal BACKSPACE bytes: the
        pattern was `\\x08dog\\x08`, invisible to grep, rendered as a plain
        substring match by `inspect.getsource`, and the function returned
        "unspecified" for every input while looking correct in every view.
        Without word bounds, "cat" fires inside "indicate"."""
        assert species_from_reason("abstract: indicate") == "unspecified"
        assert species_from_reason("abstract: stratified") == "unspecified"
        assert species_from_reason("title: in cats") == "cat"


class TestTheCueMustBeAboutThisStudy:
    """Found by adjudicating, by hand, the rows on the HUMAN clinical ladder —
    where a wrong label actually harms someone. Both false positives failed the
    same way, and it is the same failure item D measured in the abstract
    design-extractor: a cue in a sentence about something else."""

    def test_a_previous_study_does_not_make_this_one_animal(self):
        """PMID 26275599 — "Evaluation of Root Canal Debridement of HUMAN
        MOLARS", labelled bovine from "...has been shown to result in a higher
        tissue dissolution rate in a study using bovine muscle"."""
        is_animal, why = detect_animal_subject(
            "Evaluation of Root Canal Debridement of Human Molars",
            "The system has been shown to result in a higher tissue "
            "dissolution rate in a study using bovine muscle. The purpose of "
            "this study was to compare debridement efficacy in extracted "
            "human molars.")
        assert not is_animal, "labelled from someone else's experiment: %s" % why

    def test_recommended_future_work_does_not_either(self):
        """PMID 24331984 — a human systematic review labelled from "Further
        studies, including those based on an experimental animal model, should
        provide more data"."""
        is_animal, why = detect_animal_subject(
            "Human cytomegalovirus in apical periodontitis: a review",
            "Results failed to reach statistical significance. Further "
            "studies, including those based on an experimental animal model, "
            "should provide more data on herpesviruses.")
        assert not is_animal, "labelled from work not yet done: %s" % why

    def test_a_real_animal_study_is_still_caught(self):
        """THE CONTROL ARM. Without it the two tests above pass for a build in
        which the classifier fires on nothing at all (rule 4)."""
        is_animal, why = detect_animal_subject(
            "Comparison of pulpal responses to pulpotomy in dogs",
            "Pulpotomies were performed in 12 male beagle dogs and the pulps "
            "examined histologically after 6 months.")
        assert is_animal, why
        assert species_from_reason(why) == "dog"

    def test_the_veto_is_actually_consulted(self, monkeypatch):
        """MUTATION CHECK, by running the classifier with the veto disabled
        rather than by reading the source for it."""
        import animal_subjects as A
        text = ("The system has been shown to work in a study using bovine "
                "muscle. This trial enrolled 40 adults.")
        assert not detect_animal_subject("Root canal debridement", text)[0]
        monkeypatch.setattr(A, "_cue_is_about_this_study",
                            lambda text, match: True)
        assert detect_animal_subject("Root canal debridement", text)[0], (
            "disabling the sentence-scope veto changed nothing — it is not "
            "being applied")


class TestTheContextLineSaysIt:

    def test_an_animal_row_opens_with_the_label(self):
        line = E.format_paper_context_line({
            "pmid": "25146016", "authors": "X", "year": 2014, "citations": 3,
            "score": 44.0, "level_key": "level2", "animal_subject": "dog"})
        assert line.lstrip().startswith("ANIMAL STUDY (dog)"), line
        assert "PMID: 25146016" in line

    def test_a_human_row_is_untouched(self):
        line = E.format_paper_context_line({
            "pmid": "27759881", "authors": "X", "year": 2016, "citations": 9,
            "score": 73.3, "level_key": "cochrane", "animal_subject": ""})
        assert "ANIMAL STUDY" not in line
        assert line.lstrip().startswith("PMID:")

    def test_the_label_precedes_the_score_it_qualifies(self):
        line = E.format_paper_context_line({
            "pmid": "39754111", "authors": "X", "year": 2024, "citations": 1,
            "score": 51.2, "level_key": "level2", "animal_subject": "rabbit"})
        assert line.index("ANIMAL STUDY") < line.index("Evidence Score"), (
            "the score is the thing the label qualifies; it must come first")

    def test_an_unspecified_species_still_warns(self):
        line = E.format_paper_context_line({
            "pmid": "38407663", "authors": "X", "year": 2024, "citations": 0,
            "score": 60.0, "level_key": "level1",
            "animal_subject": "unspecified"})
        assert "ANIMAL STUDY (unspecified)" in line


class TestTheModelIsToldWhatToDoWithIt:

    def test_the_prompt_block_exists_and_says_the_key_thing(self):
        b = E.ANIMAL_PROMPT_BLOCK
        assert "ANIMAL STUDY (species)" in b
        assert "IN THE SENTENCE THAT CITES IT" in b, (
            "the whole harm is a species named nowhere near the claim")
        assert "Do not discard it" in b, (
            "an animal study is real evidence; suppressing it is a different "
            "defect from mislabelling it")

    def test_it_reaches_the_prompt_every_answer_path_builds(self):
        """A block nobody concatenates is the defect rule 14 exists for."""
        import inspect
        src = inspect.getsource(E.ask_clinical_question)
        assert "ANIMAL_PROMPT_BLOCK" in src


class TestNewRowsArriveLabelled:

    def test_the_write_back_classifies_on_arrival(self):
        assert rag._animal_label(
            "Pulp capping in dogs",
            "We capped pulps in 12 beagle dogs.", "J Endod")[0] == "dog"

    def test_a_human_paper_gets_no_label(self):
        assert rag._animal_label(
            "A randomised trial in adults",
            "Ninety adult patients were randomised.", "Int Endod J") == ("", "")

    def test_a_veterinary_journal_takes_its_species_from_the_title(self):
        """41493880 is "...in Dogs Undergoing Dental Procedures" in a
        veterinary journal: correctly animal, and "unspecified" until the title
        is consulted. Only the title, never the abstract — a title is about
        this study by construction."""
        species, why = rag._animal_label(
            "Opioid-Free Anesthesia in Dogs Undergoing Dental Procedures",
            "Procedures were performed and recovery scored.",
            "Veterinary Anaesthesia and Analgesia")
        assert species == "dog", why

    def test_a_classifier_failure_never_blocks_learning(self, monkeypatch):
        """A paper must still be learned if the classifier raises. Losing a
        label is a nuisance; losing the paper is a recall regression."""
        import animal_subjects as A

        def boom(*a, **k):
            raise RuntimeError("classifier exploded")

        monkeypatch.setattr(A, "detect_animal_subject", boom)
        assert rag._animal_label("t", "a", "j") == ("", "")

    def test_the_insert_carries_the_columns(self):
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "rag.py"), encoding="utf-8").read()
        i = src.index("INSERT INTO endo_papers_rag")
        j = src.index("ON CONFLICT", i)
        assert "animal_subject" in src[i:j], (
            "the write-back does not store the label it computes")


@pytest.mark.skipif(not rag.DATABASE_URL, reason="DATABASE_URL not set")
class TestTheLibrary:

    def _q(self, sql, args=()):
        conn = rag.get_conn()
        cur = conn.cursor()
        cur.execute(sql, args)
        out = cur.fetchall()
        cur.close()
        conn.close()
        return out

    def test_the_columns_exist(self):
        got = {r[0] for r in self._q(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'endo_papers_rag' "
            "AND column_name LIKE 'animal%%'")}
        assert {"animal_subject", "animal_subject_why"} <= got

    def test_rows_are_labelled(self):
        n = self._q("SELECT COUNT(*) FROM endo_papers_rag "
                    "WHERE COALESCE(animal_subject,'') <> ''")[0][0]
        assert n > 0, "no row carries a species — did the backfill run?"

    def test_every_label_records_why(self):
        """This classifier's whole risk is false positives and a count cannot
        show them, so the cue that fired is kept for every labelled row."""
        bad = self._q("SELECT pmid FROM endo_papers_rag "
                      "WHERE COALESCE(animal_subject,'') <> '' "
                      "AND COALESCE(animal_subject_why,'') = ''")
        assert not bad, "labels with no audit trail: %s" % [r[0] for r in bad[:5]]

    def test_the_label_reaches_a_retrieved_row(self):
        """`rag.search` must SELECT the column, or the context line can never
        show it however correct the row is."""
        rows = rag.search("pulp capping in dogs", limit=10)
        assert rows, "no rows returned"
        assert any("animal_subject" in r for r in rows), (
            "rag.search does not return the column, so the label cannot reach "
            "the model")
