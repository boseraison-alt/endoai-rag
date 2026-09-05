# SESSION HANDOVER — 2026-09-05 (instrument + guidelines) → next

Boot a new coding-agent chat with:

> Read `AGENT_QUEUE.md`, `SESSION_HANDOVER_2026-09-09.md` and
> `HANDOVER_GUIDELINES_2026-09-04.md`. Continue from the ORDER section below.

**Branch `fix/retrieval-blindspot`, pushed. Tag `retrieval-freeze-20260905b`
still describes the frozen retrieval; the prompt changed after it (item 3).**
Suite **2579 passed, 50 skipped, 1 xfailed, 0 failed.** Working tree clean.
`eval/baseline_v7.json` is the current baseline, now WITH the provisional lane.

---

## 0. STATE BEFORE TOUCHING ANYTHING

- **Ports unchanged for seven sessions.** 5000 ours (pid 49800). **5003 is
  another session's (pid 27692) — never kill it, never use it.**
- **Run the suite BARE.** `testpaths = tests presentations`.
- **The prompt changed after the freeze tag.** Item 3 added the guideline block
  to `ask_clinical_question`'s system prompt. Retrieval is unchanged, so the
  v7 retrieval baseline still stands, but any *answer-level* comparison against
  a pre-2026-09-05 answer is comparing two prompts.
- **Backup:** `C:\Users\boser\endo-ai-backups\endo-ai-rag-20260905-1210.bundle`
  (verified, complete history). No DB writes this batch.

---

## 1. THE ONE THING TO CARRY FORWARD

**Scope is part of a checklist's correctness, and "repo-wide" is only half of
it.**

The `TIER_ORDER` checklist test listed `SOURCES = ("app.py", "endo_ai.py")` —
the two files its author had open. It saw **6 of the 25** `TIER_ORDER` loops in
the repository and passed while `eval/run_eval.py` dropped every provisional
paper from `per_tier` **and** from the `papers` total, in every baseline the
harness had ever produced.

Widening it to the whole repo was necessary and **not sufficient**. Scoping
each hit to its **enclosing function** let a mutation SURVIVE: `run_case` holds
three `TIER_ORDER` sites with three different dispositions, so one site's
comment vouched for the site that had none — the test passing its own mutation
check while blind to the exact bug it exists to catch. The working unit is
**per site**: from its own comment block down to the next site's comment block.
A neighbour's reason is not this loop's reason.

Both halves are now standing rules 35 and 36.

---

## 2. WHAT LANDED

| item | outcome |
|---|---|
| **1** harness sees the lane | **DONE** — plus 2 more blind spots in the same file; checklist now repo-wide, 25 sites |
| **2** guideline lane vs empty-fraction | **DONE** — excluded from the denominator, own reported metric, ceiling untouched |
| **3** why guidelines go uncited | **DONE** — one line; A/B passed 5 of 5 |
| **4** D1 full measurement | **MEASURED, NOT SHIPPED** — both thresholds breached |
| **5** standing rules 35, 36 | **DONE** |

### The v7 re-fold matched its pre-declaration exactly

No re-run was needed. The summary line excluded provisional, but the lane
printed what it admitted, so `baseline_from_log.py` recovers it from the log
body — **only when `per_tier` does not already carry the lane**, which is
self-correcting rather than dated. Pre-declared and matched: laser-live 5/5/5,
retreatment 1/1/2, cracked-tooth 1/9/14, apdt 0/0/1,
intentional-replantation 0/1/0, case-opening-sparse 26/40/40. Totals 33/56/62.
Six of 29 questions carry a provisional paper.

### Item 3's answer, in one line

The synthesis prompt enumerates the tier ladder **twice** — as a tier-order
instruction and as the literal set of EVIDENCE SUMMARY headings — and
**neither list mentioned guidelines**. The model was handed a guideline block,
told to write under named headings, told to skip levels with no relevant
evidence, and given no heading a guideline could go under. Same defect class as
`app.py`'s hardcoded lane list: an enumeration that drifted behind retrieval.

A/B with retrieval held constant (one retrieval, same evidence object
deep-copied to both arms): guideline citations **5 → 8**, questions with ≥1
**3/5 → 5/5**, total citations 49 → 56, cost +4.7%.

