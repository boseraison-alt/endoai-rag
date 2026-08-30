# Handover — endo-ai-rag

A clinical endodontics RAG assistant. It retrieves primary literature from a
Neon/pgvector library or live PubMed, scores each paper, bands it by study
design, and asks Claude to synthesise an answer that cites only what it was
given. The product's entire claim is that the citations are real and the
evidence strength is honestly labelled.

Read `docs/architecture.html` for the system layout. This file covers what the
architecture diagram cannot: the failure modes this codebase actually has, and
why the tests are shaped the way they are.

---

## The four recurring bug classes

Every serious bug this codebase has shipped is an instance of one of these
four. Each entry gives a one-line detector — the question to ask of any diff —
and the test file that guards it.

### (a) A tier label trusted from a stored column

**Detector: any read path that uses `level_key` without asking where it was
written.**
**Guard: `tests/test_end_to_end.py` (banding assertions, unlabelled-row
fixture) plus the audit scripts (`scripts/audit_laser_run.py`,
`scripts/reclassify_by_pubtype.py`, `scripts/rescore_library.py`).**

`level_key` is written into the library at ingest and read back verbatim, and
it drives the design axis at 39% weight — so every writer's bug becomes every
reader's bug, silently. A retrieval-time fix protects new rows only; existing
rows keep the wrong tier forever. The Cochrane fix needed a code change *and*
a 109-row migration (`scripts/fix_cochrane_tier.py`) *and* a rescore. The
score-banding workaround in `app.py` was the same class from the other side:
it promoted papers across tiers by score because 37% of rows had no
`level_key` to trust.

**Any change to how a tier is assigned needs a matching migration. Take a
backup table first — the first Cochrane migration did not, and the identity of
the 109 affected rows is now unrecoverable.**

### (b) Untagged or annotated terms in PubMed queries

**Detector: any query term without a field tag (`[pt]`, `[tiab]`, …) or with
trailing text after the tag.**
**Guard: `tests/test_tier_filter_syntax.py` (offline half rejects untagged
terms, trailing commentary and unbalanced quoting; network half sends each
filter to esearch under `RUN_NETWORK_TESTS=1` and fails on anything landing
in `[All Fields]`).**

PubMed does not reject a malformed query. It guesses, and it tells you what it
guessed only if you ask for `querytranslation`. Four instances so far:

| String | What PubMed actually ran |
|---|---|
| `randomized controlled trial[pt] less quality` | `... AND less AND quality` — gutted Level II |
| `Cochrane Review[pt]` | `("cochran" OR "cochrane") AND Review[pt]` — matched every SR that mentions the Cochrane Library |
| `expert opinion` (untagged) | All-Fields match, ORing in any paper containing the phrase |
| bag-of-words module topics | six words ANDed together — 1 hit in all of PubMed |

All four looked correct in code review. The network half found the `expert
opinion` bug on its first run, before anyone knew it existed — which is the
argument for the whole category of test that asks an external system what it
understood rather than asserting on the string you sent.

**If you add or edit a tier filter, run the network tests.**

### (c) Metadata computed on a batch, applied per paper

**Detector: any classifier called once per efetch batch whose result lands on
individual papers.**
**Guard: `tests/test_coi_scoping.py` (and the batch-shaped fixtures in
`tests/conftest.py`, which always test extraction inside a batch of
different-shaped papers, never on a single paper alone).**

efetch returns many `PubmedArticle` records in one XML document. Anything that
runs on "the response" instead of "the record" — a COI classifier, a pubtype
extractor, a MEDLINE-status check — stamps one paper's answer onto the whole
batch. The COI detector shipped exactly this way: it passed its unit tests
(single-paper fixtures) while 9 of 10 flagged papers in production were false
positives; only a hand spot-check of real `CoiStatement` values caught it.

For anything that classifies text, build fixtures from production data before
trusting the suite.

### (d) A check that fails open and shows nothing

**Detector: any guard whose failure branch produces no user-visible output.**
**Guard: the citation-support-status test in `tests/test_end_to_end.py`
(`test_citation_support_status_is_stated` — the answer must state the check's
outcome, including "not available", never silence).**

