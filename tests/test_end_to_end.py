"""
End-to-end test: POST /ask, follow the job, inspect the rendered answer.

Why this file exists. Three real bugs shipped past 176 passing unit tests in a
single session, and all three were invisible for the same reason — every unit
test imports one function and hands it a fixture, so nothing ever exercised the
whole path:

  * TIER_ORDER was not imported in app.py. Every live question raised
    NameError; the unit tests imported it from endo_ai directly and passed.
  * fetch_papers() never recorded level_key on the paper dict, so write-back
    inserted papers with an unknown design that were then banded to the weakest
    tier — the library quietly burying good RCTs.
  * The similarity floor gated the library DECISION but not the evidence, so
    all 100 nearest neighbours reached the model regardless of relevance.

Every external call is faked, so this is deterministic, offline and free:
NCBI, Anthropic and the embedding model are all stubbed. What it exercises is
OUR wiring — routing, banding, validation, rendering — which is exactly where
those three bugs lived.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


# ── Recorded fixtures ────────────────────────────────────────────────────
# One Cochrane review + one RCT + one case series, so tier banding has
# something to order and mis-banding is visible in the assertions.

LIBRARY_ROWS = [
    {"pmid": "1001", "title": "Single vs multiple visits: a Cochrane review",
     "abstract": "BACKGROUND: " + "Pooled analysis of randomized trials. " * 12 +
                 "We included 14 studies. No conflict of interest declared.",
     "authors": "Reviewer A", "year": 2024, "journal": "Cochrane Database Syst Rev",
     "impact_factor": None, "sample_size": None, "followup_months": 24,
     "citations": 40, "level_key": "cochrane", "score": 88.0, "similarity": 0.81,
     "is_curated": False, "coi_flag": False, "coi_funder": "",
     "coi_status": "declared_none", "registry": "PROSPERO",
     "has_erratum": False, "has_retraction": False, "medline_indexed": True},
    {"pmid": "1002", "title": "A randomized trial of sealer A vs B",
     "abstract": "METHODS: " + "A randomized controlled trial was conducted. " * 12 +
                 "150 patients were enrolled and followed for 24 months.",
     "authors": "Trialist B", "year": 2023, "journal": "J Endod",
     "impact_factor": 3.5, "sample_size": 150, "followup_months": 24,
     "citations": 20, "level_key": "level1", "score": 74.0, "similarity": 0.72,
     "is_curated": False, "coi_flag": False, "coi_funder": "",
     "coi_status": "no_statement", "registry": "",
     "has_erratum": False, "has_retraction": False, "medline_indexed": True},
    # Deliberately outscores the Cochrane review: under the old score-banding
    # this landed in the Level I bucket.
    {"pmid": "1003", "title": "A case series of 9 teeth",
     "abstract": "REPORT: " + "We describe a consecutive case series. " * 12 +
                 "Nine teeth were treated and reviewed.",
     "authors": "Author C", "year": 2025, "journal": "Int Endod J",
     "impact_factor": 4.5, "sample_size": 9, "followup_months": 12,
     "citations": 55, "level_key": "level4", "score": 91.0, "similarity": 0.69,
     "is_curated": False, "coi_flag": False, "coi_funder": "",
     "coi_status": "no_statement", "registry": "",
     "has_erratum": False, "has_retraction": False, "medline_indexed": True},
    # No level_key, and a score high enough to outrank every labelled paper
    # here. Live write-back keeps producing rows like this, so the banding rule
    # "an unknown design bands to the weakest tier" needs a standing assertion
    # rather than a comment. TIER_ORDER has no unknown bucket, so the mapping
    # lives in app.py's banding loop and nothing else pins it.
    {"pmid": "1004", "title": "An unlabelled study of uncertain design",
     "abstract": "SUMMARY: " + "The design of this work is not stated. " * 12 +
                 "Outcomes were assessed at review.",
     "authors": "Author D", "year": 2025, "journal": "Aust Endod J",
     "impact_factor": 2.0, "sample_size": 60, "followup_months": 12,
     "citations": 70, "level_key": "", "score": 95.0, "similarity": 0.70,
     "is_curated": False, "coi_flag": False, "coi_funder": "",
     "coi_status": "no_statement", "registry": "",
     "has_erratum": False, "has_retraction": False, "medline_indexed": True},
]

ANSWER_MD = """## CLINICAL RECOMMENDATION

