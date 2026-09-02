"""
Out-of-domain content is quarantined and reframed (`trust-surface-v1` Q2, Q8).

RB's decision, 2026-09-02: Curo MAY answer beyond its evidence base, but that
content is visually and structurally separated, and the answer then returns to
the decision Curo can support.

WHAT THE MEASUREMENT FOUND. The apixaban Review answer's second paragraph opens

    "From the wider literature (which this search did not return, and which
     should be consulted directly): …"

and then delivers, in prose indistinguishable from the cited paragraphs on
either side of it, a complete DOAC management protocol — bleeding-risk
classification, a haemostatic-measures list, a dosing interval, two patient
thresholds (CrCl <50 mL/min, age >75) and a bridging instruction. Nothing in
the rendering said which half of the answer the library stood behind.

WHY IT NORMALISES SERVER-SIDE. Q2a requires the block to survive every export
path. The one representation the PDF, the clipboard, the deck and the
narration all consume is the answer text, so the block is written INTO it, in
markdown that stays readable if a path never learns to upgrade it. The browser
styles the same block; it does not create it. These tests therefore assert on
both: the engine's text and the shipped renderer's HTML.

THE BOUNDARY IS THE REFRAME. The run starts at the label and extends forward
until a claim carries a citation — because a cited claim is, by definition,
back inside the evidence base. So Q2b's "never interleaved with cited prose"
and Q2c's "return to what the library supports" are the same event, and the
fixture's own reframe (Cochrane RR 1.15, 0.97-1.35, making non-surgical
retreatment a legitimate option for a patient at bleeding risk) is what closes
the block.

Q8 rides along here because it lives in the same renderer function: the
recommendation box printed an orphaned caveat line reading, in its entirety,
"not applicable." — the answer contains the sentence "INR testing is not
applicable.", the caveat extractor matched the trigger phrase, and the tail it
captured was the full stop.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from js_harness import run_node

import endo_ai
from endo_ai import (_check_quarantine_reframe, _detect_unattributed_claims,
                     _detect_uncited_directive_claims, _strip_quarantine_blocks,
                     quarantine_unsourced_content, validate_evidence_mapping)

ROOT       = Path(__file__).parent.parent
INDEX_HTML = ROOT / "templates" / "index.html"
FIXTURE    = ROOT / "eval" / "fixtures" / "review_apixaban_apicectomy.md"


def fixture_answer():
    """The stored answer in the shape the engine emits."""
    raw  = FIXTURE.read_text(encoding="utf-8")
    body = re.search(r"^## Body\s*\n(.*?)\n---\n\n## References",
                     raw, re.S | re.M).group(1).strip()
    return re.sub(r"\[PMID (\d+)\]", r"[[PMID:\1]]", body)


# ── the span, and where it stops ──────────────────────────

class TestTheApixabanSpanIsQuarantined:

    def test_exactly_one_block_is_lifted(self):
        _, blocks = quarantine_unsourced_content(fixture_answer())
        assert len(blocks) == 1

    def test_the_block_carries_the_whole_protocol(self):
        _, (block,) = quarantine_unsourced_content(fixture_answer())
        for directive in ("SDCEP, BSH, and ACC/AHA",
                          "tranexamic acid 4.8% mouthwash",
                          "CrCl <50 mL/min",
                          "age >75",
                          "consider omitting the morning dose",
                          "Bridging with LMWH is not indicated for apixaban.",
                          "INR testing is not applicable."):
            assert directive in block, "%r was left outside the block" % directive

    def test_it_stops_before_the_cited_reframe(self):
        """Q2b and Q2c are the same boundary: a cited claim is back inside the
        evidence base, so it ends the run."""
        _, (block,) = quarantine_unsourced_content(fixture_answer())
        assert "legitimate option" not in block
        assert "[[PMID:" not in block

    def test_no_cited_prose_is_pulled_in(self):
        _, (block,) = quarantine_unsourced_content(fixture_answer())
        assert "well-standardised and generally low-risk" not in block

    def test_the_footer_names_the_bodies_to_consult(self):
        out, _ = quarantine_unsourced_content(fixture_answer())
        assert "**Consult directly:** SDCEP · BSH · ACC/AHA" in out

    def test_the_block_is_marked_unverified_in_the_text_itself(self):
        """Not a browser decoration. A PDF, a paste and a slide all read this
        string, and each must carry the label."""
        out, _ = quarantine_unsourced_content(fixture_answer())
        assert "⚠ **NOT FROM THE EVIDENCE BASE — UNVERIFIED**" in out

    def test_no_directive_from_the_span_survives_outside_the_block(self):
        """Q2d. The strongest available statement of 'not interleaved'."""
        out, _ = quarantine_unsourced_content(fixture_answer())
        outside = _strip_quarantine_blocks(out)
        for directive in ("Bridging with LMWH is not indicated",
                          "INR testing is not applicable",
                          "consider omitting the morning dose",
                          "CrCl <50 mL/min"):
            assert directive not in outside, "%r rendered outside the block" % directive

    def test_the_cited_reframe_is_still_there(self):
        out, _ = quarantine_unsourced_content(fixture_answer())
        outside = _strip_quarantine_blocks(out)
        assert "no clear superiority of surgical over non-surgical retreatment" in outside
        assert "[[PMID:27759881]]" in outside

    def test_nothing_is_lost_in_the_rewrite(self):
        """A restructuring pass that drops a sentence would be far worse than
        the defect it fixes."""
        before = fixture_answer()
        after, _ = quarantine_unsourced_content(before)
        missing = [w for w in set(re.findall(r"[A-Za-z]{5,}", before))
                   if w not in after]
        assert missing == []

    def test_the_pass_is_idempotent(self):
        once, blocks1 = quarantine_unsourced_content(fixture_answer())
        twice, blocks2 = quarantine_unsourced_content(once)
        assert blocks2 == []
        assert twice == once


class TestAnAnswerWithNoOutOfDomainContentIsUntouched:
    """Standing rule 4's pair. A pass that always rewrites is not a detector."""

    CLEAN = ("## CLINICAL RECOMMENDATION\n\n"
             "Non-surgical retreatment is a legitimate alternative to apical "
             "surgery in a patient at bleeding risk [[PMID:27759881]].\n\n"
             "## Evidence summary\n\nPRF reduces early postoperative pain "
             "[[PMID:42652796]].\n")

    def test_no_block_is_created(self):
        out, blocks = quarantine_unsourced_content(self.CLEAN)
        assert blocks == []

    def test_the_text_is_returned_byte_for_byte(self):
        out, _ = quarantine_unsourced_content(self.CLEAN)
        assert out == self.CLEAN


