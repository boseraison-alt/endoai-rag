"""A49/A2 — no answer may cite a quarantined guideline record.

Twelve of the sixteen hardcoded guideline records name documents that could
not be verified against the 60-entry manifest: six are dated to an edition
that does not exist, six name no document at all. They sit in the library at
score 90.0, which outranks 100% of the 3,192 real evidence rows, and 103
stored answers cite one.

WHAT IS PINNED HERE, AND AT WHICH LAYER

  retrieval   a quarantined row never enters a candidate pool, on all three
              SQL branches including the follow-up seeding path
  citation    a quarantined slug is not in the resolvable key set, so G2 drops
              any citation to it — on freshly synthesised answers AND on the
              cached-answer serve path, which is what reaches the 103
  untouched   the four A2-verified records and the five genuinely
              PubMed-indexed guidelines still work

The retrieval and citation layers are pinned SEPARATELY and the wiring is
pinned as well as the helper. Two suites passed against a broken fix on
2026-09-04 because every test called a helper directly and none checked that
production called it (standing rule 14).

REVERSIBILITY IS PART OF THE CONTRACT. Nothing is deleted, and
`scripts/quarantine_unverified_guidelines.py --restore` is tested to put every
row back. RB decides removal; this only makes them unciteable meanwhile.
"""

import pytest

import endo_ai as E

QUARANTINED = [
    # six WRONG YEAR — the organisation publishes on the subject, but not in
    # the year the record claims
    "AAE-PS-antibiotics", "AAE-PS-cbct", "AAE-PS-microscope",
    "AAE-PS-regenerative", "AAE-PS-trauma", "ESE-QG-2023",
    # six NO SUCH DOCUMENT anywhere in the manifest
    "AAE-PS-cracked-tooth", "AAE-PS-implant-v-endo", "AAE-PS-isolation",
    "AAE-PS-obturation", "AAE-PS-retreatment", "AAE-PS-safety",
]

VERIFIED = [
    "AAE-PS-diagnosis", "AAE-PS-vital-pulp", "ESE-QG-2006", "ESE-PS-VPT-2019",
]

# Real, PubMed-indexed guidelines that also sit at level_key='guideline'.
# They were never in scope and this is the guard that says so.
REAL_PMID_GUIDELINES = ["28436043", "31668170", "36942472", "37772327", "39578680"]


def _db():
    try:
        from rag import DATABASE_URL, get_conn
        if not DATABASE_URL:
            pytest.skip("DATABASE_URL not set")
        return get_conn()
    except Exception as e:      # pragma: no cover
        pytest.skip("library unreachable: %s" % e)


@pytest.fixture
def fresh_key_cache():
    """G2 caches the resolvable key set process-wide. Clear it around each
    test so one test's read cannot decide another's result."""
    E._KNOWN_SYNTHETIC_KEYS = None
    yield
    E._KNOWN_SYNTHETIC_KEYS = None


# ── the database state ───────────────────────────────────

class TestTheRowsAreMarked:

    def test_all_twelve_carry_a_reason(self):
        conn = _db()
        cur = conn.cursor()
        try:
            cur.execute("SELECT pmid, COALESCE(quarantine_reason,'') "
                        "FROM endo_papers_rag WHERE pmid = ANY(%s)",
                        (QUARANTINED,))
            got = dict(cur.fetchall())
        finally:
            cur.close()
            conn.close()
        assert sorted(got) == sorted(QUARANTINED), "a record went missing"
        for slug in QUARANTINED:
            assert got[slug], f"{slug} is not quarantined"

    def test_the_reason_says_which_of_the_two_failures_it_is(self):
        """A bare boolean would erase the distinction that decides the remedy:
        a wrong-year record has a real document behind it and can be
        re-pointed; a no-such-document record cannot."""
        conn = _db()
        cur = conn.cursor()
        try:
            cur.execute("SELECT pmid, quarantine_reason FROM endo_papers_rag "
                        "WHERE pmid = ANY(%s)", (QUARANTINED,))
            got = dict(cur.fetchall())
        finally:
            cur.close()
            conn.close()
        kinds = {}
        for slug, reason in got.items():
            kind = reason.split(":")[0]
            assert kind in ("wrong_year", "no_such_document"), (slug, reason)
            kinds.setdefault(kind, []).append(slug)
        assert len(kinds["wrong_year"]) == 6
        assert len(kinds["no_such_document"]) == 6

    def test_nothing_was_deleted(self):
        """Quarantine, not deletion — the row and its text must still be there
        for whoever decides its fate."""
        conn = _db()
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) FROM endo_papers_rag "
                        "WHERE pmid = ANY(%s) AND COALESCE(abstract,'') <> ''",
                        (QUARANTINED,))
            n = cur.fetchone()[0]
        finally:
            cur.close()
            conn.close()
        assert n == 12, f"only {n} of 12 quarantined rows still carry their text"

    @pytest.mark.parametrize("slug", VERIFIED)
    def test_the_four_verified_are_untouched(self, slug):
        conn = _db()
        cur = conn.cursor()
        try:
            cur.execute("SELECT COALESCE(quarantine_reason,'') "
                        "FROM endo_papers_rag WHERE pmid = %s", (slug,))
            row = cur.fetchone()
        finally:
            cur.close()
            conn.close()
        assert row is not None, f"{slug} is missing from the library"
        assert row[0] == "", f"{slug} was quarantined; A2 verified it as real"

    @pytest.mark.parametrize("pmid", REAL_PMID_GUIDELINES)
    def test_real_indexed_guidelines_are_untouched(self, pmid):
        """Five rows at level_key='guideline' are genuine PubMed records and
        were never in scope."""
        conn = _db()
        cur = conn.cursor()
        try:
            cur.execute("SELECT COALESCE(quarantine_reason,'') "
                        "FROM endo_papers_rag WHERE pmid = %s", (pmid,))
            row = cur.fetchone()
        finally:
            cur.close()
            conn.close()
        assert row is not None and row[0] == ""


