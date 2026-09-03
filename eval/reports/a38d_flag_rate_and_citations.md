# A38d — flag rate and citation count, reported separately

RB's instruction: *"Measure the flag rate before and after, and the citation
count before and after, reported separately — so Defect 1's fix is not credited
with Defect 2's outcome, or blamed for its absence."*

They are separated below, and they say different things.

---

## Part 1 — flag rate (Defect 1). The false claim is gone.

29 eval questions, offline, on the same candidate sets as A35k. Three conditions,
so the two changes can be told apart.

| condition | papers flagged | % of pool | median % per question | questions hit |
|---|---|---|---|---|
| **OLD** year, unverified | 1,294 | 39.2% | 39% | 29 of 29 |
| **A38c** relevance, unverified | 695 | 21.1% | 20% | 29 of 29 |
| **NEW** relevance, verified | **1** | **0.0%** | 0% | **1 of 29** |

Attribution:

```
choosing the review by relevance alone     1294 -> 695   (-46%)
adding verified inclusion on top of that    695 ->   1   (-100%)
overall                                    1294 ->   1   (-100%)
```

**The honest reading.** Verified inclusion is a *correct* mechanism with
near-zero yield at current PubMed linkage coverage, and choosing the review by
relevance actually **lowers** coverage — a reference list exists for 34% of
year-picked reviews and 17% of relevance-picked ones. What repairs the defect is
not making the claim. Verification is a small honest bonus, not the repair.

28 of 29 questions now get the generic notice, naming a review at similarity
0.62–0.86 (mean 0.738) instead of a suppression list.

---

## Part 2 — citation count (Defect 2). **The hypothesis is not supported.**

Paired design, one variable: the same question answered twice against the **same
retrieved pool in the same process**, once with the notice as it ships now and
once with the old rule restored in-process. A before/after against the 15 cached
answers would have confounded the notice with every retrieval change since they
were cached (A5b, A30b, A31, A7, A33c).

Five library-route questions, chosen because they had the **highest** old flag
rates — if the notice suppressed citation anywhere, it is here.

| question | pool | old flags | OLD cited | NEW cited | delta | overlap |
|---|---|---|---|---|---|---|
| mta-vs-biodentine-pulpotomy | 123 | 60 | 15 | 14 | −1 | 13 |
| regenerative-immature | 145 | 61 | 23 | 23 | 0 | 17 |
| single-vs-multiple-visit | 86 | 50 | 23 | 21 | −2 | 16 |
| cbct-vs-periapical | 119 | 55 | 20 | 19 | −1 | 16 |
| direct-pulp-capping | 109 | 38 | 16 | 15 | −1 | 13 |
| **mean** | | | **19.4** | **18.4** | **−1.0** | |

**Removing a suppression instruction from 39% of the pool did not raise the
citation count.** Four of five moved down by 1–2 and one did not move; the
direction is flat-to-slightly-negative and well inside run-to-run variance.
n = 5, one run per condition; the pairing cancels question difficulty but not
synthesis stochasticity.

**Defect 2 is the fifth eliminated supply-side explanation.** As A38e says, a
negative result here is worth as much as a positive one:

1. synthesis refuses to descend the ladder — no (A35a)
2. level1 is imprecise — no, a denominator effect (A35f)
3. pool size buys citations — no, the rate *falls* as pools grow (A33j)
4. the quota is too small — no, the pool is already 114 papers (A35k)
5. the PRISMA notice suppresses citation — **no** (here)

Defect 1's fix stands on its own, exactly as RB framed it. It removed a false
claim; it was never owed a citation-count improvement.

---

## The two things this measurement found that nobody was looking for

### 1. Curo already cites ~19 papers, not 9–11. RB's target is met.

```
pool 86-145      cited 14-23      mean 18.4 (new code) / 19.4 (old rule)
```

The ~9–11 figure comes from A35a's read of the **15 cached answers**, and those
were generated *before* the membership fixes — A5b's cap, A30b's `ORDER BY`,
A31's observational tier, A7's guideline banding. Answering these five questions
fresh on current code, Curo cites 14 to 23 distinct papers.

**So the ~20-reference request appears to have been satisfied by the membership
fixes, and the whole A35 workstream has been chasing a number that was already
delivered.** That is the premise underneath A35, A35a, A35f, A35j, A35k and A38's
Defect 2, and it did not survive being measured directly.

Caveat, stated rather than buried: these are five library-route Review questions.
The cached-answer set is a different mix of modes and routes, so "9–11 → 18.4" is
not a clean before/after. What *is* directly measured is the right-hand number —
current code, these five questions, 14–23 papers cited.

### 2. Cost per Review answer is ~4× what the handover records.

| | $ / answer |
|---|---|
| `CURO_HANDOVER.md`, "cost per served Review answer" | 0.5596 |
| measured here, mean of 10 answers | **2.26** |
| worst single answer | 3.70 |

Synthesis is now reading ~86,000 input tokens per call, because the pool is ~114
papers (A35k). Two of the ten answers exceeded $3.50.

**RB's standing approval is ~$0.70 per library answer. Current cost is roughly
three times that**, and the handover figure that would have reassured anyone
checking is four times stale.

This lands directly on A35k's open question. A35k measured a
"quota + global similarity floor at 0.60" option at 74 papers and 37,302 context
tokens against the current 114 papers and 55,750 — a third less context, a more
relevant pool, and tier balance unchanged. It was reported and not shipped
because it reverses the direction A35 was pointed in. With the reference target
already met and cost at 3× the approved figure, **the argument for it is now
much stronger, and it is still RB's call.**

(A35k's per-scheme dollar figures are context-token cost only, for relative
comparison. The $2.26 measured here is all-in — output tokens, the citation
support checker, evidence mapping and any retry. The two are not the same
quantity and should not be quoted against each other.)

---

## Spend

$22.60 for ten answers. Cost read from the API responses in-process rather than
from `cost_log.jsonl`, which another chat's server on :5003 also writes to.
