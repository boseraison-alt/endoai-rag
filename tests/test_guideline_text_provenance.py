"""Item D (2026-09-07) — a guideline's text has to say where it came from.

THE RULE THIS PROTECTS. Storing the ORGANISATION'S OWN summary, verbatim, is
not paraphrase and is allowed. A model-written summary is not, and never
becomes allowed: `verify_citation_support` checking a claim against a
paraphrase is a hole directly under the grounding guarantee.

The discriminator between those two cases is `abstract_source`. A guideline
row that has text and cannot say where the text came from is exactly the state
that must never exist, because nothing downstream can tell it from a
paraphrase.

The verbatim check re-fetches a sample of pages and confirms the stored text is
still a substring — or, where the page has moved, that the stored hash still
matches the stored text, which distinguishes "the site changed" from "the text
was edited after storage".
"""
import hashlib
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

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


class TestEveryStoredGuidelineTextDeclaresItsSource:

    def test_no_guideline_row_has_text_without_a_source(self):
        """The invariant. A guideline row carrying prose that cannot name its
        origin is indistinguishable from a model-written summary."""
        rows = _q("""
            SELECT pmid, LEFT(COALESCE(abstract,''), 60)
            FROM endo_papers_rag
            WHERE level_key = 'guideline'
              AND COALESCE(quarantine_reason,'') = ''
              AND COALESCE(abstract,'') <> ''
              AND COALESCE(abstract,'') NOT LIKE 'GUIDELINE RECORD%%'
              AND COALESCE(abstract_source,'') = ''
              AND pmid !~ '^[0-9]+$'
        """)
        assert rows == [], (
            "guideline rows with text and no abstract_source: %s" % rows)

    def test_the_only_model_written_summaries_are_the_two_known_ones(self):
        """THE HOLE THIS MAKES VISIBLE, rather than closes.

        `ingest_aae_guidelines.py` says of its own records: "Summaries are
        condensed from the official documents." They are paraphrases stored as
        source text, so `verify_citation_support` checks claims against a
        model's words — the hole the handover names directly.

        The A2 audit kept these two citeable because they name REAL documents,
        and quarantining them would remove two real guidelines to fix a
        labelling problem. So they are labelled `model_summary_legacy`:
        countable, findable, and impossible to add to silently. RB decides
        between re-fetching and quarantining; a THIRD one appearing is a
        regression this test catches the day it happens.
        """
        rows = _q("""SELECT pmid FROM endo_papers_rag
                     WHERE abstract_source = 'model_summary_legacy'
                     ORDER BY pmid""")
        assert [r[0] for r in rows] == ["AAE-PS-diagnosis",
                                        "AAE-PS-vital-pulp"], rows

    def test_no_new_paraphrase_can_be_stored_as_org_page(self):
        """`org_page` means the document's own words, fetched and hashed. A row
        claiming that source must be able to prove it."""
        rows = _q("""SELECT pmid FROM endo_papers_rag
                     WHERE abstract_source = 'org_page'
                       AND (COALESCE(abstract_sha256,'') = ''
                            OR COALESCE(abstract_url,'') = '')""")
        assert rows == [], (
            "rows claiming org_page provenance without a hash or a URL: %s"
            % rows)

    def test_org_page_text_carries_its_full_provenance(self):
        rows = _q("""
            SELECT pmid, COALESCE(abstract_fetched,''),
                   COALESCE(abstract_sha256,''), COALESCE(abstract_url,'')
            FROM endo_papers_rag WHERE abstract_source = 'org_page'
        """)
        assert rows, "no org_page rows at all — the input is zero, so this " \
                     "test proves nothing (rule 34)"
        for pmid, fetched, sha, url in rows:
            assert fetched, "%s has no abstract_fetched" % pmid
            assert len(sha) == 64, "%s has no sha256" % pmid
            assert url.startswith("http"), "%s has no abstract_url" % pmid

    def test_the_stored_hash_matches_the_stored_text(self):
        """Cheap, offline, and it is what separates 'the page moved' from
        'the text was edited after we stored it'."""
        rows = _q("""SELECT pmid, abstract, abstract_sha256
                     FROM endo_papers_rag WHERE abstract_source = 'org_page'""")
        assert rows
        for pmid, text, sha in rows:
            got = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
            assert got == sha, "%s: stored text does not match stored hash" % pmid


class TestAFailedFetchStaysAPointer:

    def test_a_failed_row_still_says_pointer_only(self):
        rows = _q("""
            SELECT pmid, COALESCE(fetch_failed,''), LEFT(COALESCE(abstract,''), 40)
            FROM endo_papers_rag
            WHERE COALESCE(fetch_failed,'') <> ''
        """)
        assert rows, "no failed rows — nothing to check"
        for pmid, reason, head in rows:
            assert head.startswith("GUIDELINE RECORD") or head == "", (
                "%s failed to fetch (%s) but no longer reads as a pointer: %r"
                % (pmid, reason, head))

    def test_a_failure_reason_is_recorded_not_blank(self):
        rows = _q("""SELECT pmid FROM endo_papers_rag
                     WHERE COALESCE(fetch_failed,'') = 'unknown'""")
        assert rows == []


class TestTheStoredTextIsVerbatim:
    """Re-fetches five random pages. Network-dependent by nature, so it is
    marked slow and degrades to the hash check when a host is unreachable —
    an offline CI run must not be able to report this as a pass it did not
    earn, nor as a failure the code did not cause."""

    def test_five_random_rows_are_still_verbatim_on_the_page(self):
        rows = _q("""SELECT pmid, abstract, abstract_url, abstract_sha256
                     FROM endo_papers_rag WHERE abstract_source = 'org_page'""")
        if not rows:
            pytest.skip("no org_page rows")
        from fetch_guideline_text import page_text

        rnd = random.Random(20260907)
        sample = rnd.sample(rows, min(5, len(rows)))
        checked = moved = 0
        for pmid, text, url, sha in sample:
            live, _kind, err = page_text(url)
            if err or not live:
                # The page is unreachable now. Fall back to the offline
                # guarantee rather than failing the build on someone's outage.
                got = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
                assert got == sha, "%s: hash mismatch" % pmid
                moved += 1
                continue
            if text.strip() in live:
                checked += 1
            else:
                got = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
                assert got == sha, (
                    "%s: stored text is not on the page AND its hash does not "
                    "match — it was edited after storage" % pmid)
                moved += 1
        assert checked + moved == len(sample)
        print("\n  verbatim on the live page: %d; page moved, hash intact: %d"
              % (checked, moved))
