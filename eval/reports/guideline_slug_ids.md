# Item 3 — the 31 slug-id guideline rows, split

**Date:** 2026-09-06
**Replay:** `python scripts/quarantine_duplicate_guidelines.py` (dry run)

---

## 3a — the split

31 citeable rows at `level_key='guideline'` carried a slug id (`ESE-QG-2006`,
`AAE-VPT-2021`, …) rather than a PMID. The synthesis prompt requires
`[[PMID:nnnnnnn]]`, so on the library route those rows **cannot be cited in the
required format at all**.

| | count |
|---|---|
| slug rows, citeable | **31** |
| **WITH** a confirmed seed PMID | **1** |
| **WITHOUT** | **30** |

The 30, by reason:

| reason | count | what it means |
|---|---|---|
| `confirmed`, **no PMID in the seed at all** | **18** | real documents PubMed does not index — AAE position statements, SDCEP, NICE, CGDent |
| `unconfirmed_pmid` | **10** | the accession is precisely the field nobody verified |
| no seed record | 2 | not in the manifest |

**None of the 30 can be re-keyed without inventing bibliographic data**, which
is the error this whole line of work exists to clean up.

## 3b — the one that could be re-keyed was a duplicate, not a re-key

`ESE-QG-2006` → PMID **17180780**. And the target **already exists** in the
library, unquarantined, at `level_key='guideline'`, with
`guideline_id='ESE-QG-2006'`, org ESE, status superseded, confidence confirmed
and a NULL score — the verified copy, ingested from the manifest.

```
17180780      Quality guidelines for endodontic treatment: consensus report of
              the European Society of Endodontology        gid=ESE-QG-2006
                                                           conf=confirmed  score=None
ESE-QG-2006   ESE Quality Guidelines for Endodontic Treatment: Consensus Report
              of the European Society of Endodontology     gid=''  conf=''
```

So re-keying would have created a **second** row for 17180780 — the duplicate
this repo already made once with 30664240. The slug row is quarantined
`duplicate_of:17180780`: not renamed (the titles differ in capitalisation and
journal formatting, and choosing between them is inventing bibliographic data)
and not deleted (RB decides removal).

The script **aborts** rather than proceeding if the survivor is missing,
itself quarantined, or not `confirmed` — because the quarantine is only safe
*because* the verified copy is present and citeable. Without that check this
would remove a document from the library rather than deduplicate it.

Delta, dry-run then applied: citeable guideline rows **56 → 55**, slug rows
**31 → 30**, numeric-PMID rows **25 → 25**, nothing deleted.

## Two of the four A2-verified records have now turned out redundant

`ESE-PS-VPT-2019` (2026-09-05) and `ESE-QG-2006` (today). Both were **kept** by
the A2 audit, correctly: it asked *"does this record name a real document?"*
and the answer was yes both times.

**Verifying that a document is real does not establish that the ROW is
needed**, and nothing in the A2 pass was asking that. Recorded in
`tests/test_guideline_quarantine.py` under `QUARANTINED_LATER` rather than
edited away, with each entry's superseded verdict and the question that
superseded it (rule 24).

## 3c — the 30 stay, and that is the decision

They are left citeable-in-principle and uncitable-in-format. They need a
**non-PMID citation form**, which is A49 phase 1's `guidelines` table with its
own `ORG-TOPIC-YEAR` identifier scheme — not this batch.

It is **test-pinned at exactly 30**, so a later batch cannot read the silence
as permission: the assertion fails if they are re-keyed (inventing accessions)
*or* quarantined (removing real documents from the library). A second test
asserts no row exists under any of the 10 `unconfirmed_pmid` accessions.

---

## FOUND, NOT FIXED

- **18 real, current guideline documents cannot be cited on the library
  route.** Severity: HIGH, and it is now the largest remaining constraint on
  the guideline path. They are AAE position statements, SDCEP, NICE and CGDent
  guidance — documents a clinician acts on daily, which PubMed does not index.
  The prompt's `[[PMID:n]]` requirement is what excludes them, so the fix is a
  citation form, not a retrieval change.
- **The live route is unaffected** and that asymmetry is worth stating: a
  guideline fetched live from PubMed always has a real PMID, so it cites
  cleanly. The route that answers most warm questions is the one that cannot
  cite the specialty's own guidance.
