"""A22a — a step is never separated from its list number, on any served answer.

WHAT WAS MEASURED. The first scan for this looked for a bare `N.` line and
reported **0 split list items** across the stored corpus. On that zero, A22a and
the literal `**` leak were re-filed as *renderer* defects and moved to the
browser lane. The corpus writes the number BOLD — `**3.**` — so the detector
matched nothing. Corrected, the same corpus gives:

    quarantine blocks                       114   (file corpus, no DB)
    blocks preceded by an orphan number       30
    blocks that cut a bold run in half        24
    blocks leaving an orphan closing `**`     24

Verbatim, from `learn_history/20260902_200429_apicoectomy_of_mandibular_teeth`:

    **3.**

    > ⚠ **NOT FROM THE EVIDENCE BASE — UNVERIFIED**
    > …
    > Administer local anaesthesia**
    > Inferior alveolar nerve block plus long buccal infiltration …

The step lost its number AND its opening `**`, which is the literal `**` RB saw
rendered. One defect, two symptoms, and it is text-layer — not the renderer.

THE GENERATOR IS ALREADY FIXED. A22b's size split (285acf8, 2026-09-03 20:00)
keeps a one- or two-sentence step whole and marks it inline; all 30 cases
predate that commit by at least eight hours. What is pinned here is therefore
the READ-TIME repair, because A16b re-renders every stored answer on every read
and A16's rule is that a stored answer must never render a surface the current
code would not produce.

Only the FILE corpus is used, so these tests need no database.
"""
import glob
import importlib.util
import json
import os
from pathlib import Path

import pytest

import endo_ai as E

ROOT = Path(__file__).parent.parent


