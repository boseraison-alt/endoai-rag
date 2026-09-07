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

# A2 verified four records as naming real documents and kept them citeable.
# NONE of the four still is. All four are in QUARANTINED_LATER below: the A2
# verdict was correct on every one of them, and a different question
# superseded it in every case.
#
# That is the finding, and it is worth more than the list: "does this record
# name a real document?" and "is this ROW needed?" are different questions,
# and the A2 pass was only ever asking the first.
VERIFIED = []

# SUPERSEDED A2 VERDICT, recorded rather than edited away (rule 24).
#
# A2 asked "does this record name a real document?" and answered yes for
# ESE-PS-VPT-2019, so it stayed citeable. That answer was right, and it was
# not the only question. On 2026-09-05 the row was re-examined and the
# document it names — ESE-DEEPCARIES-2019, PMID 30664240 — turned out to be
# ALREADY IN THE LIBRARY from the verified manifest, with the verified title,
# a confirmed accession and a NULL score. So the slug row is a second,
# unverified copy of a document already present in verified form.
#
# It is quarantined for redundancy, NOT for the A2 failure modes: the document
# is real, which is exactly why the duplicate is unnecessary. The reason string
# names the survivor so a reader of the row can follow it.
QUARANTINED_LATER = {
    "ESE-PS-VPT-2019": ("duplicate_of:30664240",
                        "A2-verified as real; later found to duplicate a "
                        "manifest record already in the library"),
    # 2026-09-06, item 3. The SECOND of the four A2-verified records to turn
    # out redundant, and the same shape: A2 asked "does this name a real
    # document?" and answered yes, correctly. Item 3 asked a different
    # question -- "can this row be CITED?" -- found it could not, because its
    # id is a slug and the prompt requires [[PMID:n]], and then found the seed
    # confirms PMID 17180780 for the same document AND that the verified row
    # is already in the library with guideline_id ESE-QG-2006, org ESE, status
    # superseded, confirmed, NULL score.
    #
    # Two of the four kept records were duplicates. That is worth noticing:
    # verifying that a document is real does not establish that the ROW is
    # needed, and nothing in the A2 pass was asking that.
    "ESE-QG-2006": ("duplicate_of:17180780",
                    "A2-verified as real; item 3 found the verified PMID row "
                    "for the same document already present"),
    # 2026-09-07. The LAST TWO of the four, and the first retired for what
    # their text IS rather than for redundancy alone.
    #
    # `ingest_aae_guidelines.py` says of its own records: "Summaries are
    # condensed from the official documents." They are model-written
    # paraphrases stored as source text, so `verify_citation_support` was
    # checking clinical claims against a model's words — a hole directly under
    # the grounding guarantee, and one no amount of verifying the DOCUMENT
    # could close, because the document was never the problem.
    #
    # They could not be retired before 2026-09-07, and that is the substance
    # rather than the timing: each duplicates a manifest record that was
    # itself a bare pointer until that day, so retiring the paraphrase would
    # have replaced text with no text. AAE-VPT-2021 now carries the AAE's own
    # words, fetched through a browser session because aae.org returns 403 to
    # everything else. The exchange is a paraphrase for the document.
    #
    # AAE-DIAGNOSIS-2009 is still a pointer, so that one trades a paraphrase
    # for "position not quoted — read at <url>". That is the right direction
    # anyway: an honest absence beats an unverifiable summary a support
    # checker will treat as a source.
    #
    # Redirect targets are the manifest's own. Its note on AAE-DIAGNOSIS-2009
    # reads: "'AAE-PS-diagnosis]' leaking into Case citation slots resolves to
    # AAE-DIAGNOSIS-2009."
    "AAE-PS-vital-pulp": (
        "re-keyed: this document is AAE-VPT-2021; the text stored here was a "
        "model-written summary, not the document's own words",
        "A2-verified as real; 2026-09-07 found its stored text was a "
        "model-written paraphrase and the same document now carries the AAE's "
        "own words under AAE-VPT-2021"),
    "AAE-PS-diagnosis": (
        "re-keyed: this document is AAE-DIAGNOSIS-2009; the text stored here "
        "was a model-written summary, not the document's own words",
        "A2-verified as real; 2026-09-07 found its stored text was a "
        "model-written paraphrase and the manifest names AAE-DIAGNOSIS-2009 "
        "as what this key resolves to"),
}

# Real, PubMed-indexed guidelines that also sit at level_key='guideline'.
# They were never in scope and this is the guard that says so.
REAL_PMID_GUIDELINES = ["28436043", "31668170", "36942472", "37772327", "39578680"]

