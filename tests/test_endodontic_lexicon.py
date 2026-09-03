"""
A41a — the lexicon's claims are checked against the record, not trusted.

Every entry asserts `generator_ever_wrote_it`, and that assertion is the whole
reason the entry exists: a term the generator already reaches for adds nothing.
The first draft of the file got two of seven wrong — it claimed the generator
had never written "coronal restoration" or "MRONJ", and it has written both,
along with every other MRONJ variant. The MRONJ entry was removed to `rejected`
and the restoration entry narrowed to the one phrase that is actually novel.

So the claim is verified here against `pubmed_audit.jsonl`, which records the
search term of every live PubMed call the system has ever made. A future entry
added on a hunch fails this file.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

ROOT = Path(__file__).parent.parent
LEXICON = ROOT / "eval" / "endodontic_lexicon.json"
AUDIT = ROOT / "pubmed_audit.jsonl"


def normalise(text):
    """Fold stem truncation and plurals — the generator writes `lesion*` where
    a title says `lesions`, and comparing surface forms would measure its
    punctuation rather than its vocabulary."""
    t = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    return " " + " ".join(w.rstrip("s") if len(w) > 4 and w.endswith("s") else w
                          for w in t.split()) + " "


@pytest.fixture(scope="module")
def lexicon():
    return json.loads(LEXICON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def written_queries():
    if not AUDIT.exists():
        pytest.skip("no pubmed_audit.jsonl in this checkout")
    terms = []
    for line in AUDIT.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            terms.append(json.loads(line).get("search_term") or "")
        except Exception:
            continue
    if not terms:
        pytest.skip("audit log has no search terms")
    return normalise(" ".join(terms))


class TestTheLexiconIsWellFormed:

    def test_it_parses_and_has_terms(self, lexicon):
        assert lexicon["terms"], "an empty lexicon is not a lexicon"

    def test_every_term_carries_its_justification(self, lexicon):
        for t in lexicon["terms"]:
            assert t.get("head"), t
            assert t.get("variants"), t["head"]
            assert t.get("why"), f"{t['head']} has no fixture justifying it"
            assert t.get("concept"), t["head"]

    def test_the_head_is_among_its_own_variants(self, lexicon):
        for t in lexicon["terms"]:
            heads = {v.lower() for v in t["variants"]}
            assert t["head"].lower() in heads, (
                f"{t['head']!r} is not in its own variant list — the canonical "
                f"name must be searchable")

    def test_it_is_not_marked_reviewed_until_rb_reviews_it(self, lexicon):
        """A41a: RB reviews it before it is used. If this ever flips to true,
        it should be RB flipping it."""
        assert isinstance(lexicon.get("reviewed_by_rb"), bool)

    def test_nothing_reads_it_yet(self):
        """A41b wires it in and measures. Until then it is data, and a test
        that says so is cheaper than discovering it went live unmeasured."""
        for path in ("endo_ai.py", "app.py", "rag.py"):
            src = (ROOT / path).read_text(encoding="utf-8")
            assert "endodontic_lexicon" not in src, (
                f"{path} reads the lexicon — A41b requires recovery measured "
                f"with it and without before it is offered to the generator")


class TestTheBlindSpotClaimIsTrue:
    """The point of an entry is that the generator does not reach for it."""

    def test_no_kept_variant_has_ever_been_generated(self, lexicon, written_queries):
        offenders = {}
        for t in lexicon["terms"]:
            if not t.get("generator_ever_wrote_it", False):
                seen = [v for v in t["variants"]
                        if normalise(v).strip() in written_queries]
                if seen:
                    offenders[t["head"]] = seen
        assert not offenders, (
            "these entries claim the generator has never written them, and it "
            f"has: {offenders}. Either narrow the variants or move the entry "
            f"to `rejected` with the reason, as MRONJ was.")

    def test_the_rejected_entries_really_are_already_generated(self, lexicon,
                                                               written_queries):
        """A rejected entry is a claim too — that it was rejected for cause.
        If a variant here is NOT in the log, the rejection was wrong."""
        for t in lexicon.get("rejected", []):
            seen = [v for v in t["variants"]
                    if normalise(v).strip() in written_queries]
            assert seen, (
                f"{t['head']} was rejected as already-generated but none of its "
                f"variants appears in the audit log")

    def test_the_two_terms_the_item_exists_for_are_present(self, lexicon):
        """A33g's measurement is the reason this file exists; losing either of
        these means the file has drifted from its evidence."""
        heads = {t["head"] for t in lexicon["terms"]}
        assert "orifice barrier" in heads
        assert "bony lid" in heads

    def test_orifice_barrier_carries_the_papers_it_recovered(self, lexicon):
        t = next(x for x in lexicon["terms"] if x["head"] == "orifice barrier")
        assert set(t["evidence"]) >= {"36661351", "35097115"}
