"""A51(a) — the parameter-conflict notice, on the path that serves a document.

`detect_parameter_conflicts` has always found these. It was called by
`scripts/regenerate_curriculum.py` as a metric, and by
`annotate_curriculum_consistency` at GENERATION time -- which makes a model
call and fails closed -- and by nothing at all on the path that hands a
document to a reader. The detector was never missing. The wiring was.

A SURFACING GATE, NOT A BLOCKING ONE. A curriculum with a parameter conflict
is still useful: different studies use different concentrations and each
module may be citing its own correctly. Both values are shown, neither is
suppressed, and no winner is picked -- choosing one would be inventing a
clinical judgement out of a string comparison.

THE FALSE-POSITIVE CHECK IS THE ONE THAT MATTERS. A notice on a clean
document teaches the reader to ignore notices, and then it protects nobody on
the documents that need it. `TestItStaysSilentOnCleanDocuments` is therefore
the load-bearing class here, not the true-positive one.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import endo_ai as E

HEADER = E._CONFLICT_HEADER


def curriculum(*modules, header=True):
    """Assemble a minimal document with the shape the splitter expects."""
    parts = []
    if header:
        parts.append("# A Curriculum\n\n## OVERVIEW\n\nSome overview text.\n")
    for i, body in enumerate(modules, 1):
        parts.append("## Module %d — Topic %d\n\n%s\n" % (i, i, body))
    return "\n".join(parts)


FILLER = ("This module discusses the clinical procedure at length and "
          "contains enough words to clear the forty-word minimum the module "
          "splitter applies, which exists so that a stray heading with a "
          "single line under it is not mistaken for a module body in the "
          "assembled document. ")

CONFLICTING = curriculum(
    FILLER + "Irrigate with 2.5% NaOCl throughout the procedure.",
    FILLER + "Irrigate with 5.25% NaOCl throughout the procedure.",
)

CLEAN = curriculum(
    FILLER + "Irrigate with 2.5% NaOCl throughout the procedure.",
    FILLER + "Continue irrigation with 2.5% NaOCl as above.",
)


def served(text):
    out = E.finalise_answer_text(text)
    return out[0] if isinstance(out, tuple) else out


class TestItFiresWhenTheDocumentDisagreesWithItself:

    def test_the_notice_appears(self):
        assert HEADER in served(CONFLICTING)

    def test_it_names_both_values_and_picks_neither(self):
        """Not suppressing either value is the point. A gate that showed one
        number would be making a clinical choice out of a string comparison."""
        import re
        out = served(CONFLICTING)
        block = out[out.index(HEADER):]
        block = block[:block.index("\n\n")] if "\n\n" in block else block
        assert "2.5" in block and "5.25" in block

        # Precise, not keyword-crude: an earlier version banned the bare word
        # "use" and tripped on the note's own sentence "different studies use
        # different parameters". What must not appear is a RECOMMENDATION
        # naming one of the values -- an imperative or a correctness claim
        # attached to a number.
        picks_a_winner = [
            r"(?:should|must|correct|prefer\w*|recommend\w*)[^.]{0,40}\d",
            r"\d[^.]{0,40}(?:is\s+correct|is\s+recommended|is\s+preferred)",
            r"\buse\s+(?:the\s+)?\d",
        ]
        for pat in picks_a_winner:
            m = re.search(pat, block, re.I)
            assert not m, (
                f"the notice appears to recommend a value: {m.group(0)!r}")

    def test_it_names_where_each_value_is(self):
        out = served(CONFLICTING)
        block = out[out.index(HEADER):]
        assert "Module 1" in block and "Module 2" in block

    def test_it_names_the_quantity(self):
        assert "naocl" in served(CONFLICTING).lower()

    def test_it_lands_before_the_first_module(self):
        """A conflict notice under a protocol the reader has already followed
        is not a warning."""
        out = served(CONFLICTING)
        assert out.index(HEADER) < out.index("## Module 1")


class TestItStaysSilentOnCleanDocuments:
    """The load-bearing class. A false positive costs more than a miss,
    because it trains the reader to ignore the notice everywhere."""

    def test_a_consistent_curriculum_gets_no_notice(self):
        assert HEADER not in served(CLEAN)

    def test_one_module_stating_two_values_is_not_a_conflict(self):
        """A single passage contrasting 2% and 5.25% NaOCl is usually
        deliberate. The >=2-module rule is `detect_parameter_conflicts`'s and
        is preserved here deliberately -- see the report for why that rule is
        WRONG for time thresholds and right for concentrations."""
        one = curriculum(
            FILLER + "Compare 2.5% NaOCl with 5.25% NaOCl in this module.",
            FILLER + "This module does not discuss irrigant concentration.")
        assert HEADER not in served(one)

    def test_a_literature_answer_is_untouched(self):
        lit = ("## CLINICAL RECOMMENDATION\n\nIrrigate with 2.5% NaOCl "
               "[[PMID:27759881]]. Others use 5.25% NaOCl [[PMID:35762859]].\n")
        assert HEADER not in served(lit)

    def test_a_document_with_no_modules_is_untouched(self):
        assert E.render_numeric_conflict_notice("plain text") == "plain text"

    def test_empty_input_is_safe(self):
        assert E.render_numeric_conflict_notice("") == ""
        assert E.render_numeric_conflict_notice(None) == ""


class TestItIsIdempotent:
    """`finalise_answer_text` runs on every view of a stored row. A notice
    that stacked would grow without bound on the demo surfaces -- which is
    exactly the shape of the G2 whitespace defect found on 2026-09-04."""

    def test_rendering_twice_adds_one_notice(self):
        once = served(CONFLICTING)
        twice = served(once)
        assert once.count(HEADER) == 1
        assert twice.count(HEADER) == 1

    def test_the_second_render_changes_nothing_at_all(self):
        once = served(CONFLICTING)
        assert served(once) == once

    def test_the_stored_text_is_not_mutated(self):
        before = CONFLICTING
        served(before)
        assert CONFLICTING == before


class TestTheModuleSplitter:
    """Item 6's splitter cut a module body at its first `## ` SUBheading.

    Curricula put `## Clinical Application` (an h2) inside every module, so
    module bodies were truncated to roughly a third of their length -- 767
    words where the module holds 2,128 -- and the protocol sections where the
    concentrations actually live were never scanned. That is why item 6
    reported 25 of 36 rather than 33 of 36.
    """

    def test_a_module_body_includes_its_own_subheadings(self):
        text = curriculum(
            FILLER + "Intro prose.\n\n## Clinical Application\n\n"
            + FILLER + "Irrigate with 5.25% NaOCl here in the protocol.",
            FILLER + "Second module prose.")
        mods = E.curriculum_modules(text)
        assert len(mods) == 2
        assert "5.25% NaOCl" in mods[0][1], (
            "the module body was truncated at its `## Clinical Application` "
            "subheading — this is the defect that undercounted item 6")

    def test_reference_sections_are_not_scanned(self):
        """A reference list quoting two papers' titles is not the document
        disagreeing with itself."""
        text = (curriculum(FILLER + "Irrigate with 2.5% NaOCl.",
                           FILLER + "Irrigate with 2.5% NaOCl.")
                + "\n## REFERENCES\n\n1. Effect of 5.25% NaOCl on dentine.\n")
        assert HEADER not in served(text)


class TestOnTheRealCorpus:
    """Pinned as an INVARIANT rather than a literal count, because the corpus
    grows. The counts at the time of writing (33 firing, 3 silent of 36) are
    in eval/reports/a51a_numeric_conflicts.md."""

    @pytest.fixture(scope="class")
    def corpus(self):
        import glob
        import json
        docs = []
        for p in sorted(glob.glob(str(Path(__file__).parent.parent
                                      / "learn_history" / "*.json")))[:40]:
            try:
                rec = json.loads(Path(p).read_text(encoding="utf-8"))
            except Exception:
                continue
            if rec.get("answer"):
                docs.append((p, rec["answer"]))
        if not docs:
            pytest.skip("no stored curricula available")
        return docs

    def test_no_silent_document_has_a_conflict(self, corpus):
        """The false-positive invariant, on real documents."""
        for name, text in corpus:
            mods = E.curriculum_modules(text)
            if len(mods) < 2:
                continue
            n = len(E.detect_parameter_conflicts(mods))
            has = HEADER in served(text)
            if not has:
                assert n == 0, f"{name}: {n} conflicts but no notice rendered"

    def test_no_notice_without_a_detected_conflict(self, corpus):
        for name, text in corpus:
            mods = E.curriculum_modules(text)
            if len(mods) < 2:
                continue
            n = len(E.detect_parameter_conflicts(mods))
            if HEADER in served(text):
                assert n > 0, f"{name}: notice rendered with no conflict"

    def test_it_is_idempotent_across_the_corpus(self, corpus):
        for name, text in corpus:
            once = served(text)
            assert served(once) == once, f"{name}: not idempotent"
