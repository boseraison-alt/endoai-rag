"""Item A (2026-09-08) — a PMID-keyed guideline row's own text is its PubMed
abstract, and every stored text says where it came from.

RULE 40, WHICH THIS PINS. On 2026-09-07 `fetch_guideline_text.py` went to the
PUBLISHER's page for all 72 pointer rows and collected 29 HTTP 403s: aae.org
and Wiley refuse automated fetches. 23 of those rows carry a numeric PMID, and
for those the document's own text was already on PubMed — reachable through the
same efetch client that read 200 rows that same night without a single 403.
The instrument was wrong, not the corpus. Pointers: 45 -> 15.

THE DEFECT THIS FILE ALSO CATCHES, found only after the write was applied.
Re-keying a slug to its PubMed accession moves every citation to the new row.
Retiring `AAE-VPT-2021` stranded the AAE's own words for vital pulp therapy —
browser-fetched precisely because the publisher 403s everything else — on the
quarantined row, while `34352305`, which inherited its citations, had no text
at all. Nothing failed; the library just quietly stopped being able to quote
the AAE. `test_no_text_is_stranded_on_a_retired_row` is that alarm.

Every DB property here proves it can fail: each writes a violating row inside a
transaction, asserts the detector fires, and rolls back. A property test that
has never been shown to fail is a claim about the database, not a test.
"""
import hashlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import psycopg2.extras  # noqa: E402

import rag  # noqa: E402

import fetch_guideline_pubmed_abstracts as FETCH  # noqa: E402

TEXT_SOURCES = ("pubmed", "org_page", "org_page_browser")

# Real rows, read from the library 2026-09-08 after the item was applied.
# Not invented, and not taken from a reference list (the Hoang 2026 rule).
ESE_ECR_2018 = "30171768"        # abstract came from PubMed on the re-run
AAE_VPT_2021 = "34352305"        # PubMed has none; carries the AAE's own words


@pytest.fixture(scope="module")
def conn():
    c = rag.get_conn()
    yield c
    c.close()


def _cursor(conn):
    """`rag.get_conn()` hands back tuple cursors; every query here reads its
    columns by name."""
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _rows(conn, sql, args=()):
    cur = _cursor(conn)
    cur.execute(sql, args)
    out = cur.fetchall()
    cur.close()
    return out


class TestTheUsabilityRule:
    """The floor decides whether a row keeps its pointer. Driven, not read."""

    def test_a_real_abstract_is_usable(self):
        assert FETCH.usable_abstract(
            "The European Society of Endodontology presents this position "
            "statement on external cervical resorption, setting out current "
            "understanding of aetiology, classification and management for "
            "practitioners across Europe.")

    def test_a_publisher_one_liner_is_not_text(self):
        """This is the whole point of the floor. PubMed's abstract slot
        sometimes holds a copyright line or a bare objective; storing it as
        the document's text looks like an abstract to every downstream reader
        and says less than the pointer it replaced."""
        assert not FETCH.usable_abstract("This article has been withdrawn.")
        assert not FETCH.usable_abstract("© 2020 American Dental Association.")

    def test_nothing_is_usable(self):
        assert not FETCH.usable_abstract("")
        assert not FETCH.usable_abstract(None)
        assert not FETCH.usable_abstract("   \n  ")

    def test_the_floor_is_where_it_says_it_is(self):
        assert not FETCH.usable_abstract(" ".join(["word"] * 19))
        assert FETCH.usable_abstract(" ".join(["word"] * 20))

    def test_lowering_the_floor_admits_a_publisher_one_liner(self, monkeypatch):
        """MUTATION CHECK — the rule is run with the floor moved, not read.

        With the floor at 1, the withdrawal notice above becomes the stored
        text of a guideline. That this changes the answer is what proves the
        assertions above are load-bearing.
        """
        note = "This article has been withdrawn."
        assert not FETCH.usable_abstract(note)
        monkeypatch.setattr(FETCH, "MIN_ABSTRACT_WORDS", 1)
        assert FETCH.usable_abstract(note), (
            "the floor is not consulted at call time — the tests above pass "
            "for a reason other than the rule they claim to check")