class TestTheParagraphIsSplitRatherThanSwallowed:
    """Q2b: out-of-domain prose may never share a paragraph with cited prose."""

    MIXED = ("## CLINICAL RECOMMENDATION\n\n"
             "Apical surgery is low-risk for major bleeding [[PMID:27759881]]. "
             "From the wider literature: the drug should not be routinely "
             "interrupted. Give tranexamic acid 4.8% mouthwash. "
             "Non-surgical retreatment remains a legitimate option "
             "[[PMID:35762859]].\n")

    def test_the_cited_sentence_before_stays_outside(self):
        out, (block,) = quarantine_unsourced_content(self.MIXED)
        assert "low-risk for major bleeding" not in block
        assert "low-risk for major bleeding [[PMID:27759881]]." in out

    def test_the_cited_sentence_after_stays_outside(self):
        out, (block,) = quarantine_unsourced_content(self.MIXED)
        assert "legitimate option" not in block
        assert "legitimate option [[PMID:35762859]]." in out

    def test_the_middle_run_is_the_block(self):
        _, (block,) = quarantine_unsourced_content(self.MIXED)
        assert "should not be routinely interrupted" in block
        assert "tranexamic acid 4.8% mouthwash" in block


# ── how the block interacts with the other checkers ───────

class TestTheBlockAttributesWhatIsInsideIt:

    def test_the_validators_unattributed_detector_skips_the_block(self):
        """The block header IS the label. Flagging its sentences again would
        fail an answer for using the structure the prompt requires — the same
        trap `_UNSOURCED_LABEL_RE` exists to avoid, one level up."""
        out, _ = quarantine_unsourced_content(fixture_answer())
        inside = {"Standard practice is to either"}
        flagged = " ".join(f["sentence"] for f in _detect_unattributed_claims(out))
        for phrase in inside:
            assert phrase not in flagged

    def test_the_banner_still_counts_them(self):
        """Q2b: quarantined content feeds Q1's second number. It is excluded
        from what was CHECKED, never from what was NOT."""
        out, _ = quarantine_unsourced_content(fixture_answer())
        found = _detect_uncited_directive_claims(out)
        joined = " ".join(c["sentence"] for c in found)
        assert "Bridging with LMWH is not indicated for apixaban." in joined
        assert "INR testing is not applicable." in joined