# ── the citation layer ───────────────────────────────────

class TestNoAnswerCanCiteOne:

    @pytest.mark.parametrize("slug", QUARANTINED)
    def test_the_slug_is_not_resolvable(self, slug, fresh_key_cache):
        known = E._known_synthetic_keys()
        assert known is not None, "gate disabled — DB unreachable"
        assert slug not in known

    @pytest.mark.parametrize("slug", VERIFIED)
    def test_a_verified_slug_still_resolves(self, slug, fresh_key_cache):
        known = E._known_synthetic_keys()
        assert known is not None
        assert slug in known, (
            f"{slug} stopped resolving. A2 verified it against a real "
            f"document and the batch requires the four to keep working.")

    def test_a_citation_to_a_quarantined_record_is_dropped(self, fresh_key_cache):
        text = ("Antibiotics are not indicated for a localised abscess "
                "[[PMID:AAE-PS-antibiotics]].")
        out, dropped = E.drop_unresolvable_citations(text)
        assert "AAE-PS-antibiotics" not in out
        assert "AAE-PS-antibiotics" in dropped

    def test_a_citation_to_a_verified_record_survives(self, fresh_key_cache):
        text = ("Pulp status is assessed before treatment "
                "[[PMID:AAE-PS-diagnosis]].")
        out, dropped = E.drop_unresolvable_citations(text)
        assert "AAE-PS-diagnosis" in out
        assert dropped == []

    def test_the_drop_is_loud(self, fresh_key_cache, capsys):
        """Rule 32 and invariant 15. A silent drop is the fail-open that made
        a banner read 9/9 CONSISTENT over ten cited claims."""
        E.drop_unresolvable_citations("x [[PMID:AAE-PS-safety]]")
        assert "[G2]" in capsys.readouterr().out

    def test_the_wiring_not_just_the_helper(self, fresh_key_cache):
        """`finalise_answer_text` is what every answer path actually calls —
        including the cached-answer serve path, which is how this reaches the
        103 stored answers without rewriting a stored row. Calling
        `drop_unresolvable_citations` directly would pass even if nothing
        production runs called it (rule 14)."""
        text = ("The record says X [[PMID:AAE-PS-obturation]] and Y "
                "[[PMID:AAE-PS-vital-pulp]].")
        out = E.finalise_answer_text(text)
        served = out[0] if isinstance(out, tuple) else out
        assert "AAE-PS-obturation" not in served, (
            "a quarantined citation survived the finaliser every answer "
            "path goes through")
        assert "AAE-PS-vital-pulp" in served, (
            "the finaliser also dropped a VERIFIED record")


# ── the retrieval layer ──────────────────────────────────

class TestNoQuarantinedRowEntersAPool:

    def test_search_never_returns_one(self):
        import rag
        rows = rag.search("antibiotics in endodontics", limit=400,
                          similarity_threshold=0.0)
        bad = [r for r in rows if r.get("pmid") in QUARANTINED]
        assert not bad, f"quarantined rows reached the pool: {[r['pmid'] for r in bad]}"

    def test_the_tier_filtered_branch_never_returns_one(self):
        """search() has two SQL branches. The level-filtered one is a separate
        query and needs its own clause; testing only the unfiltered branch
        would have missed it."""
        import rag
        rows = rag.search("endodontic position statement", level_key="guideline",
                          limit=400, similarity_threshold=0.0)
        bad = [r for r in rows if r.get("pmid") in QUARANTINED]
        assert not bad, f"quarantined rows reached the guideline tier: {bad}"

    def test_the_follow_up_seeding_path_never_returns_one(self):
        """The copy that matters most. A follow-up seeds itself with the PMIDs
        the previous answer cited, and 103 stored answers cite one of these —
        so without a clause here every one of them re-admits it on the next
        turn. Invisible, and only on follow-ups."""
        import rag
        rows = rag.search_by_pmids("vital pulp therapy",
                                   QUARANTINED + VERIFIED)
        got = {r["pmid"] for r in rows}
        assert not (got & set(QUARANTINED)), (
            f"follow-up seeding re-admitted {sorted(got & set(QUARANTINED))}")
        assert got & set(VERIFIED), (
            "the verified records stopped seeding too — the clause is too broad")


# ── reversibility ────────────────────────────────────────

def test_the_before_state_was_backed_up():
    """`--restore` has to have something to restore from."""
    conn = _db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM endo_papers_rag_quarantine_backup")
        n = cur.fetchone()[0]
    finally:
        cur.close()
        conn.close()
    assert n == 12, f"backup table holds {n} rows, expected 12"


def test_restore_is_a_documented_one_liner():
    """Reversibility is part of the contract, so the undo path is pinned to
    exist rather than left to be rediscovered."""
    from pathlib import Path
    src = (Path(__file__).parent.parent / "scripts"
           / "quarantine_unverified_guidelines.py").read_text(encoding="utf-8")
    assert "--restore" in src
    assert "SET quarantine_reason = ''" in src
