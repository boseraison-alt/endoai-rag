# Endo AI — Outstanding Work List

## 0. Operating rules (read first)

**Authorization.** You are pre-approved to run multiple agents in parallel on independent items, to edit any file in this repo, to run the test suite, to run scripts against the Neon database, and to commit on the working branch. Do not ask for permission to proceed on anything in this list. Ask only when an item says "DECISION" or when an action is irreversible and outside this list's scope (dropping tables, force-pushing, deleting `learn_history/` wholesale, changing Anthropic/NCBI credentials).

**Method — non-negotiable for every item.**

1. Measure before changing. Pull the real number from the audit log, the database, or a live run. Never reason from memory about what the code does — read it.
2. Dry-run every database write. Print the delta distribution split by the dimension the change is supposed to affect (by tier, by design, by route). Apply only if the split matches the prediction.
3. Every new test must be mutation-checked: reintroduce the bug, confirm the test fails, restore. A test that cannot fail is deleted.
4. Fixtures come from real data. Sample real `CoiStatement`, real abstracts, real audit-log rows. Invented fixtures pass for the wrong reasons.
5. Commit work-in-progress on the branch before any `git checkout --`, `git stash`, `git reset`, or file-restore operation. The `app.py` wipe must not recur.
6. One end-to-end run after every batch, read by hand, not just the suite.
7. Cost is not a success metric. A run that costs $0.60 because it retrieved nothing is a failure. Report cost only next to hits-per-query and paper counts.

**Parallelism.** Items marked `[A]`, `[B]`, `[C]` are independent and may run concurrently on separate agents. Items marked `[SEQ]` depend on the item above them. Do not run two agents that write to the same file.

**Reporting.** When the list is done, produce one report: per item, what changed, the before/after number, the test that pins it, and the commit hash. Then the open-questions section (§8 format).

## 1. P0 — Correctness (do first, in this order)

### 1.1 `[A]` Search-term generator instability

**Problem.** `generate_multi_search_terms` returned 1 term and 8 terms for the same question minutes apart. Paper count moved 43 → 92. Every eval number has ±50% noise until this is fixed.
**Likely cause.** JSON parse failure on Haiku output (code fence, prose wrapper, trailing text) falling back to a single term.
**Do.**
- Pull the raw Haiku responses for both runs from the cost log / audit log. Confirm the cause.
- Write a tolerant parser: strip fences, extract the first JSON array, validate each element is a non-empty string.
- If fewer than 4 terms come back, retry once with a corrective prompt; if still fewer, log a warning and continue (never silently proceed with 1).
- Apply the same fix to `generate_search_terms` (Review path) and the syllabus query generator (Learn path).
- Tests: fenced JSON, prose-wrapped JSON, empty array, malformed JSON → all parse or retry correctly. Mutation-check.
**Done when.** Ten consecutive calls for the laser question return between 6 and 10 terms; the eval harness records term count per run and asserts ≥ 4.

### 1.2 `[B]` Live-path supersession (Cochrane versions)

**Problem.** Library path now excludes superseded Cochrane versions via `superseded_by`. Live path has no concept of it; a live question can cite a 2012 version of a review updated in 2020.
**Do.**
- In `_merge_corrections_and_registries`, read `CommentsCorrectionsList` items with `RefType="UpdateIn"` and record `superseded_by` on the paper.
- On the live path, drop any paper with `superseded_by` set if the newer version is also in the batch; otherwise keep it but badge it "superseded — see PMID X" and demote it one tier.
- Share the same badge renderer with the library path (`format_paper_context_line`).
- Test with the CD005296 chain (three generations) as a recorded fixture.
**Done when.** A live-pinned run of the laser question shows zero superseded Cochrane records in the top tier; badge parity test passes.

### 1.3 `[C]` Book records (StatPearls) tiered as Level I

