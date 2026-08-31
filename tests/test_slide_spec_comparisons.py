"""
The generator's side of the chart hard rules (PRESENTATION_WORKLIST §1.5).

`presentations/chart_data.py` holds three gates that refuse a dishonest chart:
`consistent_unit()` (units must agree), `is_range()` (a span is not a
magnitude) and the verbatim-provenance check. Those gates are correct and are
not what this file tests.

What this file tests is the thing UPSTREAM of them. The gates can only ever
say no. Whether a deck gets a chart at all depends on whether
`generate_slides_specs()` emitted a pair of numbers worth plotting — and the
prompt used to ask for "1-2 big numbers with context" without ever saying the
two had to be the same quantity. Measured on the laser deck, the generator
duly produced:

    primary_stat "SMD -0.551"   secondary_stat "2940 nm . 75-100 mJ . <50 Hz"
    primary_stat "Superior"     secondary_stat "Day 7"

Every one of those is a true statement about the evidence. None of them is a
comparison. The gates threw all of them away and the deck rendered with zero
data charts, which read as a rendering failure when it was actually a briefing
failure.

Both fixtures here are RECORDED GENERATOR OUTPUT over real answers, not
hand-written specs:

  * `laser_old_prompt`  - the deck that was sitting in `slide_specs/` on
    2026-08-31, produced by the prompt before this change. It charts nothing.
  * `laser_old_prompt_rerun` - the old prompt run AGAIN, over the same answer
    the new fixtures use, so the prompt is the only variable. It charts two
    slides, and both are dishonest in a way the render-time gate cannot see.
  * `laser_new_prompt` / `single_visit_new_prompt` - regenerated after the
    COMPARISON RULES block was added to the prompt.

The two old fixtures are the mutation check, and it is a permanent one: they
are real output that violates the rule, so any weakening of
`comparison_violations()` that lets the new fixtures pass vacuously makes
`test_pre_fix_deck_violates_the_rule` or
`test_pre_fix_rerun_pairs_unitless_quantities` fail.

Keeping both old runs matters. Judged on chart COUNT alone the rerun looks
BETTER than the fix (2 charts vs 1), and it is worse: the count was never the
measurement. What changed is which pairs the generator offers.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from presentations.chart_data import (
    consistent_unit, detect_chartable, is_range, parse_number,
)

# NOT `fixtures/slide_specs/`: .gitignore line 59 is the unanchored pattern
# `slide_specs/`, which matches at any depth, so fixtures under that name are
# silently never committed — green here, absent on a fresh clone.
FIXTURES = Path(__file__).parent / "fixtures" / "slide_spec_comparisons"


# `laser_old_prompt_rerun` was generated from the SAME answer as
# `laser_new_prompt` — that is what makes it a controlled comparison — so it
# shares the source file rather than storing a second 38 KB copy of it.
_SHARED_SOURCE = {"laser_old_prompt_rerun": "laser_new_prompt"}


def _load(name: str) -> tuple[dict, str]:
    spec = json.loads((FIXTURES / f"{name}.spec.json").read_text(encoding="utf-8"))
    src_name = _SHARED_SOURCE.get(name, name)
    source = (FIXTURES / f"{src_name}.source.txt").read_text(encoding="utf-8")
    return spec, source


# ── the rule, stated once ────────────────────────────────────────────────────

def _stat_group(slide: dict) -> tuple[str, list[str]]:
    """The raw stat strings this slide asks to be compared, with a label."""
    pattern = str(slide.get("pattern") or "")
    if pattern == "stat_panel":
        stats = [slide.get("primary_stat"), slide.get("secondary_stat")]
        return "stat_panel", [str(s) for s in stats if s not in (None, "")]
    if pattern == "evidence_summary":
        rows = slide.get("hierarchy_rows") or []
        return "evidence_summary", [
            str(r["stat"]) for r in rows
            if isinstance(r, dict) and r.get("stat") not in (None, "")
        ]
    return pattern, []


def comparison_violations(spec: dict) -> list[str]:
    """Every place the deck asks for a comparison it cannot honestly make.

    A group of stats is legal only when it is EMPTY, or a SINGLE value, or two
    or more values that are all real numbers, none of them a range, sharing one
    unit. That is the same standard `chart_data` enforces at render time, asked
    of the generator instead of the renderer — so a clean deck is one where the
    gates had nothing to refuse, not one where they refused everything.
    """
    out: list[str] = []
    for i, slide in enumerate(spec.get("slides") or [], start=1):
        if not isinstance(slide, dict):
            continue
        pattern, stats = _stat_group(slide)
        if len(stats) < 2:
            continue                      # nothing is being compared
        where = f"slide {i} ({pattern}) {stats!r}"
        non_numeric = [s for s in stats if parse_number(s) is None]
        if non_numeric:
            out.append(f"{where}: not numbers: {non_numeric!r}")
            continue
        ranges = [s for s in stats if is_range(s)]
        if ranges:
            out.append(f"{where}: range charted as a scalar: {ranges!r}")
            continue
        unit = consistent_unit(stats)
        if unit is None:
            out.append(f"{where}: units disagree — different quantities paired")
            continue
        if not unit:
            # `consistent_unit` reports "" for anything it cannot name a unit
            # for, and "" agrees with "", so every unitless quantity in the
            # corpus compares equal to every other one. Measured on a
            # re-run of the OLD prompt over the laser answer: a network-meta
            # P-score of 0.993 (a probability rank) was paired with an SMD of
            # -0.58 and cleared the render-time gate as "same unit".
            #
            # The gate cannot close that on its own — it is asked whether two
            # numbers share a unit, and neither has one. The generator can:
            # if a value carries no unit, the spec gives no way to show the
            # two are the same quantity, so it must not be offered as a
            # comparison. This is stricter than `chart_data`, deliberately,
            # and only on the authoring side.
            out.append(f"{where}: unitless values — comparability unverifiable")
    return out


def charted_slides(spec: dict, source: str) -> list:
    """The slides that actually reach a rendered chart, gates and all."""
    return [c for c in (detect_chartable(s, source)
                        for s in (spec.get("slides") or [])) if c]


# ── the guarantee ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["laser_new_prompt", "single_visit_new_prompt"])
def test_every_comparison_is_same_quantity_same_unit(name):
    spec, _ = _load(name)
    violations = comparison_violations(spec)
    assert violations == [], (
        f"{name} pairs values that are not comparable:\n  "
        + "\n  ".join(violations)
    )


@pytest.mark.parametrize("name", ["laser_new_prompt", "single_visit_new_prompt"])
def test_deck_carries_at_least_one_verified_chart(name):
    """Not-violating is not enough: emitting no numbers at all would pass the
    rule above while leaving the deck exactly as chartless as before."""
    spec, source = _load(name)
    charts = charted_slides(spec, source)
    assert charts, f"{name} produced no chart that clears the §1.5 gates"
    for chart in charts:
        assert len(chart.values) >= 2
        assert chart.unit, "a chart with no unit cannot assert comparability"
        assert chart.pmids, "§1.5: every chart carries its PMIDs"
        if chart.axis_note is None:
            assert chart.kind != "dot", "a truncated axis needs its note"


@pytest.mark.parametrize("name", ["laser_new_prompt", "single_visit_new_prompt"])
def test_every_plotted_value_is_verbatim_in_its_source(name):
    spec, source = _load(name)
    for chart in charted_slides(spec, source):
        for literal in chart.literals:
            assert literal in source.replace("−", "-"), (
                f"{name}: plotted {literal!r} is not in the cited source text"
            )


# ── the mutation check, held permanently by real pre-fix output ──────────────

def test_pre_fix_deck_violates_the_rule():
    """The deck the OLD prompt produced, checked by the SAME function.

    Two specific pairings are named because they are the measured failure this
    change exists to stop, and a generic "some violation exists" assertion
    would survive a rewrite that only caught the easy cases.
    """
    spec, _ = _load("laser_old_prompt")
    violations = comparison_violations(spec)
    assert violations, (
        "the pre-fix fixture no longer violates the rule — either the fixture "
        "was replaced or comparison_violations() has been loosened"
    )
    blob = " ".join(violations)
    assert "-0.551" in blob or "0.551" in blob, \
        "the effect-size/heterogeneity pairing is no longer caught"
    assert "Superior" in blob, \
        "the word-as-stat pairing is no longer caught"


def test_pre_fix_deck_charts_nothing():
    """The observed symptom: gates correct, deck empty. This is the 'before'
    number in the report, pinned so a regression is visible as a number."""
    spec, source = _load("laser_old_prompt")
    assert charted_slides(spec, source) == []


def test_pre_fix_rerun_pairs_unitless_quantities():
    """The second pre-fix fixture, and the more alarming one.

    `laser_old_prompt_rerun` is the OLD prompt run again over the SAME answer
    the new fixtures use — the only variable is the prompt. It did produce two
    charts, and both are dishonest in a way the render-time gate cannot see: a
    P-score of 0.993 (a 0-1 probability rank from a network meta-analysis)
    plotted beside a standardised mean difference of -0.58. Both are unitless,
    so `consistent_unit` reports agreement and the chart renders.

    So "the old prompt drew no charts" is not the whole before-state, and a
    fix judged only on chart COUNT would have scored this run as a success.
    The thing that changed is which pairs are offered, not how many.

    UPDATE: when this fixture was recorded, the render-time gate DID pass this
    pairing, and the docstring above said the gate could not close it. That was
    true of the gate as it then stood and is no longer true: consistent_unit
    now refuses a unitless PAIR outright, on the reasoning that a bare number
    is not evidence of a shared quantity but the absence of evidence either
    way. The fixture keeps its value — it is still the run that proves chart
    count is the wrong success metric — and now also pins the gate that closed
    the hole it exposed. Both layers are asserted below, deliberately: the
    generator should not offer the pairing, and the renderer should refuse it
    if it ever does.
    """
    spec, source = _load("laser_old_prompt_rerun")
    violations = comparison_violations(spec)
    assert violations, "the P-score/SMD pairing is no longer flagged at all"
    assert any(("unitless" in v) or ("units disagree" in v) for v in violations), (
        f"the pairing is flagged, but not as a unit problem: {violations}"
    )
    assert charted_slides(spec, source) == [], (
        "the render-time gate should now refuse this pairing; if it charts "
        "again, the unitless refusal in consistent_unit has been lost"
    )
