# A35k — what the per-tier quota is actually cutting

**Measured 2026-09-03, before choosing any numbers, as A35k requires.**
29 eval questions, library route, similarity floor 0.55, current per-tier cap 25.
Candidate sets collected once and every scheme scored against the same papers, so
the only variable between rows is the membership rule (rule 22).

**Headline: A35's premise is not supported, for the third time, and this time the
measurement points the other way. The pool is not too small — it is already 114
papers per answer. The quota's real defect is an ordering inversion, and removing
the quota fixes the inversion by handing 675 of 689 freed slots to level1: the
tier that already dominates the pool and is cited at the lowest rate of any tier.**

---

## 1. The pool the current scheme already produces

| | papers |
|---|---|
| min | 56 |
| p25 | 100 |
| **median** | **118** |
| p75 | 128 |
| max | 171 |
| mean | 113.8 |

RB's constraint was "a library answer already went ~38 → ~120 papers once; do not
double it again without the number visible first." **It is already at ~114.** The
~38 figure predates the A5b/A30 membership fixes. Any question about making the
quota larger has to start from 114, not from 38.

Context cost of that pool, measured from the real `_scored_to_text` renderer:
**55,750 input tokens, $0.836 per answer** at Opus input pricing.

## 2. Above the floor, below the cut — per tier, pooled over 29 questions

| tier | available | admitted | **cut** | quota-bound on | worst admitted | best cut |
|---|---|---|---|---|---|---|
| cochrane | 56 | 56 | 0 | 0 | 0.596 | — |
| **level1** | **2153** | **724** | **1429** | **28 of 29** | **0.624** | **0.625** |
| classic | 225 | 225 | 0 | 0 | 0.574 | — |
| level2 | 486 | 455 | 31 | 3 | 0.572 | 0.586 |
| level3a | 672 | 569 | 103 | 12 | 0.577 | 0.586 |
| level3 | 320 | 320 | 0 | 0 | 0.572 | — |
| level3b | 101 | 101 | 0 | 0 | 0.586 | — |
| level4 | 356 | 353 | 3 | 2 | 0.571 | 0.570 |
| invitro | 157 | 157 | 0 | 0 | 0.574 | — |
| guideline | 51 | 51 | 0 | 0 | 0.593 | — |
| level5 | 290 | 290 | 0 | 0 | 0.569 | — |
| **TOTAL** | **4867** | **3301** | **1566** | | | |

Only level1 is meaningfully quota-bound, and it is bound on **28 of 29
questions**. Nine of the eleven tiers are never bound at all.

**A correction to the queue.** Rule 23 and A35f say "level1's quota is 25 against
other tiers' 4–19". On the library route that is not so: every tier gets the same
flat 25 (`RELEVANCE_GATE["max_per_tier"]`). level1 is bound because it holds 2,153
of the 4,867 available candidates — 44% of everything above the floor. The 4–19
figures are `MODE_TIER_QUOTAS`, which belongs to the **live** path. The conclusion
that level1's 21% cited rate is a denominator effect is unaffected; the reason for
the large denominator is candidate mass, not a larger allowance.

## 3. The inversion is real, and large

For each question, papers the quota **cut** that are **more similar** than the
least similar paper it **admitted** from some other tier:

**1,525 papers, on 28 of 29 questions.**

| question | inverted | best cut | worst admitted |
|---|---|---|---|
| preemptive-nsaid | 114 | 0.675 | 0.559 |
| direct-pulp-capping | 87 | 0.709 | 0.601 |
| apdt-primary-molars | 85 | 0.661 | 0.581 |
| laser-root-canal-disinfection-library | 82 | 0.694 | 0.551 |
| mta-vs-biodentine-pulpotomy | 77 | **0.727** | 0.591 |
| bisphosphonates | 80 | 0.612 | 0.573 |

This is standing rule 19 one level up, exactly as A35j says: a fixed per-tier
quota admits a paper at 0.591 and excludes one at 0.727 because slots exist.

## 4. But fixing it that way is a swap, and the swap goes the wrong way

A35j's scheme — reserve a floor of slots per tier, then fill remaining capacity by
similarity across all tiers — at cost parity (reserve 6/tier, cap 120):

| | current flat 25 | A35j reserve 6 / cap 120 |
|---|---|---|
| mean pool | 114 | 116 |
| context tokens | 55,750 | 59,091 |
| $/answer | 0.8363 | **0.8864** (+6%) |
| mean similarity of pool | 0.6257 | **0.6316** (+0.006) |
| mean worst admitted | 0.563 | 0.567 |
| **level1 share of the pool** | **23%** | **42%** |
| inversions remaining | 1525 | 1218 |

