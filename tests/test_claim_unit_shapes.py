"""
The claim unit for the four shapes a curriculum writes (guardrails-v1 Item 1).

`_extract_claim_citation_pairs` decides what text each cited PMID is judged
against. `_split_claim_units` handled prose and a bold pseudo-heading on its
own line. A Deep Learning module writes four more structures that the
sentence splitter cannot break, for the same two reasons every time — the
line does not end in `.!?`, and the next line starts with `*` or `|` rather
than [A-Z\\d]:

  decision_tree  `**IF** / **THEN** / **BECAUSE**`, repeated. A seven-branch
                 tree was ONE claim carrying seven papers' markers.
  table_row      `#### Clinical Protocol Summary` — a whole pipe table as one
                 claim, though each row cites its own paper.
  bold_label     `**KTP laser (532 nm):** Ayhan et al. ...` — a bold label at
                 the start of a line with its content on the SAME line, which
                 `_PSEUDO_HEADING_RE` (whole line bold) does not match.
  list_item      `- **Irrigant extrusion risk**: ... [[PMID:N]]` — four
                 bullets, four papers, one 1,438-character claim. The old code
                 stripped the bullet MARKER and never split on it.

13 of the 37 hand-judged Deep Learning flags are this
(`eval/logs/dl_flag_verdicts.json`) — the largest single remaining cause in
that metric.

THE DIRECTION MATTERS, and it is why `TestTheCheckerIsNotWeakened` is the
longest class here. The last change to this splitter reversed its expected
direction: merged pairs were flagged LESS (37.6% vs 50.8%, p=0.002), because
a long blob gives the judge more surface on which to find something the
abstract does support. Un-merging therefore makes the checker STRICTER. A
change that merely lowered the flag rate by giving the judge less to object
to would be the opposite of the fix, so these tests pin that a genuinely
unsupported claim still flags, and that no citation is lost on the way.

Fixtures are real: every multi-line shape below is copied from
`learn_history/20260901_005932_use_of_lasers_in_root_canal_disinfection.json`
and `..._010712_...`, the two curricula behind the 13.3% figure.
"""

import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import pytest

from endo_ai import (
    _extract_claim_citation_pairs,
    _split_claim_units,
    _split_claim_units_tagged,
    _PMID_RE,
    SHAPE_PROSE, SHAPE_DTREE, SHAPE_TABLE, SHAPE_LABEL, SHAPE_LIST,
)

CURRICULA = [
    "learn_history/20260901_005932_use_of_lasers_in_root_canal_disinfection.json",
    "learn_history/20260901_010712_use_of_lasers_in_root_canal_disinfection.json",
]


def claims_by_pmid(answer):
    return {pmid: claim for claim, pmid in _extract_claim_citation_pairs(answer)}


def shapes_by_pmid(answer):
    return {pmid: shape
            for _c, pmid, shape in _extract_claim_citation_pairs(
                answer, with_shape=True)}


# ── The decision tree ─────────────────────────────────────

DECISION_TREE = """## Module 3

### 4b. Decision Tree

**IF** the canal system has confirmed complex anatomy (isthmuses, lateral canals, severe curvature)
**THEN** select Er:YAG LAI (PIPS or SWEEPS mode) as the primary activation modality
**BECAUSE** Er:YAG LAI removed significantly more biofilm from isthmuses and lateral canals than all other activation methods tested [[PMID:38382735]]

**IF** the case is primary root canal treatment in a straightforward canal
**THEN** conventional needle irrigation with 5.25% NaOCl is the foundation
**BECAUSE** 5.25% NaOCl alone eliminates all cultivable organisms at this concentration in clinical samples [[PMID:38976717]]

**IF** patient reports severe preoperative pain or has a large periapical lesion
**THEN** consider adding LLLT to the periapical region post-procedurally
**BECAUSE** periapical lesion volume reduced significantly more with adjunctive LLLT at six months [[PMID:40818665]]
"""


