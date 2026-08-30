"""
Superseded review versions must never be served as current evidence.

Cochrane reviews are VERSIONED. Every update is a brand-new PubMed record and
the older versions stay indexed forever — they are not withdrawn, not retracted,
and not retitled. "Single versus multiple visits for endodontic treatment of
permanent teeth" (CD005296) exists three times over, and this library holds all
three:

    17943848  2007  pub2
    27905673  2016  pub3
    36512807  2022  pub4   <- the only current one

Nothing in an older record's title, evidence level or score marks it as stale;
all three sit in the `cochrane` tier scoring 61-70. The only machine-readable
signal is PubMed's CommentsCorrections link, and its DIRECTION is the whole
feature:

    RefType="UpdateIn"  is carried by the OLDER record and names the NEWER one.
    RefType="UpdateOf"  is carried by the NEWER record and names the OLDER one.

Reading those backwards would flag every current review as obsolete while
leaving the obsolete ones in place — a silent, total inversion. The fixture
tests below pin the direction against real efetch XML captured from PubMed
(tests/fixtures/pubmed_xml/cd005296_versions.xml), not invented markup.
"""

import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "pubmed_xml" / "cd005296_versions.xml"

OLDEST  = "17943848"   # 2007, pub2
MIDDLE  = "27905673"   # 2016, pub3
CURRENT = "36512807"   # 2022, pub4


