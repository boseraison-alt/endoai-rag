"""
Non-numeric citation keys (`trust-surface-v1` Q4).

WHAT THE MEASUREMENT FOUND. The Review answer stored at
`eval/fixtures/review_apixaban_apicectomy.md` rendered this, verbatim, in its
Level I section:

    The ESE 2023 Quality Guidelines endorse magnification, CBCT for
    pre-surgical assessment, and standardised outcome reporting for endodontic
    surgery but do not provide specific guidance on DOAC management
    [[PMID:ESE-QG-2023]]

A raw engine marker on the page a clinician reads — invariant 3. `case-v3`
already fixed raw markers once, and that fix held, because every patch spelled
the id as `(\\d+)`.

The id is not always a number. `ingest_aae_guidelines.py` puts authority
documents into the library under synthetic keys — `ESE-QG-2023`,
`ESE-PS-VPT-2019`, `AAE-PS-obturation` — and NCBI Bookshelf chapters arrive as
`NBK430685`. The model cites them correctly. Six consumers of `_PMID_RE` could
not see them, and exactly one had been taught to: `validate_evidence_mapping`
carried a local `non_numeric` re-scan bolted on beside the shared pattern,
which is how the two shapes drifted apart everywhere else.

The visible marker was the least of it. The measured consequences:

  * `_extract_claim_citation_pairs` built NO pair for the ESE claim, so the
    banner said "CHECKED AGAINST ABSTRACTS: 9/9 CONSISTENT" over an answer
    carrying ten cited claims. A denominator that silently drops a citation is
    the fail-open shape invariant 15 exists for.
  * `_detect_unattributed_claims` read the ESE sentence as carrying no marker.
  * `presentations.text_budget.PMID_MARKER_RE` — the single chokepoint that is
    supposed to make a raw marker unable to reach a slide — let it through.
  * `/api/abstract/<pmid>` answered 400 for a synthetic key, so rendering the
    marker as a pill without widening that guard would only have traded a raw
    marker for a dead one.

One pattern, both shapes, in `endo_ai._PMID_ID_PAT`, mirrored once in the
browser (`PMID_KEY_SRC`) and once on each deck path.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai
from endo_ai import (_PMID_RE, _detect_unattributed_claims,
                     _extract_claim_citation_pairs, validate_evidence_mapping)
from presentations import text_budget
from webdeck import citations as wd_citations

ROOT       = Path(__file__).parent.parent
INDEX_HTML = ROOT / "templates" / "index.html"
FIXTURE    = ROOT / "eval" / "fixtures" / "review_apixaban_apicectomy.md"

# The key shapes the library actually holds, and the one it always held.
PSEUDO_KEYS  = ["ESE-QG-2023", "ESE-PS-VPT-2019", "AAE-PS-obturation", "NBK430685"]
NUMERIC_KEYS = ["27759881", "2084204"]


# ── the shared pattern ────────────────────────────────────

class TestOnePatternKnowsBothShapes:

    @pytest.mark.parametrize("key", PSEUDO_KEYS + NUMERIC_KEYS)
    def test_the_marker_regex_matches_every_key_the_library_holds(self, key):
        m = _PMID_RE.search("a claim [[PMID:%s]] here" % key)
        assert m is not None, "[[PMID:%s]] is invisible to the shared pattern" % key
        assert m.group(1) == key

    def test_whitespace_inside_the_marker_is_tolerated(self):
        assert _PMID_RE.search("[[PMID: ESE-QG-2023 ]]").group(1) == "ESE-QG-2023"

    def test_an_empty_marker_is_still_not_a_citation(self):
        assert _PMID_RE.search("[[PMID:]]") is None

    def test_the_pattern_stops_at_the_closing_brackets(self):
        """A key charset wide enough to swallow `]]` would merge two markers
        into one and lose a citation — the same silent drop this item is
        about, arriving from the other direction."""
        got = _PMID_RE.findall("[[PMID:ESE-QG-2023]] and [[PMID:27759881]]")
        assert got == ["ESE-QG-2023", "27759881"]


# ── the denominator that said 9/9 ─────────────────────────

ESE_CLAIM = ("The ESE 2023 Quality Guidelines endorse magnification, CBCT for "
             "pre-surgical assessment, and standardised outcome reporting for "
             "endodontic surgery but do not provide specific guidance on DOAC "
             "management [[PMID:ESE-QG-2023]].")


class TestAPseudoIdClaimIsACheckedClaim:

    def test_a_pseudo_id_claim_becomes_a_claim_citation_pair(self):
        """The 9/9 defect. With no pair the claim is never compared against
        its source, and the banner reports a smaller denominator without
        saying that is what it did."""
        pairs = _extract_claim_citation_pairs("## Evidence summary\n\n" + ESE_CLAIM)
        assert [p[1] for p in pairs] == ["ESE-QG-2023"]

    def test_the_marker_is_stripped_from_the_claim_handed_to_the_judge(self):
        (claim, _), = _extract_claim_citation_pairs("## Evidence summary\n\n" + ESE_CLAIM)
        assert "[[PMID:" not in claim

    def test_a_pseudo_id_claim_is_not_reported_as_unattributed(self):
        """It carries a citation. Reporting it as uncited would push an honest
        answer toward the regeneration retry for citing the right document."""
        assert _detect_unattributed_claims("## Evidence summary\n\n" + ESE_CLAIM) == []

    def test_the_apixaban_fixture_has_ten_cited_claims_not_nine(self):
        """Measured on the stored answer, in the shape the engine emits."""
        raw  = FIXTURE.read_text(encoding="utf-8")
        body = re.search(r"^## Body\s*\n(.*?)\n---\n\n## References",
                         raw, re.S | re.M).group(1)
        model_output = re.sub(r"\[PMID (\d+)\]", r"[[PMID:\1]]", body)
        pairs = _extract_claim_citation_pairs(model_output)
        assert "ESE-QG-2023" in [p[1] for p in pairs]
        assert len(pairs) == 10, (
            "the banner's denominator is the pair count; it rendered 9")


class TestASyntheticKeyIsStillCheckedAgainstTheEvidenceBase:

    EVIDENCE = {"level1": {"scored": [{"pmid": "ESE-QG-2023"}, {"pmid": "27759881"}]}}

    def test_a_synthetic_key_in_the_evidence_base_is_not_a_fabrication(self):
        out = validate_evidence_mapping("## Evidence summary\n\n" + ESE_CLAIM,
                                        self.EVIDENCE)
        assert out["fabricated_pmids"] == []
        assert "ESE-QG-2023" in out["valid_pmids"]

    def test_a_synthetic_key_that_is_NOT_in_the_evidence_base_still_hard_fails(self):
        """Widening the shape must not widen what counts as real. This is what
        keeps the fabricated-PMID gate meaningful across the new charset."""
        answer = "## Evidence summary\n\nInvented guidance [[PMID:ESE-QG-1066]]."
        out = validate_evidence_mapping(answer, self.EVIDENCE)
        assert out["fabricated_pmids"] == ["ESE-QG-1066"]
        assert not out["passed"]


# ── no raw marker reaches a rendered surface ──────────────

class TestTheDeckChokepointSeesBothShapes:

    @pytest.mark.parametrize("key", PSEUDO_KEYS + NUMERIC_KEYS)
    def test_a_marker_of_either_shape_is_a_raw_marker(self, key):
        assert text_budget.has_raw_marker("Healing improved [[PMID:%s]]." % key)

    @pytest.mark.parametrize("key", PSEUDO_KEYS + NUMERIC_KEYS)
    def test_the_chokepoint_strips_it_and_leaves_the_sentence_readable(self, key):
        assert text_budget.strip_markers(
            "Healing improved [[PMID:%s]]." % key) == "Healing improved."

    @pytest.mark.parametrize("key", PSEUDO_KEYS)
    def test_the_webdeck_path_extracts_it_rather_than_printing_it(self, key):
        assert wd_citations.PMID_MARKER.findall("x [[PMID:%s]] y" % key) == [key]
        assert key in wd_citations.extract_pmids({"body": "x [[PMID:%s]] y" % key})

    def test_the_approved_bare_footer_form_is_still_not_a_raw_marker(self):
        """The chokepoint must not start eating the citation the footer exists
        to show. This guards the widening in the other direction."""
        line = "Meire MA et al. 2023 - International endodontic journal - PMID 36156804"
        assert not text_budget.has_raw_marker(line)
        assert text_budget.strip_markers(line) == line


# ── the browser, running the shipped JavaScript ───────────

def _extract_js(names):
    """Pull named top-level declarations out of index.html so this exercises
    the SHIPPED source rather than a Python restatement of it."""
    src = INDEX_HTML.read_text(encoding="utf-8").split("\n")
    out = []
    for name in names:
        start, is_fn = None, False
        for i, line in enumerate(src):
            if line.startswith("function %s(" % name):
                start, is_fn = i, True
                break
            if line.startswith("var %s " % name) or line.startswith("var %s=" % name):
                start, is_fn = i, False
                break
        assert start is not None, "%s not found as a top-level declaration" % name
        j = start
        while j < len(src):
            if is_fn and j > start and src[j] == "}":
                break
            if not is_fn and src[j].rstrip().endswith(";"):
                break
            j += 1
        assert j < len(src), "could not find the end of %s" % name
        out.append("\n".join(src[start:j + 1]))
    return "\n\n".join(out)


def _run_node(js_body):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available - cannot exercise the shipped JS")
    harness = _extract_js(["PMID_KEY_SRC", "isNumericPmid", "pmidRefHtml",
                           "_citeEsc", "pmidMeta", "formatCite", "deShout",
                           "renderAnswer"])
    prog = "var trunc = function(s){return s;};\n" + harness + "\n" + js_body
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(prog)
        path = f.name
    try:
        r = subprocess.run([node, path], capture_output=True, text=True,
                           encoding="utf-8", timeout=30)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout.strip().splitlines()[-1])
    finally:
        os.unlink(path)


class TestTheBrowserRendersBothShapes:
    """Asserted on RENDERED OUTPUT, not on a grep of the template. A grep
    proves the pattern was edited; only the rendered string proves the marker
    stopped reaching the page."""

    def test_no_marker_of_either_shape_survives_rendering(self):
        answer = ("## Evidence summary\n\nA [[PMID:27759881]] and "
                  "B [[PMID:ESE-QG-2023]] and C [[PMID:NBK430685]].")
        html, = _run_node("console.log(JSON.stringify([renderAnswer(%s)]));"
                          % json.dumps(answer))
        assert "[[PMID:" not in html, "a raw marker reached the page: %s" % html
        assert "ESE-QG-2023" in html

    def test_a_pseudo_id_marker_becomes_a_clickable_citation_pill(self):
        answer = "## Evidence summary\n\nGuidance [[PMID:ESE-QG-2023]]."
        html, = _run_node("console.log(JSON.stringify([renderAnswer(%s)]));"
                          % json.dumps(answer))
        assert 'class="claim-cite"' in html
        assert 'data-pmid="ESE-QG-2023"' in html

    def test_a_synthetic_key_never_gets_a_pubmed_href(self):
        """A link to pubmed.ncbi.nlm.nih.gov/ESE-QG-2023/ 404s. A citation
        that leads nowhere is worse than one that is plainly local."""
        local, numeric = _run_node(
            "console.log(JSON.stringify([pmidRefHtml('ESE-QG-2023'), "
            "pmidRefHtml('27759881')]));")
        assert "pubmed.ncbi.nlm.nih.gov" not in local
        assert "pmid-link-local" in local
        assert "pubmed.ncbi.nlm.nih.gov/27759881/" in numeric

    def test_the_reference_list_key_renders_for_both_shapes(self):
        answer = ("## References\n\n1. [PMID: 27759881] Del Fabbro M et al.\n"
                  "2. [PMID: ESE-QG-2023] European Society of Endodontology.")
        html, = _run_node("console.log(JSON.stringify([renderAnswer(%s)]));"
                          % json.dumps(answer))
        assert "[PMID: ESE-QG-2023]" in html
        assert "pubmed.ncbi.nlm.nih.gov/27759881/" in html
        assert "pubmed.ncbi.nlm.nih.gov/ESE-QG-2023" not in html


# ── the panel behind the pill ─────────────────────────────

class TestTheAbstractRouteServesASyntheticKey:

    @pytest.fixture
    def client(self):
        import app as app_mod
        app_mod.app.config["TESTING"] = True
        return app_mod.app.test_client()

    def test_a_synthetic_key_is_no_longer_rejected_as_invalid(self, client, monkeypatch):
        import app as app_mod
        monkeypatch.setattr(app_mod, "get_cached_abstract", lambda pmid: None)
        app_mod._ABSTRACT_CACHE.pop("ESE-QG-2023", None)
        r = client.get("/api/abstract/ESE-QG-2023")
        assert r.status_code != 400, "the pill would open onto an 'invalid PMID' error"
        assert r.get_json().get("kind") == "local_only"

    def test_a_synthetic_key_is_never_sent_to_pubmed(self, client, monkeypatch):
        """It has no record there. Spending a rate-limited round trip to be
        told so is the cost of a shape mismatch, paid per click."""
        import app as app_mod
        monkeypatch.setattr(app_mod, "get_cached_abstract", lambda pmid: None)
        app_mod._ABSTRACT_CACHE.pop("ESE-QG-2023", None)

        def _boom(*a, **k):
            raise AssertionError("live eutils was called for a synthetic key")
        monkeypatch.setattr(app_mod, "_eutils_get", _boom)
        assert client.get("/api/abstract/ESE-QG-2023").status_code == 404

    def test_a_cached_synthetic_key_comes_back_without_a_pubmed_url(self, client, monkeypatch):
        import app as app_mod
        monkeypatch.setattr(app_mod, "get_cached_abstract", lambda pmid: {
            "title": "ESE Quality Guidelines", "abstract": "x" * 200,
            "journal": "Int Endod J", "year": "2023", "authors": "ESE"})
        app_mod._ABSTRACT_CACHE.pop("ESE-QG-2023", None)
        try:
            body = client.get("/api/abstract/ESE-QG-2023").get_json()
            assert body["url"] == ""
        finally:
            app_mod._ABSTRACT_CACHE.pop("ESE-QG-2023", None)

    def test_garbage_is_still_rejected(self, client):
        """Widening the shape must not open the route up."""
        for bad in ("9" * 20, "a b", "%2e%2e%2fetc"):
            assert client.get("/api/abstract/%s" % bad).status_code in (400, 404, 405)
