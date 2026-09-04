# Why four known papers never reached the VPT pool

Measure only; nothing changed. Target run:
`learn_history/20260904_181328_vital_pulp_therapy_in_adult_teeth.json`
— 127 papers, $2.2173, question *"vital pulp therapy in adult teeth"*.

Replay: `python scripts/diagnose_missed_papers.py`

---

## THE BRANCH — **NOT RETURNED**, for three different reasons

All three verifiable targets were **NOT RETURNED by any of the 36 generated
queries**. Nothing entered the pool and got dropped by a later stage; the
queries never delivered them. But the reason differs per paper, and the fix
differs with it.

| paper | admitted by any conjunction? | why it never arrived |
|---|---|---|
| **Sulaiman** 42388091 | **NO — none of the 96 topic×tier conjunctions admits it** | its only PubMed pubtype is `Journal Article` |
| **Komora** 39117767 | yes, by 6 conjunctions | best relevance rank **219 of 300**; production takes the top 50 |
| **EFCD-ESE-ORCA** 42018467 | yes, by 1 conjunction | rank **521 of 608**; `Practice Guideline` is in no tier filter |

---

## Step 4 first — are they real?

Two A2 records described documents that do not exist, so the same scepticism
applies in this direction.

| target | verdict |
|---|---|
| Sulaiman et al., *Effect of Pulpal Haemostasis Time on Partial Pulpotomy Outcome in Cariously Exposed Mature Permanent…*, Int Endod J, 2026 Jul 2 | **REAL — PMID 42388091** |
| Komora et al., *Comparison of bioactive material failure rates in vital pulp treatment of permanent matured teeth*, Sci Rep, 2024 Aug 8 | **REAL — PMID 39117767** |
| *Deep Caries Management: EFCD-ESE-ORCA S3-Level Clinical Practice Guideline*, Caries Res, 2026 Apr 22 | **REAL — PMID 42018467** |
| Hoang et al. 2026, SR/MA of 23 RCTs, mature posterior irreversible pulpitis | **NOT FOUND on PubMed** by author + topic + publication type. Not concluded absent — the citation may be mis-attributed or the record not yet indexed. **Needs the DOI or PMID from whoever surfaced it before anything is built on it.** |

---

## Step 1 — the generated terms, verbatim

36 queries = **four topic groups × 12 tier buckets**. Every query is
`(topic group) AND (tier filter) AND (domain filter) NOT retracted`.

```
A  (pulp exposure OR "carious pulp exposure" OR "traumatic pulp exposure" OR
    "iatrogenic pulp exposure") AND (classification OR pathophysiology OR
    etiology OR "pulp inflammation" OR "pulp necrosis") AND (adult* OR
    "permanent teeth" OR "mature teeth")

B  ("pulp capping" OR pulpotomy OR "vital pulp therapy" OR "vital pulp
    therapies") AND ("success rate" OR "success rates" OR healing OR "dentin
    bridge" OR "calcified tissue" OR complication* OR recurrent OR failure OR
    "secondary caries" OR "periapical lesion" OR "follow-up outcome" OR
    prognosis*)

C  ("pulp capping" OR "direct pulp cap*" OR "indirect pulp cap*" OR pulpotomy
    OR "partial pulpotomy" OR "coronal pulpotomy" OR "superficial pulpotomy")
    AND (technique OR protocol* OR material* OR "calcium hydroxide" OR MTA OR
    "mineral trioxide aggregate" OR "resin-modified glass ionomer" OR RMGIC OR
    "hemorrhage control" OR hemostasis)

D  (pulp vitality OR "vitality testing" OR "sensibility test*" OR "electric
    pulp test*" OR EPT OR "cold test" OR "thermal test*") AND ("pulp exposure"
    OR "carious exposure" OR "traumatic exposure") AND (diagnosis OR assessment
    OR "clinical presentation" OR prognosis)
```

Tier filters: `cochrane` (journal), `level1` RCT/SR/MA, `level2`
CCT/prospective/comparative, `level3a` retrospective/cohort/longitudinal,
`level3b` case-control, `level4` case series/case reports, `level5`
review/editorial/comment/letter, `observational` cross-sectional/observational/
CBCT/imaging/anatomy/sens-spec.