**Problem.** `PubmedBookArticle` records (StatPearls, NBK IDs) are narrative reference chapters. Three sit at Level I. The provenance merge loop iterates only `PubmedArticle`, so they also get no COI/retraction/registry data.
**Do.**
- Parser: detect `PubmedBookArticle`; assign `level_key = level5`, add badge "reference text"; extract what provenance exists.
- Merge loop: iterate both `PubmedArticle` and `PubmedBookArticle`.
- Migration: find every book record in the library (`pmid` with NBK source or `journal` matching StatPearls), set `level5`, rescore. Print the list before applying.
**Done when.** Zero book records above `level5`; e2e test includes one book fixture asserting tier.

### 1.4 `[SEQ after 1.1–1.3 and §2 baseline]` In vitro / ex vivo tier

**Problem.** Bench studies (extracted teeth, dentin blocks, bovine models, capillary tubes) are classified "prospective" and land at Level II. Endodontics is heavily bench-based; this inflates a large share of the library.
**Do.**
- Add `invitro` to `TIER_ORDER` below `level4` (case series) and above `level5`. Update the monotonic-ordering test.
- Classifier: publication type "In Vitro" where present; otherwise abstract cues (`extracted (human|bovine) teeth`, `dentin(e)? (blocks|slices|discs)`, `in vitro`, `ex vivo`, `bench`, `capillary`, `agar`, `biofilm model`). Precision matters more than recall — require two cues or one strong cue.
- Dry-run on the full library: print count per current tier that would move, and 20 random titles per source tier for hand review. Apply only after review.
- Rescore, invalidate cache, re-run both laser eval cases and record the new baseline as a separate baseline version (do not overwrite the pre-tier numbers).
**Done when.** Schulte-Lünzum / Moritz / Hmud are `invitro`; no RCT or cohort moved; e2e asserts an in vitro fixture cannot outrank a case series.

### 1.5 `[SEQ after 1.4]` Tier-relative quality floor

**Problem.** Flat floor of 50 culls entire fields whose best papers score in the 40s by construction (no n, no follow-up, older).
**Do.**
- Replace the flat floor with per-tier floors, or a percentile floor within tier (keep top 60% of each tier, min 3, cap 25). Make it a config dict, not literals.
- Dry-run on the last ten audit-log runs: print papers kept per tier before/after.
**Done when.** Laser eval case retains ≥ 3 `invitro` papers with ≥ 1 above the old floor; no well-covered case (e.g. vital pulp therapy) changes its top-tier set.

### 1.6 `[A]` Retracted rows still tiered

**Problem.** 11 rows tagged `Retracted Publication` remain at `level1`/`cochrane`. Excluded from search, so no exposure, but the bibliography and admin views show them tiered.
**Do.** Migration: set `level_key = retracted` (add to `TIER_ORDER` as terminal, never rendered to Claude), keep `has_retraction = true`. Trivial; do it with 1.3.

## 2. P1 — Eval set (the critical path)

### 2.1 `[B]` Fill `eval/questions.json`
Use the 20 draft questions in §7. For each: `question`, `mode`, `force_route`, `expect` block. Keep the two existing laser cases.

### 2.2 `[SEQ]` Harness completeness
- Runs all cases, both modes where specified.
- Per case records: route taken, queries issued, hits per query, empty-query count, papers per tier, SR count, RCT count, Cochrane count (genuine — journal-verified), validation pass/fail, support-check flag rate, cost, term count, wall time.
- Baselines stored as ranges from three runs, not points. Assertions are floors and forbidden conditions only.
- `python eval/run_eval.py --diff` prints a table against baseline; non-zero exit on any floor breach.
- Add a `--cheap` flag that stops after retrieval (no Opus synthesis) for retrieval-only regressions.

### 2.3 `[SEQ]` Baseline capture
Run the full set three times after 1.1 lands (generator must be stable first). Commit `eval/baseline.json`. This is the reference for 1.4 and 1.5.

## 3. P1 — Presentation (independent of §1; one agent, UI files only)

Do these in order in `templates/index.html` and the renderer. Screenshot each.

