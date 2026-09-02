"""
A cache is a time capsule of old behaviour (A16).

A3 found that a cached answer rendered the pre-Q1 clean tick — `✓ CHECKED
AGAINST ABSTRACTS: 9/9 CONSISTENT` — because the cache path never re-ran the
support block. That was fixed for Q1. The general case was not, and it matters
immediately: the demo plan is four CACHED questions and one live.

WHAT A16a MEASURED, on the real stored rows rather than regenerated ones.
Three read paths return a stored answer to the browser:

    /status/<job_id>         live + cache        ran finalise_answer_text
    /history/<cache_id>      History sidebar     ran NOTHING
    /learn_history/<file>    DL history panel    ran NOTHING

and on the rows those two archives actually serve:

    query_cache    (10 rows)   6 carry an impact factor
                               7 gain the banner's second half
                               1 gains a quarantine block
                              10 render the whole retrieval pool as a
                                 bibliography instead of the citation set

    learn_history  (22 files) 13 gain the banner's second half
                              18 render the pool as a bibliography

THE INVARIANT THIS FILE PINS. A stored answer must render as the current
renderer would render it — on every path that serves one. Not "the fix exists",
but "the fix reaches what is already saved".
"""

import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai

ROOT = Path(__file__).parent.parent

# A stored answer in the shape the archives actually hold: written before Stage
# 1, so it carries an impact factor, a pseudo-id marker, an out-of-domain
# paragraph, a support block with only the first number, and a paper pool
# larger than its citation set.
PRE_STAGE1_ANSWER = (
    "## CLINICAL RECOMMENDATION\n\n"
    "Apical surgery is low-risk for major bleeding [[PMID:27759881]], and the "
    "ESE guidance endorses magnification [[PMID:ESE-QG-2023]].\n\n"
    "From the wider literature: bridging with LMWH is not indicated for "
    "apixaban. INR testing is not applicable.\n\n"
    "Non-surgical retreatment remains an option [[PMID:35762859]].\n\n"
    "## REFERENCES\n\n"
    "1. [PMID: 27759881] Del Fabbro M et al. — Cochrane review. "
    "Cochrane Database Syst Rev (IF: 12.0), 2016. (Score: 73.3/100)\n\n"
    "---\n\n"
    "> ✓ **Citation support: verified.** Each of the 3 cited claims was "
    "checked against its source abstract."
)

PRE_STAGE1_PAPERS = [
    {"pmid": "27759881", "score": 73.3, "level_key": "cochrane"},
    {"pmid": "ESE-QG-2023", "score": 87.0, "level_key": "level1"},
    {"pmid": "35762859", "score": 80.9, "level_key": "level1"},
    {"pmid": "2084204", "score": 74.0, "level_key": "classic"},      # never cited
    {"pmid": "38243912", "score": 73.9, "level_key": "level3a"},     # never cited
]


def rendered(answer):
    out, _ = endo_ai.finalise_answer_text(answer)
    return out


class TestAStoredAnswerRendersAsTheCurrentRendererWould:
    """A16c. Each assertion names the Stage 1 item it is standing in for."""

    def test_q3_the_impact_factor_is_stripped(self):
        assert "(IF:" in PRE_STAGE1_ANSWER
        assert "(IF:" not in rendered(PRE_STAGE1_ANSWER)

    def test_q2_out_of_domain_prose_is_quarantined(self):
        out, blocks = endo_ai.finalise_answer_text(PRE_STAGE1_ANSWER)
        assert blocks, "the stored answer's out-of-domain paragraph was not lifted"
        assert "NOT FROM THE EVIDENCE BASE" in out

    def test_q1_the_banner_gains_its_second_number(self):
        assert not re.search(r"not from the evidence base", PRE_STAGE1_ANSWER)
        assert re.search(r"\d+ claims? not from the evidence base",
                         rendered(PRE_STAGE1_ANSWER))

    def test_q5_the_bibliography_is_the_citation_set(self):
        out = rendered(PRE_STAGE1_ANSWER)
        split = endo_ai.assemble_bibliography(out, PRE_STAGE1_PAPERS)
        assert len(split["cited"]) == 3
        assert {p["pmid"] for p in split["uncited"]} == {"2084204", "38243912"}

    def test_the_stored_text_itself_is_never_mutated(self):
        """Re-rendering happens at READ time. The row on disk keeps whatever it
        was, so nothing is lost and the change is reversible."""
        before = PRE_STAGE1_ANSWER
        rendered(before)
        assert PRE_STAGE1_ANSWER == before

    def test_re_rendering_is_idempotent(self):
        once = rendered(PRE_STAGE1_ANSWER)
        assert rendered(once) == once


