# A49 seed extension — measurement (part 2 of the ingest report)

Continues `a49_seed_extension_ingest.md`, whose predictions were committed
before any of this was run.

---

## Step 2 — the dry run. **STOPPED. NOT APPLIED.**

```
will RECLASSIFY existing    61      (52 idempotent re-applications + 9 real)
will ENRICH only (studies)   8      tier/score untouched
will INSERT new             30
keyed by manifest id        49      never emitted as [PMID:N]
quarantined on ingest        5      withdrawn / draft
marked superseded           13
```

### Delta by tier

| tier | before | after | delta |
|---|---|---|---|
| **guideline** | 51 | 81 | **+30** |
| **level1** | 1362 | 1361 | **-1** |
| **level2** | 338 | 330 | **-8** |
| every other tier | | | **+0** |
| TOTAL | 3344 | 3365 | +21 |

### The stop condition that fired

> *"A row with `level_key` in `{cochrane, level1, level2}` marked for
> reclassification... **the PMID is wrong on our side.** Quarantine the manifest
> record... rather than reclassifying the paper."*

**Nine rows, all IADT trauma guidelines:**

| PMID | manifest record | current tier | score | IF |
|---|---|---|---|---|
| 32472740 | IADT-INTRO-2020 | **level1** | 54.8 | 3.0 |
| 32475015 | IADT-FRACTURES-LUXATIONS-2020 | level2 | 47.0 | 3.0 |
| 32460393 | IADT-AVULSION-2020 | level2 | 47.0 | 3.0 |
| 32458553 | IADT-PRIMARY-2020 | level2 | 47.0 | 3.0 |
| 22230724 | IADT-FRACTURES-LUXATIONS-2012 | level2 | 37.0 | 3.0 |
| 22409417 | IADT-AVULSION-2012 | level2 | 38.1 | 3.0 |
| 22583659 | IADT-PRIMARY-2012 | level2 | 38.1 | 3.0 |
| 17511833 | IADT-AVULSION-2007 | level2 | 38.1 | 3.0 |
| 17635351 | IADT-PRIMARY-2007 | level2 | 38.1 | 3.0 |

**THE RULE'S PREMISE DOES NOT HOLD, AND THAT IS THE FINDING.** The rule assumes
a level1/level2 match means we matched the wrong paper. Checked against the
stored rows: every one of the nine is genuinely the IADT guideline the manifest
names, in *Dental Traumatology*, title matching. **The PMIDs are right. Our tier
banding is wrong.**

The mechanism is in our own write-back: `fetch_papers` stores
`level_key = eff_level`, *"the tier this paper was retrieved under"*. A
guideline retrieved by the level2 lane is stored as level2. This is exactly what
the manifest's own `ingest_notes` predict:

> *"Several of these ARE PubMed-indexed and will therefore already be entering
> the corpus as if they were primary studies. Ingesting this manifest must
> DEDUPE against the existing paper table by PMID and reclassify those rows."*

So the prescribed remedy — quarantine the manifest record, null the PMID —
**would be wrong and destructive**: it would discard nine accessions verified on
PubMed on 2026-09-06 to protect against a fault that is not present, and leave
nine guidelines sitting on the evidence ladder.

**I have not applied, as instructed.**

### The other two stop conditions

- **`superseded_by` targets:** all 13 resolve inside the manifest. **Does not fire.**
- **"More than 12 rows marked":** 61 literally, but 52 are idempotent
  re-applications of the original 60 records (already `guideline`, score NULL).
  Rows that actually change tier: **9**. On the rule's stated intent — *"the
  paper table already holds much more of this material than predicted"* — it
  **does not fire**. Reported both ways rather than picking the convenient one.

### Severity, concretely

- **PMID 32472740 is banded `level1` — "Level I — RCTs and Systematic
  Reviews"** — at score 54.8. The system prompt instructs the model to trust the
  tier label absolutely, so a consensus guideline is currently presentable as a
  systematic review.
- **Five of the nine are superseded** (the 2012 trio and two 2007 papers),
  sitting at level2 as ordinary evidence with no supersession notice — the exact
  hazard this manifest exists to prevent.
