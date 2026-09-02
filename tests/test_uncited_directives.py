"""
The second number on the trust banner (`trust-surface-v1` Q1).

WHAT THE MEASUREMENT FOUND. `eval/fixtures/review_apixaban_apicectomy.md` — a
real Review answer, captured verbatim — rendered this banner:

    LITERATURE REVIEW ✓  EVIDENCE MAPPING: PASSED ✓
    CHECKED AGAINST ABSTRACTS: 9/9 CONSISTENT

directly above a paragraph of drug directives that carried no citation at all:

    "…scheduling the procedure early in the day and >=4 hours after the
     morning dose"          "tranexamic acid 4.8% mouthwash"
    "CrCl <50 mL/min"       "age >75"
    "consider omitting the morning dose on the day of surgery"
    "Bridging with LMWH is not indicated for apixaban."
    "INR testing is not applicable."

Both halves of that banner are true. `verify_citation_support` examines CITED
claims, so an uncited claim is not a claim it disagreed with — it is a claim it
never saw. Presented alone, the count then asserts verification over the whole
answer. This is a fail-open gate on the most trust-critical surface in the
product.

WHY THE EXISTING GATE DID NOT CATCH IT. Measured, before any change:

    _detect_unattributed_claims on the fixture            3 flagged
    _EVMAP_MAX_UNATTRIBUTED (hard-fails ABOVE this)       3

It passed by one claim. And two of the directives were invisible to it in any
case — "Bridging with LMWH is not indicated for apixaban" matches none of the
`_CLAIM_PATTERNS`, because those patterns catch a claim by its NUMBERS and a
prescribing instruction need not contain a statistic.

WHAT THIS FILE PINS, in both directions, because a gate that cannot fail is
not a gate (standing rule 4):

  * the apixaban fixture must never produce an unqualified pass;
  * a fully-cited answer must still produce the clean tick.

Plus the property that makes Q1a's "runs on the RENDERED answer" real: the
count must be identical whether it is computed on the engine's `[[PMID:N]]`
text or on the single-bracket form the browser and the copy path emit.
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
from endo_ai import (_append_support_warnings, _detect_uncited_directive_claims,
                     _split_claim_units, _split_sections, _is_exempt_section)

ROOT       = Path(__file__).parent.parent
INDEX_HTML = ROOT / "templates" / "index.html"
FIXTURE    = ROOT / "eval" / "fixtures" / "review_apixaban_apicectomy.md"


def _fixture_body(rendered=False):
    raw  = FIXTURE.read_text(encoding="utf-8")
    body = re.search(r"^## Body\s*\n(.*?)\n---\n\n## References",
                     raw, re.S | re.M).group(1).strip()
    return body if rendered else re.sub(r"\[PMID (\d+)\]", r"[[PMID:\1]]", body)


# ── THE COUNT ON THIS FIXTURE MOVED 6 -> 5, AND WHY ───────
#
# A3b's adjudication sharpened `_claim_is_directive`: a sentence that DESCRIBES
# the evidence base, and asks the clinician to do nothing, is no longer counted
# as a clinical directive.
#
# On this fixture that removes exactly one claim:
#
#   "Two included trials compared surgical root-end resection with non-surgical
#    retreatment and found no clear superiority for periapical healing at 1 year
#    (RR 1.15, 95% CI 0.97-1.35)…"
#
# It fired on the `quantity` shape because of "at 1 year". It is an uncited
# claim — `_detect_unattributed_claims` still flags it, and should — but it is
# not a DIRECTIVE, and Q1a's remit is directives. The Stage 1 report already
# named it "the one finding of a different character" in this set.
#
# The five that remain are all instructions: two drug directives, a
# haemostatic-measures protocol with doses and thresholds, and two management
# statements. Recorded rather than silently re-baselined (standing rule §1.13).
UNCITED_ON_THE_FIXTURE = 5

# A Review answer in the same shape where every directive is cited. This is the
# other direction: if the detector cannot produce zero, the banner's second
# half is decoration and the first half is worthless.
FULLY_CITED = """## CLINICAL RECOMMENDATION

