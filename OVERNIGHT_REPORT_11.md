# OVERNIGHT REPORT 11 — batch 2026-09-09

<!-- PUSH STATUS GOES HERE, FIRST LINE, before anything else. -->

**Routing is live by default.** The library is a contributor on every question
and the sole source only when PubMed fails. The batch's other headline is that
closing one leak revealed three more paths into the same pool.

---

## Item A — live by default

### Routing and latency, measured on the real builder over 32 questions

| | |
|---|---|
| **routed LIVE** | **32/32** |
| pools that grew vs the A55 library-route measurement | 28 of 32 |
| latency, median / max | **77.2 s / 111.0 s** |
| spend, median / total | **$0.0103 / $0.34** |
| library rows joined by the union, sample question | 79 (beside 48 from the live lanes) |

Predictions 1 and 3 held. Prediction 5 was close on latency (I said median
40–75 s; it is 77.2) and **wrong on cost** — I predicted ~$0.006 per question
and it is $0.0103, still far below the $0.02–$0.10 I had guessed in A55.

### Prediction 2 was wrong: the missing-live fraction is not zero

I predicted zero "by construction". It is non-zero on all 32, and the reason is
that my harness compared the **bare generated term** against the assembled pool.
The live lanes send per-tier publication-type filters, `ENDO_DOMAIN_FILTER`, a
retracted exclusion and the species guard, then apply quality floors and caps.
Two different queries cannot have the same answer.

Diagnosed per PMID (rule 41) on the four worst questions, 156 absent hits:

| reason | n | verdict |
|---|---|---|
| no lane's publication-type filter matched | 73 (47%) | legitimate |
| off-domain (`ENDO_DOMAIN_FILTER`) | 52 (33%) | legitimate |
| animal-only (species guard) | 9 (6%) | legitimate |
| in the library, below the 0.55 similarity floor | 17 (11%) | the floor working |
| **above the floor and still absent** | **5 (3%)** | **a true loss** |

The 5 are unexplained and recorded as found-not-fixed rather than guessed at.

### The fallback catches outages, not bugs

The library route survives only as the emergency path, logged to
`eval/logs/library_fallback.jsonl` with its reason. It began as
`except Exception` around 380 lines and **hid two of my own `NameError`s within
the hour** — both found by reading the fallback log, not by anything failing. It
now catches request, timeout, connection and OS errors only: an outage falls
back, a bug propagates.

### 30 tests repaired, none re-pinned

| file | n | what moved |
|---|---|---|
| `test_live_path_lane_parity` | 10 | sliced source to the next top-level `def`; the lanes moved into `_build_live_evidence` |
| `test_end_to_end` | 9 | stubbed the library and left PubMed alone, so every question hit the network and timed out |
| `test_review_context` | 5 | a tripwire that raised on reaching live, written when reaching live was the mistake |
| `test_coverage_gate` + `test_a55_intersection_gate` | 3 | asserted the conditions were ANDed into `library_covers_question`; they now feed `gate_says_library` |
| `test_relevance_cap`, `test_retrieval_speed`, `test_case_discussion` | 3 | same source-slicing class |
| `test_eval_harness` | 1 | the pinned wrapper must forward `_fallback` |

**Contamination found and closed:** two stub answers written by the suite reached
`answers/`, and `test_review_context.real_answer` — which reads the most recent
*real* answer — then failed on another test's output, in a directory holding 171
genuine ones. `save_answer` now takes its directory from a module-level path and
`conftest` redirects it, as it already did for four audit logs.

---

## Item B — reband stage 1

**327 rows moved. Dry run and apply agreed line for line.**

| tier | before | after | delta |
|---|---|---|---|
| `invitro` | 191 | 426 | **+235** |
| `level1` | 1833 | 1708 | −125 |
| `level2` | 407 | 347 | −60 |
| `classic` | 272 | 250 | −22 |
| `level3a` | 579 | 558 | −21 |
| `level3` | 307 | 297 | −10 |
| `level3b` | 67 | 57 | −10 |
| `level4` | 195 | 208 | +13 |
| **TOTAL** | 4199 | 4199 | **0** |

