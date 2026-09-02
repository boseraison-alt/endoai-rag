"""
Cross-module consistency (`dl-quality-v1` Item 4).

THE DEFECT THIS ADDRESSES IS INVISIBLE TO EVERY OTHER GUARDRAIL. Four module
authors write independently from four different evidence bases. Each module is
internally consistent, correctly cited, and passes validation. Nothing has ever
compared their outputs to EACH OTHER.

Measured on the two stored curricula before writing any of this:

  NaOCl appears at 2%, 2.5%, 3% and 5.25% across modules 1 and 3 of the laser
  curriculum. Every one is right for the study it came from. Together, with
  nothing saying which is which, they are not a protocol.

  Lidocaine appears at 1.8% and 2% across modules 1 and 3 of the anesthesia
  curriculum — and 1.8% is not a lidocaine concentration at all, it is the
  CARTRIDGE VOLUME in mL, transcribed as a percentage.

  220 IF/THEN/BECAUSE branches exist across every stored curriculum; 4 have a
  BECAUSE containing no reason. One holds nothing but
  `[[PMID:40818665]] [[PMID:41389357]]` — a citation where a justification
  should be.

THE DETECTORS ARE DETERMINISTIC AND THE MODEL IS NEVER ASKED TO FIND ANYTHING.
It is asked only to write the sentence for a conflict already found. A model
asked to find conflicts finds them whether or not they are there, and this pass
edits a document that has already passed every other gate.

AND THE MODEL NEVER RETURNS THE DOCUMENT. It returns anchors and sentences,
and `_apply_consistency_edits` does the editing. That makes "annotate only" a
structural property rather than something a guard has to catch afterwards, and
it keeps the reply small enough that the pass cannot itself be truncated —
returning a 40,000-character document from a model with an output cap is
exactly how Item 1's defect got into the modules.
"""

import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai
from endo_ai import (consistency_guard, detect_malformed_because,
                     detect_parameter_conflicts, extract_numeric_parameters)

FIXTURES = Path(__file__).parent.parent / "eval" / "fixtures" / "curricula"
LASER = FIXTURES / "laser_disinfection_20260901_before.txt"
ANESTH = FIXTURES / "anesthesia_20260901_before.txt"


def _modules(text):
    body = text.split("## Citation Support by Module")[0]
    parts = re.split("^(## Module[^" + chr(92) + "n]*)$", body, flags=re.M)
    return [(parts[i].strip(), parts[i + 1]) for i in range(1, len(parts), 2)]


# ── (a) numeric parameter conflicts ───────────────────────