def _load_backfill():
    """Import scripts/backfill_pubmed_metadata.py as a module."""
    path = REPO_ROOT / "scripts" / "backfill_pubmed_metadata.py"
    spec = importlib.util.spec_from_file_location("backfill_pubmed_metadata", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def backfill():
    return _load_backfill()


@pytest.fixture(scope="module")
def fixture_xml():
    if not FIXTURE.exists():
        pytest.skip(f"missing fixture {FIXTURE}")
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def parsed(backfill, fixture_xml, monkeypatch):
    """Run the real parser over the real captured XML."""
    class FakeResp:
        status_code = 200
        text = fixture_xml

    monkeypatch.setattr(backfill.requests, "get", lambda *a, **k: FakeResp())
    meta = {p: {"superseded_by": ""} for p in (OLDEST, MIDDLE, CURRENT)}
    backfill._merge_update_relations(list(meta), meta)
    return meta


# ── The fixture itself must still say what we think it says ──────────────

def _article_blocks(xml: str) -> dict:
    """{citation PMID -> that article's raw markup}.

    Keyed on the article's OWN PMID — the first one in the block — because the
    same PMID string also appears inside other articles' CommentsCorrections,
    which is precisely the confusion this whole feature turns on.
    """
    blocks = {}
    for chunk in xml.split("</PubmedArticle>")[:-1]:
        m = re.search(r'<PMID Version="\d+">(\d+)</PMID>', chunk)
        if m:
            blocks[m.group(1)] = chunk
    return blocks


class TestFixtureIsGroundTruth:
    """If PubMed's own markup ever changes shape, fail HERE with a clear
    message rather than silently parsing nothing."""

    def test_fixture_holds_all_three_versions(self, fixture_xml):
        assert set(_article_blocks(fixture_xml)) == {OLDEST, MIDDLE, CURRENT}

    def test_older_record_carries_updatein_to_the_newer_one(self, fixture_xml):
        block = _article_blocks(fixture_xml)[MIDDLE]
        m = re.search(r'<CommentsCorrections RefType="UpdateIn">.*?'
                      r'<PMID Version="\d+">(\d+)</PMID>', block, re.S)
        assert m, "2016 record no longer carries an UpdateIn link"
        assert m.group(1) == CURRENT

    def test_newer_record_carries_updateof_to_the_older_one(self, fixture_xml):
        block = _article_blocks(fixture_xml)[CURRENT]
        m = re.search(r'<CommentsCorrections RefType="UpdateOf">.*?'
                      r'<PMID Version="\d+">(\d+)</PMID>', block, re.S)
        assert m, "2022 record no longer carries an UpdateOf link"
        assert m.group(1) == MIDDLE

    def test_current_version_has_no_updatein(self, fixture_xml):
        assert 'RefType="UpdateIn"' not in _article_blocks(fixture_xml)[CURRENT], \
            "the current version must not point forward to anything"


# ── Direction ────────────────────────────────────────────────────────────

class TestUpdateInDirection:

    def test_superseded_versions_are_flagged(self, parsed):
        assert parsed[OLDEST]["superseded_by"], "2007 version not flagged"
        assert parsed[MIDDLE]["superseded_by"], "2016 version not flagged"

    def test_current_version_is_not_flagged(self, parsed):
        """The inverted implementation fails exactly here."""
        assert parsed[CURRENT]["superseded_by"] == "", \
            "UpdateOf was read as UpdateIn — the CURRENT review got flagged stale"

    def test_middle_version_points_at_the_current_one(self, parsed):
        assert parsed[MIDDLE]["superseded_by"] == CURRENT

    def test_updateof_is_never_stored(self, parsed):
        """36512807's only version link is an UpdateOf to 27905673. If that
        leaked through, the newest review would claim a 2016 successor."""
        assert parsed[CURRENT]["superseded_by"] != MIDDLE

    def test_commentin_and_other_reftypes_are_ignored(self, parsed):
        """The 2007 and 2022 records each carry a CommentIn to an Evid Based
        Dent piece. A comment is not a new version."""
        assert parsed[OLDEST]["superseded_by"] != "18364693"
        assert parsed[CURRENT]["superseded_by"] != "37188920"

    def test_no_record_supersedes_itself(self, parsed):
        for pmid, entry in parsed.items():
            assert entry["superseded_by"] != pmid

    def test_missing_records_are_left_alone(self, backfill, fixture_xml, monkeypatch):
        """A PMID absent from the response keeps its default, and a PMID in the
        response but absent from `metadata` must not create a key."""
        class FakeResp:
            status_code = 200
            text = fixture_xml
        monkeypatch.setattr(backfill.requests, "get", lambda *a, **k: FakeResp())
        meta = {MIDDLE: {"superseded_by": ""}, "99999999": {"superseded_by": ""}}
        backfill._merge_update_relations(list(meta), meta)
        assert meta[MIDDLE]["superseded_by"] == CURRENT
        assert meta["99999999"]["superseded_by"] == ""
        assert OLDEST not in meta

    def test_empty_ids_is_a_noop(self, backfill, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("should not have hit the network")
        monkeypatch.setattr(backfill.requests, "get", boom)
        meta = {}
        backfill._merge_update_relations([], meta)
        assert meta == {}

    def test_non_200_reports_failure(self, backfill, monkeypatch):
        class Dead:
            status_code = 503
            text = ""
        monkeypatch.setattr(backfill.requests, "get", lambda *a, **k: Dead())
        meta = {MIDDLE: {"superseded_by": ""}}
        assert backfill._merge_update_relations([MIDDLE], meta) is False
        assert meta[MIDDLE]["superseded_by"] == ""

    def test_success_reports_success(self, backfill, fixture_xml, monkeypatch):
        class FakeResp:
            status_code = 200
            text = fixture_xml
        monkeypatch.setattr(backfill.requests, "get", lambda *a, **k: FakeResp())
        meta = {MIDDLE: {"superseded_by": ""}}
        assert backfill._merge_update_relations([MIDDLE], meta) is True


class TestUnknownIsNotTheSameAsCurrent:
    """A failed efetch must never be written as "this review is current" — that
    would un-flag every stale version the previous run caught."""

    def test_failed_batch_becomes_none_not_empty_string(self, backfill, monkeypatch):
        class Dead:
            status_code = 503
            text = ""
        monkeypatch.setattr(backfill.requests, "get", lambda *a, **k: Dead())
        monkeypatch.setattr(backfill, "_merge_corrections_and_registries",
                            lambda ids, meta: None)
        monkeypatch.setattr(backfill.time, "sleep", lambda s: None)
        out = backfill.fetch_all([MIDDLE, CURRENT])
        assert out[MIDDLE]["superseded_by"] is None
        assert out[CURRENT]["superseded_by"] is None

    def test_successful_batch_distinguishes_stale_from_current(self, backfill,
                                                               fixture_xml, monkeypatch):
        class FakeResp:
            status_code = 200
            text = fixture_xml
        monkeypatch.setattr(backfill.requests, "get", lambda *a, **k: FakeResp())
        monkeypatch.setattr(backfill, "_merge_corrections_and_registries",
                            lambda ids, meta: None)
        monkeypatch.setattr(backfill.time, "sleep", lambda s: None)
        out = backfill.fetch_all([OLDEST, MIDDLE, CURRENT])
        assert out[OLDEST]["superseded_by"] == CURRENT, "chain resolved end-to-end"
        assert out[MIDDLE]["superseded_by"] == CURRENT
        assert out[CURRENT]["superseded_by"] == ""

    def test_writer_treats_null_as_leave_alone(self):
        src = (REPO_ROOT / "scripts" / "backfill_pubmed_metadata.py").read_text(encoding="utf-8")
        assert "superseded_by = COALESCE(%s, superseded_by)" in src, \
            "a NULL (undetermined) value must not overwrite a stored supersession"
        assert "if u[8] is not None" in src, \
            "--only-superseded must skip rows whose supersession was not determined"


# ── Chain resolution ─────────────────────────────────────────────────────

class TestVersionChainResolution:
    """2007 -> 2016 -> 2022. Each record names only its immediate successor, so
    an unresolved 2007 row would send a clinician to another obsolete review."""

    def test_oldest_resolves_past_the_middle_version(self, backfill, parsed):
        assert parsed[OLDEST]["superseded_by"] == MIDDLE, \
            "precondition: raw parse yields the immediate successor"
        backfill._resolve_chains(parsed)
        assert parsed[OLDEST]["superseded_by"] == CURRENT, \
            "chain not followed — 2007 still points at the obsolete 2016 version"
        assert parsed[MIDDLE]["superseded_by"] == CURRENT
        assert parsed[CURRENT]["superseded_by"] == ""

    def test_resolution_is_idempotent(self, backfill, parsed):
        backfill._resolve_chains(parsed)
        once = {k: v["superseded_by"] for k, v in parsed.items()}
        backfill._resolve_chains(parsed)
        assert {k: v["superseded_by"] for k, v in parsed.items()} == once

    def test_cycle_does_not_hang(self, backfill):
        """Malformed data must not spin forever."""
        info = {"1": {"superseded_by": "2"}, "2": {"superseded_by": "1"}}
        backfill._resolve_chains(info)
        assert info["1"]["superseded_by"] != "1", "row declared itself its own replacement"
        assert info["2"]["superseded_by"] != "2", "row declared itself its own replacement"

    def test_dangling_successor_outside_the_library_is_kept(self, backfill):
        """The newer version need not be in our library — we still must not
        serve the older one, and the pointer stays useful."""
        info = {"1": {"superseded_by": "77777777"}}
        backfill._resolve_chains(info)
        assert info["1"]["superseded_by"] == "77777777"


# ── search() must exclude superseded rows in BOTH branches ───────────────

class _CapturingCursor:
    def __init__(self, sink):
        self.sink = sink

    def execute(self, sql, params=None):
        self.sink.append(sql)

    def fetchall(self):
        return []

    def close(self):
        pass


class _CapturingConn:
    def __init__(self, sink):
        self.sink = sink

    def cursor(self, *a, **k):
        return _CapturingCursor(self.sink)

    def close(self):
        pass


@pytest.fixture
def executed_sql(monkeypatch):
    """Capture the SQL search() actually sends, per branch."""
    import rag
    monkeypatch.setattr(rag, "embed", lambda text: [0.01] * 384)
    monkeypatch.setattr(rag, "DATABASE_URL", "postgres://test/test")

    def _run(**kwargs):
        sink = []
        monkeypatch.setattr(rag, "get_conn", lambda: _CapturingConn(sink))
        rag.search("single visit endodontics", **kwargs)
        assert len(sink) == 1
        return sink[0]

    return _run


class TestSearchExcludesSupersededRows:

    def test_unfiltered_branch_excludes_superseded(self, executed_sql):
        assert "COALESCE(superseded_by, '') = ''" in executed_sql()

    def test_level_key_branch_excludes_superseded(self, executed_sql):
        """The retraction filter is duplicated across both branches; a filter
        added to only one leaves a whole retrieval path unguarded, and the
        level-filtered branch is the one the cochrane tier uses."""
        sql = executed_sql(level_key="cochrane")
        assert "WHERE level_key = %s" in sql, "expected the level-filtered branch"
        assert "COALESCE(superseded_by, '') = ''" in sql

    def test_every_exclusion_appears_in_both_branches(self):
        """Whatever safety filters exist, they must exist the same number of
        times — this catches the next one being added to one branch only."""
        src = (REPO_ROOT / "rag.py").read_text(encoding="utf-8")
        body = src.split("def search(", 1)[1].split("\ndef ", 1)[0]
        for guard in ("NOT COALESCE(has_retraction, FALSE)",
                      "title NOT ILIKE 'WITHDRAWN:%%'",
                      "COALESCE(superseded_by, '') = ''"):
            assert body.count(guard) == 2, \
                f"{guard!r} appears {body.count(guard)}x in search(), expected 2 (one per branch)"

    def test_superseded_by_is_selected_by_both_branches(self, executed_sql):
        for sql in (executed_sql(), executed_sql(level_key="cochrane")):
            assert "superseded_by," in sql, "column not projected; round-trips lose it"


# ── Round-trip: the flag must survive read and re-ingest ─────────────────

class TestFieldSurvivesRoundTrip:

    def test_rag_results_to_scored_carries_the_field(self):
        from rag import rag_results_to_scored
        row = {"pmid": MIDDLE, "year": 2016, "score": 65.9, "similarity": 0.5,
               "level_key": "cochrane", "superseded_by": CURRENT}
        assert rag_results_to_scored([row])[0]["superseded_by"] == CURRENT

    def test_absent_column_defaults_to_empty_string(self):
        from rag import rag_results_to_scored
        row = {"pmid": "1", "year": 2020, "score": 50.0, "similarity": 0.5}
        assert rag_results_to_scored([row])[0]["superseded_by"] == ""

    def test_reingest_never_clears_an_existing_flag(self):
        """The live PubMed path does not parse UpdateIn, so it always sends ''.
        A plain `superseded_by = EXCLUDED.superseded_by` would un-flag every
        stale review the backfill caught, on the next write-back."""
        src = (REPO_ROOT / "rag.py").read_text(encoding="utf-8")
        assert "COALESCE(NULLIF(EXCLUDED.superseded_by, '')" in src, \
            "ON CONFLICT must preserve a stored supersession when the new value is empty"

    def test_write_back_skips_superseded_papers(self):
        src = (REPO_ROOT / "rag.py").read_text(encoding="utf-8")
        body = src.split("def learn_from_live_results(", 1)[1].split("\ndef ", 1)[0]
        assert 'p.get("superseded_by")' in body, \
            "learn_from_live_results must not seed an outdated review version"


# ── Opt-in check against the real library ────────────────────────────────

@pytest.mark.network
@pytest.mark.skipif(os.environ.get("RUN_DB_TESTS") != "1",
                    reason="reads the live Neon library; set RUN_DB_TESTS=1 to enable")
class TestLiveLibraryAgreesWithTheFixture:
    """Read-only. Confirms the backfill actually landed on the real rows and
    that retrieval no longer surfaces the stale versions."""

    def test_only_the_current_cd005296_version_is_unflagged(self):
        import psycopg2.extras
        from rag import get_conn
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute("SELECT pmid, COALESCE(superseded_by,'') AS s "
                        "FROM endo_papers_rag WHERE pmid = ANY(%s);",
                        ([OLDEST, MIDDLE, CURRENT],))
            got = {r["pmid"]: r["s"] for r in cur.fetchall()}
        finally:
            cur.close(); conn.close()
        assert got.get(OLDEST) == CURRENT
        assert got.get(MIDDLE) == CURRENT
        assert got.get(CURRENT) == ""

    def test_search_returns_the_current_version_only(self):
        from rag import search
        hits = search("single visit versus multiple visit endodontic treatment",
                      limit=50, similarity_threshold=0.0)
        pmids = {h["pmid"] for h in hits}
        assert CURRENT in pmids, "the current 2022 review disappeared from search"
        assert OLDEST not in pmids and MIDDLE not in pmids, \
            "a superseded review version is still being retrieved"