class TestTheDecisionTree:

    def test_each_branch_is_its_own_claim(self):
        claims = claims_by_pmid(DECISION_TREE)
        assert set(claims) == {"38382735", "38976717", "40818665"}
        assert "Er:YAG LAI removed" in claims["38382735"]
        assert "NaOCl alone eliminates" not in claims["38382735"], (
            "the tree did not split: the biofilm paper is being judged "
            "against the NaOCl branch as well as its own")
        assert "LLLT" not in claims["38382735"]
        assert "isthmuses" not in claims["40818665"]

    def test_a_branch_keeps_its_if_and_then(self):
        """`**BECAUSE** ...` alone is a fragment. The branch is the unit
        because the justification is only a claim in the presence of the
        action it justifies."""
        claims = claims_by_pmid(DECISION_TREE)
        c = claims["38976717"]
        assert "**IF**" in c and "**THEN**" in c and "**BECAUSE**" in c

    def test_the_branch_keeps_its_line_breaks(self):
        """Collapsing three lines that mean three different things onto one
        hands the judge a run-on. Prose claims are still collapsed."""
        claims = claims_by_pmid(DECISION_TREE)
        assert "\n" in claims["38976717"]

    def test_shape_is_reported(self):
        assert shapes_by_pmid(DECISION_TREE)["38382735"] == SHAPE_DTREE

    def test_a_tree_ends_at_the_next_heading(self):
        answer = DECISION_TREE + (
            "\n#### 4c. Materials\n\n"
            "Apical size #50 taper .05 is the minimum for LAI [[PMID:99999]].\n")
        claims = claims_by_pmid(answer)
        assert "Apical size" in claims["99999"]
        assert "**IF**" not in claims["99999"]
        assert "Materials" not in claims["40818665"]


# ── The protocol table ────────────────────────────────────

PROTOCOL_TABLE = """## Module 2

#### Clinical Protocol Summary

| Step | Parameter | Evidence-Based Value |
|---|---|---|
| Irrigation solution | NaOCl concentration | 2.5% [[PMID:31301436]] |
| aPDT photosensitiser | Agent and concentration | Methylene blue 1.56 uM/mL [[PMID:41692102]] |
| LAI laser | Er:YAG pulse energy | 75-100 mJ, <50 Hz [[PMID:38382735]] |
"""


class TestTheProtocolTable:

    def test_each_row_is_its_own_claim(self):
        claims = claims_by_pmid(PROTOCOL_TABLE)
        assert set(claims) == {"31301436", "41692102", "38382735"}
        assert "Methylene blue" not in claims["31301436"]
        assert "NaOCl" not in claims["41692102"]

    def test_a_row_reads_as_a_proposition_not_as_layout(self):
        """`| a | b |` is not something a paper can support. The cells joined
        by an em dash are."""
        c = claims_by_pmid(PROTOCOL_TABLE)["31301436"]
        assert "|" not in c
        assert "Irrigation solution" in c and "2.5%" in c

    def test_the_separator_row_is_not_a_claim(self):
        for claim, _pmid in _extract_claim_citation_pairs(PROTOCOL_TABLE):
            assert set(claim.strip()) != {"-"}
            assert "---" not in claim

    def test_shape_is_reported(self):
        assert shapes_by_pmid(PROTOCOL_TABLE)["31301436"] == SHAPE_TABLE


# ── The inline bold label ─────────────────────────────────

BOLD_LABEL = """## Module 3

**Diode laser (980 nm):** Swetha et al. reported 93% success at 18 months versus 88.4% for conventional NaOCl hemostasis [[PMID:30548497]].
**KTP laser (532 nm):** Ayhan et al. found 90.5% success for MTA pulpotomy at 12 months, not statistically significant [[PMID:41470159]].
**aPDT (630-670 nm):** Requires photosensitiser pre-loading and achieves antimicrobial action via reactive oxygen species [[PMID:31301436]].
"""


class TestTheInlineBoldLabel:

    def test_each_sub_point_is_its_own_claim(self):
        claims = claims_by_pmid(BOLD_LABEL)
        assert set(claims) == {"30548497", "41470159", "31301436"}
        assert "KTP" not in claims["30548497"], (
            "three sub-points fused: the diode paper is being judged against "
            "the KTP figures as well as its own")
        assert "Swetha" not in claims["41470159"]
        assert "90.5%" not in claims["31301436"]

    def test_shape_is_reported(self):
        assert shapes_by_pmid(BOLD_LABEL)["30548497"] == SHAPE_LABEL

    def test_a_whole_line_bold_heading_still_ends_a_claim(self):
        """The pre-existing pseudo-heading rule must survive the new one."""
        answer = ("## EVIDENCE SUMMARY\n"
                  "The ESE guidelines recommended multi-visit treatment "
                  "[[PMID:111]].\n\n"
                  "**Level I — RCTs and Systematic Reviews**\n\n"
                  "The Cochrane review found no difference at four years "
                  "[[PMID:222]].\n")
        claims = claims_by_pmid(answer)
        assert "Cochrane" not in claims["111"]
        assert "ESE" not in claims["222"]
        assert "Level I" not in claims["111"] + claims["222"]


