# A5a — why the retreatment RCTs were not retrieved

**Measurement only. Nothing changed.** Fixture:
`eval/fixtures/review_retreatment_visits.md`. The answer declared:

> "No prospective study in this evidence base directly compares single- vs
> two-visit retreatment protocols with adequate power."

## The three papers, and their three different mechanisms

| paper | PMID | in the library? | reached the candidate pool? | mechanism |
|---|---|---|---|---|
| Karaoğlan, *Int Endod J* 2022 | **35488883** | **yes** — level1, score 67.8 | **yes** — KNN hit, similarity **0.648**, above the 0.55 floor | **discarded by a silent per-tier cap** |
| Toia, *J Endod* 2022 | **34688794** | **no** | no | never ingested |
| Schwendicke, *BMJ Open* 2017 | **28148534** | **yes** — level1, score 61.5 | **no** — not returned by any of the 8 KNN queries | embedding / vocabulary miss |

The coverage gate did short-circuit live PubMed (all four conditions passed:
200 hits, 61 above the floor, 52 high-tier, newest 2026) — but for the paper
that matters most that is **not** the proximate cause. The library had it. It
was retrieved. Then it was thrown away.

## The mechanism, exactly

`app.py`, the library branch, after banding by tier:

```python
bucket.sort(key=lambda x: x["score"], reverse=True)
bucket = bucket[:MAX_RAG_PAPERS_PER_TIER]      # 25
```

There is no other statement. Measured on this question's real pool:

```
cochrane  above floor   3 -> kept  3, discarded  0
level1    above floor  55 -> kept 25, DISCARDED 30   (cut-off score 74.8)
classic   above floor   2 -> kept  2, discarded  0
level2    above floor   3 -> kept  3, discarded  0
level3a   above floor   6 -> kept  6, discarded  0
TOTAL                  69 -> kept 39, DISCARDED 30
```

**30 of 69 candidate papers — 43% — were discarded with no log, no count and
no trace in the answer.** PMID 35488883 ranked **51st of 55** in its tier and
was cut.

This is standing rule §1.5's **fourth** instance in this codebase, after the
module cap at 3,200, the stitcher budget at 11,640, and the domain filter
excluding 48 of 124 canon papers. It is the worst of the four, because the
discarded content was not merely missing from the answer — the answer went on
to assert that it did not exist.

## The design fault underneath it

The cap ranks by **score**. Score is a proxy for *study quality* — design,
sample size, recency, citation velocity, follow-up. It says nothing about
whether a paper answers the question.

Similarity — which is precisely the relevance signal — is used as a **gate** and
then **discarded**. Once a paper clears 0.55, its similarity never influences
anything again.

So on this question:

* 35488883's title is *"Outcome of single- versus two-visit root canal
  retreatment"*. It is the single most on-point paper in the library.
* Its similarity, 0.648, was among the highest in the pool.
* Its score, 67.8, is unremarkable — it is a 100-patient RCT, so it loses to 25
  larger, newer level1 papers about other subjects.
* The cap sees only the score. It cuts the most relevant paper in the tier and
  keeps 25 less relevant ones.

**A cap that must discard should discard the least relevant, not the least
impressive.**

## What this means for A1 and A5b

A5b says A1 is done when this question retrieves the two 2022 RCTs. On this
evidence that needs **three** separate fixes, and only one of them is A1:

1. **The cap (this finding).** Fixing A1's coverage gate alone would send the
   question to live PubMed — where the run's own query *does* find 35488883
   (verified: the exact term `fetch_papers` builds returns it) — so A1 would
   make this question pass. But the paper would still be dropped by the cap on
   the next question where the library route is correct. **The cap is the
   deeper defect and it should be fixed first**, because a coverage gate that
   routes correctly into a stage that silently discards 43% of the pool has
   only moved the problem.
2. **Ingestion.** 34688794 is absent. Targeted add, with provenance, dry-run
   first (Stage 3 B3's branch 2).
3. **Retrieval vocabulary.** 28148534 is in the library and no query reached it
   (Stage 3 B3's branch 3).

**Note for A5c.** The gap-declaration rule as written keys on "was live PubMed
queried for that sub-question". That would **not** have caught this answer: the
gap sentence would still have been permitted if the gate had routed live, and
the sentence was false for a reason unrelated to routing — the evidence was
retrieved and discarded. The rule needs a second clause: **a gap may not be
declared over a sub-question for which candidates were discarded by a cap.**
Otherwise the fix passes its own test while the false statement survives.

## Recommendation, in order

1. Make the cap log and count what it discards (§1.5), on every path. Cheap,
   and it turns this class of defect from invisible to obvious.
2. Rank the cap by relevance, or by a relevance-and-quality combination — not
   by score alone. Measure the effect before choosing; I have not changed it.
3. Then A1's coverage gate, with A5c's rule extended as above.

Nothing above is implemented. Reporting the mechanism first, per the item.
