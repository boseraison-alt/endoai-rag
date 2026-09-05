"""Item 4 — a guideline that REPLACES another says so, on the successor.

THE DECISION THIS IMPLEMENTS (D2). Superseded guidelines stay EXCLUDED from
evidence. A clinician shown the 2015 AAE/AAOMR CBCT statement as current is a
clinical hazard, and all four successors are in the library, so exclusion
delivers the CURRENT document — which achieves the clinical intent more
strongly than a cite-with-notice path would.

But exclusion alone never tells a clinician who knows the old statement that it
was replaced; it just silently fails to mention it. So the notice goes on the
SUCCESSOR, which is the record that actually renders.

Additive and render-only: no retrieval changes, no score changes, no row
changes. The notice is read from `supersedes[]` in the verified seed manifest.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import endo_ai as e


class TestTheNoticeNamesWhatWasReplaced:

    def test_a_single_predecessor_named_from_its_own_seed_record(self):
        """ESE-QG-2006 IS a seed record, so its org and year are read from it
        rather than parsed out of an identifier."""
        assert (e._guideline_supersession_notice("ESE-S3-2023")
                == "Replaces ESE 2006 statement.")

    def test_the_cbct_hazard_is_the_one_this_exists_for(self):
        """AAE-AAOMR-CBCT-2015 is heavily cited, still reachable, replaced in
        2025. The clinician who knows it needs to learn that from the 2025
        record, because the 2015 one is excluded and says nothing."""
        assert (e._guideline_supersession_notice("AAE-AAOMR-CBCT-2025")
                == "Replaces AAE 2015 statement.")

    def test_several_predecessors_are_all_named(self):
        assert (e._guideline_supersession_notice("AAOMS-MRONJ-2022")
                == "Replaces AAOMS 2014, AAOMS 2009 and AAOMS 2007 statements.")

    def test_a_predecessor_absent_from_the_seed_is_read_off_its_identifier(self):
        """AAE-MICROSCOPES-2012 is named by the manifest but is not itself a
        record. The id scheme is ORG-TOPIC-YEAR and reading it is reading
        DATA — it is not the same act as inventing an organisation."""
        assert (e._guideline_supersession_notice("AAE-MICROSCOPES-2020")
                == "Replaces AAE 2012 statement.")

    def test_an_unparseable_identifier_is_emitted_as_given_and_loses_the_noun(self):
        """COCHRANE-CD005296 supersedes earlier VERSIONS of the same review.
        They are not statements, and it is stored at level_key `guideline` so
        it does reach this line. Emitting the identifier verbatim is the
        honest option; calling it a statement is a small false claim in the
        one sentence whose whole job is to describe a document accurately."""
        out = e._guideline_supersession_notice("COCHRANE-CD005296")
        assert out == "Replaces CD005296.pub2 (2007) and CD005296.pub3 (2016)."
        assert "statement" not in out

    def test_the_seed_record_beats_the_identifier_when_they_disagree(self,
                                                                     monkeypatch):
        """Precedence: what the manifest SAYS a document is outranks what its
        identifier implies.

        Today's data cannot distinguish this. All five superseded documents
        that are themselves seed records have an `org` equal to their id's
        prefix, so a mutation deleting the seed-lookup branch SURVIVED every
        other test in this class. That is a real gap, not a cosmetic one: the
        id scheme is a naming convention and `org` is the field of record, and
        a joint statement (id prefix "AAE", org "AAE/AAOMR") would be
        attributed to the wrong body.

        The manifest is stubbed here deliberately, and only for the ordering
        rule — the assertions above all run against the real seed.
        """
        monkeypatch.setattr(e, "_MANIFEST_BY_ID", {
            "NEW-THING-2025": {"id": "NEW-THING-2025", "org": "NEW",
                               "year": 2025, "supersedes": ["AAE-CBCT-2015"]},
            "AAE-CBCT-2015": {"id": "AAE-CBCT-2015", "org": "AAE/AAOMR",
                              "year": 2015},
        })
        assert (e._guideline_supersession_notice("NEW-THING-2025")
                == "Replaces AAE/AAOMR 2015 statement.")

    def test_a_guideline_that_replaces_nothing_says_nothing(self):
        assert e._guideline_supersession_notice("ESE-QG-2006") == ""

    def test_an_unknown_id_says_nothing(self):
        assert e._guideline_supersession_notice("NOT-A-RECORD") == ""
        assert e._guideline_supersession_notice("") == ""


class TestItReachesTheRenderedLine:
    """Rule 14 — the helper being right is not the property that matters.
    A correct helper with a caller that never calls it is the exact shape of
    the defect this whole batch has been chasing."""

    def _line(self, **over):
        p = {"pmid": "41412684", "authors": "AAE/AAOMR", "year": "2025",
             "citations": 3, "level_key": "guideline", "score": None,
             "guideline_id": "AAE-AAOMR-CBCT-2025", "guideline_org": "AAE",
             "guideline_status": "current", "guideline_jurisdiction": "US"}
        p.update(over)
        return e.format_paper_context_line(p)

    def test_the_notice_is_in_the_line_claude_reads(self):
        assert "Replaces AAE 2015 statement." in self._line()

    def test_it_does_not_replace_the_identity_detail(self):
        """Additive. The org/status/jurisdiction block must survive it."""
        line = self._line()
        assert "(AAE, current, US)" in line
        assert "NOT SCORED" in line

    def test_an_ordinary_paper_gets_no_notice(self):
        line = self._line(level_key="level1", score=72.0, guideline_id="")
        assert "Replaces" not in line
        assert "Evidence Score: 72.0/100" in line

    def test_a_guideline_replacing_nothing_gets_no_notice(self):
        line = self._line(guideline_id="ESE-QG-2006")
        assert "Replaces" not in line
        assert "NOT SCORED" in line


class TestItChangesNothingElse:

    def test_the_notice_is_render_only(self):
        """It must not touch score, tier or retrieval. Rendering a paper twice
        must give the same line — rule 18, since the renderer is applied at
        read time on the archive routes."""
        p = {"pmid": "1", "authors": "A", "year": "2025", "citations": 0,
             "level_key": "guideline", "score": None,
             "guideline_id": "AAE-AAOMR-CBCT-2025", "guideline_org": "AAE",
             "guideline_status": "current", "guideline_jurisdiction": "US"}
        before = dict(p)
        first = e.format_paper_context_line(p)
        second = e.format_paper_context_line(p)
        assert first == second
        assert p == before, "the renderer mutated the paper"

    def test_superseded_guidelines_are_still_excluded_from_retrieval(self):
        """D2 unchanged: the notice is on the successor INSTEAD of citing the
        predecessor, not as well as. This pins that item 4 did not quietly
        become the cite-with-notice path D2 rejected."""
        src = (Path(__file__).parent.parent / "rag.py").read_text(encoding="utf-8")
        # The real form, read off rag.py rather than guessed at — standing
        # rule 17. My first version of this assertion invented the spacing and
        # failed against correct code.
        n = src.count("AND COALESCE(superseded_by, '') = ''")
        assert n >= 2, (
            f"expected both retrieval queries to exclude superseded rows, "
            f"found {n}")