A validation that catches nothing and says nothing is indistinguishable from a
validation that ran clean. Instances: the clarify gate swallowing exceptions
and proceeding, the citation-support check whose absence looked identical to a
pass, and — before this pass — an admin-auth design where an unset token would
have meant "no auth" instead of "no access". The rule now enforced in
`app.py`: a disabled or failed check must return an explicit refusal (admin
routes 403 when `ADMIN_TOKEN` is unset; X-ray uploads are rejected when
metadata stripping fails) or an explicit "not available" in the output.

### Related lesson: trusting a PubMed field that is only populated for some records

Not one of the four, but it burned a migration and shapes
`scripts/reclassify_by_pubtype.py`. `PublicationTypeList` is assigned by NLM
indexers at MEDLINE indexing time. Publisher-supplied records — most MDPI and
Frontiers titles, and nearly everything from the last ~18 months — carry only
`["Journal Article", "Review"]` no matter what the paper actually is. A
reclassification keyed on publication type alone would have demoted 45 genuine
systematic reviews to Level V, including papers with "A Systematic Review" in
the title.

`scripts/reclassify_by_pubtype.py` therefore trusts pubtypes **only when
`MedlineCitation Status == "MEDLINE"`**, identifies Cochrane by journal before
looking at pubtypes at all, and declines (never promotes) on society guidelines,
which NLM does not tag either. Non-MEDLINE rows are reported, not touched.

The general lesson: before keying a migration on a metadata field, check what
fraction of your rows actually have it populated, and whether that fraction
correlates with anything (here: recency and publisher).

**Sharpened by WORKLIST 4.7.** The MEDLINE gate is necessary but it is not
sufficient, and the 14 unlabelled rows are the clean demonstration. 13 of the 14
*are* MEDLINE-indexed — and every single one carries only `['Journal Article']`
(three plus `Scoping Review`, three plus `Research Support, Non-U.S. Gov't`).
NLM assigned no design publication type to any of them. So rung 1 of
`scripts/fix_empty_level_key.py` classified **zero of 14**.

MEDLINE status tells you the publication type list is AUTHORITATIVE. It does not
tell you the list is INFORMATIVE. For observational endodontic work — the
retrospective cohorts that make up most of what write-back brings in — NLM
routinely assigns no design type at all. Any future migration gated on "is it
MEDLINE-indexed?" must still have a rung 2, and must measure how often rung 1
actually fires before claiming pubtypes solved the problem.

### Related lesson: a design cue read off the wrong paper

`scripts/fix_empty_level_key.py` had to classify from abstract text, and PMID
39885347 is the trap. It is published in *Evidence-Based Dentistry*, a journal of
structured critical summaries, and its abstract opens:

> `DESIGN: The study is a prospective, double-blinded randomised control trial
> that compares the mineral trioxide aggregate (MTA) and Biodentine ...`

That describes the trial being summarised. The paper itself is a one-page
commentary — later in the same abstract, `RESULTS: Firstly, **the author
presented** the overall healing ...`, third-person, about somebody else. A cue
matcher looking for "randomised controlled trial" installs it at Level I, where
the system prompt tells Claude to trust the label absolutely.

This is bug class (c) wearing a new costume: metadata computed from text that
belongs to a different record. The migration carries a commentary guard
(journal list plus the `DESIGN:` … `CASE SELECTION:` abstract template) that only
ever declines, never promotes, and `tests/test_end_to_end.py` pins 39885347 at
level5 specifically. **Text-derived design cues must be self-referential** —
"this retrospective study", "a retrospective cohort study" in the title — never
a design mentioned somewhere in the prose.

### Related lesson: green unit tests over a path nothing exercises end to end

Three live bugs shipped with a passing suite: `TIER_ORDER` unimported in
`app.py` (NameError on every question), write-back inserting empty `level_key`
(class (a)), and the similarity floor gating the routing decision but not the
evidence (class (d) in spirit — the check ran and changed nothing visible).
Unit tests imported the symbols directly and passed. `tests/test_end_to_end.py`
exists for this and should be extended rather than worked around.

---