**The vocabulary was not the problem.** Group C contains `partial pulpotomy`,
`hemostasis` and `hemorrhage control`. Sulaiman matches groups B *and* C. The
generator did its job.

---

## Step 3 — the mechanism, per paper

### Sulaiman 42388091 — the tier filter excludes it. This is the finding.

```
  passes the domain filter          yes
  matches topic group B             yes
  matches topic group C             yes
  admitted by cochrane              no
  admitted by level1                no
  admitted by level2                no
  admitted by level3a / 3b / 4      no
  admitted by level5                no
  admitted by observational         no
```

**Its only PubMed publication type is `Journal Article`.** Published 2026 Jul 2,
it has not yet been assigned a study-design type by MEDLINE indexing.

Every one of the 36 queries ANDs a tier filter, and no tier filter admits a bare
`Journal Article`. So a paper whose title carries **haemostasis time, partial
pulpotomy, outcome, cariously exposed, mature permanent** — five of the topic's
own terms — is **structurally unreachable by the live path**, and would remain so
however good the term generator became.

This is the answer to the batch's own framing: the generator produced the right
terms. The tier filter, not the query, is what excluded it.

### Komora 39117767 — admitted, then buried by relevance rank

Six conjunctions admit it (B and C × level1, level2, level5). Its best rank:

| conjunction | rank | of returned | query total |
|---|---|---|---|
| B + level5 | **219** | 300 | 300 |
| B + level1 | 347 | 366 | 366 |
| C + level5 | 349 | 608 | 608 |
| B + level2 | 445 | 486 | 486 |
| C + level2 | 453 | 904 | 904 |
| C + level1 | 459 | 511 | 511 |

Production takes the top **50** (100 for `observational`), sorted by
`sort=relevance`. Its best position is 4× below the cut.

**And it is already in the library** — `level1`, score 74.8 — so the library path
should have supplied it. It did not, and here is the exact stage and value:

```
  cosine similarity to "vital pulp therapy in adult teeth"   0.5807
  evidence_floor (app.py:1154)                               0.60
  cut by                                                     0.0193
  library rows more similar than it                          332
```

**The evidence floor removed it, by two hundredths.** A42 measured that floor as
"free — 18% of the pool, 1.1% of citations". Komora is in that 18%: a network
meta-analysis of 21 RCTs on materials, on a materials question, cut by 0.02.

That is not an argument to move the floor — the do-not-change list is explicit,
and one paper is not a basis. It is an argument that "free" was measured on
citation counts, not on whether any *specific* on-point paper was lost, and
those are different questions.

### EFCD-ESE-ORCA 42018467 — guidelines have no tier

```
  pubtypes                     Journal Article, Practice Guideline
  admitted by level5 only      rank 521 of 608
  admitted by every other tier no
```

**`practice guideline[pt]` and `guideline[pt]` appear in NO tier filter.** A
clinical practice guideline can therefore only ever be reached by accident,
through the `review[pt] OR editorial[pt] OR comment[pt] OR letter[pt]` bucket,
ranked among 608 reviews — and at 521 it is nowhere near the top 50.

This is the same structural hole A49 is about, seen from the retrieval side: the
tier ladder is a study-design hierarchy, a guideline is not a study design, and
so the ladder has no rung for it. The hardcoded `ingest_aae_guidelines.py`
records exist precisely because the live path cannot reach guidelines — a
workaround for this gap, which then introduced fabricated records at score 90.

---

## What this means for the fix

The batch is right that the fix differs by branch, and there are three:

1. **Sulaiman → the tier filter needs a path for un-typed papers.** Any recent
   paper is `Journal Article` only until MEDLINE indexes it, so the live path
   is currently blind to the newest literature on every topic. That is a
   general defect, not a VPT one, and it is the largest of the three.
2. **Komora → nothing needs changing in retrieval.** It is in the library and
   was cut by a shipped floor by 0.02. The question for RB is whether
   `evidence_floor` should have a rescue for a top-tier paper on the exact
   topic, which is `min_evidence_papers`' shape and not a floor change.
3. **EFCD-ESE-ORCA → this is A49 phase 1.** Guidelines need their own
   retrieval path because the tier ladder structurally cannot carry them.

**Hoang is unresolved** and nothing should be built on it until the PMID or DOI
is supplied.
