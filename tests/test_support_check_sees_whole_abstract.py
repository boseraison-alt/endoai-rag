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
    """`_SUPPORT_MAX_PAIRS` binds on real curricula — the two laser runs
    measured 29/30/30/30 checked, i.e. at the cap on three of four modules."""

    def test_total_pairs_records_what_existed(self, judge, monkeypatch):
        n = endo_ai._SUPPORT_MAX_PAIRS + 12
        _abstracts(monkeypatch, {str(1000 + i): "abstract text " * 30
                                 for i in range(n)})
        out = endo_ai.verify_citation_support(_answer(n), {})
        assert out["total_pairs"] == n
        assert out["checked"] == endo_ai._SUPPORT_MAX_PAIRS

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
