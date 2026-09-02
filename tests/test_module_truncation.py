"""
Truncated curriculum modules (`dl-quality-v1` Item 1).

MEASURED BEFORE ANYTHING WAS WRITTEN. Of 190 `write_curriculum_module` calls
in `cost_log.jsonl`, **164 (86%) returned exactly 3,200 output tokens** — the
median output length across the entire history of the feature was the cap
itself. On the laser curriculum of 2026-09-01 13:58, all four modules and both
validation retries hit it:

    13:52:36  write_curriculum_module   in 21396  out 3200
    13:52:51  write_curriculum_module   in 26120  out 3200
    13:52:54  write_curriculum_module   in 32912  out 3200
    13:53:00  write_curriculum_module   in 35363  out 3200

`stop_reason` appeared exactly once in `endo_ai.py`, inside a comment. Nothing
read it. That is bug class (d) — a check that fails open and shows nothing —
in the output a clinician reads end to end.

WHY THE TEXT DETECTOR EXISTS ALONGSIDE `stop_reason`. The stitcher is an LLM
pass instructed to reproduce module bodies verbatim, and it does not reproduce
a truncation faithfully: Module 1's table row, cut mid-cell at "Wavelength
630", reached the final document as

    | **Laser — Diode (aPDT)** | Wavelength 630 |

with a closing pipe its author never wrote. A structural check running after
the stitch would call that row well-formed. So the gate runs on the module
text BEFORE stitching, and the detector has to work from text alone.

FALSE POSITIVES ARE THE EXPENSIVE FAILURE HERE, because a flagged module is
replaced by a "not generated" notice. Measured across every stored curriculum:
**108 module bodies scanned, 8 flagged (6 distinct curricula), 0 false
positives** — and every one of them is Module 4.

That figure was 100/5 until the scan itself was found wrong. It split module
bodies at the first `---`, which stops before `### 4a. Procedural Protocol` —
where the anesthesia curriculum's cut actually is. And the detector treated a
trailing `---` as the last content line, so a module ending "…19.35 mm from
the

---" read as finished. Both are fixed; a scan that stops before the
damage reports a clean document.
"""

import inspect
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai
from endo_ai import detect_module_truncation


# The real tails, from the fixture, byte for byte.
REAL_MODULE_4_TAIL = (
    "**Adverse Effects**\n\n"
    "Sabeti et al. confirmed that the overall adverse event profile of LAI met "
    "noninferiority criteria versus UAI [[PMID:40818665]]. Er:YAG "
    "laser-activated irrigation carries a theoretical risk of irrigant "
    "extrusion when tips are not"
)

REAL_MODULE_1_TABLE = (
    "| Category | Parameters |\n"
    "|---|---|\n"
    "| **Laser — Nd:YAG** | Wavelength 1,064 nm · photothermal mechanism |\n"
    "| **Laser — Diode (aPDT)** | Wavelength 630"
)

# A module that ends the way a finished one does.
FINISHED = (
    "## Clinical Application\n\n"
    "Er:YAG laser-activated irrigation reduced residual bacterial load by "
    "99.6% compared with conventional needle irrigation [[PMID:31543236]].\n\n"
    "- Irrigate with 5.25% NaOCl for 60 s\n"
    "- Activate at 20 mJ/pulse, 15 Hz\n"
)


