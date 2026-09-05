# SESSION HANDOVER — 2026-09-05 → 2026-09-06

Boot a new coding-agent chat with:

> Read `AGENT_QUEUE.md`, `SESSION_HANDOVER_2026-09-06.md` and
> `HANDOVER_GUIDELINES_2026-09-04.md`. Continue from the ORDER section below.

**Branch `fix/retrieval-blindspot`, 20 commits, `f503285..75054dd`, pushed.**
Suite **2536 passed, 50 skipped, 1 xfailed, 0 failed**.
Working tree clean. Base of the branch is still `ae20d3e` on `main`.

---

## 0. STATE YOU NEED BEFORE TOUCHING ANYTHING

- **Working tree is CLEAN at `75054dd`** and the branch is pushed.
- **The one remaining xfail is Komora 39117767, and it is deliberate.** It
  records that `evidence_floor` 0.60 cut a network meta-analysis by 0.0193.
  Do not "fix" it by moving the floor — the floor is on the do-not-change
  list and one paper is not a basis.
- **Two servers are up. Port 5000 is ours (pid 49800). Port 5003 is another
  session's (pid 27692) — never kill it, never use it.** Re-confirm the pids
  before any run; this has been true for four sessions and is still true.
- **THE WARM DEMO CACHE IS NOW VOID.** `query_cache` holds 20 rows. This
  batch changed retrieval on every path and rendering on several, so every
  stored answer would now render through code that did not produce it.
  Anything demo-facing must be re-warmed. Do not assume the 2026-09-04
  Literature/Curriculum rows still represent current output.
- **Library state:** 3,405 rows; 60 guideline records from the verified
  manifest; 17 quarantined (12 from the A2 audit + 5 withdrawn/draft from the
  seed).
- **Backups from the start of this batch, both verified:**
  - `C:\Users\boser\endo-ai-backups\endo-ai-rag-20260904-2143.bundle`
    (4.55 MB, "complete history", HEAD `f503285`)
  - `C:\Users\boser\endo-ai-backups\db-20260904-2143\` (14 tables,
    **21,586 rows**, every table `expected == written == reread`)

---

## 1. THE ONE THING TO CARRY FORWARD

**A helper can be right while one of its two callers never calls it, and every
test can pass.**

There are two evidence-base builders — `endo_ai.build_evidence_base` (the
curriculum path) and `app.build_evidence_base_with_progress` (the LIVE path
for Review and Case). They are separate implementations of the same idea, and
`app.py` carried its **own hardcoded copy** of the tier-lane list that had
fallen **three lanes behind**:

| lane | added | never reached Review or Case |
|---|---|---|
| `observational` | A31 | the only filter admitting cross-sectional, morphometric, imaging and diagnostic-accuracy designs |
| `guideline` | A49 item 5, **the previous night** | the entire point was that a guideline had no query that could reach it |
| `provisional` | A49 item 4b | — |

`test_observational_tier` and `test_guideline_lane` check
`tier_query_lanes()`. `test_provisional_lane` drives
`endo_ai.build_evidence_base`. **All correct, all green, all blind to it.**
I reported item 5 as landed. It was landed on one of two paths.

It was found by asking *which call sites reach this function*, not by a test.
That question then found four more sites for the same lane, and a divergence
audit found eight further behaviours present on one path and absent from the
other. **`grep -n "in TIER_ORDER" app.py endo_ai.py` is the checklist**, and
`tests/test_live_path_lane_parity.py` is that question written down.

---

## 2. WHAT LANDED

### The five ORDER items

| # | outcome |
|---|---|
| **1** design extraction | threshold **cleared** — max 30 level2-or-above per query vs 60 pre-declared. The filter removes 88.7% of the untyped pool (1,454 → 164) |
| **2** build 4b | **built**; Sulaiman's xfail flipped to a pass |
| **3** conflict gate | wired into `finalise_answer_text`; **33 of 36** curricula fire, 3 silent, idempotent, both directions clean |
| **4** ingester + seed | narrowed; 60 records ingested; guideline tier 9 → 53; cochrane 21 → 21 |
| **5** `context_block` | audited — **not a production defect**; applied exactly once on all five paths, now pinned |

### The biggest defect found, which was not in the ORDER

**The live path showed Claude 26% of the evidence it retrieved.** `_run_tiers`
accumulated `level_scored` across ~7 search terms but kept only the *first*
term's text block, and `_build_evidence_context` renders `block["text"]`.

```
  level1      73 scored,  3 in the prompt   70 never shown
  TOTAL       99 scored, 26 in the prompt   -> 26.3%
  header said: "Total papers: 80 | Avg score: 62.2"
