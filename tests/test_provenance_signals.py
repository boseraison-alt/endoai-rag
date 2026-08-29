"""
Tests for provenance-quality signals: pre-registration, corrections, and
MEDLINE indexing.

The central risk these guard: a systematic review or meta-analysis routinely
quotes the registry IDs of the trials it INCLUDES. Counting those as the
review's own registration would turn a quality marker into a keyword hit. We
therefore take trial registration only from PubMed's structured DataBankList
(populated from the article's own registration) and accept free text only for
the PROSPERO+CRD pairing that identifies a review's own record.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from endo_ai import detect_preregistration, _merge_corrections_and_registries


class TestPreregistrationDesignGating:

    @pytest.mark.parametrize("level", ["cochrane", "level1", "level2"])
    def test_registrable_designs_accept_databank(self, level):
        ok, src = detect_preregistration(level, ["ClinicalTrials.gov:NCT01234567"], "")
        assert ok is True
        assert src == "ClinicalTrials.gov"

    @pytest.mark.parametrize("level", ["level3a", "level3b", "level4", "level5", "classic", ""])
    def test_non_registrable_designs_never_flagged(self, level):
        """Registration is not a norm for case series / narrative reviews /
        lab work — absence must not be treated as a defect, and presence of a
        stray accession must not earn a bonus."""
        assert detect_preregistration(level, ["ISRCTN:12345"], "")[0] is False
        assert detect_preregistration(level, [], "PROSPERO CRD42021234567")[0] is False


class TestNCTInFreeTextIsNotRegistration:

    def test_review_quoting_included_trials_is_not_registered(self):
        abstract = (
            "We searched four databases and included six randomized trials "
            "(NCT01234567, NCT07654321, NCT11112222) in the meta-analysis."
        )
        ok, src = detect_preregistration("level1", [], abstract)
        assert ok is False, "citing other trials' NCT numbers is not self-registration"
        assert src == ""

    def test_bare_nct_without_databank_never_counts(self):
        ok, _ = detect_preregistration("level1", [], "Trial registration: NCT01234567.")
        assert ok is False, "free-text NCT is not accepted; DataBankList is the trial signal"

    def test_prospero_pairing_is_accepted_for_reviews(self):
        ok, src = detect_preregistration(
            "level1", [], "This review was registered in PROSPERO (CRD42020199999)."
        )
        assert ok is True
        assert src == "PROSPERO"

    def test_prospero_word_without_crd_number_rejected(self):
        assert detect_preregistration("level1", [], "We consulted PROSPERO.")[0] is False

    def test_molecular_databanks_are_not_trial_registries(self):
        """DataBankList also carries GenBank/RefSeq/dbSNP sequence accessions —
        those say nothing about prospective registration."""
        for bank in ("RefSeq:NM_000546", "GENBANK:AY123456", "dbSNP:rs334", "GEO:GSE12345"):
            assert detect_preregistration("level1", [bank], "")[0] is False, bank

    def test_trial_registry_recognised_among_molecular_accessions(self):
        ok, src = detect_preregistration(
            "level1", ["RefSeq:NM_000546", "ClinicalTrials.gov:NCT01234567"], ""
        )
        assert ok is True
        assert src == "ClinicalTrials.gov"

    def test_databank_wins_over_free_text(self):
        ok, src = detect_preregistration(
            "level1", ["ISRCTN:ISRCTN12345678"], "Also mentions NCT01234567 somewhere."
        )
        assert ok is True
        assert src == "ISRCTN"


class TestCorrectionsParsing:

    XML = """<?xml version="1.0"?>
    <PubmedArticleSet>
      <PubmedArticle>
        <MedlineCitation><PMID>11111111</PMID>
          <CommentsCorrectionsList>
            <CommentsCorrections RefType="ErratumIn"><PMID>99999999</PMID></CommentsCorrections>
          </CommentsCorrectionsList>
        </MedlineCitation>
      </PubmedArticle>
      <PubmedArticle>
        <MedlineCitation><PMID>22222222</PMID>
          <CommentsCorrectionsList>
            <CommentsCorrections RefType="ErratumFor"><PMID>11111111</PMID></CommentsCorrections>
          </CommentsCorrectionsList>
        </MedlineCitation>
      </PubmedArticle>
      <PubmedArticle>
        <MedlineCitation><PMID>33333333</PMID>
          <Article><DataBankList>
            <DataBank><DataBankName>ClinicalTrials.gov</DataBankName>
              <AccessionNumberList><AccessionNumber>NCT01234567</AccessionNumber></AccessionNumberList>
            </DataBank>
          </DataBankList></Article>
        </MedlineCitation>
      </PubmedArticle>
    </PubmedArticleSet>"""

    def _parse(self, monkeypatch):
        meta = {p: {"has_erratum": False, "has_retraction": False, "registry_ids": []}
                for p in ("11111111", "22222222", "33333333")}

        class FakeResp:
            status_code = 200
            text = self.XML

        import endo_ai
        monkeypatch.setattr(endo_ai.requests, "get", lambda *a, **k: FakeResp())
        _merge_corrections_and_registries(list(meta), meta)
        return meta

    def test_erratum_in_marks_the_corrected_paper(self, monkeypatch):
        meta = self._parse(monkeypatch)
        assert meta["11111111"]["has_erratum"] is True

    def test_erratum_for_does_not_mark_the_notice_itself(self, monkeypatch):
        """A paper that IS the correction notice is not itself defective."""
        meta = self._parse(monkeypatch)
        assert meta["22222222"]["has_erratum"] is False

    def test_databank_accession_captured(self, monkeypatch):
        meta = self._parse(monkeypatch)
        assert meta["33333333"]["registry_ids"] == ["ClinicalTrials.gov:NCT01234567"]

    def test_empty_ids_is_a_noop(self):
        meta = {}
        _merge_corrections_and_registries([], meta)
        assert meta == {}