Non-surgical retreatment is a legitimate alternative to apical surgery in a
patient at bleeding risk, with no clear superiority for periapical healing at
1 year [[PMID:27759881]]. Bone grafting improves apical surgery healing
outcomes and should be considered where the osteotomy is large
[[PMID:38491954]].

## Evidence summary

PRF-based adjuncts reduce early postoperative pain and may accelerate early
bone healing [[PMID:42652796]].
"""


# ── the detector ──────────────────────────────────────────

class TestTheDirectivesTheOldGateCouldNotSee:

    @pytest.mark.parametrize("sentence", [
        "Bridging with LMWH is not indicated for apixaban.",
        "INR testing is not applicable for this patient group.",
        "Omit the morning dose on the day of surgery.",
        "Tranexamic acid 4.8% mouthwash should be used as a local measure.",
        "Schedule the procedure at least 4 hours after the morning dose.",
    ])
    def test_an_uncited_drug_directive_is_counted(self, sentence):
        found = _detect_uncited_directive_claims("## CLINICAL RECOMMENDATION\n\n" + sentence)
        assert len(found) == 1, "%r was not counted" % sentence

    @pytest.mark.parametrize("sentence", [
        "Bridging with LMWH is not indicated for apixaban [[PMID:27759881]].",
        "Omit the morning dose on the day of surgery [PMID: 27759881].",
        "Omit the morning dose on the day of surgery [PMID 27759881].",
    ])
    def test_the_same_directive_carrying_a_citation_is_not_counted(self, sentence):
        """All three attribution shapes: the engine's marker, the reference-list
        key, and the form the browser's copy path writes."""
        assert _detect_uncited_directive_claims(
            "## CLINICAL RECOMMENDATION\n\n" + sentence) == []

    def test_a_statement_about_the_evidence_base_is_not_a_directive(self):
        """Naming a drug is not directing anyone to do anything. If a coverage
        disclaimer counted, the number would be inflated by exactly the
        sentences that are being honest about the gap."""
        s = ("The retrieved endodontic evidence base does not directly address "
             "perioperative management of apixaban in patients undergoing "
             "apical surgery.")
        assert _detect_uncited_directive_claims("## CLINICAL RECOMMENDATION\n\n" + s) == []

    def test_the_unsourced_label_does_not_exempt_a_claim_here(self):
        """Deliberately unlike `_detect_unattributed_claims`, and the difference
        is the point of the item. There the label is an escape hatch and must
        count, or the honest answer fails identically to the silent one. Here
        the label is the thing being counted: a labelled directive is still a
        directive nothing checked."""
        s = ("From the wider literature, not from the retrieved evidence base: "
             "the drug should not be routinely interrupted.")
        assert len(_detect_uncited_directive_claims("## CLINICAL RECOMMENDATION\n\n" + s)) == 1

    def test_reference_and_other_exempt_sections_are_skipped(self):
        answer = ("## References\n\n1. Del Fabbro M et al. — 20 RCTs, 120 months "
                  "follow-up. Consider this the highest tier retrieved.\n")
        assert _detect_uncited_directive_claims(answer) == []


class TestTheCountDescribesThePageNotAnIntermediate:
    """Q1a: the detector runs on the RENDERED answer. Which means the number
    must not change when the marker form does."""

    def test_the_fixture_gives_the_same_count_in_both_marker_forms(self):
        model    = _detect_uncited_directive_claims(_fixture_body(rendered=False))
        rendered = _detect_uncited_directive_claims(_fixture_body(rendered=True))
        assert len(model) == len(rendered) == UNCITED_ON_THE_FIXTURE
        assert [c["sentence"] for c in model] == [c["sentence"] for c in rendered]


