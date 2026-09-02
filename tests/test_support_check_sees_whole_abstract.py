"""The citation-support judge reads the whole abstract, and says what it skipped.

`_SUPPORT_ABSTRACT_CHARS = 1200` was harmless when it was written: 57% of the
library's abstracts were themselves cut at 1,000 or 1,200 characters at
ingest, so there was nothing past the cap to withhold. `grounding-v1` healed
those rows to a mean of 1,631 characters and left the cap alone, which turned
a no-op into the last truncation in the pipeline — sitting on the guardrail.

The measurement that found it: hand-judging all 37 Deep Learning citation
flags. 36 of 37 cite a paper whose stored abstract is longer than 1,200
characters, and 17 of the 37 are claims whose supporting sentence is verbatim
in the withheld tail. A structured abstract puts CONCLUSIONS last; the
Cochrane review at PMID 27759881 is 6,724 characters and the judge was shown
its search strategy.

Two properties, both of which fail silently:

  * the judge must be given the WHOLE abstract, and the payload must be
    bounded by batching rather than by cutting — a claim split away from its
    evidence is the bug, not the size of the request;
  * `_SUPPORT_MAX_PAIRS` caps how many pairs are checked at all, and a
    curriculum module routinely exceeds it. "Each of the 30 cited claims was
    checked" is true and misleading when there were 45.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai


class FakeUsage:
    input_tokens = 100
    output_tokens = 10


class FakeResponse:
    def __init__(self, text):
        self.content = [type("B", (), {"text": text})()]
        self.usage = FakeUsage()


@pytest.fixture
def judge(monkeypatch, tmp_path):
    """Capture every payload sent to the judge; answer 'supports' to all."""
    sent = []

    def _fake(client_, function_name="", **kwargs):
        body = kwargs["messages"][0]["content"]
        start = body.index("ITEMS (JSON):\n") + len("ITEMS (JSON):\n")
        end = body.index("\n\nReturn ONLY a JSON array")
        items = json.loads(body[start:end])
        sent.append(items)
        return FakeResponse(json.dumps([{"i": it["i"], "verdict": "supports"}
                                        for it in items]))

    monkeypatch.setattr(endo_ai, "_invoke_claude", _fake)
    monkeypatch.setattr(endo_ai, "log_llm_call", lambda *a, **k: 0.001)
    monkeypatch.setattr(endo_ai, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(endo_ai, "_EVMAP_LOG_PATH", str(tmp_path / "evmap.jsonl"))
    return sent


def _answer(n_claims, pmid_of=lambda i: str(1000 + i)):
    body = "\n\n".join(
        f"Claim number {i} states a finding about root canal irrigation "
        f"[[PMID:{pmid_of(i)}]]." for i in range(n_claims))
    return f"## EVIDENCE SUMMARY\n\n{body}\n"


def _abstracts(monkeypatch, mapping):
    import rag
    monkeypatch.setattr(rag, "get_cached_abstracts_bulk",
                        lambda pmids: {p: {"abstract": mapping.get(p, "")}
                                       for p in pmids if p in mapping})


class TestTheWholeAbstractReachesTheJudge:

    def test_a_long_abstract_is_not_cut(self, judge, monkeypatch):
        tail = "CONCLUSIONS: laser activation reduced pain at 24 hours."
        long_abstract = ("BACKGROUND: " + ("filler sentence. " * 400) + tail)
        assert len(long_abstract) > 6000
        _abstracts(monkeypatch, {"1000": long_abstract})

        endo_ai.verify_citation_support(_answer(1), {})
        sent_abstract = judge[0][0]["abstract"]
        assert sent_abstract == long_abstract
        assert tail in sent_abstract, \
            "the conclusion never reached the judge"

    def test_the_1200_char_excerpt_is_gone(self, judge, monkeypatch):
        """The specific regression: a 6,724-character Cochrane abstract whose
        LLLT sentence sits 5,000 characters in."""
        _abstracts(monkeypatch, {"1000": "A" * 3000 + "THE FINDING"})
        endo_ai.verify_citation_support(_answer(1), {})
        assert "THE FINDING" in judge[0][0]["abstract"]

    def test_the_prompt_tells_the_judge_where_findings_live(self, monkeypatch,
                                                            judge):
        captured = {}

        def _fake(client_, function_name="", **kwargs):
            captured["body"] = kwargs["messages"][0]["content"]
            return FakeResponse("[]")

        monkeypatch.setattr(endo_ai, "_invoke_claude", _fake)
        _abstracts(monkeypatch, {"1000": "x" * 500})
        endo_ai.verify_citation_support(_answer(1), {})
        assert "RESULTS and CONCLUSIONS" in captured["body"]


class TestThePayloadIsBoundedByBatchingNotByCutting:

    def test_many_long_abstracts_are_split_across_requests(self, judge,
                                                           monkeypatch):
        big = "Z" * 20000
        _abstracts(monkeypatch, {str(1000 + i): big for i in range(6)})
        endo_ai.verify_citation_support(_answer(6), {})
        assert len(judge) > 1, "one request carried 120,000 characters"
        for batch in judge:
            chars = sum(len(it["abstract"]) for it in batch)
            assert chars <= endo_ai._SUPPORT_BATCH_CHARS or len(batch) == 1

    def test_no_item_is_split_across_two_requests(self, judge, monkeypatch):
        """An item split in half is a claim judged against half its evidence,
        which is the bug this change removes — reintroducing it through the
        batcher would be the same defect with a new cause."""
        big = "Z" * 20000
        _abstracts(monkeypatch, {str(1000 + i): big for i in range(6)})
        endo_ai.verify_citation_support(_answer(6), {})
        seen = [it["i"] for batch in judge for it in batch]
        assert len(seen) == len(set(seen))
        for batch in judge:
            for it in batch:
                assert len(it["abstract"]) == len(big)

    def test_an_oversized_single_item_still_goes_whole(self, judge, monkeypatch):
        """One abstract larger than the whole budget gets its own request
        rather than being truncated to fit."""
        huge = "Q" * (endo_ai._SUPPORT_BATCH_CHARS + 5000)
        _abstracts(monkeypatch, {"1000": huge})
        endo_ai.verify_citation_support(_answer(1), {})
        assert len(judge) == 1
        assert len(judge[0][0]["abstract"]) == len(huge)

    def test_verdicts_from_every_batch_are_merged(self, monkeypatch, tmp_path):
        big = "Z" * 25000
        _abstracts(monkeypatch, {str(1000 + i): big for i in range(6)})

        def _fake(client_, function_name="", **kwargs):
            body = kwargs["messages"][0]["content"]
            start = body.index("ITEMS (JSON):\n") + len("ITEMS (JSON):\n")
            items = json.loads(body[start:body.index("\n\nReturn ONLY")])
            return FakeResponse(json.dumps(
                [{"i": it["i"], "verdict": "not_supported"} for it in items]))

        monkeypatch.setattr(endo_ai, "_invoke_claude", _fake)
        monkeypatch.setattr(endo_ai, "log_llm_call", lambda *a, **k: 0.001)
        monkeypatch.setattr(endo_ai, "_get_api_key", lambda: "k")
        monkeypatch.setattr(endo_ai, "_EVMAP_LOG_PATH",
                            str(tmp_path / "evmap.jsonl"))
        out = endo_ai.verify_citation_support(_answer(6), {})
        assert out["checked"] == 6
        assert len(out["flags"]) == 6, \
            "a later batch's verdicts were dropped"

    def test_cost_is_summed_across_requests(self, judge, monkeypatch):
        big = "Z" * 25000
        _abstracts(monkeypatch, {str(1000 + i): big for i in range(6)})
        out = endo_ai.verify_citation_support(_answer(6), {})
        assert out["cost"] == pytest.approx(0.001 * len(judge))


class TestTheAnswerSaysWhatWasNotChecked:
    """The cap is GONE (`dl-quality-v1` Item 2). It was 30 and it bound on
    three of four modules in both stored curricula — 117 of 130 claims checked
    on the anesthesia run, 120 of 133 on the laser run, 13 unchecked in each,
    and the skipped ones were the LAST in each module, which is where the
    clinical-application protocols live.

    The reporting stays, because `checked` can still fall short of
    `total_pairs` for a legitimate reason: a cited paper whose abstract is not
    in the cache is skipped rather than judged against nothing."""

    def test_the_cap_is_off(self):
        assert endo_ai._SUPPORT_MAX_PAIRS is None, (
            "a pair cap is back. It binds on exactly the answers that most "
            "need checking — see the constant's own comment.")

    def test_every_claim_is_checked_now(self, judge, monkeypatch):
        n = 42
        _abstracts(monkeypatch, {str(1000 + i): "abstract text " * 30
                                 for i in range(n)})
        out = endo_ai.verify_citation_support(_answer(n), {})
        assert out["total_pairs"] == n
        assert out["checked"] == n, (
            f"only {out['checked']} of {n} claims were checked")

    def test_a_cap_still_works_when_a_replay_sets_one(self, judge, monkeypatch):
        """`scripts/measure_claim_units.py` holds it fixed so a before/after
        replay stays comparable. Production leaves it None."""
        monkeypatch.setattr(endo_ai, "_SUPPORT_MAX_PAIRS", 10)
        _abstracts(monkeypatch, {str(1000 + i): "abstract text " * 30
                                 for i in range(25)})
        out = endo_ai.verify_citation_support(_answer(25), {})
        assert out["total_pairs"] == 25
        assert out["checked"] == 10

    def test_a_missing_abstract_still_shortens_the_checked_count(
            self, judge, monkeypatch):
        """The reason the footer survives the cap's removal."""
        _abstracts(monkeypatch, {str(1000 + i): "abstract text " * 30
                                 for i in range(8)})     # 8 of 12 cached
        out = endo_ai.verify_citation_support(_answer(12), {})
        assert out["total_pairs"] == 12
        assert out["checked"] < 12

    def test_the_rendered_block_states_the_unchecked_remainder(self):
        rendered = endo_ai._append_support_warnings("ANSWER", {
            "flags": [], "checked": 30, "total_pairs": 45,
            "status": "verified", "cost": 0.0})
        assert "15 further cited claim(s) were NOT checked" in rendered

    def test_a_flagged_block_states_it_too(self):
        rendered = endo_ai._append_support_warnings("ANSWER", {
            "flags": [{"pmid": "1", "claim": "c"}], "checked": 30,
            "total_pairs": 45, "status": "verified", "cost": 0.0})
        assert "NOT checked" in rendered

    def test_nothing_is_added_when_the_cap_did_not_bind(self):
        rendered = endo_ai._append_support_warnings("ANSWER", {
            "flags": [], "checked": 12, "total_pairs": 12,
            "status": "verified", "cost": 0.0})
        assert "NOT checked" not in rendered

    def test_a_result_without_total_pairs_is_not_misreported(self):
        """Stored results and `_support_not_run` predate the field. Absent, it
        must read as "the cap did not bind", never as "everything was skipped"."""
        rendered = endo_ai._append_support_warnings("ANSWER", {
            "flags": [], "checked": 9, "status": "verified", "cost": 0.0})
        assert "NOT checked" not in rendered


