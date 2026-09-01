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

### The cache key has a second half: the conversation context

Review mode carries a thread (last 3 exchanges: previous question, its CLINICAL
RECOMMENDATION only, its cited PMIDs) into the clarify gate, the intent router,
both search-term generators and synthesis. That creates a cache failure mode the
threshold cannot see.

The cache matches on an EMBEDDING of the question text. "What about in immature
teeth?" is the *same string* whether it follows a laser question, follows
nothing, or follows a question about sealers — cosine 1.0 against itself, above
both the 0.92 serve threshold and the 0.985 exact threshold that skips the Haiku
gate entirely. Nothing in the question text records which conversation it
belonged to. Without a second key the first follow-up of every thread would be
served the context-free answer.

`query_cache.context_hash` (`rag.context_fingerprint`, sha256 of the whitespace-
normalised block, "" for no context) is therefore an **equality term in the
WHERE clause, not another similarity signal** — a hard partition. `""` is the
partition every pre-existing row lives in (the column defaults to `''` and the
lookup COALESCEs NULL), so standalone questions keep hitting the entries they
always hit. Verified on the live table: the follow-up's answer stored under
`01c3d414…`, all ten pre-existing rows under `''`.

The general rule, and it is the same one the Haiku gate exists for: **anything
that changes what an answer was derived from must be in the cache KEY, not left
to the embedding to notice.** The embedding sees the question. It does not see
the conversation, the route, or the evidence base.

Related, and by design: a follow-up's write-back can invalidate the PARENT
question's cached answer (`invalidate_cache_near_query` clears a 0.85
neighbourhood regardless of context partition). Observed live — the laser
answer's row was gone by the time the follow-up finished. That is correct: the
topic's evidence changed for both.

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

**Read the cost line in that paragraph again: $1.0541 across 13 LLM calls, for
five cases each expected to cost about $1.** See the next section.

### A synthesis eval that measured stored answers

`--synthesis-subset` printed "3/5 cases passed [SYNTHESIS]" on 2026-08-31
having generated exactly ONE answer. The other four were served out of
`query_cache` from rows written the day before, so every answer-level
assertion — `must_contain`, the banner, the unsourced-numeric-module cap — was
evaluated against text the code under test never produced. Each of those four
cases finished in seconds, cost $0, and printed the same shape of output as a
clean run.

It was noticed only by coincidence: two cases in the subset share a question
string, so the second was served the first's freshly written row and reported
an identical paper count for a differently-pinned case.

`run_case_with_synthesis` now neutralises `get_cached_answer` AND
`save_query_cache` for the duration of each case. The reasoning is the same one
behind `LIBRARY_WRITE_BACK = False` and `force_route`: **an eval must not
measure a stored artefact of an earlier run, and must not leave one behind for
a clinician to be served.** A case whose answer cost $0 is now reported as a
FAILURE, because that is the signature.

Two more things the same investigation turned up in this harness:

- `measured["route"]` was `pinned or "?"` — the REQUESTED route echoed back
  into a field named like a measurement and printed as `route  library`. It is
  now `None` in synthesis mode, because this path cannot measure a route.
- **`force_route` is inert in learn mode.** `/ask` hands a learn question to
  `build_deep_learning_module`, which does its own per-module retrieval and
  never calls the pinned builder — so the two laser cases, the same question
  pinned `live` and `library`, run the identical pipeline under
  `--synthesis-subset`. The harness now says so out loud per case.

- `--diff` had been declared with argparse and never read: it ran an ordinary
  eval, printed no table and exited 0. Implemented, with the ranges reporting
  drift and the `expect` floors keeping the exit code.

### The Cochrane miss: closed, and the root cause was not the query shape

The follow-up diagnosis (Phase A, 2026-08-30) overturned the working
hypothesis. The generated queries for the failing question had 1-3 AND-groups,
never 4 — generator variance is real (recorded above) but did not cause this.
The case is library-routed, so the boolean is EMBEDDED, not sent to PubMed:
the best-formed query scored CD005296 at cosine 0.546 (rank 11 in the whole
library, cut by the 0.55 floor) while the raw clinician question scored 0.680.
A well-formed boolean is mostly operators and quotes, so the better the PubMed
query, the worse the vector search.

Three layers now stand between a query and a lost authority:
- `multi_query_search` (app.py) unions KNN over the raw question plus every
  generated term, keeping the best similarity per PMID;
- `ensure_authoritative` (app.py) guarantees journal-verified, current
  Cochrane reviews above the floor and the top-3 Level I papers, re-checking
  retracted/superseded/withdrawn itself;
