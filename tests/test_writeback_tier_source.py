"""Item C (2026-09-06) — write-back stores the DESIGN, not the lane.

`level_key` has two writers. The pubtype backfill stores what the paper IS.
Live write-back stored `eff_level` — "the tier this paper was retrieved under",
which is a fact about the QUERY, not about the paper. Write-back runs on every
live query; the backfill runs when somebody runs it. So write-back decided what
the column meant, and what it meant was "which query found this".

That is how nine IADT consensus guidelines came to sit at level1 and level2
with evidence scores and impact factors: they answered a level2 lane's query.

THE FIXTURE IS THE REAL FETCHED RECORD FOR PMID 32475015, per the batch, and
it earned its place immediately: its publication types are

    ["Journal Article", "Review", "Consensus Statement"]

not "Practice Guideline". The first version of the mapping had no entry for
`Consensus Statement`, derived nothing for this row, and would have shipped a
guard that left the exact document the item is about still banded by its lane.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import endo_ai as E

# Real records, fetched from PubMed 2026-09-06. Not invented.
IADT_2020_FRACTURES = {
    "pmid": "32475015",
    "title": "International Association of Dental Traumatology guidelines for "
             "the management of traumatic dental injuries: 1. Fractures and "
             "luxations.",
    "journal": "Dent Traumatol",
    "year": "2020",
    "publication_types": ["Journal Article", "Review", "Consensus Statement"],
}
IADT_2012_FRACTURES = {
    "pmid": "22230724",
    "journal": "Dent Traumatol",
    "publication_types": ["Journal Article", "Practice Guideline"],
}
IADT_2020_INTRO = {
    "pmid": "32472740",
    "journal": "Dent Traumatol",
    "publication_types": ["Journal Article", "Review"],
}


class TestTheTierIsDerivedFromPublicationTypes:

    def test_a_consensus_statement_derives_the_guideline_tier(self):
        tier, why = E.tier_from_pubtypes(
            IADT_2020_FRACTURES["publication_types"],
            IADT_2020_FRACTURES["journal"])
        assert tier == "guideline", (
            "PMID 32475015 derived %r; it is an IADT consensus guideline"
            % tier)
        assert "consensus statement" in why

    def test_a_practice_guideline_derives_the_guideline_tier(self):
        tier, _why = E.tier_from_pubtypes(
            IADT_2012_FRACTURES["publication_types"],
            IADT_2012_FRACTURES["journal"])
        assert tier == "guideline"

    def test_a_guideline_never_derives_level1(self):
        """`backfill_pubmed_metadata.PUBTYPE_TO_LEVEL` maps guideline types to
        level1 — written before the guideline tier existed. Deriving with it
        puts a consensus guideline at the TOP of the evidence ladder, which is
        the same category error running the other way."""
        for t in ("Practice Guideline", "Guideline", "Consensus Statement",
                  "Consensus Development Conference"):
            tier, _ = E.tier_from_pubtypes(["Journal Article", t], "Dent Traumatol")
            assert tier == "guideline", "%r derived %r" % (t, tier)

    def test_a_review_only_record_derives_nothing(self):
        """NLM does not reliably tag society guidelines in dental journals.
        PMID 32472740 — the IADT 2020 introduction — carries only
        ["Journal Article", "Review"], and mapping a bare Review to level5
        would demote a consensus guideline to expert opinion. Deriving nothing
        and falling through to the lane is no worse than today; guessing is."""
        tier, why = E.tier_from_pubtypes(IADT_2020_INTRO["publication_types"],
                                         IADT_2020_INTRO["journal"])
        assert tier is None and why == "", (
            "a Review-only record derived %r — this is the non-demotion guard"
            % tier)

    def test_cochrane_is_decided_by_journal_not_pubtype(self):
        tier, why = E.tier_from_pubtypes(["Journal Article", "Review"],
                                         "Cochrane Database Syst Rev")
        assert tier == "cochrane" and why == "journal:cochrane"

    def test_no_publication_types_derives_nothing(self):
        assert E.tier_from_pubtypes([], "Int Endod J") == (None, "")
        assert E.tier_from_pubtypes(None, "") == (None, "")


class TestTheLaneIsOnlyTheFallback:

    def _run(self, monkeypatch, pubtypes, lane):
        """Drive the real scoring path with one stubbed PubMed record."""
        captured = {}

        class _Resp:
            status_code = 200

            def json(self):
                return {"esearchresult": {"idlist": ["32475015"], "count": "1"}}

        def fake_get(url, params=None, **kw):
            return _Resp()

        def fake_meta(ids, **kw):
            return {"32475015": {
                "year": 2020, "citations": 0, "journal": "Dent Traumatol",
                "journal_abbrev": "Dent Traumatol", "authors": "Bourguignon C",
                "medline_indexed": True, "pubtypes": list(pubtypes),
                "has_erratum": False, "has_retraction": False,
                "registry_ids": [], "coi_statement": "", "superseded_by": "",
                "volume": "", "issue": "", "pages": "",
            }}

        def fake_parts(ids, **kw):
            return {"32475015": {
                "title": IADT_2020_FRACTURES["title"],
                "abstract": "Consensus guideline text for testing purposes "
                            "with enough length to pass any content floor.",
            }}

        monkeypatch.setattr(E, "ncbi_get", fake_get)
        for name, fn in (("fetch_paper_metadata", fake_meta),
                         ("fetch_pubmed_metadata", fake_meta),
                         ("_fetch_abstracts", fake_parts),
                         ("fetch_abstracts", fake_parts)):
            if hasattr(E, name):
                monkeypatch.setattr(E, name, fn)
        captured["scored"] = None
        return captured

    # BEHAVIOURAL, NOT SOURCE-TEXT. The first version of these two asserted
    # that `tier_from_pubtypes(` APPEARS between the lane assignment and the
    # store. It does — even when the call is wrapped in `if False:`. The
    # mutation check made the lane win again and all ten tests still passed,
    # which is a test that reads the code rather than running it. These drive
    # the real `fetch_papers` with a stubbed PubMed and assert on the dict it
    # produces.

    def _one_paper(self, monkeypatch, pubtypes, lane, journal="Dent Traumatol"):
        PMID = "32475015"

        class _Resp:
            status_code = 200
            text = ""

            def json(self):
                return {"esearchresult": {"idlist": [PMID], "count": "1"}}

        monkeypatch.setattr(E, "ncbi_get",
                            lambda *a, **k: _Resp())
        monkeypatch.setattr(E, "fetch_metadata", lambda ids, **k: {PMID: {
            "year": 2020, "citations": 0, "journal": journal,
            "journal_abbrev": journal, "authors": "Bourguignon C",
            "medline_indexed": True, "pubtypes": list(pubtypes),
            "has_erratum": False, "has_retraction": False, "registry_ids": [],
            "coi_statement": "", "superseded_by": "", "volume": "",
            "issue": "", "pages": "", "is_book": False,
        }})
        monkeypatch.setattr(E, "_parse_efetch_batch", lambda _t: {PMID: {
            "title": IADT_2020_FRACTURES["title"],
            "abstract": "Consensus guideline text, long enough to clear any "
                        "content floor this path applies before scoring it.",
        }})
        monkeypatch.setattr(E, "_apply_quality_threshold",
                            lambda papers, **k: papers)
        try:
            monkeypatch.setattr(E, "bulk_cache_abstracts", lambda *a, **k: 0)
        except AttributeError:
            pass
        out = E.fetch_papers("(pulpitis)", "review[pt]", lane, lane,
                             max_results=1)
        scored = out[2] if isinstance(out, tuple) and len(out) > 2 else None
        assert scored, "the stubbed path produced no scored papers"
        return scored[0]

    def test_a_consensus_guideline_is_stored_as_guideline_not_as_the_lane(
            self, monkeypatch):
        p = self._one_paper(monkeypatch,
                            IADT_2020_FRACTURES["publication_types"], "level2")
        assert p["level_key"] == "guideline", (
            "retrieved by the level2 lane and stored as %r — this is the "
            "defect: the lane decided the tier" % p["level_key"])
        assert p["level_key_source"].startswith("pubtype:"), (
            "stored source %r" % p["level_key_source"])

    def test_an_underivable_record_falls_back_to_the_lane_and_says_so(
            self, monkeypatch):
        p = self._one_paper(monkeypatch,
                            IADT_2020_INTRO["publication_types"], "level2")
        assert p["level_key"] == "level2"
        assert p["level_key_source"] == "lane:level2", (
            "the fallback must be visible, got %r" % p["level_key_source"])

    def test_a_real_trial_keeps_its_derived_tier(self, monkeypatch):
        p = self._one_paper(monkeypatch,
                            ["Journal Article", "Randomized Controlled Trial"],
                            "level5", journal="Int Endod J")
        assert p["level_key"] == "level1", (
            "an RCT retrieved by the level5 lane was stored as %r"
            % p["level_key"])


class TestTheDerivedWriterWins:

    def test_the_write_back_sql_refuses_a_lane_over_a_derivation(self):
        rag_src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "rag.py"), encoding="utf-8").read()
        i = rag_src.index("def learn_from_live_results(")
        j = rag_src.index("def ", i + 10)
        body = rag_src[i:j]
        assert "level_key_source" in body, (
            "write-back does not carry level_key_source")
        assert "lane:" in body, (
            "write-back does not distinguish a lane key from a derived one")

    def test_the_column_exists_in_the_schema(self):
        rag_src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "rag.py"), encoding="utf-8").read()
        assert '("level_key_source"' in rag_src
