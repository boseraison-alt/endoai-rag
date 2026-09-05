"""A49 item 4 — the guideline seed, ingested as guidelines rather than papers.

`ingest_aae_guidelines.py` wrote sixteen hardcoded records at level1, score
85-95, impact_factor 4.5-8.0, with model-written summaries stored as source
text. Twelve of them named documents that could not be verified and are
quarantined (c7d7540). This file pins the replacement.

WHAT IS PINNED, one class per binding rule:

  no hand-set score      every guideline row stores score NULL
  no impact factor       every guideline row stores impact_factor NULL
  no model summaries     stored text is a POINTER (org/title/year/status/URL)
  dedupe by PMID         one row per document, existing rows RECLASSIFIED
  studies stay studies   a Cochrane systematic review is NOT demoted to the
                         guideline rung by appearing in the manifest
  withdrawn              never citeable
  superseded             never served as current
  draft                  never presented as current
  unconfirmed_pmid       never emitted as [PMID:N]
  reversible             quarantine_reason is the undo

The guarded writer in `ingest_aae_guidelines.upsert_guideline` is pinned too:
a comment did not stop this the first time -- the original module docstring
described the score and the impact factor openly, as design, for months.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import endo_ai as E

ROOT = Path(__file__).parent.parent
SEED = ROOT / "data" / "guidelines_seed.json"


@pytest.fixture(scope="module")
def seed():
    return json.loads(SEED.read_text(encoding="utf-8"))["guidelines"]


def _db():
    try:
        from rag import DATABASE_URL, get_conn
        if not DATABASE_URL:
            pytest.skip("DATABASE_URL not set")
        return get_conn()
    except Exception as e:               # pragma: no cover
        pytest.skip("library unreachable: %s" % e)


def query(sql, args=()):
    conn = _db()
    cur = conn.cursor()
    try:
        cur.execute(sql, args)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


class TestGuidelinesCarryNoNumber:
    """The category error that made the original sixteen dangerous. A
    hand-set 90.0 outranked 100% of the 3,192 evidence rows; no genuine paper
    in the library scores above 85.9."""

    def test_no_guideline_row_has_a_score(self):
        bad = query("SELECT pmid, score FROM endo_papers_rag "
                    "WHERE level_key = 'guideline' AND score IS NOT NULL "
                    "AND COALESCE(guideline_id,'') <> ''")
        assert not bad, f"guideline rows carrying a score: {bad[:5]}"

    def test_no_guideline_row_has_an_impact_factor(self):
        bad = query("SELECT pmid, impact_factor FROM endo_papers_rag "
                    "WHERE level_key = 'guideline' "
                    "AND impact_factor IS NOT NULL "
                    "AND COALESCE(guideline_id,'') <> ''")
        assert not bad, f"guideline rows carrying an impact factor: {bad[:5]}"

    def test_the_stored_value_really_is_null_not_zero(self):
        """`rag.search` returns RAW database rows, so a guideline's score
        arrives as None. That is the property: the row carries no number,
        rather than a number that says zero."""
        import rag
        rows = rag.search("endodontic clinical practice guideline",
                          level_key="guideline", limit=40,
                          similarity_threshold=0.0)
        assert rows, "no guideline rows retrievable at all"
        seeded = [r for r in rows if (r.get("guideline_id") or "")]
        assert seeded, "no seeded guideline rows came back"
        assert any(r.get("score") is None for r in seeded)

    def test_the_scored_conversion_survives_a_null_score(self):
        """`float(r.get("score", 0))` raises on a present-but-NULL column --
        `.get` returns None when the key EXISTS with a null value, and the
        default never applies. `rag_results_to_scored` is where every library
        row is converted before anything sorts it, so that is the layer this
        has to hold at, not `search()`.
        """
        import rag
        rows = rag.search("endodontic clinical practice guideline",
                          level_key="guideline", limit=40,
                          similarity_threshold=0.0)
        scored = rag.rag_results_to_scored(rows)
        assert scored
        for s in scored:
            assert isinstance(s["score"], (int, float))
        # and the downstream sort pattern does not raise on the result
        assert sorted(scored, key=lambda x: x["score"], reverse=True)


class TestNoScoreIsNotAScoreOfZero:
    """`rag_results_to_scored` coalesces a NULL score to 0.0 so downstream
    sorts do not raise. Rendering that coalesced value gave
    "Evidence Score: 0.0/100" for every guideline -- which a reader, and a
    model, takes as a quality judgement rather than an absence. Zero is the
    worst possible number to show for "not applicable".

    Measured consequence of not fixing it: COCHRANE-CD004969 had the HIGHEST
    similarity in its pool (0.819) and would have been presented as scoring
    zero out of a hundred.
    """

    GUIDELINE = {
        "pmid": "AAE-VPT-2021", "authors": "AAE", "year": 2021,
        "citations": 0, "level_key": "guideline", "score": 0.0,
        "guideline_org": "AAE", "guideline_status": "current",
        "guideline_jurisdiction": "US",
        "sample_size": None, "followup_months": None,
    }
    PAPER = {
        "pmid": "27759881", "authors": "A B", "year": 2016, "citations": 40,
        "level_key": "cochrane", "score": 73.3,
        "sample_size": 100, "followup_months": 12,
    }

    def test_a_guideline_shows_no_number(self):
        line = E.format_paper_context_line(self.GUIDELINE)
        assert "0.0/100" not in line
        assert "/100" not in line
        assert "NOT SCORED" in line

    def test_it_says_why_rather_than_going_silent(self):
        line = E.format_paper_context_line(self.GUIDELINE)
        assert "stated position" in line
        assert "not a study design" in line

    def test_it_surfaces_organisation_status_and_jurisdiction(self):
        """A UK clinician shown only US guidance has been given the wrong
        answer, so jurisdiction travels with the record."""
        line = E.format_paper_context_line(self.GUIDELINE)
        assert "AAE" in line and "current" in line and "US" in line

    def test_a_real_paper_still_shows_its_score(self):
        line = E.format_paper_context_line(self.PAPER)
        assert "Evidence Score: 73.3/100" in line

    def test_a_null_score_on_a_non_guideline_is_also_not_zero(self):
        p = dict(self.PAPER)
        p["score"] = None
        p["level_key"] = "level1"
        line = E.format_paper_context_line(p)
        assert "/100" not in line
        assert "NOT SCORED" in line


class TestNothingIsParaphrased:

    def test_pointer_records_say_what_they_are(self):
        rows = query(
            "SELECT pmid, abstract FROM endo_papers_rag "
            "WHERE level_key='guideline' AND COALESCE(guideline_id,'') <> '' "
            "AND abstract LIKE 'GUIDELINE RECORD%%' LIMIT 5")
        assert rows, "no pointer records found"
        for pmid, abstract in rows:
            assert "pointer only" in abstract
            assert "Organisation:" in abstract and "Status:" in abstract

    def test_a_pointer_carries_a_url_a_clinician_can_follow(self, seed):
        with_url = [g for g in seed if g.get("url")]
        assert len(with_url) >= 50, "the manifest should carry URLs"
        rows = query(
            "SELECT COUNT(*) FROM endo_papers_rag "
            "WHERE level_key='guideline' AND COALESCE(guideline_url,'') <> ''")
        assert rows[0][0] >= 40


class TestOneRowPerDocument:

    def test_no_duplicate_guideline_ids(self):
        dupes = query(
            "SELECT guideline_id, COUNT(*) FROM endo_papers_rag "
            "WHERE COALESCE(guideline_id,'') <> '' "
            "GROUP BY guideline_id HAVING COUNT(*) > 1")
        assert not dupes, f"duplicate guideline records: {dupes}"

    def test_the_aapd_primary_guideline_was_reclassified_not_duplicated(self):
        """38449041 was in the corpus as a level1 PAPER at score 80.0. It is
        the AAPD primary-teeth VPT guideline -- a specialty position, and the
        reason a paediatric guideline anchored an adult curriculum."""
        rows = query("SELECT level_key, score, guideline_id FROM "
                     "endo_papers_rag WHERE pmid = '38449041'")
        assert len(rows) == 1, "duplicated instead of reclassified"
        level_key, score, gid = rows[0]
        assert level_key == "guideline"
        assert score is None
        assert gid == "AAPD-VPT-PRIMARY-2024"

    def test_the_systematic_review_did_not_become_a_guideline(self):
        """40533920 is titled "...A Systematic Review and Meta-Analysis" and
        is NOT in the manifest. The batch expected it to move; the data says
        it should not. A review is a study."""
        rows = query("SELECT level_key, guideline_id FROM endo_papers_rag "
                     "WHERE pmid = '40533920'")
        if not rows:
            pytest.skip("40533920 not in this library")
        level_key, gid = rows[0]
        assert level_key == "level1"
        assert not (gid or "")


class TestAStudyIsNotDemotedByAppearingInTheManifest:
    """Caught on the dry run. The manifest carries eight Cochrane entries --
    it must, because three are the withdrawn reviews G1 exists for -- but a
    Cochrane review is a SYSTEMATIC REVIEW, the top of the ladder, not a
    specialty position. Reclassifying them would have moved three real
    reviews from cochrane (LEVEL_SCORES 100) to guideline (12) and nulled
    their scores: the score-as-membership error running backwards."""

    @pytest.mark.parametrize("pmid", ["22972129", "26403154", "30720860"])
    def test_cochrane_reviews_keep_their_tier_and_score(self, pmid):
        rows = query("SELECT level_key, score, guideline_id, guideline_status "
                     "FROM endo_papers_rag WHERE pmid = %s", (pmid,))
        if not rows:
            pytest.skip("%s not in this library" % pmid)
        level_key, score, gid, status = rows[0]
        assert level_key == "cochrane", (
            f"{pmid} was demoted to {level_key!r} by the manifest ingest")
        assert score is not None and score > 0
        # ...and it was still ENRICHED, which is the point of including them.
        assert gid and gid.startswith("COCHRANE-")
        assert status

    def test_the_cochrane_tier_did_not_shrink(self):
        n = query("SELECT COUNT(*) FROM endo_papers_rag "
                  "WHERE level_key = 'cochrane'")[0][0]
        assert n >= 21, f"cochrane tier fell to {n}; the ingest demoted reviews"


class TestStatusIsEnforced:

    def test_withdrawn_records_are_not_citeable(self, seed):
        ids = [g["id"] for g in seed if (g.get("status") or "") == "withdrawn"]
        assert ids, "manifest should carry withdrawn records"
        for gid in ids:
            rows = query("SELECT COALESCE(quarantine_reason,'') FROM "
                         "endo_papers_rag WHERE guideline_id = %s", (gid,))
            if not rows:
                continue
            assert rows[0][0], f"{gid} is withdrawn but citeable"

    def test_withdrawn_records_are_also_caught_by_g1(self, seed):
        """Independent of the column: G1 reads the manifest itself, so the
        two mechanisms cover each other."""
        for g in seed:
            if (g.get("status") or "") != "withdrawn":
                continue
            bad, why = E.is_withdrawn({"pmid": g["id"], "title": g.get("title", "")})
            assert bad, f"G1 does not recognise {g['id']} as withdrawn: {why}"

    def test_draft_records_are_not_served_as_current(self, seed):
        ids = [g["id"] for g in seed if (g.get("status") or "") == "draft"]
        for gid in ids:
            rows = query("SELECT COALESCE(quarantine_reason,'') FROM "
                         "endo_papers_rag WHERE guideline_id = %s", (gid,))
            if rows:
                assert rows[0][0], f"{gid} is a draft but is citeable"

    def test_superseded_records_name_their_replacement(self, seed):
        ids = {g["id"]: g.get("superseded_by") for g in seed
               if (g.get("status") or "") in ("superseded", "superseded_in_content")}
        assert ids, "manifest should carry superseded records"
        for gid, succ in ids.items():
            rows = query("SELECT COALESCE(superseded_by,'') FROM "
                         "endo_papers_rag WHERE guideline_id = %s", (gid,))
            if rows:
                assert rows[0][0] == (succ or ""), (
                    f"{gid} does not record its replacement")

    def test_no_superseded_guideline_reaches_a_pool(self):
        import rag
        rows = rag.search("quality guidelines for endodontic treatment",
                          level_key="guideline", limit=200,
                          similarity_threshold=0.0)
        got = {r.get("pmid") for r in rows}
        sup = query("SELECT pmid FROM endo_papers_rag "
                    "WHERE COALESCE(superseded_by,'') <> ''")
        for (pmid,) in sup:
            assert pmid not in got, f"superseded {pmid} reached the pool"


class TestUnconfirmedPmidsAreNeverEmitted:
    """Ten manifest records have a verified DOI and journal but an
    UNCONFIRMED PubMed accession. Emitting one as [PMID:N] would assert a
    identifier nobody has checked."""

    def test_they_are_keyed_by_manifest_id(self, seed):
        for g in seed:
            if g.get("confidence") != "unconfirmed_pmid":
                continue
            rows = query("SELECT pmid FROM endo_papers_rag "
                         "WHERE guideline_id = %s", (g["id"],))
            if not rows:
                continue
            assert rows[0][0] == g["id"], (
                f"{g['id']} is keyed by {rows[0][0]!r}; an unconfirmed "
                f"accession must never become the citation key")

    def test_no_unconfirmed_row_is_keyed_by_a_bare_number(self):
        bad = query("SELECT pmid, guideline_id FROM endo_papers_rag "
                    "WHERE guideline_confidence = 'unconfirmed_pmid' "
                    "AND pmid ~ '^[0-9]+$'")
        assert not bad, f"unconfirmed records keyed by a numeric PMID: {bad}"

    def test_their_keys_still_resolve_for_citation(self):
        """Keyed by slug, they must still be citeable -- G2 drops a citation
        whose id names nothing."""
        E._KNOWN_SYNTHETIC_KEYS = None
        known = E._known_synthetic_keys()
        assert known is not None
        rows = query("SELECT pmid FROM endo_papers_rag "
                     "WHERE guideline_confidence = 'unconfirmed_pmid' "
                     "AND COALESCE(quarantine_reason,'') = '' "
                     "AND COALESCE(superseded_by,'') = ''")
        for (pmid,) in rows:
            assert pmid in known, f"{pmid} would be dropped by G2"
        E._KNOWN_SYNTHETIC_KEYS = None


class TestTheOldIngesterCannotComeBack:

    def test_the_hardcoded_statement_corpus_is_gone(self):
        src = (ROOT / "ingest_aae_guidelines.py").read_text(encoding="utf-8")
        assert "AAE_POSITION_STATEMENTS" not in src
        assert "ESE_GUIDELINES" not in src
        assert '"score":           90.0' not in src
        assert '"impact_factor":   8.0' not in src

    def test_the_fetch_machinery_is_kept(self):
        import ingest_aae_guidelines as I
        for fn in ("pubmed_search", "pubmed_fetch_abstracts",
                   "pubmed_fetch_meta", "_get"):
            assert callable(getattr(I, fn, None)), f"{fn} was removed"

    @pytest.mark.parametrize("bad_record,why", [
        ({"pmid": "X-1", "title": "t", "abstract": "a" * 40, "score": 90.0}, "score"),
        ({"pmid": "X-2", "title": "t", "abstract": "a" * 40, "impact_factor": 8.0}, "impact factor"),
        ({"pmid": "X-3", "title": "t", "abstract": "a" * 40, "level_key": "level1"}, "level_key"),
        ({"pmid": "X-4", "title": "t", "abstract": "a" * 40,
          "summary_is_model_written": True}, "paraphrase"),
    ])
    def test_the_writer_refuses_what_a49_removed(self, bad_record, why):
        import ingest_aae_guidelines as I
        with pytest.raises(I.GuidelineRecordRejected):
            I.upsert_guideline(bad_record, dry_run=True)


class TestReversibility:

    def test_quarantine_reason_is_the_undo(self):
        """Every status-driven exclusion is a reversible column write, not a
        deletion -- the same machinery as c7d7540."""
        rows = query("SELECT COUNT(*) FROM endo_papers_rag "
                     "WHERE COALESCE(guideline_id,'') <> '' "
                     "AND COALESCE(quarantine_reason,'') <> ''")
        assert rows[0][0] >= 4, "withdrawn/draft records should be quarantined"
        gone = query("SELECT COUNT(*) FROM endo_papers_rag "
                     "WHERE COALESCE(guideline_id,'') <> ''")
        assert gone[0][0] >= 55, "records were deleted rather than marked"
