# D1 — the early-stop recency exemption: PARKED, harness built, n=1 only

**Date:** 2026-09-05 · **Status: NOT IMPLEMENTED. Measurement incomplete.**
**Replay:** `python scripts/measure_early_stop_recency.py --json eval/reports/early_stop_recency.json`

## The decision this was to implement

> **D1** The early stop stays, with a RECENCY EXEMPTION. When cochrane +
> level1 reach the early-stop threshold, weaker tiers are still fetched for
> papers published in the last 18 months only. […] Measure first. Pre-declared:
> if it adds more than ~15 papers per question on average, report before
> shipping.

## Why it is parked

**The measurement did not finish inside the batch, and D1 says measure first.**
It is a live-path behaviour — the early stop decides which lanes are fetched
from PubMed — so there is no library-side proxy, and each question costs two
full live retrievals (production, then the same question with the stop
disabled). Measured rate: **~8–15 minutes per question** against 20 review-mode
questions. It did not fit in the remaining window.

**Alternative rejected:** implementing the exemption on the n=1 result below.
That would put an unmeasured retrieval change into the freeze this batch exists
to produce, and the n=1 number is *over* the pre-declared threshold, so the
honest reading of it is "report before shipping", not "ship".

## What n=1 says — a HYPOTHESIS, not a finding (rule 27)

`single-vs-multiple-visit`, review mode, live route:

```
early stop FIRED (strong=19). Weak lanes would return 44; 19 within 18mo. +40s
level2 8/14, level3a 3/10, level3b 2/6, level4 2/4, level5 0/4, observational 4/6
```

**19 recent papers, against a pre-declared threshold of ~15.** One question.
Rule 27 exists precisely for this shape — A42a's "the floor is free" came from
a convenient subset and was wrong on the full set. Treat 19 as a reason to
finish the measurement, not as the answer.

Two things it does establish, both useful:

- **The early stop does fire on a real eval question**, so this is not a guard
  measuring nothing (rule 34).
- **`observational` contributes 4 of its 6 papers inside the window.** That is
  the lane the previous handover flagged as the one the early stop should
  arguably not skip, and the recency exemption would reach most of it.

## Cost, measured

**+40 s per question** where the stop fires. On a Review answer that is
material — it is roughly a third of the answer's wall-clock — and it is the
number the ship/park decision should weigh alongside the paper count. This is
not visible in the paper counts at all and would have been missed by a
measurement that only counted papers.

## An item 2 cost that surfaced here

The run pays a **sentence-transformer model load** on a pure-live process,
because item 2's PRISMA similarity backfill calls `rag.embed` and the live path
otherwise never touches the embedding model. In the server this is once per
process and already paid by the library route; in a **cold, live-only process**
(this harness, a CLI review, a cron job) it is a new one-off cost. Not a
defect, but it is new and it belongs on the record.

## What the next session needs

1. Run the harness to completion — budget **~3 h**, or run it against the
   `--limit`ed subset in stages and record how many questions each stage
   covered.
2. If the mean lands **over ~15**, the ORDER says report before shipping. The
   n=1 point suggests it will.
3. If it ships, the test-pins D1 asks for are still owed: **a recent level2
   paper survives the early stop and an old one does not.**
