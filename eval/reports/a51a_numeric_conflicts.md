# Item 6 / A51(a) — internal numeric conflicts in stored curricula

**Measure only. Nothing changed.**
Replay: `python scripts/measure_numeric_conflicts.py --json eval/reports/a51a_numeric_conflicts.json`

---

## The count, which is the severity

36 stored curricula parsed (query_cache `[learn]` rows, `learn_history/*.json`,
and the committed curriculum fixtures).

| | n | of 36 |
|---|---|---|
| carrying a **concentration** conflict — what the existing detector finds | **25** | 69% |
| carrying a **haemostasis-time** conflict — what it **cannot** see | **4** | 11% |

**Two thirds of every curriculum ever generated carries a same-quantity,
two-values, one-document conflict that the existing chart-gate logic already
detects.** It detects them and nothing acts on the result: `detect_parameter_conflicts`
is called by `scripts/regenerate_curriculum.py` as a metric, not by any
answer path as a gate. That is the finding — the detector is not missing, the
wiring is.

## The more important half: what the detector structurally cannot see

`detect_parameter_conflicts` is built on `extract_numeric_parameters`, whose
docstring is explicit: *"Concentrations only — not doses, not volumes, not
success rates."* It matches an agent, a value and a unit like `%`.

The haemostasis threshold is a **time**, in minutes, attached to a clinical
event rather than to an agent. It is invisible to that extractor by
construction. So the conflict the batch names — Module 1 against Modules 3 and
4 against the Final Verdict — was never going to appear in the 25.

A deliberately narrow probe was written to size that gap, **as a probe and not
as a proposed gate**, and it finds a 4-minute against 6-minute disagreement in
4 documents, including both VPT curricula the comparison was run on:

```
  query_cache:4471                      (the 2026-09-04 18:13 VPT curriculum)
      4.0 min   Module 3 — Vital Pulp Therapy Technique
      6.0 min   Module 3 — Vital Pulp Therapy Technique; Module 4 — Outcomes

  query_cache:4126                      (VPT, mature permanent teeth)
      4.0 min   Module 4 — Clinical Outcomes, Healing
      6.0 min   Module 1 — Pathobiology; Module 3 — Techniques
```

Note 4471 disagrees with **itself inside one module**, which is worse than a
cross-module conflict and which a module-pair rule would miss.

## Where the probe falls short, stated rather than papered over

The batch describes **three** haemostasis values in the 18:13 curriculum —
"up to 10 minutes", "6 minutes", and "no threshold established". The probe
found two of them (4 and 6). It did not find the 10-minute statement, and it
cannot represent "no threshold established" at all, because that is a claim
about the absence of a number and the probe only matches numbers.

This is exactly why the probe is not being promoted to a gate in this batch.
A detector that finds two of three values would report "conflict: 4 vs 6" and
be believed, while the clinically loudest pair — a stated threshold against an
explicit statement that no threshold exists — went unmentioned. That is the
instrument-error shape this project has now hit seven times, and shipping it
under time pressure is how it would happen an eighth.

## What extending the gate actually requires

Not a wider regex. Three things the concentration path did not need:

1. **A quantity vocabulary keyed to the clinical event, not the agent.**
   Haemostasis time, working length, obturation temperature, irrigant contact
   time. Each needs its own unit family and its own plausibility ceiling, the
   way `_PARAM_MAX_PCT` bounds concentrations.
2. **A representation for "no threshold established".** A negative claim about
   a quantity has to be comparable with a positive one, or the most important
   conflict class stays invisible.
3. **Within-document as well as cross-module scope.** The current rule requires
   `len(mods) >= 2` deliberately — one module contrasting 2% and 5.25% NaOCl is
   usually a clear passage, not a defect. That reasoning does not transfer to a
   protocol threshold, where one module giving two numbers IS the defect, and
   4471 is the worked example.

## Not built, and the alternative rejected

The extension was not built. The alternative rejected was shipping the probe
above as the gate: it would have flagged 4 documents, produced a number, and
looked like the item was done, while silently missing the 10-minute value and
the no-threshold statement in the very curriculum the batch cites.

**The 25 is actionable today and needs no new detection at all** — the existing
detector already finds those conflicts on two thirds of the corpus and nothing
consumes its output. Wiring `detect_parameter_conflicts` into the answer path
is a smaller, better-understood piece of work than extending it, and it is
where the next session should start.
