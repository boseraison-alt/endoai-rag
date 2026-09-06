# OVERNIGHT REPORT 9 — batch of 2026-09-07

**A49 phase 1: guidelines are citeable and visible; duplicates retired.**

Branch `night-20260906`, continuing. Tag `night-20260907-end`.
Suite: **2738 passed, 52 skipped, 1 xfailed, 0 failed** (baseline 2683 at the start of the night).
Total LLM cost: **$12.59**.

**Both gated items read NOT AUTHORISED.** Item F was skipped entirely. Item E
ran its five preconditions, which the batch marks as measurement, and applied
nothing.

---

## Phase 0

`091139d` pushed. Bundle `endo-ai-rag-20260906-night.bundle` verifies ("The
bundle records a complete history", HEAD `81664be`).
`db-20260906-night/endo_papers_rag.csv.gz` holds 3435 rows against 3435 live.
Fresh pre-A dump taken to `db-20260907-preA/` — 14 tables, 27,574 rows, every
table's dumped count re-read and matched.

---

## Per item

### Item A — retire the two Cochrane slug duplicates. **DONE**

Applied delta == dry run == prediction.

| | predicted | measured |
|---|---|---|
| rows retired | 2 | 2 |
| rows enriched | 2 | 2, both stay `cochrane`, scores 73.7 / 63.7 |
| inserts | 0 | 0 |
| tier changes | 0 | 0 |
| `cochrane` census | 21 | 21 |
| total raw rows | 3435 | 3435 |

The guideline census falls 81 → 79, and that is **not** a tier change: the two
retired rows keep `level_key='guideline'` and leave the *citeable* census
because they are now quarantined. Both numbers are reported so neither reads as
the other.

**Stored-answer impact: 0 of 207.** Measured before the write. The four
bare-accession matches are the `pages` field of the surviving PMID rows —
Cochrane article numbers *are* the journal's page field — not citations of the
rows being retired. Counting them would have overstated the blast radius
fourfold.

**THE FIRST DRY RUN RETIRED THREE ROWS, NOT TWO.** The third was `ESE-QG-2006`,
already quarantined by the A2 audit as `duplicate_of:17180780`. Re-retiring it
would have overwritten that reason with the same fact in different words and
broken the two tests that pin the exact string. An already-quarantined row is
now **terminal**, and the dry run retires exactly the predicted two.

Generalised, not patched: 11 `unconfirmed_pmid` records remain and each will
reach this path as its accession is verified. New nullable `redirect_to`;
`rewrite_redirected_citations` runs **before** G2 on both paths, because a
retired row is a quarantined row and G2's job is to drop those — without the
rewrite the retire would silently break stored citations instead of redirecting
them.

- `tests/test_rekey_redirect.py`, 16 tests. **Mutation check failed as required, twice**: removing the finaliser rewrite failed 1 (G2 logged the drop it causes); undoing the retire in the database failed 7. Restored by re-running the ingest, which retired only the one row still needing it.
- Commits `faefd67`, `2d3a9ce`, `9e42482`. Cost: ~$0.

**Two tests I did not touch failed, and neither was a regression** (rule 39):

1. `test_the_remaining_slug_rows_are_left_alone` — two of its own 30 fixtures
   were retired by the authorised write. Nothing left the library: each is
   reachable under its PMID. Repaired to follow `redirect_to` and assert what
   the invariant has always meant — *no document leaves the library*. Mutation:
   cleared `redirect_to`, making a document genuinely unreachable; failed.
2. `test_an_unparseable_identifier_is_emitted_as_given_and_loses_the_noun` —
   **not caused by anything tonight.** RB's own `091139d` rewrote the
   manifest's `supersedes` list, reordering it and adding PMIDs, so a
   hard-coded expected string went stale while every property the test is named
   for stayed true. `data/guidelines_seed.json` is untouched since `091139d`,
   which is how that is known rather than assumed. Repaired by deriving the
   expectation from the manifest the function reads. Mutation: made the notice
   call them statements after all; failed.

### Item B — `[[GL:<id>]]`. **DONE**

Five parts, each mutation-checked by running the mutated code: the context line
(`cite as [[GL:<id>]]` on any non-numeric row), the prompt sentence, the
finaliser render, G2 acceptance, and the PMID-slot rewrite.

**Two syntheses, and the rewrite counter is the instrument:**

| | GL markers the model wrote | guideline ids in a PMID slot |
|---|---|---|
| probe3-retreat-implant | 3 | **0** |
| retreatment-vs-microsurgery | 4 | **0** |

**0 on both** — the prompt is landing, and the rendered output is not being
manufactured by the rewrite. The Literature question is named rather than
picked by "most guideline rows": six of the 29 tied at 20 last night because 20
is the esearch retmax, not a pool size. `retreatment-vs-microsurgery` is chosen
from that tied set because its own named regression fixture *is* a guideline,
PMID 37772327.

**Stored-answer sweep: 22 of 209** carry a guideline id in a PMID slot.
`AAE-PS-diagnosis` ×18 and `AAE-PS-vital-pulp` ×12 are known ids and are
rewritten at serve time; the other eight payloads are the A2-quarantined
records and keep their existing handling. Served, `query_cache#2142`:

```
stored  ...foundational to the AAE classification of apical periodontitis
        [[PMID:AAE-PS-diagnosis]].
served  ...foundational to the AAE classification of apical periodontitis
        [GL:AAE-PS-diagnosis · Endodontic Diagnosis (2009)].
```

**THE SUITE CAUGHT TWO REAL REGRESSIONS IN MY OWN CHANGE**, neither a count
proxy, both losses of function, both fixed rather than repaired around:

1. **Idempotence.** Rendering `[[GL:id]]` to bare text meant the first pass saw
   an attribution and the second saw an uncited claim — the archive routes
   re-render on every read, so the same stored answer rendered differently
   every other time it was served. Fixed by rendering to `[GL: ...]`, a shape
   `_ANY_CITATION_RE` still recognises, exactly as it already accepts the
   reference list's `[PMID: n]`.
2. **The bibliography lost the guideline.** `assemble_bibliography` builds the
   reference list by scanning the served answer for ids, so a guideline was
   attributed in the prose and **absent from the references** — a clinician
   reading "the AAE position says X" and finding nothing to follow. Fixed twice
   over: the rendered form keeps the id, and `_extract_cited_pmids` now scans
   both marker shapes.

- `tests/test_gl_citation_form.py`, 15 tests. **Mutation checks failed as required** — five separate mutations, 1–3 failures each; and the two regression fixes were mutation-checked against the *existing* suite (3 and 5 failures).
- Commits `20e4cab`, `667b5e6`. Cost: **$8.70**, of which roughly half was spent twice — see Decisions.

### Item D — the document's own words. **DONE (time-boxed)**

**27 of 72 pointer rows** now carry the organisation's own summary, verbatim,
with `abstract_source='org_page'`, a fetched date, a sha256 over the stored
text, and the source URL. **45 stayed pointers and say why.**

| reason | rows |
|---|---|
| `http_403` | 29 (AAE 12, ESE/Wiley 8, ADA 2, …) |
| `bot_blocked` | 9 (ACP/Imperva 6, AAOM 3) |
| `no_extractable_text` | 7 |

Fetched: ADA 5, SDCEP 4, ACP 2, CGDENT 2, AAOMP 2, and one each for AAO, BES,
DHSC, FDSRCS, GDC, IADT, NICE, ASDA, AAOMS, AAP, AAPD, ASA.

**Two of my own bugs were in the first numbers**, both caught before reporting:
the first run returned 403 on all eight rows it tried — the headers were the
problem, not the sites; and I advertised `Accept-Encoding: br` in an
environment with no brotli, so one page "succeeded" with 75 words of mojibake
and was filed as `no_extractable_text`, blaming the page for my header.

- `tests/test_guideline_text_provenance.py`, 8 tests. **Mutation checks failed as required**: stripping `abstract_source` from a text-bearing row failed 2; editing stored `org_page` text after storage failed the hash check.
- `TestNothingIsParaphrased` still passes. Commit `792faf6`. Cost: $0.

### Item C — admission. **DONE; one done-when not met and cannot be**

| | before | after |
|---|---|---|
| questions where k cuts an eligible guideline | 8 / 32 | **0 / 32** |
| eligible rows cut by k | 19 | **0** |
| live cap / library cap | 4 / 25 | **25 / 25 (agree)** |

**Probe 3 now holds all three watched documents** — `ACP-ASYMPTOMATIC-EXTRACTION-2016`,
`ESE-S3-2023`, `AAE-TREATMENTSTANDARDS-2018` — against one of three last night.
The specialty section it produced:

> "The AAE Treatment Standards White Paper (2018, US) and AAE Endodontic Case
> Difficulty Assessment Form (2022, US) are both listed here as pointer records
> — position not quoted [GL:AAE-TREATMENTSTANDARDS-2018 · AAE — Treatment
> Standards White Paper … (2018; current; US)] … The ACP Position Statement on
> Extractions of Asymptomatic Natural Teeth … is also a pointer record —
> position not quoted … The ESE S3-level clinical practice guideline (2023, EU)
> … stresses that retreatment decisions should follow case evaluation of
> restorability, periodontal status, and correctable causes of prior failure
> [[PMID:37772327]]."

Two specialties named separately, never merged into "guideline bodies agree";
three pointer records declared unquoted; and the one record that **has** stored
text is the only one whose position is stated. Verified against the table:
those three are pointers (`bot_blocked` / `http_403`); 37772327 has a real
PubMed abstract.

**Both builders now agree, and they did not before.** `app.py` called
`flag_superseded_by_review` at three sites and neither `collapse_guideline_copies`
nor `admit_flagship_guidelines`, so on the library route a co-published
guideline was **still counted twice** — item E's fix from 2026-09-06 never
reached that builder — and a flagship was never admitted.

**FNF #4 from last night is explained**, and it is not top-k. Three repeat runs
of probe 2, same build, minutes apart: pool 5 holding IADT-FRACTURES-LUXATIONS-2020;
pool 5 holding both; pool 6 holding only ESE-TRAUMA-2021. `AAE-TRAUMA-2026`
appears in none. **The done-when "probe 2 holds both trauma guidelines" is NOT
met, and no admission rule can meet it** — the documents do not reliably reach
the candidate set, because `generate_search_terms` is non-deterministic and
every similarity moves with the boolean it writes. Item C only *adds* rows, so
it cannot be what removed them.

Flagship candidates I would propose to RB, not added: `AAE-TREATMENTSTANDARDS-2018`,
`BES-GOODPRACTICE-2022`.

- `tests/test_guideline_block_admission.py`, 14 tests. **Mutation checks failed as required**, three ways: restoring the cap of 4 (2 failures), removing the scope guard (1), making the flagship admission a no-op (3).
- Commits `01a4b66`, `657462f`. Cost: **$3.89**.

### Item E — reband stage 1. **NOT AUTHORISED**

Nothing applied, no baseline run, no row moved. Preconditions 1–5 done:

1. **Terminal statuses.** 16 retracted rows are now excluded before any
   derivation. The 2026-09-06 run would have moved two of them `retracted →
   level1`. `tests/test_reband_terminal_status.py`, 5 tests, **mutation check
   failed as required** (2 failures, including the behavioural one that runs
   the script and reads its output).
2. **Failed batch retried.** Not derivable **1280 → 1194**; would change
   437 → 446. The 86 were a dropped connection, not an untyped corpus.
3. **Three splits.** By direction: off-ladder 185, down 154, up 103, to
   guideline 4. Versus the abstract-extracted design: **disagree 208, no
   extraction 174, agree 64**. Full tier-pair table in
   `eval/reports/e_reband_stage1.md`.
   *The abstract split is the one to read first: the batch's own apply rule
   would move 238 rows, not 446.*
4. **Manifest candidates: 4**, not moved. `39743567` (Expert consensus on
   apical microsurgery) and `39487671` (IADT terminology for time elapsed from
   avulsion) look like real additions; RB decides.
5. **The gap explained.** 26.9% and 13.4% are different denominators, not
   different findings. The sample's 26.9% is 42/156 *decidable* rows. On the
   same denominator the dry run is 446/2113 = **21.1%**, and the residual is
   sampling error on n=156 — a 95% interval for 42/156 spans roughly 20–34%.
   Predicted 21% before running it.

Commit `7d55f52`. Cost: ~$0.

### Item F — fast-forward main. **NOT AUTHORISED.** Nothing done.

### Item G — blocklist and animal subjects. **DONE**

`data/off_domain_blocklist.json`, two entries, each with a reason, a date and a
judge. Applied on **both** builders and **every** lane — the live path before
the quality cut, and on the library route both to the candidate set (before the
coverage gate counts it) and to each tier bucket.

The AHA infective-endocarditis guideline is deliberately **not** listed:
prophylaxis before dental procedures is that document's whole subject, and
listing it would remake by hand the error the 2026-09-06 judge made and then
corrected. Distinct off-domain documents in the 32 pools was 4; the tail is 2,
well under the 10 at which the batch says the blocklist is the wrong tool.

**Animal subjects — measure only.** Input counted first: 3435 rows, 3339 with
≥20 words of abstract, 96 the detector cannot read.

| | |
|---|---|
| animal-subject rows detected | **81** |
| by tier | invitro 47, classic 19, level1 6, level2 4, level5 2, retracted 2, level3a 1 |
| distinct rows reaching any of the 29 pools | **24** |

**Six of the 24 sit on the human clinical ladder**: 26275599 and 38407663 at
level1; 25146016, 39484795, 39754111 at level2; and 40683315 at level5 —
*"Vital pulp therapy in dogs maintains an 80% success rate"*, which is the
exact defect class `animal_subjects.py` was written for, reaching an eval pool.
No fix: a species guard on the paper lanes is a retrieval change and needs its
own A/B. This number says that A/B is worth running.

- `tests/test_off_domain_blocklist.py`, 11 tests, **mutation check failed as required** (2 failures).
- Commit `ccdb488`. Cost: ~$0.

### Item H — rules and logs. **DONE**

Rules 38 and 39 added; rule 39 extended from "count" to "any literal". A53 log
with three overturned premises and five instrument errors. Commit `38bc3c8`.

---

## Found, not fixed

| # | severity | finding |
|---|---|---|
| 1 | **HIGH** | **`AAE-PS-vital-pulp` and `AAE-PS-diagnosis` carry model-written summaries stored as source text.** `ingest_aae_guidelines.py` says so itself — "Summaries are condensed from the official documents" — so `verify_citation_support` has been checking claims against a paraphrase. Now **labelled** `abstract_source='model_summary_legacy'`: countable, findable, impossible to add to silently, with a test pinning that these two are the only ones. Not quarantined, because the A2 audit kept them citeable for naming real documents. RB decides between re-fetching and quarantining. |
| 2 | **HIGH** | **Retrieval is not reproducible.** Three runs of one probe, same build, minutes apart, return different guideline pools (5, 5, 6 rows, three memberships). `generate_search_terms` is non-deterministic and every similarity moves with the boolean it writes. This is the cause of last night's FNF #4 and of probe 2's unmet done-when tonight. It also means **any pool-level A/B below the noise floor is uninterpretable** — now rule 38. |
| 3 | **HIGH** | **24 animal-subject rows reach the 29 eval pools, 6 on the human clinical ladder**, including a canine VPT study at level5. The live path has never called `detect_animal_subject`. |
| 4 | MEDIUM | **45 of 72 guideline pointers still have no text**, so the model can only say "position not quoted". 29 are `http_403` (AAE and Wiley refuse automated fetching outright). A licensed feed or manual capture is the realistic route. |
| 5 | MEDIUM | **`PUBTYPE_TO_LEVEL` is a third writer of `level_key`** and maps guideline publication types to `level1`. It predates the guideline tier. Rule 37 was written after finding only two writers. |
| 6 | MEDIUM | **208 of 446 proposed reband moves disagree with the abstract-extracted design.** The pubtype derivation is not self-evidently right; the batch's own apply rule would move 238. |
| 7 | LOW | Carried forward: `baseline_v7.json` stale; library floor PARKED; `main` 80+ commits behind. |

---

## Decisions taken, with the alternative rejected

| decision | alternative rejected |
|---|---|
| **An already-quarantined row is terminal in the re-key step**, so `ESE-QG-2006` keeps the A2 audit's `duplicate_of:` reason. | Retiring all three, which would have overwritten a tested reason string with the same fact in different words and broken two tests — and made applied ≠ predicted. |
| **Repaired two tests rather than stopping** (rule 39). Both were literals invalidated by authorised writes, one of them RB's own commit; both tests' stated intent still held and both repairs are strictly stronger. | Stopping the batch. Rejected because the batch's blocking condition explicitly exempts a test whose failure I can show is an authorised write breaking a proxy — and I showed it, with the pre-write dump and with `git log` on the manifest. |
| **Rendered `[GL: ...]` keeps the manifest id.** | The shorter `[Org — title (year)]`, which dropped the guideline out of the bibliography entirely — cited in prose, absent from the references. |
| **Labelled the two legacy paraphrases rather than quarantining them.** | Quarantining, which removes two real guidelines to fix a labelling problem; and leaving them unlabelled, which is the status quo the invariant exists to forbid. |
| **Flagship admission bypasses the similarity floor for a scope-matched, manifest-flagged, current record.** | Admitting "regardless of rank" only — which is a no-op, because the one flagship record measures *below* the floor on the probe it exists for. Scope intersection is the guard that keeps this from being a floor weakening. |
| **Did not add flagship flags to the manifest.** | Flagging `AAE-TREATMENTSTANDARDS-2018` and `BES-GOODPRACTICE-2022`, which would have made probe 3 look better and is explicitly RB's call. Listed as candidates instead. |
| **Item D time-boxed at 25 minutes per pass rather than 90.** | Spending the full 90 on hosts returning 403 within a second. Two passes were run instead: the second only retried failures, after fixing the two header bugs. |
| **Ran the item-B synthesis harness twice**, paying ~$4.35 twice. | Reporting the first run's numbers, which were measured on post-finalisation text and were self-contradictory ("0 markers written" beside "1 rendered"). |

---

## Every prediction, with its measurement

| # | prediction | measured | verdict |
|---|---|---|---|
| A | 2 retired, 2 enriched, 0 inserts, 0 tier changes, 3435 rows, cochrane 21 | all six exact | correct |
| A | 0 stored answers cite the slug keys | 0 of 207 | correct |
| B1 | PMID-slot slugs after rewrite = 0 on both syntheses | 0 and 0 | correct |
| B2 | stored answers with a guideline id in a PMID slot: 1–5 | **22** | **WRONG by count.** I anchored on the single probe answer found last night and forgot the 170-file `answers/` corpus, which predates the guideline ingest entirely. |
| D | pointer rows with a URL: 40–50 | **72** | **WRONG by class.** I counted the ~45 slug-keyed records and forgot that PMID-keyed records the library did not already hold were *also* inserted as pointers. |
| D | fetch success below half | 27 / 72 = 38% | correct |
| C4 | k cuts an eligible row on a majority of the 32 | **8 of 32 (25%)** | **WRONG by count**, and the direction matters: the cap was a smaller problem than the item assumed. |
| C5 | `ESE-S3-2023` is above the floor on probe 3 but not admitted | above the floor by 0.0095 on one run, **below it on another, absent from the KNN on a third** | **WRONG by class.** The premise was that admission was the binding constraint. It is variance. |
| E6 | changed rows fall by exactly 2 (the two retracted) | 437 → 446, and **16** retracted rows now terminal | **WRONG by class.** I predicted a subtraction; the batch retry *added* 86 decidable rows, and the terminal guard protects 16 rather than 2 — the two were only the ones that would have *moved*. |
| E7 | "not derivable" shrinks by up to 100 | 1280 → 1194 (−86) | correct |
| E8 | the gap resolves to ≈21% on a common denominator | 446/2113 = **21.1%** | correct |
| G9 | off-domain tail ≤ 10, so the blocklist is the right tool | 2 | correct |
| G10 | animal rows 20–80; fewer than 10 reach a pool | **81** and **24** | **WRONG by count on both.** The second is the one that matters: 24 reach pools, 6 on the clinical ladder. |

---

## Suite

```
2738 passed, 52 skipped, 1 xfailed in 482.28s
```

The night began at **2683 passed** (the first full run, after item A's writes
and before its test repairs). +55 tests: 16 re-key/redirect, 15 GL citation
form, 8 text provenance, 14 block admission, 11 blocklist, 5 reband terminal
status = 69 new, less the ones already counted in the 2683 baseline run and the
two literal assertions replaced by property assertions.

**Two intermediate runs failed and both were fixed rather than repaired
around**, which is the part worth keeping:

- after item B, 7 failures — my GL rendering broke idempotence and dropped
  guidelines out of the bibliography. Both were losses of function, not count
  proxies.
- after item C, 5 failures — `KeyError: 'citations'`, because a flagship-
  admitted row was not shaped like every other scored row.

Only two failures all night were rule-39 repairs, and one of those was caused
by RB's own manifest commit rather than by anything in this batch.

---

## Merge to main — NOT DONE

Item F reads **NOT AUTHORISED**, so no fast-forward was attempted and no tag
was created for it. `main` remains 80+ commits behind `night-20260906`; that gap
is unchanged from last night and still needs RB's decision.

---

## Backups

**Database dump — verified.**

```
C:\Users\boser\endo-ai-backups\db-20260907-night\
all 14 tables verified, 27579 rows
```

A pre-item-A dump was also taken before any write tonight:
`db-20260907-preA/`, 14 tables, 27,574 rows, all verified. That is the restore
point for item A.

**Git bundle — verified.** Path and verification line below.

---

## `git log --oneline main..night-20260906`

Tonight's commits (the branch also carries the 80 pre-existing
`fix/retrieval-blindspot` commits, unmerged to `main` since 2026-09-03):

```
a086e7b Item C: shape a flagship-admitted row like every other scored row
38bc3c8 Item H: rules 38 and 39, and the A53 logs
7d55f52 Item E: NOT AUTHORISED. Preconditions 1-5 done; nothing applied.
ccdb488 Item G: the off-domain blocklist, and the animal-subject count
657462f Item C: the guideline block admits every current guideline, and flagships always
01a4b66 Item C: the admission measurement, and the hypothesis is overturned
792faf6 Item D: the document's own words for pointer records
667b5e6 Item B: the rendered GL citation keeps its id, and the bibliography sees it
20e4cab Item B: [[GL:id]], the citation form for guideline records
9e42482 Item A: repair the two tests the authorised write invalidated (rule 39)
2d3a9ce Item A: retire re-keyed slug rows, and redirect their citations
5a032b0 A46: predictions for the 2026-09-07 batch, committed before any write
faefd67 Item A: measure who cites the Cochrane slug rows, before retiring them
```

