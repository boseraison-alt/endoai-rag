# A42 — the evidence floor: free, and it IS the cost fix after all

Three measurements, and two of them corrected the one before.

---

## A42a — the similarity of papers that were actually cited

From A38d's ten runs, no new experiment, as instructed. 181 cited
paper-instances, scored on **the similarity the floor actually sees**.

```
lowest cited 0.587   p05 0.628   p10 0.637   median 0.713   max 0.841

floor   pool cut   cited cut        per question, cited below 0.60
0.55          0%    0  (0.0%)       mta-vs-biodentine     0 of 29
0.58          9%    0  (0.0%)       regenerative          0 of 45
0.60         18%    2  (1.1%)  <--  single-vs-multiple    0 of 38
0.62         33%    8  (4.4%)       cbct-vs-periapical    1 of 38
0.65         51%   29 (16.0%)       direct-pulp-capping   1 of 31
```

**RB's test is met: 18% of the pool is carried into every prompt and cited 1.1%
of the time.** That is cost, not evidence.

### Correction 1 — the first pass used the wrong quantity

It scored cited papers with question-only similarity and reported a lowest cited
value of **0.4633** — below a floor that demonstrably works, which is how the
error announced itself. `multi_query_search` keeps the **maximum** similarity
across the question *and* every generated term (the A4 fix: a compliant boolean
embeds further from prose than a sloppy one, so Cochrane CD005296 sat at 0.546
for the query that cut it and 0.680 for the raw question). That maximum is what
the floor sees.

Question-only similarity would have reported **17** cited papers lost at 0.60
instead of **2** — a worse trade than the real one, on the wrong number.

---

## Correction 2 — "the floor is free" was generalised from a deep-pool sample

The A42a table above is measured on the five A38d questions, and those turn out
to be the ones where the library is **deep**. Across all 29 eval questions the
same floor is wildly uneven:

| question | at 0.55 | at 0.60 |
|---|---|---|
| case-opening-sparse | 103 | **6** |
| dens-evaginatus-premolar-diagnostic | 56 | **6** |
| pregnancy | 100 | **12** |
| dens-invaginatus | 135 | 27 |
| sonic-vs-ultrasonic | 115 | 28 |
| direct-pulp-capping | 110 | 110 |
| case-opening-full | 144 | 144 |

Three questions end below 20 papers and two at six. **A pool of six manufactures
the false evidence gap A5 was about.**

So the floor gained a floor: below `min_evidence_papers` it does not cut at all
and the most similar N are kept instead.

| min keep | total pool | vs 0.55 | smallest | under 20 | context saved |
|---|---|---|---|---|---|
| none | 2,076 | 63% | 6 | 3 | 37% |
| **40** | **2,204** | **67%** | **40** | **0** | **33%** |

The guard costs four points of context saving and **cannot cost a citation**,
because it only ever adds papers back. It binds on six of 29 questions — exactly
the thin-library ones. 40 rather than A33j's arithmetic floor of ~24, because
that bound assumed the best citation rate ever observed (82%) and it has not been
seen twice.

---

## A42b — the paired re-measurement. The success bar is met.

Same design as A38d: the same question answered twice against a pool built in the
same process, one variable — the floor.

| question | 0.55 pool | 0.60 pool | 0.55 cited | 0.60 cited | Δcited | 0.55 $ | 0.60 $ | Δ$ |
|---|---|---|---|---|---|---|---|---|
| mta-vs-biodentine-pulpotomy | 124 | 91 | 15 | 11 | −4 | 3.98 | 1.55 | −2.43 |
| regenerative-immature | 126 | 119 | 24 | 25 | +1 | 1.94 | 1.95 | +0.01 |
| single-vs-multiple-visit | 91 | 63 | 16 | 19 | +3 | 1.70 | 1.48 | −0.22 |
| cbct-vs-periapical | 121 | 60 | 22 | 21 | −1 | 1.96 | 1.27 | −0.70 |
| direct-pulp-capping | 116 | 89 | 13 | 19 | +6 | 3.74 | 1.69 | −2.06 |
| **mean** | | | **18.0** | **19.0** | **+1.0** | **2.67** | **1.59** | **−1.08** |

**Cost fell 40%. Citations held — 18.0 → 19.0.** A42b's bar was "cost falling
toward $1 with cited near 18". It is met.

### Correction 3 — my own "this is not the cost fix" was wrong

The previous commit estimated the saving at **$0.15** by pricing context tokens
alone at Opus input rates, and concluded the floor was free but nearly worthless
as a cost lever. Measured, it is **$1.08**, seven times that. Estimating where
the instruction was to measure is the error, and it is standing rule 1.

The estimate missed everything downstream of the pool: fewer papers means fewer
claim-citation pairs for the support checker, and fewer retries. The two largest
savings are on the two runs that cost $3.98 and $3.74 at 0.55, which look
retry-inflated.

**How much is really the floor.** Dropping those two: $1.87 → $1.57, a saving of
$0.30. So somewhere between $0.30 and $1.08 of the $1.08 is the floor and the
rest is retry variance. n = 5, one run per condition; the pairing cancels
question difficulty but not synthesis stochasticity. The direction is consistent
(four of five cheaper) and the citation count held, which are the two things the
bar actually asked about.

**Scope note.** These runs predate the `min_evidence_papers` guard. The smallest
0.60 pool here was 60, so the guard would not have bound on any of them and the
result stands for the shipped code on these five questions. It has not been
measured on the thin-pool questions the guard exists for.

---

## What shipped

```python
"similarity_floor":     0.55,   # ROUTING — unchanged, still paired with min_relevant
"evidence_floor":       0.60,   # what the MODEL reads
"min_evidence_papers":  40,     # the floor removes surplus, never substance
```

Two constants, not one raised, because `similarity_floor` also gates routing and
app.py's own note says it and `min_relevant` move as a pair. Raising it to 0.60
would push 2 of 29 eval questions onto the **live** route, which costs more.

`apply_evidence_floor()` is a function rather than four lines inline because two
mutations survived while the tests inspected source text instead of driving the
expression (rule 14). Twenty-one tests, ten mutations, all caught.

---

## For the re-baseline (rule 13)

Every retrieval eval case will report fewer papers. That is this change, not
drift, and the six questions where the guard binds will report exactly 40. Both
belong in the re-baseline's explanation rather than being absorbed silently.

Probe spend: $21.27 (A42b) on top of A38d's $22.60.
