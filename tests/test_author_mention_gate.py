"""
A45c — UNCITED_AUTHOR_MENTION was matching the specialty's vocabulary.

WHY IT MATTERED. Measured on current code (rule 25), 23% of Review syntheses
retried and 75% of curriculum modules did, and a retry pays for a whole
synthesis twice: $3.015 against $1.472 clean. Attributed by the validator's own
`failure_reason`, **67% of those retries were UNCITED_AUTHOR_MENTION**, and the
two examples in the day's transcripts were "MTA and Biodentine" and
"AAE and ESE". Neither is an author.

WHAT WAS WRONG. The pattern's `and` branch matches any "Capitalised and
Capitalised" pair. Measured across every stored answer, curriculum and fixture:
**819 matches on that branch, of which about 30 are real author pairs — 3.7%
precision.** The largest single false positive is "RCTs and Systematic" at 156
occurrences, from the tier label "Level I — RCTs and Systematic Reviews".

Capitalisation cannot separate "Byström and Sundqvist" from "Photodiagnosis and
Photodynamic Therapy", and a seven-word stopword list cannot hold a specialty's
vocabulary.

THE FIX IS THE LOGIC, NOT THE BAR (rule 6). It still takes exactly one uncited
author to fail an answer. What changed is what counts as one: two independent
signals, either sufficient, with ALL-CAPS vetoing both.

  1. both surnames are ones the LIBRARY knows — `endo_papers_rag.authors`,
     diacritics folded, because the library stores Gostemeyer and the answer
     writes Göstemeyer and that alone lost five real pairs;
  2. the sentence asserts something about them — possessive, or a reporting
     verb within three words. "Fuss and Trope demonstrated" is a citation
     whether or not the library holds a Fuss paper.

RESULT on the same corpus: 62 of 815 kept, 100% of them real author pairs, from
3.7%. Two entries were added from measurement rather than imagination —
"Review" to the stopwords (the only non-author the union kept, 2 of 64), and
`published` REMOVED from the reporting verbs, because a journal publishes and an
author reports.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai as e


def answer(sentence, section="EVIDENCE SUMMARY"):
    return f"## {section}\n\n{sentence}\n"


def flagged(sentence):
    return [a["name"] for a in
            e._detect_uncited_author_mentions(answer(sentence))]


@pytest.fixture(autouse=True)
def _known_surnames(monkeypatch):
    """Pin the surname index so these tests do not depend on the library's
    current contents — the gate's LOGIC is what is under test."""
    monkeypatch.setattr(e, "_library_surnames",
                        lambda: {"bystrom", "sundqvist", "rossi-fedele",
                                 "rodig", "fraser", "webster", "schwendicke",
                                 "gostemeyer", "trope", "aguilar",
                                 "linsuwanont"})


class TestTheSpecialtyVocabularyIsNoLongerAnAuthor:
    """Every string here was matched by the old pattern in a real document."""

    @pytest.mark.parametrize("sentence", [
        "MTA and Biodentine both reduced microleakage in vitro.",
        "AAE and ESE guidance recommends a bonded composite.",
        "NaOCl and EDTA were used in sequence for 60 seconds.",
        "PIPS and SWEEPS achieved comparable smear-layer removal.",
        "PUI and LAI were compared across four studies.",
    ])
    def test_an_acronym_pair_is_not_an_author(self, sentence):
        assert flagged(sentence) == []

    @pytest.mark.parametrize("sentence", [
        "Level I - RCTs and Systematic Reviews are summarised below.",
        "Photodiagnosis and Photodynamic Therapy carried the trial.",
        "Development and Evaluation of a new sealer followed.",
        "Retrospective and Case-Control designs both appear here.",
    ])
    def test_title_case_prose_is_not_an_author(self, sentence):
        assert flagged(sentence) == []

    def test_the_single_largest_false_positive_is_gone(self):
        """156 occurrences across the corpus, from the tier label itself."""
        assert flagged("Level I - RCTs and Systematic Reviews") == []


