"""G1 — a withdrawn source is never cited.

Cochrane sits at the TOP of the tier ladder, so a withdrawn Cochrane review
retrieved live would be presented as the strongest evidence in the answer.

PROSPECTIVE, and measured to be so: A1 found that none of the three withdrawn
endodontic reviews (CD007997, CD005408, CD004623) is in the library and none is
cited by any stored answer. This gate protects the next live search and the next
ingest; it is not cleaning up a live contamination.

Excluded rather than badged. `has_retraction` already renders a badge, which is
right for "treat with caution". Withdrawn is different — the publisher has
removed the conclusions, so there is nothing left to weigh.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import endo_ai as e  # noqa: E402


# ── G1 ────────────────────────────────────────────────────────────────
class TestG1WithdrawnSourcesAreNeverCited:

    def test_the_seed_carries_all_four_withdrawn_manifest_entries(self):
        """Rule 5 — a gate seeded from a manifest must actually load it.

        Three of the four are Cochrane CD numbers; the fourth
        (SDCEP-BISPHOSPHONATES-2011) has NEITHER a pmid nor a CD number, so a
        seed built only from those two fields would silently cover three of
        four and look complete.
        """
        seed = e._withdrawn_seed()
        for cd in ("CD007997", "CD005408", "CD004623"):
            assert cd in seed, "%s missing from the withdrawn seed" % cd
        assert "SDCEP-BISPHOSPHONATES-2011" in seed, (
            "the fourth withdrawn entry is unmatchable: it has no pmid and no "
            "CD number, so only its manifest id can catch it")

    @pytest.mark.parametrize("paper,why", [
        ({"pmid": "111",
          "title": "Interventions for the management of post-endodontic pain",
          "journal": "Cochrane Database Syst Rev",
          "doi": "10.1002/14651858.CD007997.pub2"}, "CD number in the doi"),
        ({"pmid": "222",
          "title": "Root canal posts for the restoration of root filled teeth "
                   "(Withdrawn)",
          "journal": "Cochrane Database Syst Rev"}, "title marker"),
        ({"pmid": "444", "title": "Effect of X on Y", "journal": "J Endod",
          "publication_types": ["Withdrawn Publication"]}, "PubMed type"),
        ({"pmid": "SDCEP-BISPHOSPHONATES-2011",
          "title": "Oral Health Management of Patients Prescribed "
                   "Bisphosphonates"}, "manifest id"),
    ])
    def test_a_withdrawn_source_is_detected(self, paper, why):
        bad, reason = e.is_withdrawn(paper)
        assert bad, "%s not caught (%s)" % (paper["pmid"], why)
        assert reason

    @pytest.mark.parametrize("paper", [
        {"pmid": "333", "title": "A perfectly good randomised trial",
         "journal": "Int Endod J",
         "publication_types": ["Randomized Controlled Trial"]},
        # "withdrawn" is ordinary abstract vocabulary. A gate that fires on it
        # would delete real trials — the wrong direction for a gate that may
        # only remove wrong output.
        {"pmid": "555",
         "title": "Outcomes after two participants withdrawn consent",
         "journal": "J Endod"},
        {"pmid": "666",
         "title": "Single visit versus multiple visit endodontic treatment",
         "journal": "Cochrane Database Syst Rev",
         "doi": "10.1002/14651858.CD005296.pub3"},
    ])
    def test_a_live_source_is_not_touched(self, paper):
        bad, reason = e.is_withdrawn(paper)
        assert not bad, "false positive on %s: %s" % (paper["pmid"], reason)

    def test_the_pool_drops_them_and_keeps_the_rest(self):
        pool = [
            {"pmid": "111", "title": "Post-endodontic pain",
             "journal": "Cochrane Database Syst Rev",
             "doi": "10.1002/14651858.CD007997.pub2"},
            {"pmid": "333", "title": "A perfectly good trial",
             "journal": "Int Endod J"},
        ]
        kept = e._exclude_withdrawn(pool)
        assert [p["pmid"] for p in kept] == ["333"]

    def test_an_empty_pool_is_returned_unchanged(self):
        assert e._exclude_withdrawn([]) == []

    def test_the_retrieval_path_actually_calls_it(self):
        """Rule 14. Every test above calls `_exclude_withdrawn` directly, so
        they all pass with nothing calling it — the mutant that removes the
        call from `fetch_papers` survived the first version of this file.

        Asserted on the ORDER too: the exclusion has to run BEFORE
        `_apply_supersession`, or a withdrawn review with a successor is
        demoted-and-badged as merely superseded and stays in the pool.
        """
        import inspect
        body = inspect.getsource(e.fetch_papers)
        assert "_exclude_withdrawn(" in body, (
            "fetch_papers no longer excludes withdrawn sources")
        assert body.index("_exclude_withdrawn(") < body.index("_apply_supersession("), (
            "supersession runs first, so a withdrawn review can be demoted "
            "into the pool instead of dropped")
