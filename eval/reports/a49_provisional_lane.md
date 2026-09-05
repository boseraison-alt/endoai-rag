# Item 4b — the untyped-recent (provisional) lane

Replay:
`python scripts/measure_provisional_lane.py --mode review`
`python scripts/measure_provisional_lane.py --mode learn`

---

## What it closes

A paper MEDLINE has not yet indexed carries only `Journal Article`. Every tier
lane ANDs a publication-type filter, and none of them admits a bare
`Journal Article`. So there was a rolling window — the width of MEDLINE's
indexing lag — in which **no new paper on any topic could enter the pool**,
however good the topic terms were.

Sulaiman 42388091 carries *haemostasis time, partial pulpotomy, outcome,
cariously exposed, mature permanent* — five of a VPT question's own terms — in
its title, and was structurally unreachable.

## The shape of the fix

| constraint | how it is enforced |
|---|---|
| **separate lane** | `PROVISIONAL_KEY` is not in `TIER_ORDER`. That is this codebase's mechanism for "never competes for a tier slot". |
| **no tier** | assigning a rung would assert a classification the indexer has not made |
| **no score** | `score=None`, and provisional papers are kept out of `all_scored` — the score-bearing list every average and "top paper" reads |
| **the design is the gate** | admitted only if the abstract states a level2-or-above design *in the authors' words*. Removes 87.6% of the pool. |
| **no similarity floor** | `evidence_floor` 0.60 already loses Komora, a Level I paper on the exact topic, at 0.5807 |
| **18 months** | verified against PubMed's own query translation, not assumed |
| **rendered honestly** | year, "NOT YET CLASSIFIED BY MEDLINE — no publication type has been assigned, so this paper has no evidence tier", and the stated design *with the phrase it was read from* |

The context block also tells Claude what it may not do with them: not rank them
against tiered evidence, not call them Level I/II, not let one override a
systematic review, and where they disagree with tiered evidence to report both
and say which is which.

## Literature — A/B on the same code

The lane is stubbed off in one arm, so the arms differ in exactly one thing.

| | lane OFF | lane ON | delta |
|---|---|---|---|
| tiered pool | 38 | 29 | −9 |
| **provisional pool** | **0** | **2** | **+2** |
| citation markers | 22 | 22 | +0 |
| distinct cited | 15 | 14 | −1 |
| elapsed s | 144.5 | 141.2 | −3.3 |
| cost USD | 0.8025 | 0.7673 | −0.0352 |

**Both provisional papers were cited** — 40708757 (2025) and 41852998 (2026),
both randomised trials, both previously unreachable.

**Caveat, stated rather than buried.** `tiered_pool` differed 38 vs 29 between
arms. The lane issues a separate query and cannot affect tiered retrieval;
that is run-to-run variance in PubMed relevance, the auto-broaden step and the
stochastic term generator. It means the arms are not perfectly matched and the
cost and latency deltas are within noise — which is itself the finding: **the
lane costs nothing measurable.** One extra esearch and a batched efetch, ~5s.

## What it admits, live

On a VPT haemostasis query, 200 recent candidates → 66 unclassified by MEDLINE
→ **20 admitted**, every one 2025 or 2026, including Sulaiman:

```
  42388091  2026  clinical trial (non-randomised) or prospective study
  42530796  2026  randomised controlled trial
  42370524  2026  randomised controlled trial
  40397221  2025  randomised controlled trial
  42245173  2026  meta-analysis
  ...
```

Note what Sulaiman's design actually **is**. The batch called it an RCT. It is
not one: the abstract says *"this single centre, one-arm clinical trial"*, and
the strings `randomis`, `randomiz`, `randomly` do not appear anywhere in it.
It is admitted at level2, truthfully.

## What it correctly declines

- **Komora 39117767** — MEDLINE has classified it (`Systematic Review`,
  `Network Meta-Analysis`), so the tier lanes own it.
- **EFCD-ESE-ORCA 42018467** — classified `Practice Guideline`; the guideline
  lane owns it.
- untyped papers stating no design, a weaker design, or bench work — including
  bench work that randomises its specimens.

The lane takes only what nothing else can reach. That is the whole point of it
being separate.

## ONE LANE, FIVE PLACES — the finding worth carrying forward

Building the lane was the easy half. Wiring it took five separate fixes, and
each was found by following the previous one rather than by a test:

| site | what it does | how it was found |
|---|---|---|
| `endo_ai.build_evidence_base` | curriculum retrieval | built it here |
| `app.build_evidence_base_with_progress` | **Review and Case** retrieval | asked which call sites reach `fetch_untyped_recent` |
| `app.build_differential_evidence` | case-differential merge | followed the same question |
| `endo_ai.merge_evidence_bases` | curriculum combine | the A/B reported `provisional_pool = 0` in **both** arms |
| `endo_ai.stitch_curriculum` | reference list | followed the fourth |

`PROVISIONAL_KEY`'s absence from `TIER_ORDER` is the property that makes the
lane safe — it can never take a tier slot or be read as a rung. It is also
exactly what makes it invisible to every `for tier in TIER_ORDER` loop in the
codebase, and there are five that matter. **The safety property and the failure
mode are the same fact.**

`grep -n "in TIER_ORDER" app.py endo_ai.py` is the checklist. Any future lane
that sits *beside* the ladder rather than on it inherits this.

### And the one with history

`app.py` carried its **own hardcoded copy** of the lane list, three lanes
behind `tier_query_lanes()`:

- **`observational`** (A31) — added so cross-sectional, morphometric, imaging
  and diagnostic-accuracy designs would be reachable at all. Never reached a
  Review or Case answer.
- **`guideline`** (A49 item 5, the previous night) — the entire point was that
  a clinical practice guideline had no query that could reach it. On this path
  it still had none. **I reported that item as landed; it was landed on one of
  two paths.**
- **`provisional`** (this item).

Every existing test passed and each was correct about what it asserted:
`test_observational_tier` and `test_guideline_lane` check
`tier_query_lanes()`; `test_provisional_lane` drives
`endo_ai.build_evidence_base`. The helper was right and one of its two callers
did not call it.

### A second layer, found by measuring the fix

With the lists merged, the guideline lane *still* did not run on Review,
because the early stop skips every non-`level1` tier once `cochrane+level1`
supply 15 papers — and it fired at 59 on the measured question. That reasoning
("tier banding means a case series cannot override a Level I finding") does not
cover a guideline, which is a specialty's stated **position**, a different axis.
It now runs regardless, as the provisional lane already did by construction.

Measured on `app.build_evidence_base_with_progress` itself, `force_route=live`:

| | before | after |
|---|---|---|
| lanes issued | 3 | 4 (+guideline) |
| provisional pool | 0 | 5 |
| elapsed s | 48.7 | 48.2 |

## Rule 32 — when it finds nothing

The lane logs its own arithmetic on every run, including the empty case:

```
  [provisional] 3 of 3 recent papers are unclassified by MEDLINE;
                2 state a level2-or-above design, 1 states none or a weaker one
```

Of the 29 eval questions, **9 have zero admitted papers** and three have no
untyped-recent candidates at all. That is a legitimate outcome and is reported
as one, not smoothed away.
