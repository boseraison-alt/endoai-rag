# SESSION HANDOVER — 2026-09-05 → next

Boot a new coding-agent chat with:

> Read `AGENT_QUEUE.md`, `SESSION_HANDOVER_2026-09-07.md` and
> `HANDOVER_GUIDELINES_2026-09-04.md`. Continue from the ORDER section below.

**Branch `fix/retrieval-blindspot`, tag `retrieval-freeze-20260905`, pushed.**
Suite **2562 passed, 50 skipped, 1 xfailed, 0 failed.** Working tree clean.

---

## 0. STATE BEFORE TOUCHING ANYTHING

- **Ports unchanged for five sessions.** 5000 is ours (pid 49800). **5003 is
  another session's (pid 27692) — never kill it, never use it.** Re-confirmed
  at the end of this batch.
- **THE WARM CACHE IS STILL VOID** and is now voided a second time: the PRISMA
  notice names a different review on ~27 of 29 questions, and the Case
  differential prompt changed. Re-warm anything demo-facing.
- **The v6 baseline has NOT been run.** It is the next batch on its own, 3.5 h,
  against the frozen tag. **The A46 prediction is already committed** —
  `eval/reports/a46_prediction_v6_baseline.md`. Read it BEFORE running, or the
  run is a rubber stamp rather than a test.