## The eval set

`eval/questions.json` + `python eval/run_eval.py`. Retrieval only — no LLM
tokens.

**Every case must set `force_route`.** Write-back moves the ground under an
unpinned case: the laser case was written for a live search-term bug, the fixed
run wrote 196 papers into the library, and the same case silently started
testing the library path instead. It would have passed the next identical
regression. A topic worth testing both ways gets two cases, one pinned each way.

**Routes are measured, not assumed.** `eval/probe_routes.py` runs each question
through the real coverage gate and reports where measurement disagrees with
clinical expectation. It disagreed on 8 of 20 — in both directions — and
finding that is what surfaced the similarity-floor bug below. 21 cases now,
12 library / 9 live.

**Answer-level assertions are recorded but inert.** `must_contain`,
`must_not_contain`, `banner`, `modules_non_empty` and
`max_unsourced_numeric_modules` live in the case files as intent; the harness
is retrieval-only and does not evaluate them. A green run is not evidence that
they hold. The README in `questions.json` repeats this — do not let it drift.

### The similarity floor asks a different question than you think

`RAG_SIMILARITY_FLOOR` in `app.py` decides both routing and which papers reach
Claude. It was 0.45. Measured across the 20 eval questions, that routed 18 of
20 to the library — including "root canal treatment in pregnancy", which had
63 hits above the floor and **not one on-topic paper**; the whole "relevant"
set was generic AAE/ESE position statements clustering at 0.45–0.52.

all-MiniLM-L6-v2 scores any two endodontic texts around 0.45 purely on shared
domain vocabulary. At that threshold the gate asks *is this endodontics?*, not
*is this the question?*. At 0.55 the thin topics fall out (pregnancy 1, SDF 1,
bisphosphonates 3) while covered ones keep 14–56.

The errors here are asymmetric and the floor is set accordingly: routing live
when the library would have served costs one PubMed search; routing to the
library when it lacks the topic answers a clinical question from papers about
something else. Set the floor where the thin topics fall out, not where
coverage looks best. **A count of hits above a low floor is not a coverage
measurement** — check the distribution (top, p90, count above 0.60) instead.

---

### The measurement behind `RELEVANCE_GATE`

Every hit count below is a real measurement against the live library, one row
per WORKLIST §7 eval question, taken 2026-08-30 after the term-generator fix.
`top` is the single closest paper; `p90` the 10th-closest; the last three
columns count hits clearing each candidate floor.

| question | top | p90 | ≥0.45 | ≥0.55 | ≥0.60 |
|---|---|---|---|---|---|
| single-vs-multiple-visit | 0.689 | 0.570 | 55 | 10 | 8 |
| mta-vs-biodentine-pulpotomy | 0.782 | 0.687 | 79 | 36 | 24 |
| naocl-concentration | 0.727 | 0.663 | 38 | 25 | 18 |
| cbct-vs-periapical | 0.702 | 0.612 | 36 | 17 | 12 |
| bioceramic-vs-resin-sealer | 0.723 | 0.671 | 95 | 48 | 34 |
| retreatment-vs-microsurgery | 0.743 | 0.637 | 97 | 32 | 12 |
| direct-pulp-capping | 0.768 | 0.674 | 82 | 55 | 42 |
| preemptive-nsaid | 0.764 | 0.619 | 77 | 38 | 13 |
| regenerative-immature | 0.634 | 0.591 | 78 | 16 | 7 |
| cracked-tooth-prognosis | 0.689 | 0.575 | 48 | 11 | 7 |
| laser-disinfection | 0.725 | 0.637 | 58 | 32 | 17 |
| apdt-primary-molars | 0.658 | 0.538 | 39 | 8 | 2 |
| bisphosphonates | 0.559 | 0.515 | 60 | 3 | 0 |
| **pregnancy** | **0.553** | **0.509** | **63** | **1** | **0** |
| pips-vs-ultrasonic | 0.657 | 0.584 | 88 | 25 | 4 |
| intentional-replantation | 0.660 | 0.531 | 64 | 4 | 1 |
| sdf-pulp-outcomes | 0.554 | 0.477 | 23 | 1 | 0 |
| sonic-vs-ultrasonic | 0.690 | 0.567 | 31 | 14 | 5 |
| dens-invaginatus | 0.655 | 0.486 | 34 | 5 | 5 |
| diabetes-outcomes | 0.783 | 0.649 | 94 | 56 | 25 |