- All nine carry `impact_factor = 3.0`, a forbidden signal (invariant 11),
  because they entered through the paper channel.

### Woo 2006 — the judgement call the batch flagged

**Not applicable: PMID 16702591 is NOT in the paper table.** It is in *Annals of
Internal Medicine* and `ENDO_DOMAIN_FILTER` requires an endodontic MeSH/tiab
term. No overrule needed.

### A caution on a looser count

A title sweep for "guideline / position statement / consensus" among rows banded
off the guideline tier returns **17**. That is a hypothesis, not a finding: it
includes `36920339` ("Systematic review of clinical practice guidelines for
trauma"), which is a systematic review **about** guidelines and correctly sits at
level1, plus two commentaries on the IADT guidelines. **The nine matched by PMID
against the verified manifest are the solid set.**

---

## Step 1 predictions vs measurement

| # | prediction | actual | verdict |
|---|---|---|---|
| P1 | 2-6 already in the paper table (batch: 3-8) | **9** | **both wrong, mine wronger** |
| P2 | Woo 2006 absent; IADT series present | Woo absent; 9 of 10 IADT present (17367451 absent) | **correct** |
| P3 | hits sit at `guideline` or `level5` | **`level1` and `level2`** | **WRONG BY CLASS** |
| P4 | no stop condition fires | one fired | **wrong** |

### Overturned premise — P3, logged under rule 21

**Premise:** *"`level_key` was backfilled from PubMed publication types, so a row
whose pubtype is `Practice Guideline` should have been banded `guideline`."*

**Killed by:** all nine hits sit at level1/level2; none at `guideline` or
`level5`.

**Why it was wrong:** the pubtype backfill is not the only writer of `level_key`
and it is not the last one. **Live write-back stores the tier the paper was
RETRIEVED UNDER.** A guideline that answers a level2 lane's query is written back
as level2. I reasoned from the backfill and forgot the write-back, which is the
larger and more recent writer.

**Worth keeping:** *when two mechanisms write the same column, the one that runs
most often decides what the column means.*

---

## Step 4.1 — the withdrawn/superseded sweep

**ZERO.** 238 stored answers swept (20 `query_cache` rows + 218 answer files).
No citation to any of the seven newly-superseded PMIDs, nor to either superseded
ADA sedation id.

**Rule 34 — the input the zero guards, measured:**

| | |
|---|---|
| files carrying at least one PMID citation | **217 of 218** |
| distinct PMIDs cited overall | **927** |
| files mentioning trauma vocabulary | **50** |
| citations to the **current** IADT 2020 series | **1** (PMID 32475015) |

A real *matches-nothing*, not a *fires-never*: the corpus cites heavily, does
discuss trauma, and does cite an IADT guideline — the current one.

**That single citation is the defect realised.** PMID 32475015 was cited while
banded `level2` at score 47.0 — an IADT consensus guideline presented to a
clinician as Level II prospective-study evidence.

---

## Step 4.2 / 4.3 — trauma recall and specialty divergence: BEFORE only

The after half needs the apply. The before half surfaced something unrelated and
worse.

| probe | pool | guideline tier | watched documents reached |
|---|---|---|---|
| avulsion, 40 min dry time | 61 | 4 | **none** |
| complicated crown fracture | 67 | 4 | **none** |
| failed retreatment -> implant | 68 | 4 | **none** |

No IADT guideline — current or superseded — reached any pool. `AAE-TRAUMA-2026`,
`ESE-TRAUMA-2021` and `ACP-ASYMPTOMATIC-EXTRACTION-2016` are absent as expected
(not yet ingested).

### What the guideline tier contained instead

| probe | guideline-tier contents |
|---|---|
| avulsion | ESE-S3-2023 · EFCD deep caries (42017497) · EFCD deep caries **again** (42014635) · **"The Society for Vascular Surgery practice guidelines..."** |
| crown fracture | ESE-S3-2023 · EFCD deep caries · **"2025 FelineVMA feline oral health and dental care guidelines"** · AAPD VPT |
| divergence | ESE-S3-2023 · ADA/AAOMR patient selection · ESE antibiotics · an IADT-titled commentary |

---

## FOUND, NOT FIXED — a regression I shipped yesterday. Severity: HIGH.

**The guideline lane's broadened topic selects the wrong concept group, and
yesterday's measurement was blind to it.**

Yesterday I changed the lane to query the *subject group* rather than the full
conjunction and reported **empty rate 79% -> 3%, 22 questions gain a guideline,
0 lose one.** That counted **whether the lane returned something.** It never
asked **whether what came back was the right document.** A recall metric,
reported as though it were precision.

Measured now across all 29 questions — which group the rule actually picks:

- **10 of 29** have no group with generic vocabulary, so the **length tiebreak**
  decides. Usually it picks a sensible subject (`mta OR biodentine...`,
  `laser* OR pdt OR pips...`), but on `dens-evaginatus-premolar-diagnostic` it
  picks **`tooth #20 OR maxillary right first molar...`** — a tooth identifier.
- **On about 6 of the other 19 the generic-share rule actively selects the
  OUTCOME group:**

| question | group the lane now queries |
|---|---|
| naocl-concentration | `efficacy OR outcome* OR success OR disinfect* OR treatment` |
| regenerative-immature | `success OR survival OR outcome* OR efficacy` |
| dens-invaginatus | `management OR treatment OR therap* OR clinical approach` |
| case-opening-sparse | `tooth OR teeth OR dental OR odontogenic` |
| dens-evaginatus-prevention-followup | `prevent* OR manag* OR treatment OR therap*` |
| avulsion probe (above) | `timing OR dry time OR extra-alveolar time OR delay* OR prognosis` |

**My error was in what I assumed `_COVERAGE_GENERIC` encodes.** I read it as
"the endodontic subject". It is actually "vocabulary with no discriminating
power" — built for the coverage gate — and it mixes domain nouns (`root canal`,
`pulp`) with research nouns (`outcome`, `efficacy`, `success`, `treatment`,
`management`, `tooth`, `dental`). Selecting *for* it selects for the outcome
group about a fifth of the time. **This is the second assumption I have made
about that helper without checking it, in two days.**