class TestTheApixabanFixture:

    def test_it_reports_the_six_uncited_directives(self):
        found = _detect_uncited_directive_claims(_fixture_body())
        assert len(found) == UNCITED_ON_THE_FIXTURE
        joined = " ".join(c["sentence"] for c in found)
        for directive in ("LMWH is not indicated", "INR testing is not applicable",
                          "Standard practice is to either"):
            assert directive in joined

    def test_the_directives_the_old_gate_missed_are_among_them(self):
        """`_detect_unattributed_claims` flags 3 on this fixture and the
        validator's limit is 3, so it passed — and these two were not even
        among the 3."""
        old = {f["sentence"] for f in endo_ai._detect_unattributed_claims(_fixture_body())}
        new = {c["sentence"] for c in _detect_uncited_directive_claims(_fixture_body())}
        for missed in ("Bridging with LMWH is not indicated for apixaban.",
                       "INR testing is not applicable."):
            assert missed not in old
            assert missed in new


class TestASentenceAboutTheEvidenceIsNotADirective:
    """A3b's sharpening, built on the hand-adjudicated sample.

    40 flagged claims (25 DL, 15 Review, seed 20260902) came out 62.5% TRUE
    DIRECTIVE / 30% NARRATIVE / 7.5% CITED ELSEWHERE, and the over-reach was
    not spread evenly:

        deontic     n=13   TRUE  4   NARRATIVE  9   (69%)
        quantity    n=21   TRUE 15   NARRATIVE  3   (14%)
        imperative  n=6    TRUE  6   NARRATIVE  0   ( 0%)

    Every string below is verbatim from that sample. This is accuracy, not
    leniency (standing rule §1.6): the paired class beneath it asserts that all
    25 TRUE directives still flag, and they do — 100% recall, precision 62.5%
    -> 92.6%.
    """

    @pytest.mark.parametrize("sentence", [
        # the modal governs an interpretation, not an action
        "The GRADE rating of low quality means this finding carries substantial "
        "uncertainty and should not be interpreted as mandating a switch from lidocaine.",
        "Clinicians must therefore distinguish the application context: LAI as an "
        "irrigant activator versus adjunctive LLLT post-surgery.",
        "Because higher-tier evidence does not directly address this, the "
        "recommendation should be framed as a considered alternative.",
        "This case report represents Level IV evidence and should be treated as "
        "expert-level anatomical awareness rather than evidence-graded guidance.",
        "Lip numbness is necessary but not sufficient for pulpal anesthesia in SIP.",
        "Larger, adequately powered RCTs are required before laser disinfection "
        "can displace conventional irrigation as standard of care.",
        # the sentence describes the evidence base
        "Both sources converge: laser-activated irrigation does not statistically "
        "outperform conventional methods for periapical healing at 12 months.",
        "Longer-term (>=24-month) CBCT-based RCTs in molars are the key evidence gap.",
        "Across Cochrane-tier guidelines, >=8 systematic reviews/meta-analyses and "
        "prospective RCTs, evidence is remarkably concordant.",
    ])
    def test_a_claim_about_the_evidence_is_not_counted(self, sentence):
        assert _detect_uncited_directive_claims(
            "## Evidence summary\n\n" + sentence) == [], sentence

    @pytest.mark.parametrize("sentence", [
        # …but naming the evidence gap and THEN instructing is still a directive.
        # The first cut of this veto threw all four of these away.
        "The evidence base does not specify a tolerance value for working length "
        "in the included studies; apply standard clinical practice (+/-0.5 mm of "
        "the radiographic apex).",
        "Delivery method was not specified in either study — use a side-vented "
        "needle and deliver to working length -1 mm per standard practice.",
        "Deposit 1.8 mL of 2% lidocaine with 1:100,000 epinephrine; the evidence "
        "base for this module does not specify an injection rate in seconds.",
        "Apply a final 2 mL EDTA flush followed by 3 mL NaOCl flush — specific "
        "volumes are not drawn from the laser-specific evidence here.",
    ])
    def test_an_evidence_disclaimer_does_not_excuse_the_instruction_after_it(self, sentence):
        """The veto applies only when the sentence asks the clinician to do
        nothing. A sentence can be about the evidence AND instruct."""
        assert len(_detect_uncited_directive_claims(
            "## CLINICAL RECOMMENDATION\n\n" + sentence)) == 1, sentence

    def test_an_imperative_is_never_vetoed(self):
        """0 of 6 imperatives in the sample were narrative. An imperative verb
        opening the sentence is always an instruction, whatever else it says."""
        s = ("Confirm fluence = 71.4 J/cm2 before insertion, though the included "
             "systematic reviews and RCTs do not report this parameter.")
        assert len(_detect_uncited_directive_claims(
            "## CLINICAL RECOMMENDATION\n\n" + s)) == 1


