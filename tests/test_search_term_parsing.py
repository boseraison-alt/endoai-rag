"""
Search-term parsing must never silently degrade retrieval breadth.

The old path was `json.loads` behind `except: pass`, falling back to ONE term.
Measured on ten consecutive live Haiku calls (2026-08-29): 5/10 parse failures,
none of them truncation. The cause: PubMed queries require quoted phrases, the
prompt demands them, and the model emits them unescaped inside JSON strings —
invalid JSON by construction. Retrieval breadth flapped between 1 and 3 terms
for the same question; paper counts moved 43 → 92.

The RAW_* fixtures below are verbatim responses captured from those live probe
calls, not invented shapes.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from endo_ai import (_parse_term_list, _looks_like_query, _clean_single_query,
                     _parse_module_lines)

# ── Real captured Haiku responses ────────────────────────────────────────

# Probe call 0: unescaped inner quotes inside JSON strings — the dominant
# failure (5/10 calls). json.loads raises; the old code returned 1 term.
RAW_UNESCAPED_QUOTES = '''```json
[
  "(laser* OR photoacoustic OR photothermal) AND (endodontic* OR "root canal treatment") AND (bacterial reduction OR pathogen elimination OR microbial control OR intracanal infection)",
  "(Er:YAG OR Nd:YAG OR diode laser OR "laser irradiation") AND ("root canal disinfection" OR "endodontic sterilization" OR "intracanal debridement") AND (efficacy OR effectiveness OR clinical outcomes)"
]
```'''

# Probe call 1: properly escaped JSON — the shape that worked.
RAW_CLEAN_JSON = '''```json
[
  "(laser* OR photoacoustic OR photothermal) AND (endodontic* OR \\"root canal\\" OR \\"intracanal\\") AND (bacterial OR pathogen* OR infection* OR microorganism*)",
  "(\\"laser disinfection\\" OR \\"laser irrigation\\") AND (endodontic* OR \\"root canal therapy\\") AND (efficacy OR effectiveness OR outcome* OR success*)"
]
```'''

# The new line-based contract.
RAW_TERM_LINES = '''TERM: (laser* OR aPDT OR "photodynamic therapy") AND ("root canal" OR endodontic*) AND (disinfect* OR biofilm)
TERM: (Er:YAG OR Nd:YAG OR "diode laser") AND (intracanal OR "root canal") AND (bacteric* OR antimicrobial)
TERM: (PIPS OR SWEEPS OR "laser-activated irrigation") AND (endodontic* OR "root canal") AND (irrigat* OR debride*)'''

RAW_PROSE_WRAPPED = '''Here are the additional search queries you requested:

TERM: (laser* OR aPDT) AND ("root canal" OR endodontic*) AND (disinfect* OR biofilm)
TERM: (Er:YAG OR "diode laser") AND (intracanal OR "root canal") AND (antimicrobial OR bacteric*)

These cover different angles from the primary search.'''


class TestParseTermList:

    def test_recovers_unescaped_quote_json(self):
        """The 5/10 failure. The old code got 0 extras from this response."""
        terms = _parse_term_list(RAW_UNESCAPED_QUOTES)
        assert len(terms) == 2
        assert all(" AND " in t for t in terms)
        assert '"root canal treatment"' in terms[0]

    def test_parses_clean_json(self):
        terms = _parse_term_list(RAW_CLEAN_JSON)
        assert len(terms) == 2
        assert '"root canal"' in terms[0]

    def test_parses_term_lines(self):
        assert len(_parse_term_list(RAW_TERM_LINES)) == 3

    def test_term_lines_survive_prose_wrapper(self):
        assert len(_parse_term_list(RAW_PROSE_WRAPPED)) == 2

    def test_empty_and_garbage_yield_empty_not_crash(self):
        assert _parse_term_list("") == []
        assert _parse_term_list("[]") == []
        assert _parse_term_list("I cannot help with that.") == []
        assert _parse_term_list("{broken json") == []

    def test_unbalanced_terms_are_dropped_not_repaired(self):
        """PubMed reinterprets malformed queries instead of rejecting them
        (the tier-filter bug class), so a damaged term must be dropped."""
        raw = ('TERM: (laser* OR aPDT AND ("root canal" OR endodontic*)\n'      # missing )
               'TERM: (laser* OR "aPDT) AND ("root canal")\n'                    # odd quotes
               'TERM: (laser* OR aPDT) AND ("root canal" OR endodontic*)')       # good
        terms = _parse_term_list(raw)
        assert terms == ['(laser* OR aPDT) AND ("root canal" OR endodontic*)']

    def test_duplicates_are_removed(self):
        raw = "TERM: (a OR b) AND (c OR d)\nTERM: (a OR b) AND (c OR d)"
        assert len(_parse_term_list(raw)) == 1


class TestLooksLikeQuery:

    @pytest.mark.parametrize("bad", [
        "", "short", "no boolean operators here at all",
        "(unbalanced OR parens AND x",
        '(odd OR "quotes) AND (x OR y)',
    ])
    def test_rejects(self, bad):
        assert not _looks_like_query(bad)

    def test_accepts_real_query(self):
        assert _looks_like_query(
            '(laser* OR aPDT) AND ("root canal" OR endodontic*) AND disinfect*')


class TestCleanSingleQuery:

    def test_plain_query_passes_through(self):
        q = '(laser* OR aPDT) AND ("root canal" OR endodontic*)'
        assert _clean_single_query(q) == q

    def test_strips_fence_and_surrounding_quotes(self):
        q = '(laser* OR aPDT) AND ("root canal" OR endodontic*)'
        assert _clean_single_query(f'```\n"{q}"\n```') == q

    def test_picks_query_line_out_of_prose(self):
        q = '(laser* OR aPDT) AND ("root canal" OR endodontic*)'
        raw = f"Here is the PubMed boolean query:\n\n{q}\n\nThis covers the topic."
        assert _clean_single_query(raw) == q

    def test_truncated_query_returns_empty_for_retry(self):
        """A response cut mid-query has unbalanced parens; shipping it would
        hand PubMed something it silently reinterprets."""
        assert _clean_single_query('(laser* OR aPDT) AND ("root canal" OR endod') == ""


class TestParseModuleLines:

    LINES = ('MODULE: Laser Physics and Mechanisms ||| (laser* OR Er:YAG OR Nd:YAG) AND (mechanism* OR physic* OR photothermal)\n'
             'MODULE: Diagnosis and Case Selection ||| ("case selection" OR diagnos*) AND (laser* OR "photodynamic therapy")\n'
             'MODULE: Clinical Technique ||| (technique* OR protocol*) AND (laser* OR PIPS OR SWEEPS)\n'
             'MODULE: Outcomes and Complications ||| (outcome* OR complicat* OR prognos*) AND (laser* OR aPDT)')

    def test_parses_module_lines(self):
        mods = _parse_module_lines(self.LINES, 4)
        assert len(mods) == 4
        assert mods[0]["title"] == "Laser Physics and Mechanisms"
        assert " AND " in mods[0]["search_query"]

    def test_legacy_json_still_accepted(self):
        raw = ('[{"title": "Background", "search_query": "(pulp* OR endodontic*) AND (patho* OR etiolog*)"},'
               ' {"title": "Treatment", "search_query": "(treat* OR manag*) AND (laser* OR aPDT)"}]')
        mods = _parse_module_lines(raw, 4)
        assert [m["title"] for m in mods] == ["Background", "Treatment"]

    def test_module_with_mangled_query_is_dropped(self):
        raw = ('MODULE: Good ||| (a* OR b*) AND (c OR d)\n'
               'MODULE: Bad ||| (a* OR b AND (c OR d)')
        mods = _parse_module_lines(raw, 4)
        assert [m["title"] for m in mods] == ["Good"]

    def test_garbage_yields_empty(self):
        assert _parse_module_lines("Sorry, I can't do that.", 4) == []
