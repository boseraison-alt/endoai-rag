# Overnight Report 3 — `guardrails-v1`

Autonomous batch on `main`, 2026-09-01. Standing rules from `WORKLIST.md`
§0/§6 in full. Report in §8 format.

Two of the five items changed a measured behaviour and were run in separate,
non-overlapping measurements for that reason: Item 1 before Item 2, Item 3
after Item 1 and deliberately untouched by Item 2.

---

## 1. Per item

| Item | Status | Before → After | Test file | Commit |
|---|---|---|---|---|
| 0 · `/health` reports the running commit | DONE | field absent → frozen at import, verified `30c2bfd == HEAD` | `tests/test_health_revision.py` | `30c2bfd` |
| 1 · The claim unit | DONE | flag rate **9.7% → 4.9%**, McNemar p = 0.0118 | `tests/test_claim_unit_shapes.py` | `cdd4c11` |
| 2 · The retry tension | DONE | attempt-1 pass **30% → 100%** (p = 0.0031); cost per served answer **$0.9306 → $0.5596** | `tests/test_grounding_rule.py` (unchanged, still green) | `167b48a` |
| 3 · Curriculum grounding regression | DONE | DL flag rate **13.3% → 6.7%** (p = 0.0217); regression closed | `eval/logs/dl_flag_verdicts_guardrails.json` | `932827e` |
| 4 · `source` field + contamination guard | DONE | cost log unfilterable → `product` default; `pubmed_audit` had no guard → pid + redirect | `tests/test_shared_log_contamination.py` | `94fb3cf`, `3a94e19` |
| 5 · Close | DONE | suite **1377 → 1440 passing**, 39 skipped | — | this report |

---

## 2. Item 0 — the stale-process class, closed

PID 35820 was already gone when the batch started; the machine had been
restarted. The *defect* was not the process, it was that nothing about a
running server said which commit it had imported, and `endo-ai-noreload` does
not pick up code changes by design.

`/health` now returns `git_revision`, `git_dirty`, `imported_at` and `pid`,
with the revision resolved **once, at import, and frozen**. A request-time
shell-out would report the working tree — the state you already know, and
precisely not the state you are asking the server about. The test that
separates the two patches `subprocess.run` to return a different hash and
asserts `/health` does not follow it; mutation-checked by resolving per
request, which fails it while the other seven tests still pass. A checkout
with no `.git` answers `"unknown"` rather than dropping the field.

Verified end to end: server restarted, `/health` → `30c2bfd` = `HEAD`,
`git_dirty: false`; one cached demo question served in **430 ms at $0.0000**
over 36 papers.

**It earned its keep the same day.** During Item 3's live curriculum run the
harness printed *"1 citation-support check (13 pairs) in this window was
written by another process and is EXCLUDED"* — PID 25272, the app server
started earlier in this batch, running pre-Item-1 code, with `by_shape: null`
in its record where every other row had shapes. Item 0's field and Item 4's
guard identified it between them.

---

## 3. Item 1 — the claim unit

### What the splitter could not see

`_extract_claim_citation_pairs` handled prose and a bold pseudo-heading on its
own line. A curriculum writes **four** more structures the sentence splitter
cannot break, for the same two reasons every time — the line does not end in
`.!?`, and the next line starts with `*` or `|` rather than `[A-Z\d]`:

| shape | what it looked like | what it did |
|---|---|---|
| `decision_tree` | `**IF** … **THEN** … **BECAUSE** … [[PMID:N]]`, repeated | a seven-branch tree became ONE claim carrying seven papers' markers |
| `table_row` | `#### Clinical Protocol Summary` pipe table | the whole table was one claim, though each row cites its own paper |
| `bold_label` | `**KTP laser (532 nm):** Ayhan et al. …` | `_PSEUDO_HEADING_RE` needs the bold run to be the whole line, so three sub-points fused |
| `list_item` | `- **Irrigant extrusion risk**: … [[PMID:N]]` | four bullets, four papers, one 1,438-character claim |

The last two were **not in the brief** — they were found while measuring the
first two. `list_item` is the sharpest: the old code stripped the bullet
*marker* (`^\s*[-*•]\s+`) and then never split on it, so the marker's only
effect was to hide the boundary it marks.

