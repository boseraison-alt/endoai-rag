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

    # ── THE FLAG SET IS PINNED BY PROPERTY, NOT BY NAME (2026-09-07) ──────
    #
    # This class used to assert `flags == ["ESE-S3-2023"]`. RB then flagged
    # AAE-TREATMENTSTANDARDS-2018 and BES-GOODPRACTICE-2022 — the two records
    # this batch had listed as candidates — and the assertion failed. It failed
    # doing its job: it made an addition visible instead of silent.
    #
    # Rule 39 forbids re-pinning the new list. A name list of three would go
    # stale the same way, and would say nothing about whether the fourth flag
    # is SAFE. What makes a flagship safe is not its name:
    #
    #   * it is CURRENT — a flagship bypasses the similarity floor, so a
    #     superseded one would be force-fed into pools it can no longer earn
    #   * it has a non-empty `scope[]` — scope intersection is the only guard
    #     on that bypass, and a record with no scope would match nothing, or
    #     with a widened rule, everything
    #   * its jurisdiction is UNIQUE among flagships — the design rule behind
    #     the three: one whole-specialty guideline per jurisdiction (ESE/EU,
    #     AAE/US, BES/UK). Two US flagships would mean a US clinician is force-
    #     fed two competing whole-specialty positions on every question in
    #     their scope, which is the divergence display working as noise.
    #
    # Those three properties are what the next addition has to satisfy, and
    # asserting them keeps it exactly as visible as RB's was.

    def test_no_flag_is_written_anywhere_in_the_code(self):
        """RB owns the flag. It comes from the manifest and from nowhere
        else — nothing in the engine may set, infer or default one."""
        import glob
        offenders = []
        for path in (glob.glob("*.py") + glob.glob("scripts/*.py")):
            src = open(path, encoding="utf-8", errors="replace").read()
            for pat in ('"flagship":', "'flagship':", '["flagship"]',
                        "['flagship']", "flagship=True", 'flagship" : '):
                if pat in src:
                    # reading the flag is fine; writing or assigning is not
                    for line in src.splitlines():
                        if pat in line and ("=" in line.split(pat)[0][-3:]
                                            or pat.endswith(":")):
                            if ".get(" in line or "rec.get" in line:
                                continue
                            offenders.append("%s: %s" % (path, line.strip()))
        assert not offenders, (
            "the code appears to write a flagship flag: %s" % offenders)

    def test_every_flagship_is_current(self):
        """A flagship bypasses the similarity floor. A superseded one would be
        force-fed into pools it can no longer earn a place in."""
        import json
        man = json.load(open("data/guidelines_seed.json", encoding="utf-8"))
        bad = [(g["id"], g.get("status"))
               for g in man["guidelines"]
               if g.get("flagship") and (g.get("status") or "") != "current"]
        assert not bad, "flagship records that are not current: %s" % bad

    def test_every_flagship_declares_a_scope(self):
        """Scope intersection is the ONLY guard on the floor bypass."""
        import json
        man = json.load(open("data/guidelines_seed.json", encoding="utf-8"))
        bad = [g["id"] for g in man["guidelines"]
               if g.get("flagship") and not (g.get("scope") or [])]
        assert not bad, "flagship records with no scope[]: %s" % bad

    def test_one_flagship_per_jurisdiction(self):
        """The design rule behind the three: one whole-specialty guideline per
        jurisdiction. Two in the same jurisdiction would force-feed a clinician
        two competing whole-specialty positions on every in-scope question."""
        import json
        from collections import Counter
        man = json.load(open("data/guidelines_seed.json", encoding="utf-8"))
        flags = [g for g in man["guidelines"] if g.get("flagship")]
        assert flags, "no flagship records at all — this test proves nothing"
        by_j = Counter((g.get("jurisdiction") or "").strip() for g in flags)
        dupes = {j: n for j, n in by_j.items() if n > 1}
        assert not dupes, (
            "more than one flagship in a jurisdiction: %s (%s)"
            % (dupes, [(g["id"], g.get("jurisdiction")) for g in flags]))
        assert "" not in by_j, (
            "a flagship with no jurisdiction: %s"
            % [g["id"] for g in flags if not (g.get("jurisdiction") or "").strip()])

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
        # ASSERTED AS A SUPERSET, NOT A COUNT (rule 39). This said
        # `len(gids) == 2`, and RB flagging two more records made it 3 — a
        # count that an authorised manifest change necessarily moves. What the
        # test is named for is that the rule ADDS and never removes.
        assert "AAE-VPT-2021" in gids, "the pre-existing row was removed"
        assert len(gids) >= 2, gids
        assert len(gids) == len(set(gids)), "a row was duplicated: %s" % gids

    def test_the_admitted_row_reaches_the_prompt_not_just_the_pool(self):
        """`_build_evidence_context` renders `block["text"]`, and both builders
        build that text in the tier loop BEFORE admission runs. A row appended
        only to `scored` would be counted in the summary, appear in the
        bibliography, and never be shown to the model."""
        ev = {"guideline": {"ids": [], "scored": [], "text": "",
                            "source": "rag"}}
        out = E.admit_flagship_guidelines(ev, PROBE3)
        text = out["guideline"]["text"]
        assert "37772327" in text, (
            "the flagship row is in the pool but not in the text the model "
            "reads: %r" % text[:200])
        ctx = E._build_evidence_context(out)
        assert "37772327" in ctx, "it does not survive into the evidence context"

    def test_a_block_created_here_declares_a_source(self):
        """Without one the block reads as source None, and a library-pinned
        answer reports its sources as {None, 'rag'}."""
        ev = {}
        out = E.admit_flagship_guidelines(ev, PROBE3)
        assert out.get("guideline", {}).get("source") == "rag"

    def test_the_admitted_row_carries_a_sortable_score(self):
        """`build_synthesis_order` sorts on `p.get("score", 0)`. A literal None
        raises TypeError there; `rag_results_to_scored` coalesces NULL to 0.0
        for exactly this reason, and this row skipped that path."""
        ev = {"guideline": {"ids": [], "scored": [], "text": ""}}
        out = E.admit_flagship_guidelines(ev, PROBE3)
        row = next(p for p in out["guideline"]["scored"]
                   if p.get("guideline_id") == "ESE-S3-2023")
        assert isinstance(row.get("score"), (int, float)), row.get("score")
        E.build_synthesis_order(out)   # must not raise

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
