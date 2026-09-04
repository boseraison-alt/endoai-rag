# A37 — how often does the clarify gate ask 2+? (item 5)

**STATUS: BLOCKED — partial.** The full measurement needs live model calls and
the Anthropic API ran out of credit at ~01:00 tonight (400
`invalid_request_error`, confirmed on Haiku). What is recorded here is the
prediction, committed before any run per A46, and the five real observations
tonight happened to produce. **Nothing has been changed.**

---

## The trigger, and why it is not enough to act on

The v7 smoke run failed one case: `case-opening-full` — *"clarify asked 2
questions, expected 0-1"*. The item's own instruction is the right one: do not
tune from a single failure. Count the distribution first.

`case-opening-full` is the fixture whose whole point is invariant 8 — the
description already states the medical history, the bisphosphonate status,
restorability and the ferrule, so **at most one** follow-up is allowed. Its
`expect` block is `clarify.count_between: [0, 1]` plus a forbidden-token list
(`bisphosphonate`, `ferrule`, `restorab`, `diabet`).

## Prediction, written before the measurement (A46)

If the gate were simply mis-tuned, every run of `case-opening-full` would ask
2+. My prediction is that it is **variable, not broken**, and specifically:

1. `case-opening-full` asks 2+ on **20–40%** of runs, not on most of them.
2. The modal count for a FULL description is **1**, not 0 — the gate is
   reluctant to ask nothing at all.
3. `case-opening-sparse` stays inside `[1, 3]` on every run, because a
   three-word history genuinely needs questions.
4. No run violates the forbidden-token list. The 2-question failure is one
   question too many, not a re-ask of something already stated — those are
   different defects and only the second would be an invariant-8 violation.
5. Therefore the fix, if one is needed, is a **count** discipline, not a
   relevance one — and a count threshold is RB's to approve.

## Observed tonight — n=5, all on real fixtures through the live path

| # | fixture | expected | asked | verdict |
|---|---|---|---|---|
| 1 | `case-opening-full` | 0–1 | **2** | FAIL (v7 smoke, previous session) |
| 2 | `case-opening-full` | 0–1 | **1** | pass |
| 3 | `case-opening-full` | 0–1 | **0** | pass |
| 4 | `case-opening-sparse` | 1–3 | **2** | pass |
| 5 | `case-opening-sparse` | 1–3 | **3** | pass |

`case-opening-full`: **1 of 3 runs asked 2+** — 33%, inside the predicted
20–40%. All three counts differ from each other on identical code and an
identical description.

The one question asked in run 2 was *"Any history of trauma to this tooth, even
minor injury the patient may not have connected to the tooth problem?"* — not in
the forbidden-token list, and a legitimate discriminator for a tooth that failed
eight years after treatment. Run 4's and 5's questions were likewise
discriminating and each carried its reason.

## What this already establishes

- **The gate is not consistently broken.** A single failing observation was
  33% of a three-run sample. Tuning from it would have been tuning noise.
- **This is the A14 class.** `pips-vs-ultrasonic` swung 40 → 112 papers between
  two runs of identical code; the clarify count swings 0 → 2 the same way. No
  single-run number on this metric is a fact.
- **The eval treats a variable quantity as a pass/fail assertion.** A
  `count_between: [0, 1]` gate on a stochastic generator fails ~33% of the time
  by design. That is a harness question as much as a generator one, and it is
  worth putting to RB alongside any threshold change.

## To finish this item (needs credit)

1. Run every case fixture **n≥5** and report the full distribution at 0, 1, 2
   and 3+, per fixture. Five runs is the minimum that can distinguish 33% from
   10%; three cannot.
2. Report the forbidden-token violation rate separately from the count rate —
   they are different defects and only one is an invariant-8 violation.
3. Instrument the gate's REFUSAL rate too (rule 32): how often it declines to
   ask anything, not only how often it asks too much. Run 3 asked zero, and
   nothing counts that.
4. Only then decide whether the fix is a prompt change, a count cap, or a
   change to how the eval asserts on a stochastic quantity. **A count cap is a
   threshold and needs RB's approval before it ships.**
