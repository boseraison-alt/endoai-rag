"""Choosing the abstract out of a PubMed text entry.

Four call sites built a paper's abstract by taking the LONGEST PARAGRAPH of
`rettype=abstract&retmode=text`. The recorded belief was that this loses the
conclusions of structured abstracts, the way the ingest truncation did.
Measured against efetch XML on 198 library PMIDs — 95 of them structured — it
loses NOTHING: PubMed's text renderer emits BACKGROUND / METHODS / RESULTS /
CONCLUSIONS as one blank-line-free block, so the collapse keeps 100%. That
half of the item is closed by measurement, and the first test class pins it so
a future "fix" for a loss that does not happen cannot be introduced.

The real failure is over-capture. "Longest paragraph" is a proxy for "the
abstract" and two other blocks can be longer:

  * the AUTHOR AFFILIATION list — PMID 39743567 (a consensus with ~30
    institutional addresses) stored 6,304 characters of university departments
    in place of its 707-character abstract;
  * a FOREIGN-LANGUAGE abstract, which PubMed prints under `Publisher:` —
    PMID 41337506's Portuguese version is longer than its English one.

Both reached synthesis as the paper's text and both were written into
`abstract_cache`, which is what `verify_citation_support` reads. 175 of 9,985
cache rows and 4 of 2,348 library rows were in that state.

The fixture is the REAL text dump for those two PMIDs plus a structured
control, saved from efetch. A hand-written fixture would not reproduce the
shape: what makes the affiliation block win is that PubMed emits it as one
paragraph with no blank lines inside it, which is not something you would
think to write.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai

FIXTURE = Path(__file__).parent / "fixtures" / "pubmed_text" / "collapse_cases.txt"

AFFILIATION_CASE = "39743567"   # ~30 institutional addresses, one paragraph
TRANSLATION_CASE = "41337506"   # Portuguese abstract longer than the English
STRUCTURED_CASE  = "36156804"   # BACKGROUND/OBJECTIVES/.../CONCLUSIONS, 3015 ch


@pytest.fixture(scope="module")
def entries():
    raw = FIXTURE.read_text(encoding="utf-8")
    return endo_ai._parse_efetch_batch(raw)


class TestTheStructuredAbstractIsNotLost:
    """The hypothesis this item was queued on, falsified. Kept as a test so
    nobody re-derives it from the code and 'fixes' it."""

    def test_a_structured_abstract_survives_whole(self, entries):
        ab = entries[STRUCTURED_CASE]["abstract"]
        for section in ("BACKGROUND:", "OBJECTIVES:", "METHODS:", "RESULTS:",
                        "CONCLUSIONS:"):
            assert section in ab, f"{section} missing from the parsed abstract"

    def test_the_conclusion_is_present(self, entries):
        ab = entries[STRUCTURED_CASE]["abstract"]
        assert "insufficient evidence to recommend any adjunctive therapy" in ab

    def test_it_is_the_full_length_pubmed_holds(self, entries):
        """3,015 characters is what the XML gives for this record. The text
        dump must not be shorter."""
        assert len(entries[STRUCTURED_CASE]["abstract"]) > 2900


class TestTheAffiliationBlockIsNotAnAbstract:
    def test_the_abstract_is_the_abstract(self, entries):
        ab = entries[AFFILIATION_CASE]["abstract"]
        assert ab.startswith("Apical microsurgery"), ab[:120]

    def test_no_department_addresses_reach_the_prompt(self, entries):
        ab = entries[AFFILIATION_CASE]["abstract"]
        assert "Author information" not in ab
        assert "State Key Laboratory" not in ab

    def test_it_is_the_short_one_not_the_long_one(self, entries):
        """The whole trap: the wrong answer here is 6,304 characters and the
        right one is ~707. A length check alone would have preferred the
        affiliations, which is exactly what the old heuristic did."""
        assert len(entries[AFFILIATION_CASE]["abstract"]) < 1200


class TestTheEnglishAbstractWinsOverTheTranslation:
    def test_the_stored_abstract_is_english(self, entries):
        ab = entries[TRANSLATION_CASE]["abstract"]
        assert ab.lower().startswith("calcium aluminate cement"), ab[:120]

    def test_the_publisher_translation_is_not_used(self, entries):
        ab = entries[TRANSLATION_CASE]["abstract"]
        assert "Cimento de aluminato" not in ab
        assert not ab.startswith("Publisher:")


class TestTheSelectorItself:
    """`_select_abstract_paragraph` is shared by every site that parses the
    text dump, so its contract is tested directly as well as through the batch
    parser."""

    def test_a_labelled_block_is_skipped_even_when_longest(self):
        paras = ["J Endod. 2024.",
                 "A title.",
                 "Author information: " + ("(1)Some Department. " * 200),
                 "OBJECTIVE: A short real abstract about root canals that runs "
                 "past two hundred characters so it clears the length floor "
                 "the way a genuine abstract does, and then keeps going for a "
                 "while longer to be sure of it."]
        got = endo_ai._select_abstract_paragraph(paras)
        assert got.startswith("OBJECTIVE:")

    def test_the_length_floor_still_applies(self):
        assert endo_ai._select_abstract_paragraph(["short", "also short"]) == ""

    def test_nothing_but_excluded_blocks_falls_back_rather_than_blanking(self):
        """A record whose ONLY long block is publisher-supplied still has an
        abstract — dropping it would be a second data loss on top of the one
        this fix exists to reverse, and a blank abstract silently disables the
        citation-support check for that paper."""
        only = "Publisher: " + ("An abstract in another language. " * 20)
        assert endo_ai._select_abstract_paragraph([only]) == only

    def test_an_empty_input_is_empty_not_an_error(self):
        assert endo_ai._select_abstract_paragraph([]) == ""

    @pytest.mark.parametrize("body", [
        # PubMed folds the publisher's copyright line into the abstract
        # paragraph on a large share of records. A substring match would drop
        # every one of those abstracts — the paper would reach synthesis with
        # nothing, and an empty abstract silently SKIPS that paper in
        # verify_citation_support, so the guardrail goes quiet instead of
        # complaining.
        "OBJECTIVE: To compare two irrigation protocols in mature permanent "
        "teeth over twelve months of follow-up in ninety patients. RESULTS: "
        "No significant difference was found between the groups at any time "
        "point. Copyright: 2024 The Authors. Published by Elsevier Inc.",
        # A methods section naming a data source, and a paper about indexing.
        "BACKGROUND: We audited how Author information: is populated across "
        "endodontic journals, including Comment in: and Erratum in: notices, "
        "over a decade of records, which is a long enough run of text to "
        "clear the two-hundred-character floor comfortably.",
    ])
    def test_the_exclusions_match_only_at_the_start(self, body):
        # A genuinely excluded block has to be in the list too, and it has to
        # be LONGER: with the real abstract alone, the "no candidate survived,
        # keep the longest anyway" fallback returns it either way and the test
        # cannot see the difference between anchored and unanchored matching.
        affiliations = ("Author information: "
                        + "(1)Department of Endodontics, Somewhere. " * 60)
        assert len(affiliations) > len(body)
        assert endo_ai._select_abstract_paragraph([affiliations, body]) == body

    def test_every_excluded_block_kind_is_recognised(self):
        real = ("OBJECTIVE: A genuine abstract that is comfortably longer "
                "than two hundred characters, so the selector has a real "
                "candidate to prefer over each of the blocks below when it "
                "is deciding which paragraph is the paper's abstract.")
        for prefix in ("Author information:", "Publisher:", "Comment in:",
                       "Comment on:", "Erratum in:", "Update in:",
                       "Conflict of interest statement:", "Collaborators:"):
            blob = prefix + " " + ("filler text that goes on and on. " * 40)
            got = endo_ai._select_abstract_paragraph([blob, real])
            assert got == real, f"{prefix} was not excluded"


class _Resp:
    def __init__(self, text="", payload=None):
        self.text, self._payload, self.status_code = text, payload or {}, 200

    def json(self):
        return self._payload


class TestEveryTextDumpParserAgrees:
    """Four sites each had their own copy of the heuristic and they had
    already drifted — `_parse_efetch_batch` returned "" when no paragraph
    cleared the floor while `ingest_classics` fell back to the longest of any
    length. These assert on what each site RETURNS for the real affiliation
    case, not on whether it calls a particular function: a site that
    reimplements the fix correctly should pass, and a site that imports the
    helper and then ignores it should not.
    """

    def _entry(self, pmid):
        raw = FIXTURE.read_text(encoding="utf-8")
        import re
        for chunk in re.split(r"\n\n(?=\d+\.\s+[A-Z])", raw):
            if re.search(rf"^PMID:\s*{pmid}\b", chunk, re.M):
                return chunk
        raise AssertionError(f"{pmid} not in the fixture")

    def test_the_live_batch_parser(self, entries):
        assert entries[AFFILIATION_CASE]["abstract"].startswith("Apical microsurgery")

    def test_ingest_classics(self, monkeypatch):
        import ingest_classics
        entry = self._entry(AFFILIATION_CASE)

        def _get(url, params, **kw):
            if "esummary" in url:
                return _Resp(payload={"result": {AFFILIATION_CASE: {
                    "title": "Expert consensus on apical microsurgery",
                    "pubdate": "2025", "fulljournalname": "J Endod",
                    "authors": [{"name": "A B"}]}}})
            return _Resp(text=entry)

        monkeypatch.setattr(ingest_classics, "_eutils_get", _get)
        got = ingest_classics.fetch_paper_data(AFFILIATION_CASE)
        assert got and got["abstract"].startswith("Apical microsurgery")
        assert "Author information" not in got["abstract"]

    def test_the_api_abstract_route(self, monkeypatch):
        import app as app_mod
        entry = self._entry(AFFILIATION_CASE)

        def _get(url, params=None, **kw):
            if "esummary" in url:
                return _Resp(payload={"result": {AFFILIATION_CASE: {
                    "title": "Expert consensus on apical microsurgery",
                    "pubdate": "2025", "fulljournalname": "J Endod",
                    "authors": [{"name": "A B"}]}}})
            return _Resp(text=entry)

        monkeypatch.setattr(app_mod, "_eutils_get", _get)
        monkeypatch.setattr(app_mod, "get_cached_abstract", lambda p: None)
        monkeypatch.setattr(app_mod, "cache_abstract", lambda **kw: None)
        app_mod._ABSTRACT_CACHE.pop(AFFILIATION_CASE, None)
        app_mod.app.config["TESTING"] = True
        client = app_mod.app.test_client()
        body = client.get(f"/api/abstract/{AFFILIATION_CASE}").get_json()
        assert body["abstract"].startswith("Apical microsurgery")
        assert "Author information" not in body["abstract"]


class TestTheGuidelineIngestActuallyParsesAnything:
    r"""A fourth variant, and the worst of them: it joined the whole entry —
    citation line, authors, every affiliation, the DOI/PMID footer — into one
    string and stored that as the abstract.

    It also never ran. Its entry separator was `^(\d{5,9})\.` — a five- to
    nine-digit number followed by a dot at the start of a line — while PubMed
    numbers entries `1. `, `2. `. Nothing matched, the function returned {},
    and every record was then dropped by `if len(abstract) < 60: continue`.
    The `abstract[:1200]` cap removed from this file in `grounding-v1` was on
    a line that had never executed.
    """

    def test_the_old_separator_matched_nothing(self):
        """Pinned so the finding is checkable rather than asserted. If PubMed
        ever numbers entries with five digits this fails and says why."""
        import re
        raw = FIXTURE.read_text(encoding="utf-8")
        assert not any(re.match(r"^(\d{5,9})\.", line)
                       for line in raw.split("\n"))

    def test_it_now_returns_one_abstract_per_pmid(self):
        import ingest_aae_guidelines as aae

        class _R:
            text = FIXTURE.read_text(encoding="utf-8")
            status_code = 200

        got = aae.pubmed_fetch_abstracts.__wrapped__(["x"]) \
            if hasattr(aae.pubmed_fetch_abstracts, "__wrapped__") else None
        # The function fetches; call it with `_get` stubbed instead.
        import types
        orig = aae._get
        try:
            aae._get = lambda url, params: _R()
            got = aae.pubmed_fetch_abstracts([AFFILIATION_CASE,
                                              STRUCTURED_CASE])
        finally:
            aae._get = orig
        assert set(got) >= {AFFILIATION_CASE, STRUCTURED_CASE}
        assert got[AFFILIATION_CASE].startswith("Apical microsurgery")
        assert "CONCLUSIONS:" in got[STRUCTURED_CASE]

    def test_it_no_longer_stores_the_citation_line_as_the_abstract(self):
        import ingest_aae_guidelines as aae

        class _R:
            text = FIXTURE.read_text(encoding="utf-8")
            status_code = 200

        orig = aae._get
        try:
            aae._get = lambda url, params: _R()
            got = aae.pubmed_fetch_abstracts([STRUCTURED_CASE])
        finally:
            aae._get = orig
        assert not got[STRUCTURED_CASE].startswith("1. Int Endod J")
        assert "Author information" not in got[STRUCTURED_CASE]