- **B1 agreements: 92**, not the batch's 64. Largest bucket `level2 → level1` (42).
- **B2 bench-on-clinical-ladder: 235** at apply time, against my predicted
  60–120. It measured 204 earlier in the night; item A's write-back added ~737
  rows between the two, which is the live route working.

**B2 is a conjunction, not a regex** — a bench cue *about this study*, and
`extract_stated_design` independently reading the design as `invitro`. A single
cue match would have moved PMID `27486835`, a Cochrane review of xylitol for
otitis media whose background says bacteria adhere to nasopharyngeal cells "in
vitro". Both signals agreed on it and both were wrong; what settles it is what a
Cochrane review *is*, so `cochrane` is protected on that ground.

### B3 — guideline pubtypes leave `level1`

The manifest decides: a guideline pubtype whose PMID has a manifest record
becomes `guideline`; one without is **banded at nothing** and written to
`eval/reports/manifest_candidates.md` for a human. Written on both exits,
because a dry run that finds unrecorded guidelines and throws the list away has
done the expensive part and kept none of it.

### B4 — F5–F8

| | outcome |
|---|---|
| F5 `42634020` | already at `level3a` — **item A's write-back ingested it** |
| F6 `42004800` | ingested at `level1`, score 67.0 |
| F7 `41555359` | **moved `level1` → `invitro`** by explicit decision |
| F8 `38849637` | **not ingested** — scores 41.8 against the write-back floor of 50 |

**B2 does not reach F7 and is right not to.** B2 is a *population* rule; F7's
subjects are studies and `extract_stated_design` reads it correctly as a
systematic review. Its bench-ness is in its **outcomes** — sealing ability,
marginal adaptation. Subjects and outcomes are different axes, so F7 moved by an
explicit decision recorded in `level_key_source` rather than by widening a
population rule until it caught an outcome.

**Dry run said +2 and the apply delivered +1.** F8 was refused by the write-back
quality floor. The floor is right and stays; the dry run was wrong not to model
it, and now does.

---

## Item C — an animal study says so in the sentence that cites it

| | |
|---|---|
| documents scanned | 205 |
| citations of an animal-subject row | 60 |
| of those, prose claims | 53 |
| **unlabelled prose claims, as served** | **48 → 0** |

Applied at render time in the finaliser, on the same principle as the redirect
rewrite: the archive records what was said and is corrected on the way out.
Sentence-scoped, so a claim that already names the species is left alone.

A test I wrote asserted the bibliography form `[PMID: n]` should be labelled
too. It fails, and the measurement settles it: a bibliography entry is not a
claim, and after rendering **0 of 53** prose claims are unlabelled, so no prose
claim in the archive uses that form.

---

## Item 3 — no non-current guideline reaches a pool, by any path

**Measured first**, on the 32 with frozen terms: **28 of 31 questions** carried
at least one superseded document in the guideline block.

| PMID | id | questions | why |
|---|---|---|---|
| 22409417 | `IADT-AVULSION-2012` | 22 | superseded |
| 17180780 | `ESE-QG-2006` | 21 | superseded **and quarantined by A2** |
| 17511833 | `IADT-AVULSION-2007` | 15 | superseded |
| 22230724 | `IADT-FRACTURES-LUXATIONS-2012` | 12 | superseded |
| 30664240 | `ESE-DEEPCARIES-2019` | 1 | superseded_in_content |

**The path, asked of each candidate separately rather than inferred from the
rows** — and the prediction committed beforehand named this order and held:

| path | offending rows |
|---|---|
| library union | **none** — `rag.search` already excludes them |
| `admit_scoped_guidelines` | **none** — filters on manifest status |
| **the live guideline lane** | `17180780`, `17511833`, `22409417` |

The lane queries PubMed and scores what comes back. A superseded IADT 2012
guideline is a real, indexed, unretracted record; nothing about it looks wrong
to a query, and the lane has no reason to consult a manifest or a
`quarantine_reason` column, because those are facts about *our* library.

Closed with a single gate beside `drop_off_domain`, applied to every lane rather
than bolted onto the one that leaked. Disqualifying on **any of three
independent facts**: status not in (`current`, `current_but_stale`), a
`quarantine_reason`, or a `superseded_by`. `ESE-QG-2006` carries two and reached
21 pools regardless.