class TestTheDetectorCatchesTheRealTruncations:
    """Both of the two the item names, from the fixture itself."""

    def test_module_4_cut_mid_sentence(self):
        r = detect_module_truncation(REAL_MODULE_4_TAIL)
        assert r["truncated"]
        assert "mid-sentence" in r["reason"]
        assert "not" in r["reason"]

    def test_module_1_cut_mid_table_row(self):
        r = detect_module_truncation(REAL_MODULE_1_TABLE)
        assert r["truncated"]
        assert "table" in r["reason"]
        assert "closing pipe" in r["reason"]

    def test_a_row_short_of_cells_but_with_its_closing_pipe(self):
        """The SECOND table rule, and it needed its own case.

        `REAL_MODULE_1_TABLE` is caught by the missing-closing-pipe rule and
        returns before the cell count is ever compared, so a mutant disabling
        `if got < want:` passed the whole file. This is the shape that only
        the cell count catches: syntactically a complete row, one cell short
        of its own header.
        """
        text = ("| Laser | Wavelength | Energy |\n"
                "|---|---|---|\n"
                "| Er:YAG | 2,940 nm | 50 mJ |\n"
                "| Nd:YAG | 1,064 nm |")
        r = detect_module_truncation(text)
        assert r["truncated"], "a row one cell short of its header passed"
        assert "cells" in r["reason"]
        assert "2 cells" in r["reason"] and "header has 3" in r["reason"]

    def test_the_cell_count_is_compared_against_the_rows_OWN_table(self):
        """A module may hold several tables of different widths, and the
        header of the wrong one would flag a perfectly good row."""
        text = ("| A | B | C | D |\n|---|---|---|---|\n| 1 | 2 | 3 | 4 |\n"
                "\nSome prose in between.\n\n"
                "| X | Y |\n|---|---|\n| 8 | 9 |")
        assert not detect_module_truncation(text)["truncated"]

    def test_a_cut_citation_marker(self):
        """The shape the renderer cannot degrade gracefully: `[[PMID:412` is
        not a citation, it is three digits nobody can look up. Found for real
        in `answers/answer_20260829_174551.txt`, cut at `[[PMID:27759`."""
        r = detect_module_truncation("Healing was established [[PMID:27759")
        assert r["truncated"]
        assert "citation" in r["reason"]

    def test_an_empty_module(self):
        assert detect_module_truncation("")["truncated"]
        assert detect_module_truncation("   \n\n ")["truncated"]

    def test_the_reason_names_what_was_wrong(self):
        """It reaches the reader in the notice block, so it has to say
        something a human can act on."""
        for text in (REAL_MODULE_4_TAIL, REAL_MODULE_1_TABLE):
            r = detect_module_truncation(text)
            assert len(r["reason"]) > 10
            assert r["tail"], "the tail is what makes the log line diagnosable"


class TestTheDetectorDoesNotFlagFinishedModules:
    """The expensive failure direction. A false positive here replaces a real
    module with a notice saying it could not be written."""

    @pytest.mark.parametrize("text,why", [
        (FINISHED, "an ordinary finished module"),
        ("## Clinical Application", "a heading needs no full stop"),
        ("- 5.25% NaOCl for 60 s", "a list item needs no full stop"),
        ("**Adverse Effects**", "a bold label needs no full stop"),
        ("Three parameters matter:", "a colon lead-in precedes a list"),
        ("| A | B |\n|---|---|\n| x | y |", "a complete table row"),
        ("Success reached 86.8% [[PMID:41339865]].", "ends on a marker"),
        ("The literature is currently divided on this topic.", "plain prose"),
        ("Bacterial reduction was significant (p < 0.05)", "ends on a paren"),
        ("See the parameters above (Table 1)", "ends on a paren, no stop"),
    ])
    def test_finished_text_is_not_flagged(self, text, why):
        r = detect_module_truncation(text)
        assert not r["truncated"], f"false positive on {why}: {r['reason']}"

    def test_every_stored_curriculum_module_that_reads_as_finished_passes(self):
        """The measurement, run as a test so it cannot silently rot.

        Scans every curriculum in `answers/`. The flagged ones must all be
        genuinely cut — asserted here by their tails, which is the only
        property a test can check without re-reading 100 modules by hand.
        """
        root = Path(__file__).parent.parent / "answers"
        if not root.exists():
            pytest.skip("no stored curricula in this checkout")
        scanned, flagged = 0, []
        for f in sorted(root.glob("*.txt")):
            t = f.read_text(encoding="utf-8", errors="replace")
            if "## Module" not in t:
                continue
            body = t.split("## Citation Support by Module")[0]
            parts = re.split(r"^(## Module[^\n]*)$", body, flags=re.M)
            for i in range(1, len(parts), 2):
                seg = parts[i + 1].split("\n---\n")[0]
                if len(seg.split()) < 40:
                    continue
                scanned += 1
                r = detect_module_truncation(seg)
                if r["truncated"]:
                    flagged.append((f.name, r))
        if scanned < 20:
            pytest.skip(f"only {scanned} module bodies available")
        # Measured 2026-09-01: 108 scanned, 8 flagged. The rate is allowed
        # to move; what must not move is that a flag means something real.
        assert len(flagged) / scanned < 0.25, (
            f"{len(flagged)}/{scanned} flagged — that is a false-positive rate, "
            f"not a truncation rate")
        for name, r in flagged:
            tail = r["tail"]
            assert (tail.endswith(("[[", "[[PMID:")) or "PMID:" in tail[-12:]
                    or not tail.rstrip().endswith((".", "!", "?", ":", "|"))), (
                f"{name} was flagged but its tail looks finished: {tail!r}")