# ── The list ──────────────────────────────────────────────

BULLET_LIST = """## Module 4

**Key limitations and adverse effects** of laser disinfection include:

- **Heterogeneity of protocols**: laser type, power, tip diameter and application time vary markedly across studies [[PMID:36156804]]
- **Irrigant extrusion risk**: Er:YAG laser-assisted irrigation poses risks of irrigant extrusion beyond the apex [[PMID:40287048]]
- **No benefit in single-canal teeth**: Dogan et al. concluded advanced agitation made no significant healing difference at 12 months [[PMID:38878107]]
"""


class TestTheList:

    def test_each_item_is_its_own_claim(self):
        claims = claims_by_pmid(BULLET_LIST)
        assert set(claims) == {"36156804", "40287048", "38878107"}
        assert "extrusion" not in claims["36156804"], (
            "the bullets fused: the heterogeneity paper is being judged "
            "against the extrusion claim as well as its own")
        assert "Heterogeneity" not in claims["38878107"]

    def test_a_numbered_item_is_its_own_claim(self):
        answer = ("## Protocol\n"
                  "1. Establish patency and confirm working length "
                  "[[PMID:111]]\n"
                  "2. Irrigate with 2.5% NaOCl for 60 seconds per canal "
                  "[[PMID:222]]\n")
        claims = claims_by_pmid(answer)
        assert "NaOCl" not in claims["111"]
        assert "patency" not in claims["222"]

    def test_a_wrapped_continuation_stays_with_its_item(self):
        """A continuation line matches no boundary rule, so it belongs to the
        item it wraps from. Splitting there would strand the citation on a
        fragment — the same defect the abbreviation guard exists for."""
        answer = ("## Findings\n"
                  "- Er:YAG laser-activated irrigation removed more biofilm\n"
                  "  from isthmuses than ultrasonic activation [[PMID:111]]\n")
        claims = claims_by_pmid(answer)
        assert "Er:YAG" in claims["111"] and "isthmuses" in claims["111"]

    def test_shape_is_reported(self):
        assert shapes_by_pmid(BULLET_LIST)["36156804"] == SHAPE_LIST

    def test_a_bold_run_is_not_mistaken_for_a_bullet(self):
        """`*` opens a bullet only with a space after it; `**bold**` does
        not."""
        answer = ("## Findings\n"
                  "**Er:YAG** outperformed ultrasonic activation "
                  "[[PMID:111]].\n")
        assert "Er:YAG" in claims_by_pmid(answer)["111"]


# ── The checker must not have been weakened ───────────────

