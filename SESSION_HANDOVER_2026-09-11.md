# SESSION HANDOVER — 2026-09-06 (seed-extension ingest) → next

Boot a new coding-agent chat with:

> Read `AGENT_QUEUE.md`, `SESSION_HANDOVER_2026-09-11.md` and
> `HANDOVER_GUIDELINES_2026-09-04.md`. Continue from the ORDER section below.

**Branch `fix/retrieval-blindspot`, HEAD `b64b0c7`, pushed.**
Suite **2626 passed, 52 skipped, 1 xfailed, 0 failed** (measured 2026-09-06
23:25, with the extended manifest on disk and the ingest NOT applied).
Working tree clean.

---

## 0. READ THIS BEFORE ANYTHING ELSE — TWO THINGS ARE WAITING

### (a) The ingest is BLOCKED on a decision, not on a bug

`data/guidelines_seed.json` is at 99 records (commit `6444752`) and **has not
been ingested**. The dry run hit a stop condition the batch wrote, and the stop
condition's stated premise is false. **Nothing was applied. The database is
untouched.** See §2 — it needs one line from RB either way.

### (b) A retrieval regression I shipped on 2026-09-05 is LIVE IN PRODUCTION

The guideline lane is pulling out-of-domain guidelines into endodontic answers —
a vascular-surgery guideline into an avulsion pool, a **feline veterinary**
dental guideline into a human crown-fracture pool. Severity HIGH, mechanism
fully diagnosed, fix not attempted. See §4. **If you only do one thing, do this
one** — it degrades live answers today, whereas the ingest only withholds an
improvement.

---

## 1. STATE

- **Ports unchanged for nine sessions.** 5000 is ours (pid 49800). **5003 is
  another session's (pid 27692) — never kill it, never use it.**
- **Run the suite BARE** (`python -m pytest`). `pytest.ini` sets
  `testpaths = tests presentations`; naming `tests/` silently drops 126 guards.
- **Database untouched this session**, verified after the dry run rolled back:
  3,405 rows; citeable guideline 55, level1 1362, level2 338.
- **Backups, both verified:**
  - `C:\Users\boser\endo-ai-backups\endo-ai-rag-20260905-2305.bundle`
  - `C:\Users\boser\endo-ai-backups\db-20260905-2305\` — 14 tables,
    **27,281 rows**, taken before the dry run.
- **The demo cache is still void.** Prompt and retrieval have both moved since
  anything was warmed.

---

## 2. THE DECISION: authorise the ingest, or not

### What the dry run says

```
will RECLASSIFY existing    61      (52 idempotent re-applications + 9 real)
will INSERT new             30
will ENRICH only (studies)   8      tier/score untouched
quarantined on ingest        5      withdrawn / draft
marked superseded           13
```

| tier | before | after | delta |
|---|---|---|---|
| guideline | 51 | 81 | **+30** |
| level1 | 1362 | 1361 | **−1** |
| level2 | 338 | 330 | **−8** |
| all others | | | +0 |

### Why it stopped

The batch said: stop if any row in `{cochrane, level1, level2}` is marked for
reclassification, because *"the PMID is wrong on our side"* — and prescribed
quarantining the manifest record.

**Nine rows matched, all IADT trauma guidelines, and the premise is false.**
Each was checked against the stored row: every one is genuinely the IADT
guideline the manifest names, in *Dental Traumatology*, title matching.

| PMID | record | tier | score | IF |
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

**The PMIDs are right; our banding is wrong.** `fetch_papers` stores
`level_key = eff_level`, *"the tier this paper was retrieved under"* — so a
guideline that answers a level2 lane's query is stored as level2. This is
exactly what the manifest's own `ingest_notes` predict.

### Why it matters

- **PMID 32472740 sits at `level1` — "Level I — RCTs and Systematic Reviews"** —
  at score 54.8, and the system prompt tells the model to trust the tier label
  absolutely. A consensus guideline is presentable as a systematic review.
- **Five of the nine are superseded** (2012 trio, two 2007 papers) sitting on
  the evidence ladder with no supersession notice — the hazard the manifest
  exists to prevent.
- All nine carry `impact_factor = 3.0`, a forbidden signal (invariant 11).
- The defect is **already realised once**: PMID 32475015 is cited in a stored
  answer while banded `level2` at score 47.0.

### The two options

**Option A — authorise (recommended).** Run
`python scripts/ingest_guidelines_seed.py --apply`. Reclassifies the nine to
`guideline` with NULL score, strips their impact factor, moves five superseded
documents off the ladder, inserts 30 new records. Then `python -m pytest`
(bare) — `tests/test_guideline_seed.py` must be green, and
`test_the_cochrane_tier_did_not_shrink` in particular; if it fails, the ingest
demoted a review — stop and restore from `quarantine_reason`.

**Option B — follow the batch literally**: quarantine the nine manifest
records, null their PMIDs. **I recommend against it.** It discards nine
accessions verified on PubMed on 2026-09-06 to protect against a fault that is
not present, and leaves nine guidelines on the evidence ladder.

The other two stop conditions do **not** fire: all 13 `superseded_by` targets
resolve inside the manifest, and rows that actually change tier number 9 (the
"61" is 52 idempotent re-applications of the original 60 records).

**Woo 2006 does not arise.** PMID 16702591 is not in the paper table — it is in
*Annals of Internal Medicine* and cannot pass `ENDO_DOMAIN_FILTER`. The
judgement call the batch flagged never came up.

---

## 3. THE ONE THING TO CARRY FORWARD

**A recall metric reported as if it were precision.**

On 2026-09-05 I broadened the guideline lane's query and reported *"empty rate
79% → 3%, 22 questions gain a guideline, 0 lose one"* as a clean win. Every one
of those numbers is true. **They all measure whether the lane returned
something. None asks whether what came back was the right document.**

It took a probe that looked at *what* was in the pool — not *how much* — to see
that the lane was returning a vascular-surgery guideline for an avulsion
question. **When a change is meant to improve relevance, a count of results is
not evidence; only a check of the results is.**

This is the same family as the project's other instrument errors, and it is the
second time in two days I built on an assumption about `_COVERAGE_GENERIC`
without reading it.

---

## 4. THE REGRESSION — diagnosed, not fixed. Severity HIGH.

`endo_ai.guideline_topic()` picks which AND-group of the generated query the
guideline lane should use. It selects by **generic share**, tie-broken by
length. Measured across all 29 eval questions:

- **10 of 29** have no group with generic vocabulary, so **length decides**.
  Usually fine (`mta OR biodentine…`), but `dens-evaginatus-premolar-diagnostic`
  picks **`tooth #20 OR maxillary right first molar…`** — a tooth identifier.