class TestStoredTextCarriesItsProvenance:

    def test_no_guideline_text_is_anonymous(self, conn):
        """THE BATCH'S MUTATION CHECK: store a fetched abstract without
        `abstract_source`, watch it fail."""
        bad = _rows(conn, """
            SELECT pmid, left(title, 60) AS title
            FROM endo_papers_rag
            WHERE level_key = 'guideline'
              AND COALESCE(quarantine_reason, '') = ''
              AND COALESCE(abstract_source, '') = ''
              AND abstract IS NOT NULL
              AND abstract NOT LIKE 'GUIDELINE RECORD%%'
        """)
        assert not bad, (
            "%d guideline row(s) hold text that names no source: %s"
            % (len(bad), [(r["pmid"], r["title"]) for r in bad[:5]]))

    def test_that_detector_fires(self, conn):
        """The same query, run against a deliberately broken row, rolled back.

        Without this the test above is a statement about today's database.
        """
        cur = _cursor(conn)
        try:
            cur.execute("""
                UPDATE endo_papers_rag
                SET abstract = 'Fetched text with no provenance whatsoever.',
                    abstract_source = ''
                WHERE pmid = %s
            """, (ESE_ECR_2018,))
            cur.execute("""
                SELECT COUNT(*) AS n FROM endo_papers_rag
                WHERE level_key = 'guideline'
                  AND COALESCE(quarantine_reason, '') = ''
                  AND COALESCE(abstract_source, '') = ''
                  AND abstract IS NOT NULL
                  AND abstract NOT LIKE 'GUIDELINE RECORD%%'
            """)
            assert cur.fetchone()["n"] >= 1, (
                "an anonymous abstract did not trip the detector")
        finally:
            conn.rollback()
            cur.close()

    def test_the_stored_hash_matches_the_stored_text(self, conn):
        """`abstract_sha256` is the receipt. If it does not match the text
        beside it, the column is decoration and any later 'has this changed?'
        answer is worthless.

        FETCHED-SPAN SOURCES ONLY. `org_page_browser` is excluded on purpose,
        not because it fails: for those rows the column hashes the SOURCE FILE
        so the verifiable chain is file -> sidecar -> row, which
        `tests/test_guideline_text_provenance.py` checks end to end. The first
        version of this test asserted one meaning across all three sources and
        convicted 14 correct rows — the column has two writers and two
        meanings (rule 37), and a test has to know which one it is reading.
        """
        rows = _rows(conn, """
            SELECT pmid, abstract, abstract_sha256
            FROM endo_papers_rag
            WHERE abstract_source IN ('pubmed', 'org_page')
              AND COALESCE(abstract_sha256, '') <> ''
        """)
        assert rows, "no row carries a fetched abstract — fixture is stale"
        bad = [r["pmid"] for r in rows
               if hashlib.sha256(
                   r["abstract"].encode("utf-8")).hexdigest()
               != r["abstract_sha256"]]
        assert not bad, "stored hash does not match stored text: %s" % bad[:5]

    def test_the_two_meanings_of_the_hash_column_stay_separated(self, conn):
        """Pin the split so neither half is silently "fixed" into the other.

        A future pass that made `org_page_browser` hash its stored span would
        break the file -> sidecar -> row chain without failing anything else;
        one that made `org_page` hash a file would break re-verification
        against the live page. Both directions are caught here.
        """
        span_hashed = _rows(conn, """
            SELECT pmid, abstract, abstract_sha256 FROM endo_papers_rag
            WHERE abstract_source = 'org_page'
              AND COALESCE(abstract_sha256, '') <> ''
        """)
        file_hashed = _rows(conn, """
            SELECT pmid, abstract, abstract_sha256 FROM endo_papers_rag
            WHERE abstract_source = 'org_page_browser'
              AND COALESCE(abstract_sha256, '') <> ''
        """)
        assert span_hashed and file_hashed, "one arm of the split is empty"
        assert all(hashlib.sha256(r["abstract"].encode("utf-8")).hexdigest()
                   == r["abstract_sha256"] for r in span_hashed), (
            "an org_page row stopped hashing its stored span")
        assert not any(
            hashlib.sha256(r["abstract"].encode("utf-8")).hexdigest()
            == r["abstract_sha256"] for r in file_hashed), (
            "an org_page_browser row now hashes its stored span — the "
            "file -> sidecar -> row chain is what that column is for")

    def test_a_pubmed_sourced_row_links_to_its_pubmed_record(self, conn):
        rows = _rows(conn, """
            SELECT pmid, COALESCE(abstract_url, '') AS url
            FROM endo_papers_rag WHERE abstract_source = 'pubmed'
        """)
        assert rows
        bad = [r["pmid"] for r in rows
               if r["url"] != "https://pubmed.ncbi.nlm.nih.gov/%s/" % r["pmid"]]
        assert not bad, "pubmed-sourced rows with a wrong URL: %s" % bad[:5]

    def test_every_fetched_row_records_when_it_was_fetched(self, conn):
        bad = _rows(conn, """
            SELECT pmid FROM endo_papers_rag
            WHERE abstract_source IN %s
              AND COALESCE(abstract_fetched::text, '') = ''
        """, (TEXT_SOURCES,))
        assert not bad, "fetched text with no fetch date: %s" % [
            r["pmid"] for r in bad[:5]]


