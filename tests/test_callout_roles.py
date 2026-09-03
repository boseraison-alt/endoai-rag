"""
A44m — the generator emits a semantic ROLE; the renderer owns appearance.

A9 says the model writes prose and never metadata. This is that one step out.

MEASURED BEFORE BUILDING, and the measurement changes what this item IS. Across
160 stored curricula, answers and fixtures there is not one HTML tag, CSS class,
inline style, custom property, colour instruction or box-drawing character in
model output. The only regex hits were `#14A` and `#9` — rubber dam clamp sizes.

**So A44m is a GUARD AGAINST DRIFT, not a repair of a live leak**, and RB's
stated reason is the correct one: without the rule the vocabulary drifts, the
model invents box types, two of them mean the same thing, and A22's eighteen
boxes return under new names.

What HAS accumulated is ad-hoc SHAPES — 1,309 blockquotes across 119 documents,
225 emoji callouts across 83, 117 bold-label lines across 47 — which is the same
drift one level down. Hence a closed vocabulary.

Every test here is mutation-checked.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai as e

ROOT = Path(__file__).parent.parent


class TestTheVocabularyIsClosed:

    def test_it_is_four_or_five_roles(self):
        """A44a: 'define exactly four or five callout types'. A vocabulary that
        grows is the thing this item exists to prevent."""
        assert 4 <= len(e.CALLOUT_ROLES) <= 5

    def test_every_role_has_exactly_one_tag(self):
        tags = list(e.CALLOUT_ROLES.values())
        assert len(set(tags)) == len(tags), "two roles share a tag"
        for role, tag in e.CALLOUT_ROLES.items():
            assert tag and tag.isupper(), role

    def test_the_quarantine_block_is_a_member_not_a_bespoke_thing(self):
        """A44a's explicit requirement."""
        assert "unverified" in e.CALLOUT_ROLES

    def test_no_tag_names_a_colour_or_a_shape(self):
        """The tag is what the block IS, never how it looks."""
        banned = ("RED", "AMBER", "GREEN", "YELLOW", "BOX", "BORDER", "GREY")
        for role, tag in e.CALLOUT_ROLES.items():
            assert not any(b in tag for b in banned), f"{role} -> {tag}"


class TestAnUnknownRoleRendersAsProse:
    """A44m's own test, verbatim: 'an unknown role renders as plain prose
    rather than as a guessed style'."""

    TEXT = ("Before.\n\n:::trap\nDo not resect more than 3 mm.\n:::\n\n"
            "Middle.\n\n:::warning\nAn invented role.\n:::\n\nAfter.")

    def test_a_known_role_survives(self):
        out = e.normalise_callouts(self.TEXT)
        assert ":::trap" in out
        assert "Do not resect more than 3 mm." in out

    def test_an_unknown_role_loses_its_fence(self):
        out = e.normalise_callouts(self.TEXT)
        assert ":::warning" not in out

    def test_an_unknown_role_KEEPS_ITS_CONTENT(self):
        """Stripping the body would delete clinical content to enforce a
        style rule. The fence goes; the words stay."""
        assert "An invented role." in e.normalise_callouts(self.TEXT)

    def test_it_is_not_given_a_guessed_style(self):
        out = e.normalise_callouts(self.TEXT)
        body = out[out.index("Middle."):]
        assert ":::" not in body.split("After.")[0]

    def test_normalising_is_idempotent(self):
        """Rule 18 — this runs at read time on every archive route."""
        once = e.normalise_callouts(self.TEXT)
        assert e.normalise_callouts(once) == once

    def test_parse_reports_which_roles_are_known(self):
        roles = e.parse_callouts(self.TEXT)
        assert [(r, k) for r, _b, k in roles] == [("trap", True), ("warning", False)]

    def test_case_and_spacing_do_not_smuggle_a_role_in(self):
        assert e.parse_callouts(":::TRAP\nx\n:::")[0][2] is True
        assert e.parse_callouts("::: trap \nx\n:::")[0][2] is True

    def test_normalising_matches_the_role_case_insensitively_too(self):
        """`parse_callouts` and `normalise_callouts` lowercase in two separate
        places, and a mutation that made only the second case-sensitive passed
        every other test here — an uppercase `:::TRAP` would have been stripped
        as unknown while `parse_callouts` still reported it as known."""
        for text in (":::TRAP\nx\n:::", "::: Trap \nx\n:::"):
            assert e.normalise_callouts(text) == text, text


