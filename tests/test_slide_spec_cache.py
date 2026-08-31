"""
The canonical slide spec (PRESENTATION_WORKLIST §0 prime rule, §5.1).

§5.1 asks both deck exports to "consume one canonical text object and assert
its content hash matches between builds". That is unsatisfiable without this
module: `generate_slides_specs` is an LLM call, so two invocations with
identical arguments return different slides and therefore different hashes.
The assertion would fail every time, and the natural "fix" — loosening the
assertion — would quietly abandon the guarantee it exists to provide.

Caching the spec per (answer, question, length) makes the two exports read the
same object, so a hash mismatch means something real went wrong.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import slide_spec_cache as ssc

ANSWER = "## CLINICAL RECOMMENDATION\n\nLasers reduce bacterial load [[PMID:28294701]]."
QUESTION = "Use of lasers in root canal disinfection"

SPEC_A = {"slides": [{"pattern": "title_slide", "title": "Lasers in disinfection"},
                     {"pattern": "bullets", "bullets": ["Reduces load"]}]}
SPEC_B = {"slides": [{"pattern": "title_slide", "title": "A DIFFERENT deck"}]}


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Never touch the real slide_specs/ directory from tests."""
    monkeypatch.setattr(ssc, "CACHE_DIR", tmp_path / "slide_specs")


class TestKeying:

    def test_same_inputs_give_the_same_key(self):
        assert ssc.spec_key(ANSWER, QUESTION, 10) == ssc.spec_key(ANSWER, QUESTION, 10)

    @pytest.mark.parametrize("a,q,n", [
        (ANSWER + " edited", QUESTION, 10),
        (ANSWER, QUESTION + "?", 10),
        (ANSWER, QUESTION, 20),
    ])
    def test_any_input_change_gives_a_new_key(self, a, q, n):
        """A regenerated answer must not silently reuse the old deck."""
        assert ssc.spec_key(a, q, n) != ssc.spec_key(ANSWER, QUESTION, 10)

    def test_field_boundaries_cannot_be_spliced(self):
        """The fields are hashed in the order question, answer, length. Without
        a separator those concatenate, so question="a" + answer="b" and
        question="ab" + answer="" both reduce to "ab10" — two different
        questions sharing one cached deck.

        (An earlier version of this test compared ("ab","c") with ("a","bc"),
        which is not a collision under that ordering and passed even with the
        separator removed. Mutation-checking caught it.)
        """
        assert ssc.spec_key("b", "a", 10) != ssc.spec_key("", "ab", 10)


class TestContentHash:

    def test_identical_slides_hash_identically(self):
        assert ssc.content_hash(SPEC_A) == ssc.content_hash(dict(SPEC_A))

    def test_different_slides_hash_differently(self):
        assert ssc.content_hash(SPEC_A) != ssc.content_hash(SPEC_B)

    def test_key_order_does_not_change_the_hash(self):
        a = {"slides": [{"pattern": "bullets", "title": "T"}]}
        b = {"slides": [{"title": "T", "pattern": "bullets"}]}
        assert ssc.content_hash(a) == ssc.content_hash(b)

    def test_only_slide_content_is_hashed(self):
        """One exporter adding rendering metadata alongside `slides` must not
        register as a content difference — otherwise the §5.1 assertion fires
        on a difference that is not about what the deck says."""
        with_meta = dict(SPEC_A, renderer="pptx", generated_at="2026-08-31")
        assert ssc.content_hash(with_meta) == ssc.content_hash(SPEC_A)

    def test_empty_spec_is_hashable(self):
        assert ssc.content_hash({}) == ssc.content_hash({"slides": []})


class TestSharedSpecAcrossExports:
    """The behaviour §5.1 actually needs."""

    def test_two_exports_of_one_answer_get_the_same_spec(self):
        calls = []

        def flaky_builder(a, q, n):
            """Stands in for the LLM: a different deck every call."""
            calls.append(1)
            return {"slides": [{"pattern": "bullets",
                                "title": f"generation {len(calls)}"}]}

        spec1, h1, cached1 = ssc.get_or_build(ANSWER, QUESTION, 10, builder=flaky_builder)
        spec2, h2, cached2 = ssc.get_or_build(ANSWER, QUESTION, 10, builder=flaky_builder)

        assert len(calls) == 1, "the generator ran twice; the decks would disagree"
        assert (cached1, cached2) == (False, True)
        assert h1 == h2
        assert spec1 == spec2

    def test_without_the_cache_the_hashes_would_differ(self):
        """Documents why this module exists: the raw generator is not stable,
        so the §5.1 assertion cannot be met by calling it twice."""
        n = [0]

        def flaky(a, q, m):
            n[0] += 1
            return {"slides": [{"pattern": "bullets", "title": f"run {n[0]}"}]}

        assert ssc.content_hash(flaky(ANSWER, QUESTION, 10)) != \
               ssc.content_hash(flaky(ANSWER, QUESTION, 10))

    def test_a_changed_answer_regenerates(self):
        n = [0]

        def builder(a, q, m):
            n[0] += 1
            return {"slides": [{"pattern": "bullets", "title": a[:12]}]}

        ssc.get_or_build(ANSWER, QUESTION, 10, builder=builder)
        ssc.get_or_build(ANSWER + " revised", QUESTION, 10, builder=builder)
        assert n[0] == 2, "an edited answer must not reuse the stale deck"


class TestFailureModes:
    """Caching must never be able to break an export."""

    def test_a_corrupt_cache_file_regenerates_rather_than_raising(self):
        key = ssc.spec_key(ANSWER, QUESTION, 10)
        ssc.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (ssc.CACHE_DIR / f"{key}.json").write_text("{not json", encoding="utf-8")
        assert ssc.load(key) is None
        spec, _h, cached = ssc.get_or_build(
            ANSWER, QUESTION, 10, builder=lambda a, q, n: SPEC_A)
        assert cached is False and spec == SPEC_A

    def test_an_empty_spec_is_not_cached(self):
        """Caching a zero-slide result would serve an empty deck forever."""
        ssc.save(ssc.spec_key(ANSWER, QUESTION, 10), {"slides": []})
        assert ssc.load(ssc.spec_key(ANSWER, QUESTION, 10)) is None

    def test_an_unwritable_cache_dir_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(ssc, "CACHE_DIR", Path("\x00invalid"))
        ssc.save("k", SPEC_A)          # must not raise
        spec, _h, cached = ssc.get_or_build(
            ANSWER, QUESTION, 10, builder=lambda a, q, n: SPEC_A)
        assert spec == SPEC_A and cached is False

    def test_a_stale_entry_expires(self, monkeypatch):
        key = ssc.spec_key(ANSWER, QUESTION, 10)
        ssc.save(key, SPEC_A)
        assert ssc.load(key) == SPEC_A
        monkeypatch.setattr(ssc, "CACHE_TTL_DAYS", -1)
        assert ssc.load(key) is None

    def test_a_partial_write_cannot_be_read_as_valid(self):
        """save() writes to a temp file and replaces, so a crash mid-write
        leaves either the old spec or none — never a truncated one."""
        key = ssc.spec_key(ANSWER, QUESTION, 10)
        ssc.save(key, SPEC_A)
        stray = list(ssc.CACHE_DIR.glob("*.tmp"))
        assert not stray, f"temp file left behind: {stray}"
        assert ssc.load(key) == SPEC_A