class TestParameterExtraction:

    def test_the_ordinary_forms_both_parse(self):
        got = extract_numeric_parameters(
            "Irrigate with 5.25% NaOCl. Then NaOCl at 2% for activation.")
        assert {(p["agent"], p["value"]) for p in got} == {
            ("naocl", 5.25), ("naocl", 2.0)}

    def test_a_success_rate_is_not_a_concentration(self):
        """The filter that makes this usable. A percentage beside a drug name
        is usually an outcome, and the two are identical in shape — so the
        distinction has to come from the domain, not the text."""
        got = extract_numeric_parameters(
            "Articaine achieved 87.1% success versus lidocaine.")
        assert not [p for p in got if p["value"] == 87.1]

    def test_a_rate_word_INSIDE_the_match_still_disqualifies_it(self):
        """The case the mutation run exposed.

        The rate-word window used to end at the start of the match, which is
        fine for "achieved 87.1% success with articaine" and useless for
        "articaine success 12%" — where the rate word sits BETWEEN the agent
        and the number, inside the match. That parsed as a 12% articaine
        concentration. The only test exercising the filter was being caught by
        the 20% ceiling instead, so disabling the filter entirely changed
        nothing and the mutant lived.

        12 is under the ceiling, so this case can only be caught by the filter.
        """
        got = extract_numeric_parameters("articaine success 12%")
        assert not got, f"a success rate parsed as a concentration: {got}"

    def test_the_forward_form_takes_no_filler_word(self):
        """REAL SENTENCES, because the synthetic one I first wrote was already
        caught by the rate filter and left the mutant alive.

        Measured across every stored curriculum: allowing ONE filler word in
        the forward form produces exactly two extra parses, and both are the
        same error — a value being attached to the wrong agent because the
        right one is a word further away.
        """
        # "0.1 mg/mL" is toluidine blue's; "0.005%" is methylene blue's.
        got = extract_numeric_parameters(
            "A photosensitiser (methylene blue 0.005% or toluidine blue "
            "0.1 mg/mL) applied to the canal absorbs light")
        assert ("toluidine blue", 0.005) not in {(p["agent"], p["value"])
                                                 for p in got}
        assert ("methylene blue", 0.005) in {(p["agent"], p["value"])
                                             for p in got}

        # "2%" is mepivacaine's; epinephrine is two words further on.
        got = extract_numeric_parameters(
            "no significant efficacy difference among lidocaine 2%, "
            "articaine 4%, bupivacaine 0.5%, and mepivacaine 2% for IANB")
        assert ("epinephrine", 2.0) not in {(p["agent"], p["value"])
                                            for p in got}

    def test_no_endodontic_irrigant_is_above_twenty_percent(self):
        """EDTA at 17% is the strongest of them, so anything above 20% beside
        an agent name is an outcome.

        REAL SENTENCES again. The synthetic "Success was 93.0% with NaOCl" is
        caught by the rate-word filter instead, so it left the ceiling mutant
        alive. Measured across every stored curriculum, removing the ceiling
        produces exactly three extra parses; these are two of them, and
        neither has a rate word within reach of the number.
        """
        got = extract_numeric_parameters(
            "KTP laser for chamber disinfection yielded a 12-month success "
            "rate of 90.5% (19/21 teeth) versus 86.4% for NaOCl and 86.4% "
            "for saline")
        assert ("naocl", 86.4) not in {(p["agent"], p["value"]) for p in got}

        got = extract_numeric_parameters(
            "adjunctive PDT reduced the need for inter-appointment calcium "
            "hydroxide from 72.4% to 16.4% in primary treatment cases")
        assert ("calcium hydroxide", 72.4) not in {(p["agent"], p["value"])
                                                   for p in got}

        # ...and the strongest real concentration still parses.
        assert extract_numeric_parameters("Chelate with 17% EDTA")

    def test_a_value_belonging_to_the_NEXT_agent_is_not_stolen(self):
        """"2.5% NaOCl with 17% EDTA" — the backward form matches
        "NaOCl with 17%" and filed EDTA's concentration under NaOCl, which
        produced a phantom fifth NaOCl concentration in the first run."""
        got = extract_numeric_parameters(
            "used 2.5% NaOCl with 17% EDTA as the conventional protocol.")
        assert ("naocl", 17.0) not in {(p["agent"], p["value"]) for p in got}
        assert ("naocl", 2.5) in {(p["agent"], p["value"]) for p in got}
        assert ("edta", 17.0) in {(p["agent"], p["value"]) for p in got}


class TestConflictDetection:

    def test_one_module_using_two_values_is_not_a_conflict(self):
        """A single passage contrasting 2% and 5.25% is deliberate, and
        annotating it would clutter a document that is already clear."""
        mods = [("## Module 1", "Use 5.25% NaOCl, or 2% NaOCl for activation.")]
        assert detect_parameter_conflicts(mods) == []

    def test_two_modules_disagreeing_is_a_conflict(self):
        mods = [("## Module 1", "Irrigate with 5.25% NaOCl."),
                ("## Module 3", "The trial used 2.5% NaOCl.")]
        out = detect_parameter_conflicts(mods)
        assert len(out) == 1
        assert out[0]["agent"] == "naocl"
        assert [v["value"] for v in out[0]["values"]] == [2.5, 5.25]

    def test_the_same_value_in_two_modules_is_not_a_conflict(self):
        mods = [("## Module 1", "Irrigate with 5.25% NaOCl."),
                ("## Module 3", "They used 5.25% NaOCl.")]
        assert detect_parameter_conflicts(mods) == []

    @pytest.mark.skipif(not LASER.exists(), reason="fixture absent")
    def test_the_real_laser_curriculum_reproduces_the_items_example(self):
        """`NaOCl 2/2.5/3/5.25%`, which is the conflict the item names."""
        mods = _modules(LASER.read_text(encoding="utf-8", errors="replace"))
        out = detect_parameter_conflicts(mods)
        naocl = [c for c in out if c["agent"] == "naocl"]
        assert naocl, f"NaOCl conflict not found; got {[c['agent'] for c in out]}"
        assert {v["value"] for v in naocl[0]["values"]} == {2.0, 2.5, 3.0, 5.25}

    @pytest.mark.skipif(not ANESTH.exists(), reason="fixture absent")
    def test_the_real_anesthesia_curriculum_finds_the_transcription_error(self):
        """1.8% lidocaine is not a concentration — 1.8 mL is the cartridge
        volume. The detector found a real error in the curriculum, not just a
        difference between studies."""
        mods = _modules(ANESTH.read_text(encoding="utf-8", errors="replace"))
        out = detect_parameter_conflicts(mods)
        lido = [c for c in out if c["agent"] == "lidocaine"]
        assert lido
        assert 1.8 in {v["value"] for v in lido[0]["values"]}


