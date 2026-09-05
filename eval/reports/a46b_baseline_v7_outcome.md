# A46b — the baseline against the prediction

**Date:** 2026-09-05 · **Tag:** `retrieval-freeze-20260905b`
**Prediction:** `eval/reports/a46_prediction_v6_baseline.md`, committed before the run.
**Baseline:** `eval/baseline_v7.json` — 29 cases × 3 runs, retrieval-only.
**Logs:** `eval/logs/v7freeze_run{1,2,3}.log`, `v7freeze_live_synth.log`,
`v7freeze_lib_synth.log`.

---

## Contamination — the gate the batch put first

| run | contamination warnings | foreign-pid rows | cases passed |
|---|---|---|---|
| 1 | **0** | **0** | 19/29 |
| 2 | **0** | **0** | 21/29 |
| 3 | **0** | **0** | 19/29 |

Ports were re-confirmed before each run: 5000 = pid 49800 (ours), 5003 =
pid 27692 (**not ours, untouched**).

**A first attempt at run 1 reported 7 warnings and was stopped, as instructed.
It was not contamination.** All 7 were on live-pinned cases; library cases,
which issue no PubMed queries, never tripped it. The pid check — the real
detector, which *excludes* foreign rows rather than guessing — reported zero
foreign rows on all 29, and the audit log confirms a single writing process
during the window.

The `n_terms` counter measures "level1 audit records" and calls it "search
terms". Two things that postdate it write a level1 record that is not a term.
Measured on that run's own records: of **131** level1 records, **77** were
terms, **48** were `[broadened]` re-queries of a term already counted, and
**6** were the `early_stop` marker, which is not an esearch call at all. A
7-term case counted 14 and tripped a >10 threshold.

The logic was fixed, not the bar (rule 6), and the exclusions enumerated from
the label forms the log actually contains (rule 17). Verified on `pregnancy`:
14 → 7 terms, warning gone.

**And the false warning was hiding real failures.** A "contaminated" case skips
every esearch-based assertion. With the counter corrected, `pregnancy` fails
two — 3.9 hits/query against a floor of 5, and 26 of 32 queries returning
nothing against a ceiling of 50%. The first attempt's "27/29 passed" was partly
seven cases not being fully checked. Corrected, the three runs pass 19–21.

---

## The eight declared surprises

### 1. Provisional citations at zero across all 29 — **NOT DETERMINABLE**

Not a result, and the reason is a finding in its own right.

`run_eval.py` builds `per_tier` with `for tier in TIER_ORDER`, and
`PROVISIONAL_KEY` is deliberately not in `TIER_ORDER`. **So the eval harness
cannot see the provisional lane at all** — the baseline records it as absent
and the `papers` total excludes it.

The lane is not idle. The same run logs show it admitting papers on nine
questions: `111 of 174`, `147 of 400`, `15 of 30`, `8 of 21`, `8 of 23`,
`3 of 13`, `2 of 8`, `0 of 2`. Rule 34 exactly — fires-never and
matches-nothing look identical from outside, and only measuring the input
separates them.

This is **the same bug class this entire batch has been chasing**, now found in
the eval harness. My item-3 checklist test scans `app.py` and `endo_ai.py`; it
does not scan `eval/`. Not fixed here: changing the harness mid-baseline would
void the three runs it just produced.

### 2. Guideline citations at zero on the live path — **NEARLY, AND IT MATTERS**

**1 guideline citation across 5 live Review questions** (PMID 30720860), out of
66 distinct cited papers. Predicted: **1–4 per question**. Observed: **0.2 per
question**.

The lane is working — it retrieved 1–4 guidelines on 4 of the 5 cases, and 21
of 29 questions have a populated `guideline` tier. So this is not a retrieval
failure. **The evidence reaches the prompt and is almost never cited**, which
is the prompt-side reading the prediction named, and it stands whether the true
figure is 0 or 1.

### 3. level1 counts on live cases not falling — **DID NOT HAPPEN (predicted correctly)**

They fell hard, to the quota exactly:

| case | v6 level1 | v7 level1 |
|---|---|---|
| dens-invaginatus | 81.0 | **18.0** |
| case-opening-sparse | 91.0 | **18.0** |
| laser-root-canal-disinfection-live | 72.7 | **10.0** |
| cracked-tooth-prognosis | 63.0 | **18.0** |
| bisphosphonates | 54.0 | 14.3 |
| retreatment-vs-microsurgery | 43.3 | **18.0** |

`MODE_TIER_QUOTAS["review"]["level1"]` is 18 and six cases land on exactly
that. The cap moving onto the deduped list is confirmed on the path the eval
exercises.

### 4. Library counts moving more than ~10 — **HAPPENED, AND THE MISS IS MINE**

**13 of 14 library cases with a v6 counterpart moved by more than +10.
Mean +48.0.** I predicted "+0 to +8" and named >10 movement on ~10 cases as the
signal that "something else changed the library route and I did not notice".

Nothing unaccounted-for shipped. **My own prediction contradicted itself.** Its
§1 table says A5b/A30b give "papers UP, ~3.2× on library-routed cases"; its §2
then predicted "+0 to +8" because "retrieval is unchanged this batch". Both
sentences are about a different question: §2 predicted movement *since the last
batch*, and the reference point is `baseline_v6`, recorded **2026-08-31**,
which predates A5b, A30b, A31, A7, A42 and the `level_key` backfill.

The per-tier data says where it came from, and it is not level1:

| tier | v6 | v7 (bioceramic-vs-resin-sealer) |
|---|---|---|
| level1 | 25.0 | **25.0** (flat — item 1 did not ship) |
| level2 | 4.0 | 15.7 |
| level3 | 3.0 | 23.3 |
| level3a | 3.3 | 20.7 |
| level4 | 0 | 10.3 |
| level5 | 0 | 11.7 |
| invitro | 0 | 18.7 |
| guideline | 0 | 0.7 (new lane) |
| observational | 0 | 0.7 (new lane) |

level1 is pinned at the flat 25 in both, exactly as predicted. Every weak tier
filled up. **I cannot attribute that to one change from this data** (rule 22) —
A42's 40-paper rescue, the `level_key` backfill that gave weak-tier rows a tier
at all, and corpus growth to 3,405 rows all land between the two baselines.
The honest statement is that v6 is a stale reference point, not that a single
mechanism did this.

**The lesson is about the prediction, not the code:** a prediction has to name
its reference point. Mine named the changes correctly and then measured them
against the wrong "before".

### 5. Mean citations below 14 — **HAPPENED ON THE LIVE PATH ONLY (13.2)**

Splitting by route changes the verdict, and the split is the finding:

| route | distinct papers cited | predicted | verdict |
|---|---|---|---|
| **live** Review (5) | 23, 24, 8, 7, 4 — **mean 13.2** | 16–24 | **below range** |
| **library** Review (3) | 18, 20, 16 — **mean 18.0** | 16–24 | **in range** |
| **curriculum** (2) | 36, 39 — **mean 37.5** | 30–42 | **in range** |

Two of the three routes landed inside the predicted range. Only the live path
missed, and it missed because its evidence base is now the smallest of the
three.

Live-path synthesis, 5 Review questions:

| case | papers | citations | synthesis cost |
|---|---|---|---|
| retreatment-vs-microsurgery | 40 | 23 | $0.87 |
| bisphosphonates | 41 | 24 | $0.98 |
| cracked-tooth-prognosis | 30 | 8 | $0.85 |
| pregnancy | 18 | 7 | $0.45 |
| intentional-replantation | 18 | 5 | $0.44 |
| **mean** | **29.4** | **13.4** | **$0.72** |

Predicted 18–26. **This is the prediction's most important failure**, and the
mechanism is visible in the table: citations track the size of the evidence
base almost linearly (40→23, 41→24, 30→8, 18→7, 18→5).

I predicted the 26%→100% visibility fix would dominate. It shipped **together
with** the per-tier quota moving onto the deduped list, which cut level1 from
~73 to 18. Rule 22: two variables moved at once, and I credited the outcome to
one of them. **The cap's reduction outweighed the visibility gain.** Whether
that is a bad trade is a real question this baseline cannot answer — the 18
papers are the *most relevant* 18 rather than an arbitrary 18, and 5 of 104
claim-citation pairs were flagged (4.8%) against 39.4% before the abstracts
fix.