- the eval pins `must_include_pmid`/`must_cite_pmid` on 36512807.

Measured: the question went from 10 relevant papers (and an answer that never
mentioned Cochrane) to 36-38 across three runs, with CD005296 present and
cited in every one. Library-pinned eval cases are now near-deterministic.

## How case discussion answers (measured 2026-08-31)

Written because a case answer citing two papers looked like a retrieval
failure. It is not. The retrieval is the same engine Review uses; the loss is
downstream.

### The pipeline

`/case_chat` (app.py) → clarify gate on the FIRST message only
(`generate_clarifying_questions`, Haiku) → `run_case_chat` on a worker thread
→ `build_evidence_base_with_progress(job_id, search_q)` → `ask_case_question`
(endo_ai.py) → `validate_evidence_mapping` + one corrective retry → job record.

Retrieval is **not** a small fixed search. It is the full engine: library
coverage gate, union-KNN across the question and generated terms, tier
banding, per-tier quality floors, the authority guarantee, retraction /
superseded / withdrawn exclusion. A follow-up turn re-searches with
`"{original case} -- {latest message}"`, so vague follow-ups still land.

### What the numbers say

Last five case discussions, from `evidence_mapping.jsonl`:

| when | evidence base | cited | ratio | passed |
|---|---|---|---|---|
| 2026-04-27 | 100 | 2 | 0.02 | yes |
| 2026-05-02 | 100 | 1 | 0.01 | yes |
| 2026-08-09 | 3 | 2 | 0.67 | yes |
| 2026-08-30 | 148 | 6 | 0.04 | yes |
| 2026-08-31 | 37 | 5 | 0.14 | yes |

**Evidence base: median 100 papers. Cited: median 2.** The evidence is
retrieved and then almost entirely unused. Review, for comparison, reaches 31
citations on its best runs against a median-26 evidence base.

### The three real causes

1. **`max_tokens = 2000`** for `ask_case_question`, against **8000** for
   `ask_clinical_question`. A conversational answer that must also carry
   citations cannot spend what it does not have.
2. **The review-mode early stop fires on case answers.** `run_case_chat` calls
   `build_evidence_base_with_progress(job_id, search_q)` with no `mode=`, so it
   defaults to `"review"` — and `EARLY_STOP_MIN_PAPERS` then skips level2
   through level5 and invitro once cochrane+level1 clear 15 papers. Those are
   exactly the tiers a case discussion wants: case series and case reports are
   often the only literature on an unusual presentation. Learn mode passes
   `mode="learn"` and sweeps every tier; case was never given the same
   treatment.
3. **`verify_citation_support` never runs on case answers.** It is called only
   inside `ask_clinical_question` (endo_ai.py:3866). `validate_evidence_mapping`
   DOES run, with a corrective retry, so a case answer cannot cite a fabricated
   PMID — but nothing checks whether the cited abstract actually supports the
   claim, which is the check that catches real-but-irrelevant citations.

### What was NOT wrong

The original hypothesis was that the case path used a small fixed retrieval and
skipped the validator. Both halves are false: retrieval is the full engine, and
the validator runs with a retry. Reporting that plainly matters more than
confirming the guess — a fix aimed at retrieval would have changed nothing
visible, because retrieval was already returning a hundred papers.

## The library evidence block had no evidence in it

Written after hand-judging 20 flagged claim–citation pairs (CURO_HANDOVER
§5[B]). The citation-support checker was flagging around half of all pairs on
real answers, and the open question was whether the checker was too strict.

**It was not. The checker is right and the synthesis was the guilty side.**

### What the hand-judgement found

20 pairs, sampled deterministically from the 187 flags recorded on 2026-08-30
and -31, read with the FULL claim sentence recovered from the stored answer
(`evidence_mapping.jsonl` truncates the claim at 160 characters, and 271 of 313
flags were truncated) beside the abstract the checker actually saw:

| verdict | n |
|---|---|
| the claim is genuinely not supported by the cited paper | 16 |
| the checker was too strict, or its input was malformed | 3 |
| the cached "abstract" was a title only, so nothing could be judged | 1 |

15 of the 20 cite a paper whose TITLE is about a different subject, which takes
no judgement to see: a claim about MTA vs Biodentine pulpotomy in mature teeth
cited to a network meta-analysis of regenerative scaffolds in immature necrotic
teeth; a claim about PIPS/SWEEPS smear-layer removal cited to a systematic
review of photodynamic therapy in primary teeth; a claim about antiresorptive
therapy cited to a review of nonsurgical retreatment outcomes.

### Three structural hypotheses, all killed by measurement

Each looked obviously causal. None survives:

| hypothesis | flag rate when true | when false |
|---|---|---|
| the claim was merged across a bold pseudo-heading | 50.0% (101/202) | 52.9% (190/359) |
| the abstract was truncated at 1200 chars for the checker | 49–53% | 55.6% (whole abstract seen) |
| the answer was library-routed rather than live | 52.1% (147/282) | 52.4% (166/317) |

~52% in every stratum. That uniformity IS the finding: nothing about the
checker's input predicts a flag, which is what you see when the claims
themselves are the problem. **Measure the strata before fixing the obvious
thing** — all three of these would have been fixed on sight, and all three
would have moved nothing.

### Why the model wrote findings the paper does not report

`rag.rag_results_to_scored` built the library's paper dicts without `title` or
`abstract`, though `rag.search` selects both columns. `app._scored_to_text`
therefore rendered one metadata line per paper, and that was the whole library
evidence block:

```
[Level I]
PMID: 1 | Authors: A B | Year: 2024 | Citations: 3 | n=60 | 12mo follow-up | IF=4.0 | Evidence Score: 70.0/100
```

That paper is titled "Er:YAG laser-activated irrigation in immature teeth". The
word "laser" appears nowhere in what Claude was given. The prompt then asks for
a 3–6 sentence paragraph per tier on what the evidence shows, with authors
cited inline and a `[[PMID:N]]` marker on every clinical claim.

In 9 of the 10 flagged pairs checked, the author name in the claim matched the
cited paper's actual author field — and the year and the sample size were right
too. **The model invented only the finding, because the finding was the one
thing it was not given.**

### The measurement

Three library-pinned Review cases, run through the full `/ask` path with the
answer cache bypassed, before and after:

| case | before | after |
|---|---|---|
| single-vs-multiple-visit | 7/18 flagged (39%) | 1/11 (9%) |
| naocl-concentration | 14/21 (67%) | 4/18 (22%) |
| pips-vs-ultrasonic | 5/27 (19%) | 0/30 (0%) |
| **total** | **26/66 — 39.4%** | **5/59 — 8.5%** |

All three moved down; all six runs passed their answer-level assertions.

**The cost, which belongs beside that number and not on its own:** the library
prompt went from ~7k input tokens to ~31k (7188/7593/5814 → 34080/26793/31954),
and an answer from ~$0.36 to ~$0.70. That is the size of the hole — a
library-served answer was being written from about a fifth of the input a
live-served one got.

Two caveats. One before/after pair per case, on a metric whose per-case spread
was 19–67% beforehand, is a direction and not an effect size. And the fix
supplies whatever the library STORED — which is what the abstract repair below
went on to address.

### DECISION (RB, 2026-08-31): the ~$0.70 library answer is the permanent default

Full titles and abstracts in the synthesis context are approved as the standing
behaviour, at roughly double the previous per-answer cost (~$0.36 → ~$0.70;
~7k → ~31k input tokens).

**The rationale is not that the answers got better in the abstract. It is that
the $0.36 path was writing clinical answers without the papers' content.** The
model was given each paper's authors, year, citations, sample size, follow-up,
impact factor and a score — and no sentence of what the paper found — and was
then asked to write a paragraph per tier on what the evidence shows, with a
`[[PMID:N]]` marker on every claim. It did what that prompt makes inevitable:
it got the author, the year and the n right and invented the finding. The
cheaper number was never the price of the same product.

Do not re-litigate this to save tokens. If cost has to come down, take it out of
paper COUNT or tier caps — decisions about which evidence to send — not out of
whether the evidence sent has any content in it.

### The detector

**Any evidence assembled for a model on one retrieval path and asserted to
match another. Test the BLOCK, not the renderer.** The parity test in
`tests/test_coi_scoping.py` compared the two metadata LINES and passed
throughout — the line was never the difference. `_scored_to_text`'s own
docstring says it shares the live path's renderer "so provenance badges appear
identically", and the change that added the badges is where the abstract
stopped being included. Guarded now by
`TestTheLibraryBlockContainsThePaper`, which asserts on the assembled block.

### ~~Not fixed, deliberately~~ — DONE (`grounding-v2`, 2026-09-01)