### There was a fourth path

The first fix took the block from 28 questions to **1**, and the survivor was
`ESE-DEEPCARIES-2019` arriving through **`snowball_from_reviews`** — which
admits rows directly from a review's reference list, bypassing both
`fetch_papers` and the union. "A single gate every path inherits" was the right
principle; I had counted three paths and there were four. A reference list is
exactly where a superseded guideline lives: the review cited the version that
was current when it was written.

**`test_no_superseded_guideline_reaches_a_pool` did not cover the leaking path.**
It exercised `rag.search` only, and passed throughout all 28 questions. Extended
to the union and to the live lane's guard.

**Closed: 0 offending rows across all 31 questions**, on the run whose file
mtime (12:59:57) proves it is the run that included the snowball guard. The
first two readings of that result were of a **stale file** — a `nohup` run had
died when its tool call returned, and a fixed leak read as open. Recorded as
instrument error 10, and reproduced on purpose later in the night: a
`nohup … &` launch returns exit 0 immediately, so the harness reports success
while the work either dies or, worse, runs a second copy into the same log.
Both copies were killed and the measurement re-run once. **A result file must
be read together with its mtime.**

### The harm realised — and it is worse than the leak count

The leak count says how often a superseded guideline reached the **context**.
This says how often it reached a **clinician**.

| | |
|---|---|
| documents scanned | 205 |
| citing sentences naming one of the five | **36** |
| …carrying no supersession notice, as served | **36 — all of them** |

`_guideline_supersession_notice` fires on the context line, where the model
reads it. It does **not** fire on a citing sentence in a served answer. A
clinician reading the archive sees `ESE-DEEPCARIES-2019` cited for what vital
pulp therapy contraindicates, with nothing anywhere to say the document has
been replaced.

Corpora counted out loud (rule 34): `answers/` 171 files,
`eval/logs/case_answers/` 17, `eval/logs/curricula/` 0, `query_cache` 17 rows.

**This is item C's shape exactly** — an upstream fix changes what gets written
next and does nothing for the stored answers served again on every archive
read — and item C's remedy applies: a render-time notice in the finaliser.
**Not done tonight.** Measured, and carried as found-not-fixed. It is the third
instance of this pattern, which is the argument for fixing the class rather
than the instance.

---

## Item E — the crown-fracture probe, scopes corrected

**PASS 3/3.** With RB's corrected scopes (`3224b76`), both watched documents are
admitted by scope on 3 of 3 cold-term runs:

| | scope (b≥2) | similarity (a) | union |
|---|---|---|---|
| `AAE-TRAUMA-2026` | **3/3** | 0/3 | 3/3 |
| `IADT-FRACTURES-LUXATIONS-2020` | **3/3** | 0/3 | 3/3 |

**The 2026-09-08 diagnosis holds: the manifest was the blocker, not the
matcher.** Rule (a) is still 0/3, which was the other half of that diagnosis and
also holds.

### The synthesis, and why the renderer is not wired

The one authorised synthesis of probe 2 ran. A55 item 5's renderer **had never
been wired** — it passed its own tests for a day while nothing called it. Wired
for this item, it produced three defects on a real answer, and the first is a
clinical hazard:

1. **It rendered a superseded guideline as an entry.** `ESE-QG-2006`, status
   *superseded*, listed beside current ones.
2. **It mis-attached the model's sentences.** They are lifted by matching the
   organisation, and six of the 32 admitted rows are ESE — so the ESE 2023 S3
   recommendation was attached to the ESE 2006 superseded document.
3. **Its header citations were dropped by G2**, leaving the section
   unattributed — which also cost it the evidence-mapping retry, so the model's
   own section won and the log reported a section the served answer did not
   contain.

Any one is worse than the model writing the section itself. **Reverted**; the
function and its tests stay.

---

## Item D — the v8 baseline

**29 cases × 3 runs, routing live by default, no `force_route` pins.**
Retrieval-only, which is what v7 was and what makes the two comparable.

