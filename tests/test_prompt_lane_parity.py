"""The prompt's heading set must equal the lane set, exactly.

THE PROMPT'S VERSION OF THE BUILDER-AGREEMENT TEST.

Four hand-written copies of the lane set had drifted behind it:

    app.py's tier list                three lanes behind; observational,
                                      guideline and provisional never reached
                                      a Review or Case answer
    eval/run_eval.py's TIER_ORDER     blind to provisional, in every baseline
    loop                              the harness had ever produced
    the synthesis prompt              TWICE — the tier-order line and the set
                                      of EVIDENCE SUMMARY headings

The prompt copies cost the most and were found last. Guidelines were retrieved
on 21 of 29 questions and cited on 1 in 5, because the model was handed a
guideline block, told to write under named headings, told to "skip levels with
no relevant evidence" — and given no heading the block could go under. Naming
the lane in the prompt moved guideline citations from 5 to 8 across five live
Review questions and from 3/5 to 5/5 questions carrying at least one.

So the prompt no longer writes them by hand, and this asserts the agreement:
every lane has a heading, every heading has a lane. A test of the renderer
alone would not do it — that is the shape that let all four copies drift.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import endo_ai as E

ROOT = Path(__file__).parent.parent


def _rendered_prompt():
    """The REAL system prompt, captured from the production call site.

    Rule 14: assert on the expression production evaluates. Rendering
    `render_evidence_headings()` here and checking that would test the helper
    while the prompt kept its own copy — which is precisely the defect.
    """
    captured = {}

    class _Stop(Exception):
        pass

    def _fake(client, **kw):
        captured["system"] = kw.get("system", "")
        raise _Stop()

    real = E._invoke_claude
    E._invoke_claude = _fake
    try:
        ev = {"level1": {"text": "x", "ids": ["1"], "source": "pubmed",
                         "scored": [{"pmid": "1", "score": 70.0, "title": "t",
                                     "abstract": "a", "year": "2024",
                                     "authors": "A", "citations": 1,
                                     "level_key": "level1"}]}}
        try:
            E.ask_clinical_question("q", dict(ev))
        except _Stop:
            pass
    finally:
        E._invoke_claude = real
    return captured.get("system", "")


@pytest.fixture(scope="module")
def prompt():
    return _rendered_prompt()


def _headings(text):
    """The EVIDENCE SUMMARY heading block, as the model receives it."""
    i = text.index("## EVIDENCE SUMMARY")
    j = text.index("## REFERENCES", i)
    return {m.strip() for m in re.findall(r"^\*\*(.+?)\*\*", text[i:j], re.M)}


class TestEveryLaneHasAHeadingAndEveryHeadingHasALane:

    def test_the_sets_are_equal(self, prompt):
        want = {E.lane_label(k) for k in E.prompt_lane_keys()}
        got = _headings(prompt)
        assert got == want, (
            "the prompt's heading set and the lane set disagree.\n"
            "  lanes with no heading: %s\n"
            "  headings with no lane: %s"
            % (sorted(want - got), sorted(got - want)))

    def test_it_is_not_vacuous(self, prompt):
        """Rule 4. If the heading block stops being found, or the lane list
        empties, the assertion above passes while saying nothing."""
        got = _headings(prompt)
        assert len(got) >= 12, "only %d headings parsed — parser broke?" % len(got)
        assert len(E.prompt_lane_keys()) >= 12

    @pytest.mark.parametrize("lane", ["observational", "guideline", "invitro",
                                      "classic", E.PROVISIONAL_KEY])
    def test_the_lanes_that_had_no_heading_now_do(self, prompt, lane):
        """The five that were missing when this was written. Named
        individually so a regression says WHICH one went."""
        assert E.lane_label(lane) in _headings(prompt)


class TestTheSynthesisOrderIsDerivedToo:

    def test_every_rung_appears_in_the_order_line(self, prompt):
        line = [l for l in prompt.splitlines()
                if l.startswith("Synthesise the evidence in tier order")][0]
        for k in E.TIER_ORDER:
            if k in ("guideline", "observational", "invitro"):
                continue
            head = E.lane_label(k).split(" —")[0].split(" /")[0].strip()
            assert head in line, "%s is a rung and is missing from the order" % k

    def test_the_non_rungs_are_deliberately_absent_from_the_order(self, prompt):
        """They get headings and their own guidance, and they are NOT ranked.

        Putting a guideline into a hierarchy the prompt then tells the model to
        obey is the score-as-membership category error in a different costume:
        a guideline is not weak evidence, it is a different kind of fact.
        Observational and in-vitro are excluded for the mirror reason — they
        answer a different question, not a worse version of the same one.
        """
        line = [l for l in prompt.splitlines()
                if l.startswith("Synthesise the evidence in tier order")][0]
        for k in ("guideline", "observational", "invitro"):
            assert E.lane_label(k) not in line

    def test_the_order_line_carries_the_two_rungs_the_handwritten_one_missed(
            self, prompt):
        """`classic` and the legacy `level3` band sit in TIER_ORDER and are
        ranked by build_synthesis_order, and the hand-written line omitted
        both. The derived line is more accurate than what it replaced, which
        is the point of deriving it."""
        line = [l for l in prompt.splitlines()
                if l.startswith("Synthesise the evidence in tier order")][0]
        assert "Classic" in line
        assert "Level III " in line or line.rstrip().endswith("Level III")


class TestNoSecondCopyOfTheLabels:
    """The table holds a NOTE per lane and no labels. A second copy of the
    labels would be the thing it exists to remove."""

    def test_the_note_table_covers_every_lane(self):
        missing = [k for k in E.prompt_lane_keys()
                   if k not in E.LANE_PROMPT_NOTE]
        assert not missing, "lanes with no entry in LANE_PROMPT_NOTE: %s" % missing

    def test_the_note_table_has_no_extra_keys(self):
        extra = [k for k in E.LANE_PROMPT_NOTE
                 if k not in E.prompt_lane_keys()]
        assert not extra, "LANE_PROMPT_NOTE names lanes that do not exist: %s" % extra

    def test_labels_come_from_tier_label(self):
        for k in E.TIER_ORDER:
            assert E.lane_label(k) == E.TIER_LABEL[k]
        assert E.lane_label(E.PROVISIONAL_KEY) == E.PROVISIONAL_LABEL


class TestTheGuidelineWordingThatWonTheABIsPreserved:
    """It is not paraphrased into the table. The A/B measured THAT text."""

    def test_the_block_is_still_verbatim_in_the_prompt(self, prompt):
        for phrase in ("A guideline is not a study and carries no evidence score",
                       "neither\noutranks nor is outranked by the tiers above",
                       "guidelines lag the literature by years by construction"):
            assert phrase in prompt, "the A/B-winning wording changed: %r" % phrase

    def test_the_guideline_lane_carries_no_duplicate_note(self):
        """Its guidance is the block, so a note as well would say it twice."""
        assert E.LANE_PROMPT_NOTE["guideline"] == ""
