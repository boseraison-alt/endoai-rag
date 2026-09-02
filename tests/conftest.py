"""
Pytest fixtures for metadata extraction tests.

The two fixtures here serve different purposes:

1. mock_pubmed_efetch_batch — for unit tests. Returns recorded XML responses
   so the test runs offline and is deterministic. The XML is hand-crafted
   to put the target PMID alongside DIFFERENT-shape papers, so the test
   proves per-PMID isolation rather than just that extraction works on a
   single paper.

2. real_pubmed_search_result — for integration tests. Hits the real
   PubMed eutils API. Slow, requires network, but catches real-world bugs
   that mocked XML can't reproduce.
"""

import os
import sys
from pathlib import Path
from typing import Callable

import pytest

# Make endo_ai importable from tests/
sys.path.insert(0, str(Path(__file__).parent.parent))

FIXTURE_XML_DIR = Path(__file__).parent / "fixtures" / "pubmed_xml"


@pytest.fixture(autouse=True, scope="session")
def _audit_logs_stay_out_of_the_repo(tmp_path_factory):
    """A test run must not append to the production audit trail.

    `tests/test_end_to_end.py` drives the real `/ask` path with a stubbed
    Claude, and `verify_citation_support` writes one row per answer into the
    repo's `evidence_mapping.jsonl`. Nine such rows landed inside one eval
    case's measurement window on 2026-09-01 and inflated its denominator by 27
    — the same class of contamination `run_eval._esearch_hits_since` already
    warns about for `pubmed_audit.jsonl`, arriving through a file nobody
    thought of as shared state.

    The cost log goes the same way: a suite run was adding rows to the record
    of what the product spent.

    `pubmed_audit.jsonl` is the third, added in `guardrails-v1`. It has the
    same shape — `run_eval._esearch_hits_since` reads a byte-offset window of
    it — and it had no guard at all: not this redirect, because the writer
    built its path inline, and not a writer pid. Both now exist.
    """
    import endo_ai

    d = tmp_path_factory.mktemp("audit")
    endo_ai._EVMAP_LOG_PATH = str(d / "evidence_mapping.jsonl")
    endo_ai._COST_LOG_PATH = str(d / "cost_log.jsonl")
    endo_ai._PUBMED_AUDIT_LOG_PATH = str(d / "pubmed_audit.jsonl")

    # The fourth, found in `case-v3` by noticing a stray `c.md` in `git status`
    # twice. The eval harness saves every case answer it generates so an
    # assertion failure can be read against the actual text; under pytest that
    # wrote a stub answer into the repo's own log directory on every run.
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent / "eval"))
        import run_eval
        run_eval.CASE_ANSWER_DIR = d / "case_answers"
    except Exception:      # the eval harness is not importable in every env
        pass
    yield


@pytest.fixture
def mock_pubmed_efetch_batch() -> Callable[..., str]:
    """
    Returns a function that, given a target PMID, returns a batch XML
    response containing that PMID plus 4-5 OTHER papers of varying types.

    This is the key design choice: we never test extraction on a single
    paper alone. We always test it inside a batch, so a regression to the
    "extract from concatenated batch" bug would be visible.

    Usage in test:
        batch_xml = mock_pubmed_efetch_batch(target_pmid="30174103")
    """
    def _build_batch(target_pmid: str) -> str:
        # Each fixture file is a real PubMed efetch response saved to disk.
        # Save these once via fetch_and_save_fixtures.py (see scripts/).
        fixture_path = FIXTURE_XML_DIR / f"batch_{target_pmid}.txt"
        if not fixture_path.exists():
            pytest.skip(
                f"No XML fixture saved for PMID {target_pmid}. "
                f"Run scripts/fetch_and_save_fixtures.py to generate."
            )
        return fixture_path.read_text(encoding="utf-8")

    return _build_batch


@pytest.fixture
def real_pubmed_search_result() -> Callable[..., list]:
    """
    Runs a real query through the full evidence pipeline and returns the
    scored paper list. Use sparingly — slow and rate-limited.

    Skipped automatically when SKIP_NETWORK_TESTS=1 in the environment
    (set this in CI configs that don't have outbound network).
    """
    if os.environ.get("SKIP_NETWORK_TESTS") == "1":
        pytest.skip("Network tests disabled via SKIP_NETWORK_TESTS=1")

    from endo_ai import build_evidence_base  # adjust import to your actual entry point

    def _run(query: str, n: int = 20):
        result = build_evidence_base(query, mode="review")
        # Flatten all tiers into a single scored-paper list
        summary = result.get("_summary", {})
        return (summary.get("all_scored") or [])[:n]

    return _run