class TestACachedAnswerGetsTheSecondNumberToo:
    """Found in the running app, not by a test.

    Asking the apixaban question through the restarted server returned it from
    cache. `finalise_answer_text` stripped its impact factors and quarantined
    its out-of-domain paragraph — and the banner then read

        ✓ CHECKED AGAINST ABSTRACTS: 9/9 CONSISTENT

    a clean tick, over the five uncited directives the quarantine block had
    just been built around. Every answer in the cache carries a support block
    written before Q1 existed, and the cache path does not regenerate it.

    That is exactly the defect Q1 exists to fix, surviving on the one path that
    never re-runs the checker.
    """

    CACHED = (
        "## CLINICAL RECOMMENDATION\n\n"
        "Apical surgery is low-risk for major bleeding [[PMID:27759881]].\n\n"
        "From the wider literature: bridging with LMWH is not indicated for "
        "apixaban. INR testing is not applicable.\n\n"
        "Non-surgical retreatment remains an option [[PMID:35762859]].\n\n"
        "---\n\n"
        "> ✓ **Citation support: verified.** Each of the 2 cited claims was "
        "checked against its source abstract.")

    def test_the_second_half_is_added_to_a_pre_q1_block(self):
        out = endo_ai.ensure_uncited_half(self.CACHED)
        assert "not from the evidence base" in out
        assert "Citation support: verified" in out

    def test_it_runs_on_the_path_a_cached_answer_takes(self):
        """Standing rule 14 — `finalise_answer_text` is what the cache-hit path
        calls, so that is where this must be wired."""
        out, _ = endo_ai.finalise_answer_text(self.CACHED)
        assert re.search(r"\d+ claims? not from the evidence base", out)

    def test_it_counts_the_quarantined_content_it_just_created(self):
        """Ordering: quarantine first, then count. Counting first would miss
        the block's own contents, which is the whole of Q2b."""
        out, blocks = endo_ai.finalise_answer_text(self.CACHED)
        assert blocks, "the fixture should produce a quarantine block"
        n = int(re.search(r"(\d+) claims? not from the evidence base", out).group(1))
        assert n >= 2, "the quarantined directives were not counted"

    def test_the_status_block_is_never_swallowed_by_a_quarantine_block(self):
        """Why quarantining must run FIRST, stated as its consequence.

        The half this adds quotes the flagged claims verbatim, and those quotes
        carry the very "from the wider literature" vocabulary the quarantiner
        looks for. Counting first therefore lets the quarantiner wrap the status
        block itself, and the answer renders

            >
            > > ✓ **Citation support: verified.** …

        with the trust banner nested inside the unverified block it is
        reporting on. A mutation that swapped the order produced exactly that
        and every other assertion here still passed."""
        out, _ = endo_ai.finalise_answer_text(self.CACHED)
        i = out.index("Citation support:")
        assert "> >" not in out[max(0, i - 20):i], \
            "the status block is nested inside a quarantine block: %r" % out[i - 20:i + 40]
        assert "NOT FROM THE EVIDENCE BASE" not in out[i:], \
            "a quarantine block was opened inside the status block"

    def test_it_is_idempotent(self):
        once, _ = endo_ai.finalise_answer_text(self.CACHED)
        twice = endo_ai.ensure_uncited_half(once)
        assert twice == once
        assert once.count("not from the evidence base") == 1

    def test_a_clean_cached_answer_gains_nothing(self):
        clean = ("## X\n\nA cited claim [[PMID:1]].\n\n---\n\n"
                 "> ✓ **Citation support: verified.** Each of the 1 cited "
                 "claims was checked against its source abstract.")
        assert endo_ai.ensure_uncited_half(clean) == clean

    def test_an_answer_with_no_support_block_is_left_alone(self):
        """Nothing to attach to. Inventing a block would assert a check that
        never ran."""
        s = "## CLINICAL RECOMMENDATION\n\nOmit the morning dose on the day of surgery.\n"
        assert endo_ai.ensure_uncited_half(s) == s


