"""Item 5 — `context_block` is additive, so it must be applied exactly once.

WHERE THIS CAME FROM. Measuring the impact-factor removal, an A/B arm was
built by passing a with-IF evidence context through `context_block`. That arm
received the whole evidence base TWICE -- 102,242 input tokens against the
other arm's 27,514, $1.77 against $1.06 -- because `_with_context` PREPENDS
its block to a prompt that already embedded the evidence. The measurement was
of duplicated context, not of the signal under test. The token counts gave it
away.

That was a mistake in a measurement script, not in production. This file
exists to establish that it is ALSO not in production, and to keep it that
way, because the failure is invisible: a doubled block produces a valid
answer at roughly double the input cost, and nothing downstream complains.

WHAT `context_block` ACTUALLY IS. Not an evidence channel -- the conversation
history for a Review thread, built by `build_context_block(exchanges)`:
the earlier questions, their recommendations and the PMIDs they cited.
`ask_clinical_question` builds the EVIDENCE separately via
`_build_evidence_context` and embeds it in the prompt body. The two are
different things that both end up in one prompt, which is exactly why passing
one through the other's parameter silently doubled it.

WHAT IS PINNED
  1. `_with_context` is a prepend, and an empty block is byte-identical to no
     block at all -- the property every offline test depends on.
  2. On every production path that accepts a `context_block`, the label
     appears AT MOST ONCE in the prompt actually sent to the model. Asserted
     on captured prompts, not by reading the source, because the retry branch
     in `generate_multi_search_terms` appends to an already-contextualised
     prompt and is precisely where a second application would hide.
  3. Nesting is caught: `_with_context` applied twice to one prompt yields two
     labels, and the guard above would see it.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import endo_ai as E

LABEL = E.CONTEXT_BLOCK_LABEL

EXCHANGES = [
    {"question": "Single visit versus multiple visit for necrotic teeth?",
     "recommendation": "Single visit is acceptable where the canal can be dried.",
     "pmids": ["27759881", "35762859"]},
]


@pytest.fixture
def block():
    b = E.build_context_block(EXCHANGES)
    assert b and LABEL in b
    return b


class TestTheHelperItself:

    def test_an_empty_block_changes_nothing(self):
        assert E._with_context("", "PROMPT") == "PROMPT"
        assert E._with_context(None, "PROMPT") == "PROMPT"
        assert E._with_context("   ", "PROMPT") == "PROMPT"

    def test_it_prepends_rather_than_replaces(self, block):
        out = E._with_context(block, "PROMPT BODY")
        assert out.endswith("PROMPT BODY")
        assert out.startswith(block.strip()[:40])
        assert LABEL in out

    def test_applying_it_twice_doubles_the_block(self, block):
        """The defect being guarded against, stated as a fact about the
        helper. It is additive by design; safety comes from calling it once."""
        once = E._with_context(block, "P")
        twice = E._with_context(block, once)
        assert once.count(LABEL) == 1
        assert twice.count(LABEL) == 2


class TestEveryProductionPathAppliesItOnce:
    """Asserted on the prompt actually handed to the model.

    `_invoke_claude` is the single choke point every one of these paths goes
    through, so capturing there sees the real string rather than an
    intermediate. Reading the source would not have covered the retry branch
    of `generate_multi_search_terms`, which appends to an already-
    contextualised prompt -- the one place a second application could hide.
    """

    @pytest.fixture
    def captured(self, monkeypatch):
        seen = []

        class _Resp:
            class _C:
                text = "TERM: root canal\nTERM: pulpitis\nTERM: apical\nTERM: endodontic"
            content = [_C()]

            class usage:
                input_tokens = 10
                output_tokens = 10
                cache_creation_input_tokens = 0
                cache_read_input_tokens = 0

        def _fake(client, *a, **kw):
            for m in kw.get("messages", []):
                seen.append(m.get("content", ""))
            return _Resp()

        monkeypatch.setattr(E, "_invoke_claude", _fake)
        monkeypatch.setattr(E, "log_llm_call", lambda *a, **kw: None)
        monkeypatch.setattr(E, "_get_api_key", lambda: "test-key")
        return seen

    def test_generate_search_terms(self, captured, block):
        E.generate_search_terms("does articaine outperform lidocaine?",
                                context_block=block)
        assert captured, "no prompt captured"
        for p in captured:
            assert p.count(LABEL) <= 1, "context block applied twice"
        assert any(p.count(LABEL) == 1 for p in captured)

    def test_generate_multi_search_terms_including_its_retry(self, captured, block):
        """The retry branch appends to an already-contextualised prompt. If it
        ever re-wraps, this is where it shows."""
        E.generate_multi_search_terms("does articaine outperform lidocaine?",
                                      "(articaine) AND (lidocaine)",
                                      context_block=block)
        assert captured
        for p in captured:
            assert p.count(LABEL) <= 1, (
                "context block applied twice in generate_multi_search_terms — "
                "check the corrective-retry prompt")

    def test_classify_question_intent(self, captured, block):
        try:
            E.classify_question_intent("what about in pregnancy?",
                                       context_block=block)
        except Exception:
            pass          # parsing the stub reply may fail; the prompt is the subject
        for p in captured:
            assert p.count(LABEL) <= 1

    def test_generate_clarifying_questions(self, captured, block):
        try:
            E.generate_clarifying_questions("vital pulp therapy",
                                            context_block=block)
        except Exception:
            pass
        for p in captured:
            assert p.count(LABEL) <= 1


class TestTheEvidenceContextIsNotRoutedThroughIt:
    """The specific confusion that caused the measurement error.

    `_build_evidence_context` output belongs in the prompt BODY, which
    `ask_clinical_question` already does. Nothing in production may hand it to
    `context_block` as well -- that is what doubled 27k tokens to 102k.
    """

    def test_ask_clinical_question_builds_evidence_itself(self):
        src = (Path(__file__).parent.parent / "endo_ai.py").read_text(encoding="utf-8")
        i = src.index("def ask_clinical_question(")
        j = src.index("\ndef ", i + 1)
        body = src[i:j]
        assert "_build_evidence_context(evidence)" in body, (
            "ask_clinical_question no longer builds its own evidence context; "
            "if a caller now supplies it, check it is not ALSO passed as "
            "context_block")

    def test_no_production_call_site_passes_evidence_as_context_block(self):
        """Grep-level guard over both modules. A call site writing
        `context_block=<something evidence-shaped>` is the defect."""
        for name in ("endo_ai.py", "app.py"):
            src = (Path(__file__).parent.parent / name).read_text(encoding="utf-8")
            for lineno, line in enumerate(src.splitlines(), 1):
                if "context_block=" not in line:
                    continue
                arg = line.split("context_block=", 1)[1]
                assert "_build_evidence_context" not in arg, (
                    f"{name}:{lineno} passes the evidence context as "
                    f"context_block; it is ADDITIVE and the evidence is "
                    f"already in the prompt body — this doubles it")
                assert "evidence" not in arg.split(",")[0].lower(), (
                    f"{name}:{lineno} passes something evidence-shaped as "
                    f"context_block: {line.strip()[:100]}")
