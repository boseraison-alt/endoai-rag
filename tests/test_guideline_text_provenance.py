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

    def test_no_citeable_row_carries_a_model_written_summary(self):
        """THE HOLE, NOW CLOSED — and pinned as a property, not a name list.

        `ingest_aae_guidelines.py` says of its own records: "Summaries are
        condensed from the official documents." They are paraphrases stored as
        source text, so `verify_citation_support` was checking claims against a
        model's words — a hole directly under the grounding guarantee.

        This test used to assert the two known ids by name, which made the hole
        VISIBLE while leaving it open. Both are now retired (2026-09-07):

            AAE-PS-vital-pulp  -> AAE-VPT-2021        (AAE's own text)
            AAE-PS-diagnosis   -> AAE-DIAGNOSIS-2009

        so the assertion is the property that matters — **no citeable row
        anywhere carries a model-written summary**. A name list would pass
        again the moment a third one appeared under a different id; this
        cannot. Retired rows keep their label and their text, which is what
        makes the retirement reversible.
        """
        rows = _q("""SELECT pmid, LEFT(COALESCE(abstract,''), 50)
                     FROM endo_papers_rag
                     WHERE abstract_source = 'model_summary_legacy'
                       AND COALESCE(quarantine_reason,'') = ''
                     ORDER BY pmid""")
        assert rows == [], (
            "citeable rows whose stored text is a model-written summary: %s"
            % rows)

    def test_every_retired_row_still_resolves(self):
        """Retired, not deleted. 10 stored answers cite AAE-PS-vital-pulp and
        22 cite AAE-PS-diagnosis; each must still reach a citeable row, or the
        retirement broke 32 answers to fix 2 rows.

        SELECTED BY `redirect_to`, NOT BY `abstract_source` (rule 39).
        This used `abstract_source = 'model_summary_legacy'` as its way of
        naming the retired pair, and item F2 replaced that text with pointer
        text — so on 2026-09-08 the selector matched nothing and the test
        failed for having found no input rather than for a broken redirect.

        The identity was never "the rows with a paraphrase"; it is "the rows
        that were retired". Selecting on `redirect_to` says that directly, and
        it now covers all ten retired rows instead of two — the six re-keyed by
        item A and the two Cochrane slugs included.
        """
        rows = _q("""SELECT pmid, redirect_to
                     FROM endo_papers_rag
                     WHERE COALESCE(redirect_to,'') <> ''
                     ORDER BY pmid""")
        assert rows, "no retired rows at all — nothing checked (rule 34)"
        for pmid, redirect in rows:
            assert redirect, "%s was retired with no redirect_to" % pmid
            target = _q("""SELECT COALESCE(quarantine_reason,'')
                           FROM endo_papers_rag WHERE pmid = %s""", (redirect,))
            assert target, "%s redirects to %s, which does not exist" % (
                pmid, redirect)
            assert not target[0][0].strip(), (
                "%s redirects to %s, which is itself quarantined"
                % (pmid, redirect))

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


