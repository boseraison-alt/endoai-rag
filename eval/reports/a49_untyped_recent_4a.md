# Item 4a — how big is the untyped-recent blind spot?

> # ⚠ WITHDRAWN — EVERY NUMBER BELOW THIS LINE IS WRONG
>
> **The median in this report is 426. The real figure is 26.**
>
> The script that produced it was wrong in two ways at once:
>
> 1. It called `generate_search_terms(q)`, which returns the single primary
>    PubMed query as a **string**, and then sliced it `terms[:4]` — taking the
>    first **four characters**. The queries actually issued were
>    `("(") AND "last 18 months"[dp]`, `("l") AND …`. The list of topic groups
>    comes from `generate_multi_search_terms(question, primary_term)`, a
>    different function.
> 2. It omitted `ENDO_DOMAIN_FILTER`, which production ANDs into every query.
>
> So it measured *"recent papers anywhere in PubMed matching a single
> character"*. The pool contained celery genomics, vanadium-oxide catalysis,
> *Fusarium* fungal genetics and Chinese health policy in Africa. The
> `retmax=200` cap hid it by holding every total near 600.
>
> **The corrected distribution** (production's own query shape, `retmax=500`):
>
> ```
>   min 0 | p25 3 | MEDIAN 26 | p75 48 | max 307 | total 1,454
> ```
>
> The blind spot is real but roughly **16× smaller** than this report claims,
> and the corrected median sits *under* the affordability line this report
> uses to argue against building the lane.
>
> **The conclusion is therefore also withdrawn.** Item 4b WAS built, on
> 2026-09-05, after a separate measurement of the design filter cleared its
> own pre-declared threshold (max 30 level2-or-above per query against 60).
>
> Kept rather than deleted because the error is the point: it was found by
> *reading the abstracts the extractor could not classify*, not by re-checking
> the count. Superseded by
> **`eval/reports/a49_design_extraction.md`** and
> **`eval/reports/a49_provisional_lane.md`**.

**Measure only. Nothing changed by this item.**
Replay: `python scripts/measure_untyped_recent.py --json eval/reports/a49_untyped_recent_4a.json`
(the script itself is fixed; re-running it now produces the corrected numbers,
not the ones below)

---

## The defect being sized

A paper MEDLINE has not yet indexed carries only `Journal Article`. Every
generated query ANDs a tier filter, and **no tier filter admits a bare
`Journal Article`**. So there is a rolling window — MEDLINE's indexing lag — in
which no new paper on any topic can enter the pool.

Sulaiman 42388091 is one instance of this. The question here is how many there
are, because that decides whether a separate lane is affordable.

## Method

For each of the 29 eval questions: `generate_search_terms` produces the topic
groups production would use; each group is issued to PubMed ANDed with
`"last 18 months"[dp]` and **no tier filter**, which is exactly what an untyped
lane would issue; publication types are fetched for everything returned; and
the count is of papers whose **only** publication type is `Journal Article`.

**The threshold was declared before the run**, so the verdict could not be
rationalised afterwards: *median above ~40 per query means the lane needs a
relevance gate to be affordable.*

## Distribution — per query, not the mean

```
  n questions      29
  min              243
  p25              377
  MEDIAN           426
  p75              471
  max              621
  mean             424.1
  total distinct   12,299
```

```
  bucket     questions
  0          
  1-5        
  6-20       
  21-40      
  41-100     
  >100       #############################  29
```

Full sorted distribution:

```
243 308 308 311 316 316 318 377 380 386 403 411 416 424 426 442
459 467 468 468 471 471 476 478 489 520 546 580 621
```

**Every one of the 29 questions is above 100.** The shape is not a long tail
with a small median — it is uniformly large. There is no question for which an
ungated lane would be cheap.

## What the instrument does and does not bound

**These counts are a FLOOR, not an estimate.** Each topic group was fetched at
`retmax=200`, and most questions returned 3–4 groups, so the ceiling any
question could report is roughly 600–800. Fourteen of the 29 sit at 400+ with
their `recent` totals pinned near that ceiling, which means the query had more
to give and the fetch stopped first. The true population is larger than the
number in the table.

That only strengthens the verdict, so it is not worth more API calls to refine:
the question was "is this above or below 40", and the answer is not close.

A second limit, stated rather than corrected: `generate_search_terms` capped
several questions to 3 AND-groups and logged what it dropped (visible in the
run log for questions 5, 10, 11, 12, 15, 16, 19, 25). Those questions were
measured on a narrower topic set than production's full breadth, which again
biases the counts **down**.

## Verdict

**Median 426 against a declared threshold of 40 — 10.7× over.**

An untyped-recent lane cannot be built as a plain additional query. Admitting
even the top 50 per topic group, as every other lane does, means fetching and
scoring roughly 150–200 abstracts per question that carry no design
information at all, on every question, forever.

**The lane needs a relevance gate before it is built, and the gate needs its
own measurement.** Reporting that is what this item asked for, rather than
shipping something unaffordable.

## What the gate has to do — for whoever builds 4b

The constraint that makes this hard: the lane exists precisely because these
papers carry no study-design signal, so the gate cannot use one. What is
available is:

- **cosine similarity to the question**, which the library path already
  computes and which is the only relevance signal that does not require
  reading the paper;
- **the 18-month window**, already applied and already counted above — it is
  not a gate, it is the definition of the set;
- **a hard per-query cap**, which bounds cost but selects arbitrarily unless it
  is applied *after* a relevance sort.

The design 4b should measure first is a similarity floor applied to the untyped
lane alone, with the cap applied after it — and the number to measure is what
floor admits Sulaiman 42388091 for a VPT question while holding the per-query
admission to a affordable count. Sulaiman is the one worked example where the
right answer is known, so it is the calibration point.

**Do not reuse `evidence_floor` (0.60) for this.** That floor is on the
do-not-change list, it was tuned on tiered papers, and Komora — a network
meta-analysis on the exact topic — sits below it at 0.5807. A floor that
already loses a level-1 paper on topic is not the floor to select untyped
papers with.

## Not built, and why

Item 4b was not started. With the median 10.7× over the declared affordability
threshold, the honest options were to build the lane ungated (which 4a
explicitly forbids) or to design the gate and measure it, which is a larger
piece of work than the remaining time in this batch could do properly.

The alternative rejected: shipping the lane with an arbitrary cap and no
measured gate. That would have made Sulaiman's xfail flip and looked like
progress, while adding 150+ unscored abstracts per question and hiding the
real question — what relevance signal is legitimate for a paper with no design
information — behind a number nobody measured.

**Sulaiman's xfail therefore stays failing, and stays accurate.**
