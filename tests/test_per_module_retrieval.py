"""
A24 — retrieve per module, and search the module's own subject.

A24a's premise turned out to be wrong, which is worth recording: the modules do
NOT share one query set. Each carries its own `search_query` and
`_curriculum_module_body` calls `build_evidence_base` on it, per module, with
its own broadening retry. Measured on "apicoectomy of mandibular teeth": 4 of 4
distinct queries.

What was actually wrong is subtler and is A24b. The four queries were the
TOPIC's terms with an aspect adjective bolted on — apicoectomy AND mandibular
AND (indication* OR anatom*), then the same two groups AND (prognos* OR
outcome*). Four near-identical piles, so the anatomy module was written from
evidence assembled for the topic as a whole, exactly as A24 describes, but by a
different mechanism than it assumed.

Measured after the prompt change, same topic:
  module 1  "cortical bone" OR "buccal bone thickness" OR "mandibular canal"
            OR "mental foramen" OR "root apex position" ...
  pool for the anatomy module x observational tier: 771 -> 343
  Lee 2020 bone window   not in 200 -> rank 24
  Bi 2022 bony lid       rank 32    -> rank 38
  Jeon 2021 anatomy      rank 76    -> rank 54
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

ROOT = Path(__file__).parent.parent
ENDO = (ROOT / "endo_ai.py").read_text(encoding="utf-8")


def syllabus_prompt():
    """The prompt with its line wrapping normalised. Several of these rules
    wrap mid-phrase in the source, and a test that matches the wrapping rather
    than the words breaks on a reflow that changed nothing."""
    i = ENDO.index("def generate_curriculum_syllabus(")
    j = ENDO.index('log_llm_call("generate_curriculum_syllabus"', i)
    return " ".join(ENDO[i:j].split())


class TestEachModuleRetrievesForItself:
    """A24a, pinned as the already-true property it turned out to be."""

    def test_the_module_body_retrieves_on_its_own_query(self):
        body = ENDO[ENDO.index("def _curriculum_module_body("):]
        body = body[:body.index("\ndef ", 10)]
        assert 'build_evidence_base(mod["search_query"], mode="learn")' in body

    def test_a_thin_module_broadens_before_giving_up(self):
        body = ENDO[ENDO.index("def _curriculum_module_body("):]
        body = body[:body.index("\ndef ", 10)]
        assert "broadening and retrying" in body
        assert "generate_search_terms(" in body

    def test_a_module_with_no_evidence_writes_no_protocol(self):
        """Invariant 6, and the reason A31's weakest-tier banding is safe: a
        module that retrieved nothing emits a gap, not a numeric protocol."""
        body = ENDO[ENDO.index("def _curriculum_module_body("):]
        body = body[:body.index("\ndef ", 10)]
        assert "_module_not_generated_block" in body
        assert "MIN_MODULE_PAPERS" in body


class TestTheSyllabusSearchesEachModulesOwnSubject:
    """A24b. The rule and its worked contrast are asserted on the prompt text
    the model is actually shown — the same reason CASE_FOLLOWUP_PROMPT and
    _NO_QUESTIONS_RULE are hoisted."""

    def test_it_names_the_failure_it_is_preventing(self):
        p = syllabus_prompt()
        assert "EACH MODULE'S QUERY MUST BE ABOUT THAT MODULE" in p
        assert "aspect adjective bolted on" in p

    def test_it_shows_the_bad_shape_and_the_good_one(self):
        """A rule with only a good example is a rule the model can satisfy
        while doing the wrong thing — it was already OR-expanding correctly
        and still produced four copies of one query."""
        p = syllabus_prompt()
        assert "BAD module 1:" in p and "GOOD module 1:" in p
        assert "differing only in an adjective" in p

    def test_the_good_example_is_actually_anatomical(self):
        """The example has to carry the vocabulary, not describe it."""
        p = syllabus_prompt()
        for term in ('"cortical bone"', '"mandibular canal"', '"mental foramen"'):
            assert term in p, term

    def test_it_caps_how_much_the_modules_may_share(self):
        p = syllabus_prompt()
        assert "At most one concept group may be shared across modules" in p

    def test_the_or_expansion_rule_survived(self):
        """The new rule sits alongside the old one; losing OR-expansion would
        trade one retrieval failure for a worse one."""
        p = syllabus_prompt()
        assert "must be OR-expanded, not a list of words" in p
        assert "PubMed ANDs bare words together" in p

    def test_it_still_forbids_duplicating_the_appended_filters(self):
        p = syllabus_prompt()
        assert "Do NOT add [pt] design filters" in p
