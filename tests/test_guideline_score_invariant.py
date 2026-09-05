"""A49's endgame invariant: a citeable guideline row carries NO score.

    no row at level_key='guideline' with an empty quarantine_reason
    carries a non-NULL score

WHY THIS IS THE INVARIANT AND NOT A TIDY-UP. A guideline is not on the
study-design ladder. It is a specialty's stated position, ranked by authority
and jurisdiction, and the library's score is computed by a therapy-shaped
scorer that gives a position statement no credit for a comparison it never made
or a follow-up it never had. A49 established this and all 60 seed records store
NULL; `rag_results_to_scored` coalesces that to 0.0 only so downstream sorts do
not raise, and the renderer prints "NOT SCORED" rather than "0.0/100" because
"no score" must not read as "scores zero".

Five rows never got the memo, and they were the ones that mattered:

    AAE-PS-diagnosis   90.0    AAE-PS-vital-pulp  90.0
    ESE-PS-VPT-2019    87.0    ESE-QG-2006        50.4
    39578680           59.3

No genuine paper in the library scores above 85.9, so three of these outranked
every real systematic review in the corpus -- including the Schwendicke
Cochrane review at 81.5 -- on a scale they are not on.

THE FIRST FOUR ARE THE ROWS THE A2 AUDIT KEPT. It verified they name real
documents, and verification settled whether the document exists; it never
touched the score. So the score-as-authority defect A49 was built to remove
survived on exactly the four rows that were kept because they are citeable.
That is the shape worth remembering: an audit that answers the question it was
asked, on rows it correctly declines to quarantine, and leaves a different
defect standing on them.

THE FIFTH WAS ADDED ON REVIEW. PMID 39578680 is a real Dent Traumatol position
statement with a legitimately COMPUTED score. An earlier report of mine set it
aside as "different: real accession, computed score". That distinction does not
survive this invariant -- A49's principle is about the TIER, not the provenance
of the number.

QUARANTINED ROWS ARE OUT OF SCOPE, deliberately. The twelve A2 rows keep their
90.0 because `quarantine_unverified_guidelines.py --restore` promises to put
them back exactly as they were. The invariant is about rows that can reach an
answer, which is what it is for.
"""
import pytest

import endo_ai as E

NULLED = ["AAE-PS-diagnosis", "AAE-PS-vital-pulp", "ESE-PS-VPT-2019",
          "ESE-QG-2006", "39578680"]

DUPLICATE_SLUG = "ESE-PS-VPT-2019"
DUPLICATE_OF = "30664240"


def _db():
    try:
        from rag import DATABASE_URL, get_conn
        if not DATABASE_URL:
            pytest.skip("DATABASE_URL not set")
        return get_conn()
    except Exception as e:      # pragma: no cover
        pytest.skip("library unreachable: %s" % e)


def _q(sql, args=()):
    conn = _db()
    cur = conn.cursor()
    try:
        cur.execute(sql, args)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


class TestTheInvariant:

    def test_no_citeable_guideline_row_carries_a_score(self):
        rows = _q("""
            SELECT pmid, score, title FROM endo_papers_rag
            WHERE level_key = 'guideline'
              AND COALESCE(quarantine_reason, '') = ''
              AND score IS NOT NULL
            ORDER BY score DESC
        """)
        assert rows == [], (
            "guideline rows carrying a score: "
            + "; ".join("%s=%s (%s)" % (r[0], r[1], (r[2] or "")[:40])
                        for r in rows))

    def test_the_tier_is_not_empty(self):
        """Rule 4 -- the assertion above passes trivially if the tier is empty
        or the level_key was renamed. This fails when that happens."""
        n = _q("""SELECT COUNT(*) FROM endo_papers_rag
                  WHERE level_key = 'guideline'
                    AND COALESCE(quarantine_reason, '') = ''""")[0][0]
        assert n >= 50, "only %d citeable guideline rows -- tier looks wrong" % n

    @pytest.mark.parametrize("pmid", NULLED)
    def test_each_named_row_is_now_null(self, pmid):
        rows = _q("SELECT score FROM endo_papers_rag WHERE pmid = %s", (pmid,))
        assert rows, "%s went missing -- nothing here deletes rows" % pmid
        assert rows[0][0] is None, "%s still carries %s" % (pmid, rows[0][0])

    def test_no_other_tier_lost_its_scores(self):
        """The delta the dry run promised: guideline only. A script that
        nulled a score outside the guideline tier would be deleting evidence,
        and this is the assertion that would have caught it."""
        rows = _q("""
            SELECT level_key, COUNT(*) - COUNT(score) AS n_null
            FROM endo_papers_rag
            WHERE COALESCE(quarantine_reason, '') = ''
              AND level_key NOT IN ('guideline', '')
            GROUP BY level_key HAVING COUNT(*) - COUNT(score) > 0
        """)
        assert rows == [], "tiers outside guideline carrying NULL scores: %s" % rows


