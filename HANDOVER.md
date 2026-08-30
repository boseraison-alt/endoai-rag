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
    human case series. No animal tier exists and WORKLIST 1.4 (in vitro/ex vivo)
    has not been done, so it was parked at `level5` rather than given an invented
    tier. **There is no filter that keeps veterinary studies out of the library
    at all — worth checking how many others are in there.**

- **DECISION NEEDED — scoping reviews now disagree with themselves.** These 3
  went to `level5`; the 8 scoping reviews already in the library sit at
  `level1`. Both migrations declined to invent a tier and defaulted to the
  direction that preserved existing banding, and they defaulted opposite ways.
  A scoping review charts a literature without effect estimates or quality
  appraisal, so it is neither Level I nor plainly Level V. Recommendation: move
  all 11 to `level5` (a scoping review makes no effect claim, so presenting it
  to Claude as Level I evidence overstates it), or add a tier — but not before
  WORKLIST 1.4, which is already reshaping the bottom of `TIER_ORDER`.
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
