# Batch 2026-09-09 — predictions, committed before any change

Phase 0: origin verified current at `3224b76`; last night's bundle records a
complete history; fresh dump `db-20260909-pre`, 15 tables, 27,714 rows. The ACP
re-key applied — dry run and apply both **1 insert, 1 retire, 1 text carry-over,
census delta 0**, with the slug's 2,155 characters of `org_page` text carried to
`32681591`. Stranded text after: 0. Total rows 3,462.

## Item A — live by default

1. **Route: LIVE 32/32.** By construction. I will verify rather than assume,
   because "by construction" is how the coverage gate came to be trusted for a
   year while declaring coverage it did not have.
2. **Missing-live fraction 0** — also by construction, and the A55 harness
   should confirm it. If it does not, the harness and the router disagree about
   what "the live set" is, and that is the finding.
3. **Pool size grows on nearly every question.** The union of live lanes and
   library rows is a superset of either. I predict the median pool roughly
   **doubles**, and that the growth is largest on the questions A55 found most
   badly covered.
4. **Fixture recall: the 8 A54 fixtures reach 6–8 by the per-PMID test but
   fewer in the assembled pool**, because the assembled pool is subject to the
   0.55 similarity floor and per-tier quotas that the raw query is not. F3 is
   the specific one I expect to fail the floor rather than the query — it did on
   2026-09-08. For the 3 VPT fixtures I predict **3/3 present**.
5. **Latency: median 40–75 s, max above 90 s.** A55 measured 73.9 s and 40.6 s
   on two questions; a 32-question set will have a worse tail. Spend per
   question ~**$0.006** on retrieval, and I expect the total to be dominated by
   the questions with the most lanes returning results.
6. **The builder-agreement test is the one most likely to break**, because this
   change makes the two builders take the same path for the first time. If it
   fails I will repair to the property, not re-pin.

## Item B — reband stage 1

7. **B1, the agreements.** The adjudication found 92 of 272 decidable rows where
   the two writers agree. Not all of those differ from the stored tier. I
   predict **40–70 rows actually move**, and that the largest single (from → to)
   bucket is **`level3a → invitro`**, because that is the largest disagreement
   bucket and the agreements will follow the same distribution.
8. **B2, the population rule.** Rows with a bench/animal abstract signal sitting
   on the clinical ladder: I predict **60–120**. The 2026-09-08 animal count was
   86 with 9 on the clinical ladder, but B2's signal is broader — it includes
   *in vitro*, *ex vivo* and *extracted teeth*, which are far more common in this
   corpus than animal work. **Bench rows move; animal rows stay labelled where
   they are**, per the 2026-09-08 decision.
9. **B3.** Guideline pubtypes with a manifest record → `guideline`. I predict
   **fewer than 15** such rows, and **more than 20** guideline-pubtype rows with
   no manifest record, which go to `manifest_candidates.md` and are never
   `level1`.
10. **B4.** F5 (cohort) → `level3a`; F6 (n=24 RCT) → `level1` or `level2`;
    F7 → `invitro` under B2; F8 → `invitro` under B2.

## Item C — animal labels at render time

11. **48 → 0 unlabelled at render**, and I predict the render-time count of
    *labelled* citations comes out **above 48**, because the finaliser sees
    every citation including ones in sentences that already name a species (it
    should not double-label those — if my count of "already labelled" is wrong
    the appended text will read oddly and I will say so).

## Item D — v8 baseline

12. **Pass count falls or is flat versus v7's 19/21/19.** The evidence base
    changed under 27 of 32 questions and the route changed under all of them;
    a baseline that improved would more likely mean the criteria are measuring
    the retrieval mode than the answer. **I will not tune toward the number.**
13. **Contamination 0.** Anything else is a stop.
14. **Cost per run above $15**, given `ask_clinical_question` averages $0.75 and
    21 questions now all take the live path.

## Item E — the crown-fracture probe

15. **Admitted by scope on 3/3 for both** `AAE-TRAUMA-2026` and
    `IADT-FRACTURES-LUXATIONS-2020`, now that the manifest scopes name crown
    fracture. This is the direct test of the 2026-09-08 claim that the manifest,
    not the matcher, made the done-when unreachable. If it still fails, my
    diagnosis was wrong and the report says so.

## Item F

16. `tests/test_no_control_bytes.py` finds **zero** control bytes today — the
    backspace incident was repaired on 2026-09-08 — and the CRLF check passes
    on this checkout because `.gitattributes` now marks the corpus `-text`.
    A zero here is only meaningful beside the file count, which is reported.

---

## Item 3 — superseded / withdrawn / draft / quarantined in the guideline block

Committed before measuring, and before reading the admission code.

**Which path I expect to be the leak, in order:**

1. **The live guideline lane.** It queries PubMed and scores what comes back.
   A superseded IADT 2012 guideline is a real, indexed, unretracted PubMed
   record — nothing about it looks wrong to a query — and the lane has no
   reason to consult our manifest or our `quarantine_reason` column, because
   those are facts about OUR library and the lane is not reading our library.
   This is where I expect most of it, and it explains the observed case:
   `IADT-FRACTURES-LUXATIONS-2012` and `IADT-AVULSION-2012` both appeared.
2. **`admit_scoped_guidelines`.** It filters on the MANIFEST's `status ==
   "current"`, which would stop a superseded record — but I do not expect it
   to check the ROW's `quarantine_reason`, which is a different fact stored in
   a different place. `ESE-QG-2006` is quarantined by A2 *and* superseded by
   the manifest, so it should be stopped by the status filter; if it got
   through, the status filter is not being applied where I think it is.
3. **Item A's union — I expect this to be CLEAN.** It goes through
   `rag.search`, which already excludes retracted, withdrawn and superseded
   rows. If the union is a leak, my reading of `rag.search` is wrong and that
   is the more important finding.

**Counts.** Of the 32 questions I predict **more than half** carry at least one
non-current row in the guideline block, because both IADT 2012 documents are
indexed and highly relevant to any trauma question. I predict the total
distinct offending rows is **small — under 15** — and dominated by the IADT
2012 series plus `ESE-QG-2006`.

**What "closing it at the source" should mean.** Not a filter bolted on after
assembly: the check belongs wherever a guideline row is admitted, so every
path inherits it. If I find myself adding the same condition in three places,
that is the wrong fix and the right one is a single admission gate.