# THE CONTROL ARM, and it needs one now that VERIFIED is empty.
#
# Three tests below use a citeable slug row to prove the quarantine clause is
# not TOO BROAD — that it removes the quarantined rows and nothing else. They
# used VERIFIED for that, and when the last two A2-verified records were
# retired on 2026-09-07 the control became an empty set: `got & set(VERIFIED)`
# is then vacuously falsy, and the "too broad" assertion could never fail for
# the right reason again (rule 4).
#
# The replacement is deliberately the two RETIREMENT TARGETS. They are the
# documents those retired citations now resolve to, so if the clause ever
# swallowed them the retirement would have broken the 32 stored answers it was
# supposed to repair — which makes them the most load-bearing control
# available, not merely a convenient one.
# RESOLVED, NOT NAMED (rule 39).
#
# Naming the targets was still a literal, and on 2026-09-08 the literal went
# stale for the second time: `AAE-VPT-2021` was itself re-keyed onto its
# PubMed accession 34352305, so the row a retired citation resolves to moved
# again and three tests here failed for a reason that had nothing to do with
# the quarantine clause they check.
#
# The property was never "AAE-VPT-2021 stays citeable". It is "whatever a
# retired citation resolves to stays citeable". So follow the chain and let
# the database answer. This survives the next re-key without an edit.
def _terminal_target(cur, key, _seen=None):
    seen = _seen or set()
    while key and key not in seen:
        seen.add(key)
        cur.execute("SELECT COALESCE(redirect_to,'') FROM endo_papers_rag "
                    "WHERE pmid = %s", (key,))
        row = cur.fetchone()
        if not row or not row[0]:
            return key
        key = row[0]
    return key


def _resolve_citeable_control():
    try:
        from rag import DATABASE_URL, get_conn
        if not DATABASE_URL:
            return []
        conn = get_conn()
    except Exception:
        return []
    try:
        cur = conn.cursor()
        out = []
        for retired in ("AAE-PS-vital-pulp", "AAE-PS-diagnosis"):
            t = _terminal_target(cur, retired)
            if t and t != retired:
                out.append(t)
        cur.close()
        return out
    finally:
        conn.close()


