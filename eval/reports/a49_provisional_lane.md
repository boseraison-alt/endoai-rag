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

## Rule 32 — when it finds nothing

The lane logs its own arithmetic on every run, including the empty case:

```
  [provisional] 3 of 3 recent papers are unclassified by MEDLINE;
                2 state a level2-or-above design, 1 states none or a weaker one
```

Of the 29 eval questions, **9 have zero admitted papers** and three have no
untyped-recent candidates at all. That is a legitimate outcome and is reported
as one, not smoothed away.