3.1 Move the citation-support status and validation warning into the header chip row. Reword "verified" → "Checked against abstracts: N/M consistent". Show "not available" explicitly when the check didn't run.
3.2 Replace "Avg score N/100" chip with an evidence-shape chip: "2 Cochrane · 6 RCT · 14 cohort · 3 case series · 5 in vitro". Counts must equal the bibliography.
3.3 Box the Clinical Recommendation at the top with its tier badge and a "Does not apply when…" line. Render "The literature is currently divided on this topic" as a colored banner, not a sentence.
3.4 Remove IF from reference lines and bibliography rows. Keep it in the abstract popover only.
3.5 Bibliography grouped by tier as collapsible sections, score-ranked within each, top 3 per tier expanded. Provenance badges (declared COI, erratum, pre-registered, non-MEDLINE, superseded, retracted, reference text) render on rows and in the popover. Verify with a COI-flagged paper and a superseded Cochrane row.
3.6 Abstract-only caveat: one line directly under the recommendation box.
3.7 Cost chip behind a toggle (default on).
3.8 Sidebar: a history entry whose cache/archive was purged must not reload as if valid; show "regenerated" or drop it.

## 4. P2 — Hygiene

4.1 `[C]` Admin routes (`/admin/*`, `/cache/clear`, `DELETE /learn_history`) behind a shared-secret header or basic auth. Add to README.
4.2 `[C]` `_merge_corrections_and_registries` must also read `ExpressionOfConcernIn` if not already; confirm badge.
4.3 `[C]` Requirements: pin every dependency; `pip install -r requirements.txt` on a fresh venv must import `endo_ai` cleanly.
4.4 `[C]` X-ray feature: disable behind `ENABLE_XRAY=false` (default off). When on, strip EXIF/DICOM metadata and never send case text with the image. Note in HANDOVER.md that enabling requires a BAA. DECISION already made: off.
4.5 `[C]` HANDOVER.md: add the four recurring bug classes with one-line detectors — (a) tier label trusted from a stored column, (b) untagged/annotated terms in PubMed queries, (c) metadata computed on a batch applied per paper, (d) a check that fails open and shows nothing. Each with the test file that guards it.
4.6 `[C]` Cache: on any rescore or tier migration, invalidate; on write-back that adds ≥ N papers to a topic, invalidate cache entries with cosine ≥ 0.85 to the written-back query.
4.7 `[C]` The 14 library rows with empty `level_key`: classify by hand-review list (print titles), set, rescore.

## 5. Decisions already taken (do not re-ask)

- Write-back of live results into the library: yes, above the quality floor, with full provenance.
- X-ray / vision path: off by default until a BAA exists.
- Abstract popovers: keep; "copyright firewall" claim removed from docs.
- Impact factor: excluded from scoring, displayed only in the popover.
- COI: penalty applied only at rescore from stored `coi_status`; conflict requires a named commercial entity in a non-negated declaration sentence.
- Zero-evidence modules: never render a protocol; broaden once, then "Module not generated".
- Commit style: separate commits per concern; binaries (`.pptx`) gitignored.

## 6. Process rules for the agents

- Branch: continue on `evidence-scoring-provenance` or a child branch per §; never commit to `main`.
- Before any destructive git command: `git add -A && git commit -m "wip: <item>"`.
- Two agents never edit the same file concurrently. §1 agents own `endo_ai.py`/`rag.py`/`scripts/`; §3 agent owns `templates/` and the renderer; §4 agent owns `app.py` auth, `requirements.txt`, docs.
- Every database migration is a script in `scripts/`, dry-run by default, idempotent, printing its delta split.
- Every network-dependent test is opt-in (`RUN_NETWORK_TESTS=1`) and has an offline twin.
- After each § completes: full suite, one live run of the laser question (live-pinned), one library-pinned, read both by hand.

## 7. Draft eval questions (for RB to correct before §2.1)

These are drafts. Correct the expected route and the must/must-not lines from your own knowledge of the library. "Well-covered" = expect `library`; "thin" = expect `live`. Each case also inherits the global floors: ≥ 4 search terms, ≥ 5 hits/query, 0 unsourced numeric protocols, Cochrane tier journal-verified.