# ── (c) malformed IF/THEN/BECAUSE ─────────────────────────

class TestMalformedBecause:

    def test_a_because_that_is_only_citations(self):
        out = detect_malformed_because(
            "**IF** x\n**THEN** y\n**BECAUSE** [[PMID:1]] [[PMID:2]]")
        assert len(out) == 1
        assert "only citations" in out[0]["reason"]

    def test_an_empty_because(self):
        out = detect_malformed_because("**BECAUSE**\n\n**IF** next")
        assert len(out) == 1
        assert out[0]["reason"] == "empty"

    def test_a_real_reason_is_left_alone(self):
        out = detect_malformed_because(
            "**BECAUSE** the tubercle fractures and exposes the pulp horn "
            "[[PMID:1]]")
        assert out == []

    def test_a_reason_with_no_citation_at_all_is_still_a_reason(self):
        """This detector is about MISSING REASONING, not missing citations.
        The unattributed-claim validator owns the other question, and having
        two checks disagree about one sentence helps nobody."""
        assert detect_malformed_because(
            "**BECAUSE** the canal is unlikely to be negotiable") == []

    @pytest.mark.skipif(not LASER.exists(), reason="fixture absent")
    def test_the_real_curriculum_has_exactly_one(self):
        out = detect_malformed_because(
            LASER.read_text(encoding="utf-8", errors="replace"))
        assert len(out) == 1
        assert "40818665" in out[0]["because"]


# ── the guard ─────────────────────────────────────────────

class TestTheGuardIsWhatMakesThisSafe:
    """"This pass ANNOTATES and repairs formatting; it must not rewrite
    evidence claims." That is the whole mandate, and it is enforced twice —
    structurally, because the model returns anchors rather than a document,
    and then again here."""

    BEFORE = ("Irrigate with 5.25% NaOCl [[PMID:111]].\n\n"
              "**BECAUSE** [[PMID:222]]\n")

    def test_an_inserted_sentence_is_allowed(self):
        after = self.BEFORE.replace(
            "[[PMID:111]].", "[[PMID:111]].\n\nThe 2.5% figure is Yang 2024.")
        assert consistency_guard(self.BEFORE, after)[0]

    def test_a_dropped_marker_is_rejected(self):
        ok, why = consistency_guard(self.BEFORE,
                                    self.BEFORE.replace(" [[PMID:111]]", ""))
        assert not ok and "markers changed" in why

    def test_an_added_marker_is_rejected(self):
        """Adding one attaches a paper to a sentence no module author chose it
        for, which is the cheap fix `case-v3` Item B forbids by name."""
        ok, why = consistency_guard(
            self.BEFORE, self.BEFORE.replace("[[PMID:111]]",
                                             "[[PMID:111]] [[PMID:999]]"))
        assert not ok and "markers changed" in why

    def test_a_reworded_cited_claim_is_rejected(self):
        ok, why = consistency_guard(
            self.BEFORE, self.BEFORE.replace("Irrigate with", "Flush using"))
        assert not ok and "rewritten" in why

    def test_a_flagged_because_MAY_be_repaired(self):
        """The one exemption, and it is exactly the lines the detector
        flagged — not 'any line the model felt like changing'."""
        after = self.BEFORE.replace(
            "**BECAUSE** [[PMID:222]]",
            "**BECAUSE** residual biofilm survives conventional irrigation "
            "[[PMID:222]]")
        assert consistency_guard(self.BEFORE, after,
                                 repairable=["[[PMID:222]]"])[0]

    def test_the_exemption_does_not_licence_editing_other_lines(self):
        after = self.BEFORE.replace("Irrigate with", "Flush using")
        ok, _ = consistency_guard(self.BEFORE, after,
                                  repairable=["[[PMID:222]]"])
        assert not ok


class TestTheEditsAreAppliedProgrammatically:

    def test_a_bad_anchor_is_dropped_not_guessed(self):
        text = "Line one.\n\nLine two."
        out, counts = endo_ai._apply_consistency_edits(
            text, {"annotations": [{"anchor": "Line three.", "text": "X"}]}, [])
        assert out == text
        assert counts["dropped_anchor"] == 1
        assert counts["annotations"] == 0

    def test_an_anchor_is_matched_verbatim_and_inserted_after(self):
        text = "Line one.\n\nLine two."
        out, counts = endo_ai._apply_consistency_edits(
            text, {"annotations": [{"anchor": "Line one.", "text": "Added."}]},
            [])
        assert out == "Line one.\n\nAdded.\n\nLine two."
        assert counts["annotations"] == 1

    def test_a_repair_that_does_not_match_is_dropped(self):
        out, counts = endo_ai._apply_consistency_edits(
            "**BECAUSE** [[PMID:1]]",
            {"repairs": [{"because": "[[PMID:9]]", "text": "reason"}]}, [])
        assert counts["dropped_because"] == 1
        assert out == "**BECAUSE** [[PMID:1]]"