Read the pregnancy row: **63 hits above 0.45, one above 0.55, none above 0.60.**
Hand-checking those 63 found not one on-topic paper — they were AAE and ESE
position statements plus unrelated outcome studies. The `≥0.45` column does not
measure coverage at all; it measures how much endodontics is in the library.

The `≥0.55` column separates: thin topics collapse to 1–8, covered ones hold
14–56. That is where `similarity_floor` now sits.

**Caveat on reproducing this table.** Search terms are LLM-generated, so counts
move between runs — `retreatment-vs-microsurgery` measured 32 above 0.55 here
and 7 on a later run with different terms, which is why it ended up pinned
`live`. Compare the *shape* (does the count collapse as the floor rises?), not
the absolute number. `eval/probe_routes.py` regenerates the routing half of
this on demand.

### Why the semantic answer cache needs its Haiku gate

The same compression that broke the 0.45 floor explains a design choice that
otherwise looks like belt-and-braces. `query_cache` serves a stored answer when
a new question embeds within cosine 0.92 of a cached one, and then *also* asks
Haiku whether the two are clinically the same question before serving.

MiniLM squeezes this whole corpus into a narrow band: across twenty genuinely
different clinical questions, the closest library paper scored between 0.553
and 0.783 — nothing anywhere near 0.92. So 0.92 is genuinely selective, but the
usable range above it is thin, and the distance between "the same question" and
"a different question about the same procedure" is a few hundredths. A pure
threshold cannot hold that line reliably, and the failure is expensive: serving
a stored answer to a question it does not answer.

The Haiku equivalence check is not redundant with the threshold — it is the
part that does not depend on the embedding space being well-spread. Anywhere
this codebase makes a decision from a MiniLM cosine value, assume the space is
compressed and pair the threshold with a check of a different kind.

A postscript that makes the point sharper: none of that gate had ever run.
`get_cached_answer` selected a column `question` where the table has
`question_text`, so every lookup raised, the broad `except` swallowed it, and
the cache returned a miss — for its entire existence. A permanent miss looks
exactly like a cold cache, which is why it survived so long. Fixed 2026-08-30
after checking the gate fails closed. **When a cache shows no hits, prove it is
cold before assuming it is.**


## Evidence tiers: what each one now means

`TIER_ORDER` is strongest-first and `LEVEL_SCORES` must stay monotonic along it
(`tests/test_tier_banding.py` pins this). Two tiers were added on 2026-08-30.

**`invitro` (15), between case series and expert opinion.** Endodontics is
heavily bench-based, and extracted teeth, dentine blocks, bovine incisors and
agar plates all read as "prospective" to a design classifier — 155 bench
studies were sitting at Level II/III and being shown as the second-strongest
kind of evidence there is. `detect_in_vitro` is deliberately asymmetric:
demoting a real clinical trial into a bench tier is far worse than leaving one
bench paper at Level II, so it needs one strong cue (a preparation that cannot
be a patient) or two weak ones, clinical language vetoes everything, and
cochrane/level1/classic are never touched.

**`retracted` (0), deliberately NOT in `TIER_ORDER`.** Absence from that list
is this codebase's mechanism for "never rendered to Claude". It has a
`TIER_LABEL` only so admin and bibliography views can name it honestly.

### Quality floors are per-tier, and may only loosen

`QUALITY_FLOOR` was one number (50) for every tier. Score is not comparable
across tiers by construction — design contributes 39%, so a Cochrane review
starts from 100 and a case series from 20 before the paper itself is weighed.
Measured on the real library, the flat floor kept 4 of 175 level4 rows, 1 of
155 invitro, 3 of 153 level5: for those three tiers even the 90th percentile
was below the floor, so it was not filtering quality, it was deleting the tier.
Only `MIN_PAPERS_KEPT=3` kept them non-empty, which meant a "case series" block
held three papers chosen by a rule that had already discarded the other 172.