| run | passed | imported | wall clock | term-cache hits |
|---|---|---|---|---|
| 1 | **24/29** | 13:25:38 | 34m 14s | 27/29 |
| 2 | **23/29** | 13:59:52 | 34m 59s | 29/29 |
| 3 | **23/29** | 14:34:51 | ~34m | 29/29 |

Runs 1 and 2–3 report different commits (`e5cca30`, `c331f77`) because RB
committed a protocol document at 13:59. The diff between them is **one
markdown file and no code**, so the three runs executed identical retrieval;
recorded rather than smoothed over.

**Contamination: 0 cases across all three runs.** No run had >10 search terms
in its audit window and none had >25% of esearch calls fail, so every case's
retrieval numbers describe its own queries.

### The 14 re-pinned cases: all 14 passed, 3 of 3

None failed on a real criterion. Every `min_papers` floor was met by the union,
and `single-vs-multiple-visit` met its `must_include_pmid` for **36512807** on
all three runs — the criterion the batch named as the one to leave alone.

That result is right and its reason is worth stating, because it hid a defect:
the live lane supplied 36512807 while the guard was silently dropping the
**library's** copy of the same document 80 times. The expectation passed on a
path that happened to be open.

### Failed 3 of 3 — four cases, all on query quality

| case | criterion, quoted | papers |
|---|---|---|
| `apdt-primary-molars` | *esearch returned 2.2 / 2.8 / 4.3 hits/query < 5* — and *58% / 55% / 58% of queries returned nothing (max 50%)* | 122 / 122 / 137 |
| `intentional-replantation` | *3.7 / 3.5 / 0.5 hits/query < 5*; *51% / 53% / 82% empty* | 167 / 183 / 162 |
| `pregnancy` | *0.3 / 0.9 / 2.0 hits/query < 5*; *83% / 66% empty* | 87 / 135 / 108 |
| `sdf-pulp-outcomes` | *2.0 / 1.0 / 2.0 hits/query < 5*; *65% / 70% / 59% empty* | 86 / 89 / 86 |

Not one of them is a route failure, a pool-size failure or the 36512807
expectation. All four are the same criterion: the generated booleans match
nothing at PubMed. Every one still assembled a full pool — 86 to 183 papers —
because the library union carried them, which is the live-default design doing
exactly what it was built to do while the query generator underperforms. **Not
tuned. Not re-pinned.** `pregnancy` and `sdf-pulp-outcomes` are narrow topics
where thin PubMed yield is arguable; `apdt-primary-molars` and
`intentional-replantation` are not, and they are the ones to diagnose first.

Four more failed intermittently: `bisphosphonates` (4.9 vs a floor of 5.0),
`dens-invaginatus` (53% empty), `retreatment-vs-microsurgery` (run 1 only), and
`case-opening-full`, which is the only failure of a different kind — the
clarifier asked 2 questions where 0–1 was expected, twice, and once re-asked
restorability the case description already states.

### Both route readings, side by side

| | inferred from tier `source` | the router's recorded decision |
|---|---|---|
| live | **87 / 87** | **87 / 87** |
| library | 0 | 0 |
| disagreements | — | **0** |

The recorded reading is the router's own printed statement, not a re-derivation
from the pools. Its three values each leave a distinct mark: `live` prints
`actual=LIVE`, `library-forced` prints `[force_route=library]`, and
`library-fallback` cannot happen without a line in
`eval/logs/library_fallback.jsonl` — whose **mtime is 07:56, before the first
run imported at 13:25**. Read with the mtime, as tonight's leak result had to
be.

**The two agreeing is not a vindication of the inferred derivation.** Its blind
spot is a question whose tiers come only from `library-union`, and no case-run
was in that state, so the defect was never exercised. **Zero route artefacts:**
every case-run inferred cleanly as `live`. The derivation is still wrong and is
still to be replaced — it was simply not wrong here.

### The finding: item 3's own guard was blocking current guidelines

The baseline earned its cost here. Across the three runs the guard logged
**778 drop events, and 215 of them (28%) were current documents.**