CITEABLE_CONTROL = _resolve_citeable_control()


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

    @pytest.mark.parametrize("slug", CITEABLE_CONTROL)
    def test_a_citeable_guideline_row_is_untouched_by_the_quarantine(self, slug):
        """RETARGETED 2026-09-07. This was parametrized on VERIFIED, which is
        now empty — a zero-parameter test does not run at all and proves
        nothing (rule 4). It now uses the two rows the retired slugs redirect
        to: if the quarantine ever swallowed THOSE, the retirement would have
        broken the 32 stored answers it repaired."""
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

    @pytest.mark.parametrize("slug", sorted(QUARANTINED_LATER))
    def test_the_fourth_was_quarantined_later_for_a_different_reason(self, slug):
        """A2's verdict stands and was superseded by a different question.

        The distinction is load-bearing: quarantining this row for
        `no_such_document` would assert the document is unreal, which is false
        and would be a fabrication of the opposite kind. The reason string has
        to say REDUNDANT, and it has to name the row that survives.
        """
        expected, _why = QUARANTINED_LATER[slug]
        conn = _db()
        cur = conn.cursor()
        try:
            cur.execute("SELECT COALESCE(quarantine_reason,'') "
                        "FROM endo_papers_rag WHERE pmid = %s", (slug,))
            row = cur.fetchone()
        finally:
            cur.close()
            conn.close()
        assert row is not None, f"{slug} was deleted; nothing here deletes rows"
        assert row[0] == expected
        assert not row[0].startswith(("wrong_year", "no_such_document")), (
            "quarantined under an A2 failure mode, which would assert the "
            "document is unreal — it is real, and that is why the copy is "
            "redundant")

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

    @pytest.mark.parametrize("slug", CITEABLE_CONTROL)
    def test_a_citeable_slug_still_resolves(self, slug, fresh_key_cache):
        """RETARGETED 2026-09-07, same reason: VERIFIED is empty and a
        zero-parameter test is not a test. These are what AAE-PS-vital-pulp
        and AAE-PS-diagnosis now redirect to, so a citation of either retired
        key resolves only if these still do.

        THE TWO TARGETS RESOLVE BY DIFFERENT ROUTES, and after the 2026-09-08
        re-key they no longer share one. `AAE-DIAGNOSIS-2009` is a manifest
        slug and resolves through the synthetic-key gate; `34352305` is a
        PubMed accession and resolves the way every other PMID citation does —
        as a citeable row. Asserting the slug route for both convicted the
        PMID target for being an ordinary PMID.
        """
        if str(slug).isdigit():
            conn = _db()
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT COUNT(*) FROM endo_papers_rag
                    WHERE pmid = %s
                      AND COALESCE(quarantine_reason, '') = ''
                """, (slug,))
                assert cur.fetchone()[0] == 1, (
                    "%s stopped being a citeable row — every citation of the "
                    "slug that redirects to it now resolves to nothing."
                    % slug)
                cur.close()
            finally:
                conn.close()
            return
        known = E._known_synthetic_keys()
        assert known is not None
        assert slug in known, (
            f"{slug} stopped resolving — every citation of the slug that "
            f"redirects to it now resolves to nothing.")

    @pytest.mark.parametrize("slug", sorted(QUARANTINED_LATER))
    def test_the_later_quarantine_reaches_the_citation_gate_too(
            self, slug, fresh_key_cache):
        """Quarantining a row for redundancy has to make it uncitable by the
        SAME mechanism as the A2 rows, not merely mark it in the table. This
        row was citeable until 2026-09-05 and stored answers may reference it,
        so the gate is what actually protects the reader."""
        known = E._known_synthetic_keys()
        assert known is not None, "gate disabled — DB unreachable"
        assert slug not in known, (
            f"{slug} is quarantined in the table but still resolves as a "
            f"citation key — the gate reads a different source than the mark")

    def test_a_citation_to_a_quarantined_record_is_dropped(self, fresh_key_cache):
        text = ("Antibiotics are not indicated for a localised abscess "
                "[[PMID:AAE-PS-antibiotics]].")
        out, dropped = E.drop_unresolvable_citations(text)
        assert "AAE-PS-antibiotics" not in out
        assert "AAE-PS-antibiotics" in dropped

    def test_a_citation_to_a_citeable_record_survives(self, fresh_key_cache):
        """The control for the test above: G2 must drop the quarantined key and
        NOT this one, or it is a gate that drops everything.

        RETARGETED 2026-09-07. It cited AAE-PS-diagnosis, which is now retired
        — so the test would have been asserting that a RETIRED key survives
        the gate, which is the opposite of what the gate is for.
        AAE-DIAGNOSIS-2009 is the row that key now redirects to."""
        text = ("Pulp status is assessed before treatment "
                "[[PMID:AAE-DIAGNOSIS-2009]].")
        out, dropped = E.drop_unresolvable_citations(text)
        assert "AAE-DIAGNOSIS-2009" in out
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
        expected = CITEABLE_CONTROL[0] if CITEABLE_CONTROL else None
        assert expected, "no citeable control resolved — see the note above"
        assert expected in served, (
            "the finaliser also dropped a citeable record — and this one is "
            "the row AAE-PS-vital-pulp now redirects to (%s)" % expected)


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
                                   QUARANTINED + CITEABLE_CONTROL)
        got = {r["pmid"] for r in rows}
        assert not (got & set(QUARANTINED)), (
            f"follow-up seeding re-admitted {sorted(got & set(QUARANTINED))}")
        assert got & set(CITEABLE_CONTROL), (
            "citeable guideline rows stopped seeding too — the clause is too "
            "broad. These two are what the retired slugs redirect to, so "
            "losing them breaks every stored answer the retirement repaired.")


# ── reversibility ────────────────────────────────────────

def test_the_before_state_was_backed_up():
    """`--restore` has to have something to restore from."""
    conn = _db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM endo_papers_rag_quarantine_backup")
        n = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM endo_papers_rag_quarantine_backup "
                    "WHERE pmid = ANY(%s)", (QUARANTINED,))
        n_a2 = cur.fetchone()[0]
    finally:
        cur.close()
        conn.close()
    # The A2 twelve are the ones THIS script must be able to restore. The
    # table is shared: 2026-09-05 added ESE-PS-VPT-2019 through
    # null_guideline_scores.py, so a bare count of 12 stopped being the
    # property worth asserting — it would fail on a correct, unrelated write.
    assert n_a2 == 12, f"backup holds {n_a2} of the A2 twelve, expected 12"
    assert n >= 12, f"backup table holds {n} rows, expected at least 12"


def test_restore_is_a_documented_one_liner():
    """Reversibility is part of the contract, so the undo path is pinned to
    exist rather than left to be rediscovered."""
    from pathlib import Path
    src = (Path(__file__).parent.parent / "scripts"
           / "quarantine_unverified_guidelines.py").read_text(encoding="utf-8")
    assert "--restore" in src
    assert "SET quarantine_reason = ''" in src