- **~6 of the other 19** select the **outcome** group:

| question | what the lane now queries |
|---|---|
| naocl-concentration | `efficacy OR outcome* OR success OR disinfect* OR treatment` |
| regenerative-immature | `success OR survival OR outcome* OR efficacy` |
| dens-invaginatus | `management OR treatment OR therap* OR clinical approach` |
| case-opening-sparse | `tooth OR teeth OR dental OR odontogenic` |
| dens-evaginatus-prevention-followup | `prevent* OR manag* OR treatment OR therap*` |
| avulsion (probe) | `timing OR dry time OR extra-alveolar time OR delay* OR prognosis` |

**Root cause.** I assumed `_COVERAGE_GENERIC` encodes "the endodontic subject".
It encodes *vocabulary with no discriminating power* — built for the coverage
gate — and mixes domain nouns (`root canal`, `pulp`) with research nouns
(`outcome`, `efficacy`, `success`, `treatment`, `management`, `tooth`,
`dental`). Selecting **for** it selects for the outcome group about a fifth of
the time.

**Why it reaches out of domain.** With the topic reduced to `(timing OR
prognosis)` or `(tooth OR teeth OR dental)`, **`ENDO_DOMAIN_FILTER` becomes the
only discriminator left** — and it was designed as a floor, not a selector. One
matching term is enough. Verified against PubMed:

```
Society for Vascular Surgery guideline   matched via periapical[tiab]
FelineVMA feline dental guideline        matched via endodontic*[tiab]
```

Both matches are *correct*. The filter is doing its job; the topic is not.

**Compounding it:** the 2026-09-05 prompt change hands these documents to the
model under a heading stating they are *"what a professional body has formally
stated"*.

### Suggested direction (not measured, not a recommendation)

Rank groups by **domain nouns only** — a subset of `_COVERAGE_GENERIC` with the
research vocabulary removed — rather than by the whole set; or keep two
AND-groups instead of one, which preserves some discrimination while staying
broader than a trial-shaped conjunction. **Whichever is tried needs a PRECISION
measurement**, which is the thing the original change lacked: for each of the 29
questions, is the top returned guideline actually about that question?

---

## 5. FOUND, NOT FIXED — full list, worst first

1. **The guideline-lane regression.** §4. HIGH. Live in production.
2. **Nine IADT guidelines banded as level1/level2 evidence.** §2. HIGH. Fixed by
   the ingest the moment it is authorised.
