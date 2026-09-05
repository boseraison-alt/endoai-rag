# Item 1 — the prompt's enumerations are derived, and the observational A/B

**Date:** 2026-09-06
**Replay:** `python scripts/ab_lane_headings.py --json eval/reports/a49_lane_headings_ab.json`

---

## 1a — one table, two enumerations

Four hand-written copies of the lane set had drifted behind it:

| copy | how far behind |
|---|---|
| `app.py`'s tier list | three lanes — observational, guideline, provisional never reached Review or Case |
| `eval/run_eval.py`'s `TIER_ORDER` loop | blind to provisional, in every baseline the harness ever produced |
| the synthesis prompt's tier-order line | omitted guideline, observational, invitro, classic, provisional |
| the synthesis prompt's heading list | the same five |

The prompt copies cost the most and were found last. Both are now rendered
from **one table**, `LANE_PROMPT_NOTE`, holding a one-line note per lane —
**and no labels**, which come from `TIER_LABEL` / `PROVISIONAL_LABEL`. A second
copy of the labels would be the thing the table exists to remove, and a test
pins that.

### The source is `TIER_ORDER + PROVISIONAL_KEY`, not `tier_query_lanes()`

The batch specified `tier_query_lanes()` plus the guideline and provisional
lanes. **Following that literally would have reintroduced the bug one layer
along.** `tier_query_lanes()` is the **fetch** set: eight lanes that get a
PubMed query. `TIER_ORDER` is the **render** set, and it also carries:

- `cochrane` — fetched by its own function, not a lane
- `classic`, `level3` (legacy), `invitro` — **no lane queries them**, but
  library rows are banded into them and they do reach the prompt

A heading list built from the fetch set would omit exactly the lanes that only
ever arrive from the library.

### The derived order line is more accurate than the one it replaced

The hand-written line omitted `classic` and the legacy `level3` band, both of
which sit in `TIER_ORDER` and **are** ranked by `build_synthesis_order`. The
prompt was telling the model a hierarchy the engine does not use.

Non-rungs — `guideline`, `observational`, `invitro` — get headings and their
own notes and are deliberately **not** ranked. Putting a guideline into a
hierarchy the prompt then tells the model to obey is the score-as-membership
category error in a different costume.

## 1b — the parity test

`tests/test_prompt_lane_parity.py` asserts the rendered heading set **equals**
the lane set: no lane without a heading, no heading without a lane. It captures
the **real** system prompt from the production call site rather than calling
the renderer, because a test of the renderer is what let all four copies drift
(rule 14).

Mutation-checked: **M1** drop observational from the render — KILLED;
**M2** revert to a hand-written list — KILLED; **M3** paraphrase the
A/B-winning guideline wording — KILLED.

---

## 1c — the observational A/B

### The first run was inconclusive, and the reason is the finding

The batch pre-declared *"observational citations rise to ≥1 on 3 of the 5 live
cases where the tier is populated"*, using the five live Review cases from
yesterday's guideline A/B. **On that set the tier was populated on ONE case.**
The bar was 3 of 1 — arithmetically unmeetable.

The "18 of 29 questions" figure that motivated the item is across **all 29**,
most of them library-routed. It does not describe that five-case subset.
Reporting "FAIL — revert" would have been reporting a premise error as a
result.

### Re-run on the population that has the tier

Five live-pinned cases whose observational tier is populated in **all three**
v7 runs, read from `baseline_v7.json` rather than guessed at. Same bar.
`laser-root-canal-disinfection-live` has the deepest tier (10 papers) and is
deliberately excluded: it is learn-mode, and this harness synthesises through
`ask_clinical_question`, so including it would measure a Review prompt on a
curriculum question.

| case | obs. retrieved | obs. control | obs. treated | guideline ctrl → treat |
|---|---|---|---|---|
| apdt-primary-molars | 10 | 0 | 0 | 2 → 2 |
| case-opening-sparse | 6 | 0 | **1** | 2 → 3 |
| case-opening-full | 3 | 0 | 0 | 4 → 4 |
| intentional-replantation | 6 | 2 | **2** | 2 → 2 |
| sdf-pulp-outcomes | 4 | 0 | **2** | 4 → 4 |

| | control | treated |
|---|---|---|
| observational citations | 2 | **5** |
| guideline citations | 14 | **15** |
| total citations | 73 | **87** |
| cost | $9.78 | $9.57 |
| mean citations | 14.6 | 17.4 |

**Pre-declared: ≥1 on 3 of 5 populated. Result: 3 of 5. PASS.**
**Guideline regression check: 14 → 15, no regression.**

Total citations rose 19% and cost did not — the answers cite more of what was
already retrieved and paid for.

Two cases still cite no observational paper despite a populated tier
(`apdt-primary-molars` with 10, `case-opening-full` with 3). The heading makes
the lane *available* to the model; it does not make every lane relevant to
every question, and a descriptive study genuinely may not bear on a treatment
comparison. That is the correct behaviour, not a shortfall — but it is the
reason the bar was 3 of 5 and not 5 of 5.