class TestTheRealRowsThisItemProduced:

    def test_the_ese_resorption_statement_holds_its_pubmed_abstract(self, conn):
        r = _rows(conn, "SELECT abstract, abstract_source, level_key "
                        "FROM endo_papers_rag WHERE pmid = %s",
                  (ESE_ECR_2018,))
        assert r, "PMID %s is not in the library" % ESE_ECR_2018
        r = r[0]
        assert r["abstract_source"] == "pubmed"
        assert r["level_key"] == "guideline"
        assert FETCH.usable_abstract(r["abstract"])
        assert not r["abstract"].startswith("GUIDELINE RECORD"), (
            "still a pointer after the fetch")

    def test_the_aae_vpt_row_kept_the_aae_s_own_words_through_the_rekey(
            self, conn):
        """PubMed has no abstract for 34352305. Its text is the AAE's, fetched
        from aae.org in a browser session, and it survived the slug being
        re-keyed onto this accession — see the module docstring."""
        r = _rows(conn, "SELECT abstract, abstract_source, abstract_url "
                        "FROM endo_papers_rag WHERE pmid = %s",
                  (AAE_VPT_2021,))[0]
        assert r["abstract_source"] == "org_page_browser", (
            "the AAE's own words were lost in the re-key; source is %r"
            % r["abstract_source"])
        assert "aae.org" in (r["abstract_url"] or "")
        assert FETCH.usable_abstract(r["abstract"])

    def test_a_row_pubmed_cannot_supply_stays_a_pointer_and_says_why(
            self, conn):
        """The failure is recorded, not hidden. A row PubMed indexes without
        an abstract must be visibly a pointer, so the next fetch attempt is
        aimed at the publisher rather than repeated against PubMed."""
        rows = _rows(conn, """
            SELECT pmid, abstract FROM endo_papers_rag
            WHERE fetch_failed = 'pubmed_no_abstract'
              AND COALESCE(quarantine_reason, '') = ''
        """)
        assert rows, "no row records pubmed_no_abstract — did the item run?"
        for r in rows:
            assert (r["abstract"] or "").startswith("GUIDELINE RECORD"), (
                "%s is marked pubmed_no_abstract but is not a pointer"
                % r["pmid"])


class TestNoTextIsStrandedByAReKey:

    def test_no_text_is_stranded_on_a_retired_row(self, conn):
        """A retired row's text must not outrank an empty successor.

        This is the 2026-09-08 defect. Citations follow `redirect_to`; text
        does not, so re-keying a slug moved every citation onto a row with no
        abstract while the document's own words sat on the quarantined one.
        """
        bad = _rows(conn, """
            SELECT s.pmid AS retired, t.pmid AS target,
                   s.abstract_source AS src
            FROM endo_papers_rag s
            JOIN endo_papers_rag t ON t.pmid = s.redirect_to
            WHERE COALESCE(s.redirect_to, '') <> ''
              AND s.abstract_source IN %s
              AND COALESCE(t.abstract_source, '') = ''
        """, (TEXT_SOURCES,))
        assert not bad, (
            "%d document(s) have their own text on a retired row while the "
            "row that inherited their citations has none: %s"
            % (len(bad), [(r["retired"], "->", r["target"], r["src"])
                          for r in bad]))

    def test_that_detector_fires(self, conn):
        """Re-create the exact defect — blank the successor, keep the text on
        the retired row — and confirm the query above finds it."""
        cur = _cursor(conn)
        try:
            cur.execute("""
                UPDATE endo_papers_rag SET abstract_source = '', abstract = ''
                WHERE pmid = %s
            """, (AAE_VPT_2021,))
            cur.execute("""
                UPDATE endo_papers_rag SET abstract_source = 'org_page_browser'
                WHERE pmid = 'AAE-VPT-2021'
            """)
            cur.execute("""
                SELECT COUNT(*) AS n FROM endo_papers_rag s
                JOIN endo_papers_rag t ON t.pmid = s.redirect_to
                WHERE COALESCE(s.redirect_to, '') <> ''
                  AND s.abstract_source IN %s
                  AND COALESCE(t.abstract_source, '') = ''
            """, (TEXT_SOURCES,))
            assert cur.fetchone()["n"] >= 1, (
                "the stranding detector did not fire on a stranded row")
        finally:
            conn.rollback()
            cur.close()