class TestThePassFailsClosed:

    def test_no_detections_means_no_llm_call(self, monkeypatch):
        """A pass that runs on a clean document spends money to change
        nothing, and gives a model an opportunity to touch it."""
        called = []
        monkeypatch.setattr(endo_ai, "_invoke_claude",
                            lambda *a, **k: called.append(1))
        text = "Nothing to reconcile here [[PMID:1]]."
        out, cost, report = endo_ai.annotate_curriculum_consistency(
            text, [("## Module 1", text)], "q")
        assert out == text
        assert cost == 0.0
        assert not called
        assert report["reason"] == "nothing detected"

    def test_an_unparseable_reply_leaves_the_document_alone(self, monkeypatch):
        text = ("## Module 1\nIrrigate with 5.25% NaOCl [[PMID:1]].\n"
                "## Module 3\nThey used 2.5% NaOCl [[PMID:2]].\n")
        mods = [("## Module 1", "Irrigate with 5.25% NaOCl [[PMID:1]]."),
                ("## Module 3", "They used 2.5% NaOCl [[PMID:2]].")]
        _stub_model(monkeypatch, "this is not json")
        out, _cost, report = endo_ai.annotate_curriculum_consistency(
            text, mods, "q")
        assert out == text
        assert not report["applied"]
        assert "unparseable" in report["reason"]

    def test_a_pass_that_rewrites_a_claim_is_discarded_ENTIRELY(self, monkeypatch):
        """Not partially. The good annotations go with the bad one, because an
        annotation is a convenience and a rewritten evidence claim is a
        defect."""
        text = ("## Module 1\nIrrigate with 5.25% NaOCl [[PMID:1]].\n"
                "## Module 3\nThey used 2.5% NaOCl [[PMID:2]].\n")
        mods = [("## Module 1", "Irrigate with 5.25% NaOCl [[PMID:1]]."),
                ("## Module 3", "They used 2.5% NaOCl [[PMID:2]].")]
        _stub_model(monkeypatch, json_dumps({
            "annotations": [
                {"anchor": "Irrigate with 5.25% NaOCl [[PMID:1]].",
                 "text": "A fine reconciling sentence.", "kind": "parameter"}],
            # a repair whose "because" is an ordinary cited line
            "repairs": [{"because": "They used 2.5% NaOCl [[PMID:2]].",
                         "text": "They used 3% NaOCl [[PMID:2]]."}],
        }))
        out, _cost, report = endo_ai.annotate_curriculum_consistency(
            text, mods, "q")
        assert out == text, "the rewritten claim survived"
        assert not report["applied"]
        assert "guard rejected" in report["reason"]

    def test_a_clean_pass_is_applied(self, monkeypatch):
        text = ("## Module 1\nIrrigate with 5.25% NaOCl [[PMID:1]].\n"
                "## Module 3\nThey used 2.5% NaOCl [[PMID:2]].\n")
        mods = [("## Module 1", "Irrigate with 5.25% NaOCl [[PMID:1]]."),
                ("## Module 3", "They used 2.5% NaOCl [[PMID:2]].")]
        _stub_model(monkeypatch, json_dumps({
            "annotations": [
                {"anchor": "Irrigate with 5.25% NaOCl [[PMID:1]].",
                 "text": "The 2.5% figure is the conventional-protocol arm.",
                 "kind": "parameter"}],
            "repairs": [],
        }))
        out, _cost, report = endo_ai.annotate_curriculum_consistency(
            text, mods, "q")
        assert report["applied"], report
        assert "conventional-protocol arm" in out
        assert "Irrigate with 5.25% NaOCl [[PMID:1]]." in out


# ── helpers ───────────────────────────────────────────────

def json_dumps(o):
    import json
    return json.dumps(o)


def _stub_model(monkeypatch, reply_text):
    class _Usage:
        input_tokens = 10
        output_tokens = 10

    class _R:
        content = [type("B", (), {"text": reply_text})()]
        usage = _Usage()

    monkeypatch.setattr(endo_ai.anthropic, "Anthropic", lambda **kw: object())
    monkeypatch.setattr(endo_ai, "_get_api_key", lambda: "test")
    monkeypatch.setattr(endo_ai, "log_llm_call", lambda *a, **k: 0.0)
    monkeypatch.setattr(endo_ai, "_invoke_claude", lambda *a, **k: _R())
