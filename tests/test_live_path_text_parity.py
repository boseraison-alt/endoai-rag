"""On the live path, what Claude READS must be what was retrieved.

THE BUG. `app.build_evidence_base_with_progress` fetches each tier once per
search term -- about seven fetches per tier -- and folded them like this:

    level_scored.extend(new_scored)      # every term
    level_ids.extend(new_ids)            # every term
    if text and not level_text:          # the FIRST term only
        level_text = text

`_build_evidence_context` renders `block["text"]` and nothing else. So the
prompt carried ONE term's papers per tier while `_summary` counted them all.

MEASURED on a live Review retrieval for "sodium hypochlorite concentration
for root canal irrigation" (scripts/measure_live_text_gap.py):

    level1      73 scored,  3 in the prompt   70 never shown
    guideline    4 scored,  1 in the prompt    3 never shown
    TOTAL       99 scored, 26 in the prompt

    the model saw 26.3% of the retrieved evidence, under a header telling it
    "Total papers: 80 | Avg score: 62.2"

That is the A5 false-evidence-gap mechanism in its original form: the answer
can state that no study addresses X while that study sits in `scored`, and
the "Top paper per tier" panel can name a paper whose abstract was never in
the prompt. It was also NON-DETERMINISTIC -- `raw[lk]` is appended in
`as_completed` order, so which term's block survived depended on which HTTP
round trip finished first, and the same question asked twice could answer
differently.

After the fix the same measurement reads 100.0%.

WHY THE CAP MOVED TOO. `fetch_papers` applies the per-tier cap per CALL, so
seven calls accumulated roughly seven times the intended quota (level1: 73
against a quota of 18). Rendering all of that would have grown the prompt
about 24x. The cap is now applied to the deduped list, which is what
MODE_TIER_QUOTAS always meant and what the curriculum path already did.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import endo_ai as E

ROOT = Path(__file__).parent.parent
APP = (ROOT / "app.py").read_text(encoding="utf-8")

PMID_IN_TEXT = re.compile(r"PMID:?\s*(\d{5,9})")


def _run_tiers_src(strip_comments=False):
    i = APP.index("    def _run_tiers(tier_specs):")
    j = APP.index("\n    if not is_aborted(job_id):", i)
    src = APP[i:j]
    if strip_comments:
        # The fix's own comment QUOTES the removed construct, so a naive grep
        # over the slice finds it and reports the bug as still present.
        src = "\n".join(l for l in src.splitlines()
                        if not l.lstrip().startswith("#"))
    return src


class TestTheFoldNoLongerKeepsOneTerm:

    def test_the_first_text_wins_construct_is_gone(self):
        src = _run_tiers_src(strip_comments=True)
        assert "if text and not level_text:" not in src, (
            "the fold is keeping only the first search term's text block; "
            "the prompt then carries one term's papers while _summary counts "
            "all of them")

    def test_the_text_is_rebuilt_from_the_scored_list(self):
        src = _run_tiers_src()
        assert "_scored_to_text(" in src, (
            "text must be rebuilt from the deduped scored list so the two are "
            "one-to-one by construction")

    def test_the_cap_is_applied_to_the_deduped_list(self):
        """Otherwise seven per-(tier, term) caps accumulate ~7x the quota."""
        src = _run_tiers_src()
        assert "cap_by_relevance(" in src
        assert "_tier_cap(mode, level_key)" in src, (
            "the live path must use the same per-tier quota as the curriculum "
            "path, not a separate number")


class TestTextAndScoredAreOneToOne:
    """Behavioural. Drives the real fold with stubbed fetches, several terms
    per tier, and asserts every scored paper appears in the rendered text."""

    @pytest.fixture
    def evidence(self, monkeypatch):
        import app as A

        def paper(pmid, score):
            return {"pmid": pmid, "score": score, "level_key": "level1",
                    "title": "T%s" % pmid, "abstract": "A%s" % pmid,
                    "authors": "X Y", "year": 2024, "journal": "J",
                    "citations": 1, "sample_size": None,
                    "followup_months": None, "impact_factor": None}

        # Different papers per TERM, keyed by the term itself. An earlier
        # version used a shared call counter, which is wrong twice over: the
        # fetches run on a ThreadPoolExecutor so the counter races, and the
        # counter also advanced on the other tiers' calls and ate the batches.
        # Keying on the term is deterministic under parallelism.
        by_term = {
            "t1": ("text-A", ["10000001", "10000002"],
                   [paper("10000001", 90.0), paper("10000002", 89.0)]),
            "t2": ("text-B", ["10000003", "10000004"],
                   [paper("10000003", 88.0), paper("10000004", 87.0)]),
            "t3": ("text-C", ["10000005", "10000006"],
                   [paper("10000005", 86.0), paper("10000006", 85.0)]),
        }

        def fake_fetch_papers(topic, filt, label, level_key, **kw):
            if level_key != "level1":
                return "", [], []
            return by_term.get(topic, ("", [], []))

        monkeypatch.setattr("endo_ai.fetch_papers", fake_fetch_papers)
        monkeypatch.setattr("endo_ai.fetch_cochrane", lambda t: None)
        monkeypatch.setattr("endo_ai.fetch_untyped_recent",
                            lambda *a, **k: ("", [], []))
        monkeypatch.setattr("endo_ai.generate_search_terms",
                            lambda q, **k: "(topic)")
        monkeypatch.setattr("endo_ai.generate_multi_search_terms",
                            lambda q, p, **k: ["t1", "t2", "t3"])
        monkeypatch.setattr("endo_ai.label_and_expand", lambda q, t: t)

        with A.jobs_lock:
            A.jobs["parity"] = {"status": "running", "abort": False}
        return A.build_evidence_base_with_progress(
            "parity", "a question", force_route="live", mode="review")

    def test_every_scored_paper_appears_in_the_text(self, evidence):
        block = evidence.get("level1") or {}
        scored = {str(p["pmid"]) for p in (block.get("scored") or [])}
        if not scored:
            pytest.skip("stub produced no level1 papers")
        in_text = set(PMID_IN_TEXT.findall(block.get("text") or ""))
        missing = scored - in_text
        assert not missing, (
            f"{len(missing)} scored paper(s) never reach the prompt: "
            f"{sorted(missing)}")

    def test_more_than_one_terms_papers_survive(self, evidence):
        """The specific regression: the old fold kept batch A only."""
        scored = {str(p["pmid"])
                  for p in ((evidence.get("level1") or {}).get("scored") or [])}
        assert len(scored) > 2, (
            "only one search term's papers survived the fold")

    def test_the_text_names_no_paper_that_is_not_scored(self, evidence):
        """The other direction: a 'Top paper per tier' panel must never name
        a paper whose abstract was not supplied."""
        block = evidence.get("level1") or {}
        scored = {str(p["pmid"]) for p in (block.get("scored") or [])}
        in_text = set(PMID_IN_TEXT.findall(block.get("text") or ""))
        assert in_text <= scored, f"text names unscored papers: {in_text - scored}"


class TestTheQuotaIsPerTierNotPerTermTimesTier:

    def test_the_curriculum_quota_is_the_one_used(self):
        """Both paths must bound level1 the same way, or the same question
        answered in two modes sees a different amount of evidence with
        nothing saying so."""
        assert E._tier_cap("review", "level1") == 18
        src = _run_tiers_src()
        assert "_tier_cap(mode, level_key)" in src