3. **18 real guideline documents cannot be cited on the library route.** AAE
   position statements, SDCEP, NICE, CGDent: `confirmed` documents PubMed does
   not index, so no PMID exists and the prompt's `[[PMID:n]]` requirement
   excludes them. Needs a citation form (A49 phase 1's `guidelines` table with
   `ORG-TOPIC-YEAR`), not a retrieval change. Test-pinned at exactly 30 slug
   rows so nobody quietly re-keys or quarantines them.
4. **One document, three PMIDs.** `42017497` and `42014635` are the
   EFCD-ESE-ORCA deep-caries guideline co-published in two journals and **both
   reached the same pool**, while the manifest keys it by a third accession
   (`42018467`). PRISMA dedup works on PMIDs and cannot see this. MEDIUM.
5. **The library floor.** Still PARKED; needs the two-guard design
   (`eval/reports/library_floor_29.md`). Needs RB.
6. **`baseline_v7.json` is stale.** Retrieval changed twice (guideline query,
   D1 recency exemption) and the prompt changed. A re-baseline needs a
   prediction that **names its reference baseline and date** (rule 35).
7. **~10.4 s embedding-model load** on cold live-only processes, from the PRISMA
   similarity backfill. One-off per process. Known, low.
8. The extractor's ~77% recall; the Komora xfail. Both long-standing.

---

## 6. DECISIONS THIS SESSION, WITH THE ALTERNATIVE REJECTED

| decision | alternative rejected |
|---|---|
| **did not apply** the ingest | applying on my own judgement — the instruction was explicit and it is a DB write on citeable clinical rows |
| **did not quarantine** the nine manifest records | the batch's literal remedy, which is written for a wrong-PMID case that did not occur |
| reported the stop rule's premise as **false** | reporting "stop condition fired" and leaving the reader to assume the PMIDs were bad |
| **did not fix** the guideline-lane regression | fixing it inside a batch already stopped on an unrelated matter — two changes at once, neither attributable (rule 22) |
| reported "61 rows" **both ways** | quoting only the 9 that change tier, which is the convenient reading |
| ran the trauma probes as a **before** measurement | skipping them because the after half was unavailable |

---

## 7. ORDER FOR THE NEXT SESSION

1. **Fix the guideline-lane regression (§4).** Before/after across the 29 with a
   **precision** metric — is the top returned guideline about the question? Two
   named regression fixtures already exist and must keep passing: PMID
   **37772327** (retreatment vs apical microsurgery) and **26990236** (immature
   teeth). Add two new ones from this session's probes: an avulsion question
   must reach an IADT avulsion guideline and must **not** reach a
   vascular-surgery or veterinary guideline.
2. **Decide the ingest (§2).** If authorised: `--apply`, bare `pytest`, then the
   two measurements the last batch could not complete —
   (a) trauma recall: do `IADT-AVULSION-2020` / `IADT-FRACTURES-LUXATIONS-2020`
   reach an avulsion and a crown-fracture pool, and do `AAE-TRAUMA-2026` /
   `ESE-TRAUMA-2021` appear alongside them, with the three superseded IADT
   documents suppressed; (b) specialty divergence: does a "failed retreatment,
   patient wants an implant" case surface `ACP-ASYMPTOMATIC-EXTRACTION-2016`
   **next to** the ESE-S3 / AAE tooth-preservation position and **label them as
   two specialties' positions** rather than blending them.
   *Both halves must appear in the report — the before half is already in
   `eval/reports/a49_seed_extension_ingest_part2.md`.*
3. **Re-baseline (§5.6).** Only after 1 and 2 settle; otherwise it measures a
   moving target. Prediction first, naming `baseline_v7` and its date.
4. **A citation form for the 18 non-indexed guidelines (§5.3).** This is also
   A51's precondition — its guideline-versus-evidence divergence check cannot
   compare what the answer cannot cite.
5. Re-warm the demo cache.

---

## 8. REPLAY — every number in this handover

```
python scripts/ingest_guidelines_seed.py                  # DRY RUN; --apply to write
python scripts/measure_guideline_lane_query.py            # the recall-only metric
python -m pytest                                          # BARE
python scripts/dump_db.py <outdir>
```

Reports: `a49_seed_extension_ingest.md` (predictions, committed first),
`a49_seed_extension_ingest_part2.md` (measurement, the stop condition, the
regression), `guideline_lane_query.md`, `a49_lane_headings_ab.md`,
`guideline_slug_ids.md`, `early_stop_recency.md`,
`a46b_baseline_v7_outcome.md`, `library_floor_29.md`.