| key | dropped | the document it blocked |
|---|---|---|
| `AAE-MRONJ-2026` | 81× | PMID 41985837, `current` |
| `COCHRANE-CD005296` | 80× | **PMID 36512807**, `current` |
| `AAE-VPT-2021` | 34× | PMID 34352305, `current` |
| `COCHRANE-CD004969` | 9× | PMID 31145805, `current` |
| `ESE-EXTRUSION-REPLANT-2021` | 4× | PMID 33501680, `current` |
| `AAE-TRAUMA-2026` | 3× | PMID 41941956, `current` |
| `ESE-TRAUMA-2021` | 3× | PMID 33934366, `current` |
| `ESE-ECR-2018` | 1× | PMID 30171768, `current` |

`AAE-TRAUMA-2026` is the document item E's crown-fracture probe watches.
`COCHRANE-CD005296` is the pinned expectation.

**The mechanism is the redirect story wearing a new hat.** When a document is
re-keyed from its manifest slug to its real PMID, the old row stays behind as a
forwarding stub:

```
pmid='COCHRANE-CD005296'   status='current'
quarantine_reason='re-keyed: this document is 36512807'
```

The guard disqualified on `quarantine_reason <> ''`. So the stub qualified, and
the loop added the stub's `pmid` column — which holds the **slug**. The guard
then dropped every row whose `guideline_id` was that slug: the current,
re-keyed document itself. Live lanes were untouched, because a PubMed row
carries no `guideline_id` and only its PMID is checked. **The rows lost were
the library's own copies — the curated documents the union exists to
contribute.**

**A pointer is not a document.** `re-keyed:` and `duplicate_of:` are forwarding
addresses, so a stub is now disqualified exactly when the document it points
*at* is disqualified.

| | predicted | measured |
|---|---|---|
| block set | 54 → 45 | 54 → **45** |
| current guidelines released | 9 | **9** |
| genuine blocks lost | 0 | **0** |

The prediction was wrong once on the way: the first fix released only seven,
because `COCHRANE-CD005296` re-keys onto a row banded **`cochrane`, not
`guideline`**, and a guideline-only lookup could not find it — and an
unresolvable pointer is treated as disqualifying, correctly. Pointer targets
are now resolved across bands. Scanning every row instead is not an option: an
ordinary paper has no `guideline_status`, so a blank status would disqualify
the entire library.

`ESE-PS-VPT-2019` is the case that makes the loosening safe: its stub says
`duplicate_of:30664240`, and 30664240 is `superseded_in_content`, so the old
slug stays blocked. All five of item 3's leaked rows remain blocked.

**12 new tests, on fixtures rather than the database** — including the cycle,
the cross-band target, the four non-pointer quarantine reasons, and a clean
current row as the control arm. The over-block survived for hours in a guard
whose tests all passed, because every one of them asked the database what it
thought instead of asking the rule what it does.

### What the harness does not measure, and did not tonight

**Cost: essentially zero, and the ~$60 authorisation went unspent.** A
retrieval-only pass makes no synthesis calls, and the A55 term cache served 85
of 87 cases, so the entire baseline cost **two LLM term-generation calls**.

**Per-case latency and cost are not instrumented at all.** `run_eval` records
neither, so the median/max the batch asked for cannot be produced from these
runs; the wall clock per run above is what exists. Reported as a gap rather
than filled with an estimate, and queued.

**Answer-level assertions were not evaluated** — `must_contain`,
`must_not_contain`, `banner`, `modules_non_empty` and
`max_unsourced_numeric_modules` are all synthesis-mode checks. v8 measures
retrieval, as v7 did.

`eval/baseline_v8.json` carries the commit, `routing_mode: live-default`, both
route readings, and every failing criterion verbatim.

---

## Item F — rules and logs

- **Rule 42**: code and data are written with the file tools, never a heredoc.
  `tests/test_no_control_bytes.py` enforces it, plus the CRLF corpus check.
- **Rule 41 extended**: a harness reading a ranked list must state its window
  size beside the count.

`tests/test_no_control_bytes.py` **earned its place the day it was written**. It
found two backspace bytes nobody knew about, and one was a live bug:
`tests/test_guideline_text_provenance.py` held `\x08www\.` and `\.org\x08` where
`\bwww\.` and `\.org\b` were intended, so two alternatives of a furniture
detector had **never matched anything** — in a test that had been passing since
the day it was written. Three further heredoc manglings happened while fixing
it, which is the rule restating itself.