class TestTheCheckerIsNotWeakened:
    """Merged pairs were flagged LESS (37.6% vs 50.8%, p=0.002). Un-merging
    is therefore expected to make the checker stricter, and a version of this
    change that lowered the flag rate by hiding claims from the judge would be
    the opposite of the fix."""

    def test_no_citation_is_lost_or_gained_on_the_measured_curricula(self):
        """The pair count and the per-PMID multiset must be identical to the
        prose-only splitter's. Measured when the patch was written: 114 and
        124 pairs, unchanged in both arms; mean claim length 527 -> 244 and
        459 -> 243; longest claim 2,403 -> 469 characters."""
        for src in CURRICULA:
            path = pathlib.Path(src)
            if not path.exists():
                pytest.skip(f"{src} not present")
            answer = json.loads(path.read_text(encoding="utf-8"))["answer"]
            answer = "\n".join(l for l in answer.splitlines()
                               if not l.lstrip().startswith(">"))
            after = _extract_claim_citation_pairs(answer)
            before = _pairs_with_prose_only_splitter(answer)
            assert collections.Counter(p for _c, p in after) == \
                   collections.Counter(p for _c, p in before), (
                f"{path.name}: the shape-aware split changed WHICH papers are "
                f"checked, not just what each one is judged against")

    def test_every_extracted_pmid_is_really_in_the_text(self):
        for src in CURRICULA:
            path = pathlib.Path(src)
            if not path.exists():
                pytest.skip(f"{src} not present")
            answer = json.loads(path.read_text(encoding="utf-8"))["answer"]
            cited = {p for _c, p in _extract_claim_citation_pairs(answer)}
            in_body = {m.group(1) for m in _PMID_RE.finditer(answer)}
            assert cited <= in_body

    def test_a_claim_never_grows(self):
        """Every new unit is a SUBSET of the blob it came out of. A splitter
        that merged anything new would be judging a marker against text it was
        never attached to."""
        for src in CURRICULA:
            path = pathlib.Path(src)
            if not path.exists():
                pytest.skip(f"{src} not present")
            answer = json.loads(path.read_text(encoding="utf-8"))["answer"]
            longest_after = max(len(c) for c, _p in
                                _extract_claim_citation_pairs(answer))
            longest_before = max(len(c) for c, _p in
                                 _pairs_with_prose_only_splitter(answer))
            assert longest_after <= longest_before

    def test_an_unsupported_claim_inside_a_split_shape_still_flags(self):
        """THE test the item required: the fix must not weaken the checker.

        The judge is stubbed, so this asserts on what the CHECKER DOES with a
        contradicting abstract, not on Haiku's opinion. The claim sits on a
        decision-tree branch — the shape most changed by this patch — and says
        the opposite of its abstract. It must still reach the judge and still
        come back flagged.
        """
        import endo_ai

        answer = ("## Module 3\n\n"
                  "**IF** the canal is retreated and E. faecalis is suspected\n"
                  "**THEN** add aPDT with methylene blue\n"
                  "**BECAUSE** methylene blue aPDT eliminated 100% of "
                  "E. faecalis in every treated canal [[PMID:777]]\n")

        pairs = _extract_claim_citation_pairs(answer)
        assert len(pairs) == 1, "the branch must reach the judge as one pair"
        assert "100%" in pairs[0][0]

        seen = {}

        class _Stub:
            def __init__(self, *a, **kw):
                pass

        def fake_invoke(client, function_name=None, **kw):
            seen["payload"] = kw["messages"][0]["content"]

            class R:
                content = [type("T", (), {"text": json.dumps(
                    [{"i": 0, "verdict": "not_supported"}])})()]
                usage = type("U", (), {"input_tokens": 10,
                                       "output_tokens": 10,
                                       "cache_creation_input_tokens": 0,
                                       "cache_read_input_tokens": 0})()
            return R()

        import rag
        orig_bulk = rag.get_cached_abstracts_bulk
        orig_invoke = endo_ai._invoke_claude
        orig_client = endo_ai.anthropic.Anthropic
        orig_key = endo_ai._get_api_key
        rag.get_cached_abstracts_bulk = lambda pmids: {
            "777": {"abstract": "Methylene blue aPDT achieved a mean 62% "
                                "reduction in E. faecalis CFU counts; no "
                                "canal was rendered culture-negative."}}
        endo_ai._invoke_claude = fake_invoke
        endo_ai.anthropic.Anthropic = _Stub
        endo_ai._get_api_key = lambda: "test"
        try:
            out = endo_ai.verify_citation_support(answer, {})
        finally:
            rag.get_cached_abstracts_bulk = orig_bulk
            endo_ai._invoke_claude = orig_invoke
            endo_ai.anthropic.Anthropic = orig_client
            endo_ai._get_api_key = orig_key

        assert out["checked"] == 1
        assert len(out["flags"]) == 1, "a contradicted claim did not flag"
        assert out["flags"][0]["pmid"] == "777"
        assert out["flags"][0]["shape"] == SHAPE_DTREE
        assert out["by_shape"][SHAPE_DTREE] == {"checked": 1, "flagged": 1}
        # And the judge saw the branch, not a fragment of it.
        assert "**THEN**" in seen["payload"]
        assert "culture-negative" in seen["payload"], \
            "the judge was not shown the whole abstract"