class TestEveryRouteThatServesAStoredAnswerNormalisesIt:
    """Standing rule 14 — assert on the routes the product actually serves,
    not on the helper they are supposed to call.

    `/history/<cache_id>` and `/learn_history/<filename>` each returned a
    stored answer with no normalisation at all. Both are demo surfaces: the
    History sidebar and the Deep Learning report list.
    """

    ROUTES = [
        ('@app.route("/history/<int:cache_id>")', "/history/<cache_id>"),
        ('@app.route("/learn_history/<filename>")', "/learn_history/<filename>"),
        ('@app.route("/status/<job_id>")', "/status/<job_id>"),
    ]

    def _body(self, marker):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        i = src.index(marker)
        j = src.index("@app.route", i + len(marker))
        return src[i:j]

    @pytest.mark.parametrize("marker,name", ROUTES)
    def test_the_route_re_renders_the_stored_answer(self, marker, name):
        assert "finalise_answer_text" in self._body(marker), (
            "%s serves a stored answer without re-rendering it" % name)

    @pytest.fixture
    def client(self):
        import app as app_mod
        app_mod.app.config["TESTING"] = True
        return app_mod.app.test_client()

    def test_the_history_route_actually_returns_the_cited_set(self, client, monkeypatch):
        """Exercised through the route, not grepped for.

        The first version of this searched the route body for "cited_pmids" —
        and a mutation deleting the key from the JSON response survived it,
        because the line that COMPUTES the value also contains that string.
        Standing rule 14: assert on what the product returns."""
        import app as app_mod

        class _Cur:
            def execute(self, *a, **k): pass
            def fetchone(self):
                return ("[review] q", PRE_STAGE1_ANSWER, PRE_STAGE1_PAPERS)
            def close(self): pass

        class _Conn:
            def cursor(self): return _Cur()
            def close(self): pass

        monkeypatch.setattr("rag.get_conn", lambda: _Conn())
        body = client.get("/history/1").get_json()
        assert "cited_pmids" in body, (
            "the History route serves papers without saying which were cited, "
            "so the bibliography falls back to the whole retrieval pool")
        assert set(body["cited_pmids"]) == {"27759881", "ESE-QG-2023", "35762859"}
        assert "(IF:" not in body["answer"], "the stored answer was served unrendered"
        assert re.search(r"\d+ claims? not from the evidence base", body["answer"])

    def test_the_learn_history_route_actually_returns_the_cited_set(
            self, client, tmp_path, monkeypatch):
        import app as app_mod
        rec = {"question": "q", "answer": PRE_STAGE1_ANSWER,
               "papers": PRE_STAGE1_PAPERS}
        p = tmp_path / "20260101_000000_q.json"
        p.write_text(json.dumps(rec), encoding="utf-8")
        monkeypatch.setattr(app_mod, "_LEARN_HISTORY_DIR", str(tmp_path))
        body = client.get("/learn_history/20260101_000000_q.json").get_json()
        assert "cited_pmids" in body
        assert set(body["cited_pmids"]) == {"27759881", "ESE-QG-2023", "35762859"}
        assert "(IF:" not in body["answer"]
        assert "NOT FROM THE EVIDENCE BASE" in body["answer"]

    def test_the_cache_hit_branch_re_renders_too(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        i = src.index("cached = get_cached_answer(")
        j = src.index("return", i)
        assert "finalise_answer_text" in src[i:j]


class TestTheBrowserHistoryLoadersUseTheSameRenderer:
    """Both history loaders rendered the answer themselves rather than going
    through `showResult`, which is how they missed the marking pass — the same
    shape as the export-source bug already recorded in that function."""

    def _src(self):
        return (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    def test_both_loaders_mark_the_flagged_claims(self):
        src = self._src()
        loaders = re.findall(r"setCitationMeta\(rec\.papers \|\| \[\]\);"
                             r"(?:.|\n){0,220}", src)
        assert len(loaders) == 2, "expected the two history loaders"
        for body in loaders:
            assert "markUncitedClaims" in body, (
                "a history loader renders without marking the flagged claims:\n%s"
                % body[:200])

    def test_the_learn_loader_carries_the_cited_set_into_the_shape_card(self):
        src = self._src()
        m = re.search(r"window\._lastJob = \{[^}]*\}", src)
        assert m and "cited_pmids" in m.group(0), m.group(0) if m else "not found"


class TestTheRealStoredRowsWouldChange:
    """The measurement, kept as a test so the claim stays true. Uses the real
    archive on disk — `learn_history/` is committed, so this runs anywhere."""

    def test_the_stored_curricula_need_the_re_render(self):
        import glob
        changed = pool_bigger = 0
        docs = 0
        for p in glob.glob(str(ROOT / "learn_history" / "*.json")):
            try:
                d = json.load(io.open(p, encoding="utf-8"))
            except Exception:
                continue
            ans = d.get("answer")
            if not ans:
                continue
            docs += 1
            out, _ = endo_ai.finalise_answer_text(ans)
            if out != ans:
                changed += 1
            cited = endo_ai.assemble_bibliography(out, d.get("papers") or [])["cited_pmids"]
            if len(d.get("papers") or []) > len(cited):
                pool_bigger += 1
        assert docs >= 20, "the archive shrank; re-measure before trusting this"
        assert changed >= 10, (
            "only %d of %d stored curricula change under the current renderer — "
            "if that is now 0, this test is vacuous and A16 should be re-measured"
            % (changed, docs))
        assert pool_bigger >= 10
