# COMPLETE — tag grounding-v1, all items done, suite green (1269 passed)

Batch `grounding-v1`, run overnight 2026-08-31 → 2026-09-01. Nothing blocked.
Every item finished, tree clean, pushed, tagged, bundle refreshed and verified.

Read `CURO_HANDOVER.md` next — it has the state, the invariants and the next
batch. This file is the batch's own report.

---

## Per item

| Item | Status | Before → After | Test file | Commit |
|---|---|---|---|---|
| **1a** Truncating ingest sites | Done | 6 sites capping stored abstracts → 0 | `tests/test_abstract_ingest.py` (9 tests) | `9899059`, `b2cf7c5` |
| **1b** Re-fetch and heal | Done | 1,342 truncated → **1**; mean abstract **1,182 → 1,631** chars | `scripts/repair_truncated_abstracts.py` (dry-run gated) | `caac725` |
| **1c** Re-embed | Done | 1,355 changed rows → **1,355 re-embedded (exact match)** | — | `caac725` |
| **1d** Rescore + cache invalidation | Done | 80 of 2,334 scores moved; every tier median **+0.0**; 11 cached answers invalidated | `scripts/score_delta_by_tier.py` | `6876832` |
| **2** Re-baseline as v6 | Done | 25 cases × 3 runs, **25/25 each**; flag rate **8.5% → 4.3%** | `eval/baseline_v6.json`, `eval/logs/v6_run{1,2,3}.log` | `dbe9ac6` |
| **3** DL citation support | Done | 0 modules checked → **every module**; first ever measurement 20.3% and 11.2% | `tests/test_curriculum_support.py` (20 tests) | `4764c2b` |
| **4** MEDIUM/LOW sweep | Done | see below | `presentations/test_deck_rules.py`, `tests/test_webdeck.py`, `tests/test_citation_validation.py` | `78e2413`, `fdacea2`, `62b0ff4` |
| **5** Demo assets | Done | 6 answers + curriculum + web deck + PPTX regenerated and hand-verified | `DEMO_RUNBOOK.md` re-timed | `60e941a` |

**Item 4 detail.** `_unit_of` now takes the unit of the number actually
plotted (it returned "months" for `"12 mm at 3 months"`); a real three-arm
comparison from a stored answer drives both exports as
`tests/fixtures/multi_arm_stat_panel.json`; `_extract_claim_citation_pairs`
now ends a claim at a bold pseudo-heading and no longer splits after `vs.` or
`et al.`; `case_convs` deleted.

**Headline.** Citation-support flag rate on the three measured library Review
cases: **39.4% (26/66) two batches ago → 8.5% (5/59) → 4.3% (2/46)**.

## Found, not fixed

| Severity | Finding |
|---|---|
| **HIGH** | The synthesis prompt still has no grounding rule — it mandates a `[[PMID:N]]` on every claim and never says what to do when no paper supports one. The remaining known mechanism for a decorative citation, and the one that applies on the LIVE path. Queued as §5[A]. |
| **HIGH** | The "longest paragraph" heuristic in `ingest_classics.py:219-232` and `app.py`'s `/api/abstract` keeps only the longest paragraph of an abstract. Same data-loss class as the truncation just fixed, different mechanism, untouched by that fix. Queued as §5[B]. |
| MEDIUM | 112 rows returned nothing from efetch during the repair. 4 genuinely have no abstract in PubMed (verified individually); the other **108 were not investigated**. Queued as §5[C]. |
| MEDIUM | The repair backed up the old ABSTRACTS but not the old EMBEDDINGS, so the pre-repair vectors are unrecoverable. Same mistake this repo already records about the first Cochrane migration. Only mostly reconstructable, because the corpus builders used three different embedding-text conventions. |
| LOW | 8 library rows have an empty `title`, which now reaches the prompt as a blank line. |
| LOW | `narration.strip_markdown_for_speech` does not strip blockquotes; a raw-narration path would read the citation-support blocks aloud. No live path is affected. |
| LOW | Deep Learning modules flag at 11–20%, well above Review's 4.3%. Nobody has looked at why. Queued as §5[D]. |

## Baseline moves, v5 → v6

Ten metrics left their v5 range. **Six are on the four cases that had ONE
observation in v5** — comparing a point with a three-run range. All 25 cases
now have three runs; that class of noise is gone.

The two real ones, neither a regression:

- **`sdf-pulp-outcomes` (live) 32-46 → 26-29.** The v5 range was inflated by a
  single atypical run in which the early stop did not fire and every tier was
  swept (`{level1:8, level2:15, level3a:8, …}` against `{level1:33}` for the
  others). v6's three runs are tightly clustered. Live-pinned, so nothing done
  to the library can reach it.
