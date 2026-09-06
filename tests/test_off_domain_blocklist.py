"""Item G (2026-09-07) — the off-domain blocklist.

TWO DOCUMENTS REACH ENDODONTIC POOLS THROUGH A CORRECT FILTER MATCH.

  29729847  SIOPE paediatric brain-tumour craniospinal radiotherapy. Its
            abstract says "no need to include sacral root canals in the spinal
            CTV". `ENDO_DOMAIN_FILTER` carries `"root canal"[tiab]`, and a
            spinal nerve root canal is a root canal. The filter is right; the
            document addresses no oral or dental care.
  29268916  Society for Vascular Surgery, abdominal aortic aneurysm. NOT
            off-domain by the abstract test — its abstract carries a genuine
            recommendation about antibiotic prophylaxis before dental
            procedures — and off-topic for every endodontic question measured.

A NAMED LIST RATHER THAN A FILTER CHANGE, because `ENDO_DOMAIN_FILTER` is
shared by every lane and narrowing it would change what the study lanes
retrieve. That needs its own A/B.

THIS STRENGTHENS A GATE. Every code path here only removes rows.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import endo_ai as E

SIOPE = "29729847"
SVS = "29268916"
AHA = "17446442"


@pytest.fixture(autouse=True)
def _fresh():
    E._reset_off_domain_blocklist()
    yield
    E._reset_off_domain_blocklist()


class TestTheListItself:

    def test_it_holds_exactly_the_two_seeded_documents(self):
        b = E.off_domain_blocklist()
        assert sorted(b) == sorted([SIOPE, SVS]), sorted(b)

    def test_every_entry_is_signed_and_reasoned(self):
        """A blocklist nobody signed is a filter nobody can audit."""
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "data", "off_domain_blocklist.json")
        data = json.load(open(path, encoding="utf-8"))
        assert data["entries"]
        for e in data["entries"]:
            assert e.get("pmid") and str(e["pmid"]).isdigit()
            assert len(e.get("reason", "")) > 40, e
            assert e.get("judged") and e.get("judged_by"), e

    def test_the_aha_endocarditis_guideline_is_not_listed(self):
        """The document the 2026-09-06 judge wrongly convicted and then
        correctly exonerated. Prophylaxis before dental procedures is its whole
        subject, and blocklisting it would re-make the error by hand."""
        assert AHA not in E.off_domain_blocklist()


class TestItOnlyEverRemoves:

    def test_a_blocklisted_row_is_dropped(self):
        pool = [{"pmid": SIOPE}, {"pmid": "27759881"}, {"pmid": SVS}]
        kept = E.drop_off_domain(pool, "guideline")
        assert [p["pmid"] for p in kept] == ["27759881"]

    def test_an_unlisted_row_is_untouched(self):
        pool = [{"pmid": "27759881"}, {"pmid": "37772327"}]
        kept = E.drop_off_domain(pool, "level1")
        assert len(kept) == 2

    def test_it_never_adds_a_row(self):
        """The gate-strengthening property, asserted rather than assumed."""
        for pool in ([], [{"pmid": "1"}], [{"pmid": SIOPE}]):
            assert len(E.drop_off_domain(list(pool), "x")) <= len(pool)

    def test_an_empty_pool_survives(self):
        assert E.drop_off_domain([], "guideline") == []

    def test_a_missing_list_fails_open(self, monkeypatch):
        """An unreadable blocklist must not empty every pool — same failure
        direction as `_known_synthetic_keys`."""
        monkeypatch.setattr(E, "_OFF_DOMAIN_BLOCKLIST", {})
        pool = [{"pmid": SIOPE}, {"pmid": "27759881"}]
        assert len(E.drop_off_domain(pool, "guideline")) == 2

    def test_it_applies_to_every_lane_not_just_guidelines(self):
        """SIOPE matches `"root canal"[tiab]`, which every lane's query
        carries. A guideline-only guard would leave it reachable everywhere
        else."""
        for lane in ("level1", "level2", "level5", "observational",
                     "guideline"):
            kept = E.drop_off_domain([{"pmid": SIOPE}], lane)
            assert kept == [], lane


class TestBothBuildersApplyIt:

    def test_the_live_builder_filters_before_the_quality_cut(self):
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "endo_ai.py"), encoding="utf-8").read()
        i = src.index("scored_papers = drop_off_domain(scored_papers, level_key)")
        j = src.index("_apply_quality_threshold(scored_papers", i)
        assert j > i, "the blocklist must run before the quality cut"

    def test_the_library_builder_filters_its_candidate_set_and_its_buckets(self):
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "app.py"), encoding="utf-8").read()
        assert "drop_off_domain(rag_results, 'library')" in src, (
            "the library candidate set is not filtered, so a blocklisted row "
            "can still help a question pass the coverage gate")
        assert "drop_off_domain(bucket, tier)" in src
