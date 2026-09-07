# Batch 2026-09-08 — Item C: retrieval becomes reproducible, and what that revealed

## Change 1 — the variance measurement

10 real eval questions × 5 runs of `generate_search_terms` (Haiku), comparing
query **strings** as rule 38 requires.

| | before | after |
|---|---|---|
| identical query string across 5 runs | **0/10** | **10/10** |
| identical AND-group set (order ignored) | **0/10** | **10/10** |
| mean pairwise group Jaccard | **0.135** | **1.000** |
| questions giving 5 distinct queries in 5 runs | 9/10 | 0/10 |

The cause was a single omission: no `temperature` was passed to the one model
call every retrieval depends on, so the API default applied. Prediction 5 —
"it is NOT already at temperature 0" — confirmed.

Prediction 4 said "below 40% identical". Right, and far too generous: it was
**zero**. Two runs of the same build were searching PubMed for different
things. This is the root of both open mysteries: the 2026-09-06 confinement
proof measuring 61/256 pools changed against an *identical* build, and A54's
probe returning three different guideline pools.

**Prediction for the after-run, committed before it ran, was 60–90% identical
and Jaccard above 0.9.** It reached 100%. Saying so, as promised.

## Change 2 — the term cache

`search_term_cache`, keyed on `sha256(mode, prompt-version, normalised
question)`. No TTL; the prompt hash is the invalidation. Hit and miss are both
logged. There was no existing harness cache to reuse, so this is the only one.

The prompt hash is taken over the **fully rendered** prompt with the question
elided, so it moves when the template moves, when `lexicon_offer_block()`
changes, and when a conversation context block is attached. A cache keyed on
the question alone would keep serving terms built by a prompt that no longer
exists — most damagingly right after someone improved it.

The degraded fallback is **never cached**. When the generator cannot produce a
usable query it falls back to the raw question; storing that would freeze a
known-bad retrieval in place *and hide it*, because the next run would hit the
cache, print nothing, and never re-attempt generation.

Given temperature 0 already delivers reproducibility, the cache earns its place
on three other grounds: temperature 0 is near-deterministic in a served model,
not guaranteed, and says nothing across a model version change; it makes the
query an artefact a stored answer can point at; and it removes a Haiku call
from every retrieval.

## Change 3 — provenance on stored answers

`query_cache.retrieval_provenance` (nullable) records the query string, its
cache key, the mode, and whether the terms came from the model, the cache, or a
degraded fallback. Nullable and staying so: the 100+ answers stored before this
have no honest value to put there, and a back-filled guess would look like a
record of what happened.

The record is **thread-local**. A module-level dict would let one question's
query be stored as another's provenance under Flask's concurrent requests or
the curriculum builder's thread pool — a wrong audit trail, which is worse than
none because it looks authoritative.

## Change 4 — the three admission rules. **Nothing shipped.**

31 questions (the eval set has 29 entries, 28 unique, plus 3 probes — not the
32 the batch assumed).

| rule | median | max | mean | non-current admitted |
|---|---|---|---|---|
| (a) similarity above floor | 1.0 | 7 | 1.4 | none |
| (b) scope, ≥2 shared terms | 0.0 | 3 | 0.3 | none |
| (c) union | 1.0 | 7 | 1.6 | none |
| *(b1) scope, ≥1 — diagnostic only* | *2.0* | *10* | *3.8* | *none* |

Every rule passes the size bar. **Every rule fails the probes 0/3.**

Per the batch: *"If none does, ship nothing and report the table."* Nothing was
shipped. `(b1)` is the shipped ≥1 bypass, measured only to show what the ≥2
threshold costs; it is not a shipping candidate, because inventing a fourth
rule that happens to pass would be tuning to the target — and it fails the
probes anyway.

### Why (a) fails — the documents never arrive

| probe 2 watched document | similarity | floor 0.55 |
|---|---|---|
| `IADT-FRACTURES-LUXATIONS-2020` | 0.526 | below, by 0.024 |
| `AAE-TRAUMA-2026` | — | not in the top 100 |
| `ESE-TRAUMA-2021` | — | not in the top 100 |

For probe 3, none of the three watched documents is in the top 100.

### Why (b) fails — a vocabulary gap, and a watch list that may be wrong