**Well-covered (expect library)**

1. Single-visit vs multiple-visit root canal treatment for necrotic teeth with apical periodontitis — must cite Cochrane; must state no significant difference in healing; must not say single visit is contraindicated.
2. MTA vs Biodentine for full pulpotomy in mature permanent teeth with irreversible pulpitis — must cite ≥ 1 SR and ≥ 2 RCTs; must state comparable success; must not claim superiority without a cited effect size.
3. Sodium hypochlorite concentration (low vs high) and outcome of primary root canal treatment — must surface the divided-literature banner or state equivalence with citation; must not recommend a single concentration as evidence-based without an RCT.
4. CBCT vs periapical radiography for detecting apical periodontitis — must state higher CBCT sensitivity with citation; must include the ALARA / selection-criteria caveat.
5. Calcium silicate (bioceramic) sealers vs epoxy resin sealers — outcomes — must cite ≥ 1 SR; must state short follow-up limitation.
6. Nonsurgical retreatment vs apical microsurgery for persistent apical periodontitis — must cite ≥ 1 SR; must present both as viable with case-selection criteria.
7. Vital pulp therapy (direct pulp capping) in cariously exposed mature permanent teeth — must cite ESE/AAE position statement; must state material and rubber dam as determinants.
8. Postoperative pain after root canal treatment: preemptive NSAID vs placebo — must cite ≥ 1 RCT or SR; must give a cited effect direction.
9. Regenerative endodontic procedures in immature necrotic teeth — success and survival — must distinguish survival from true regeneration; must cite AAE considerations.
10. Cracked tooth: prognosis after root canal treatment by crack extent — must state prognosis depends on crack depth/extension with citation; must not give a single survival number without a cited cohort.

**Thin or vocabulary-heavy (expect live)**

11. Lasers in root canal disinfection (existing case — keep both pins).
12. Antimicrobial photodynamic therapy as an adjunct in primary molars with necrotic pulps — expect live; must retrieve ≥ 1 RCT; must not claim superiority over NaOCl without citation.
13. Endodontic management in patients on bisphosphonates / antiresorptives — expect live; must state MRONJ risk context; must not recommend extraction over RCT.
14. Root canal treatment in pregnancy: timing and local anesthetic choice — expect live; must cite a guideline or SR; must not state a trimester rule without citation.
15. Laser-activated irrigation (PIPS/SWEEPS) vs ultrasonic activation — periapical healing outcomes — expect live; must retrieve ≥ 1 SR; divided-literature banner expected.
16. Intentional replantation for teeth unsuitable for surgery — expect live; must cite a cohort or SR with survival; must state extra-oral time as a determinant.
17. Silver diamine fluoride and pulp outcomes in deep carious lesions (adult teeth) — expect live; must state limited endodontic-outcome evidence; must not extrapolate from pediatric caries-arrest data without saying so.
18. Sonic vs ultrasonic irrigant activation — bacterial reduction in vivo — expect live; must distinguish in vitro from in vivo evidence; ≥ 1 `invitro`-tier paper expected once 1.4 lands.
19. Dens invaginatus type III: management — expect live; must cite case series; must state evidence is case-level.
20. Endodontic outcomes in patients with diabetes — healing of apical periodontitis — expect live or library; must cite ≥ 1 SR or cohort; must state association vs causation.

For each, once corrected, add: `mode` (review / learn), `force_route`, and `expect: { min_terms, min_hits_per_query, min_sr, min_rct, must_contain: [], must_not_contain: [], banner: divided|none|any }`.

## 8. Final report format

For each item: Item · Status · Before → After (number) · Test file · Commit. Then:

- **Found, not fixed** — anything discovered outside this list, with a one-line severity.
- **Baseline changes** — every eval baseline that moved, with the cause.
- **Decisions needed** — anything that needs RB, phrased as a yes/no with your recommendation first.
