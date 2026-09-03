# SESSION HANDOVER — 2026-09-02 evening → 2026-09-03

Boot a new coding-agent chat with:

> Read `AGENT_QUEUE.md`, `SESSION_HANDOVER_2026-09-03.md` and `CURO_HANDOVER.md`.
> Continue from the ORDER section below.

28 commits, `77867e1..c295a11`. Suite **1951 passed, 50 skipped**. Spend across
the session **$19.64** over 426 model calls.

---

## 1. THE ONE THING TO CARRY FORWARD

**Seven queue premises were overturned by measurement this session — two of them
mine.** This is now standing rules 21–24. It is the most useful fact in this file.

| item | the premise | what was actually true |
|---|---|---|
| A5b | three papers absent from the library | two were present; the per-tier cap was cutting them **by score** |
| A23 / A24 | the four curriculum modules share one query set | they already retrieve separately; the tier **taxonomy** could not express an anatomy paper |
| A32 | the authority guarantee needs redefining | it could never fire at all, and its eight unit tests passed only because they called it with `relevant=[]` |
| A33d | the query was under-specified | it was **over**-specified |
| A33d follow-up (**mine**) | dropping the ceramic group recovers the papers | two variables changed at once; the **vocabulary** did the work |
| A35 | Curo refuses to descend below level1 | it cites levels IIIa/IIIb/V at ~2× level1's rate |
| A35a → A35f (**mine**) | 70% level1 / four fifths uncited = a level1 precision defect | a **denominator effect**: level1 supplies 59% of all citations |

Every one was diagnosed from a symptom rather than an instrumented mechanism.
Measure the mechanism before building.

---

## 2. WHAT LANDED

**UI — A19, A20, A21.** Layout rebuilt to the Curo Search Modes canvas; the real
Curo mark; tagline **Evidence-Based Dental Educator**; History became a collapsed
drawer; one composer with the mode chips docked inside it; three "what you get"
cards per mode; a follow-up composer and New topic on every answer in every mode;
a progress clock that ticks on its own timer so a stalled poll cannot make the
page look dead. Literature no longer interviews. Curriculum asks **only** to
narrow a topic too broad to teach from.

**Retrieval — four membership decisions corrected (standing rule 19).**

- `rag.search`'s `ORDER BY (score*0.6 + similarity*40)` → pure relevance. Score
  carried 60 of the 100 available weight on a `LIMIT` that decides who enters the
  candidate pool at all.
- The library per-tier cap → `cap_by_relevance`, logging what it drops.
- The live `_apply_quality_threshold` cap → PubMed's own relevance order, via a
  new `pubmed_rank` recorded before the score sort destroys it.
- `ensure_authoritative` → **deleted** (A32). It had never fired once.

**Taxonomy — two new tiers.** `observational` (A31): cross-sectional,
morphometric, imaging and diagnostic-accuracy designs were unreachable by *any*
tier query — 46% of the most relevant apicoectomy papers could not be retrieved
at all. `guideline` (A7): 21 rows rebanded out of level1, where AAE/ESE
statements at score 90.0 were **evicting trials** from the candidate pool.

**Eval — A30d.** 28/29 twice. 33 metrics moved: 17 cases retrieve ~3.2× more (the
membership fixes), 4 retrieve fewer (term-generation variance, A14).

---

## 3. STATE AND TRAPS

- **Servers.** Yours runs on **5000**. A second server on **5003** belongs to
  another chat and is on `77867e1` — *before this entire session*. Do not demo
  from it.
- **Rule 9 is easy to break.** The first eval run carried 22 contamination
  warnings from two Flask servers left running. Stop every local server before an
  eval: the harness excludes foreign PIDs, but the NCBI rate limiter is shared.
- **DB.** Library 3,035 rows. `guideline` 21 rows, backed up in
  `endo_papers_rag_tier_backup_a7`. Toia 2022 (`34555421`) ingested for A5b.
