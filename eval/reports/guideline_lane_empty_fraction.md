# Item 2 — the guideline lane and the empty-fraction assertion

**Date:** 2026-09-05
**Change: the guideline lane is out of the `max_empty_fraction` denominator and
has its own reported metric. The 50% ceiling is untouched.**

---

## The measurement

Across the three v7 baseline runs, 2,172 esearch calls:

| lane | queries | empty | empty % |
|---|---|---|---|
| **guideline** | **482** | **415** | **86%** |
| cochrane | 67 | 50 | 75% |
| level3b | 208 | 123 | 59% |
| level1 | 439 | 219 | 50% |
| level3a | 192 | 89 | 46% |
| level4 | 188 | 79 | 42% |
| level2 | 188 | 73 | 39% |
| level5 | 189 | 71 | 38% |
| **observational** | 184 | 66 | **36%** |
| provisional | 35 | 7 | 20% |
| **TOTAL** | **2,172** | **1,192** | **55%** |

Pre-existing lanes together: **47%**. The two lanes added: **72%**, entirely
driven by the guideline lane — `observational` is at 36%, *better* than the
corpus average, so "the new lanes are noisy" would have been the wrong
generalisation.

**Excluding the guideline lane brings the corpus rate to 46%**, under the 50%
ceiling the assertion was written against.

## Why exclusion is right, and why it is not weakening the gate

The assertion's own message says: *"when most queries match no records the
queries are malformed, not the topic thin"*. That reasoning holds for a study
lane — a well-formed query about a treatment should find *some* trials.

It does not transfer. **A specialty body either has published on this exact
topic or it has not.** An empty guideline result on a narrow clinical question
is the expected case and carries no information about query quality. The lane
is on a different axis from the study lanes the assertion was written for, and
it did not exist when the 50% ceiling was chosen.

**The threshold is untouched (rule 6).** The denominator is corrected to the
lanes the assertion was written for. And removing a lane from an assertion must
not mean ceasing to measure it, so `guideline_hit_rate` is now reported per
question and never asserted (rule 32).

## Re-evaluating the v7 failures

Nine cases failed on `max_empty_fraction` in v7. Re-run against the corrected
assertion:

| | count | cases |
|---|---|---|
| failed before | 9 | apdt, bisphosphonates, cracked-tooth, dens-invaginatus, intentional-replantation, laser-live, pregnancy, retreatment, sdf |
| fail after | 6 | apdt, bisphosphonates, dens-invaginatus, intentional-replantation, pregnancy, retreatment |
| **tripping on guideline emptiness alone** | **3** | **cracked-tooth-prognosis, laser-root-canal-disinfection-live, sdf-pulp-outcomes** |

**Caveat, stated because it matters:** this is a fresh re-run, not a
recomputation over the same audit records. PubMed is not deterministic between
runs, so part of the movement is variance. The six that still fail did so
consistently in all three v7 runs as well, which is the more robust half of
this result.

Observed hit rates in the re-run: 0% (apdt, cracked-tooth,
intentional-replantation, retreatment), 21% (bisphosphonates, laser-live,
pregnancy), 23% (dens-invaginatus).

---

## Is 86% the query shape or the corpus? — **THE QUERY SHAPE**

Eight of 29 questions had an empty guideline tier in all three runs. Checking
five of them by hand against the seed manifest:

| question | relevant guideline in the seed? |
|---|---|
| lasers in root canal disinfection | **no** — the manifest has no laser scope |
| sodium hypochlorite concentration | **no** — no irrigation/irrigant scope |
| PIPS/SWEEPS vs ultrasonic | **no** |
| sonic vs ultrasonic activation | **no** |
| **retreatment vs apical microsurgery** | **YES — ESE-S3-2023, PMID 37772327** |
| **"what about in immature teeth?"** | **YES — ESE-REVITALISATION-2016, PMID 26990236** |

Three of the five are correctly empty: the specialty has not published on
irrigant activation or laser disinfection, and silence is the right answer.

**Two are genuine misses, and the diagnosis is precise.** Both documents are
PubMed-indexed *and* both match the lane's publication-type filter — verified
directly against PubMed:

```
ESE-S3-2023      (PMID 37772327)  matches guideline[pt] filter: 1
ESE-REVITALISATION-2016 (26990236) matches guideline[pt] filter: 1
```

So the pubtype filter is not the problem. **The topic half of the query is.**
The lane inherits the same generated topic string the study lanes use — narrow,
trial-shaped, three AND-groups of synonyms — and a guideline is broad by
construction. "Treatment of pulpal and apical disease: the ESE S3-level
clinical practice guideline" cannot match a query built to find trials about
*nonsurgical retreatment versus apical microsurgery in persistent apical
periodontitis*, even though it is the guideline that answers the question.

**FOUND NOT FIXED — severity HIGH.** The guideline lane needs a broader topic
term than the study lanes, because it is looking for a different kind of
document. Two named misses with PMIDs: **37772327** and **26990236**. Not fixed
here: the batch forbids threshold and constant changes, and changing the lane's
query is a retrieval change that would need its own before/after across the 29.

The second finding stands beside it: **31 of 56 citeable guideline rows carry a
slug id rather than a PMID**, so on the library route they cannot satisfy the
`[[PMID:nnnnnnn]]` citation format at all. Between them, these two say the
guideline path is reachable in principle and constrained in practice at both
ends — retrieval and citation.
