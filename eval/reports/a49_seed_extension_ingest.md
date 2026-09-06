# A49 seed extension (commit 6444752) — ingest report

**Date:** 2026-09-06 · **Base:** `6444752` · **Manifest:** 60 → 99 records, 22 → 31 orgs

---

## Step 1 — PREDICTIONS, written before the dry run

*Committed before `scripts/ingest_guidelines_seed.py` was run even in dry mode.
A46: a prediction after the fact is a rubber stamp.*

### P1 — how many of the 23 new confirmed PMIDs are already in the paper table

**My prediction: 2–6.** The batch's prediction is 3–8; I am predicting slightly
lower and the reason is the mechanism, not a hunch.

A PMID gets into `endo_papers_rag` two ways: the original corpus build, or
**live write-back**. Write-back is `LIBRARY_WRITE_BACK = False` in every eval
run by design (`run_eval.run_case` sets it), so the 29-question eval set — which
is where nearly all recent retrieval traffic has gone — has deposited nothing.
That leaves the original build plus demo/production runs, and the demo set is
predominantly VPT, irrigation, retreatment and diagnosis, not trauma.

Against that: the **guideline lane** was broadened yesterday (item 2 of the
previous batch) and now returns something on 28 of 29 questions rather than 6,
so any production run since then had a much better chance of pulling an IADT
guideline in. That is why I am not predicting 0–2.

### P2 — which PMIDs specifically

Same shortlist as the batch, and for the same reason: the IADT series is the
only new material that is both PubMed-indexed and squarely inside the
endodontic query space.

| likelihood | PMIDs |
|---|---|
| **most likely** | 32460393 (IADT avulsion 2020), 32475015 (IADT fractures/luxations 2020) — avulsion and crown fracture are live eval/demo topics |
| plausible | 22409417, 22230724 (the 2012 pair), 32472740 (IADT intro 2020) |
| less likely | 32458553 (IADT primary dentition — paediatric, outside the corpus's centre), 22583659 (2012 primary) |
| wildcard | 16702591 (Woo 2006) — Ann Intern Med, not a dental journal, so `ENDO_DOMAIN_FILTER` should have kept it out |

**I predict Woo 2006 is NOT present**, which is where I differ from the batch's
shortlist. It is in *Annals of Internal Medicine*; every lane query is
`AND ENDO_DOMAIN_FILTER`, and a general-medicine bisphosphonate review is
unlikely to have satisfied it.

### P3 — which tiers the hits sit in

**My prediction: `guideline` or `level5`, and I expect `guideline` to dominate.**

The reasoning is specific rather than a guess: `level_key` was backfilled from
PubMed publication types, and the IADT 2020 papers carry `Practice Guideline`
as a pubtype (verified indirectly — the guideline lane's filter is
`practice guideline[pt] OR guideline[pt] OR consensus development conference[pt]`
and yesterday's fixture check showed two ESE guidelines matching it). A row
whose pubtype maps to a guideline should have been banded `guideline`.

If any hit turns up at **`level1` / `level2` / `cochrane`**, that is not a tier
question — it means the PMID is wrong on our side, and the batch's stop rule
applies.

### P4 — the stop conditions

I predict **none of them fire**: no hit in `{cochrane, level1, level2}`, fewer
than 12 rows marked, and every `superseded_by` target resolving inside the
manifest.

---

*Everything below this line was written after the measurement.*