- **`learn_history/` is a live test fixture.** `test_narration` reads the NEWEST
  laser curriculum there, so any eval run changes what that test sees. That is how
  a real narration bug surfaced (the single-bracket `[PMID: N]` reference form was
  being read aloud letter by letter). Do not pin the fixture without reading why.
- **Heredocs mangle backslashes** in this shell. Use the Write tool for any patch
  script containing a regex or an escaped newline.
- **Curriculum runs take 5–6 minutes and buffer their log.** A quiet log is not a
  hung run — check the last row of `cost_log.jsonl` instead.

---

## 4. ORDER FOR THE NEXT SESSION

1. **A33h-i + A33g, both halves** (approved, not started). The generator labels
   each AND-group `subject` / `scenario` / `qualifier`; relaxation drops only the
   declared qualifier; position becomes a legacy fallback. Labelling measured
   **4/4** against a clinician versus trailing-order's 3/4 — and the disagreement
   is the laser query, where trailing order would drop the **scenario**. Plus
   A33g's vocabulary half: the scenario group needs its own OR-expansion.
   Recovery is **0/4 relaxation alone, 0/4 vocabulary alone, 2/4 both**. 2/4 is
   the target to beat, not the finish line — say which two are still missing and
   why.
2. **A33i** — justify surveys-in-the-observational-tier on the apicoectomy
   evidence alone, or drop it. It is no longer justified by the GIC fixture.
3. **A33c** — ingest `42444634` (2026 Cochrane, direct coronal restoration of
   permanent posterior teeth). Dry-run first. `35097115` (de Araújo) is also
   absent and is the other half of A33b.
4. **A33e** — retrieved-but-uncited distribution by tier; the fixtures are now in
   the repo at `eval/fixtures/gic_access_ceramic_{curo,oe}.md`.
5. **A34** — journal balance. A34b is the decisive number: is JOE
   under-represented *relative to what PubMed returns for the same queries*?
   Library skew → A34c additive ingestion, no scoring change. Retrieval skew →
   report with numbers and **stop for RB**.
6. **Re-baseline v6** from 3 runs, v5 kept, the explanation committed beside it.
   Mean similarity moved 0.551 → 0.635 while mean score fell 78.3 → 61.0; that is
   why the ranges moved, and it is an improvement rather than drift.
7. Then **A26**, and **A25a** with materials/bench counted as its own question
   class.

---

## 5. OPEN, NEEDING RB

- **The laser-live synthesis failure.** Reproducible — 2 and 3 uncited-numeric
  sections on two runs. **A31 and A24b are both exonerated** by bisect. Remaining
  suspects: A30a's live cap, or a pre-existing generation defect this fixture has
  always been able to catch. One more curriculum run (~$2) would settle it.
- **`BROADEN_THRESHOLD` is deliberately unset.** It is applied to ONE tier's
  esearch count, not the final pool, and that transfer is unmeasured. The ~24
  floor is arithmetic, not a setting.
- **The ~20-reference target may not be reachable without padding**, which A35d
  forbids. Three supply-side explanations are now eliminated: synthesis already
  descends (A35a), level1 is not imprecise (A35f), and pool size does not buy
  citations (A33j — the rate ranges 2.2%–82.4%, and *bigger* pools cite at lower
  rates). Answers cite ~9–11 of ~35 available. Whether that is too few is a
  synthesis-judgement question, not a supply question.
- **A7's scoring inconsistency stands.** Hand-ingested guidelines carry 90.0,
  PubMed-indexed equivalents 30.9–50.4. Banding fixed the ordering; the score
  disparity is a separate decision under A12.
- **`sdf-pulp-outcomes`** fails only inside a full eval run and passes 3/3 in
  isolation. Unattributed, filed to A14.
- **A5b's Schwendicke branch is CLOSED** — it was the KNN ordering, not a
  vocabulary miss. Older queue text still says otherwise in places; rule 24's
  archive pass should catch it.