class TestTheCountPointsAtTheText:
    """A3c. "A number alone is a nag; a number that points at text is a tool."

    The status block already quotes the flagged claims verbatim as `> - "…"`
    lines, so the renderer has the list without a new server field. Each is
    located in the rendered answer and marked, and the banner's second half
    scrolls to the first one.
    """

    def _rendered(self, answer):
        return run_node(
            "var q = _uncitedClaimQuotes(A);"
            "console.log(JSON.stringify([markUncitedClaims(renderAnswer(A), q), q]));",
            preamble="var A = %s;\n" % json.dumps(answer))

    def test_the_quoted_claims_are_read_off_the_status_block(self):
        answer = _append_support_warnings(_fixture_body(), dict(VERIFIED))
        _, quotes = self._rendered(answer)
        assert len(quotes) == 5
        assert any("Bridging with LMWH is not indicated" in q for q in quotes)

    def test_each_flagged_claim_is_marked_in_the_answer(self):
        answer = _append_support_warnings(_fixture_body(), dict(VERIFIED))
        html, quotes = self._rendered(answer)
        assert html.count('class="uncited-claim"') >= 4, (
            "only %d of %d flagged claims could be located in the rendered answer"
            % (html.count('class="uncited-claim"'), len(quotes)))
        assert 'id="uncited-0"' in html

    def test_the_mark_lands_on_the_claim_it_is_counting(self):
        """Not merely that something is marked. A mutation that made the probe
        match any word still produced marks, and every other assertion here
        passed — a highlighter pointing at the wrong sentence is worse than
        none, because it tells the reader a cited claim is unsourced."""
        answer = _append_support_warnings(_fixture_body(), dict(VERIFIED))
        html, _ = self._rendered(answer)
        marked = re.findall(r'<mark class="uncited-claim"[^>]*>(.*?)</mark>',
                            html, re.S)
        assert marked, "nothing was marked"
        joined = " ".join(marked)
        assert "Bridging with LMWH is not indicated" in joined, \
            "the marks do not cover the claims: %r" % marked[:2]
        # and nothing marked may carry a citation — that is the whole point
        for m in marked:
            assert "claim-cite" not in m, \
                "a CITED claim was marked as unsourced: %r" % m[:120]

    def test_a_clean_answer_marks_nothing(self):
        """Standing rule 4's pair — a highlighter that always highlights is
        worse than none."""
        answer = _append_support_warnings(FULLY_CITED, dict(VERIFIED))
        html, quotes = self._rendered(answer)
        assert quotes == []
        assert "uncited-claim" not in html

    def test_a_claim_containing_regex_metacharacters_does_not_throw(self):
        """Real claims contain parentheses, asterisks and question marks —
        `(a) proceed…`, `CrCl <50 mL/min`. An unescaped probe would either
        throw or mark the wrong span."""
        answer = _append_support_warnings(_fixture_body(), dict(VERIFIED))
        html, _ = self._rendered(answer)
        assert "uncited-claim" in html          # it got that far without throwing

    def test_the_banner_half_is_a_control_that_reaches_them(self):
        src = INDEX_HTML.read_text(encoding="utf-8")
        m = re.search(r'atag-uncited"[^>]*onclick="([^"]+)"', src)
        assert m, "the count is not clickable"
        assert "jumpToUncited" in m.group(1)
        assert ".uncited-claim" in src.split("function jumpToUncited")[1][:400]


