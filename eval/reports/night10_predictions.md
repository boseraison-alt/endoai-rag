# Batch 2026-09-08 — predictions, committed before any write

Phase 0: bundle `endo-ai-rag-20260907-night.bundle` records a complete history;
`db-20260907-night/` holds 3435 rows against 3443 live — the difference is the
8 live write-backs the running server made from real traffic, identified and
accounted for on 2026-09-07, not a backup failure. Fresh dump
`db-20260908-pre/`, 14 tables, 27,603 rows, all verified.

Item F first half: `main` fast-forwarded `ae20d3e` → `fa5ca1f` (110 commits).
Tag `main-before-ff-20260908` at `ae20d3e`. Both pushed.

---

## Item A

1. **Of the 23 PMID-keyed pointer rows, how many carry a PubMed abstract?**
   The batch predicts 16–19, with the five AAOM Clinical Practice Statements
   and ESE-QG-2006 as the likely blanks. I predict **the same range but a
   different blank list**: AAOM statements are short practice statements and
   are the obvious candidates, but `17899726` (Gen Dent, "use of biopsy in
   dental practice") and `16383047`/`20516097` (JADA council reports) are also
   the shape that PubMed indexes without an abstract. Recorded so the blank
   list is checked rather than the count alone.
2. **DOI resolution.** 9 records tried. I predict **3–6 resolve with a
   title match**. `ACP-PARAMETERS-OF-CARE-2020` is pre-declared as a
   no-match (the only PubMed hit is an editorial) — if it *does* match, that
   is a signal my normalisation is too loose, not a win.
3. **Retire count** = the number of DOI matches whose slug row exists, and the
   dry run must equal it exactly.

## Item C

4. **Term-group stability across 5 runs of 10 questions.** I predict
   **below 40%** identical. A54 measured three runs of one probe returning
   three different guideline pools, and the generator is a temperature-default
   Haiku call.
5. **`generate_search_terms` is NOT already at temperature 0.** If it is, this
   whole item's first change is a no-op and I say so.
6. **Guideline-pool Jaccard across runs: below 0.6.** Study-pool Jaccard
   higher — the study lanes AND three groups, so they are less sensitive to
   one group changing.
7. **Admission rules (a)/(b)/(c):** I predict **(a) alone fails 3/3 on probe
   2** (A54 measured its pool swinging run to run), **(b) alone passes both
   probes** and has the smaller median block, and **(c) passes but with a
   larger median**. Pre-declared acceptance is median ≤ 8, max ≤ 25.
8. **Residual pool difference with the cache warm** — PubMed's own ranking
   noise, separated from term noise for the first time. Predicted **10–20% of
   pools**, well below the 24% (61/256) measured on 2026-09-06 when both
   sources of noise were present.

## Item D

9. **Per-writer error on 30 adjudicated rows.** I predict **abstract-extraction
   is wrong more often than pubtype**, and that **"definitional" is the largest
   single bucket** — the two writers labelling the same design differently
   rather than either being wrong. If definitional dominates, the honest
   recommendation is that neither writer's error rate justifies a reband.
10. **"off-ladder 185"** — I predict these are rows whose derived tier is a key
    outside `LADDER` (`guideline`, `invitro`, `classic`, `observational`,
    `retracted`), i.e. moves that leave the study ladder entirely.

## Item E

11. **Backfill: exactly 81 rows labelled**, matching the 2026-09-07 count.
12. **The species guard on the paper lanes loses zero human rows.** If any
    human row is lost the guard is reverted — that is the pre-declared stop.
13. **Harm realised**: stored answers citing one of the 81 with no species word
    in the citing sentence. Predicted **5–20**.

## Item F2 — a conflict I will not resolve silently

The batch says: replace the two legacy rows' abstracts with pointer text and
set `abstract_source = "pointer"`, and pins "no row carries
`model_summary_legacy` after this item".

**What shipped on 2026-09-07 is different and stronger.** Both rows were
RETIRED: quarantined, `redirect_to` set to their manifest records, and their
citations rewritten at serve time — 10 stored answers for `AAE-PS-vital-pulp`,
22 for `AAE-PS-diagnosis` now resolve to `AAE-VPT-2021` and
`AAE-DIAGNOSIS-2009`. The rows keep their label precisely because
`quarantine_reason` is the undo.

So the batch's pin is unsatisfied only in its letter: **zero CITEABLE rows
carry a model-written summary**, and the two that carry the label are
unreachable by retrieval or citation.

I will do the batch's write **on top of** the retirement — replace the
abstract with pointer text and set `abstract_source = "pointer"` — because it
removes the paraphrase text itself rather than only hiding it, which is the
stronger reading of the standing rule. The retirement and the redirects stay.
Predicted: **2 rows**, no change to `quarantine_reason` or `redirect_to`, and
one test of mine needs its query repointed (rule 39).

---

## Item C — measured, then predicted again (2026-09-08)

**Prediction 4 was right and far too generous.** I predicted "below 40%"
identical across 5 runs. Measured on 10 real eval questions: **0/10** identical
query strings, **0/10** identical AND-group sets, mean pairwise group Jaccard
**0.135**, and 9 of the 10 questions produced 5 distinct queries in 5 runs.
Retrieval in this system has never been reproducible.

**Prediction 5 confirmed.** `generate_search_terms` passed no `temperature`, so
the API default applied.

**New prediction, committed before the after-measurement is run.** Temperature 0
will raise the identical-string rate sharply but **not to 100%** — served LLM
sampling is near-deterministic at temperature 0, not guaranteed, and batching
can still change a token. I predict **60–90% identical strings** and mean group
Jaccard **above 0.9**. If it reaches 100% I will say so; if it stays below 60%
then temperature is not the dominant source and the cache is doing all the
work, which changes what item C's cache is for — from an optimisation to the
only thing standing between an A/B and noise.
