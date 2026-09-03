# A7 — guideline banding, APPLIED

Follows the dry run in `a7_guideline_banding_dryrun.md` (`bf93a52`), which sat
awaiting sign-off. **Banding only (A12): `level_key` is the only column written.
No score is read, computed or changed.**

## Why it stopped being cosmetic

The dry run treated this as a labelling defect — position statements wearing
"Level I — RCTs & Systematic Reviews". A30 showed it was also a *retrieval*
defect. The KNN's `ORDER BY (score * 0.6 + similarity * 40)` and the per-tier
cap both decided MEMBERSHIP by score, and these 21 rows carry the highest
scores in the library. Measured on the retreatment question, the papers the old
ordering kept and the new one drops:

```
  sim 0.574  score 90.0  AAE Position Statement: Implant Decision Making
  sim 0.495  score 90.0  AAE Position Statement: Endodontic Diagnosis
  sim 0.397  score 90.0  AAE Position Statement: Obturation
```

Six of the eight shown sat BELOW the 0.55 similarity floor — occupying
candidate slots they could never use, purely on score. That is why A7 moved
from parked to urgent.

## Delta

```
rows matching the predicate   21     (0.69% of a 3,035-row library)
  level1 -> guideline         19
  level2 -> guideline          1
  level5 -> guideline          1
backup                        endo_papers_rag_tier_backup_a7 (pmid, level_key)
```

**One row was excluded from the dry run's 22.** `36920339` — "Systematic
review of clinical practice guidelines for traumatic dental injuries" — matched
the title predicate and is typed `Systematic Review` by PubMed. A systematic
review *of* guidelines is a systematic review; banding it would have demoted
real evidence on the strength of a word in its title, which is the same
title-matching error the predicate exists to avoid. The predicate now excludes
`title ILIKE 'systematic review of%'`.

## Where the rung sits

```
cochrane, level1, classic, level2, level3a, level3, level3b, level4,
invitro, GUIDELINE, level5, observational
```

Invariant 1 is tier by study design. A position statement is expert consensus
synthesised by a specialty body: above one expert's opinion, below a bench
result about a mechanism, and not a study at all. Its own floor (27), its own
quota (4 review / 6 learn / 4 case), its own `LEVEL_SCORES` design weight (12,
between invitro's 15 and level5's 10). No existing tier's floor or quota moved,
and tests pin each.

`LEVEL_SCORES` needed entries for `guideline` and `observational` or
`TIER_ORDER` stopped being monotonic in design strength. **That is not the A12
score change**: no stored score is read or written, and the 21 rebanded rows
keep the scores they had. It affects only how a row ingested after this point
is scored.

## Effect

Top of the Level I band on the retreatment question, after:

```
40898413  82.8  Outcome Following Complete and Partial Pulpotomy
42063099  81.7  Endodontic treatment outcomes in apical periodontitis
38145805  81.7  Outcome of root canal retreatment filled with gutta-percha
35762859  80.9  Non-surgical root canal treatment and retreatment
37815804  80.0  Outcome of single-visit root canal treatment
```

Real outcome studies, where three AAE/ESE statements sat before. Guidelines
occupy their own 2-row rung on the same question.

## Still open, and still RB's

The AAE statements keep **90.0**, the highest score in the library, on
documents that are not studies. Harmless for ordering now that they are in
their own band — but the next rescore bakes it in further, and the same
document class still carries five different scores depending on how it was
ingested (90.0 hand-ingested, 30.9 from PubMed). That is a scoring decision,
deliberately not taken here.