### 6. Cost per Review question above $0.40 — **HAPPENED, ALL EIGHT**

| route | synthesis cost | predicted |
|---|---|---|
| live Review (5) | $0.44–0.98, mean **$0.72** | $0.10–0.22 |
| library Review (3) | $1.07–1.40, mean **$1.20** | $0.10–0.22 |
| curriculum (2) | $1.18, $1.19, mean **$1.19** | $1.10–1.60 ✅ |

Every Review question on both routes exceeded the $0.40 surprise threshold, by
3× to 6×. **The curriculum prediction was accurate**, which is the useful
control: the cost model was not wrong in general, it was wrong about Review.

The prediction said a jump to $0.40 "would mean synthesis retries (A45), not
retrieval". **That inference is not supported.** Cost tracks evidence-base size:
the library Review cases carry 60–96 papers and cost ~$1.20, the live ones carry
18–41 and cost ~$0.72. Bigger prompt, higher cost — no retries needed to explain
it. I predicted Review cost from a era when a Review answer saw ~35 papers; it
now sees 60–96 on the library route.

Totals: live subset **$5.26**, library subset **$8.64**, both including the
citation-support checker.

### 7. Case differential citations not rising — **NOT MEASURED**

Needs `--case-subset`, which did not fit in the window alongside three baseline
runs and two synthesis subsets. Named here so it is not mistaken for a null
result.

### 8. `distinct_pmids_retrieved` unchanged on a live route — **DID NOT HAPPEN**

Every live case moved, all but one downward (mean −44.4). Nothing was
unchanged, so the three added lanes are reaching every live question.

---

## Summary of the eight

| # | surprise | outcome |
|---|---|---|
| 1 | provisional citations zero | **not determinable — harness is blind to the lane** |
| 2 | guideline citations zero (live) | **effectively yes: 1 per 5 questions vs 1–4 predicted** |
| 3 | level1 not falling | no — fell to the quota, as predicted |
| 4 | library counts moving >10 | **yes, 13 cases — my prediction's reference point was wrong** |
| 5 | mean citations below 14 | **yes, 13.4** |
| 6 | Review cost above $0.40 | **yes, all five, mean $0.72** |
| 7 | Case citations not rising | not measured |
| 8 | live retrieval unchanged | no — every live case moved |

**Four of eight surprises fired.** Two of those four (4 and 6) point at defects
in the prediction rather than in the code; two (2 and 5) are real findings
about the system and are the ones worth acting on.

---

## The five questions that moved most from v6, attributed

`baseline_v6` was recorded **2026-08-31** and predates A5b, A30b, A31, A7, A42
and the `level_key` backfill. It is a stale reference point, and that is itself
the main lesson of surprise 4.

| case | v6 | v7 | delta | route | attribution |
|---|---|---|---|---|---|
| case-opening-sparse | 171–220 | 73–76 | **−121** | live | per-tier quota on the deduped list (level1 91 → 18) |
| laser-root-canal-disinfection-live | 156–182 | 63–75 | **−100** | live | same; level1 72.7 → 10.0 |
| bioceramic-vs-resin-sealer | 37–40 | 128–142 | **+97** | library | weak tiers filling: level4 0→10, level5 0→12, invitro 0→19, level3 3→23 |
| regenerative-immature | 37–39 | 109–123 | **+78** | library | same shape: level4 0→22, level3a 6→25 |
| direct-pulp-capping | 35–35 | 110–110 | **+75** | library | same shape, plus guideline 0→5.3 |

**The two directions have different causes and both are intended.** Live cases
fell because the quota now applies to the deduped list, so level1 is capped at
18 instead of accumulating ~73 across search terms. Library cases rose because
every weak tier is populated where v6 had zeros.