```

That is the **A5 false-evidence-gap mechanism itself** — the answer can state
that no study addresses X while that study sits in `scored` — and it was
**non-deterministic**, because `raw[lk]` is appended in `as_completed` order,
so which term survived depended on which HTTP round trip finished first. The
same question asked twice could answer differently.

Now **100.0%**, with the per-tier cap moved onto the deduped list so the quota
is what `MODE_TIER_QUOTAS` actually says (level1 73 → 18).

### One lane, five wiring sites

`PROVISIONAL_KEY`'s absence from `TIER_ORDER` is what makes the lane safe — it
can never take a tier slot — and exactly what makes it invisible to every
`for tier in TIER_ORDER` loop. **The safety property and the failure mode are
the same fact.** All five fixed and pinned:

`endo_ai.build_evidence_base` · `app.build_evidence_base_with_progress` ·
`app.build_differential_evidence` merge · `endo_ai.merge_evidence_bases` ·
`endo_ai.stitch_curriculum` reference list

### Eight more divergences between the two paths

Cross-tier dedup missing on the curriculum path (the same paper rendered under
two contradictory tier labels in one prompt); `TIER_FETCH_DEPTH` and `mode`
not forwarded on the live path; `seen_pmids` not seeded with the Cochrane
tier; `detect_outliers` never running on the curriculum path; live-fetched
guidelines carrying no org/status/jurisdiction (so a **superseded** guideline
was indistinguishable from the current edition); and a dead `question=`
parameter of my own implying a relevance gate that does not exist.

---

## 3. TWO WITHDRAWN NUMBERS — READ THIS BEFORE TRUSTING ANY REPORT

**`eval/reports/a49_untyped_recent_4a.md` now carries a withdrawal banner.**
Its median of 426 is wrong; the real figure is **26**.

The script called `generate_search_terms`, which returns the primary query as
a **string**, then sliced it `terms[:4]` — four **characters**. It also
dropped `ENDO_DOMAIN_FILTER`. It was measuring *"recent papers anywhere in
PubMed matching a single character"*: the pool held celery genomics,
vanadium-oxide catalysis and Chinese health policy in Africa, and `retmax=200`
hid it by pinning every total near 600.

**Item 5's guideline-lane volume figure (200–396/query) is withdrawn for the
same defect.** Item 5's *conclusion* stands — it rested on EFCD-ESE-ORCA being
unreachable, measured against PubMed's own admission, not through that script.

Found by **reading the abstracts the extractor could not classify**, not by
re-checking the count. That is the only reason it was found.

---

## 4. THE DOMAIN FACT THAT BROKE THE EXTRACTOR

> **`RCT` in endodontics means ROOT CANAL TREATMENT.**

Not "randomised controlled trial". Ten independent judges audited the first
design extractor: **34% false-admission rate**, and that single token promoted
a retrospective cohort (40509940), a case report (40213509), a diagnostic
cohort (39880187) and a cross-sectional questionnaire of 90 dentists
(40729775) to Level I.

After two fix rounds the rate is **15%**, with recall ~77% and **zero level1
papers missed**. Three audit rounds are written up in
`eval/reports/a49_design_extraction.md`, including the fix that **round one
introduced** (making a self-declared trial self-evidencing removed the
location check, so a four-patient case series ending *"randomized controlled
trials are warranted"* was admitted at level1).

**Sulaiman 42388091 is not an RCT.** Its abstract says *"this single centre,
one-arm clinical trial"*; `randomis`/`randomiz`/`randomly` do not occur in it.
It is admitted at **level2**, truthfully, and is now retrieved **and cited** in
the VPT curriculum.

---

## 5. ORDER FOR THE NEXT SESSION

1. **The library route has no per-tier quality floor.** This is the largest
   open defect and it is measured, not suspected — see §6. It needs a
   before/after across all three modes and it has a trap that will bite a
   careless fix. **Start here.**
2. **Re-warm the demo cache.** Every stored answer predates this batch's
   retrieval and rendering changes.
3. **A51 is now unblocked** — 4b has landed, so a contradiction query can
   reach the newest literature instead of hitting the tier-filter wall. Its
   design questions (load-bearing definition, hit-rate measurement) still need
   a session RB is awake for.
4. **The v6 three-run baseline is still deferred and should stay deferred**
   until the library-route floor is settled — that change would void it.
5. A22e, A44c (attended sessions only), the A37 gate distribution at n≥5.

---

## 6. FOUND, NOT FIXED — with severities

- **The library route applies no per-tier quality floor at all.**
  `_apply_quality_threshold`, `_tier_floor`, `_tier_cap` and
  `MODE_TIER_QUOTAS` have **no caller in `app.py`**. Measured against the live
  library: **516 of 3,346 rows (15.4%)** are served below their own tier's
  floor, including **42 papers scoring 40.4–49.9 rendered under "Level I —
  RCTs and Systematic Reviews"**. The cap is a flat 25 against the live path's
  18 for level1 and 4 for the weak tiers, so eight weak tiers can contribute
  25 each against level1's 25.
  **Severity: high — this is the route that answers most warm questions.**
  **THE TRAP:** 48 guideline rows store `score` NULL *by design* (A49 item 4)
  and `rag_results_to_scored` coalesces that to 0.0, so bolting a quality
  floor on naively **deletes every guideline from library-served answers**.
  Replay: `python scripts/measure_library_route_floor.py`.
  The false comment claiming parity **is** fixed; the behaviour is not.
- **The review-mode early stop skips the `observational` lane.** I exempted
  `guideline` (a specialty position is a different axis, not weaker evidence);
  `observational` is genuinely the weakest rung so the early stop's reasoning
  does apply to it. But it is the only lane admitting diagnostic-accuracy and
  morphometric designs, and it is skipped on exactly the well-covered
  questions clinicians ask most. **Severity: for RB's judgement.**
- **Superseded guidelines are excluded from retrieval rather than cited with
  a supersession notice.** Stricter than item 4b asked for. All four
  successors are present in the library, so the clinician gets the *current*
  document — which achieves the clinical intent more strongly — but the
  historical record is lost. **Severity: this is the one place I did less than
  the ORDER asked.**
- **`ESE-PS-VPT-2019`'s stored title names a third document.** It resolves to
  ESE-DEEPCARIES-2019 but is titled *"Outcome of Primary Root Canal
  Treatment"*. Kept citeable (one of the four A2-verified) and deliberately
  **not** retitled — choosing a replacement title would be inventing
  bibliographic data. **Needs RB.**
- **Design-extractor recall is ~77%**: ~42 genuine level2 papers turned away
  across 858 rejections. **Zero level1 missed.** Eight of nine misses are
  abstracts where *no pattern fires at all* — the extractor matches design
  LABELS, never DESCRIPTIONS. The obvious fix ("read the title") was tested
  **on the code** and is a **no-op**: the title is already in the haystack.
  **Severity: bounded, ~1.4 papers per question.**
- **PRISMA dedup nominates by YEAR on the live paths and by RELEVANCE on the
  library route** — a documented asymmetry that picks different reviews on 26
  of 29 questions. **Severity: known, self-disclosed in the code.**
- **`PROVISIONAL_MAX_ADMITTED` (40) sits below item 1's affordability
  threshold (60).** The threshold test is unaffected — it applies no cap and
  its max was 30 — but the lane can never admit more than 40 however good
  recall becomes. Recorded in the constant's comment.

---

## 7. DECISIONS TAKEN, WITH THE ALTERNATIVE REJECTED

| decision | alternative rejected |
|---|---|
| Sulaiman admitted as **level2**, not RCT | matching the batch's stated premise — which would mean inventing a design the authors never claimed |
| Deleted `\bRCT\b` from the level1 patterns | keeping it; in endodontics it means root canal treatment |
| Design claims scoped **by sentence** | another keyword — a keyword is what broke it in round one |
| Library-route floor **measured, not fixed** | fixing it at 01:00 without a before/after; the naive fix deletes 48 guidelines |
| Cochrane manifest records **enriched, not reclassified** | letting the manifest decide where a systematic review sits on a study-design ladder (would have moved 3 real reviews from tier 100 to tier 12) |
| Guideline `score` stored **NULL**, rendered "NOT SCORED" | rendering the coalesced 0.0 — "no score" must not read as "scores zero" |
| Superseded guidelines **excluded** | a cite-with-notice path whose render guarantee could not be verified in one night |
| `question=` parameter **removed** from the lane | documenting it — a parameter naming a safety property that is never read is worse than none |
| Provisional papers kept **out of `all_scored`** | adding them; `score=None` breaks every average that reads it |
| The lane **never writes back** to the library | persisting it — a stored row carries a `level_key`, and MEDLINE will classify these within months |

---

## 8. MY OWN INSTRUMENT ERRORS THIS SESSION — read these, they recur

Four, all the same shape. The project's count is now in double figures.

1. **The mutation harness poisoned `__pycache__`.** `shutil.copyfile` does not
   preserve mtime, so a restored file could look *older* than the `.pyc`
   compiled during the mutated run and CPython reused the **mutated
   bytecode**. Caught only because a live PubMed query went out asking for
   `"last 60 months"` while the source on disk said 18. The harness now
   touches the file and clears `__pycache__`. **Any run in that window
   measures mutated code while the diff looks clean.**
2. **I ran the full suite in the background and then kept editing the files it
   reads.** Seven tests that tokenise source slices failed with
   `unterminated string literal`. They pass in isolation; a clean run is
   green. I would have misread it as a regression.
3. **A source-grep test matched the construct inside the fix's own comment**
   quoting it, and reported the bug as still present.
4. **A mutation survived because my tests exercised the helper and not the
   caller** — the identical shape to the bug the whole file was about,
   committed while fixing it. A wiring assertion was added.

Also: the mutation harness replaces only the **first** occurrence, so a
mutation can silently hit the wrong call site and report SURVIVED. That
happened once and was retargeted rather than recorded as a pass.

---

## 9. OPEN, NEEDING RB

- **The library-route quality floor** (§6) — the trap makes this a decision,
  not just a task.
- **`ESE-PS-VPT-2019`'s title.**
- **Whether superseded guidelines should be citeable with a notice** rather
  than excluded.
- **Whether `observational` should survive the early stop** the way
  `guideline` now does.
- Everything still open from 2026-09-04: rotate the three keys, the *Rung* /
  *Yardstick* trademark search, the quarantine block colour, the lexicon's
  `reviewed_by_rb: false`, and **Hoang's PMID or DOI** — still not supplied,
  still correctly excluded from the fixtures and still test-pinned.

---

## 10. REPLAY — every number in this handover

```
python scripts/measure_design_all29.py --json eval/reports/a49_design_all29.json
python scripts/measure_design_extraction.py            # the 1c control
python scripts/measure_untyped_recent.py               # corrected 4a
python scripts/measure_provisional_lane.py --mode review
python scripts/measure_provisional_lane.py --mode learn
python scripts/measure_live_text_gap.py                # the 26% -> 100% finding
python scripts/measure_live_path_lanes.py
python scripts/measure_conflict_gate.py
python scripts/measure_numeric_conflicts.py
python scripts/measure_library_route_floor.py          # the open defect
python scripts/ingest_guidelines_seed.py               # DRY RUN; --apply to write
python scripts/quarantine_unverified_guidelines.py     # DRY RUN; --restore to undo
```

Reports: `eval/reports/a49_design_extraction.md`,
`a49_provisional_lane.md`, `a51a_numeric_conflicts.md`, and
`a49_untyped_recent_4a.md` (**withdrawn — banner at the top**).
