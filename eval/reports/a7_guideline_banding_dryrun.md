# A7 — position statements are not Level I. **DRY RUN, NOT APPLIED.**

Standing rule 2: dry-run, delta split first, back up every column overwritten.
A12: **banding only — no score is read, computed or changed.**

## What is there now

```
library                     2,909 rows
Cochrane band                  42 rows, score 51.5 – 85.9
rows matching the predicate    22
```

Predicate: a synthetic authority key (`AAE-`, `ESE-`, `SDCEP-`, `ADA-`,
`AAOMR-`) **or** a title naming itself a position statement / quality guideline
/ clinical practice guideline / consensus statement.

| pmid | level_key | score | title |
|---|---|---|---|
| AAE-PS-retreatment | level1 | 90.0 | AAE Position Statement: Endodontic Retreatment |
| AAE-PS-antibiotics | level1 | 90.0 | …Systemic Antibiotics |
| AAE-PS-microscope | level1 | 90.0 | …Surgical Operating Microscope |
| AAE-PS-implant-v-endo | level1 | 90.0 | …Implant Decision |
| AAE-PS-trauma | level1 | 90.0 | …Traumatic Dental Injuries |
| AAE-PS-diagnosis | level1 | 90.0 | …Endodontic Diagnosis |
| AAE-PS-obturation | level1 | 90.0 | …Obturation |
| AAE-PS-safety | level1 | 90.0 | …Patient Safety |
| AAE-PS-cbct | level1 | 90.0 | …CBCT |
| AAE-PS-vital-pulp | level1 | 90.0 | …Vital Pulp Therapy |
| AAE-PS-cracked-tooth | level1 | 90.0 | …Cracked Teeth |
| AAE-PS-regenerative | level1 | 90.0 | …Regenerative Endodontics |
| AAE-PS-isolation | level1 | 90.0 | …Isolation of the Operating Field |
| ESE-QG-2023 | level1 | 87.0 | ESE Quality Guidelines |
| ESE-PS-VPT-2019 | level1 | 87.0 | ESE Position Statement: Outcome of Primary RCT |
| 31668170 | level1 | 73.7 | Evidence-based clinical practice guideline |
| 37772327 | level1 | 58.1 | Treatment of pulpal and apical disease: The ESE… |
| 36920339 | level1 | 58.1 | Systematic review of clinical practice guidelines |
| ESE-QG-2006 | level1 | 50.4 | ESE Quality Guidelines, consensus |
| 28436043 | level1 | 50.4 | ESE position statement |
| 39578680 | level2 | 59.3 | Position Statement and Recommendations… |
| 36942472 | level5 | 30.9 | ESE position statement on root resorption |

**Two things fall out of that table that the item did not ask about.**

1. The 13 hand-ingested AAE statements score **90.0 — higher than every one of
   the 42 Cochrane reviews in the library** (top 85.9).
2. The same document class is treated three different ways depending on how it
   was ingested. An ESE position statement carries 87.0 in `level1` when it was
   hand-ingested (`ESE-PS-VPT-2019`) and 30.9 in `level5` when it came from
   PubMed (`36942472`). Five distinct scores and three tiers for one kind of
   document.

## Delta split

```
level1 -> guideline    20
level2 -> guideline     1
level5 -> guideline     1
                       --
TOTAL                  22 rows = 0.76% of the library
```

**One column written: `level_key`.** Scores, embeddings, abstracts, provenance
flags and every other column are untouched.

## Where the rung goes

`endo_ai.TIER_ORDER` is currently:

```
cochrane, level1, classic, level2, level3a, level3, level3b, level4, invitro, level5
```

Invariant 1 is tier by **study design**. A position statement is expert
consensus synthesised by a specialty body: stronger than one expert's opinion,
weaker than a trial or a systematic review of trials, and not a study at all —
so it does not belong on the primary-evidence rungs. Proposed:

```
cochrane, level1, classic, level2, level3a, level3, level3b, level4,
invitro, GUIDELINE, level5
```

Precedent exists: `retracted` is already a tier key outside `TIER_ORDER` (16
rows), and both the browser (`TIER_DISPLAY` → `tierSectionLabel`) and the deck
render an unknown key generically rather than dropping it. So a missing UI edit
degrades to "Other — guideline" rather than to silence. **The UI edit is still
required** and is part of the change, not optional.

## Effect on the answer you reported

The retreatment answer's papers table, computed on its real pool:

```
now                                  after banding
36512807  cochrane  73.7             36512807  cochrane  73.7
27759881  cochrane  73.3             27759881  cochrane  73.3
AAE-PS-retreatment  level1  90.0     35579093  level1    84.0
AAE-PS-diagnosis    level1  90.0     40898413  level1    82.8
ESE-PS-VPT-2019     level1  87.0     38145805  level1    81.7
35579093            level1  84.0     35762859  level1    80.9
```

Q6 already stopped the position statements outranking Cochrane. This stops them
being **labelled** "Level I — RCTs & Systematic Reviews", which is the half Q6
could not fix, and it clears two rows (`AAE-PS-diagnosis`, `ESE-PS-VPT-2019`)
that are irrelevant to the question and reached the table only through the
retrieval pool.

## Backup, before applying

```sql
create table endo_papers_rag_tier_backup_a7 as
  select pmid, level_key from endo_papers_rag where <predicate above>;
```

`endo_papers_rag_tier_backup` already exists from an earlier banding change and
must not be clobbered — hence the `_a7` suffix.

## Not applied. Awaiting sign-off.

**Open question.** A12 says banding only, so the AAE statements keep 90.0 — the
highest score in the library, on documents that are not studies. Within a band
that is harmless, because invariant 1 makes score rank only inside a tier, and
after this change they are inside their own tier. So the display is correct
either way and I have not touched it. But if a guideline should not out-score a
Cochrane review even notionally, that is a scoring decision for a separate
change, and I would want to know before the next rescore bakes 90.0 in further.