I cannot attribute the library rise to a single change from this data (rule 22):
A42's 40-paper rescue, the `level_key` backfill that gave weak-tier rows a tier
at all, and corpus growth to 3,405 rows all land between the two baselines. The
honest statement is that three things changed together and the total is ~3.2×,
which matches the figure already recorded for A5b/A30b — not that one of them
did it.

---

## FOUND, NOT FIXED

### 1. The eval harness cannot see the provisional lane. Severity: HIGH.

`eval/run_eval.py:580` — `for tier in TIER_ORDER`, and `PROVISIONAL_KEY` is not
in `TIER_ORDER`. Every provisional paper is missing from `per_tier` **and from
the `papers` total**, on every case, in every baseline this harness has ever
produced. The lane admitted papers on nine questions in these runs (up to
`147 of 400`).

This is the identical bug class the previous batch fixed at five sites in
`app.py` and `endo_ai.py`, and my own checklist test
(`TestEveryTierOrderLoopAccountsForTheProvisionalLane`) scans exactly those two
files. **The harness was never in scope and should have been.**

Not fixed here: changing the harness after the runs would void them. The fix is
one line plus extending the checklist test's `SOURCES` to `eval/`.

### 2. The guideline lane returns nothing on 86% of its queries. Severity: HIGH.

Measured across the three runs (2,172 esearch calls):

| lane | queries | empty | empty % |
|---|---|---|---|
| **guideline** | **482** | **415** | **86%** |
| cochrane | 67 | 50 | 75% |
| level3b | 208 | 123 | 59% |
| level1 | 439 | 219 | 50% |
| observational | 184 | 66 | **36%** |
| provisional | 35 | 7 | 20% |
| **TOTAL** | **2,172** | **1,192** | **55%** |

Pre-existing lanes: 47% empty. The two lanes added: 72%. **Excluding the
guideline lane alone brings the corpus back to 46%, under the 50% assertion
ceiling.**

This is the direct cause of the run's most common failure. 8–10 of 29 cases
fail on `max_empty_fraction` (>50% of queries returning nothing) or
`hits_per_query` (<5), almost all live-pinned — and those assertions were being
**skipped** before the contamination counter was corrected, so they are new
information, not a regression.

**Read alongside surprise 2 this is a cost/benefit finding, not just a noisy
lane.** The guideline lane issues 22% of all queries, 86% of them return
nothing, and the guidelines it does retrieve were cited **once across five live
Review questions.** The lane is doing a lot of work for very little.

Whether the fix is a narrower guideline query, or fetching guidelines from the
library instead of PubMed (60 verified records are already there), or accepting
the empty rate and re-calibrating an assertion written before three lanes
existed — that is a design question, and rule 6 forbids moving the threshold to
make the number go away.

### 3. `pregnancy` and `retreatment-vs-microsurgery` are the thinnest. Severity: medium.

`pregnancy` returns 3.5–4.2 hits/query with 78–81% empty;
`retreatment-vs-microsurgery` 1.5–1.7 hits/query with 81–83% empty. Both are
live-pinned and both fail consistently across all three runs, so this is
structural rather than variance.

### 4. Run-to-run variance is large on several library cases. Severity: medium.

`bisphosphonate-extraction-vs-rct-treatment` 40–119, `necrotic-virgin-tooth`
40–91, `diabetes-outcomes` 66–115. A 3× spread across three runs of the same
question on the same library means the candidate pool is order-sensitive.
Several land on exactly 40, which is `min_evidence_papers` flooring them — so
the low end is the guard, not the corpus.

---

## The baseline

`eval/baseline_v7.json`, 29 cases × 3 runs, labelled for
`retrieval-freeze-20260905b`. **Ranges, not means**, per the batch.

**Naming:** the batch calls this "the v6 baseline", but `baseline_v6.json`
already exists (2026-08-31) and is what this supersedes. Writing it as
`baseline_v7.json` keeps both and preserves the record (rule 24). `v5` and `v6`
are untouched.

**It is retrieval-only.** Citations and cost above come from two synthesis
subsets (5 live + 5 library/curriculum cases) and are NOT in the baseline file,
because the harness has no full-set synthesis mode. Any future comparison that
mixes the two will produce nonsense.