- **Backups, both verified:**
  - `C:\Users\boser\endo-ai-backups\endo-ai-rag-20260905-0755.bundle` (batch start)
  - `C:\Users\boser\endo-ai-backups\endo-ai-rag-20260905-freeze.bundle` (at the tag)
  - `C:\Users\boser\endo-ai-backups\db-20260905-0755\` — 14 tables, **22,209 rows**,
    every table live == dumped == re-read

---

## 1. THE ONE THING TO CARRY FORWARD

**A degraded fallback that does not say which of its causes fired will send the
next reader to the wrong subsystem.**

Item 2 unified the PRISMA nomination. The fix looked complete and did not work:
the live path still nominated by year, and the log said *"the question could
not be embedded"*. The question embedded fine. The real fault was that
`fetch_papers` never put `title` or `abstract` on its scored dicts, so there
was nothing to embed — a live-path paper knew its authors, journal, year,
citations, sample size, follow-up and score, and **not what the paper was
called.**

The message was mine, written in the same commit, and it asserted one cause for
three different faults. The backfill loop also swallowed its failures with
`except: continue` — standing rule 5, broken inside a fix for a
silent-divergence bug. Both corrected; the branch now distinguishes *no
question passed* / *no candidate could be given a similarity* / *every computed
similarity was zero*, and the loop counts what it drops.

**The generalisation:** every fallback in this codebase should name which of
its preconditions failed, not that "something" failed.

---

## 2. WHAT LANDED

| item | outcome |
|---|---|
| **1** library floor | **MEASURED, PARKED** — 8 of 29 below the guard vs a threshold of 5 |
| **2** PRISMA nomination | **SHIPPED** — unified on relevance, 23–4 on a blind panel |
| **3** divergences + parity | **SHIPPED** — agreement test + TIER_ORDER checklist test |
| **4** supersession notice | **SHIPPED** — on the successor, render-only |
| **5** ESE-PS-VPT-2019 | **NOT RETITLED** — condition not met; the row carries no PMID |
| **6** freeze | **DONE** — tag `retrieval-freeze-20260905`, prediction committed |
| **D1** recency exemption | **PARKED** — harness built, measurement incomplete |

### The measurement that decided item 1

8 of 29 questions fall below `min_evidence_papers` 40 (6 newly). **The reason
matters more than the count:** the two guards are on different axes and only
one has a rescue. `apply_evidence_floor` runs on SIMILARITY, before banding,
and tops a thin pool back up to 40. A quality floor runs on SCORE, after
banding, over the pool rescue just built — and nothing tops it up again. On
sparse diagnostic questions that reads 40 → rescued to 40 → cut to 26, with no
guard noticing, because `min_evidence_papers` was satisfied upstream by a
different measurement. **It cuts hardest where the corpus is thinnest**, which
is where A5's false evidence gap is manufactured.

Rule 22: the cap alone puts 7 under 40 and the floor alone puts 7 under.
**Neither half is the conservative option** — the thing a future reader would
otherwise assume.

---

## 3. FOUND, NOT FIXED — with severities

- **Four guideline rows still carry hand-set scores. Severity: HIGH, and this
  is new.** `AAE-PS-diagnosis` 90.0, `AAE-PS-vital-pulp` 90.0,
  `ESE-PS-VPT-2019` 87.0, `ESE-QG-2006` 50.4 — unquarantined, citeable, at
  `level_key = 'guideline'`. These are the records the A2 audit **kept**
  because it verified they are real documents; verification settled whether the
  document exists and never touched the score. So the score-as-authority defect
  A49 was built to remove is still live on exactly the four rows kept because
  they are citeable, rendering `Evidence Score: 90.0/100` against the
  Schwendicke Cochrane review's 81.5, while every other guideline row renders
  "NOT SCORED". `39578680` (59.3) is NOT one of these — real accession,
  computed score. **The fix is small and the renderer already exists**: null the
  three hand-scored slugs, dry-run first (rule 2).
- **`ESE-PS-VPT-2019` is a duplicate, not a mistitled record. Severity:
  medium.** PMID 30664240 is already in the library from the verified manifest
  with the verified title, a confirmed accession and a NULL score. So the
  question is "quarantine a duplicate?", not "what should it be called?" — out
  of scope this batch.
- **A non-numeric PMID column holds id-slugs on 49 rows.** This is the
  `[PMID AAE-PS-diagnosis]` leak mechanism, visible in the data. 44 are the
  seed's own guideline records and correct by design; the 5 hand-scored ones
  above are not. **Severity: low as data, high as the source of the leak.**
- **Search-term breadth differs between the curriculum and live paths.**
  Curriculum issues one term set per lane, live issues ~7. Arguably by design.
  **Deferred: needs a cost measurement before it is even a candidate.**
- **D1's n=1 is over threshold** (19 recent papers vs ~15) and costs **+40 s**
  per question. Hypothesis only — rule 27.
- **A pure-live process now pays a sentence-transformer model load** from item
  2's similarity backfill. Once per process, already paid on the library route.
- Everything still open from 2026-09-06 that this batch did not touch: the
  extractor's ~77% recall, `PROVISIONAL_MAX_ADMITTED` below item 1's
  affordability threshold, the Komora xfail.

---

## 4. DECISIONS, WITH THE ALTERNATIVE REJECTED

| decision | alternative rejected |
|---|---|
| library floor **parked** on the pre-declared threshold | shipping it; both readings of the threshold breach, and each half breaches alone |
| PRISMA unified on **relevance** | unifying on year — the panel preferred relevance 23–4; and demoting the library path to the weaker rule |
| the live path gets a **computed similarity** | dropping the library path's cosine to match — that removes the divergence by discarding the better signal |
| similarity computed over **title AND abstract** | title alone — the library indexed `title\nabstract`, and title-only would be a second notion of similarity sharing a name |
| supersession notice on the **successor** | citing the superseded document with a caveat — D2, and the successor is what actually renders |
| the noun **dropped** when an identifier does not resolve | the ORDER's literal wording — Cochrane `.pub2`/`.pub3` are versions, not statements |
| `ESE-PS-VPT-2019` **not retitled** | matching it to 30664240 by year and organisation, which is the inference being cleaned up |
| D1 **parked** | implementing on n=1, which is over its own threshold and would put an unmeasured retrieval change into the freeze |
| the checklist scans the **enclosing function** | a fixed line window, which called a correct site a defect |

---

## 5. ORDER FOR THE NEXT SESSION

1. **Run the v6 baseline against `retrieval-freeze-20260905`.** 3.5 h, its own
   batch. **Read the A46 prediction first**, then compare — anything that moves
   and is not predicted is the signal.
2. **Null the three hand-set guideline scores** (§3, first item). Small,
   contained, dry-run first, and the "NOT SCORED" renderer already handles the
   result.
3. **Finish D1's measurement** (~3 h) and decide. Test-pins still owed if it
   ships.
4. **The library floor needs a design, not a batch** — the three options are
   written up in `eval/reports/library_floor_29.md` §"Why the threshold is the
   right call". Option 3 (route sparse questions live) is the one to put to RB
   first: existing gate, right axis, fails safe — but it trades cost on the
   demo path.
5. Re-warm the demo cache. A51 stays blocked on the baseline.

---

## 6. REPLAY — every number in this handover

```
python scripts/measure_library_floor_29.py --json eval/reports/library_floor_29.json
python scripts/measure_prisma_nomination.py --json eval/reports/prisma_nomination.json
python scripts/measure_early_stop_recency.py --json eval/reports/early_stop_recency.json
python scripts/measure_library_route_floor.py          # the corpus-side number
python scripts/dump_db.py <outdir>                     # verified DB backup
```

Reports: `library_floor_29.md`, `prisma_nomination.md`, `path_divergences.md`,
`ese_ps_vpt_2019.md`, `early_stop_recency.md`,
`a46_prediction_v6_baseline.md`.

**Run the suite bare (`python -m pytest`), never `pytest tests/`.**
`pytest.ini` sets `testpaths = tests presentations`, and naming `tests/`
silently drops 126 presentation guards — the exact fail-open its own comment
warns about. I did it once this batch and read 2419 as green.
