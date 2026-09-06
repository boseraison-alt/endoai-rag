"""Item C (2026-09-07) — the guideline block admits, it does not shortlist.

TWO RULES.

1. FLOOR, NOT TOP-K. Every other per-tier quota bounds COMPETITION inside a
   rung: eighteen Level I papers compete to support the same claim. Guidelines
   do not compete. Two bodies holding different positions on one question are
   both current and both true, and showing one of them is the divergence
   failure A49 exists to remove. Measured before changing: on 8 of 32
   questions a cap of 4 cut an eligible guideline, 19 rows in total.

2. FLAGSHIP. ESE-S3-2023 is the only `flagship: true` record. Its embedding
   covers the whole field, so on any specific question it loses to any narrow
   document and sits on the wrong side of the floor by a hair. Measured, three
   runs of probe 3 minutes apart: absent from the KNN; similarity 0.6089 rank
   4; similarity 0.5748 rank 5. The floor is 0.55.

   Scope intersection is the guard that keeps this from being a floor
   weakening: a flagship is admitted only where the question hits its declared
   `scope[]`, and only manifest-flagged current records are reachable at all.

THE TWO BUILDERS MUST AGREE. `endo_ai.build_evidence_base` and app.py's
library and differential routes all assemble a guideline block, and before
this item they disagreed — quota 4 against 25, and app.py called neither
`collapse_guideline_copies` nor `admit_flagship_guidelines`.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import endo_ai as E

PROBE3 = ("Mature molar with a failed root canal retreatment. The patient "
          "asks for extraction and an implant. How should this be decided?")


class TestTheBlockIsNotATopK:

    def test_the_guideline_quota_is_the_block_cap_in_every_mode(self):
        for mode in ("review", "learn", "case"):
            assert E._tier_cap(mode, "guideline") == E.GUIDELINE_BLOCK_CAP, mode

    def test_it_is_not_four(self):
        """The specific number that cut 19 eligible guidelines across 8 of the
        32 measured questions."""
        assert E.GUIDELINE_BLOCK_CAP > 4

    def test_both_builders_agree_on_the_cap(self):
        """A question answered by the library route and by the live route must
        see the same number of specialty positions."""
        import app
        assert (E._tier_cap("review", "guideline")
                == app.RELEVANCE_GATE["max_per_tier"]), (
            "live cap %s vs library cap %s"
            % (E._tier_cap("review", "guideline"),
               app.RELEVANCE_GATE["max_per_tier"]))

    def test_every_route_that_builds_a_block_also_dedups_and_admits(self):
        """app.py called `flag_superseded_by_review` at three sites and neither
        of the other two helpers, so a co-published guideline was counted twice
        on the library route and a flagship was never admitted there."""
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "app.py"), encoding="utf-8").read()
        n_super = src.count("flag_superseded_by_review(evidence, question=")
        n_super += src.count("flag_superseded_by_review(evidence, "
                             "question=case_description)")
        assert src.count("collapse_guideline_copies(evidence)") >= 3
        assert src.count("admit_flagship_guidelines(evidence,") >= 3


class TestTheFlagshipRule:

    def test_ese_s3_is_the_only_flagship_and_this_test_owns_no_flags(self):
        """RB owns the flag. Nothing in the code adds one, and if a second
        record gains one this test says so rather than silently widening the
        rule's blast radius."""
        import json
        man = json.load(open("data/guidelines_seed.json", encoding="utf-8"))
        flags = sorted(g["id"] for g in man["guidelines"] if g.get("flagship"))
        assert flags == ["ESE-S3-2023"], flags

    def test_a_scope_matching_question_selects_it(self):
        assert "ESE-S3-2023" in E.flagship_guidelines_for(PROBE3), (
            "probe 3 names retreatment, which is in ESE-S3-2023's scope")

    def test_an_out_of_scope_question_does_not(self):
        """The guard. A flagship must not appear on a question outside its
        subject — otherwise this is a floor weakening with extra steps."""
        assert E.flagship_guidelines_for(
            "What is the best material for a denture base?") == []
        assert E.flagship_guidelines_for("") == []

    def test_it_is_admitted_even_with_an_empty_block(self):
        ev = {"guideline": {"ids": [], "scored": []}}
        out = E.admit_flagship_guidelines(ev, PROBE3)
        gids = [p.get("guideline_id") for p in out["guideline"]["scored"]]
        assert "ESE-S3-2023" in gids, gids

    def test_it_is_not_admitted_twice(self):
        """Additive means additive. Running it on a block that already holds
        the record must not duplicate it."""
        ev = {"guideline": {"ids": ["37772327"],
                            "scored": [{"pmid": "37772327",
                                        "guideline_id": "ESE-S3-2023",
                                        "score": None}]}}
        out = E.admit_flagship_guidelines(ev, PROBE3)
        gids = [p.get("guideline_id") for p in out["guideline"]["scored"]]
        assert gids.count("ESE-S3-2023") == 1, gids

    def test_it_removes_nothing(self):
        ev = {"guideline": {"ids": ["AAE-VPT-2021"],
                            "scored": [{"pmid": "AAE-VPT-2021",
                                        "guideline_id": "AAE-VPT-2021",
                                        "score": None}]}}
        out = E.admit_flagship_guidelines(ev, PROBE3)
        gids = [p.get("guideline_id") for p in out["guideline"]["scored"]]
        assert "AAE-VPT-2021" in gids
        assert len(gids) == 2

    def test_the_admitted_row_is_marked_as_a_flagship_admission(self):
        """It did not earn its place on similarity, and the row says so rather
        than looking like an ordinary hit."""
        ev = {"guideline": {"ids": [], "scored": []}}
        out = E.admit_flagship_guidelines(ev, PROBE3)
        row = next(p for p in out["guideline"]["scored"]
                   if p.get("guideline_id") == "ESE-S3-2023")
        assert row.get("admitted_as") == "flagship"
        assert row.get("similarity") is None


class TestTheSpecialtySectionInstruction:

    def test_the_prompt_forbids_merging_two_specialties(self):
        block = E.GUIDELINE_PROMPT_BLOCK
        assert "SEPARATELY" in block or "separately" in block
        assert "guideline bodies agree" in block, (
            "the prompt must name the phrase it is forbidding")

    def test_the_prompt_forbids_stating_a_pointer_record_s_position(self):
        block = E.GUIDELINE_PROMPT_BLOCK
        assert "position not quoted" in block
        assert "pointer record" in block

    def test_it_is_derived_not_hand_written_twice(self):
        """The heading itself comes from `render_evidence_headings()`, so the
        prompt-parity test governs it. This asserts the instruction lives in
        the one block and not as a second hand-written heading."""
        assert E.GUIDELINE_PROMPT_BLOCK.count(
            "Specialty Guidelines & Position Statements") == 1