def _pairs_with_prose_only_splitter(answer):
    """What the shipped extractor returned before this patch.

    Re-composed from `_split_claim_units` — which is still the validator's
    splitter and so is still real code — rather than from a frozen copy of the
    old function, so this comparison cannot drift into testing a fossil.
    """
    import re
    from endo_ai import _split_sections, _is_exempt_section
    pairs = []
    for title, body in _split_sections(answer or ""):
        if _is_exempt_section(title):
            continue
        for sent in _split_claim_units(body):
            s = sent.strip()
            if len(s) < 20:
                continue
            pmids = [m.group(1) for m in _PMID_RE.finditer(s)]
            if not pmids:
                continue
            claim = re.sub(r"\s{2,}", " ", _PMID_RE.sub("", s).strip())
            for pid in pmids:
                pairs.append((claim, pid))
    return pairs


class TestTheValidatorsUnitIsUnchanged:
    """`_detect_unattributed_claims` still uses the prose-only splitter, on
    purpose. It feeds `validate_evidence_mapping`, which REJECTS an answer and
    buys a full Opus regeneration — and the retry rate is what the next item
    in this batch measures. Two changes to one number in one batch is the
    confound this item was split out to avoid.

    This test pins the scoping so that widening it later is a deliberate act
    with its own measurement, not a quiet side effect of touching the file.
    """

    def test_a_table_row_is_not_a_unit_for_the_validator(self):
        body = ("| Irrigant | 2.5% NaOCl for 60 seconds |\n"
                "| Chelator | 17% EDTA for 60 seconds |\n")
        units = _split_claim_units(body)
        assert any("EDTA" in u and "NaOCl" in u for u in units), (
            "the validator's splitter now sees table rows — that changes "
            "which answers are REJECTED, and needs its own measurement")

    def test_the_checkers_splitter_does_see_them(self):
        body = ("| Irrigant | 2.5% NaOCl for 60 seconds |\n"
                "| Chelator | 17% EDTA for 60 seconds |\n")
        shapes = [s for s, _t in _split_claim_units_tagged(body)]
        assert shapes.count(SHAPE_TABLE) == 2


class TestOrdinaryProseIsUntouched:
    """The shapes above are additions. Everything the splitter already did
    correctly must be byte-identical, or the before/after measurement is
    comparing two changes."""

    def test_two_real_sentences_still_split(self):
        answer = ("## Findings\nMTA outperformed CaOH [[PMID:111]]. "
                  "Biodentine was equivalent to MTA [[PMID:222]].\n")
        claims = claims_by_pmid(answer)
        assert "Biodentine" not in claims["111"]
        assert "MTA outperformed" not in claims["222"]

    def test_an_abbreviation_does_not_end_a_claim(self):
        answer = ("## Findings\n"
                  "Er:YAG vs. SWEEPS showed no difference at 12 months "
                  "[[PMID:333]].\n"
                  "Dagher et al. 2019 found no difference between PIPS and "
                  "needle irrigation [[PMID:444]].\n")
        claims = claims_by_pmid(answer)
        assert "Er:YAG vs. SWEEPS" in claims["333"]
        assert claims["444"].startswith("Dagher et al. 2019")

    def test_prose_claims_are_identical_to_the_old_splitter(self):
        """On a plain Review answer with none of the four shapes in it, the
        two splitters must agree exactly."""
        answer = ("## EVIDENCE SUMMARY\n"
                  "The Cochrane review found no difference in healing at four "
                  "years [[PMID:111]]. A later cohort reported 92% survival at "
                  "five years [[PMID:222]].\n")
        assert _extract_claim_citation_pairs(answer) == \
               _pairs_with_prose_only_splitter(answer)

    def test_shape_is_prose_for_a_plain_sentence(self):
        answer = ("## Findings\nThe Cochrane review found no difference "
                  "[[PMID:111]].\n")
        assert shapes_by_pmid(answer)["111"] == SHAPE_PROSE


class TestTheDefaultArityIsUnchanged:
    """`verify_citation_support` and four test files unpack 2-tuples."""

    def test_two_tuples_by_default(self):
        answer = "## F\nA finding [[PMID:111]].\n"
        assert all(len(p) == 2 for p in _extract_claim_citation_pairs(answer))

    def test_three_tuples_on_request(self):
        answer = "## F\nA finding [[PMID:111]].\n"
        got = _extract_claim_citation_pairs(answer, with_shape=True)
        assert all(len(p) == 3 for p in got)