Based on Level I evidence, single-visit and multiple-visit treatment show
comparable healing [[PMID:1001]].

## EVIDENCE SUMMARY

**Cochrane Reviews**

Pooled analysis found no clinically meaningful difference between protocols
[[PMID:1001]]. A randomized trial reached the same conclusion [[PMID:1002]].

## REFERENCES

1. [PMID: 1001] Reviewer A — Cochrane review. 2024.
2. [PMID: 1002] Trialist B — RCT. 2023.
"""


def _filler(i):
    """Padding so the coverage gate is satisfied — it requires a realistic
    number of relevant hits before it will trust the library."""
    return {
        "pmid": f"20{i:02d}", "title": f"Supporting cohort study {i}",
        "abstract": "METHODS: " + "A prospective cohort was followed. " * 12 +
                    f"{40 + i} patients were treated.",
        "authors": f"Author {i}", "year": 2022, "journal": "J Endod",
        "impact_factor": 3.5, "sample_size": 40 + i, "followup_months": 18,
        "citations": 5, "level_key": "level2", "score": 60.0,
        "similarity": 0.66, "is_curated": False, "coi_flag": False,
        "coi_funder": "", "coi_status": "no_statement", "registry": "",
        "has_erratum": False, "has_retraction": False, "medline_indexed": True,
    }


LIBRARY_ROWS = LIBRARY_ROWS + [_filler(i) for i in range(22)]


class FakeUsage:
    input_tokens = 100
    output_tokens = 200


class FakeBlock:
    def __init__(self, text):
        self.text = text


class FakeResponse:
    def __init__(self, text):
        self.content = [FakeBlock(text)]
        self.usage = FakeUsage()


@pytest.fixture
def client(monkeypatch):
    """A Flask test client with every external dependency stubbed."""
    import rag, endo_ai, app as app_mod

    monkeypatch.setattr(rag, "embed", lambda text: [0.01] * 384)
    monkeypatch.setattr(rag, "library_stats", lambda: {"total": len(LIBRARY_ROWS) + 100})
    monkeypatch.setattr(rag, "search",
                        lambda *a, **k: [dict(r) for r in LIBRARY_ROWS])
    monkeypatch.setattr(rag, "get_cached_answer", lambda *a, **k: None)
    monkeypatch.setattr(rag, "save_query_cache", lambda *a, **k: None)
    monkeypatch.setattr(rag, "get_cached_abstracts_bulk",
                        lambda pmids: {r["pmid"]: r for r in LIBRARY_ROWS
                                       if r["pmid"] in set(pmids)})
    monkeypatch.setattr(app_mod, "get_cached_answer", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(app_mod, "save_query_cache", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(app_mod, "save_answer", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(app_mod, "write_citation_audit", lambda *a, **k: None, raising=False)

    # Search-term generation, intent routing, synthesis and the support check
    # all funnel through _invoke_claude; dispatch on the caller's name.
    def fake_invoke(client_, function_name="", **kwargs):
        if "search_terms" in function_name:
            return FakeResponse("single visit versus multiple visit endodontics")
        if "intent" in function_name:
            return FakeResponse(json.dumps({
                "kind": "standard", "needs_clarify": False,
                "retrieval": "local", "reason": "well covered"}))
        if "citation_support" in function_name:
            return FakeResponse(json.dumps([{"i": 0, "verdict": "supports"},
                                            {"i": 1, "verdict": "supports"},
                                            {"i": 2, "verdict": "supports"}]))
        return FakeResponse(ANSWER_MD)

    monkeypatch.setattr(endo_ai, "_invoke_claude", fake_invoke)
    monkeypatch.setattr(endo_ai, "log_llm_call", lambda *a, **k: 0.0)
    monkeypatch.setattr(endo_ai, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(endo_ai, "LIBRARY_WRITE_BACK", False)

    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client()


def _run(client, question="Single visit versus multiple visit endodontic treatment?"):
    """POST /ask and drain the background job to completion."""
    import time
    r = client.post("/ask", json={"question": question, "mode": "review",
                                  "skip_clarify": True})
    assert r.status_code == 200, r.data
    job_id = r.get_json()["job_id"]
    for _ in range(200):
        status = client.get(f"/status/{job_id}").get_json()
        if status.get("status") in ("complete", "error", "aborted"):
            return status
        time.sleep(0.05)
    pytest.fail("job did not finish")


class TestQuestionReachesAnAnswer:

    def test_job_completes_without_error(self, client):
        """The NameError bug: app.py referenced TIER_ORDER without importing it,
        so every live question failed here while unit tests passed."""
        job = _run(client)
        assert job["status"] == "complete", f"job failed: {job.get('error')}"
        assert job.get("error") in (None, "")

    def test_answer_is_rendered_with_citations(self, client):
        job = _run(client)
        assert "CLINICAL RECOMMENDATION" in job["answer"]
        assert "[[PMID:1001]]" in job["answer"]

    def test_papers_are_returned_without_abstracts(self, client):
        """The copyright boundary: metadata reaches the client, abstract text
        does not."""
        job = _run(client)
        assert job["papers"], "no papers returned"
        for p in job["papers"]:
            assert "abstract" not in p


class TestTierHierarchyHoldsEndToEnd:

    def test_case_series_does_not_reach_the_top_tier(self, client):
        """PMID 1003 is a case series scoring 91 — higher than the Cochrane
        review at 88. Under the old score-banding it was presented as Level I."""
        job = _run(client)
        served = {p["pmid"]: p for p in job["papers"]}
        assert served["1003"]["level_key"] == "level4"
        assert served["1001"]["level_key"] == "cochrane"

    def test_all_three_designs_survive_retrieval(self, client):
        job = _run(client)
        assert {"1001", "1002", "1003"} <= {p["pmid"] for p in job["papers"]}

    def test_unlabelled_paper_bands_to_the_weakest_tier(self, client):
        """PMID 1004 has no level_key and scores 95 — the highest in the set.

        An unknown design must never be presentable as a strong one, because
        the system prompt instructs Claude to trust the tier label absolutely.
        Banding it to the weakest tier keeps it available as evidence without
        letting score promote it across tiers.
        """
        job = _run(client)
        served = {p["pmid"]: p for p in job["papers"]}
        assert "1004" in served, "unlabelled paper was dropped instead of banded"
        assert served["1004"]["level_key"] in ("", "level5"), \
            f"unlabelled paper was promoted to {served['1004']['level_key']!r}"

    def test_unlabelled_paper_lands_in_the_weakest_evidence_block(self, client):
        """Assert against the evidence dict itself, not the /status payload.

        The tier blocks are what get rendered into the prompt, each stamped
        with its TIER_LABEL, so a paper in the wrong block is described to
        Claude as the wrong strength no matter what the JSON says.
        """
        from app import build_evidence_base_with_progress, jobs
        from endo_ai import TIER_ORDER

        jobs["banding-probe"] = {"status": "running", "steps": [], "progress": 0}
        evidence = build_evidence_base_with_progress(
            "banding-probe", "Single visit versus multiple visit endodontic treatment?")

        placed = [t for t in TIER_ORDER
                  if "1004" in ((evidence.get(t) or {}).get("ids") or [])]
        assert placed == ["level5"], \
            f"unlabelled paper banded into {placed or 'no tier at all'}, expected ['level5']"

        # And it must not have been silently dropped on the way in.
        every_id = {i for t in TIER_ORDER for i in ((evidence.get(t) or {}).get("ids") or [])}
        assert "1001" in every_id and "1004" in every_id


class TestEvalRoutePinning:
    """force_route exists so the eval set keeps measuring the path each case was
    written for. Write-back silently moved the laser case from the live path
    (where its bug lived) to the library path, and it would have passed the next
    identical regression. If these break, the eval set is lying again."""

    def test_rejects_an_unknown_route(self, client):
        from app import build_evidence_base_with_progress
        with pytest.raises(ValueError):
            build_evidence_base_with_progress("bad-route", "anything",
                                              force_route="pubmed")

    def test_library_pin_holds_when_coverage_is_thin(self, client, monkeypatch):
        """Without the pin, a library that lost coverage falls through to live
        PubMed and the case passes by measuring the wrong path."""
        import rag
        from app import build_evidence_base_with_progress, jobs
        from endo_ai import TIER_ORDER

        import endo_ai

        # Two rows: far below MIN_RAG_RESULTS, so the gate would normally hand
        # this to PubMed.
        monkeypatch.setattr(rag, "search",
                            lambda *a, **k: [dict(LIBRARY_ROWS[0]), dict(LIBRARY_ROWS[1])])

        def _no_network(*a, **k):
            raise AssertionError("fell through to PubMed despite force_route='library'")
        monkeypatch.setattr(endo_ai, "generate_multi_search_terms", _no_network)

        jobs["pin-lib"] = {"status": "running", "steps": [], "progress": 0}
        evidence = build_evidence_base_with_progress(
            "pin-lib", "Single visit versus multiple visit endodontic treatment?",
            force_route="library")

        sources = {(evidence.get(t) or {}).get("source")
                   for t in TIER_ORDER if evidence.get(t)}
        assert sources == {"rag"}, f"expected library-only, got sources {sources}"

    def test_live_pin_skips_the_library_entirely(self, client, monkeypatch):
        """The laser bug was in live search-term generation. If the pin does not
        bypass the library, that generator never runs."""
        import rag
        from app import build_evidence_base_with_progress, jobs

        def _boom(*a, **k):
            raise AssertionError("library was searched despite force_route='live'")
        monkeypatch.setattr(rag, "search", _boom)

        # Stop before any real PubMed traffic — reaching the term generator is
        # the whole assertion.
        import endo_ai
        reached = {}

        def _stop(question, *a, **k):
            reached["yes"] = True
            raise RuntimeError("stop-here")
        monkeypatch.setattr(endo_ai, "generate_multi_search_terms", _stop)

        jobs["pin-live"] = {"status": "running", "steps": [], "progress": 0}
        with pytest.raises(RuntimeError, match="stop-here"):
            build_evidence_base_with_progress(
                "pin-live", "Single visit versus multiple visit endodontic treatment?",
                force_route="live")
        assert reached.get("yes"), "live path never reached the search-term generator"


# ── WORKLIST 4.7: no paper reaches the evidence base unlabelled ─────────────
# Real rows, copied out of endo_papers_rag after
# scripts/fix_empty_level_key.py --apply. All five sat at level_key = '' and
# were classified from their own abstracts; the tier on each row here is the
# tier the migration wrote. 39885347 is the one that matters most: it is an
# Evidence-Based Dentistry critical summary whose abstract opens by describing
# somebody else's randomised trial, so a cue-matcher that reads "randomised
# control trial" out of it installs a one-page commentary at Level I.
MIGRATED_LIBRARY_ROWS = [
    {"pmid": "42260496", "level_key": "level3a", "year": 2026,
     "title": "Frequency and associated factors of segmental root developmental "
              "arrest in endodontically treated immature permanent teeth with "
              "apical periodontitis: a retrospective cohort study.",
     "abstract": "BACKGROUND: Segmental root developmental arrest (SRDA) is an "
                 "uncommon developmental pattern in immature permanent teeth "
                 "with apical periodontitis. This retrospective study evaluated "
                 "the frequency, clinical features, and factors associated with "
                 "SRDA after regenerative endodontic procedures (REPs) or "
                 "apexification. METHODS: A total of 103 immature permanent "
                 "teeth were retrospectively reviewed. RESULTS: SRDA was "
                 "identified in 12 of 103 teeth (11.65%).",
     "journal": "BMC oral health", "authors": "Author A", "score": 57.3,
     "similarity": 0.74},
    {"pmid": "39885347", "level_key": "level5", "year": 2025,
     "title": "Tooth vitality and periapical healing: is Biodentine at par with "
              "MTA in regenerative endodontics?",
     "abstract": "DESIGN: The study is a prospective, double-blinded randomised "
                 "control trial that compares the mineral trioxide aggregate "
                 "(MTA) and Biodentine as the pulp space barrier material. A "
                 "total of 36 patients were included in the study. CASE "
                 "SELECTION: Participants were recruited from the Department of "
                 "Endodontics outpatient clinic. RESULTS: Firstly, the author "
                 "presented the overall healing of the periapical lesion.",
     "journal": "Evidence-based dentistry", "authors": "Author B", "score": 59.4,
     "similarity": 0.73},
    {"pmid": "39775507", "level_key": "level2", "year": 2025,
     "title": "Clinical and radiographic evaluation of two different "
              "apexification protocols in traumatized immature permanent incisors.",
     "abstract": "BACKGROUND: Dental trauma can cause damage to the pulp tissue "
                 "in immature teeth. The aim of this prospective study was to "
                 "evaluate the radiographic and clinical results of immature "
                 "teeth with a history of trauma. METHODS: Forty-one patients "
                 "aged between 7 and 12 years were included in the study and "
                 "followed for a period of 24 months.",
     "journal": "Ulusal travma ve acil cerrahi dergisi", "authors": "Author C",
     "score": 58.3, "similarity": 0.72},
    {"pmid": "41167331", "level_key": "level5", "year": 2026,
     "title": "Clinical and Laboratory Insights Into the GentleWave System: A "
              "Scoping Review.",
     "abstract": "INTRODUCTION: The GentleWave System is an advanced endodontic "
                 "irrigation technology. This scoping review aims to "
                 "systematically assess the available clinical and laboratory "
                 "evidence. METHODS: This review was conducted in accordance "
                 "with PRISMA-ScR guidelines. RESULTS: A total of 34 studies met "
                 "the inclusion criteria.",
     "journal": "Journal of endodontics", "authors": "Author D", "score": 37.5,
     "similarity": 0.71},
    {"pmid": "30519823", "level_key": "level3a", "year": 2019,
     "title": "The fate of root canals obturated with Thermafil: 10-year data "
              "for patients treated in a master's program.",
     "abstract": "OBJECTIVES: Retrospective description of the 10-year success "
                 "rate of endodontic treatments with Thermafil (TF). MATERIALS "
                 "AND METHODS: Teeth satisfying the inclusion criteria (206 "
                 "teeth in 89 patients) were reexamined clinically and "
                 "radiographically. RESULTS: At 10 years, 179 (87%) teeth "
                 "survived and 27 were extracted.",
     "journal": "Clinical oral investigations", "authors": "Author E",
     "score": 64.1, "similarity": 0.70},
]

# Fill in the columns rag.search() returns, so these rows are shaped exactly
# like the ones the real query produces.
for _r in MIGRATED_LIBRARY_ROWS:
    _r.update({"impact_factor": None, "sample_size": None,
               "followup_months": 12, "citations": 3, "is_curated": False,
               "coi_flag": False, "coi_funder": "", "coi_status": "no_statement",
               "registry": "", "has_erratum": False, "has_retraction": False,
               "medline_indexed": True})


class TestNoUnlabelledPaperReachesTheEvidenceBase:
    """WORKLIST 4.7. `level_key` drives the design axis at 39% of the score, and
    app.py bands anything it cannot recognise to level5 — safe, but it means a
    ten-year retrospective cohort of 206 teeth is handed to Claude stamped
    "Level V — Expert Opinion". 14 rows were in that state.

    The banding fallback above is still load-bearing and its own test
    (test_unlabelled_paper_bands_to_the_weakest_tier) stays. What these two add
    is the stronger property the migration establishes: nothing unlabelled
    should be arriving in the first place.
    """

    def test_every_paper_in_the_evidence_base_carries_a_tier(self, client,
                                                             monkeypatch):
        """Offline twin, on the real migrated rows.

        Fails if any of those rows regresses to level_key = '', and fails if a
        future change to the retrieval path drops the column on the way through.
        """
        import rag
        from app import build_evidence_base_with_progress, jobs
        from endo_ai import TIER_ORDER

        rows = [dict(r) for r in MIGRATED_LIBRARY_ROWS] + \
               [_filler(i) for i in range(22)]
        monkeypatch.setattr(rag, "search", lambda *a, **k: [dict(r) for r in rows])
        monkeypatch.setattr(rag, "get_cached_abstracts_bulk",
                            lambda pmids: {r["pmid"]: r for r in rows
                                           if r["pmid"] in set(pmids)})

        # Pinned, for the same reason the eval cases are: none of these rows is
        # cochrane/level1, so the coverage gate's high-tier check hands the
        # question to live PubMed and the test measures the wrong path (and
        # goes online). The library path is the one that reads stored
        # level_key, so it is the one this property belongs to.
        jobs["unlabelled-probe"] = {"status": "running", "steps": [], "progress": 0}
        evidence = build_evidence_base_with_progress(
            "unlabelled-probe",
            "Single visit versus multiple visit endodontic treatment?",
            force_route="library")

        unlabelled = [(t, p.get("pmid"))
                      for t in TIER_ORDER
                      for p in ((evidence.get(t) or {}).get("scored") or [])
                      if not (p.get("level_key") or "").strip()]
        assert not unlabelled, (
            f"{len(unlabelled)} paper(s) reached the evidence base with no "
            f"level_key: {unlabelled}")

        # And the migrated rows actually made it in — an empty evidence base
        # would satisfy the assertion above for the wrong reason.
        served = {p.get("pmid")
                  for t in TIER_ORDER
                  for p in ((evidence.get(t) or {}).get("scored") or [])}
        assert {"42260496", "39885347", "30519823"} <= served, \
            f"migrated rows never reached the evidence base: {sorted(served)}"

        # 39885347 is a critical summary of somebody else's RCT. If it ever
        # shows up at level1 the cue matcher has read the summarised trial's
        # design off the summarising paper.
        placed = {p["pmid"]: t
                  for t in TIER_ORDER
                  for p in ((evidence.get(t) or {}).get("scored") or [])}
        assert placed["39885347"] == "level5", (
            f"an Evidence-Based Dentistry critical summary was banded as "
            f"{placed['39885347']!r} — its abstract describes the trial it "
            f"summarises, not itself")

    @pytest.mark.network
    @pytest.mark.skipif(os.environ.get("RUN_NETWORK_TESTS") != "1",
                        reason="reads the live Neon library; "
                               "set RUN_NETWORK_TESTS=1 to enable")
    def test_library_holds_no_unlabelled_rows(self):
        """The property at its source. The offline twin above cannot see the
        database, and the leak that produced these 14 rows was a write path, not
        a read path."""
        import psycopg2.extras
        from rag import get_conn

        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute("""
                SELECT pmid, LEFT(COALESCE(title, ''), 70) AS title
                  FROM endo_papers_rag
                 WHERE COALESCE(level_key, '') = ''
                 ORDER BY pmid;
            """)
            rows = cur.fetchall()
        finally:
            cur.close(); conn.close()

        assert not rows, (
            f"{len(rows)} library row(s) carry no level_key and will be banded "
            f"to Level V regardless of design — run "
            f"scripts/fix_empty_level_key.py --apply, then "
            f"scripts/rescore_library.py --apply:\n"
            + "\n".join(f"  {r['pmid']}  {r['title']}" for r in rows))


class TestGuardrailsRunOnTheRealPath:

    def test_citation_support_status_is_stated(self, client):
        """A fail-open check that says nothing is indistinguishable from one
        that passed."""
        job = _run(client)
        assert "Citation support" in job["answer"]

    def test_no_validation_warning_on_a_clean_answer(self, client):
        job = _run(client)
        assert "VALIDATION WARNING" not in job["answer"]

    def test_provenance_fields_survive_to_the_client(self, client):
        """These were silently dropped twice by the _safe_papers whitelist."""
        job = _run(client)
        p = next(x for x in job["papers"] if x["pmid"] == "1001")
        for field in ("coi_status", "registry", "has_retraction", "medline_indexed"):
            assert field in p, f"{field} was stripped before reaching the client"