class TestTheDetectorIsNotVacuousInEitherDirection:
    """Standing rule 4. A detector that fires on nothing reports a clean page
    over unchecked text; one that fires on everything makes the number
    meaningless and the banner ignorable. Both are failures."""

    def test_a_fully_cited_answer_produces_zero(self):
        assert _detect_uncited_directive_claims(FULLY_CITED) == []

    def test_it_fires_on_a_small_minority_of_claim_units(self):
        """Measured across the 22 stored Deep Learning curricula: 197 of 2,883
        claim units, 6.8%. Pinned loosely — this asserts the shape of the
        number, not the number."""
        body  = _fixture_body()
        units = [s for t, b in _split_sections(body) if not _is_exempt_section(t)
                 for s in _split_claim_units(b) if len(s.strip()) >= 20]
        rate  = len(_detect_uncited_directive_claims(body)) / float(len(units))
        assert 0 < rate < 0.35, "fire rate %.2f — the number stopped meaning anything" % rate


# ── the status block the banner is built from ─────────────

VERIFIED = {"flags": [], "checked": 10, "total_pairs": 10, "cost": 0.0,
            "status": "verified", "detail": ""}


class TestTheStatusBlockCarriesBothNumbers:

    def test_the_block_states_the_uncited_count(self):
        out = _append_support_warnings(_fixture_body(), dict(VERIFIED))
        assert "5 claims not from the evidence base" in out
        assert "Each of the 10 cited claims" in out

    def test_it_lists_the_claims_rather_than_only_counting_them(self):
        """Standing rule 5: a component that leaves content unchecked must say
        WHAT it left unchecked.

        Asserted on the APPENDED BLOCK, not on the whole output. The first
        version of this test looked for the directive anywhere in `out` and a
        mutation that listed nothing survived it — the sentence was still
        there, in the answer the block is attached to."""
        body  = _fixture_body()
        block = _append_support_warnings(body, dict(VERIFIED))[len(body):]
        assert "Bridging with LMWH is not indicated for apixaban." in block
        assert block.count('> - "') == 5, "the block must quote all five"

    def test_a_fully_cited_answer_adds_no_second_half(self):
        out = _append_support_warnings(FULLY_CITED, dict(VERIFIED))
        assert "not from the evidence base" not in out
        assert "Citation support: verified" in out

    def test_the_count_is_written_back_so_a_restated_block_matches(self):
        """`_ensure_curriculum_support_blocks` rebuilds a module's block from
        the stored result and compares it against the stitched text. A count
        recomputed from an empty string would differ and the restatement would
        fire on every module."""
        support = dict(VERIFIED)
        _append_support_warnings(_fixture_body(), support)
        assert support["uncited_directive"] == UNCITED_ON_THE_FIXTURE
        assert endo_ai._support_status_block(support).count(
            "5 claims not from the evidence base") == 1

    def test_the_second_half_rides_along_on_every_outcome(self):
        for support in (dict(VERIFIED),
                        {"flags": [{"pmid": "27759881", "claim": "x" * 30,
                                    "verdict": "unsupported"}],
                         "checked": 10, "status": "verified"},
                        {"flags": [], "checked": 0, "status": "not_run",
                         "detail": "check unavailable"}):
            out = _append_support_warnings(_fixture_body(), support)
            assert "5 claims not from the evidence base" in out, support.get("status")


# ── the banner, running the shipped JavaScript ────────────

def _extract_js(names):
    src = INDEX_HTML.read_text(encoding="utf-8").split("\n")
    out = []
    for name in names:
        start, is_fn = None, False
        for i, line in enumerate(src):
            if line.startswith("function %s(" % name):
                start, is_fn = i, True
                break
            if line.startswith("var %s " % name) or line.startswith("var %s=" % name):
                start, is_fn = i, False
                break
        assert start is not None, "%s not found as a top-level declaration" % name
        j = start
        while j < len(src):
            if is_fn and j > start and src[j] == "}":
                break
            if not is_fn and src[j].rstrip().endswith(";"):
                break
            j += 1
        assert j < len(src), "could not find the end of %s" % name
        out.append("\n".join(src[start:j + 1]))
    return "\n\n".join(out)