### Structural before → after, on the two curricula behind the 13.3% figure

| | curriculum 1 | curriculum 2 |
|---|---|---|
| pairs, before → after | 114 → **114** | 124 → **124** |
| per-PMID multiset | **identical** | **identical** |
| mean claim length | 527 → **244** | 459 → **243** |
| longest claim | 2,403 → **469** | 1,820 → **745** |
| claims over 1,000 chars | 16 → **0** | 13 → **0** |

No citation lost, none gained. Only what each one is judged against changed.

### Measured by replay, not by regeneration

The change is in the **checker**, so both arms run over the SAME stored text —
the two curricula from the run that measured 32/240 — and differ in exactly
one place. Regenerating would have put an Opus sampling difference between the
arms, and the expected effect (13 flags in 37) is smaller than the run-to-run
spread already recorded for these two cases (11.7% and 15.0%, same question,
same run).

**Three judge runs per arm, because the judge is not deterministic.** Two runs
over the identical 238 pairs with the identical splitter returned 19 and 29
flags — 8.0% and 12.2%. One run per arm cannot attribute anything smaller than
that, which is the mistake `4.3% was a draw, not a level` already records.

| arm | run 1 | run 2 | run 3 | pooled |
|---|---|---|---|---|
| before | 8.8% | 9.7% | 10.5% | 69/714 = **9.7%** |
| after | 5.0% | 5.0% | 4.6% | 35/714 = **4.9%** |

The ranges do not overlap. The arms are **paired** — same pair count, same
PMID multiset, document order — so the test is McNemar, over each pair's
majority verdict across its three runs:

| | n |
|---|---|
| flagged in both arms | 7 |
| flagged BEFORE only (cleared) | **16** |
| flagged AFTER only (**new**) | **4** |
| flagged in neither | 211 |

**exact two-sided p = 0.0118.** Cleared pairs sat on `decision_tree` (8),
`list_item` (7) and `bold_label` (1).

### The 4 new flags matter more than the 16 cleared

Merged pairs were flagged **less** — 37.6% against 50.8%, p = 0.002 — because
a long blob gives the judge more surface on which to find something the
abstract does support. Un-merging therefore makes the checker **stricter**, and
a version of this change that only lowered the rate would have been the defect
rather than the fix. Four pairs the merge was hiding now flag.

Flag rate by shape, after arm, three runs pooled:

| shape | flagged / checked |
|---|---|
| `bold_label` | 0/261 = 0.0% |
| `decision_tree` | 1/63 = 1.6% |
| `prose` | 5/156 = 3.2% |
| `list_item` | 23/219 = 10.5% |
| `table_row` | **6/15 = 40.0%** |

`table_row` at 40% is the residual: a protocol-summary row is a terse
parameter (`Irrigant contact time — Per canal, per cycle — 60 seconds`) that is
barely a proposition. It is *visible* now instead of buried in a blob.

### Scoping, deliberate

`_detect_unattributed_claims` keeps the prose-only splitter. It feeds
`validate_evidence_mapping`, which **rejects** an answer and buys a full Opus
regeneration — and the retry rate is what Item 2 measures. Under the
shape-aware split, a materials-table row with a numeric parameter and no marker
becomes a new `UNATTRIBUTED_CLAIMS` finding. That may well be right; it is also
a second change to the number Item 2 was measuring, in the same batch.
`TestTheValidatorsUnitIsUnchanged` pins the scoping so widening it later is a
deliberate act with its own measurement.

### Also landed

`verify_citation_support` records each flag's **shape and its denominator** in
`evidence_mapping.jsonl`. Establishing "13 of 37 flags are a merged claim unit"
previously took a hand-judgement of every flag; it is now a query. Item 3 used
it the same day.