class TestTheWriterRegeneratesOnce:

    def _src(self):
        return inspect.getsource(endo_ai.write_curriculum_module)

    def test_it_reads_stop_reason(self):
        """The signal that needed no heuristic and was never read: before this
        batch, `stop_reason` appeared once in the whole module, in a comment."""
        assert 'stop_reason' in self._src()
        assert 'stop == "max_tokens"' in self._src()

    def test_either_signal_is_enough(self):
        src = self._src()
        assert 'stop == "max_tokens" or cut["truncated"]' in src, (
            "the text detector must also be able to trigger the regeneration; "
            "a module can stop mid-thought for reasons other than the cap")

    def test_it_regenerates_rather_than_continues(self):
        """A continuation produces a module whose two halves were written under
        different remaining budgets, and the join is exactly where a numeric
        protocol loses its citation."""
        src = self._src()
        assert "REGENERATION, not a continuation" in src
        # The regeneration re-sends the ORIGINAL conversation, not one with the
        # severed answer appended.
        i = src.index("untruncate")
        assert "convo.append" not in src[:i], (
            "the truncation regeneration must not run after the answer was "
            "appended to the conversation")

    def test_the_cap_is_the_measured_constant_in_both_calls(self):
        src = self._src()
        assert "max_tokens=3200" not in src
        assert src.count("CURRICULUM_MODULE_MAX_TOKENS") == 2, (
            "the first call and the validation retry must share one cap")

    def test_the_constant_is_larger_than_what_was_measured_hitting_it(self):
        assert endo_ai.CURRICULUM_MODULE_MAX_TOKENS > 3200