def _load_scanner():
    spec = importlib.util.spec_from_file_location(
        "scan_split_items", str(ROOT / "scripts" / "scan_split_items.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sc = _load_scanner()


def _file_corpus():
    docs = []
    for p in sorted(glob.glob(str(ROOT / "learn_history" / "*.json"))):
        try:
            rec = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        docs.append((os.path.basename(p), rec.get("answer") or ""))
    for p in sorted(glob.glob(str(ROOT / "answers" / "*.txt"))):
        docs.append((os.path.basename(p),
                     open(p, encoding="utf-8", errors="replace").read()))
    return docs


@pytest.fixture(scope="module")
def stored():
    docs = _file_corpus()
    if len(docs) < 50:
        pytest.skip("stored corpus not present in this checkout")
    return docs


@pytest.fixture(scope="module")
def served(stored):
    return [(n, E.finalise_answer_text(t)[0]) for n, t in stored]


class TestTheDetectorStillSeesTheDefect:
    """Rule 4 — the pair that fails when the assertion below goes vacuous.

    `test_no_split_list_items_on_any_served_answer` passes trivially if the
    detector stops matching, which is precisely how this defect hid for a day.
    These assert the instrument is still sharp against the UNREPAIRED text.
    """

    def test_stored_corpus_still_contains_the_defect(self, stored):
        tot, _ = sc.scan_corpus(stored)
        assert tot["blocks"] >= 100, tot
        assert tot["orphan_number"] >= 25, (
            "the detector no longer finds the orphaned list numbers in the "
            "stored corpus - it has drifted again, and the served-side test "
            "is now vacuous: %s" % tot)
        assert tot["odd_stars"] >= 20, tot

    def test_a_bare_number_detector_would_have_found_none_of_them(self, stored):
        """The exact instrument bug, pinned so it cannot come back."""
        import re
        bare_only = re.compile(r"^(\d{1,2})[.)]\s*$")
        found = 0
        for _name, text in stored:
            for start, _end, _block in sc._blocks(text):
                before = [ln for ln in text[max(0, start - 60):start].split("\n")
                          if ln.strip()]
                if before and bare_only.match(before[-1].strip()):
                    found += 1
        assert found == 0, (
            "a bare `N.` detector now matches %d blocks; the corpus shape has "
            "changed and this test's premise needs re-deriving" % found)


class TestServedAnswersAreClean:

    def test_no_split_list_items_on_any_served_answer(self, served):
        tot, per = sc.scan_corpus(served)
        bad = [d for d in per if d["orphan_number"] or d["odd_stars"]
               or d["orphan_close"]]
        assert tot["orphan_number"] == 0, (
            "%d block(s) still orphan a list number after re-render: %s"
            % (tot["orphan_number"], [d["doc"] for d in bad][:5]))
        assert tot["odd_stars"] == 0, (
            "%d block(s) still cut a bold run: %s"
            % (tot["odd_stars"], [d["doc"] for d in bad][:5]))
        assert tot["orphan_close"] == 0, tot

    def test_the_repair_does_not_drop_the_quarantine(self, stored, served):
        """A44n's requirement: nothing written before today loses its label.

        The block becomes an INLINE mark at one or two sentences (A22b), so the
        block count falls — but every document that carried a quarantine must
        still carry one, in one form or the other.
        """
        for (name, before), (_n, after) in zip(stored, served):
            had = bool(sc._blocks(before))
            if not had:
                continue
            still_labelled = (bool(sc._blocks(after))
                              or E._QUARANTINE_INLINE_MARK in after)
            assert still_labelled, "%s lost its quarantine entirely" % name

    def test_re_rendering_twice_changes_nothing(self, served):
        """Rule 18 — the archive routes re-render on EVERY read."""
        for name, once in served:
            twice, _ = E.finalise_answer_text(once)
            assert twice == once, "%s is not idempotent" % name


class TestTheTwoRealShapes:
    """Both shapes come from stored text, not from invention. They are the only
    two that exist in the corpus (n=24 and n=6)."""

    SHAPE_A = (
        "**3.**\n\n"
        "> ⚠ **NOT FROM THE EVIDENCE BASE — UNVERIFIED**\n"
        ">\n"
        "> _General clinical knowledge. No paper in this library was retrieved "
        "for it and nothing below was checked against an abstract._\n"
        ">\n"
        "> Administer local anaesthesia**\n"
        "> Inferior alveolar nerve block plus long buccal infiltration for "
        "mandibular molars and premolars — standard practice, not from the "
        "retrieved evidence base.\n"
        ">\n"
        "> **Consult directly:** the specialty guidelines for this question "
        "— Curo has not retrieved or checked them.\n")

    SHAPE_B = (
        "**5.**\n\n"
        "> ⚠ **NOT FROM THE EVIDENCE BASE — UNVERIFIED**\n"
        ">\n"
        "> _General clinical knowledge. No paper in this library was retrieved "
        "for it and nothing below was checked against an abstract._\n"
        ">\n"
        "> **Final chelating rinse with 17% EDTA**\n"
        "> One minute, then a final rinse — standard practice, not from the "
        "retrieved evidence base.\n"
        ">\n"
        "> **Consult directly:** the specialty guidelines for this question "
        "— Curo has not retrieved or checked them.\n")

    def test_shape_a_rejoins_the_number_and_closes_the_bold_run(self):
        out, _ = E.finalise_answer_text(self.SHAPE_A)
        assert "3. **Administer local anaesthesia**" in out, out
        assert "**3.**" not in out
        body = out.replace(E._QUARANTINE_LEGEND, "")
        assert body.count("**") % 2 == 0, "a bold run is still unbalanced"

    def test_shape_b_rejoins_the_number(self):
        out, _ = E.finalise_answer_text(self.SHAPE_B)
        assert "5. **Final chelating rinse with 17% EDTA**" in out, out
        assert "**5.**" not in out

    def test_the_step_is_still_labelled_after_the_repair(self):
        for shape in (self.SHAPE_A, self.SHAPE_B):
            out, _ = E.finalise_answer_text(shape)
            assert E._QUARANTINE_INLINE_MARK in out or "NOT CHECKED" in out, (
                "the step was un-quarantined by the repair")

    def test_a_block_with_no_orphan_number_is_left_alone(self):
        """The repair is targeted. Converting every legacy block is A22e/A44n's
        question, and doing it here would change 88 blocks nobody asked about."""
        plain = self.SHAPE_A.replace("**3.**\n\n", "")
        out, _ = E.finalise_answer_text(plain)
        assert "NOT FROM THE EVIDENCE BASE" in out, (
            "a legacy block with no orphaned number was rewritten anyway")
