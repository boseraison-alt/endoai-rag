"""Item A (2026-09-07) — re-keying a guideline record, and the redirect.

THE DEFECT. A manifest record whose PubMed accession is unknown is keyed by its
slug and INSERTED, because the ingest dedupes by PMID and a record with no PMID
cannot dedupe against anything. When the accession is later verified, the same
document is in the library twice under two keys — and, because the insert
branch hardcodes `level_key='guideline'`, at two tiers:

    COCHRANE-CD005296   guideline   score NULL     one Cochrane review
    36512807            cochrane    score 73.7     two rows, two rungs

    COCHRANE-CD004969   guideline   score NULL     the other
    31145805            cochrane    score 63.7

Eleven `unconfirmed_pmid` records remain in the manifest, so this will recur
once per verified accession. The fix is a general re-keying step.

FIXTURES ARE THE REAL PRE-A ROWS, read from the 2026-09-07 pre-A dump
(`db-20260907-preA/endo_papers_rag.csv.gz`) before the ingest ran.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import endo_ai as E
from rag import get_conn


def _q(sql, args=None):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(sql, args or ())
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


# The real pair, as it stood before item A ran.
SLUG = "COCHRANE-CD005296"
TARGET = "36512807"
SLUG2 = "COCHRANE-CD004969"
TARGET2 = "31145805"


class TestTheSlugRowIsRetiredNotDeleted:

    @pytest.mark.parametrize("slug,target",
                             [(SLUG, TARGET), (SLUG2, TARGET2)])
    def test_the_slug_row_still_exists(self, slug, target):
        """Nothing is deleted. `quarantine_reason` is the undo."""
        rows = _q("SELECT pmid, title FROM endo_papers_rag WHERE pmid = %s",
                  (slug,))
        assert len(rows) == 1, "%s was deleted, not retired" % slug
        assert (rows[0][1] or "").strip(), "%s lost its title" % slug

    @pytest.mark.parametrize("slug,target",
                             [(SLUG, TARGET), (SLUG2, TARGET2)])
    def test_it_is_quarantined_and_points_at_its_replacement(self, slug, target):
        rows = _q("SELECT COALESCE(quarantine_reason,''), redirect_to "
                  "FROM endo_papers_rag WHERE pmid = %s", (slug,))
        reason, redirect = rows[0]
        assert reason == "re-keyed: this document is %s" % target, reason
        assert redirect == target, redirect

    @pytest.mark.parametrize("slug", [SLUG, SLUG2])
    def test_its_guideline_id_is_cleared(self, slug):
        """Two rows carrying one guideline id IS the duplicate. Leaving the id
        on the retired row would keep `test_no_duplicate_guideline_ids`
        failing while claiming the duplicate was fixed."""
        rows = _q("SELECT COALESCE(guideline_id,'') FROM endo_papers_rag "
                  "WHERE pmid = %s", (slug,))
        assert rows[0][0] == "", "retired row still claims a guideline id"

    @pytest.mark.parametrize("target,gid,score",
                             [(TARGET, SLUG, 73.7), (TARGET2, SLUG2, 63.7)])
    def test_the_surviving_row_keeps_its_tier_and_score(self, target, gid,
                                                        score):
        """A Cochrane review's rung is a study-design fact and the manifest has
        no authority over it. The enrichment adds identity, never a tier."""
        rows = _q("SELECT level_key, score, guideline_id, guideline_org "
                  "FROM endo_papers_rag WHERE pmid = %s", (target,))
        lk, sc, g, org = rows[0]
        assert lk == "cochrane", "%s moved to %r" % (target, lk)
        assert sc is not None and abs(float(sc) - score) < 0.05, sc
        assert g == gid
        assert org == "COCHRANE"

    def test_no_guideline_id_is_claimed_by_two_rows(self):
        rows = _q("""SELECT guideline_id, COUNT(*) FROM endo_papers_rag
                     WHERE COALESCE(guideline_id,'') <> ''
                     GROUP BY guideline_id HAVING COUNT(*) > 1""")
        assert rows == [], "guideline ids on more than one row: %s" % rows

    def test_an_already_quarantined_row_is_terminal(self):
        """ESE-QG-2006 was retired by the A2 audit as `duplicate_of:17180780`.
        The re-key step must not overwrite that with the same fact in
        different words — two tests pin the exact string, and the A2 audit's
        provenance is worth more than a uniform reason."""
        rows = _q("SELECT COALESCE(quarantine_reason,'') FROM endo_papers_rag "
                  "WHERE pmid = 'ESE-QG-2006'")
        assert rows and rows[0][0] == "duplicate_of:17180780", rows


class TestTheFinaliserRewritesARetiredCitation:

    def setup_method(self):
        E._reset_redirect_map()

    def test_a_citation_of_a_retired_key_is_rewritten(self):
        out, rewrites = E.rewrite_redirected_citations(
            "Single-visit treatment is no better [[PMID:%s]]." % SLUG)
        assert "[[PMID:%s]]" % TARGET in out, out
        assert SLUG not in out, out
        assert rewrites == [(SLUG, TARGET)]

    def test_the_reference_list_form_is_rewritten_too(self):
        out, rewrites = E.rewrite_redirected_citations(
            "1. [PMID: %s] Mergoni G et al. — Cochrane review." % SLUG)
        assert TARGET in out and SLUG not in out, out
        assert len(rewrites) == 1

    def test_a_numeric_citation_is_untouched(self):
        text = "Healing was comparable [[PMID:27759881]]."
        out, rewrites = E.rewrite_redirected_citations(text)
        assert out == text and rewrites == []

    def test_an_unrelated_slug_is_untouched(self):
        """THE CONTROL IS RESOLVED, NOT NAMED (rule 39).

        This was `AAE-VPT-2021` until 2026-09-08, when that record was itself
        re-keyed onto its PubMed accession — so the "unrelated, untouched"
        control acquired a redirect and the test failed for being right. The
        property is "a slug with no redirect_to is left alone", so ask the
        library for one instead of naming one that can be re-keyed next.
        """
        from rag import DATABASE_URL, get_conn
        if not DATABASE_URL:
            pytest.skip("DATABASE_URL not set")
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT pmid FROM endo_papers_rag
                WHERE level_key = 'guideline'
                  AND COALESCE(quarantine_reason, '') = ''
                  AND COALESCE(redirect_to, '') = ''
                  AND pmid !~ '^[0-9]+$'
                ORDER BY pmid LIMIT 1
            """)
            row = cur.fetchone()
            cur.close()
        finally:
            conn.close()
        assert row, "no un-redirected slug row to use as a control"
        text = "The position says so [[PMID:%s]]." % row[0]
        out, rewrites = E.rewrite_redirected_citations(text)
        assert out == text and rewrites == []

    def test_the_rewrite_survives_the_whole_finaliser(self):
        """The point of the item: a stored answer citing the old key must come
        out of `finalise_answer_text` citing the new one — NOT dropped by G2,
        which is what would happen without the rewrite, because a retired row
        is a quarantined row."""
        text = ("## Answer\n\nSingle-visit and multiple-visit treatment do not "
                "differ in healing [[PMID:%s]] for necrotic teeth.\n" % SLUG)
        out, _blocks = E.finalise_answer_text(text)
        assert TARGET in out, (
            "the citation was lost instead of redirected: %r" % out)
        assert SLUG not in out, out

    def test_a_retired_key_would_otherwise_be_dropped_by_g2(self):
        """Proves the ordering matters rather than asserting it. G2 alone, with
        no rewrite, removes the citation — so the rewrite has to run first."""
        text = "Healing was comparable [[PMID:%s]]." % SLUG
        out, dropped = E.drop_unresolvable_citations(text)
        assert SLUG in [d.strip() for d in dropped], (
            "G2 no longer drops a quarantined key, so this test no longer "
            "shows why the rewrite must precede it: %s" % dropped)