`TIER_QUALITY_FLOORS` gives each tier its own 40th percentile. **`_tier_floor`
caps every value at `QUALITY_FLOOR`, so this can only ever loosen a tier.** Keep
that property: it is what makes the config safe to edit — no change to the dict
can remove a paper that reaches a clinician today. Re-measure with
`scripts/measure_quality_floor.py` if the library composition shifts.

### Two migrations, one lesson about dry runs

Both 1.4 and 1.5 shipped guards that only existed because the dry run printed
random samples for review rather than a summary count:

- 8 rows would have been *promoted* into `invitro` from `level5` (15 > 10) —
  narrative reviews that merely discuss bench work.
- One genuine clinical case report was caught by an "extracted premolars" cue
  describing the procedure, not the specimens.

A migration script that prints only totals cannot surface either. Print random
samples, not top-N, so the sample cannot flatter itself.

### The synthesis assertions earned their keep on the first run

`run_eval.py --synthesis-subset` ran once, 2026-08-30, 4/5 cases passed,
$1.0541 across 13 LLM calls. The one failure is worth more than the four
passes.

`single-vs-multiple-visit` asserts `must_contain: ["Cochrane"]`. The answer did
not mention Cochrane — and it did not cite the review either. CD005296 "Single
versus multiple visits for endodontic treatment" is the definitive systematic
review on precisely that question, all three of its versions are in the library,
and the current one (PMID 36512807, score 70.4, tier `cochrane`, not
superseded, not retracted) was not among the 8 papers served.

Re-measured immediately afterwards on a fresh query, that paper sits at cosine
0.61 against the generated search terms and 0.68 against the raw question —
comfortably above the 0.55 floor and inside the top-100 KNN. So nothing is
structurally excluding it. The failing run simply generated a query for which
it fell out.

That is the search-term variance already recorded as the top open item, but
this is the version of it that matters: not "paper counts move 3x between
runs", but **"whether the single most authoritative paper on the question
reaches the clinician depends on which query the generator happened to emit."**
Retrieval-only runs cannot see this — the count looked fine.

## Cost

A four-module Deep Learning curriculum with real retrieval costs **~$1.18**
(measured 2026-08-29, `learn_history/` records `cost_usd` per run). The target
was $0.50. Quote $1.18 — it is the honest number.

The failing 5-paper run cost $0.60, i.e. it "met" the target by not retrieving
anything. Cost per run is not a quality metric and should never be optimised on
its own.

---

## X-ray / vision path — OFF by default, BAA required to enable

`POST /api/analyze-xray` sends a patient radiograph to a third-party vision
API (Gemini 2.5 Pro, GPT-4o fallback). Patient imagery is PHI. The route ships
disabled and returns 403 until `ENABLE_XRAY=true` is set — and **setting it in
any production deployment requires a Business Associate Agreement (BAA) with
the vision provider first**. This is a decision already taken (WORKLIST §5);
do not re-litigate it in code.

When enabled, `app.py` re-encodes every upload to strip EXIF/GPS/PNG-text
metadata (DICOM-to-JPEG exporters routinely embed patient name/DOB there;
stripping failure rejects the upload rather than forwarding raw bytes), and
the `tooth_hint` field is sanitized to a bare tooth designation so free-text
case narrative never travels with the image. `tests/test_xray_gating.py` pins
all three properties. Note the app accepts PNG/JPG only — raw DICOM uploads
are rejected by extension, so DICOM tag stripping is deliberately out of
scope until someone adds a DICOM ingest path (which would need its own
de-identification pass, not just this one).

## Things deliberately not done

- **In vitro / ex vivo tier**, and a **tier-relative quality floor**. Both change
  how every paper ranks; doing them before the eval set is populated would
  freeze their effects into the baseline unmeasured.
- **Journal impact factor** is excluded from scoring (`USE_IMPACT_FACTOR`,
  default false) on PRISMA grounds — it measures the journal, not the paper.

## Stale evidence

Three separate ways a paper can be obsolete and still be served:

- **Retracted** — `has_retraction`, excluded from `search()` and filtered at the
  PubMed query level.
- **Withdrawn** — Cochrane retitles these `WITHDRAWN: ...` in PubMed and does
  *not* mark them retracted, so `has_retraction` misses them. Excluded by title
  match, which is canonical here rather than a heuristic.
- **Superseded** — every Cochrane update is a new PubMed record and the old ones
  stay indexed. 18 were being served, including a 2005 review superseded in 2019.
  `superseded_by` holds the PMID of the current version; chains resolve to the
  terminal version (CD005296 has three generations). `UpdateIn` is carried by the
  *older* record and names its successor; `UpdateOf` points backwards.

Both retrieval paths now handle all three. The live path parses `UpdateIn` in
`_merge_corrections_and_registries` and `_apply_supersession` drops an old
version when its replacement is in the same batch, or demotes and badges it
when the replacement was not retrieved. The live path records the DIRECT
successor only; the library backfill resolves chains to the terminal version
(CD005296 has three generations).

## Known open items

- ~~14 library rows carry no `level_key`.~~ **DONE (WORKLIST 4.7,
  2026-08-30.)** All 14 classified and set by `scripts/fix_empty_level_key.py`
  (backup `endo_papers_rag_tier_backup`, `run_id =
  empty_level_key_20260830T031533`), then rescored. Split: 8 → `level3a`,
  1 → `level2`, 5 → `level5`. Rung 1 (MEDLINE pubtypes) settled none of them —
  see the sharpened lesson above. The library now holds **0** unlabelled rows,
  asserted by `tests/test_end_to_end.py::TestNoUnlabelledPaperReachesTheEvidenceBase`
  (offline twin + an opt-in `RUN_NETWORK_TESTS=1` query against Neon).

  The single largest correction: PMID 38419999 (pulse-oximetry scoping review)
  was sitting at **score 80.1 with no tier at all**. Because RAG ranks on
  `score * 0.6 + similarity * 40`, it was outranking genuine Level I papers
  while banding to Level V in the prompt. It is now `level5` at 38.6, below the
  quality floor.

  The app.py unlabelled → level5 banding fallback is still load-bearing and its
  test stays: this migration cleared the existing rows, it did not make the
  fallback unnecessary.

- **4 rows left at `level5` "needs review"** (WORKLIST 4.7 rung 3) — a human
  should confirm these:
  - `38419999` Pulse oximetry as a dental pulp test: A scoping review… (*Saudi
    Dent J*, NOT MEDLINE-indexed) — scoping review
  - `39015942` Replantation After Dental Avulsion: A Scoping Review… (*Eur J
    Paediatr Dent*) — scoping review
  - `41167331` Clinical and Laboratory Insights Into the GentleWave System: A
    Scoping Review (*J Endod*) — scoping review
  - `40683315` Vital pulp therapy **in dogs**… a 25-year retrospective study
    (*JAVMA*) — the design cue is real (retrospective cohort) but the tier would
    not be: this hierarchy ranks human clinical evidence and `level3a` outranks a
    human case series. ~~There is no filter that keeps veterinary studies out of
    the library at all.~~ **DONE (WORKLIST C2, 2026-08-30):**
    `animal_subjects.detect_animal_subject` +
    `scripts/classify_animal_subjects.py` moved 36 animal-subject rows
    (15 level2, 12 level3a, 9 level3) into `invitro` (backup run_id
    `animal_subjects_20260830`), guarded by tests/test_animal_subjects.py.
    The JAVMA row itself stays parked at `level5` — the migration never
    promotes, even into `invitro`.

