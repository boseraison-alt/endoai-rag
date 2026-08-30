"""
Every tier filter must mean what it says to PubMed.

Two bugs of this shape have now shipped, both invisible in code review because
the strings look plausible:

  * "randomized controlled trial[pt] less quality" — a comment that leaked into
    a query string. PubMed parsed it as `... AND less AND quality`, gutting
    Level II.
  * "Cochrane Review[pt]" — a publication type that does not exist. PubMed
    silently translated it to ("cochran" OR "cochrane" ...) AND "Review"[pt],
    matching any review that mentions the word Cochrane — which is nearly every
    systematic review, since they all cite searching the Cochrane Library. That
    put ordinary journal SRs into the tier the prompt treats as most
    authoritative.

The offline tests below catch malformed syntax. The network test asks PubMed
what it actually understood, which is the only way to catch a filter that is
syntactically fine and semantically wrong.

The network tests are skipped by default so a plain `pytest` run stays offline.
Enable them with:  RUN_NETWORK_TESTS=1 pytest tests/test_tier_filter_syntax.py
"""

import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from endo_ai import (COCHRANE_TERM, LEVEL_1_TERMS, LEVEL_2_TERMS,
                     LEVEL_3A_TERMS, LEVEL_3B_TERMS, LEVEL_4_TERMS,
                     LEVEL_5_TERMS, ENDO_DOMAIN_FILTER)

ALL_TIERS = {
    "cochrane": [COCHRANE_TERM],
    "level1":   LEVEL_1_TERMS,
    "level2":   LEVEL_2_TERMS,
    "level3a":  LEVEL_3A_TERMS,
    "level3b":  LEVEL_3B_TERMS,
    "level4":   LEVEL_4_TERMS,
    "level5":   LEVEL_5_TERMS,
}

# Every PubMed field tag the filters legitimately use.
_FIELD_TAG = re.compile(r"\[(pt|mh|jour|tiab|ti|ab|MeSH|majr|sb)\]", re.IGNORECASE)


def _terms():
    for tier, terms in ALL_TIERS.items():
        for t in terms:
            yield tier, t


class TestTierFilterSyntax:

    @pytest.mark.parametrize("tier,term", list(_terms()))
    def test_every_term_carries_a_field_tag(self, tier, term):
        assert _FIELD_TAG.search(term), \
            f"{tier}: term has no PubMed field tag, so it searches all fields: {term!r}"

    @pytest.mark.parametrize("tier,term", list(_terms()))
    def test_no_text_trails_the_field_tag(self, tier, term):
        """'randomized controlled trial[pt] less quality' — the exact shape of
        a comment leaking into a query."""
        tail = _FIELD_TAG.split(term)[-1].strip()
        assert tail == "", \
            f"{tier}: text after the field tag will be ANDed as a search term: {term!r} (trailing {tail!r})"

    @pytest.mark.parametrize("tier,term", list(_terms()))
    def test_balanced_quotes_and_brackets(self, tier, term):
        assert term.count('"') % 2 == 0, f"{tier}: unbalanced quotes in {term!r}"
        assert term.count("[") == term.count("]"), f"{tier}: unbalanced brackets in {term!r}"

    def test_cochrane_tier_is_journal_scoped(self):
        """The cochrane tier must identify the JOURNAL. No publication type
        named 'Cochrane Review' exists, and matching on the word alone pulls in
        every SR that cites searching the Cochrane Library."""
        assert "[jour]" in COCHRANE_TERM.lower(), \
            f"cochrane tier must be journal-scoped, got {COCHRANE_TERM!r}"
        assert "cochrane database" in COCHRANE_TERM.lower()
        assert "[pt]" not in COCHRANE_TERM.lower(), \
            "there is no 'Cochrane Review' publication type in PubMed"


@pytest.mark.network
@pytest.mark.skipif(os.environ.get("RUN_NETWORK_TESTS") != "1",
                    reason="hits live PubMed; set RUN_NETWORK_TESTS=1 to enable")
class TestPubMedUnderstandsTheFilters:
    """Ask PubMed what it actually parsed. A filter can be syntactically valid
    and still mean something entirely different once translated."""

    def _search(self, term):
        import requests
        from endo_ai import NCBI_EUTILS_BASE, _ncbi_params
        r = requests.get(f"{NCBI_EUTILS_BASE}/esearch.fcgi",
                         params=_ncbi_params({"db": "pubmed", "term": term,
                                              "retmax": 0, "retmode": "json"}),
                         timeout=30)
        time.sleep(0.4)               # NCBI courtesy limit
        d = r.json()["esearchresult"]
        return int(d["count"]), d.get("querytranslation", "")

    @pytest.mark.parametrize("tier,terms", list(ALL_TIERS.items()))
    def test_tier_filter_returns_results_in_the_endo_domain(self, tier, terms):
        query = f"({' OR '.join(terms)}) AND {ENDO_DOMAIN_FILTER}"
        count, _ = self._search(query)
        assert count > 0, f"{tier}: filter matches nothing in endodontics — {query[:160]}"

    @pytest.mark.parametrize("tier,term", list(_terms()))
    def test_no_term_leaks_into_an_all_fields_match(self, tier, term):
        """A tagged term should translate to a field-scoped clause. Stray words
        show up as [All Fields], which is how both known bugs manifested."""
        _, translation = self._search(term)
        stray = re.findall(r'"(\w+)"\[All Fields\]', translation)
        # Journal and MeSH terms legitimately expand; only flag bare words that
        # are not part of the term itself.
        leaked = [s for s in stray if s.lower() not in term.lower()]
        assert not leaked, f"{tier}: {term!r} leaked into All Fields: {leaked}"

    def test_cochrane_filter_matches_only_the_cochrane_database(self):
        count, translation = self._search(COCHRANE_TERM)
        assert "[Journal]" in translation, \
            f"cochrane filter is not journal-scoped once translated: {translation}"
        assert "All Fields" not in translation, \
            f"cochrane filter is matching free text: {translation}"
        assert count > 1000, "expected the Cochrane Database to be well populated"