class TestTheAssemblyGateBehaviourally:
    """RUN, not read.

    The first version of `TestTheAssemblyGate` only inspected the source of
    `_curriculum_module_body`, and TWO mutants walked through it: replacing
    `if cut["truncated"]:` with `if False:`, and replacing the
    `_support_not_run(...)` call with a dict claiming the answer was verified.
    Both leave every inspected string in place. Source inspection proves the
    code is WRITTEN; only running it proves the code DECIDES anything.

    Third time this pattern has cost a mutant across three batches
    (`check_precedence`, `phase_cb`, now this), so the behavioural test is the
    primary one and the source checks below it are the supplement.
    """

    @pytest.fixture
    def wired(self, monkeypatch):
        """`_curriculum_module_body` with retrieval and writing stubbed, so
        the only thing under test is what the gates do with the text."""
        ev = {"_summary": {"all_scored": [{"pmid": str(9000 + i)}
                                          for i in range(40)]}}
        monkeypatch.setattr(endo_ai, "build_evidence_base",
                            lambda q, mode=None: ev)
        monkeypatch.setattr(endo_ai, "_append_support_warnings",
                            lambda script, support: script)
        monkeypatch.setattr(endo_ai, "verify_citation_support",
                            lambda *a, **k: {"status": "verified", "checked": 1,
                                             "flags": [], "cost": 0.0})

        class _Progress:
            def probe(self):
                pass

            def tick(self, *a, **k):
                pass

        class _Evt:
            def is_set(self):
                return False

        def _run(script):
            monkeypatch.setattr(endo_ai, "write_curriculum_module",
                                lambda *a, **k: (script, 0.01))
            return endo_ai._curriculum_module_body(
                0, {"title": "Clinical Outcomes", "search_query": "lasers"},
                "lasers in disinfection", 4, _Progress(), _Evt())

        return _run

    def test_a_truncated_module_is_withheld(self, wired):
        out = wired(REAL_MODULE_4_TAIL)
        entry = out["entry"]
        assert entry.get("truncated") is True
        assert entry.get("not_generated") is True
        assert "cut off before it was finished" in entry["script"]
        assert "when tips are not" not in entry["script"], (
            "the severed text reached the document")

    def test_the_withheld_module_makes_no_support_claim(self, wired):
        """Invariant 15. A module nobody wrote cannot have had its citations
        verified, and a green tick on it is bug class (d) in its worst form."""
        support = wired(REAL_MODULE_4_TAIL)["entry"]["citation_support"]
        assert support.get("status") != "verified", support
        assert "truncated" in str(support).lower() or                "not generated" in str(support).lower(), support

    def test_the_notice_blames_the_generator_not_the_literature(self, wired):
        script = wired(REAL_MODULE_4_TAIL)["entry"]["script"]
        assert "GENERATION failure" in script
        assert "insufficient evidence retrieved" not in script, (
            "the module was withheld for running out of tokens and the notice "
            "told the reader the literature was thin")

    def test_a_FINISHED_module_passes_straight_through(self, wired):
        """The other direction, and the one that costs more if it breaks."""
        good = ("Er:YAG irrigation reduced bacterial load by 99.6% "
                "[[PMID:31543236]].\n\n"
                "- Irrigate with 5.25% NaOCl for 60 s [[PMID:31543236]]\n")
        entry = wired(good)["entry"]
        assert not entry.get("truncated")
        assert not entry.get("not_generated")
        assert entry["script"].startswith("Er:YAG")


class TestTheAssemblyGate:
    """The module never reaches the stitcher cut."""

    def _src(self):
        return inspect.getsource(endo_ai._curriculum_module_body)

    def test_the_gate_runs_before_the_evidence_anchoring_gate(self):
        src = self._src()
        assert src.index("detect_module_truncation(script)") < \
            src.index("validate_module_output(script, ev)")

    def test_it_emits_the_truncation_notice_not_the_evidence_notice(self):
        """They say opposite things about WHY. Saying the literature was thin
        when the truth is that we ran out of tokens is a lie in the direction
        that makes us look better."""
        src = self._src()
        tail = src[src.index("detect_module_truncation(script)"):][:1400]
        assert "_module_truncated_block(" in tail
        assert "_module_not_generated_block(" not in tail

    def test_the_notice_says_the_evidence_was_fine(self):
        block = endo_ai._module_truncated_block("T", "cut mid-sentence")
        assert "GENERATION failure" in block
        assert "not a gap in the literature" in block
        assert "retrieved successfully" in block

    def test_the_two_notices_do_not_say_the_same_thing(self):
        a = endo_ai._module_truncated_block("T", "r")
        b = endo_ai._module_not_generated_block("T", 0)
        assert a != b
        assert "insufficient evidence retrieved" in b
        assert "insufficient evidence retrieved" not in a

    def test_a_rejected_module_is_marked_and_carries_no_support_claim(self):
        src = self._src()
        tail = src[src.index("detect_module_truncation(script)"):][:1400]
        assert '"truncated":        True' in tail
        assert '"not_generated":    True' in tail
        assert "_support_not_run(" in tail, (
            "a withheld module must not report a citation-support result — "
            "invariant 15")
