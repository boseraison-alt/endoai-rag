# SESSION HANDOVER — 2026-09-05 (baseline batch) → next

Boot a new coding-agent chat with:

> Read `AGENT_QUEUE.md`, `SESSION_HANDOVER_2026-09-08.md` and
> `HANDOVER_GUIDELINES_2026-09-04.md`. Continue from the ORDER section below.

**Branch `fix/retrieval-blindspot`, tag `retrieval-freeze-20260905b`, pushed.**
Suite **2577 passed, 50 skipped, 1 xfailed, 0 failed.** Working tree clean.
**`eval/baseline_v7.json` is the current baseline.**

---

## 0. STATE BEFORE TOUCHING ANYTHING

- **Ports unchanged for six sessions.** 5000 is ours (pid 49800). **5003 is
  another session's (pid 27692) — never kill it, never use it.** Re-confirmed
  before each of the three baseline runs and at the end.
- **Run the suite BARE (`python -m pytest`).** `pytest.ini` sets
  `testpaths = tests presentations`; naming `tests/` silently drops 126 guards.
- **The library changed this batch.** Five citeable guideline rows now carry
  NULL score; `ESE-PS-VPT-2019` is quarantined `duplicate_of:30664240`.
  3,405 rows, 18 quarantined.
- **Backups, all verified:**
  - `endo-ai-rag-20260905-0940.bundle` (batch start)
  - `endo-ai-rag-20260905-baseline.bundle` (end, complete history)
  - `db-20260905-0940\` — 14 tables, **23,562 rows** (before item 1)
  - `db-20260905-post-baseline\` — 14 tables, **25,190 rows** (after)

---

## 1. THE ONE THING TO CARRY FORWARD

**A measurement instrument that counts a proxy will break silently when the
thing it proxies for changes.**

Baseline run 1 reported **7 contamination warnings** and was stopped, as the
batch required. It was not contamination. The `n_terms` counter counts *level1
audit records* and calls them *search terms*, on the premise that each term is
fetched once per tier. Two things that postdate it now write a level1 record
that is not a term: `[broadened]` re-queries, and the `early_stop` marker.
Measured on that run's own records — **131 level1 records = 77 terms + 48
broadened + 6 early_stop.** A 7-term case counted 14 and tripped a >10
threshold.

The real detector — the pid check, which *excludes* foreign rows rather than
inferring — reported **zero** foreign rows on all 29 cases, and the audit log
showed one writing process during the window. The warnings were also confined
to live-pinned cases; library cases issue no PubMed queries and never tripped
it. Genuine interleaving would not respect that boundary.

**And the false alarm was hiding real failures.** A "contaminated" case skips
every esearch-based assertion, so the first attempt's *27/29 passed* was partly
seven cases not being fully checked. Corrected: 19–21/29, with 8–10 cases
failing on empty-query rate — see §3.

That is the project's instrument-error count in double figures, and this one
had the specific shape of *a proxy whose denominator changed underneath it*.

---

## 2. WHAT LANDED

| item | outcome |
|---|---|
| **1** null the hand-set guideline scores | **DONE — five rows, not four** |
| **2** re-tag the freeze | **DONE — `retrieval-freeze-20260905b`** |
| **3** the baseline, 3 serial runs | **DONE — 0 contamination on all three** |
| **4** compare to the prediction | **DONE — 4 of 8 surprises fired** |

### Item 1 took five rows, not four

The batch named four hand-set scores. It also asked to test-pin *"no row at
`level_key='guideline'` carries a non-NULL score"*, and that pin is impossible
while `39578680` sits at the guideline tier with a computed 59.3. A49's
principle is about the **tier**, not the provenance of the number, so it was
included. My own earlier report had set it aside as "different: real accession,
computed score"; that distinction does not survive the invariant.

Quarantined rows were deliberately excluded — `--restore` promises to put the
twelve A2 rows back exactly as they were.

**The restore round trip was broken and the mutation check found it.**
Restoring to verify the invariant test fails (it did, 7 failures) and
re-applying raised `UniqueViolation` on the quarantine backup's primary key. A
backup path that only works once is not a backup path. Fixed with
`ON CONFLICT DO NOTHING`, round trip now proven twice.

### The baseline

`eval/baseline_v7.json`, 29 cases × 3 runs, ranges not means. **Named v7, not
v6** — `baseline_v6.json` already exists (2026-08-31) and is what this
supersedes; both survive (rule 24).

---

## 3. FOUND, NOT FIXED — with severities

- **The eval harness cannot see the provisional lane. Severity: HIGH.**
  `eval/run_eval.py:580` loops `TIER_ORDER`, and `PROVISIONAL_KEY` is not in it.
  Every provisional paper is missing from `per_tier` **and from the `papers`
  total**, in every baseline this harness has ever produced — while the lane
  admitted up to `147 of 400` papers in these runs. **This is the identical bug
  class the previous batch fixed at five sites**, and my own checklist test
  (`TestEveryTierOrderLoopAccountsForTheProvisionalLane`) scans only `app.py`
  and `endo_ai.py`. The harness was never in scope and should have been.
  **Fix: one line, plus extend that test's `SOURCES` to `eval/`.** Not done
  here because changing the harness would void the runs it had just produced.
- **The guideline lane returns nothing on 86% of its 482 queries. Severity:
  HIGH.** It issues 22% of all queries and produces 35% of all empties.
  Excluding it, the corpus empty rate falls 55% → 46%, under the assertion
  ceiling — so it is the direct cause of the run's most common failure. Read
  with the citation finding below, it is doing a great deal of work for very
  little. **Rule 6 forbids moving the threshold to make this go away.**
  Candidate fixes: a narrower guideline query; serving guidelines from the
  library (60 verified records are already there) instead of PubMed; or
  re-calibrating an assertion written before three lanes existed.
- **Guidelines are retrieved and almost never cited. Severity: HIGH.**
  One guideline citation across five live Review questions, against a predicted
  1–4 *per* question, while the lane populates the guideline tier on 21 of 29
  questions. Not a retrieval failure — the evidence reaches the prompt and the
  model does not use it. **This is a prompt-side problem and it redirects the
  next batch.**
- **Live-path citations are below the pre-fix range. Severity: medium-high.**
  Mean 13.2 distinct papers cited on the live route, against library Review
  18.0 and curriculum 37.5 (both in the predicted range). Citations track
  evidence-base size almost linearly. The 26%→100% visibility fix shipped
  **together with** the quota moving onto the deduped list, and the cap's
  reduction outweighed the visibility gain.
- **Review synthesis costs 3–6× the predicted range.** Live mean $0.72,
  library mean $1.20, against a predicted $0.10–0.22. The curriculum prediction
  was accurate ($1.19 vs $1.10–1.60), which is the control. Cost tracks
  evidence-base size; A45 retries are **not** the mechanism.
- **Run-to-run variance is large on several library cases.** 40–119, 40–91,
  66–115 across three runs of the same question on the same library. Several
  land on exactly 40, which is `min_evidence_papers` flooring them.
- Still open and untouched: the library floor (parked, needs the two-guard
  design), D1's recency exemption (harness built, ~3 h to run), the extractor's
  ~77% recall, the Komora xfail.

---

## 4. DECISIONS, WITH THE ALTERNATIVE REJECTED

| decision | alternative rejected |
|---|---|
| nulled **five** guideline scores, not four | leaving `39578680`, which makes the batch's own test-pin impossible to write |
| quarantined rows keep their scores | nulling them too, which breaks `--restore`'s contract |
| `ESE-PS-VPT-2019` quarantined `duplicate_of:` | an A2 failure mode, which would assert the document is unreal — it is real, and that is *why* the copy is redundant |
| fixed the contamination counter's **logic** | relaxing the >10 threshold (rule 6), and "stop and report" without diagnosing |
| baseline written as **v7** | overwriting `baseline_v6.json`, destroying the reference point |
| provisional blindness **reported, not fixed** | fixing it mid-batch, which would void the three runs |
| ran two synthesis subsets | reporting five of eight surprises as unmeasurable — the harness has no full-set synthesis mode |

---

## 5. ORDER FOR THE NEXT SESSION

1. **Fix the harness's provisional blindness** (§3, one line) and extend the
   checklist test to `eval/`. Then re-fold the baseline — the current `papers`
   totals understate every live and curriculum case.
2. **The guideline lane's 86% empty rate.** Measure whether the lane's query is
   too narrow or whether guidelines should be served from the library at all.
   This is the largest single source of wasted retrieval in the system.
3. **Why guidelines are not cited.** One citation in five questions with the
   evidence present in the prompt. Prompt-side; start by reading what the
   guideline block actually looks like in a rendered prompt.
4. The library floor still needs its two-guard design
   (`eval/reports/library_floor_29.md` §"Why the threshold is the right call").
5. D1's recency exemption — harness built, needs a ~3 h window.
6. Re-warm the demo cache. Nothing stored predates fewer than three retrieval
   changes.

---

## 6. REPLAY

```
python scripts/null_guideline_scores.py            # DRY RUN; --apply, --restore
python eval/run_eval.py                            # retrieval-only, 29 cases
python eval/run_eval.py --live-subset              # 5 live Review, synthesis
python eval/run_eval.py --synthesis-subset         # 5 library/curriculum
python eval/baseline_from_log.py --out eval/baseline_v7.json --label "..." eval/logs/v7freeze_run{1,2,3}.log
python scripts/dump_db.py <outdir>
```

Reports: `a46_prediction_v6_baseline.md` (the prediction, amended),
`a46b_baseline_v7_outcome.md` (the comparison), `library_floor_29.md`,
`prisma_nomination.md`, `path_divergences.md`, `early_stop_recency.md`,
`ese_ps_vpt_2019.md`.