class TestTheAuditRecordStaysOneRowPerCheck:
    def test_one_record_however_many_requests(self, judge, monkeypatch,
                                              tmp_path):
        path = tmp_path / "evmap.jsonl"
        monkeypatch.setattr(endo_ai, "_EVMAP_LOG_PATH", str(path))
        big = "Z" * 25000
        _abstracts(monkeypatch, {str(1000 + i): big for i in range(6)})
        endo_ai.verify_citation_support(_answer(6), {})
        rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
                if l.strip()]
        support = [r for r in rows if r["function"] == "verify_citation_support"]
        assert len(support) == 1, \
            "batching changed the audit shape; the flag-rate aggregation " \
            "sums these records and would double-count the denominator"
        assert support[0]["checked"] == 6
        assert support[0]["n_requests"] > 1


class TestAQuotedClaimNeverEndsInHalfAMarker:
    """`_extract_claim_citation_pairs` strips the marker that ENDS a claim,
    but a merged claim — a decision tree, a run of bold pseudo-headings —
    carries markers INSIDE it, and the support block quotes at 140 characters.
    A real curriculum (learn_history 20260901_014227) rendered

        > - [[PMID:41063319]] cited for: "... resolving by day 14 [[PMID:"

    and `strip_markdown_for_speech` left that fragment in the narration script,
    where a TTS engine reads it aloud letter by letter. It is also a raw marker
    on a rendered surface, which invariant 3 forbids.
    """

    def test_a_cut_landing_inside_a_marker_leaves_nothing_dangling(self):
        claim = "A" * 130 + " [[PMID:41063319]] and more text after it."
        got = endo_ai._quote_claim(claim)
        assert "[[PMID" not in got
        assert not got.rstrip().endswith("[")

    def test_a_whole_marker_inside_the_kept_text_is_removed_too(self):
        claim = "Lasers reduced pain [[PMID:123]] at 24 hours."
        got = endo_ai._quote_claim(claim)
        assert "[[PMID" not in got
        assert "at 24 hours." in got

    def test_a_short_claim_is_returned_intact(self):
        assert endo_ai._quote_claim("A plain claim.") == "A plain claim."

    def test_the_rendered_block_carries_no_fragment(self):
        claim = "B" * 132 + " [[PMID:41063319]] trailing."
        rendered = endo_ai._append_support_warnings("ANSWER", {
            "flags": [{"pmid": "41063319", "claim": claim}],
            "checked": 10, "total_pairs": 10, "status": "verified",
            "cost": 0.0})
        # The one marker the block is ENTITLED to is the pill it renders
        # itself; there must be no second, broken one inside the quote.
        assert rendered.count("[[PMID:") == 1

    def test_narration_strips_a_fragment_that_reaches_it_anyway(self):
        import narration
        spoken = narration.strip_markdown_for_speech(
            'cited for: "resolving by day 14 [[PMID:"')
        assert "PMID" not in spoken

    def test_narration_still_strips_whole_markers(self):
        import narration
        spoken = narration.strip_markdown_for_speech(
            "Lasers reduced pain [[PMID:123]] at 24 hours.")
        assert "PMID" not in spoken and "24 hours" in spoken

    def test_a_line_mentioning_pmid_in_prose_is_not_eaten(self):
        """The partial pattern is anchored to end-of-line so it can only take
        a dangling fragment. A sentence that merely says the word must survive."""
        import narration
        text = "Every claim carries a PMID marker for the clinician to check."
        assert narration.strip_markdown_for_speech(text) == text
