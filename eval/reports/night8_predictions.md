# Night batch 2026-09-06 — predictions, committed BEFORE the measurements

Standing rule: commit the prediction before the measurement. This file is
written and committed before `--apply` is run, before the item-B measurement,
and before the item-C matrix. Nothing below has been measured yet at the time
of the commit that adds this file.

Branch `night-20260906`, off `d6492d1`.

---

## Phase 0 — verified before writing this

| check | expected | measured | verdict |
|---|---|---|---|
| `endo-ai-rag-20260905-2305.bundle` exists | yes | yes | PASS |
| bundle integrity | verifies | "The bundle records a complete history." | PASS |
| `db-20260905-2305/` exists | yes | 14 tables | PASS |
| `endo_papers_rag` total rows | 3405 | 3405 | PASS |
| citeable `guideline` | 55 | 55 | PASS |
| `level1` | 1362 | 1362 | PASS |
| `level2` | 338 | 338 | PASS |

Phase 0 passes. The batch is cleared to start.

---

## A DEFINITIONAL CONFLICT INSIDE ITEM A'S PREDICTION — flagged before applying

Item A predicts `guideline 55 -> 94`. The dry run in
`a49_seed_extension_ingest_part2.md` predicts `guideline 51 -> 81`. Both
cannot be a prediction about the same number, and the difference is **not**
disagreement about what the ingest does — `level1 1362 -> 1361` and
`level2 338 -> 330` are identical in both. It is three different definitions
of "a guideline row", all three live in this repo right now:

| definition | where it lives | count now |
|---|---|---|
| raw — every row at `level_key='guideline'` | none; it is what a bare `GROUP BY` gives | **74** |
| citeable — `COALESCE(quarantine_reason,'') = ''` | `rag.py:570, 626, 708` (the three retrieval queries) | **55** |
| census — citeable AND not retracted AND title NOT ILIKE 'WITHDRAWN:%' AND not superseded | `scripts/ingest_guidelines_seed.py::tier_census` | **51** |

The handover's "citeable guideline 55" is the middle one. The dry run's
"51 -> 81" is the third one — the ingest script prints its own delta under its
own census. Item A's `55 -> 94` takes the **middle** baseline and adds
`30 inserts + 9 reclassifications = +39` to it.

**That arithmetic cannot be right under either definition**, and predicting it
here is the point of writing this down before the run:

- Under the **census** definition, +39 double-counts. 5 of the 30 inserts are
  quarantined on ingest (withdrawn/draft) and 13 records are marked superseded,
  so they are excluded from the census the moment they are written. The census
  delta is +30, not +39.
- Under the **citeable** definition, the 9 reclassifications add nothing at
  all: those 9 rows are already citeable today, sitting at level1/level2. They
  move *between* tiers. They are a +9 to `guideline` and a −9 from
  level1/level2 — which is exactly what the level1 and level2 predictions say,
  and those two are the halves everybody agrees on.

### So this is my prediction, stated per definition, before the run

| number | definition | before | predicted after | delta |
|---|---|---|---|---|
| guideline | census (what the script prints) | 51 | 81 | +30 |
| guideline | citeable (`quarantine_reason` only) | 55 | 90 | +35 |
| guideline | raw | 74 | 113 | +39 |
| level1 | all three agree | 1362 | 1361 | −1 |
| level2 | all three agree | 338 | 330 | −8 |
| total rows | raw | 3405 | 3435 | +30 |

The citeable +35 is `30 inserts − 5 quarantined-on-ingest + 9 reclassified in
− 0 out` = +34, plus 1: PMID 17367451 is predicted by the batch to be
"inserted fresh since it is absent", and if it is instead already present the
insert count falls to 29 and this becomes +34. **I am recording +35 and the
alternative +34 rather than picking one**, because I have not yet looked at
whether 17367451 is in the table, and guessing would make this a postdiction.

**If the dry run disagrees with all three of these, I stop and report — I do
not reason my way to a fourth definition that fits.**

The blocking condition the batch actually names is `applied delta ==
dry-run delta`. A prediction that misses is a wrong prediction, reported as
wrong by count or by class; a *dry run* that misses the *applied* run is a
stop.

---

## Item A — the realised defect

Prediction: the served rendering of the stored answer citing 32475015 will
**still show level2 / 47.0**, because a stored answer is stored *text* and the
ingest writes the *table*. I expect this to be found-not-fixed HIGH with a
non-zero count. I am predicting non-zero specifically so that a zero, if it
comes back, has to be defended rather than accepted.

## Item B — the lane regression

Predictions, all falsifiable:

1. The chosen group will contain **no domain noun** on ≥ 10 of the 32 (the
   handover measured 10 of 29 where length alone decides).
2. Off-domain guidelines will be **> 0** in the before-state. If the
   before-state comes back 0, my detector is wrong, not the handover — the
   vascular-surgery and feline rows were seen directly.
3. `DOMAIN_NOUNS` built from the 29 questions' own term groups will contain
   **fewer than half** the 40 terms in `_COVERAGE_GENERIC`.
4. Fix (1) will meet the criteria and fix (2) — the PICO tagging — will not be
   needed. Stated so that reaching for (2) counts as a missed prediction.
5. Paper-lane pools will be **identical by PMID set**. If any paper pool
   changes, the change leaked and I revert.

## Item C — write-back banding

1. Publication types are **not stored per row** in `endo_papers_rag` (schema
   read: 31 columns, none of them a pubtype). So the 200-row sample path is the
   one that runs, and the matrix is reported on the sample with n stated.
2. The lane that admitted 32472740 as level1 is **level1** itself
   (`randomized controlled trial[pt] OR systematic review[pt] OR
   meta-analysis[pt]`) — and **not** because that filter contains a guideline
   publication type. `scripts/reclassify_by_pubtype.py` records that 32472740
   carries only `["Journal Article", "Review"]`. Prediction: **no lane filter
   in `tier_query_lanes()` contains a guideline publication type**, and the
   "door" is not a pubtype door at all — it is the write-back storing the lane.
   If a guideline pubtype does appear in a lane filter, this prediction is
   wrong by class, not by count.

## Item E — co-publication

1. 42017497 and 42014635 will both resolve to the EFCD-ESE-ORCA deep-caries
   guideline by title and journal.
2. The manifest already carries `alt_pmid` on **6** records and the ingest
   references the field **0** times (grepped). Both confirmed before writing.
3. Same-title/same-year/different-PMID pairs across the corpus: predicted
   **between 5 and 30**. A count of 0 would mean my normalisation is broken,
   not that the corpus is clean.