class TestTheDuplicateIsQuarantinedNotRenamed:
    """ESE-PS-VPT-2019 is a second, unverified copy of a document already in
    the library in verified form. It is made unciteable; it is not renamed
    (choosing a title is inventing bibliographic data) and not deleted (RB
    decides removal)."""

    def test_the_slug_row_is_quarantined_as_a_duplicate(self):
        rows = _q("SELECT COALESCE(quarantine_reason,'') FROM endo_papers_rag "
                  "WHERE pmid = %s", (DUPLICATE_SLUG,))
        assert rows and rows[0][0] == "duplicate_of:" + DUPLICATE_OF

    def test_the_document_it_duplicates_is_present_and_verified(self):
        """The quarantine is only safe BECAUSE the real record is here. If it
        were not, this would be removing the document from the library."""
        rows = _q("""SELECT title, score, guideline_id, guideline_confidence,
                            COALESCE(quarantine_reason,'')
                     FROM endo_papers_rag WHERE pmid = %s""", (DUPLICATE_OF,))
        assert rows, "PMID 30664240 is not in the library"
        title, score, gid, conf, qr = rows[0]
        assert qr == "", "the surviving copy must stay citeable"
        assert score is None, "and it must obey the invariant too"
        assert gid == "ESE-DEEPCARIES-2019"
        assert conf == "confirmed"
        assert "management of deep caries" in (title or "").lower()

    def test_the_slug_row_was_not_renamed(self):
        """It keeps its wrong title on purpose. A quarantined row is a record
        of what was there, and correcting the title by inference is the error
        being cleaned up."""
        rows = _q("SELECT title FROM endo_papers_rag WHERE pmid = %s",
                  (DUPLICATE_SLUG,))
        assert rows and "Outcome of Primary Root Canal Treatment" in rows[0][0]

    def test_it_is_not_deleted(self):
        assert _q("SELECT COUNT(*) FROM endo_papers_rag WHERE pmid = %s",
                  (DUPLICATE_SLUG,))[0][0] == 1


class TestItIsReversible:

    def test_every_nulled_score_was_backed_up_first(self):
        rows = _q("""SELECT pmid, score FROM endo_papers_rag_score_backup
                     WHERE run_id LIKE 'null_guideline_scores_%%'""")
        got = {r[0]: r[1] for r in rows}
        for pmid in NULLED:
            assert pmid in got, "%s was nulled with no backup row" % pmid
            assert got[pmid] is not None
        assert got.get("AAE-PS-diagnosis") == pytest.approx(90.0)
        assert got.get("39578680") == pytest.approx(59.3, abs=0.05)

    def test_the_prior_quarantine_state_was_backed_up(self):
        rows = _q("""SELECT prior_quarantine_reason FROM
                     endo_papers_rag_quarantine_backup WHERE pmid = %s""",
                  (DUPLICATE_SLUG,))
        assert rows, "no quarantine backup for the duplicate"
        assert "" in [r[0] for r in rows], "prior state was 'not quarantined'"


class TestTheRendererAlreadyHandlesIt:
    """No renderer change was needed, and this says why rather than leaving it
    to be inferred: the NOT SCORED branch keys off `score is None`, which these
    rows now satisfy."""

    def test_a_nulled_guideline_renders_not_scored(self):
        line = E.format_paper_context_line({
            "pmid": "AAE-PS-diagnosis", "authors": "AAE", "year": "2009",
            "citations": 0, "level_key": "guideline", "score": None,
            "guideline_org": "AAE", "guideline_status": "current",
            "guideline_jurisdiction": "US"})
        assert "NOT SCORED" in line
        assert "0.0/100" not in line
        assert "Evidence Score" not in line