class TestThePresentationRuleIsEnforcedNotStated:

    @pytest.mark.parametrize("bad,kind", [
        ('See <div class="box">x</div>', "html tag"),
        ('<span style="color:red">x</span>', "html tag"),
        ("border: var(--accent-red)", "css custom property"),
        ("color: #c00", "css declaration"),
        ("┌─────┐", "box drawing"),
        ("Highlight this in red for emphasis", "styling instruction"),
    ])
    def test_presentation_markup_is_detected(self, bad, kind):
        kinds = [k for k, _x in e.find_presentation_markup(bad)]
        assert kind in kinds, f"{bad!r} -> {kinds}"

    def test_ordinary_clinical_prose_is_not_flagged(self):
        """A false positive here would fail correct answers. `#14A` is a rubber
        dam clamp, and it is why the first measurement over-reported."""
        clean = ("Use a clamp appropriate to the tooth (e.g., #14A for molars, "
                 "#9 for premolars); resect 3 mm [[PMID:26449431]].")
        assert e.find_presentation_markup(clean) == []

    def test_a_role_fence_is_not_presentation(self):
        assert e.find_presentation_markup(":::trap\nDo not.\n:::") == []

    @pytest.mark.parametrize("clinical", [
        "Radiographs show red-free imaging is unnecessary.",
        "A red-brown discolouration was noted at the margin.",
        "These findings highlight the importance of the coronal seal.",
        "The review highlights three prognostic factors.",
    ])
    def test_hyphenated_and_idiomatic_prose_is_not_a_styling_instruction(self, clinical):
        """Rule 17, learned here: `\b` matches inside "red-free", so the first
        version of this pattern flagged a sentence about imaging. The colour
        word must not be followed by a hyphen or a letter."""
        assert e.find_presentation_markup(clinical) == []


class TestStoredDocumentsStillWork:
    """A44n — 22 stored curricula and every cached answer were written before
    this vocabulary existed. 'Should work' is not 'does'."""

    def _docs(self, limit=40):
        docs = (list((ROOT / "learn_history").rglob("*.md")) +
                list((ROOT / "answers").glob("*.txt")))
        return docs[:limit]

    def test_no_stored_document_is_changed_by_normalising(self):
        """Nothing stored contains a role fence, so normalising must be a
        no-op on every one of them. If this ever fails, a stored document has
        acquired a fence and A44n's verification is owed."""
        docs = self._docs()
        if not docs:
            pytest.skip("no stored documents in this checkout")
        for p in docs:
            text = p.read_text(encoding="utf-8", errors="ignore")
            assert e.normalise_callouts(text) == text, p.name

    def test_no_stored_document_carries_presentation_markup(self):
        """The measurement that made A44m a guard rather than a repair. If a
        future answer breaks this, the PROMPT regressed."""
        docs = self._docs()
        if not docs:
            pytest.skip("no stored documents in this checkout")
        offenders = {}
        for p in docs:
            found = e.find_presentation_markup(
                p.read_text(encoding="utf-8", errors="ignore"))
            if found:
                offenders[p.name] = found[:3]
        assert not offenders, offenders


class TestTheMeasurementIsRecordedBesideTheCode:

    def test_the_drift_counts_are_written_where_the_rule_is(self):
        src = (ROOT / "endo_ai.py").read_text(encoding="utf-8")
        assert "160 stored curricula" in src
        assert "rubber dam" in src.lower()
        assert "1309 occurrences" in src