**Who enters and who leaves** (A30c's standard):

- **entering:** 689 papers, similarity 0.551–0.727 (median 0.613), median score 67
- **leaving:** 620 papers, similarity 0.550–0.679 (median 0.587), median score 47

| tier | entering | leaving | net |
|---|---|---|---|
| **level1** | **675** | 0 | **+675** |
| level3a | 14 | 137 | −123 |
| level2 | 0 | 132 | −132 |
| level4 | 0 | 109 | −109 |
| level3 | 0 | 87 | −87 |
| level5 | 0 | 83 | −83 |
| classic | 0 | 45 | −45 |
| invitro | 0 | 23 | −23 |
| level3b | 0 | 4 | −4 |

**675 of the 689 entrants are level1.** That is not a coincidence and it is not a
tuning artefact: level1 holds 44% of the candidates and is the only tier the quota
binds, so every slot the quota stops rationing goes to it. The per-tier quota is
the only thing currently keeping level1 below a quarter of the pool.

The pool gets 0.006 more similar on average, costs 6% more, and doubles the share
of the tier A35a measured as cited at **21%** — against 42% for cochrane, 46% for
level3a, 54% for level3b and 45% for level5.

Weighting each scheme's tier composition by A35a's measured per-tier cited rates:

| scheme | weighted cited-rate of the pool |
|---|---|
| current flat 25/tier | **0.312** |
| A35j reserve 6 / cap 120 | 0.285 |
| quota + global floor at the highest cut similarity | 0.294 |
| quota + fixed floor 0.60 | 0.308 |
| quota + fixed floor 0.62 | 0.304 |

Those rates were measured on ~40-paper pools and A33j found the rate **falls** as
pools grow, so this is not a citation-count prediction and must not be quoted as
one. What it licenses is a direction, and every scheme's direction is the same:
A35j's pool is composed of papers that have historically been **less** likely to
be cited than the pool it replaces.

**So A35j, built and measured, is predicted to lower the citation count it exists
to raise. It is not shipped.**

## 5. The other direction, measured

The same inversion can be removed by dropping the low-similarity papers the quota
**admitted**, rather than by admitting the ones it cut:

| scheme | pool | ctx tok | $/ans | mean sim | level1 % |
|---|---|---|---|---|---|
| current: flat 25/tier | 114 | 55,750 | 0.8363 | 0.6257 | 23% |
| A35j: reserve 6, cap 120 | 116 | 59,091 | 0.8864 | 0.6316 | 42% |
| quota + fixed floor 0.60 | **74** | 37,302 | **0.5595** | **0.6520** | 28% |
| quota + fixed floor 0.62 | 57 | 28,840 | 0.4326 | 0.6644 | 28% |

A floor of 0.60 gives a third fewer papers, a third less cost, a more relevant
pool, and the tier balance essentially unchanged.

**This is a hypothesis, not a recommendation to ship.** It is a supply
*reduction*, and whether a smaller, more relevant pool produces more citations is
precisely the untested thing — though A33j's finding that bigger pools cite at
lower rates points that way. Rule 21: it needs its own measurement, and it is a
question for RB because it reverses the direction A35 was pointed in.

## 6. The constraint nobody has moved

`multi_query_search` returns `out[:limit * 2]` — a hard **200** candidates.

- The KNN returned 200 on **29 of 29** questions.
- All 200 cleared the similarity floor on **14 of 29**.

On those 14 the similarity floor is selecting nothing; an unexamined constant is
deciding the candidate pool, upstream of every tier decision in this report. It
truncates in similarity order, so it is membership-by-relevance in kind and not a
rule-19 violation — but "how much evidence exists for this question" is currently
answered by that constant on half the eval set.

Not changed here. The rest of this measurement says supply is not the constraint,
so raising it would add cost against a hypothesis the same data does not support.

## 7. What A35l says to conclude

> If the count does not rise, the supply explanation is exhausted and this is a
> synthesis-judgement question — say so rather than reaching for another
> mechanism.

Four supply-side explanations have now been eliminated by measurement:

1. synthesis refuses to descend the tier ladder — **no**, it descends more
   readily than it uses level1 (A35a)
2. level1 is imprecise — **no**, a denominator effect (A35f)
3. pool size buys citations — **no**, the rate ranges 2.2–82.4% and *falls* as
   pools grow (A33j)
4. the quota is too small — **no**, the pool is already 114 papers, and removing
   the quota moves the composition toward the lowest-citing tier (this report)

Curo cites ~9–11 of ~114 available. **Whether that is too few is a synthesis
judgement, not a supply problem, and that is where A35 now sits.**

## 8. Scope limit, stated rather than buried

This measures the **library** route. The live path's quota question is
unmeasured, and it is not measurable by the same method: `MODE_TIER_QUOTAS` caps
each tier's own PubMed result set, where `pubmed_rank` is a rank *within that
tier's query*. There is no relevance number comparable between tiers on that
path, so "fill remaining capacity by similarity across all tiers" — A35j's
mechanism — is not defined there at all.

## 9. Found while measuring this: a third cap deciding membership by score

`app.py`, the differential merge loop, capped the merged per-tier union with
`bucket.sort(key=score); bucket[:max_per_tier]`. A30a's enumeration missed it.
Fixed to `cap_by_relevance`, with the score kept for ordering within the tier.
It matters most here of anywhere: the differential exists to carry evidence for
the candidate causes that are *not* the leading one, and the score does not know
which candidate a paper was retrieved for.