class TestRealAuthorMentionsStillFail:
    """The bar is unchanged: one uncited author is enough."""

    def test_et_al_is_untouched(self):
        """The branch that was never wrong."""
        assert flagged("Smail-Faugeron et al. reported a 74% success rate.")

    def test_et_al_fires_with_no_verb_and_an_unknown_surname(self):
        """This is the only test that can tell whether `et al.` is exempted in
        its own right. With a reporting verb, or a surname the library knows,
        the other two signals would carry it and a mutation removing the
        exemption would go unnoticed."""
        assert flagged("This is consistent with Nagendrababu et al.")

    def test_a_known_pair_with_a_reporting_verb(self):
        assert flagged("Bystrom and Sundqvist showed that pulp status dominates.")

    def test_a_known_pair_possessive(self):
        assert flagged("Bystrom and Sundqvist's landmark study changed practice.")

    def test_a_known_pair_with_no_assertion_still_fails(self):
        """The surname index is the point of the first signal — it does not
        need the sentence to assert anything."""
        assert flagged("This is consistent with Fraser and Webster.")

    def test_an_UNKNOWN_surname_pair_fails_when_the_sentence_asserts(self):
        """The second signal exists for authors the library does not hold —
        which includes a hallucinated pair, the case that matters most."""
        assert flagged("Fuss and Whitaker demonstrated a classification.")

    def test_diacritics_do_not_lose_a_real_pair(self):
        """The library stores Gostemeyer; the answer writes Göstemeyer. Five
        real pairs were lost to this alone."""
        assert flagged("This follows Schwendicke and Göstemeyer's analysis.")

    def test_a_marker_in_the_same_claim_unit_still_exempts(self):
        assert flagged("Bystrom and Sundqvist showed X [[PMID:12345]].") == []


class TestTheFallbackIsSafe:
    """Rule 28 — where the guard can fail, prefer the direction that keeps the
    gate working."""

    def test_no_surname_index_falls_back_to_the_assertion_signal(self, monkeypatch):
        monkeypatch.setattr(e, "_library_surnames", lambda: set())
        assert flagged("Bystrom and Sundqvist showed that pulp status dominates.")

    def test_a_database_failure_does_not_raise(self, monkeypatch):
        monkeypatch.undo()   # this test needs the REAL _library_surnames
        e._reset_author_surnames()

        def boom():
            raise RuntimeError("db down")
        monkeypatch.setattr("rag.get_conn", boom)
        assert e._library_surnames() == set()
        e._reset_author_surnames()

    def test_the_index_is_built_once(self, monkeypatch):
        monkeypatch.undo()   # this test needs the REAL _library_surnames
        e._reset_author_surnames()
        calls = []

        class Cur:
            def execute(self, *a):
                calls.append(1)

            def fetchall(self):
                return [("Bystrom S, Sundqvist G",)]

            def close(self):
                pass

        class Conn:
            def cursor(self):
                return Cur()

            def close(self):
                pass
        monkeypatch.setattr("rag.get_conn", lambda: Conn())
        assert "bystrom" in e._library_surnames()
        e._library_surnames()
        assert len(calls) == 1, "the surname index must be built once per process"
        e._reset_author_surnames()


class TestTheMeasurementIsRecordedBesideTheCode:

    def test_the_precision_number_is_written_where_the_fix_is(self):
        src = (Path(__file__).parent.parent / "endo_ai.py").read_text(encoding="utf-8")
        assert "PRECISION 3.7%" in src
        assert "819 matches" in src
        assert "67% of synthesis retries" in src

    def test_published_is_deliberately_absent_from_the_verbs(self):
        assert "published" not in e._AUTHOR_REPORTING_VERBS
        src = (Path(__file__).parent.parent / "endo_ai.py").read_text(encoding="utf-8")
        assert "a JOURNAL publishes, an author" in src
