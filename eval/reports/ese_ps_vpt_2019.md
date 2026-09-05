# Item 5 — ESE-PS-VPT-2019: NOT retitled, and why

**Date:** 2026-09-05 · **Verdict: the condition for retitling is NOT met. Nothing changed.**

## The rule the ORDER set

> IF the stored row carries PMID 30664240, retitle it from the manifest — that
> is copying a verified record, not inventing. IF it carries no PMID, or a
> different one, DO NOT retitle; the match is by inference and that is the
> error being cleaned up.

## What the row actually carries

```
pmid                   'ESE-PS-VPT-2019'          <-- the id_slug, not an accession
title                  'ESE Position Statement: Outcome of Primary Root Canal Treatment'
year                   2019
level_key              'guideline'
score                  87.0
guideline_id           ''                          <-- empty
guideline_confidence   ''
```

**It carries no PMID at all.** The `pmid` column holds the identifier slug
`ESE-PS-VPT-2019` — which is the `[PMID AAE-PS-diagnosis]` leak mechanism the
guidelines handover identified, visible here in the data rather than in a
rendered citation.

So the condition fails and **the row is not retitled.** Matching it to
PMID 30664240 would be an inference from the year and the organisation, and
inference is the error being cleaned up.

## And the document it was thought to be is already here, correctly

```
pmid                   '30664240'
title                  'European Society of Endodontology position statement:
                        management of deep caries and the exposed pulp'
level_key              'guideline'
score                  None
guideline_id           'ESE-DEEPCARIES-2019'
guideline_status       'superseded_in_content'
guideline_confidence   'confirmed'
```

This changes the shape of the problem. `ESE-PS-VPT-2019` is not a record with a
wrong title that needs repairing — the correct document is **already in the
library**, from the verified manifest, with the verified title, a confirmed
accession, a NULL score and its status recorded. `ESE-PS-VPT-2019` is a
**second, unverified row for a document that is already present in verified
form.**

That makes the disposal question "is this row a duplicate that should be
quarantined", not "what should it be called" — a different question, with a
different answer, and one the ORDER did not ask. Deleting or quarantining
library rows is explicitly out of scope for this batch. **Recorded for RB.**

---

## FOUND NOT FIXED — hand-set guideline scores are still live. Severity: HIGH.

Looking at this row surfaced something not on any current list. **Five
unquarantined rows at `level_key = 'guideline'` still carry a non-NULL score:**

| pmid | score | title |
|---|---|---|
| `AAE-PS-diagnosis` | **90.0** | AAE Position Statement: Endodontic Diagnosis |
| `AAE-PS-vital-pulp` | **90.0** | AAE Position Statement: Vital Pulp Therapy |
| `ESE-PS-VPT-2019` | **87.0** | ESE Position Statement: Outcome of Primary Root Canal Treatment |
| `ESE-QG-2006` | 50.4 | ESE Quality Guidelines for Endodontic Treatment |
| `39578680` | 59.3 | Position Statement and Recommendations for Custom... |

The first four are `ingest_aae_guidelines.py` records — the hand-set 85–90
scores that the guidelines handover named as defect #4:

> Hand-scored guideline records at 85–90 therefore **outrank every genuine
> systematic review in the library.**

The A2 audit quarantined 12 of the 16, and these four survived because they
were **verified as real documents**. Verification settled whether the document
exists. It did not touch the score, and nothing since has. So the score-as-
authority defect A49 was built to remove is still live on the four rows that
were kept precisely because they are citeable.

**Why this matters more than it looks.** Every other guideline row now stores
`score` NULL and renders "NOT SCORED — a guideline is a specialty's stated
position, not a study design". These four render `Evidence Score: 90.0/100` —
above the Schwendicke Cochrane review at 81.5 and Coll 2025 at 80.0. They are
the highest-scoring "evidence" in the library, on a scale they are not on.

`39578680` is a different case and should not be swept up with them: it has a
real accession and a computed score. It is a PubMed paper banded to the
guideline tier, not a hand-scored record.

**Not fixed here**: this is a DB write on citeable rows that no item in this
batch asked for, and standing rule 2 wants a dry run with the delta split by
tier before any such write. It is a clean, well-scoped next item — null the
score on the three hand-scored slugs, leave `39578680` alone, and the
"NOT SCORED" renderer already built will pick them up with no further work.
