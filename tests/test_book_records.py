"""
Book records (WORKLIST 1.3) and the retracted terminal tier (1.6).

PubmedBookArticle records (StatPearls chapters) are narrative reference texts.
The provenance merge loop iterated only PubmedArticle, so books got NO
provenance at all — no pubtypes, no MEDLINE status, no COI — and kept the tier
of whatever search retrieved them: three sat at Level I scoring 67.

The XML fixture is a real efetch response for PMID 30725797 ("Anatomy, Head
and Neck, Dental Pulp", StatPearls), captured live and pruned.
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from endo_ai import (_merge_corrections_and_registries, format_provenance_badges,
                     format_paper_context_line, LEVEL_SCORES, TIER_ORDER,
                     TIER_LABEL)

FIXTURE = Path(__file__).parent / "fixtures" / "pubmed_xml" / "statpearls_30725797.xml"


class TestBookRecordParsing:

    def _run_merge(self):
        meta = {"30725797": {"has_erratum": False, "has_retraction": False,
                             "registry_ids": [], "superseded_by": "",
                             "medline_indexed": True}}
        fake = MagicMock(status_code=200, text=FIXTURE.read_text(encoding="utf-8"))
        with patch("endo_ai.requests.get", return_value=fake):
            _merge_corrections_and_registries(["30725797"], meta)
        return meta["30725797"]

    def test_book_is_detected_and_titled(self):
        entry = self._run_merge()
        assert entry["is_book"] is True
        assert entry["book_title"] == "StatPearls"

    def test_book_is_not_medline_indexed(self):
        """Books are not MEDLINE journal articles; leaving the default True
        would hand them a small credibility premium they haven't earned."""
        assert self._run_merge()["medline_indexed"] is False


class TestReferenceTextBadge:

    def test_badge_from_the_live_field(self):
        badge = format_provenance_badges({"pmid": "1", "is_reference_text": True})
        assert "REFERENCE TEXT" in badge

    def test_badge_from_the_backfilled_journal(self):
        """Library rows predate the field; the migration backfills journal to
        the book title, and the badge triggers off that."""
        badge = format_provenance_badges({"pmid": "30725797", "journal": "StatPearls"})
        assert "REFERENCE TEXT" in badge

    def test_badge_reaches_the_shared_context_line(self):
        line = format_paper_context_line(
            {"pmid": "30725797", "journal": "StatPearls", "year": 2019,
             "score": 39.8, "authors": "X", "citations": 0})
        assert "REFERENCE TEXT" in line

    def test_ordinary_journal_gets_no_badge(self):
        assert "REFERENCE TEXT" not in format_provenance_badges(
            {"pmid": "1", "journal": "International Endodontic Journal"})


class TestRetractedTerminalTier:

    def test_retracted_scores_zero_on_the_design_axis(self):
        assert LEVEL_SCORES["retracted"] == 0
        assert LEVEL_SCORES["retracted"] < min(
            v for k, v in LEVEL_SCORES.items() if k != "retracted")

    def test_retracted_is_not_in_tier_order(self):
        """In this codebase, absence from TIER_ORDER is the mechanism for
        "never rendered to Claude" — _build_evidence_context iterates it.
        Putting 'retracted' IN the list would do the opposite of the intent."""
        assert "retracted" not in TIER_ORDER

    def test_retracted_has_a_display_label(self):
        """Admin and bibliography views still need to name it honestly."""
        assert "retracted" in TIER_LABEL
        assert "excluded" in TIER_LABEL["retracted"].lower()