class TestTheReframeIsRequired:
    """Q2c. The fixture does this well, by accident. This makes it an element."""

    def test_the_fixture_passes_the_reframe_check(self):
        out, _ = quarantine_unsourced_content(fixture_answer())
        assert _check_quarantine_reframe(out) == []

    def test_a_block_with_nothing_cited_after_it_is_a_finding(self):
        answer = ("## CLINICAL RECOMMENDATION\n\n"
                  "From the wider literature: the drug should not be routinely "
                  "interrupted. Give tranexamic acid 4.8% mouthwash.\n")
        out, blocks = quarantine_unsourced_content(answer)
        assert blocks
        issues = _check_quarantine_reframe(out)
        assert len(issues) == 1
        assert "UNREFRAMED_QUARANTINE" in issues[0]

    def test_it_fails_validation_and_the_retry_message_says_what_to_do(self):
        """The recommendation here is deliberately traceable and the evidence
        summary deliberately cited, so the ONLY thing wrong with this answer is
        that its out-of-domain block is where the reader is left."""
        answer = ("## CLINICAL RECOMMENDATION\n\n"
                  "Based on Cochrane evidence, non-surgical retreatment is a "
                  "legitimate alternative [[PMID:27759881]].\n\n"
                  "## Evidence gap\n\n"
                  "This search returned no evidence on DOACs. From the wider "
                  "literature: the drug should not be routinely interrupted. "
                  "Give tranexamic acid 4.8% mouthwash.\n")
        out, _ = quarantine_unsourced_content(answer)
        result = validate_evidence_mapping(
            out, {"level1": {"scored": [{"pmid": "27759881"}]}})
        assert not result["passed"]
        assert "UNREFRAMED_QUARANTINE" in result["failure_reason"], \
            result["failure_reason"]
        msg = endo_ai._build_corrective_message(result)
        assert "OUT-OF-DOMAIN CONTENT LEFT HANGING" in msg
        assert "Do not add a marker to the unverified content itself" in msg

    def test_a_reframed_answer_passes(self):
        answer = ("## CLINICAL RECOMMENDATION\n\n"
                  "From the wider literature: the drug should not be routinely "
                  "interrupted.\n\nNon-surgical retreatment is a legitimate "
                  "alternative here, with no clear superiority for periapical "
                  "healing at 1 year [[PMID:27759881]].\n")
        out, blocks = quarantine_unsourced_content(answer)
        assert blocks
        assert _check_quarantine_reframe(out) == []


# ── the browser, running the shipped JavaScript ───────────

def _run_node(js_body):
    return run_node(js_body)


def _render(answer):
    return _run_node("console.log(JSON.stringify([renderAnswer(%s)]));"
                     % json.dumps(answer))[0]


class TestTheBrowserBuildsTheContainer:

    def test_the_block_becomes_its_own_container(self):
        out, _ = quarantine_unsourced_content(fixture_answer())
        html = _render(out)
        assert html.count('class="unverified-block"') == 1
        assert '<div class="unverified-head">⚠ NOT FROM THE EVIDENCE BASE — UNVERIFIED</div>' in html

    def test_the_footer_survives_into_the_container(self):
        out, _ = quarantine_unsourced_content(fixture_answer())
        html = _render(out)
        m = re.search(r'<div class="unverified-foot">(.*?)</div>', html, re.S)
        assert m and "SDCEP" in m.group(1)

    def test_every_directive_lands_inside_the_container(self):
        """Not merely 'a container exists somewhere on the page'."""
        out, _ = quarantine_unsourced_content(fixture_answer())
        html = _render(out)
        body = re.search(r'<div class="unverified-body">(.*?)</div>', html, re.S).group(1)
        for directive in ("Bridging with LMWH is not indicated for apixaban.",
                          "INR testing is not applicable.",
                          "tranexamic acid 4.8% mouthwash"):
            assert directive in body

    def test_no_blockquote_scruff_is_left_on_the_page(self):
        out, _ = quarantine_unsourced_content(fixture_answer())
        html = _render(out)
        assert "&gt; ⚠" not in html
        assert "NOT FROM THE EVIDENCE BASE — UNVERIFIED**" not in html

    def test_the_container_is_not_stranded_inside_a_paragraph(self):
        out, _ = quarantine_unsourced_content(fixture_answer())
        html = _render(out)
        assert '<p><div class="unverified-block"' not in html

    def test_a_clean_answer_renders_no_container(self):
        html = _render("## Evidence summary\n\nPRF reduces pain [[PMID:42652796]].\n")
        assert "unverified-block" not in html


# ── Q8: the empty caveat field ────────────────────────────

class TestTheOrphanedCaveatLine:

    REC_WITH_TRIGGER_AT_SENTENCE_END = (
        "## CLINICAL RECOMMENDATION\n\n"
        "Proceed on the Cochrane evidence [[PMID:27759881]]. Bridging is not "
        "needed. INR testing is not applicable.\n")

    REC_WITH_A_REAL_CAVEAT = (
        "## CLINICAL RECOMMENDATION\n\n"
        "Proceed on the Cochrane evidence [[PMID:27759881]]. This does not "
        "apply when the canal is calcified beyond negotiation.\n")

    def _box(self, answer):
        return _run_node("var p = renderAnswerWithBox(%s);"
                         "console.log(JSON.stringify([p.box]));" % json.dumps(answer))[0]

    def test_an_empty_caveat_field_renders_nothing(self):
        """The trigger phrase ends the sentence, so the tail the caveat IS
        captures only the full stop. That produced a line reading, entire,
        'not applicable.'"""
        box = self._box(self.REC_WITH_TRIGGER_AT_SENTENCE_END)
        assert "rec-caveat" not in box, box

    def test_a_real_caveat_still_renders(self):
        """Standing rule 4's pair — the fix must not be 'delete the feature'."""
        box = self._box(self.REC_WITH_A_REAL_CAVEAT)
        assert "rec-caveat" in box
        assert "calcified beyond negotiation" in box
