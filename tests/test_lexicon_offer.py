"""
A41b — the domain lexicon, offered to the term generator and never imposed.

WHY IT EXISTS. A33g's vocabulary half failed and A39 explained why: the
generator writes synonyms of the words it was given, and it cannot invent a term
of art it has no reason to reach for. "Endodontic microsurgery" is not a synonym
for apicoectomy — it is what the literature calls the procedure, and it is the
difference between reaching the answering papers and not.

MEASURED, three runs per condition, one variable:

    fixture              targets   without   with
    GIC / ceramic crown        4       0/4     0/4
    apicoectomy module         5   1-2 / 5     4/5   <- three runs, all 4/5
    retreatment visits         1       1/1     1/1
    laser disinfection         0         -       -
    controls (pulpotomy, single-vs-multiple):  no lexicon vocabulary either way

TWO THINGS THE MEASUREMENT CHANGED.

1. SELECTION BY COSINE WAS BUILT, MEASURED AND REJECTED. Choosing entries by
   similarity between the question and each entry's concept fails the way the
   0.45 similarity floor failed: on the GIC question the right entry (orifice
   barrier, 0.460) is outscored by the wrong one (direct coronal restoration,
   0.592), and the retreatment question — which needs no term of art — pulls
   "targeted endodontic microsurgery" at 0.506 as its top pick. A short concept
   string embedded against a clinical question measures "is this endodontics?",
   not "is this the question?". With seven entries the whole list costs ~80
   tokens, so the judgement goes to the model instead.

2. PLACEMENT MATTERS MORE THAN SELECTION, and the first version got it wrong.
   Offering the vocabulary without saying where to put it made the generator
   add "endodontic microsurgery" as a THIRD AND-GROUP — a hard conjunction
   requiring every paper to mention it as well as apicoectomy and mandibular.
   Apicoectomy went 2/5 -> 0/5 and the pool collapsed 143 -> 24: A33d's
   over-specification failure, caused by the fix for A33g. The prompt now says
   the terms go inside the subject or scenario group as OR-alternatives and
   never as a new AND-group, and the pool GROWS (146 -> 166) instead.

WHAT IT DOES NOT FIX, stated rather than buried: the GIC fixture. There the
generator reaches for `direct coronal restoration` — whose concept matches the
QUESTION's own words, "permanent access restoration" — over `orifice barrier`,
whose whole value is that it does NOT match the question's words. That is the
cosine selector's failure reproduced inside the model, and it is the harder half
of A41.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai as e

ROOT = Path(__file__).parent.parent
LEXICON = ROOT / "eval" / "endodontic_lexicon.json"


@pytest.fixture(autouse=True)
def _clean():
    e._reset_lexicon_cache()
    yield
    e._reset_lexicon_cache()


@pytest.fixture
def reviewed(monkeypatch, tmp_path):
    """The shipped lexicon, marked reviewed, so the offer path can be tested
    without pretending RB has approved the real file."""
    data = json.loads(LEXICON.read_text(encoding="utf-8"))
    data["reviewed_by_rb"] = True
    p = tmp_path / "lex.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(e, "LEXICON_PATH", str(p))
    e._reset_lexicon_cache()
    return data


class TestRBsReviewIsTheGate:
    """A41a: 'RB reviews it before it is used.' Enforced, not commented."""

    def test_the_shipped_file_is_not_yet_marked_reviewed(self):
        data = json.loads(LEXICON.read_text(encoding="utf-8"))
        assert data["reviewed_by_rb"] is False, (
            "if RB has approved the lexicon this assertion is what should "
            "change, deliberately, in the same commit as the flag")

    def test_an_unreviewed_lexicon_is_not_offered(self):
        assert e.load_lexicon() == []
        assert e.lexicon_offer_block() == ""

    def test_a_reviewed_lexicon_is_offered(self, reviewed):
        assert len(e.load_lexicon()) == len(reviewed["terms"])
        assert e.lexicon_offer_block() != ""

    def test_a_missing_file_fails_open(self, monkeypatch):
        monkeypatch.setattr(e, "LEXICON_PATH", str(ROOT / "no_such_lexicon.json"))
        e._reset_lexicon_cache()
        assert e.load_lexicon() == []
        assert e.lexicon_offer_block() == ""

    def test_malformed_json_fails_open(self, monkeypatch, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(e, "LEXICON_PATH", str(p))
        e._reset_lexicon_cache()
        assert e.load_lexicon() == []

    def test_the_switch_turns_it_off_even_when_reviewed(self, reviewed, monkeypatch):
        monkeypatch.setattr(e, "OFFER_LEXICON", False)
        assert e.lexicon_offer_block() == ""


class TestTheOfferIsAnOfferAndNotAnInstruction:
    """A41b: 'as AVAILABLE vocabulary, never as a mandatory expansion'."""

    def test_it_says_the_terms_are_optional(self, reviewed):
        block = e.lexicon_offer_block().lower()
        assert "not required" in block
        assert "most questions need none" in block

    def test_it_never_tells_the_model_to_include_them(self, reviewed):
        block = e.lexicon_offer_block().lower()
        for imperative in ("you must", "always add", "include these",
                           "add all of"):
            assert imperative not in block, imperative

    def test_it_says_where_the_terms_go(self, reviewed):
        """The measured failure: without this the generator adds a new
        AND-group and the pool collapses 143 -> 24."""
        block = e.lexicon_offer_block()
        assert "OR-alternatives INSIDE" in block
        assert "NEVER add a new AND-group" in block

    def test_it_explains_why_a_new_and_group_is_wrong(self, reviewed):
        """A rule with its reason attached survives a prompt rewrite; a bare
        prohibition does not."""
        assert "hard requirement" in e.lexicon_offer_block()

    def test_every_entry_offers_its_variants(self, reviewed):
        block = e.lexicon_offer_block()
        for term in reviewed["terms"]:
            assert term["head"] in block
            assert term["variants"][0] in block


class TestBothGeneratorsCarryTheOffer:
    """Standing rule 14 — the block is only worth building if the prompts
    actually contain it."""

    def _src(self, fn):
        import inspect
        return inspect.getsource(fn)

    def test_the_primary_generator_offers_it(self):
        assert "lexicon_offer_block()" in self._src(e.generate_search_terms)

    def test_the_multi_generator_offers_it(self):
        assert "lexicon_offer_block()" in self._src(e.generate_multi_search_terms)


class TestTheMeasurementIsRecordedBesideTheCode:

    def test_the_rejected_selector_is_recorded(self):
        src = (ROOT / "endo_ai.py").read_text(encoding="utf-8")
        assert "0.460" in src and "0.592" in src, (
            "the cosine selector was built and rejected; its numbers must stay "
            "or it will be built again")

    def test_the_placement_failure_is_recorded(self):
        src = (ROOT / "endo_ai.py").read_text(encoding="utf-8")
        assert "EXCLUDES the" in src