def _chips(answer, mode="review"):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available - cannot exercise the shipped JS")
    prog = ("var mode=%s;\n" % json.dumps(mode) +
            _extract_js(["CHIPS_CHECKING", "buildTrustChips",
                         "_SUPPORT_BLOCKQUOTE_RE", "_stripSupportBlockquote"]) +
            "\nconsole.log(JSON.stringify([buildTrustChips({status:'complete',"
            "checks_status:'complete',answer:%s}), "
            "_stripSupportBlockquote(%s, false)]));"
            % (json.dumps(answer), json.dumps(answer)))
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(prog)
        path = f.name
    try:
        r = subprocess.run([node, path], capture_output=True, text=True,
                           encoding="utf-8", timeout=30)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout.strip().splitlines()[-1])
    finally:
        os.unlink(path)


PASS_MARKERS = ("atag-ok", "✓ Checked against abstracts")


def _support_chip(chips):
    """`buildTrustChips` returns the evidence-mapping chip followed by the
    citation-support one. Only the second is what Q1 governs — the first makes
    the narrower claim that every inline PMID resolved, which it did."""
    parts = re.findall(r'<span class="atag [^>]*>.*?</span>(?=<span class="atag |$)',
                       chips, re.S)
    assert parts, chips
    return parts[-1]


class TestTheBannerNeverShowsAnUnqualifiedPass:

    def test_the_apixaban_answer_does_not_render_a_clean_tick(self):
        """The single most important assertion in this file."""
        answer = _append_support_warnings(_fixture_body(), dict(VERIFIED))
        chip = _support_chip(_chips(answer)[0])
        for marker in PASS_MARKERS:
            assert marker not in chip, (
                "the banner still reads as a pass over unchecked directives: %s" % chip)

    def test_it_reports_both_numbers_in_the_required_form(self):
        answer = _append_support_warnings(_fixture_body(), dict(VERIFIED))
        chips, _ = _chips(answer)
        assert "10/10 consistent" in chips
        assert "5 claims not from the evidence base" in chips
        assert "atag-warn" in chips

    def test_the_second_half_is_styled_as_a_warning_not_a_tick(self):
        answer = _append_support_warnings(_fixture_body(), dict(VERIFIED))
        chips, _ = _chips(answer)
        m = re.search(r'<span class="atag-uncited"[^>]*>([^<]*)</span>', chips)
        assert m, "the second half carries no warning styling: %s" % chips
        assert "5 claims not from the evidence base" in m.group(1)

    def test_a_fully_cited_answer_still_shows_the_clean_tick(self):
        """Standing rule 4's pair. Without this the item could be 'passed' by
        making the banner warn unconditionally."""
        answer = _append_support_warnings(FULLY_CITED, dict(VERIFIED))
        chip = _support_chip(_chips(answer)[0])
        assert "atag-ok" in chip
        assert "✓ Checked against abstracts: 10/10 consistent" in chip
        assert "not from the evidence base" not in chip

    def test_a_curriculum_sums_the_uncited_count_across_modules(self):
        """One block per module. Reporting module 1's count as the document's
        is the same fail-open shape from a third angle."""
        answer = ("mod1" + _append_support_warnings("", {
                      "flags": [], "checked": 4, "status": "verified",
                      "uncited_directive": 2,
                      "uncited_directive_claims": [{"sentence": "Give 2 mL of x."}]}) +
                  "\n\nmod2" + _append_support_warnings("", {
                      "flags": [], "checked": 6, "status": "verified",
                      "uncited_directive": 3,
                      "uncited_directive_claims": [{"sentence": "Avoid y in z."}]}))
        chips, _ = _chips(answer, mode="learn")
        assert "5 claims not from the evidence base" in chips

    def test_the_whole_block_still_moves_out_of_the_body_into_the_chip(self):
        """The added lines must stay inside the blockquote the renderer lifts,
        or the answer shows the same warning twice."""
        answer = _append_support_warnings(_fixture_body(), dict(VERIFIED))
        _, body = _chips(answer)
        assert "not from the evidence base" not in body
        assert "Citation support: verified" not in body
        assert "Bridging with LMWH" in body, "the answer text itself was eaten"