**Six mutants, six kills** (each of the four shape rules disabled, the table
flatten reverted to raw pipes, and the validator's splitter widened).

---

## 4. Item 2 — the retry tension

### The diagnosis is narrower than "6 of 8"

Correlating every attempt-1 failure in `evidence_mapping.jsonl` back to its
eval case: **all six `UNTRACEABLE_RECOMMENDATION` "no citation" failures came
from ONE question** — `cracked-tooth-prognosis`, a live-pinned case in a
literature the library does not cover — across four separate runs. The seventh
UNTRACEABLE is a different sub-reason (no tier named) from the demo re-warm.
Every `UNATTRIBUTED_CLAIMS` failure in the same window is a *curriculum* module,
not a Review answer.

It is a reproducer, not a diffuse property of the Review path. Attempt-1
failure rate for real Review runs, fixture rows excluded:

| window | attempt-1 | failed | UNTRACEABLE |
|---|---|---|---|
| pre-rule (31 Aug – 1 Sep 00:38) | 27 | 11 (40.7%) | **0** |
| post-rule | 31 | 9 (29.0%) | **7** |

### The 10-failure classification table

Ten attempt-1 syntheses of the reproducer, evidence base **pinned** so both
arms answer from the same papers, retry suppressed at the module's single
Claude seam so attempt 1 is measured rather than the cost of failing it.

| # | outcome | rule violated | did the two rules contradict? | what the model actually wrote |
|---|---|---|---|---|
| 1 | UNTRACEABLE | traceability | **yes** | states the gap, then gives crown-coverage guidance "from general principles", unmarked |
| 2 | pass | — | — | states the gap, then cites what the evidence base *does* establish |
| 3 | UNTRACEABLE | traceability | **yes** | gap + unmarked prognosis-by-extent guidance, labelled "expert-consensus / low-certainty" |
| 4 | UNTRACEABLE | traceability | **yes** | gap + "provisional and extrapolated from general principles", unmarked; `n_cited = 1` for the whole answer |
| 5 | pass | — | — | gap + cites the one tangentially relevant paper |
| 6 | GAP_SECTIONS | traceability (worse form) | **yes** | drops the disclaimer, gives 85–90% / ~50% survival figures, **`n_cited = 0` for the entire answer** |
| 7 | UNTRACEABLE | traceability | **yes** | management guidance first, gap disclaimer last, no marker anywhere in the section |
| 8 | pass | — | — | gap + cites two papers for the general principles they do state |
| 9 | GAP_SECTIONS | traceability (worse form) | **yes** | same as 6 — numbers, no citations, `n_cited = 0` |
| 10 | UNTRACEABLE | traceability | **yes** | gap + staged-treatment plan, unmarked, closes "a recommendation grounded in the supplied evidence cannot be made" |

**All ten reach the same correct conclusion** — this evidence base does not
address prognosis by crack extent. **Not one failure violates the grounding
rule; every one of them obeys it.** Two of them (6 and 9) obey it so hard they
cite nothing anywhere in the answer, which is the worse failure and was hiding
behind the more visible one. The three passes already contain the move the
prompt should have mandated.

### The fix, and what it is not

Option 3 of the grounding rule ("write it unmarked") is **withdrawn in the
CLINICAL RECOMMENDATION section only**, and the gap case is given an explicit
three-move shape: state the gap unmarked (it is a claim about the evidence
base, not about a paper), put the markers on what this evidence base *does*
establish, label outside-literature guidance as such with no marker.

`_GROUNDING_RULE` itself is **byte-identical**. It feeds the curriculum and case
prompts too, and changing it would have confounded Item 3, which ran in the
same batch. Neither gate was weakened; `validate_evidence_mapping` and
`_check_recommendation` are untouched.

### Result

| | before | after |
|---|---|---|
| attempt-1 pass, reproducer × 10 | 3/10 | **10/10** — Fisher p = **0.0031** |
| `UNTRACEABLE_RECOMMENDATION` | 5/10 | **0/10** — p = 0.0325 |
| mean cost per attempt-1 | $0.5474 | $0.5596 |
| **cost per SERVED answer** (attempt-1 + retry on failure) | **$0.9306** | **$0.5596** (−40%) |
| control: well-covered library question × 3 | — | 3/3 pass |

Target was "attempt-1 pass rate back above 75% with both gates intact". It is
100% with both gates untouched.

### The check that mattered more than the pass rate

The cheapest way to make this retry disappear is to attach a marker the paper
does not support: it clears the validator, fails the reader, and looks like
success on every number above. So the citations were judged.
`verify_citation_support` over the answers that **pass** validation:

| | flagged / checked | |
|---|---|---|
| before | 5/33 = 15.2% | 3 answers |
| after | 23/108 = 21.3% | 10 answers |

**Fisher p = 0.62 — no detectable difference.** The after arm cites three times
as much, which is where the denominator went. Watch the denominator: a rate
that falls because the answer stopped citing is not an improvement, and here
the rate held while the citing tripled.

### Residual, named rather than closed

Two of ten after-arm recommendations put a marker on a general principle
composed across two papers — *"outcome is governed by preoperative periapical
status, coronal seal and restoration timing"* cited to a retreatment review and
a single-visit review, neither of which states the composite. A clause
forbidding exactly that was added and did **not** remove it. The support-check
block renders the flag to the clinician, so it is surfaced rather than silent.

The open question: did the retry the old prompt paid for produce a *better*
shipped answer, or the same composite? The before arm's retries were never
generated, so nobody knows. That measurement is small and is queued.

### Method note — a contaminated measurement, kept

The first version of this fix quoted a worked example containing **two real
PMIDs, lifted from a passing answer to the same question being measured**. It
scored 10/10 — and the model reproduced those two PMIDs **27 times across 10
answers**. An example that names the evidence is an example the model can copy
instead of reason from, and on a single-question measurement that is
indistinguishable from success. The shipped prompt names no PMID and describes
the shape instead; the contaminated run is kept as
`eval/logs/item2_attempt1_after_repro_v1_contaminated.json` so the difference
stays visible.

---

## 5. Item 3 — the curriculum regression was the claim unit

Both laser eval cases re-run with Item 1's splitter in and nothing else changed
on that path. Cache bypassed, run separately so neither could contaminate the
other's window.

| | flagged / checked | |
|---|---|---|
| before the grounding rule | 20/235 = **8.5%** | |
| after the grounding rule | 32/240 = **13.3%** | the regression |
| **now** | 16/238 = **6.7%** | p = **0.0217** vs 13.3% |
| | | p = **0.49** vs 8.5% |

Live-pinned 9/120 = 7.5%, library-pinned 7/118 = 5.9%.

**The regression is gone, and the current rate is statistically
indistinguishable from the pre-rule baseline.** The brief's contingency —
adapt the grounding rule's wording for the module prompt if a real regression
remains — does not fire, so `_GROUNDING_RULE` was not touched.

### All 16 flags hand-judged

`eval/logs/dl_flag_verdicts_guardrails.json`, the way the 37 were.

| verdict | n | was, of 37 |
|---|---|---|
| `artifact_negative` — **new** | **7** | — |
| `unsupported` | 5 | 7 |
| `artifact_unit` | 2 | 13 |
| `artifact_meta` — **new** | 2 | — |
| `artifact_tail` | **0** | 17 |

**Genuinely-unsupported rate: 5/238 = 2.1%**, against 3.0% (7/234) before.
Artifact share 11/16 = 69%, against 81%.

`artifact_tail` no longer exists as a category — the judge sees the whole
abstract. `artifact_unit` has nearly gone, and both survivors are **one list
item carrying two assertions about two papers**, not a seven-branch tree
carrying seven. On one of them the half carrying the marker — *RR 1.55, 95% CI
1.14–2.09, moderate-certainty* — is verbatim in the cited Cochrane abstract.

### The new class is the finding, and it is Item 2's collision in a second place

Seven of sixteen flags are claims of the form *"Fahim et al. did not report a
specific final apical instrument size"* or *"no serious adverse events were
reported in the RCTs reviewed by Meire et al."* Every one is **true**, names the
**right paper**, and **cannot be verified from an abstract**, because an
abstract cannot state what it omits. (Checked: the words *adverse*, *harm* and
*safety* appear nowhere in Meire's 3,015-character abstract.)

`_GROUNDING_RULE` asks for exactly this move — *"take the number from the paper
that reports it, or state that the cited study did not report it"* — so the
rule and the checker disagree about whether a negative carries a marker. Same
shape as the collision Item 2 resolved for the recommendation, in a second
place. **Not fixed here**: it is a change to the shared constant, it needs its
own before/after, and this batch already carries two.

### The best catch in the set

Flag 16 is a decision-tree branch recommending laser-activated irrigation for a
**small** periapical lesion (PAI ≤ 2), justified by a trial that enrolled
**PAI ≥ 3** and is titled for **large** lesions — verified in the abstract. A
recommendation generalised past its paper's population is grounding-rule trap 4.
**Un-merging the tree is what made it visible**; under the old splitter it was
one seventh of a blob.

---

## 6. Item 4 — the shared logs

### `cost_log.jsonl` names its writer

Every row now carries `source` ∈ `product` / `test` / `script`, resolved from
what the process **is** rather than passed in by callers — and the callers who
would forget are the ones inside a test. `/admin/costs` shows `product` by
default, `?source=all` reproduces the old contaminated number, and `by_source`
always counts **every** row in the window so a filter can never read as an empty
log.

**The historical rows are not edited.** An append-only audit log is not
rewritten after the fact; a reader that can filter is the fix. The $5.70 of
stubbed TTS stays where it is, documented in `OVERNIGHT_REPORT_2.md` §7.

**A bug in this, found the same day.** The detector looked for `"/scripts/"` in
`argv[0]`, and `python scripts/x.py` gives `argv[0]` with no leading slash — so
every script invoked the ordinary way logged as `product`. Found by reading the
rows the first real script run wrote. The suite could not have caught it: under
pytest the detector returns `"test"` before it ever looks at `argv`, so that
branch had **no coverage at all**. Now parametrized over the four shapes that
occur, and mutation-checked against the substring version (two of seven cases
fail — exactly the two that happen in practice).

### `pubmed_audit.jsonl` gets the guard it never had

`run_eval._esearch_hits_since` reads a byte-offset window of it exactly the way
`_support_since` reads `evidence_mapping.jsonl` — where nine rows from a
concurrent pytest run once turned 16/119 into 16/146 — and it had **neither** a
writer pid **nor** a redirectable path, because the writer built its path
inline. Both now exist, and `tests/conftest.py` points it at tmp for the whole
session.

The regression test the original fix never got is here, and it is **two** tests
because the property has two halves that pull against each other:

- a foreign-pid row inside a case's window must be **excluded**;
- four curriculum modules landing in the same second must **not** be.

A timing heuristic passes the first and fails the second — the real
contaminating burst was 1.3 s apart, which is what a thread pool finishing four
modules looks like. Threads share a pid; separate processes do not.

Both guards fired for real during Item 3 (§2 above).

### `prior_pmids` — the item's premise was stale

`CURO_HANDOVER.md` records the seeding-after-the-gate ordering as *"correct
today, load-bearing, written down in one docstring and asserted nowhere"*. The
last clause is **wrong**. It is asserted, end to end and behaviourally, by
`tests/test_review_context.py::TestSeedsDoNotDecideTheRoute
::test_a_thin_library_still_goes_live_with_seeds_available`, which drives the
real builder with a 21-hit library whose 4 relevant rows plus 8 carried papers
reach exactly `RELEVANCE_GATE["min_relevant"]`.

**Mutation-verified**: moving the seeding block above the gate and recomputing
coverage after it makes that test fail, while the other four tests in its two
classes still pass. A second, weaker source-inspection test was written here
and **deleted** — two guards on one property is how the worse one ends up being
the one that gets maintained.

---

## 7. Item 5 — close

- **Full suite: 1440 passed, 39 skipped** (was 1377 passed / 39 skipped).
  63 new tests, every one mutation-checked.
- **Re-warm**, full (Review prompt changed in Item 2, curriculum output
  changed in Item 1, so both needed it):

  | | cold | cached |
  |---|---|---|
  | 5 Review answers | 55.8–69.4 s, $0.68–$0.95, **$4.23 total** | 0.5–1.0 s |
  | laser curriculum | 447.6 s (7.5 min), **$1.17**, 97 papers | 0.5 s |

  All six verified served-from-cache on the second pass. **Cost per cold
  Review answer is now ~$0.85, from ~$1.28** — Item 2 showing up where the
  demo will feel it. `DEMO_RUNBOOK.md` re-measured, including the four
  modules' citation-support lines (now 0 / 0 / 0 / 1 of 30 flagged, from 2–6).
- Bundle refreshed and verified after every commit; pushed to GitHub after
  every item.

### A trap found in the re-warm itself

`scripts/regenerate_demo_assets.py` did **not** evict before its cold pass. The
last time it ran, a rescore had just `DELETE`d `query_cache`, so its cold pass
really was cold. Run against a warm cache — the normal state — every "cold"
pass is served at $0 in half a second, it prints a full set of timings, and it
**re-warms nothing while looking exactly like a success**. That is invariant 12
pointed at the re-warm instead of at the eval. It now evicts each question's row
first, and a cold pass returning $0.0000 raises instead of printing.

---

## 8. Found, not fixed

| severity | finding |
|---|---|
| **HIGH** | **A true "the cited study did not report X" claim cannot pass the citation-support check.** 7 of the 16 remaining Deep Learning flags. `_GROUNDING_RULE` explicitly instructs the model to write these; the judge is asked "does this abstract support this claim?" and correctly says no, because an abstract cannot state its own omissions. Same shape as Item 2's collision, in the shared constant rather than the Review prompt. **Recommended fix**: teach the judge a fourth verdict (`negative_claim` — the claim asserts the paper does NOT report something; supported iff the abstract indeed does not), OR tell the prompt to write such statements unmarked. The first is better: it keeps the information and does not create a new unmarked-claim class. Needs its own before/after — do not fold it into another synthesis change. |
| **MEDIUM** | **A claim about the EVIDENCE BASE carrying a paper's marker.** 2 of 16 (`artifact_meta`): "the evidence base does not specify a minimum canal diameter" marked to one umbrella review. No single paper can support or refute it. Same family as the above. |
| **MEDIUM** | **The Item 2 residual**: 2 of 10 recommendations cite a general principle composed across two papers, which neither states alone. The clause forbidding it did not work. The unmeasured half is whether the old prompt's *retry* produced better text — a ~$3 experiment. |
| **MEDIUM** | **`_SUPPORT_MAX_PAIRS = 30` binds on every curriculum module, harder than before.** The four modules of the live run measured `total_pairs` 43 / 37 / 33 / 34 against `checked` 30 — **27 pairs of 147 (18%) never looked at**. The block names the remainder, so it is honest rather than silent, but nobody has measured what raising it would find. It costs Haiku calls and nothing else. |
| **MEDIUM** | **`table_row` claims flag at 40%** (6/15) — by far the highest of the five shapes. A protocol-summary row is a terse parameter, barely a proposition. Either the row needs its column header as context, or such rows should not carry markers at all. Newly visible, not newly caused. |
| **LOW** | **The eval floor "0 sections state numeric clinical parameters with no citation" fails intermittently on the live laser case.** It failed in this batch's run — and identically in the *pre-grounding-rule* baseline run of 2026-09-01 (`eval/logs/item1_before_synthesis.log`). Pre-existing and not caused by anything here, but it means that case has never reliably passed. |
| **LOW** | **`scripts/classify_dl_flags.py` had been broken since `grounding-v2`** — it read `endo_ai._SUPPORT_ABSTRACT_CHARS`, which that batch deleted, and raised `AttributeError` on line 163 while `CURO_HANDOVER.md` went on telling the next session to run it. Fixed here (`--excerpt-cap`, `--runs`, pid filtering, shape column). **The general lesson: a handover that names a command should have run it.** |
| **LOW** | Re-judging an OLD run with the NEW splitter matches fewer stored claims back to the answer (20 of 37 unmatched, against 8 before), because `evidence_mapping.jsonl` stores `claim[:160]` of the *merged* blob and the new units are shorter. Harmless — `dl_flag_verdicts.json` is the durable artefact — but the worksheet for runs A/B can no longer be regenerated identically. |

---

## 9. Baseline changes

| baseline | from | to | cause |
|---|---|---|---|
| Deep Learning citation-support flag rate | 32/240 = 13.3% | **16/238 = 6.7%** | Item 1, the claim unit. Confirmed by hand-judging all 16. |
| DL genuinely-unsupported rate | 7/234 = 3.0% | **5/238 = 2.1%** | same |
| Review attempt-1 pass, `cracked-tooth-prognosis` | 3/10 | **10/10** | Item 2, the prompt reconciliation |
| Cost per served Review answer, that case | $0.9306 | **$0.5596** | same |
| Test count | 1377 | **1440** | 63 new tests |

Not moved, and deliberately: `eval/baseline_v6.json`. Item 1 changes the
citation-support *metric*, not retrieval, and Items 2–4 change neither. The
retrieval baseline is still the reference.

---

## 10. Decisions taken, with the alternative rejected

1. **The recommendation must always be traceable — and the retry was not the
   price of saying so.** The trade the `grounding-v2` report offered was false:
   the retry was buying the same answer twice, because attempt 1 already
   contained a traceable formulation in 3 of 10 cases and the prompt never said
   which move to take. *Rejected*: accepting the retry as "the system working"
   and writing the cost into the handover. That was the brief's own first
   branch, and the measurement says it was avoidable.

2. **The reconciliation lives in the Review prompt, not in `_GROUNDING_RULE`.**
   *Rejected*: amending the shared constant, which is the more obviously
   "correct" place. It feeds the curriculum and case prompts too, and Item 3 —
   a curriculum measurement — ran in the same batch. One measurable change per
   measured surface.

3. **The shape-aware splitter is scoped to the checker, not the validator.**
   *Rejected*: giving `_detect_unattributed_claims` the same units. It would
   newly reject uncited numeric table rows — plausibly correct, per invariant 6
   — but it changes the retry rate, which is the number Item 2 measures.

4. **Measured by replay, on fixed text, three runs per arm.** *Rejected*:
   regenerating curricula for the before/after. Two identical runs over the same
   238 pairs returned 8.0% and 12.2%; adding Opus sampling on top of that spread
   would have produced a number that could not be attributed.

5. **The `$5.70` of stubbed spend stays in `cost_log.jsonl`.** *Rejected*:
   deleting the rows. An append-only audit log is not rewritten after the fact —
   a reader that can filter is the fix, and `by_source` reports what the filter
   dropped.

---

## 11. Cost

Reported beside what it bought, per WORKLIST §0.7.

| what | cost | what it bought |
|---|---|---|
| Item 1 replay, 6 judge runs over 238 pairs | $1.00 | the 9.7% → 4.9% measurement with its spread |
| Item 2 capture, 33 attempt-1 syntheses + 3 controls + 1 smoke | $19.9 | the 10-failure classification table and the 3/10 → 10/10 result |
| Item 2 support checks | $0.23 | the "did it buy the pass rate with worse citations" answer |
| Item 3, two curricula | $2.64 | 13.3% → 6.7% with all 16 flags judged |
| pinned evidence, 4 questions | ~$0.30 | both arms answering from the same papers |
| Item 5 re-warm | $5.39 | the demo's warm cache, and the ~$1.28 → ~$0.85 number |
| **batch total** | **$36.37** | 286 logged calls |

Split by the field Item 4 added, which is the first thing it was useful for:

| `source` | | |
|---|---|---|
| `script` | $22.51 | measurement runs, correctly labelled |
| unset | $8.10 | written before the field existed (Item 1 replay, Item 2 before-arm, the pins) |
| `product` | $5.76 | **mislabelled** — the contaminated after-arm, written by a script before the `argv[0]` bug was fixed |

**Real product spend this batch: $0.** Nothing here was a user request.

One line is larger than it should have been: **$5.66 of the Item 2 total was
the contaminated worked-example run**, which is not the reported number. It
bought the method note in §4, which is worth having, but it was avoidable by
not putting real PMIDs in a prompt example. It is also, by coincidence, the
$5.76 sitting in the `product` bucket above — the same run, mislabelled by the
same afternoon's other bug.

---

## 12. Tag

`guardrails-v1`. Rollback point: `grounding-v2`.
