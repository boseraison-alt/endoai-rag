"""The guideline lane asks a guideline-shaped question.

WHAT WENT WRONG. The lane inherited the study lanes' topic string — a
three-group conjunction naming the intervention, the subject and the
population qualifier. That is the right shape for finding trials and the wrong
shape for finding guidelines, because a guideline is broad by construction.

MEASURED across the three v7 baseline runs: 482 lane queries, 415 of them
empty — 86%, against 47% for every other lane together. It supplied 35% of all
empties and dragged the corpus empty rate from 46% to 55%, through a 50%
assertion ceiling written before the lane existed.

THE TWO FIXTURES. Both documents are PubMed-indexed AND both match the lane's
own `guideline[pt]` filter — verified directly against PubMed — and the lane
returned nothing on the questions they answer:

    PMID 37772327   ESE S3-level clinical practice guideline, 2023
                    "Treatment of pulpal and apical disease"
                    the guideline for: retreatment vs apical microsurgery

    PMID 26990236   ESE position statement, revitalisation, 2016
                    the guideline for: immature permanent teeth

So the emptiness was the TOPIC half of the query. Not the pubtype filter, not
the corpus. Measured on the fixtures' own questions:

    full conjunction   0 hits, fixture absent   (both questions)
    subject group      28 hits / 6 hits, fixture PRESENT

These are regression fixtures in the sense §6 of the guidelines handover
means: real misses, contributed by a real comparison, that get stronger every
time they catch something.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import endo_ai as E


class TestTheSubjectGroupIsWhatTheLaneAsksFor:

    def test_it_picks_the_generic_subject_group_not_the_longest(self):
        """Selection is by GENERIC SHARE, not by length and not by
        `_group_is_generic`.

        `_group_is_generic` is all-or-nothing and a real subject group rarely
        is: ("root canal" OR endodontic* OR "root canal treatment") scores 2 of
        3, because the third is not in _COVERAGE_GENERIC. The all-or-nothing
        form returned False for every group on this exact query, and the
        length fallback then picked the five-synonym SCENARIO group — the
        widest, and the wrong concept. That was my first version."""
        term = ('("single-visit" OR "one-visit" OR "same-day" OR "single appointment" '
                'OR "one appointment") AND ("root canal" OR endodontic* OR "root canal '
                'treatment") AND (necrotic OR "pulp necrosis")')
        got = E.guideline_topic(term)
        assert "root canal" in got and "endodontic*" in got
        assert "single-visit" not in got, "kept the scenario qualifier"
        assert "necrotic" not in got, "kept the population qualifier"

    def test_a_query_with_no_boolean_structure_is_returned_unchanged(self):
        """`generate_search_terms` falls back to the raw question when
        generation fails. Guessing at a subject group there would invent one."""
        raw = "Single visit versus multiple visit endodontic treatment?"
        assert E.guideline_topic(raw) == raw

    def test_a_single_group_is_returned_unchanged(self):
        one = '("root canal" OR endodontic*)'
        assert E.guideline_topic(one) == one

    def test_the_widest_group_is_the_fallback_when_none_is_generic(self):
        term = '(alpha OR beta OR gamma OR delta) AND (zeta OR eta)'
        got = E.guideline_topic(term)
        assert "alpha" in got and "zeta" not in got

    def test_a_non_empty_topic_never_becomes_empty(self):
        """An empty topic would make the lane query the domain filter ALONE —
        every endodontic guideline on PubMed regardless of the question. The
        first version of this test also asserted it for an empty INPUT, which
        no function can satisfy without inventing a topic; the real property is
        that broadening never destroys one."""
        for t in ("(a) AND (b)", "x AND y AND z", "(alpha OR beta) AND (g)",
                  '("root canal") AND (necrotic)'):
            assert E.guideline_topic(t).strip() != "", t

    def test_an_empty_input_is_passed_through_unchanged(self):
        """Not invented into something. The caller's problem stays visible."""
        assert E.guideline_topic("") == ""


class TestOnlyTheGuidelineLaneIsBroadened:
    """The batch is explicit: do not touch the study lanes' queries."""

    def test_the_broadening_is_gated_on_the_lane_key(self):
        src = (Path(__file__).parent.parent / "endo_ai.py").read_text(encoding="utf-8")
        i = src.index("def fetch_papers(")
        j = src.index("search_url    = ", i)
        body = src[i:j]
        assert 'if level_key == "guideline":' in body, (
            "the broadening is not gated on the lane — every study lane would "
            "lose its qualifiers")
        assert "guideline_topic(topic)" in body

    def test_it_sits_in_the_shared_helper_not_a_caller(self):
        """A broadening that lived in app.py would reach Review and Case and
        not the curriculum — the divergence class this codebase has spent
        three batches removing."""
        app = (Path(__file__).parent.parent / "app.py").read_text(encoding="utf-8")
        assert "guideline_topic(" not in app


class TestTheTwoFixtures:
    """Network. Skipped unless RUN_NETWORK_TESTS=1, like every live check."""

    FIXTURES = [
        ("37772327",
         "Nonsurgical retreatment versus apical microsurgery for persistent "
         "apical periodontitis"),
        ("26990236",
         "Regenerative endodontic revitalisation in immature permanent teeth"),
    ]

    @pytest.mark.network
    @pytest.mark.parametrize("pmid,question", FIXTURES)
    def test_the_broadened_lane_reaches_the_guideline(self, pmid, question):
        import os
        if not os.environ.get("RUN_NETWORK_TESTS"):
            pytest.skip("network test")
        smart = E.generate_search_terms(question)
        topic = E.guideline_topic(smart)
        term = (f"({topic}) AND (practice guideline[pt] OR guideline[pt] OR "
                f"consensus development conference[pt]) AND {E.ENDO_DOMAIN_FILTER}")
        r = E.ncbi_get(f"{E.NCBI_EUTILS_BASE}/esearch.fcgi", params=E._ncbi_params({
            "db": "pubmed", "term": term, "retmode": "json", "retmax": 200}),
            timeout=20)
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        assert pmid in ids, (
            f"PMID {pmid} is PubMed-indexed, matches guideline[pt], and is THE "
            f"guideline for this question — and the lane still does not reach it")

    def test_the_fixtures_are_recorded_where_the_fix_is(self):
        """Rule 21/24 — offline, so the record survives without the network."""
        src = (Path(__file__).parent.parent / "endo_ai.py").read_text(encoding="utf-8")
        assert "37772327" in src and "26990236" in src
        assert "86%" in src, "the measurement that justified the change is gone"
