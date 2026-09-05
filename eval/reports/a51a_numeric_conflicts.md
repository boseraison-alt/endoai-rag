# A51(a) — internal numeric conflicts: the count, and the gate that surfaces them

Replay:
`python scripts/measure_numeric_conflicts.py --json eval/reports/a51a_numeric_conflicts.json`
`python scripts/measure_conflict_gate.py --json eval/reports/a51a_conflict_gate.json`

---

## CORRECTION — the count was 25 of 36 and is actually 33 of 36

The first pass of this report said 25 of 36 stored curricula (69%) carry a
same-quantity/two-values conflict. **That was an undercount, and the cause was
the instrument, not the corpus.**

`modules_of` split on **every** `## ` heading and kept the sections beginning
`## Module`. Curricula put `## Clinical Application` — an h2 — *inside* every
module, so each module body was truncated at its first subheading:

```
  query_cache:4471   old splitter  767  837  633  618   words per module
                     new splitter 2128 2699 2438 2175
```

The protocol sections, where the irrigant concentrations actually live, were
never scanned. Where a curriculum happens to have no h2 subheadings the two
splitters agree exactly (`query_cache:2346`: 1389/1475/1386/771 under both),
which is what made the undercount invisible.

**Corrected: 33 of 36 (92%).** Three curricula are clean.

This is the same failure as `scan_split_items.py` looking for a bare `N.`
where the corpus writes `**3.**` — a detector pointed slightly to one side of
the data. Ninth instrument error recorded in this project.

## The gate

`detect_parameter_conflicts` has always found these. It was called by
`scripts/regenerate_curriculum.py` as a metric and by
`annotate_curriculum_consistency` at generation time — which makes a model call
and fails closed — and by nothing on the path that serves a document to a
reader. The detector was never missing. The wiring was.

`render_numeric_conflict_notice` now runs inside `finalise_answer_text`,
deterministic and model-free, after the quarantine pass. Because that function
serves stored answers as well as fresh ones, the notice appears on the 33
already-stored curricula without rewriting a single row.

**Surfacing, not blocking.** Both values are shown, neither is suppressed, and
no winner is picked — choosing one would be inventing a clinical judgement out
of a string comparison. The note says what is actually missing: the sentence
saying which study used which.

## Measured on the serve path

| | n |
|---|---|
| curricula with ≥2 modules | 36 |
| **notice rendered** | **33** |
| **silent** | **3** |
| idempotent on re-render | yes |

**The false-positive check, which matters more than the 33.** A notice on a
clean document teaches the reader to ignore notices, and then it protects
nobody on the documents that need one.

```
  learn_history/20260430_190228_perforation_in_molars…   conflicts=0   silent
  learn_history/20260902_200429_apicoectomy_of_mandib…   conflicts=0   silent
  eval/fixtures/curricula/anesthesia_after.txt           conflicts=0   silent

  -> no silent document has a conflict
  -> no rendered notice lacks a detected conflict
```

Both directions are clean, and both are pinned as invariants rather than as
literal counts, because the corpus grows.

## What the 33 disagree about

Overwhelmingly irrigant concentration. The worst single document carries six
distinct NaOCl values:

```
  …_root_canal_disinfection.json   naocl   0.5, 1.0, 2.5, 2.6, 5.25, 6.0
  query_cache:4471                 naocl   2.5, 5.0, 5.25
  query_cache:2346                 lidocaine 1.8 vs 2.0 · mepivacaine 2.0 vs 3.0
```

## Time quantities — measured, not built

The haemostasis threshold is a **time**, attached to a clinical event rather
than to an agent, and `extract_numeric_parameters` is concentrations-only by
design. A narrow probe sized the gap.

**A second correction.** The first pass reported that the probe found only two
of the three haemostasis values the batch describes. With the corrected
splitter it finds **all three**:

```
  query_cache:4471  (the 2026-09-04 18:13 VPT curriculum)
      10 min   Module 1
       6 min   Module 3, Module 4
       4 min   Module 3, Module 4
```

The missing 10-minute value was the truncated module body, not the probe. Note
also that Modules 3 and 4 each carry **both** 4 and 6 minutes — the document
disagrees with itself *inside a single module*, which a cross-module rule
cannot see.

### What a time extension actually needs

1. **A quantity vocabulary keyed to the clinical EVENT, not the agent.**
   Haemostasis time, working length, obturation temperature, irrigant contact
   time — each with its own unit family and plausibility ceiling, the way
   `_PARAM_MAX_PCT` bounds concentrations.
2. **A representation for "no threshold established".** Module 2 of the same
   curriculum states that no threshold is established. That is a claim about
   the *absence* of a quantity, and it conflicts with Module 1's "up to 10
   minutes" more sharply than 4 conflicts with 6. A number-matching probe
   cannot represent it, and this remains the reason the extension is not
   built here.
3. **Within-document scope.** `detect_parameter_conflicts` requires
   `len(mods) >= 2` deliberately, and that is *right* for concentrations — one
   passage contrasting 2% and 5.25% NaOCl is usually deliberate. It is *wrong*
   for a protocol threshold, where one module giving two numbers is the defect.
   Modules 3 and 4 of `query_cache:4471` are the worked example.

**Not built, and the alternative rejected:** promoting the probe to a gate. It
would now find 3 of 3 values and look complete, while still being unable to
represent Module 2's "no threshold established" — the sharpest conflict in the
document. A gate that reports the two easy disagreements and silently drops the
hard one is worse than no gate, because it looks thorough.