**Why it produces out-of-domain results.** With the topic reduced to
`(timing OR prognosis)` or `(tooth OR teeth OR dental)`, **`ENDO_DOMAIN_FILTER`
becomes the only discriminator left** — and it was designed as a floor, not a
selector. One matching term suffices. Verified directly against PubMed:

```
Society for Vascular Surgery guideline  matched via periapical[tiab]
FelineVMA feline dental guideline       matched via endodontic*[tiab]
```

Both matches are *correct*. The filter is doing its job; the topic is no longer
doing any.

**Net:** the lane went from 86% empty and on-topic to 3% empty and frequently
off-topic — and yesterday's prompt change hands those documents to the model
under a heading saying they are *"what a professional body has formally
stated"*. A feline veterinary guideline in a human crown-fracture answer is a
worse failure than an empty lane.

**Not fixed here:** it is a retrieval change, this batch's stop condition has
already fired on an unrelated matter, and fixing two things at once would make
neither attributable (rule 22). It needs its own before/after with a
**precision** metric — the one yesterday lacked.

**Also found:** `42017497` and `42014635` are both the EFCD-ESE-ORCA deep-caries
guideline, co-published in different journals, and **both reached the same pool**
— while the manifest keys that document by a third accession, `42018467`. One
document, three PMIDs, two in one answer. PRISMA dedup works on PMIDs and cannot
see this.

---

## RECOMMENDATION

1. **Authorise the ingest.** The stop condition fired on a premise that does not
   hold: the PMIDs are verified and correct, and it is our banding that is wrong.
   Reclassifying the nine IADT rows to `guideline` with a NULL score is the
   manifest's stated intent, strips `impact_factor` from nine rows, and takes
   five superseded documents off the evidence ladder.
2. **Do not quarantine the nine manifest records.** That remedy is written for a
   wrong-PMID case which did not occur.
3. **Treat the guideline-lane regression as the next item**, ahead of the rest of
   A49 phase 1. It is live in production now.
