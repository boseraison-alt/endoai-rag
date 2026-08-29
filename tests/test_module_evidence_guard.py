"""
A module with no evidence must not produce a clinical protocol.

The incident this guards: a Deep Learning run on laser root canal disinfection
retrieved ZERO papers for module 4 and still emitted a fully specified numeric
protocol — "Er:YAG 20 mJ, 15 Hz", "5.25% NaOCl, 2 mL, 60 s", "ISO #30/.04" —
with no citation anywhere, shipped behind a disclaimer. Invented irrigant
concentrations and laser settings are the most dangerous output this system can
produce, and a disclaimer does not redeem them.

Root cause was upstream: esearch returned 5 PMIDs across 28 queries for that
run because module search strings were bags of words ("laser irradiation power
settings endodontic disinfection"), which PubMed ANDs together. That is fixed in
the prompts; this file guards the failure mode itself, so a future retrieval
regression degrades to an explicit gap rather than to invented numbers.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from endo_ai import (module_has_usable_evidence, validate_module_output,
                     _module_not_generated_block, MIN_MODULE_PAPERS,
                     LEVEL_2_TERMS)


def ev(n):
    return {"_summary": {"all_scored": [{"pmid": str(9000 + i), "score": 60.0}
                                        for i in range(n)]}}


class TestEvidenceSufficiency:

    def test_zero_papers_is_insufficient(self):
        ok, n = module_has_usable_evidence(ev(0))
        assert ok is False and n == 0

    def test_one_paper_is_insufficient(self):
        assert module_has_usable_evidence(ev(1))[0] is False

    def test_minimum_is_sufficient(self):
        assert module_has_usable_evidence(ev(MIN_MODULE_PAPERS))[0] is True

    def test_missing_summary_is_insufficient(self):
        assert module_has_usable_evidence({})[0] is False
        assert module_has_usable_evidence(None)[0] is False


class TestNumericProtocolWithoutCitations:
    """The exact strings the incident produced."""

    @pytest.mark.parametrize("text", [
        "Irradiate with Er:YAG at 20 mJ, 15 Hz for 30 s.",
        "Irrigate with 5.25% NaOCl, 2 mL per canal, 60 s contact time.",
        "Prepare to ISO #30/.04 taper before final rinse.",
        "Apply 17% EDTA for 1 min, then dry with paper points.",
        "Set the diode laser to 1.5 W in continuous mode.",
    ])
    def test_uncited_numeric_parameters_are_rejected(self, text):
        v = validate_module_output(text, ev(0))
        assert v["ok"] is False
        assert "numeric clinical parameter" in v["reason"]

    def test_same_parameters_with_a_citation_pass(self):
        v = validate_module_output(
            "Irrigate with 5.25% NaOCl for 60 s [[PMID:12345678]].", ev(3))
        assert v["ok"] is True

    def test_prose_without_parameters_passes(self):
        v = validate_module_output(
            "Laser disinfection remains an adjunct rather than a replacement for "
            "chemomechanical preparation, and the evidence base is still forming.",
            ev(3))
        assert v["ok"] is True

    def test_empty_text_passes(self):
        assert validate_module_output("", ev(3))["ok"] is True


class TestNotGeneratedBlock:

    def test_states_the_gap_and_gives_no_protocol(self):
        block = _module_not_generated_block("Laser disinfection outcomes", 0,
                                            "laser disinfection endodontic")
        assert "Module not generated" in block
        assert "insufficient evidence" in block.lower()
        assert "no papers" in block.lower()
        # It must not itself contain clinical parameters.
        assert validate_module_output(block, ev(0))["ok"] is True

    def test_reports_a_partial_count(self):
        assert "only 1 paper(s)" in _module_not_generated_block("T", 1)

    def test_includes_the_search_for_debuggability(self):
        assert "laser" in _module_not_generated_block("T", 0, "laser endodontic")


class TestTierFilterSyntax:
    """A stray annotation in the Level II filter — "randomized controlled
    trial[pt] less quality" — was parsed by PubMed as `... AND less AND
    quality`, silently gutting the tier."""

    def test_no_bare_words_in_level2_terms(self):
        for term in LEVEL_2_TERMS:
            stripped = term
            for tag in ("[pt]", "[mh]", "[tiab]", "[MeSH]"):
                stripped = stripped.replace(tag, "")
            # Every term must be a single tagged field, not a tagged field
            # followed by loose commentary.
            assert term.count("[") >= 1, f"untagged Level II term: {term!r}"
            assert not stripped.strip().endswith(("quality", "less")), \
                f"stray annotation in Level II term: {term!r}"

    def test_level2_terms_are_recognised_pubmed_syntax(self):
        for term in LEVEL_2_TERMS:
            assert term.strip().endswith(("]",)), \
                f"Level II term must end in a field tag: {term!r}"
