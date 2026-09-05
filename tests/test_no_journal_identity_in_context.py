"""A49/A4 — no journal-identity signal reaches the synthesiser.

Invariant 22 says nothing ranks by journal identity, and nothing did.
`USE_IMPACT_FACTOR` is off, scoring never reads the field, there is no
`ORDER BY` on it and no sort key — all of that is asserted elsewhere and was
re-confirmed by the A49 phase 0 audit.

The leak was one step later. `_build_evidence_context` appended `IF={value}`
to the "Top paper per tier" block, and that block is sent to Claude on ALL
FOUR answer paths — ask_clinical_question, ask_learn_question,
write_curriculum_module, ask_case_question. 1,572 of 3,208 library rows carry
a stored impact factor, so on roughly half the evidence the model was handed
the journal's prestige and asked to weigh the papers.

Keeping the letter of the invariant while handing the signal to the model is
the same influence one step later, and it is worse than ranking by it openly,
because it does not appear in any score, any breakdown or any test of the
ranker.

WHAT THIS FILE PINS
  1. the value never appears in the assembled context, whatever its magnitude
  2. it is absent from the per-tier block SPECIFICALLY, which is where it was
  3. no substitute signal replaces it — not a band, not a tag, not a label
  4. the four answer paths all build their context through this one function,
     so pinning the function is pinning the paths (rule 14)

`format_paper_context_line` was cleaned earlier (trust-surface-v1 Q3,
invariant 11) and is re-pinned here so the two halves cannot drift.
"""

import re
from pathlib import Path

import pytest

import endo_ai as E

ROOT = Path(__file__).parent.parent

# Deliberately distinctive so a match cannot be a coincidence of some other
# number in the block.
IF_VALUE = 37.771


def _paper(pmid, tier, score, **kw):
    p = {
        "pmid": pmid, "score": score, "year": 2024, "citations": 12,
        "journal": "Cochrane Database Syst Rev", "impact_factor": IF_VALUE,
        "sample_size": 88, "followup_months": 24, "authors": "Someone A",
        "tier_key": tier, "tier_label": E.TIER_LABEL.get(tier, tier),
    }
    p.update(kw)
    return p


@pytest.fixture
def evidence():
    papers = [
        _paper("111", "cochrane", 73.3),
        _paper("222", "level1", 80.9),
        _paper("333", "level5", 21.0),
    ]
    return {
        "cochrane": {"text": "PMID: 111 | ...", "ids": ["111"],
                     "scored": [papers[0]]},
        "level1": {"text": "PMID: 222 | ...", "ids": ["222"],
                   "scored": [papers[1]]},
        "level5": {"text": "PMID: 333 | ...", "ids": ["333"],
                   "scored": [papers[2]]},
        "_summary": {
            "total_scored": 3, "avg_score": 58.4,
            "all_scored": papers,
            "synthesis_order": papers,
        },
    }


class TestTheValueNeverReachesClaude:

    def test_the_number_is_absent(self, evidence):
        ctx = E._build_evidence_context(evidence)
        assert "37.771" not in ctx, (
            "the stored impact factor reached the context sent to Claude")

    def test_the_label_is_absent(self, evidence):
        ctx = E._build_evidence_context(evidence)
        assert "IF=" not in ctx
        assert "IF:" not in ctx
        assert not re.search(r"impact\s*factor", ctx, re.I)

    def test_it_is_gone_from_the_per_tier_block_specifically(self, evidence):
        """Located precisely, because a global absence check would also pass
        if the whole block stopped being emitted — which would be a different
        and much larger regression."""
        ctx = E._build_evidence_context(evidence)
        assert "Top paper per tier" in ctx, (
            "the per-tier block itself disappeared; that is not this fix")
        block = ctx[ctx.index("Top paper per tier"):]
        assert "37.771" not in block
        # and the block still carries the signals it is supposed to carry
        assert "PMID 111" in block and "73.3/100" in block
        assert "Year: 2024" in block and "Citations: 12" in block
        assert "n=88" in block and "24mo follow-up" in block

    def test_no_substitute_signal_took_its_place(self, evidence):
        """A band or a tag would be the same influence under another name."""
        ctx = E._build_evidence_context(evidence).lower()
        for banned in ("high-impact", "high impact", "top-tier journal",
                       "journal quality", "journal rank", "prestige",
                       "q1 journal", "jcr"):
            assert banned not in ctx, f"substitute journal signal: {banned!r}"

    @pytest.mark.parametrize("value", [0.1, 1, 4.5, 8.0, 12.0, 99.9])
    def test_absent_whatever_the_magnitude(self, evidence, value):
        for p in evidence["_summary"]["all_scored"]:
            p["impact_factor"] = value
        ctx = E._build_evidence_context(evidence)
        assert "IF=" not in ctx

    def test_a_missing_value_is_not_special_cased_into_a_signal(self, evidence):
        """`impact_factor: None` must not become 'IF=unknown' either — an
        absence that is reported is still a journal-identity signal."""
        for p in evidence["_summary"]["all_scored"]:
            p["impact_factor"] = None
        ctx = E._build_evidence_context(evidence)
        assert "unknown" not in ctx.lower().split("top paper per tier")[-1]


class TestTheOtherContextLineStaysClean:
    """`format_paper_context_line` is the per-paper header for the same
    prompt. It was cleaned first (invariant 11); both halves are pinned in one
    file so they cannot drift apart."""

    def test_the_paper_line_carries_no_impact_factor(self):
        line = E.format_paper_context_line(_paper("444", "level1", 70.0))
        assert "37.771" not in line
        assert "IF" not in line

    def test_the_paper_line_still_carries_what_it_should(self):
        line = E.format_paper_context_line(_paper("444", "level1", 70.0))
        assert "PMID: 444" in line
        assert "n=88" in line
        assert "Citations: 12" in line


class TestAllFourAnswerPathsGoThroughThisFunction:
    """Pinning `_build_evidence_context` only pins the four paths if the four
    paths actually call it. Asserted on the source, because the alternative is
    four live answers at roughly two dollars each."""

    PATHS = ["ask_clinical_question", "ask_learn_question",
             "write_curriculum_module", "ask_case_question"]

    @pytest.mark.parametrize("fn", PATHS)
    def test_the_path_builds_its_context_here(self, fn):
        src = (ROOT / "endo_ai.py").read_text(encoding="utf-8")
        i = src.index(f"def {fn}(")
        j = src.index("\ndef ", i + 1)
        body = src[i:j]
        assert "_build_evidence_context" in body, (
            f"{fn} assembles its evidence context some other way, so the "
            f"absence pinned above does not cover it")

    def test_the_leak_is_not_reintroduced_anywhere_in_the_builder(self):
        src = (ROOT / "endo_ai.py").read_text(encoding="utf-8")
        i = src.index("def _build_evidence_context(")
        j = src.index("\ndef ", i + 1)
        body = src[i:j]
        code = "\n".join(l for l in body.splitlines()
                         if not l.strip().startswith("#"))
        assert "impact_factor" not in code, (
            "the context builder reads impact_factor again")