- **`direct-pulp-capping` (library) 38-39 → 35-35.** Two candidate causes
  eliminated by measurement — not the similarity floor (325 papers clear 0.55
  for this question) and not the tier quality floor (6 crossings, 4 of them
  upward). The cause is the fixed top-100 KNN candidate pool: re-embedded rows
  now rank higher (median similarity 0.6175 vs 0.6130; 69 vs 28 above 0.65 in
  the top 300), so they occupy more of the 100 slots and displace the marginal
  papers that had been filling the smaller tiers. `level1` is cap-bound at 25
  and absorbs none of it, which is exactly where the loss shows. Precision
  bought with a little recall; all floors still pass. If that recall is ever
  wanted back, `limit=100` is the dial, not the floor.

## Decisions taken

1. **The ~$0.70 library answer is permanent** (RB-approved; recorded in
   `HANDOVER.md` with the rationale — the $0.36 path was writing clinical
   answers without the papers' content). *Rejected:* trimming cost by sending
   fewer abstracts. If cost must fall, take it out of paper COUNT or tier caps,
   not out of whether the evidence sent has content in it.
2. **Re-embed on `title\nabstract`**, the convention `rag.learn_from_live_results`
   already uses. *Rejected:* keeping the corpus builders' `title + abstract[:400]`,
   which would have left the library on two conventions permanently, and
   inventing a third. The retrieval effect was measured immediately afterwards
   by baseline v6 rather than assumed.
3. **Rescore deferred until Lane C had landed**, so it ran against a stable
   `endo_ai.py` rather than a half-edited one. *Rejected:* running it
   concurrently — a half-applied edit to `score_paper` would have been silent.
4. **Ran all 25 eval cases ×3, not the 21 the brief asked for.** It costs the
   same wall time and it retired the `cases_with_one_run` flag on the four
   cases added last batch. *Rejected:* running 21 and leaving four cases on a
   single observation for another batch.
5. **`case_convs` deleted, not wired up.** The client re-sends the whole
   conversation each turn and the evidence base is rebuilt from the latest
   follow-up, so a cached turn-1 base would answer turn 3 from the wrong
   literature. *Rejected:* wiring it to a sources panel — `job.papers` already
   serves that, the way Review does.
6. **`_extract_claim_citation_pairs` fixed even though a previous measurement
   said it did not matter.** The re-measurement reversed it: merged claims are
   flagged LESS (37.6% vs 50.8%, p=0.002), because a longer blob gives the
   judge more surface on which to find something supported. The defect was
   suppressing the guardrail.

## Cost

**$12.22** across 323 API calls (eval runs, the synthesis subset, and the demo
regeneration at $6.43 of it). PubMed: ~2,350 records re-fetched over 12 batched
efetch calls, plus the eval runs' searches.

## Verification

- Full suite: **1,269 passed, 39 skipped**, exit 0.
- Every new test mutation-checked; 47 mutations across the batch, all killed
  their test. Two tests were found useless by mutation and tightened.
- Hand-verified on the freshly generated deck, not assumed: 36 abstracts
  embedded at a median of **1,836 characters** (old cap 1,200); all 20 raw
  `[[PMID:N]]` markers inside `<aside class="notes">`, which invariant 3
  exempts, and **0 on any rendered surface** across 234 text shapes on 22 PPTX
  slides; the chart slide plots 53.14% and 42.44% with PMID 36823417 in the
  footer, all three verbatim in the source answer; all six regenerated answers
  carry their citation-support status.
- The repair script is **idempotent and resumable** — confirmed by re-running
  the dry run after the apply: 0 rows would change.

## Bundle

`C:\Users\boser\OneDrive\Desktop\endo-ai-rag_backup.bundle`

```
The bundle records a complete history.
The bundle uses this hash algorithm: sha1
```

## Suggestions (not implemented — no scope was taken)

- `multi_query_search`'s `limit=100` is now the binding constraint on recall
  for library questions, not the similarity floor. Worth measuring what 150
  does to paper counts and to the flag rate before assuming either direction.
- The four "Antibiotic use for irreversible pulpitis" Cochrane rows each
  dropped 6.7 points because the healed abstract revealed n=40. That is the
  scoring model working, but it is worth asking whether a Cochrane review's
  participant count should weigh as heavily as a primary study's.
- Three ingest scripts embed on `title + abstract[:400]` while the write-back
  path embeds on the full text. The library is now converging on the latter by
  attrition. Making it explicit would be a one-line change and a re-embed.