class TestBrowserFetchedTextIsTraceableToItsFile:
    """`org_page_browser` rows came from `data/guideline_text/<id>.txt`, fetched
    through a real Chrome session because aae.org returns 403 and
    prosthodontics.org returns an Imperva notice to anything else.

    `abstract_sha256` MEANS SOMETHING DIFFERENT FOR THESE ROWS and that is
    worth stating rather than discovering. For `org_page` it hashes the STORED
    SPAN; for `org_page_browser` it hashes the SOURCE FILE, as the batch
    specified. So the chain that can be re-verified is file -> sidecar -> row,
    and it is verified here rather than assumed.
    """

    def test_every_row_matches_its_sidecar_and_its_file(self):
        import glob
        import json
        rows = _q("""SELECT COALESCE(guideline_id, ''), abstract,
                            abstract_sha256, abstract_url, abstract_fetched
                     FROM endo_papers_rag
                     WHERE abstract_source = 'org_page_browser'
                       AND COALESCE(quarantine_reason, '') = ''""")
        assert rows, ("no org_page_browser rows — the input is zero, so this "
                      "proves nothing (rule 34)")
        files = {os.path.basename(p)[:-5]
                 for p in glob.glob("data/guideline_text/*.json")}
        assert files, "no sidecars on disk"
        # KEYED BY guideline_id, NOT BY ROW KEY (rule 39).
        #
        # These files are named for the manifest record. The row key is not:
        # re-keying AAE-VPT-2021 onto its PubMed accession 34352305 moved the
        # row and left the file where it was, and this test went looking for
        # `34352305.txt`. The repair is to the STABLE identity — the manifest
        # id, which is what the file was always named for — not to a second
        # accepted filename.
        for pmid, text, sha, url, fetched in rows:
            assert pmid in files, (
                "%s claims browser provenance with no sidecar on disk" % pmid)
            meta = json.load(open("data/guideline_text/%s.json" % pmid,
                                  encoding="utf-8"))
            raw = open("data/guideline_text/%s.txt" % pmid, "rb").read()
            assert hashlib.sha256(raw).hexdigest() == meta["sha256"], (
                "%s: the .txt no longer matches its sidecar hash" % pmid)
            assert sha == meta["sha256"], (
                "%s: stored hash is not the sidecar's" % pmid)
            assert url == meta["url"], "%s: stored url is not the sidecar's" % pmid
            assert fetched == meta["fetched_at"], pmid

    def test_the_stored_text_is_verbatim_from_the_file(self):
        """The whole claim. Every stored word must appear, in order, in the
        file RB fetched — no paraphrase, no reflow, no repair."""
        rows = _q("""SELECT COALESCE(guideline_id, ''), abstract
                     FROM endo_papers_rag
                     WHERE abstract_source = 'org_page_browser'
                       AND COALESCE(quarantine_reason, '') = ''""")
        assert rows
        for pmid, text in rows:      # keyed by guideline_id — see above
            src = open("data/guideline_text/%s.txt" % pmid,
                       encoding="utf-8").read()
            # Compared against the file WITH `[[PAGE n]]` lines removed, which
            # is the one transform the ingest performs. Comparing against the
            # raw file fails on every PDF whose span crosses a page break —
            # the first version of this test did, and the failure was the
            # test's, not the ingest's.
            import re as _re
            src = "\n".join(
                l for l in src.splitlines()
                if not _re.match(r"\s*\[\[PAGE \d+\]\]\s*$", l))
            flat_src = " ".join(src.split())
            flat_txt = " ".join((text or "").split())
            assert flat_txt and flat_txt in flat_src, (
                "%s: stored text is not a verbatim span of its source file"
                % pmid)

    def test_no_page_marker_survives_into_a_stored_abstract(self):
        """RB's `[[PAGE n]]` markers are the fetch's, not the document's."""
        rows = _q("""SELECT pmid, abstract FROM endo_papers_rag
                     WHERE abstract_source = 'org_page_browser'
                       AND COALESCE(quarantine_reason, '') = ''""")
        for pmid, text in rows:
            assert "[[PAGE" not in (text or ""), pmid

    def test_no_span_ends_in_page_furniture(self):
        """AAE-VPT-2021's summary ends at '...also warranted.' and ran on into
        'Position StatementPage 5AAE Position S tatement - V ital Pulp Therapy'
        before the tail trim — the PDF's running head, not the document's
        summary.

        ASSERTED ON FURNITURE, NOT ON A FULL STOP. The first version required
        every span to end on sentence punctuation, and the six `first_300_words`
        spans end mid-sentence BY DESIGN — they are cut at a word budget. That
        assertion would have forced the ingest to distort a documented rule to
        satisfy a test.
        """
        import re as _re
        FURNITURE = _re.compile(r"(Page\s?\d|Position S\s?tatement|"
                                r"AAE Position|www\.|\.org)", _re.I)
        rows = _q("""SELECT pmid, abstract FROM endo_papers_rag
                     WHERE abstract_source = 'org_page_browser'
                       AND COALESCE(quarantine_reason, '') = ''""")
        assert rows
        bad = [p for p, t in rows if FURNITURE.search((t or "")[-80:])]
        assert not bad, "spans ending in page furniture: %s" % bad


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