- ~~DECISION NEEDED — scoping reviews now disagree with themselves.~~
  **DONE (WORKLIST C3, 2026-08-30.)** `scripts/reclassify_scoping_reviews.py`
  applies one rule to every title-identified scoping review: `level5` UNLESS
  `PublicationTypeList` includes Systematic Review / Meta-Analysis on a
  MEDLINE-indexed record (none currently does — NLM has a dedicated "Scoping
  Review" pubtype and uses it). 15 rows moved (9 level1, 2 level2, 4 level3;
  backup run_id `scoping_reviews_20260830T134620`), 4 already `level5`,
  3 parked: 2 at `invitro` (placed by classify_invitro's reviewed migration)
  and 39487671, which NLM tagged both Scoping Review AND Consensus Statement
  — demoting it would conflict with reclassify_by_pubtype's consensus→level1
  mapping, so it is left for a human. Guarded by
  tests/test_scoping_review_tier.py.
- 25 `Journal Article`-only rows sit at `level1` with no derivable design — the
  tier was never verified for them. Note that `Journal Article`-only is now
  known to be the *normal* state for MEDLINE-indexed observational endodontic
  work, not an anomaly, so these need the same rung-2 treatment rather than a
  pubtype re-check.
- **Where the unlabelled rows came from — traced, not fixed.** The recorded
  belief was that live write-back keeps producing them. It does not, any more.
  `fetch_papers()` sets `level_key` on every paper dict; `_demote_one_tier()`
  fails safe on an unknown tier; and `learn_from_live_results()`'s
  `ON CONFLICT DO UPDATE` already guards the column
  (`COALESCE(NULLIF(EXCLUDED.level_key,''), endo_papers_rag.level_key)`), so an
  empty value cannot overwrite a good one.

  What the data says: 12 of the 14 were inserted inside one ten-minute window
  (2026-08-29 20:04:15 → 20:14:02), **interleaved second-by-second with
  correctly-labelled rows from the same minute** — 20:04:15.605 empty,
  20:04:15.938 `level2`, 20:04:16.110 empty. Two writers were running at once.
  The 317 rows written since (21:00 → 2026-08-30 07:58) contain **zero**
  empties. This is a stale long-lived process, not a live code path: `start.py`
  runs Flask under the reloader, the parent has been up since 2026-08-27, and
  the serving child gets a new PID whenever a source file changes (observed
  twice while working on 4.7: 29360 → 29916). The child serving at 20:04 had
  imported `endo_ai` before the `"level_key": eff_level` line landed. **After
  editing `endo_ai.py` or `rag.py`, confirm the serving child actually
  restarted before trusting anything it writes.**

  Two latent paths remain, neither of which produced these rows — both worth
  closing when someone owns `rag.py`:
  - `rag.upsert_paper()` (rag.py:393) is a second INSERT into `endo_papers_rag`
    and its `ON CONFLICT DO UPDATE` does **not** carry `learn_from_live_results`'
    `level_key` guard. It happens to be safe only because it never updates the
    column at all.
  - `repair_abstracts.py:171` builds its paper dict with a hard-coded
    `"level_key": ""` and calls `upsert_paper`. Harmless today because it only
    ever revisits rows that already exist (so the UPDATE branch fires and the
    column is untouched), but one row disappearing between its SELECT and its
    upsert would insert an unlabelled row.
- No in vitro / ex vivo tier yet (WORKLIST 1.4). Bench studies — extracted
  teeth, dentin blocks, bovine models — classify as "prospective" and land at
  Level II. Endodontics is heavily bench-based, so this inflates a large share
  of the library.
- The quality floor is flat at 50 (WORKLIST 1.5), which culls entire fields
  whose best papers score in the 40s by construction (no n, no follow-up,
  older).
- `DELETE /learn_history/<filename>` is deliberately ungated while the other
  admin routes require `X-Admin-Token`, because the sidebar delete button calls
  it without a header. Gating it needs a UI change.
- The eval harness does not evaluate answer-level assertions (see above).

## Commit-history notes

- The 1.2 (live supersession) change lives in commit `b139af5`, titled
  `wip: 1.2 live supersession before mutation check`. The annotation commit
  `af6a57c` that explains it mistypes the hash as `b139af9`. Left uncorrected
  deliberately: rewriting a pushed-shaped history to fix a typo in a comment is
  a worse trade than a note here.
- Several changes landed under `wip:` titles because the mutation-check
  workflow (commit, mutate, verify the test fails, `git checkout --` to
  restore) returns the tree to the WIP commit, and concurrent agents' unstaged
  work made rewording unsafe. Each has a following empty annotation commit with
  the real message.