The prompt mandated a `[[PMID:N]]` marker on every standalone clinical claim
and gave no instruction for what to do when no retrieved paper supports one;
the corrective-retry message ("Add markers from the evidence base, OR
rephrase") pushed the same way. `_GROUNDING_RULE` is now one constant spliced
into all three synthesis prompts. See the next section for what it did.

## The grounding rule, and the three-way measurement it needed

`_GROUNDING_RULE` (endo_ai.py, one constant, three prompts) says a
`[[PMID:N]]` marker is a factual claim ABOUT the paper, asks the model to find
the language it could quote if asked "where does it say that?", and supplies
the option the prompt was missing: cite a different paper, weaken the sentence
to what this one states, or **write it unmarked**. It does not relax the
marker mandate.

Measured on three strata, cache bypassed, 2026-09-01:

| stratum | before | + rule | + whole abstract to the judge | + collapsed-abstract fix |
|---|---|---|---|---|
| Review, LIVE-pinned (5 cases) | 7/34 **20.6%** | 3/32 9.4% | 3/25 12.0% | **0/51 0.0%** |
| Review, library-pinned (3) | 4/49 8.2% | 4/45 8.9% | 3/48 6.3% | — |
| Deep Learning (2 curricula) | 20/235 8.5% | 32/240 13.3% | 31/239 13.0% | — |

**Only the live endpoint is significant, and only for the three changes
together** (7/34 vs 0/51, Fisher exact p = 0.0011). The rule alone is p=0.31;
the curriculum move is p=0.11. Nothing here licenses a claim about any single
change.

Three things worth keeping:

- **The live path was never measured before this.** Every number in the
  39.4% → 8.5% → 4.3% history is library-pinned, so none of the fixes behind
  it could reach the path where abstracts were never missing. Measure the path
  a fix cannot reach before believing the fix generalises.
- **A lower flag rate can be bought with fewer citations, so watch the
  denominator.** A rule whose third option is "say it unmarked" is exactly the
  kind that could. It did not: the live denominator went 34 → 51.
- **4.3% was a draw, not a level.** The same three library cases measured 8.2%
  the next day with nothing changed in between. Quote a range or quote the
  run.

## The last truncation was on the guardrail

`_SUPPORT_ABSTRACT_CHARS = 1200` fed `verify_citation_support`
`abstract[:1200]`. It was harmless when written — 57% of library abstracts
were themselves cut at 1,000 or 1,200 at ingest, so there was nothing past it.
`grounding-v1` healed those rows to a mean of 1,631 characters **and left the
cap in place**, which turned a no-op into the last truncation in the pipeline,
sitting on the check whose whole job is to read the paper.

Found by hand-judging all 37 Deep Learning citation flags
(`eval/logs/dl_flag_verdicts.json`, regenerate with
`scripts/classify_dl_flags.py`):

| verdict | n |
|---|---|
| checker artifact — the supporting sentence was past character 1,200 | 17 |
| checker artifact — the extracted "claim" is not one claim | 13 |
| genuinely unsupported | 7 |
| abstract unusable | 0 |

**36 of the 37 cite a paper whose stored abstract exceeds 1,200 characters.**
PMID 27759881 is a 6,724-character Cochrane review whose LLLT finding sits
~5,000 characters in; the judge was shown its search strategy.

So Deep Learning's 11–20% is **81% checker artifact**. Its genuinely-
unsupported rate is 7/234 = **3.0%**, in line with Review's rather than four
times it. The gap is explained by two things the curriculum prompt itself
requires: a Decision Tree that emits `IF / THEN / BECAUSE` across lines (the
splitter has no rule for it, so a seven-branch tree becomes ONE claim carrying
seven markers), and mandated procedural specificity, which makes claims cite
deep-in-the-abstract RESULTS values.

The judge now gets the whole abstract, **bounded by batching on item
boundaries rather than by cutting** — an item split across two requests is a
claim judged against half its evidence, the same bug with a new cause. That
makes the checker stricter, not looser.

**The claim-unit half is untouched and is the largest remaining single cause
in this metric.** Fixing it means changing `_extract_claim_citation_pairs`,
and the last change to that splitter reversed its expected direction (merged
claims were flagged LESS, p=0.002). It needs its own batch.

### The other fail-open in the same function

`_SUPPORT_MAX_PAIRS = 30` caps how many pairs are checked at all. The two
laser curricula measured 29/30/30/30 — three of four modules **at the cap** —
and the rendered block said "each of the 30 cited claims was checked" while 15
were never looked at. True, and read as complete. `total_pairs` is recorded
now and the block names the remainder. **A cap that binds silently is bug
class (d) whatever the sentence around it says.**

## A third shared file, and the same contamination

`run_eval` computes a case's citation-support flag rate from a byte-offset
window of `evidence_mapping.jsonl` — the same shape as `_esearch_hits_since`
over `pubmed_audit.jsonl`, and with the same exposure. A `pytest` run of
`tests/test_end_to_end.py`, started while an eval was in flight, put nine rows
of `checked: 3, n_flagged: 0` inside one curriculum's window and reported
16/146 = 11.0% for what was 16/119 = 13.4%.

Two fixes, because either alone leaves a hole:

- `tests/conftest.py` redirects `_EVMAP_LOG_PATH` and `_COST_LOG_PATH` to a
  tmp directory for the whole session. **A test run must not append to the
  record of what the product did.** It had also been adding stubbed TTS rows
  to `cost_log.jsonl` — $5.70 of imaginary spend in one night.
- Every `verify_citation_support` record carries `pid`, so the harness
  EXCLUDES a foreign row instead of guessing.

A timing heuristic was written first and thrown away: the real burst was 1.3 s
apart, which is also what four curriculum modules finishing on a thread pool
look like.

**The general rule: any file in the repo root that a running process appends
to is shared mutable state, and any measurement taken as an offset window into
one has this bug until it identifies its own writer.** `pubmed_audit.jsonl`
and `cost_log.jsonl` are still unguarded.

## Healing the abstracts, and two ways to write a paper onto the wrong row

The library's abstracts were cut at ingest — 1,342 of 2,350 rows (57%) at
exactly 1,000 or 1,200 characters, across six call sites. Fixed at the source
(`build_library.py` ×2, `fetch_open_sources.py`, `fetch_pmc_corpus.py`,
`ingest_aae_guidelines.py`, `repair_abstracts.py`) and healed in place by
`scripts/repair_truncated_abstracts.py`.

| | before | after |
|---|---|---|
| mean abstract length | 1,182 chars | 1,631 |
| rows with the truncation signature | 1,342 | 1 |
| abstracts containing "conclusion" | 7.2% truncated / 39.3% whole | 54.7% |
| rows PubMed holds no abstract for | 8 | 4 |

The remaining signature row is PMID 25231145, whose PubMed abstract genuinely
IS 1,200 characters and ends on a complete sentence; the four empty rows were
confirmed abstract-less by a targeted re-fetch rather than assumed. 1,355 rows
re-embedded, matching the changed-row count exactly.

**Fetch the XML, not the text dump.** The live path parses
`rettype=abstract&retmode=text` with a "longest paragraph ≥ 200 chars"
heuristic. That is the wrong tool when fidelity is the whole point: efetch XML
gives `<AbstractText>` as tagged elements WITH their section labels, so a
structured abstract arrives as "BACKGROUND: … RESULTS: … CONCLUSIONS: …"
rather than as whichever paragraph happened to be longest.

### Two bugs in the fetcher, both of which would have written one paper's abstract onto another's row

Worth recording because each one produced plausible output and neither is
obvious from reading the code:

1. **`.//PMID` matched the wrong PMID.** A PubMed record's
   `CommentsCorrectionsList` contains `<PMID>` children of its own — the ids of
   the papers it corrects or updates. A descendant search picks up whichever
   comes first, and on some records that is not the article's own id. Observed
   returning PMID 2019, which is not in this library at all. Use the explicit
   `MedlineCitation/PMID` (and `BookDocument/PMID` for book records).
2. **`find(a) or find(b)` silently discarded a valid element.** An ElementTree
   element with no children is FALSY, so `<PMID>12345</PMID>` — a childless
   element with text — evaluates false and the `or` falls through to the
   fallback path. This turned 2,241 successfully fetched abstracts into 72
   usable ones, and the failure looked exactly like PubMed not answering.
   **Never truth-test an Element. `is None`, always.**

The first bug crashed on a KeyError, which is why it was found. It is worth
noticing that it crashed only because the stray id was absent from the library:
had it been a PMID the library DOES hold, the run would have written one
paper's abstract onto another's row and reported success. The script now
guards on membership as well as using the explicit path.

### v5 → v6: ten moves, and what each one was

Ten metrics left their v5 range. **Six of them are on the four cases that had
ONE observation in v5** — `case-opening-full`, `case-opening-sparse`,
`review-followup-immature-teeth` — where a single point was being compared with
a three-run range. All 25 cases now have three runs and that class of noise is
gone for good.

The two real ones, and neither is a regression:

**`sdf-pulp-outcomes` (live), papers 32-46 → 26-29.** The v5 range was inflated
by one atypical run: its per-tier shape was `{level1:8, level2:15, level3a:8,
level3b:1, level4:6, level5:8}` — the early stop did not fire and it swept
every tier — against `{level1:33}` and `{cochrane:6, level1:26}` for the other
two. v6's three runs are all level1-dominated and tightly clustered. This is a
LIVE-pinned case, so nothing done to the library can reach it; the mechanism is
the early stop plus PubMed term variance on a genuinely thin topic (HANDOVER's
own coverage table gives SDF one library hit above 0.55).

**`direct-pulp-capping` (library), papers 38-39 → 35-35.** Three causes were
checked and two eliminated by measurement:

- *Not the similarity floor.* 325 library papers clear 0.55 for this question.
- *Not the tier quality floor.* Exactly 6 papers crossed a floor after the
  rescore, and 4 of them crossed UPWARD (net +2).
- *It is the candidate pool.* `multi_query_search(..., limit=100)` takes a
  fixed top-100 KNN per query. Re-embedded rows now rank HIGHER — median
  similarity 0.6175 against 0.6130 for untouched rows, and 69 against 28 in the
  top 300 above 0.65 — so they occupy more of those 100 slots and displace
  papers that used to fill the smaller tiers. `level1` is cap-bound at 25 and
  absorbs none of it, which is why the whole loss lands in level2 / level3a /
  classic, exactly where it does.

That is precision bought with a little recall: the papers displaced were the
lower-similarity ones. The case passes every floor in all three runs. Worth
knowing rather than worth reverting — but if a future change wants that recall
back, `limit=100` is the dial, not the floor.

**One thing I did not back up and should have.** The repair backed up the old
ABSTRACTS but not the old EMBEDDINGS, so the pre-repair vectors are gone. That
is the same mistake this file already records about the first Cochrane
migration. It is only *mostly* recoverable — the old vectors could be rebuilt
from the backed-up abstracts, but the corpus builders used several different
embedding-text conventions (`title + abstract[:400]`, `topic + …[:400]`,
`text[:600]`), so a reconstruction would not be faithful row by row. **Back up
the column you are about to overwrite, not the column you are thinking about.**

## The deck: two budgets, and only one of them was consulted

`content_slide` is handed `avail` — the body height its frame actually has,
after the title wrapped and the lead was drawn — by `_content_frame`, and never
used it. Pagination was done entirely by `text_budget.split_bullets`, which
counts WORDS. Five cascade steps of under 25 words each cost five slots and
"fit", while each one renders as a bold header line PLUS a body paragraph: real
spec `01e071f7` slide 9 drew its body to 7.385in against a 7.000in footer rule,
in a single un-split page.

Neither budget is redundant. The word budget is a house style (§1.3: at most
five bullets of ~25 words); the height budget is physics. `_paginate` now
applies both and balances the result, because filling page one to the brim and
letting the remainder fall onto page two produces the four-then-one orphan
`split_bullets` was already written to avoid. Text is never truncated to fit —
a bullet that does not fit starts the next page.

**The guard is parametrised over every `cascade_slide` in `slide_specs/`** —
real generator output. A hand-written fixture would not have produced the
shape: the steps have to be short enough to pass the word budget and tall
enough to overflow the frame, which is a coincidence of real clinical prose.

Two more from the same pass, both the "a check that shows nothing" class:

- `evidence_summary` drew a `REPORTED` column header over an entirely blank
  column whenever no hierarchy row carried a stat — which is every
  `evidence_summary` in every cached spec, because the generator is correctly
  told to omit `stat` rather than put a verdict word in it. A blank column
  under that header reads as "these studies reported nothing".
- `_from_explicit_chart` in `chart_data` was the one detector with no
  `is_range` and no `consistent_unit` gate. It was unreachable, so it did not
  matter — until multi-arm comparisons started using it. The web deck's
  `_plan_stat` had neither gate either, on a path that WAS reachable: the SMD
  beside an I², and the 24-48h span as one bar, were both caught in the PPTX
  and drawn on the web from the same spec.

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
- ~~**`verify_citation_support` never runs on the Deep Learning path.**~~
  **DONE.** It now runs per module, after that module's own validation gate,
  through the same `_append_support_warnings` renderer as Review and Case —
  ~$0.0024 per module, about $0.01 on a $1.40 curriculum. Three things that
  pass on to whoever touches it next:
  - **The status has to survive the stitcher.** `stitch_curriculum` is an LLM
    call told to reproduce module text verbatim, which is not a guarantee. The
    post-stitch pass COUNTS the expected blocks in the output and restates any
    that went missing in an appendix. Counting, not substring-matching: two
    modules with identical statuses produce identical blocks.
  - **The three "module not generated" paths need a status too**, or a module
    that was never written is indistinguishable from one that passed.
  - **The view's blockquote-strip pattern was a live regression waiting.** It
    ended `[\s\S]*$` anchored to the FIRST match, so the moment an answer
    carried a second support block it would have deleted the curriculum from
    module 1 onward. Adding per-module blocks is what would have triggered it.
- **1342 of 2342 library abstracts — 57% — are hard-truncated at ingest,**
  749 at exactly 1200 characters and 593 at exactly 1000. Five call sites do
  it: `build_library.py:166` and `repair_abstracts.py:163` store
  `abstract[:1000]`; `fetch_open_sources.py:334`, `fetch_pmc_corpus.py:330`
  and `ingest_aae_guidelines.py:438` store `abstract[:1200]`. The live path
  applies no cap at all.

  Structured abstracts put RESULTS and CONCLUSIONS last, and the measurement
  shows exactly that: only **7.2%** of the truncated rows still contain the
  word "conclusion", against **39.3%** of the untruncated ones — a 5.5x drop.
  Tails cut mid-word (`...'or proportio'`, `...'udies were i'`).

  This limits the citation-support checker, and it qualifies the fix above:
  for 57% of library papers the synthesis now gets a plausible-looking
  abstract that stops before the findings, which is better than nothing but is
  not the same as being shown the paper. Fixing it is a re-ingest, not a code
  change.
- ~~**`_extract_claim_citation_pairs` has two input defects, neither of which
  drives the flag rate.**~~ **CORRECTED, and the correction reverses the
  conclusion.** The first measurement (50.0% merged vs 52.9% clean — "no
  effect") did not reproduce. A second pass matched every
  `verify_citation_support` record to the stored answer written within 600s of
  it, kept only records whose re-derived pair count equals `checked` exactly,
  and dropped one record whose stored answer had been rewritten after the
  check — 36 usable records, 686 pairs, all 322 flags matched back to a derived
  pair. Result: **merged 37.6% (76/202) vs clean 50.8% (246/484), p=0.002.**
  The clean rate reproduces the original 52.9% almost exactly; the merged rate
  does not, and the dropped record accounts for it.

  **The direction is the uncomfortable one.** Merged pairs are flagged LESS
  often. A long blob gives the judge more surface on which to find something
  the abstract does support, so a bad citation buried in a merged claim is
  *less* likely to be caught than the same citation on its own sentence. The
  defect suppresses the guardrail rather than blurring it — which makes it a
  correctness fix for a safety gate, not the cosmetic cleanup the first
  measurement made it look like.

  Two lessons worth more than the fix: a null result deserves the same scrutiny
  as a positive one (the first pass matched flags to claims loosely and never
  checked that its derived pair count agreed with the `checked` the run
  recorded), and "no effect" is the easiest finding to get wrong, because
  nothing about it demands explanation. The defects:
  - `_HEADING_RE` only matches ATX headings (`## …`), so the `**Level II —
    Prospective Studies**` pseudo-headings the generator actually emits do not
    split a section. `_SENTENCE_SPLIT_RE` then does not split there either
    (the line starts with `*`, not `[A-Z\d]`), so one "sentence" can carry
    several claims and several PMIDs, and each PMID is judged against all of
    them. 36% of all claim-citation pairs are such blobs.
  - `_SENTENCE_SPLIT_RE` splits after any `.` followed by a capital, so
    "Er:YAG vs. SWEEPS" breaks mid-sentence and the citation lands on a
    fragment ("SWEEPS pulse modes) limits pooled effect estimation").
- **One cached "abstract" is a title.** PMID 6594419's `abstract` column holds
  only the paper's title, so the support checker had nothing to judge against
  but did not skip the pair — `verify_citation_support` only skips when the
  field is EMPTY. A non-empty field that is not an abstract fails closed into a
  flag.
- **`_unit_of` can pick the wrong quantity's unit.** `_unit_of("12 mm at 3
  months")` returns `"months"`, because the `month` token test runs before the
  `mm` match, while `parse_number` returns `12` — the mm value. Two such arms
  therefore agree on a unit computed from a number nobody plotted, and the
  chart is axis-labelled with the wrong one. Mislabelling, not invention (both
  numbers are verbatim in the source), and pre-existing on all three
  detectors. Left alone because reordering `_unit_of` shifts behaviour under
  every chart in the product and there was no budget to re-verify them.
- **`case_convs` (`app.py:258`) is written and never read.** grep finds the
  declaration and one assignment (`app.py:2036`) and no reader anywhere. It has
  no cap either, unlike `review_threads` (`REVIEW_THREADS_MAX = 500`), so it
  accumulates a full evidence base per case conversation for the life of the
  process — ~277 KB each now that the library block carries abstracts. Either
  wire it up or delete it.
- **`content_slide`'s no-overflow guarantee has one exception.** A SINGLE
  bullet taller than the whole frame still gets its own page and runs off it
  (a 500-word bullet renders 8.3in tall on a 7.5in slide). That is deliberate —
  the alternative is splitting a clinical sentence — but the guarantee is "no
  overflow unless one bullet alone exceeds the frame", not "no overflow". No
  cached spec triggers it.
- **8 library rows have an empty `title`.** Harmless while the library block
  sent metadata only; now that `_scored_to_text` emits the title, those papers
  reach Claude with a blank line where their subject should be. Small, and the
  titles are one efetch away.
- **`narration.strip_markdown_for_speech` does not strip blockquotes.** No live
  path is affected — every narration route rewrites the answer through an LLM
  first — but if a raw-narration path is ever added, a curriculum's citation
  support blocks would be read aloud verbatim.
- ~~**The "longest paragraph" abstract heuristic loses paragraphs.**~~
  **FALSE, and the correction is the interesting half. DONE
  (`grounding-v2`, 2026-09-01.)** Measured against efetch XML on 198 library
  PMIDs, 95 of them structured, the collapse loses **nothing**: 0 rows lose
  more than 20 characters, 0 lose a CONCLUSIONS section, 100.0% of the text is
  kept. PubMed's text renderer emits BACKGROUND / METHODS / RESULTS /
  CONCLUSIONS as one blank-line-free block, so the longest paragraph IS the
  whole structured abstract. `scripts/measure_paragraph_collapse.py` records
  it and `tests/test_abstract_selection.py` pins it, so nobody fixes a loss
  that does not happen.

  **The real defect is the opposite one — over-capture — and it was live.**
  "Longest paragraph" is a proxy for "the abstract", and two other blocks can
  be longer:
  - the AUTHOR AFFILIATION list. PMID 39743567, a consensus with ~30
    institutional addresses, stored **6,304 characters of university
    departments** in place of its 707-character abstract.
  - a FOREIGN-LANGUAGE abstract, printed under `Publisher:`. PMID 41337506's
    Portuguese version is longer than its English one.

  Both reached synthesis as the paper's text AND were written into
  `abstract_cache`, which is what `verify_citation_support` reads: a paper
  whose "abstract" is a list of addresses flags every claim cited to it, and
  the clinician sees the flag with no way to know why. 175 of 9,985 cache rows
  and 4 of 2,348 library rows were in that state; 124 healed by
  `scripts/repair_collapsed_abstracts.py`, leaving 40 records PubMed holds no
  abstract for at all.

  `endo_ai._select_abstract_paragraph` is shared by all four parsing sites
  now. Two properties are load-bearing and each has a test: the exclusions are
  ANCHORED (a paper whose abstract merely contains "Copyright:" keeps it), and
  a record whose only long block is excluded keeps that block rather than
  being blanked — an empty abstract silently SKIPS that paper in the support
  check, so the guardrail would go quiet instead of complaining.

  **Two lessons past the fix.** The first measurement drew `ORDER BY pmid
  LIMIT 60`, which is the oldest rows in the library and the one stratum the
  heuristic cannot hurt; it reported 0.0% and was right for the wrong reason.
  A deterministic sample still has to be a spread one. And a hypothesis
  carried in a handover for two batches is still a hypothesis: this one was
  written down three times before anyone measured it.

- **`ingest_aae_guidelines.pubmed_fetch_abstracts` had never returned
  anything.** Its entry separator was `^(\d{5,9})\.` — five to nine digits
  then a dot — while PubMed numbers entries `1. `, `2. `. Verified against a
  real dump: zero entries, every time. Every record it fetched was then
  dropped by `len(abstract) < 60`, and the `abstract[:1200]` cap removed from
  that file in `grounding-v1` was on a line that had never executed. Fixed to
  share `_parse_efetch_batch`. **That ingest path is live for the first time,
  so dry-run the script before running it.**

- **A quoted claim could end in half a citation marker.** The support block
  quotes a flagged claim at 140 characters, and a MERGED claim carries
  `[[PMID:N]]` markers inside it, so the cut lands mid-marker. A real
  curriculum rendered `... resolving by day 14 [[PMID:` and
  `strip_markdown_for_speech` left the fragment in the narration script, where
  TTS reads it out letter by letter — and it is a raw marker on a rendered
  surface, which invariant 3 forbids. `endo_ai._quote_claim` strips it at the
  source and narration catches a fragment that reaches it anyway. Both
  patterns require the DOUBLE bracket so prose that says "a PMID marker"
  survives. **Found by an existing test whose fixture is the newest laser
  curriculum in `learn_history/` — it started failing the moment this batch
  generated one with the shape. Fixtures from real data pay for themselves at
  exactly these moments.**

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
