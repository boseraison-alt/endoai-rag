"""Item B (2026-09-07) — `[[GL:<id>]]`, the citation form for guidelines.

THE DEFECT, OBSERVED. ~44 guideline rows are citeable under a NON-NUMERIC key —
AAE and ESE position statements, SDCEP, NICE, CGDent: real documents PubMed
does not index, so no accession exists. The prompt asked for `[[PMID:n]]`, so
the model did the only thing it could and wrote

    [[PMID:ACP-ASYMPTOMATIC-EXTRACTION-2016]]

seen in state 2 of probe 3 on 2026-09-06, 1 of 38 citations. That is wrong
twice: the browser's `[[PMID:(\\d+)]]` replacer leaves it RAW on the rendered
page, and it asserts a PubMed accession that does not exist.

Fixtures are real rows from the live library.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import endo_ai as E

GL = "ACP-ASYMPTOMATIC-EXTRACTION-2016"
GL2 = "AAE-VPT-2021"
UNKNOWN = "ACP-NO-SUCH-DOCUMENT-2099"
RETIRED = "COCHRANE-CD005296"          # quarantined by item A


@pytest.fixture(autouse=True)
def _fresh_caches():
    E._reset_gl_render_map()
    E._reset_redirect_map()
    E._KNOWN_SYNTHETIC_KEYS = None
    yield
    E._reset_gl_render_map()
    E._reset_redirect_map()
    E._KNOWN_SYNTHETIC_KEYS = None


class TestTheContextLineTellsTheModelTheKey:

    def test_a_non_numeric_row_is_told_to_cite_as_gl(self):
        line = E.format_paper_context_line(
            {"pmid": GL, "authors": "ACP", "year": 2016, "level_key":
             "guideline", "score": None, "guideline_org": "ACP",
             "guideline_status": "current", "guideline_jurisdiction": "US"})
        assert "cite as [[GL:%s]]" % GL in line, line

    def test_a_numeric_row_is_not(self):
        """A paper keeps `[[PMID:n]]`. Telling the model both forms for one row
        is how the two get mixed."""
        line = E.format_paper_context_line(
            {"pmid": "36512807", "authors": "Mergoni G", "year": 2022,
             "level_key": "cochrane", "score": 73.7})
        assert "[[GL:" not in line, line


class TestTheRenderedCitation:

    def test_it_names_org_title_year_status_and_jurisdiction(self):
        out, n = E.render_gl_citations("The position is clear [[GL:%s]]." % GL2)
        assert n == 1
        assert "AAE" in out
        assert "Vital Pulp Therapy" in out
        assert "2021" in out and "current" in out and "US" in out
        assert "[[GL:" not in out, out

    def test_an_unknown_id_is_left_for_g2_not_rendered(self):
        out, n = E.render_gl_citations("Claim [[GL:%s]]." % UNKNOWN)
        assert n == 0 and UNKNOWN in out

    def test_a_row_with_no_org_still_renders(self):
        """A row with no organisation must not render as ' — title'.

        DRIVEN THROUGH AN EXPLICIT MAPPING since 2026-09-07. The fixture used
        to be AAE-PS-vital-pulp, one of the two grandfathered pre-manifest rows
        that carried no org — and both were retired that day, leaving ZERO
        citeable rows with an empty org. Pointing the test at a live row again
        would mean waiting for the defect to reappear before it could be
        caught; `render_gl_citations` takes its mapping as a parameter, so the
        shape can be exercised directly.
        """
        mapping = {"NO-ORG-2020": {"org": "", "title": "Vital Pulp Therapy",
                                   "year": 2020, "status": "current",
                                   "juris": "", "url": "", "has_text": False}}
        out, n = E.render_gl_citations("X [[GL:NO-ORG-2020]].", mapping)
        assert n == 1
        assert "—" not in out.split("]")[0], (
            "an org-less row rendered a dangling em dash: %r" % out)
        assert "Vital Pulp Therapy" in out
        assert "[GL:NO-ORG-2020 · Vital Pulp Therapy (2020; current)]" in out, out

    def test_a_long_title_is_cut_at_a_word_boundary(self):
        out, _n = E.render_gl_citations("X [[GL:ESE-TRAUMA-2021]].")
        assert "manag…" not in out and "endodontic manag " not in out, out


class TestG2TreatsGlLikeAnyOtherKey:

    def test_a_known_gl_id_survives(self):
        text = "The position says so [[GL:%s]]." % GL2
        out, dropped = E.drop_unresolvable_citations(text)
        assert dropped == [] and "[[GL:%s]]" % GL2 in out

    def test_an_unknown_gl_id_is_dropped_and_counted(self):
        text = "Claim [[GL:%s]]." % UNKNOWN
        out, dropped = E.drop_unresolvable_citations(text)
        assert UNKNOWN in dropped, dropped
        assert UNKNOWN not in out

    def test_a_quarantined_record_is_dropped_with_no_new_path(self):
        """A retired row is absent from `_known_synthetic_keys`, so a GL marker
        naming it is dropped exactly as a PMID marker naming it would be."""
        text = "Claim [[GL:%s]]." % RETIRED
        _out, dropped = E.drop_unresolvable_citations(text)
        assert RETIRED in dropped, dropped


class TestThePmidSlotRewrite:

    def test_a_guideline_id_in_a_pmid_slot_becomes_a_gl_marker(self):
        out, rewrites = E.rewrite_pmid_slot_guidelines(
            "The ACP position [[PMID:%s]]." % GL)
        assert "[[GL:%s]]" % GL in out, out
        assert "[[PMID:%s]]" % GL not in out
        assert rewrites == [GL]

    def test_a_real_pmid_is_untouched(self):
        text = "Healing was comparable [[PMID:27759881]]."
        out, rewrites = E.rewrite_pmid_slot_guidelines(text)
        assert out == text and rewrites == []

    def test_an_unknown_non_numeric_payload_keeps_its_handling(self):
        """Not a known guideline id, so it is NOT promoted to a GL marker —
        it stays a PMID marker and G2 drops it, which is the existing
        behaviour for a citation that names nothing."""
        text = "Claim [[PMID:%s]]." % UNKNOWN
        out, rewrites = E.rewrite_pmid_slot_guidelines(text)
        assert out == text and rewrites == []
        _o, dropped = E.drop_unresolvable_citations(out)
        assert UNKNOWN in dropped


class TestEndToEndThroughTheFinaliser:

    def test_a_pmid_slot_slug_comes_out_rendered_not_raw(self):
        """The whole item, in one assertion: what the model wrote on
        2026-09-06 must reach the page as a readable guideline citation."""
        text = ("## Answer\n\nExtraction should not be the default "
                "[[PMID:%s]] for a restorable tooth.\n" % GL)
        out, _blocks = E.finalise_answer_text(text)
        assert "[[PMID:%s]]" % GL not in out, out
        assert "[[GL:" not in out, "the marker was not rendered: %r" % out
        assert "ACP" in out and "2016" in out, out

    def test_a_gl_marker_counts_as_an_attribution_before_it_is_rendered(self):
        """`_ANY_CITATION_RE` must see GL, or every guideline-cited sentence
        reads as unsourced to the banner and the quarantine pass."""
        assert E._ANY_CITATION_RE.search("Claim [[GL:%s]]." % GL2)

    def test_an_unknown_gl_marker_does_not_survive_the_finaliser(self):
        text = "## Answer\n\nA claim [[GL:%s]] here.\n" % UNKNOWN
        out, _blocks = E.finalise_answer_text(text)
        assert UNKNOWN not in out, out