---

## 3. FOUND, NOT FIXED — with severities

- **The guideline lane's topic query is trial-shaped. Severity: HIGH, and this
  is the next item.** The lane inherits the study lanes' narrow generated topic
  string, and a guideline is broad by construction. Verified against PubMed:
  **ESE-S3-2023 (PMID 37772327)** and **ESE-REVITALISATION-2016 (PMID
  26990236)** are both indexed AND both match the lane's `guideline[pt]`
  filter, and the lane returned nothing on the two questions they answer. So
  the 86% empty rate is the **query shape, not the corpus** — three of five
  hand-checked empty questions are correctly empty (the specialty has published
  nothing on irrigant activation or laser disinfection), two are real misses.
- **31 of 56 citeable guideline rows carry a slug id, not a PMID. Severity:
  HIGH.** The prompt requires `[[PMID:nnnnnnn]]`, so those rows **cannot be
  cited at all** on the library route — the route that answers most warm
  questions. Invisible in the live-subset A/B, because live-fetched guidelines
  have real PMIDs. Needs an id-scheme decision, not a prompt change.
- **Three more lanes are missing from the prompt's heading list.**
  `observational` (populates 18 of 29 questions), `classic`, `invitro`. Only
  the guideline lane was changed, deliberately, so the A/B attributed cleanly.
  **The same one-line fix almost certainly applies to all three.**
- **A cold live-only process now pays ~10.4 s** for the embedding-model load
  that item 2's PRISMA backfill introduced. One-off per process; the server
  pays it once and the library route already did.
- Still open and untouched: the library floor (parked, two-guard design needs
  RB), the extractor's ~77% recall, the Komora xfail.

---

## 4. DECISIONS, WITH THE ALTERNATIVE REJECTED

| decision | alternative rejected |
|---|---|
| checklist scoped **per site** | enclosing function (let the mutation survive) and a fixed window (false positive) |
| re-fold from log bodies | re-running three baselines to recover a number that was already recorded |
| recover provisional **only when absent** | always adding it, which double-counts post-fix logs |
| guideline lane **out of the denominator** | lowering the 50% ceiling — rule 6 |
| lane keeps a **reported** metric | dropping it from the assertion and stopping measuring it — rule 32 |
| prompt says what guidelines **are** | "cite guidelines", which produces irrelevant citations |
| only the guideline heading added | adding all four missing lanes at once, which would have made the A/B unattributable |
| **D1 not shipped** | shipping on a breach of both declared thresholds |
| lexicon variant narrowed | moving the entry to `rejected`, which would record a false claim — the device term still has 0 occurrences |

---

## 5. ORDER FOR THE NEXT SESSION

1. **Give the guideline lane its own topic query.** §3, first item. It is the
   largest single source of wasted retrieval (22% of all queries, 86% empty)
   AND the cause of two named misses. Measure before/after across the 29; the
   two PMIDs above are the regression fixtures.
2. **Decide the guideline id scheme.** 31 of 56 rows cannot be cited. Options:
   mint a citable form the prompt accepts, or restrict the library guideline
   tier to PMID-bearing records and serve the rest as pointers.
3. **Add the three missing headings** (`observational`, `classic`, `invitro`)
   and A/B them the same way item 3 was A/B'd.
4. Re-warm the demo cache — the prompt changed, so every stored answer predates
   the guideline block.
5. The library floor still needs its two-guard design
   (`eval/reports/library_floor_29.md`).

---

## 6. REPLAY

```
python eval/run_eval.py                                  # retrieval-only
python eval/baseline_from_log.py --out eval/baseline_v7.json --label "..." eval/logs/v7freeze_run{1,2,3}.log
python scripts/ab_guideline_prompt.py --json eval/reports/a49_guideline_citation_ab.json
python scripts/measure_early_stop_recency.py --json eval/reports/early_stop_recency.json
```

Reports: `a49_guideline_citation_ab.md` (item 3),
`guideline_lane_empty_fraction.md` (item 2), `early_stop_recency.md` (D1),
`a46b_baseline_v7_outcome.md`, `library_floor_29.md`, `path_divergences.md`.
