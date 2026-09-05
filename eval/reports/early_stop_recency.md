# D1 — the early-stop recency exemption: MEASURED IN FULL, NOT SHIPPED

**Date:** 2026-09-05 · **Verdict: both pre-declared thresholds breached. Parked.**
**Replay:** `python scripts/measure_early_stop_recency.py --json eval/reports/early_stop_recency.json`
**Log:** `eval/logs/d1_full.log`

---

## The proposal

In Review mode, once cochrane + level1 supply `EARLY_STOP_MIN_PAPERS` (15), the
weaker lanes are skipped entirely. D1 keeps that but exempts recency: weaker
lanes are still fetched and papers from the last 18 months are kept, older ones
dropped as before. The reasoning is sound — a settled topic is exactly where a
new contradicting finding matters most, and an old contradicting paper has
already been absorbed or refuted.

## The result, against the thresholds declared before the run

| | measured | threshold | verdict |
|---|---|---|---|
| extra papers per question | **24.6** | ~15 | **OVER** |
| extra wall-clock per question | **48 s** | ~30 s | **OVER** |

**Both breached, so it is reported and not shipped**, exactly as the batch
specified. This is not a close call in either dimension: 1.6× the paper budget
and 1.6× the latency budget.

- 20 review-mode questions measured
- the early stop **fired on 17 of them** — this is the common case, not an edge
- weak lanes would return **687 papers** in total, **419** inside the window

## Per question

| question | strong | fired | recent | all |
|---|---|---|---|---|
| single-vs-multiple-visit | 19 | YES | 14 | 28 |
| mta-vs-biodentine-pulpotomy | 20 | YES | 24 | 39 |
| naocl-concentration | 19 | YES | 31 | 44 |
| cbct-vs-periapical | 19 | YES | 25 | 42 |
| bioceramic-vs-resin-sealer | 18 | YES | 30 | 44 |
| retreatment-vs-microsurgery | 18 | YES | 8 | 24 |
| direct-pulp-capping | 19 | YES | 14 | 43 |
| preemptive-nsaid | 20 | YES | 21 | 41 |
| regenerative-immature | 18 | YES | 27 | 44 |
| cracked-tooth-prognosis | 21 | YES | 33 | 44 |
| bisphosphonates | 6 | — | 0 | 0 |
| pregnancy | 3 | — | 0 | 0 |
| pips-vs-ultrasonic | 19 | YES | 30 | 43 |
| intentional-replantation | 18 | YES | 15 | 39 |
| sdf-pulp-outcomes | 10 | — | 0 | 0 |
| sonic-vs-ultrasonic | 19 | YES | 27 | 40 |
| dens-invaginatus | 28 | YES | 24 | 44 |
| diabetes-outcomes | 20 | YES | 30 | 43 |
| review-followup-immature-teeth | 19 | YES | 33 | 41 |
| review-newtopic-reset | 21 | YES | 33 | 44 |

The three questions where it does not fire — `bisphosphonates` (6 strong),
`pregnancy` (3), `sdf-pulp-outcomes` (10) — are the thin topics that never
reach the threshold. **The exemption does nothing for exactly the questions
with the least evidence**, which is worth knowing: it is not a fix for sparse
coverage, only for well-covered topics.

## The n=1 hypothesis was directionally right and understated both numbers

The earlier single-question probe gave **19 papers at +40 s** and was recorded
as a hypothesis under rule 27. The full set gives **24.6 papers at +48 s** —
same direction, both worse. Rule 27 earned its keep in the safe direction here:
the hypothesis would have led to the same "report, do not ship" decision, but
the honest number is 30% higher on papers and 20% on time.

## The embedding-model load, measured separately as instructed

| | |
|---|---|
| cold-process model load | **9.4 / 10.6 / 11.1 s — mean 10.4 s** |
| first embed after load | 0.037 s |

It is a **one-off per process**, not per question, and it does **not** inflate
the +48 s figure: both passes of a question run in the same process, and the
load happens in the first pass, which makes the measured delta if anything
slightly conservative.

Where it does cost: a cold live-only process — a CLI review, a cron job, this
harness — now pays ~10 s that it did not before item 2's PRISMA similarity
backfill. The long-lived server pays it once at first use and the library route
already did.

## Why 48 s is the number that should decide this, not 24.6 papers

The paper count is arguable — 24.6 more papers on a well-covered question is
not obviously bad, and they are the *recent* ones, which is the whole point.

**The latency is not arguable.** A Review answer is a chairside interaction.
Adding 48 s to the retrieval of a question that already has 18+ Level I papers,
to admit weak-tier evidence that tier banding says cannot override them, is a
poor trade on the path where the user is waiting. And it would apply to 17 of
20 Review questions.

If this comes back, the version worth measuring is **narrower**: exempt only
the `observational` lane (the one the previous handover actually flagged, and
the only lane admitting diagnostic-accuracy and morphometric designs), rather
than every weak lane. That would cost a fraction of the 48 s and admit the
papers the original concern was about. **It has not been measured and is not a
recommendation — only the next hypothesis.**

## Status

**PARKED.** No production code changed by D1. The harness
(`scripts/measure_early_stop_recency.py`) and this measurement stand, so the
next session can re-run a narrower variant against the same instrument. The
test-pins the D1 spec asks for (a recent level2 paper survives the early stop,
an old one does not) are **not written**, because nothing shipped to pin.
