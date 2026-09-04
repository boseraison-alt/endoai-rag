"""
A22b / A22c / A22f — the quarantine block, at the right size and said once.

RB, on the apicoectomy curriculum: the boxes are unreadable and there are far
too many of them. Measured across the stored corpus, he is right and it is not
only cosmetic:

    56 blocks across 7 documents, and 56 identical "Consult directly:" footers
    17 blocks and 17 footers in a single answer

A warning that appears seventeen times is wallpaper — A3's ambient-versus-
alarming finding for the banner, in visual form.

A22b — TWO LEVELS, AND THE MEASUREMENT CHOSE THE THRESHOLD. Block sizes:

    1 sentence   26 blocks  46%
    2 sentences  23 blocks  41%
    3 sentences   6 blocks  11%
    41 sentences  1 block    2%

    inline if <=1   30 full blocks remain, worst document still 10
    inline if <=2    7 full blocks remain, worst document still  2   <- shipped
    inline if <=3    1 full block remains, worst document still  1

A22b's wording is "a single unsourced sentence or step", i.e. <=1. That is not
enough: at <=1 the worst document keeps 10 boxes and still fails A22e's ~5 bar.
Two sentences is not a paragraph, and A22b's own test for the full block is "a
paragraph or more", so <=2 is inside the item's intent and is what meets it.

A22c — one legend at the top, one consolidated note at the end, and the
per-block footer deleted.

A22f — the old wording claimed more than the engine knows. "From the wider
literature (which this search did not return)" asserts the content IS published
and merely went unretrieved. Curo cannot know that; some of this content is
convention that was never studied. Same class as "citations & impact factor".
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai as e

ROOT = Path(__file__).parent.parent

CITED = "The retrieved trials support a bonded composite [[PMID:111]]."
ONE = "Standard practice, not from the retrieved evidence base: etch for 20 s."
TWO = ("Standard practice, not from the retrieved evidence base: etch for 20 s. "
       "Silane follows immediately.")
PARA = ("Not from the evidence base: bridging with LMWH is not indicated. INR "
        "testing is not applicable here. AAE guidance suggests review at six "
        "months. A fourth sentence makes this a paragraph.")


def answer(unsourced):
    return f"## RECOMMENDATION\n\n{CITED}\n\n{unsourced}\n\nAlso supported [[PMID:222]]."


def body_of(out):
    """Everything after the legend and before the consolidated note.

    The legend contains the words "passages marked" and "the model's own
    knowledge", so asserting those against the WHOLE output passes even when
    the block and the inline mark have been removed entirely. Three mutations
    survived on exactly that before this existed.
    """
    text = out.split("## RECOMMENDATION", 1)[-1]
    return text.split("What Curo did not check", 1)[0]


class TestA22bTwoLevelsChosenBySize:

    def test_the_threshold_is_where_the_measurement_put_it(self):
        assert e.QUARANTINE_INLINE_MAX_SENTENCES == 2

    def test_one_sentence_stays_in_the_prose(self):
        out, _b = e.quarantine_unsourced_content(answer(ONE))
        assert e._QUARANTINE_HEADER not in out, "a one-liner must not get a box"
        assert e._QUARANTINE_INLINE_MARK in body_of(out)

    def test_two_sentences_stay_in_the_prose(self):
        """41% of stored blocks are exactly two sentences. At <=1 the worst
        document keeps 10 boxes, which still fails A22e."""
        out, _b = e.quarantine_unsourced_content(answer(TWO))
        assert e._QUARANTINE_HEADER not in out
        assert e._QUARANTINE_INLINE_MARK in body_of(out)

    def test_a_paragraph_keeps_the_full_block(self):
        out, _b = e.quarantine_unsourced_content(answer(PARA))
        assert e._QUARANTINE_HEADER in out

    def test_the_inline_treatment_keeps_every_word(self):
        out, _b = e.quarantine_unsourced_content(answer(TWO))
        assert "Silane follows immediately." in out
        assert "etch for 20 s." in out

    def test_the_inline_treatment_carries_no_boilerplate(self):
        """A22b: 'no header, no footer, no repeated boilerplate'."""
        out, _b = e.quarantine_unsourced_content(answer(ONE))
        body = out.split("## RECOMMENDATION")[1]
        assert "Consult directly" not in body
        assert e._QUARANTINE_NOTE[:30] not in body

    def test_both_levels_are_still_reported_as_quarantined(self):
        """The count feeds the banner and Q2b. An inline passage is still
        unsourced content — the treatment changed, not the fact."""
        for text in (ONE, TWO, PARA):
            _out, blocks = e.quarantine_unsourced_content(answer(text))
            assert len(blocks) == 1, text[:40]


class TestA22cSayItOnce:

    def test_the_per_block_footer_is_gone(self):
        out, _b = e.quarantine_unsourced_content(answer(PARA))
        assert "**Consult directly:**" not in body_of(out)
        # and the block itself carries no footer at all
        assert "Consult directly" not in e._quarantine_block(["a. b. c. d."])

    def test_a_second_block_does_not_add_a_second_legend(self):
        """The early return on `not blocks` hides legend duplication from the
        idempotence test, so this drives the path where blocks ARE found and
        the legend is already present."""
        once, _b = e.quarantine_unsourced_content(answer(PARA))
        more = "\n\n".join([once, "## LATER", PARA, "Cited [[PMID:7]]."])
        twice, blocks = e.quarantine_unsourced_content(more)
        assert blocks, "the new section should have been quarantined"
        assert twice.count("passages marked") == 1

    def test_the_consolidated_note_is_empty_for_no_blocks(self):
        assert e._quarantine_consolidated_note([]) == ""

    def test_there_is_exactly_one_legend(self):
        two = f"## A\n\n{CITED}\n\n{PARA}\n\nCited [[PMID:2]].\n\n## B\n\n{PARA}\n\nCited [[PMID:3]]."
        out, blocks = e.quarantine_unsourced_content(two)
        assert len(blocks) == 2
        assert out.count("passages marked") == 1

    def test_there_is_exactly_one_consolidated_note(self):
        two = f"## A\n\n{CITED}\n\n{PARA}\n\nCited [[PMID:2]].\n\n## B\n\n{PARA}\n\nCited [[PMID:3]]."
        out, _b = e.quarantine_unsourced_content(two)
        assert out.count("What Curo did not check") == 1

    def test_the_note_names_the_bodies_the_passages_lean_on(self):
        out, _b = e.quarantine_unsourced_content(answer(PARA))
        tail = out.split("What Curo did not check")[1]
        assert "AAE" in tail

    def test_nothing_is_added_when_nothing_was_quarantined(self):
        """A note that always appears is the wallpaper this item removes."""
        clean = f"## A\n\n{CITED}\n"
        out, blocks = e.quarantine_unsourced_content(clean)
        assert blocks == []
        assert "What Curo did not check" not in out
        assert "passages marked" not in out

    def test_re_rendering_is_idempotent(self):
        """Rule 18 — A16b re-renders the archive on every read, and this pass
        now adds a legend and a tail that must not accumulate."""
        once, _b = e.quarantine_unsourced_content(answer(PARA))
        twice, blocks2 = e.quarantine_unsourced_content(once)
        assert twice == once
        assert blocks2 == []

    def test_the_inline_mark_is_idempotent_too(self):
        once, _b = e.quarantine_unsourced_content(answer(ONE))
        twice, _b2 = e.quarantine_unsourced_content(once)
        assert twice == once
        assert once.count(e._QUARANTINE_INLINE_MARK) == twice.count(
            e._QUARANTINE_INLINE_MARK)


class TestA22fTheWordingClaimsOnlyWhatIsKnown:

    def test_the_block_no_longer_says_unverified_evidence_base(self):
        out, _b = e.quarantine_unsourced_content(answer(PARA))
        assert "NOT FROM THE EVIDENCE BASE — UNVERIFIED" not in out

    def test_no_surface_asserts_the_content_is_in_the_literature(self):
        """A22f's own test. 'From the wider literature' says the content IS
        published and merely went unretrieved — a claim Curo cannot support."""
        out, _b = e.quarantine_unsourced_content(answer(PARA))
        assert "wider literature" not in out.lower()

    def test_the_wording_names_the_model_as_the_source(self):
        """Asserted against the BLOCK, not the whole answer — the legend says
        the same thing, and a mutation that gutted the block's note passed
        while this checked `out`."""
        out, _b = e.quarantine_unsourced_content(answer(PARA))
        assert "model's own knowledge" in body_of(out)

    def test_the_prompt_no_longer_offers_the_overclaiming_phrase(self):
        """The model wrote that phrase because the prompt handed it over.

        The phrase may still APPEAR in a prompt — the prompts now forbid it by
        name, which is stronger than silence. So every occurrence outside a
        comment must be preceded by a prohibition. A first version of this test
        matched the prohibition itself and failed on the fix.

        A THIRD category exists now: the read-time STRIPPER. 12 occurrences of
        the phrase survive in the stored corpus, written before A22f fixed the
        generator, and `_A22F_OVERCLAIM_RE` removes them on every read. A
        pattern that deletes the phrase is the opposite of a prompt offering
        it, so it is allowed BY NAME — not by a general loosening that a prompt
        could slip through. `test_the_overclaim_is_stripped_from_stored_text`
        below is what holds it to actually doing the job.
        """
        src = (ROOT / "endo_ai.py").read_text(encoding="utf-8")
        bad = []
        for m in re.finditer(r"from the wider literature", src, re.I):
            line_start = src.rfind("\n", 0, m.start()) + 1
            if src[line_start:m.start()].lstrip().startswith("#"):
                continue                      # a comment recording the defect
            window = src[max(0, m.start() - 120):m.start()]
            if "_A22F_OVERCLAIM_RE = re.compile(" in window:
                continue                      # the stripper's own pattern
            if not re.search(r"do not (?:say|write)|never (?:say|write)",
                             window.lower()):
                bad.append(src[max(0, m.start() - 90):m.end() + 20])
        assert not bad, bad

    def test_the_overclaim_is_stripped_from_stored_text(self):
        """The pair for the allowance above: the stripper must actually strip.

        Three real shapes exist in the corpus — a colon, a comma with the
        phrase embedded mid-sentence, and a 90-character parenthetical. A first
        version of the pattern required a <=60-char parenthetical AND a colon
        and removed only 6 of the 12.
        """
        cases = [
            ("From the wider literature (which this search did not return): "
             "AAE and ESE position statements endorse epinephrine.",
             "AAE and ESE position statements endorse epinephrine."),
            ("From the wider literature (which this search did not return), "
             "the decision to attempt removal is driven by the fragment.",
             "The decision to attempt removal is driven by the fragment."),
            ("From the wider literature (which this search did not return, and "
             "which should be consulted directly): calcium hydroxide is used.",
             "Calcium hydroxide is used."),
        ]
        for raw, want in cases:
            got = e._strip_a22f_overclaim(raw)
            assert got == want, "%r -> %r, wanted %r" % (raw, got, want)
            assert "wider literature" not in got.lower()

    def test_the_stripper_runs_on_the_path_that_serves_answers(self):
        """Rule 14 — the test above calls the helper directly, so it passes
        even when nothing calls it. This one goes through the function every
        served and cached answer actually passes through."""
        raw = ("## Findings\n\n"
               "> ⚠ **NOT FROM THE EVIDENCE BASE — UNVERIFIED**\n"
               ">\n"
               "> From the wider literature (which this search did not "
               "return): AAE and ESE position statements endorse epinephrine "
               "— standard practice, not from the retrieved evidence base.\n"
               ">\n"
               "> **Consult directly:** the specialty guidelines for this "
               "question — Curo has not retrieved or checked them.\n")
        served, _ = e.finalise_answer_text(raw)
        assert "wider literature" not in served.lower(), served
        assert "AAE and ESE position statements" in served, (
            "the strip removed the passage instead of the lead-in")

    def test_the_detector_still_matches_the_old_phrase(self):
        """Stored answers use it, and a model may still write it. Narrowing
        the DETECTOR would un-quarantine exactly the content this is about."""
        assert e._UNSOURCED_LABEL_RE.search(
            "From the wider literature, the protocol is as follows.")


class TestA44nStoredDocumentsStillWork:
    """22 stored curricula and every cached answer carry the LEGACY shape, and
    A16b re-renders the archive on every read. 'Should work' is not 'does'."""

    LEGACY = ("## X\n\n"
              "> ⚠ **NOT FROM THE EVIDENCE BASE — UNVERIFIED**\n>\n"
              "> _General clinical knowledge. No paper in this library was "
              "retrieved for it and nothing below was checked against an "
              "abstract._\n>\n"
              "> Old body text here.\n>\n"
              "> **Consult directly:** AAE — Curo has not retrieved or checked "
              "these sources.\n\n"
              "Cited [[PMID:9]].")

    def test_a_legacy_block_is_still_stripped(self):
        assert "Old body" not in e._strip_quarantine_blocks(self.LEGACY)

    def test_a_legacy_block_still_yields_its_content(self):
        out = e._quarantine_content_only(self.LEGACY)
        assert "Old body text here." in out

    def test_a_legacy_block_s_furniture_is_still_removed(self):
        """It used to be counted as uncited clinical directives — the defect
        the anesthesia curriculum found."""
        out = e._quarantine_content_only(self.LEGACY)
        assert "Consult directly" not in out
        assert "NOT FROM THE EVIDENCE BASE" not in out

    def test_the_reframe_check_still_sees_a_legacy_block(self):
        assert e._check_quarantine_reframe(self.LEGACY) == []
        unreframed = self.LEGACY.replace("Cited [[PMID:9]].", "Nothing cited.")
        assert e._check_quarantine_reframe(unreframed)

    def test_a_legacy_block_is_not_re_quarantined(self):
        out, blocks = e.quarantine_unsourced_content(self.LEGACY)
        assert blocks == []
        assert out == self.LEGACY

    def test_the_browser_renderer_knows_both_shapes(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        assert "_QUARANTINE_LEGACY_RE_JS" in html
        assert "NOT CHECKED — not from any paper Curo retrieved" in html
        assert "NOT FROM THE EVIDENCE BASE" in html, (
            "the legacy pattern is gone — 7 stored answers carrying 56 blocks "
            "would silently render un-quarantined")
        # and it must be USED, not merely declared: a rename left the variable
        # defined and the stash function calling an undefined name.
        stash = html.split("function _stashUnverifiedBlocks")[1][:400]
        assert "_QUARANTINE_LEGACY_RE_JS" in stash
        assert "_QUARANTINE_BLOCK_RE_JS" in stash