| document | shares with its probe | need |
|---|---|---|
| `IADT-FRACTURES-LUXATIONS-2020` | `crown fracture`, `pulp` (2) | ✓ |
| `ESE-TRAUMA-2021` | `pulp` (1) | ✗ |
| `AAE-TRAUMA-2026` | **none** | ✗ at any threshold |
| `ESE-S3-2023` | `retreatment` (1) | ✗ |
| `AAE-TREATMENTSTANDARDS-2018` | `retreatment` (1) | ✗ |
| `ACP-ASYMPTOMATIC-EXTRACTION-2016` | **none** | ✗ at any threshold |

Two of these are worth RB's attention:

- **`AAE-TRAUMA-2026` may not belong on probe 2's watch list.** Its manifest
  scope is `[dental trauma, avulsion, luxation, root fracture]`. Probe 2 asks
  about a **crown** fracture. The document's own declared scope says it is not
  about this question, so no scope rule can or should admit it — and the
  done-when cannot be met while it is watched for.
- **`ACP-ASYMPTOMATIC-EXTRACTION-2016` is a pure vocabulary gap.** Its scope
  says `failing endodontic treatment`; probe 3 says `failed root canal
  retreatment`. Same clinical situation, no shared token. This is fixable in
  the manifest, not in the code.

### A premise of mine, overturned

The 2026-09-07 report concluded: *"the done-when is NOT met, and no admission
rule can meet it — the documents do not reliably reach the candidate set,
because `generate_search_terms` is non-deterministic."*

Terms are now fully deterministic and the bar is **still** not met. So
non-determinism was not the reason, or not the only one. The actual reasons are
the two above, and neither was visible while the pool moved run to run.

### An instrument error I repeated

My first version of rule (a) embedded the raw question and ranked guideline rows
against that single vector. It reported median-above-floor = 0. That is
**instrument error #4 in `AGENT_QUEUE.md`, recorded on 2026-09-07, with the
identical symptom** — production calls `multi_query_search`, which KNNs once per
generated boolean *and* once for the question and keeps the best similarity per
PMID, precisely because a well-formed boolean embeds *further* from a paper's
prose than the clinician's own words. Corrected; the numbers above are from the
production instrument. (Rule 33.)

## Rule 38 extension — the residual, and it is not what I predicted

Same query string sent to PubMed twice, 31 questions, retmax 50 by relevance.
Term noise is zero **by construction**.

| | |
|---|---|
| pools with a different member set | **8/31 (26%)** |
| pools differing in order only | 4/31 |
| any difference at all | 12/31 (39%) |

**Prediction 8 was wrong.** I predicted 10–20%, "well below the 24% (61/256)
measured on 2026-09-06 when both sources of noise were present". The residual is
**26%** — statistically indistinguishable from the 24% measured with term noise
included.

The conclusion is the opposite of the one I expected: **PubMed's own ranking
accounts for essentially all pool instability, and freezing the terms does not
reduce it.** Term generation was 100% unstable at the string level and
contributed almost nothing to pool membership on top of the source's own churn.

Caveat, stated because the two numbers are not strictly comparable: the
2026-09-06 figure was 256 pools across a full multi-lane build; this is 31
questions at one esearch each. The direction and magnitude are what matter.

**For rule 38 this means the same-build noise floor for a pool A/B is ~26%, and
it is not removable by freezing terms.** Any A/B reporting a pool-membership
effect below that is measuring PubMed, not the change. Query-construction
changes must continue to compare query strings, where the floor is now zero.

## Tests

- `tests/test_term_cache.py` — 16. Mutation-checked by breaking the key twice
  and watching the right tests fail: dropping `mode` failed
  `test_the_mode_is_part_of_the_key`; dropping the prompt hash failed both
  `test_changing_the_prompt_retires_the_entry` and
  `test_a_conversation_context_block_changes_the_key`.
- `tests/test_retrieval_provenance.py` — 8, including thread isolation and that
  a degraded run is recorded as degraded.
- `tests/test_guideline_scope_admission.py` — 12, pinning the scope machinery
  that exists rather than a rule that was not adopted.

Full suite bare: **2819 passed, 52 skipped, 1 xfailed**.
