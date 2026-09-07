# OVERNIGHT REPORT 10 — batch 2026-09-08

Every item ran. Two shipped nothing on purpose, and both refusals are the
finding. Suite green at **2842 passed, 52 skipped, 1 xfailed**.

The night's single largest result is that **retrieval is reproducible for the
first time** — and the second largest is that this changed less than anyone
expected, because the instability was never mostly ours.

---

## The headline numbers

| | before | after |
|---|---|---|
| identical query string, 5 runs × 10 questions | **0/10** | **10/10** |
| mean pairwise AND-group Jaccard | 0.135 | 1.000 |
| guideline pointer rows (no stored text) | 45 | **15** |
| `unconfirmed_pmid` manifest records | 11 | **5** |
| citeable rows carrying a model-written summary | 2 | **0** |
| animal-subject rows labelled | 0 | **86** |
| stored claims citing an animal study without saying so | 48 | *measured, not yet fixed* |

---

## Item A — a PMID-keyed row's own text is its PubMed abstract

Full detail in [`eval/reports/night10_item_a.md`](eval/reports/night10_item_a.md).

The 2026-09-07 fetch went to the **publisher** for all 72 pointer rows and
collected 29 HTTP 403s. 23 of those rows carry a numeric PMID, and their text
was already on PubMed — through the same efetch client that read 200 rows that
night without a single failure. Pointers **45 → 15**. That is rule 40.

- **Change 1**: 39 candidates, 32 abstracts stored, 7 genuinely blank on
  PubMed. Of the batch's 23: **16 with, 7 without** — the batch predicted 16–19,
  correct at the bottom of the range. My own prediction that the blanks would
  not be only the five AAOM statements held.
- **Change 2**: 9 DOI lookups, 7 title matches, **6 written**.
  `unconfirmed_pmid` **11 → 5**.
- **Re-key**: 6 retires / 6 inserts, dry run == apply, census delta 0, redirect
  chains 0.

### One held back, for RB

The batch pre-declared `ACP-PARAMETERS-OF-CARE-2020` a no-match — *"the only
PubMed hit is an editorial"*. Its DOI resolves to **32681591**, which is
*J Prosthodont* 2020;29(S1):**3-147**, no authors, no abstract. A 145-page
supplement is the Parameters of Care itself, not an editorial about it.

I did not take it. The asymmetry decides it: declining leaves the status quo,
while taking it wrongly writes a false accession into the manifest **and then**
retires the slug row with a redirect to it. One line to reverse if RB agrees.

### The defect the re-key caused, and nothing failed

Citations follow `redirect_to`. Text did not. Retiring `AAE-VPT-2021` left the
AAE's vital-pulp-therapy text — browser-fetched precisely because aae.org 403s
everything else — on the quarantined row, while `34352305`, which had just
inherited every citation, had no abstract at all.

The library had quietly stopped being able to quote the AAE, and the re-key had
undone item B's whole point for that document. No test failed. No count moved.

Repaired with a carry-over pass that runs over **every** redirect rather than
only fresh ones, into empty targets only, with provenance travelling alongside.
Stranded documents after: **0**. `test_no_text_is_stranded_on_a_retired_row` is
now the alarm, and it re-creates the defect in a transaction to prove it fires.

### A second silent breakage: CRLF

All 13 browser-fetched files failed their sidecar hash on a clean `git status`
with nothing edited. Git stores them LF and had checked them out **CRLF**. Item
B would have refused the entire corpus. Fixed at the storage layer
(`.gitattributes … -text`) rather than by normalising before hashing, which
would have weakened the one check that makes the provenance chain worth having.

---

## Item C — retrieval becomes reproducible

Full detail in [`eval/reports/night10_item_c.md`](eval/reports/night10_item_c.md).

**Prediction 4 was right and far too generous.** I said "below 40% identical".
It was **zero**: 9 of 10 questions produced 5 different queries in 5 runs. Two
runs of the same build were searching PubMed for different things. One omission
caused it — no `temperature` passed to the one call every retrieval depends on.
**Prediction 5 confirmed.** The after-run prediction (60–90%) was committed
before it ran; it reached **100%**, and I said I would say so.

Shipped alongside: a term cache keyed on `sha256(mode, prompt-version,
normalised question)` — the prompt hash covers the *rendered* prompt with the
question elided, so template, lexicon block and conversation context all
invalidate it — and `query_cache.retrieval_provenance`, thread-local at the
source so one question's query cannot be recorded as another's.

The degraded fallback is **never cached**: storing it would freeze a known-bad
retrieval *and hide it*, because the next run would hit the cache silently.

### Admission rules (a)/(b)/(c) — nothing shipped

| rule | median | max | non-current admitted | probes |
|---|---|---|---|---|
| (a) similarity above floor | 1.0 | 7 | none | **0/3** |
| (b) scope, ≥2 shared terms | 0.0 | 3 | none | **0/3** |
| (c) union | 1.0 | 7 | none | **0/3** |

All three pass the size bar; all three fail the probes. Per the batch —
*"if none does, ship nothing and report the table"* — nothing shipped.

**Why (a) cannot pass:** the documents never arrive. Probe 2's
`IADT-FRACTURES-LUXATIONS-2020` sits at **0.526** against a 0.55 floor; the
other five watched documents are not in the top 100 at all.

**Why (b) cannot pass:** in *each* probe, one watched document shares **no**
domain noun with its question.

Two of these deserve RB's attention:

- **`AAE-TRAUMA-2026` may not belong on probe 2's watch list.** Its manifest
  scope is `[dental trauma, avulsion, luxation, root fracture]`; probe 2 asks
  about a **crown** fracture. The document's own declaration says it is not
  about this question. The done-when is unreachable while it is watched for.
- **`ACP-ASYMPTOMATIC-EXTRACTION-2016` is a pure vocabulary gap** — its scope
  says `failing endodontic treatment`, probe 3 says `failed root canal
  retreatment`. Fixable in the manifest, not in code.

### Rule 38 extension — prediction 8 was wrong

Same query string sent to PubMed twice; term noise zero by construction.

**8/31 pools (26%) differ in membership** — against 24% measured on 2026-09-06
when term noise was still present. I predicted 10–20%.

**PubMed's own ranking accounts for essentially all pool instability, and
freezing the terms does not reduce it.** The same-build noise floor for a pool
A/B is ~26% and is not removable by anything we control. Any A/B reporting a
pool-membership effect below that is measuring PubMed. Query-construction
changes must keep comparing query *strings*, where the floor is now zero.

---

## Item D — 30 disagreements adjudicated by hand. No DB write.

Full detail in [`eval/reports/d_reband_adjudication.md`](eval/reports/d_reband_adjudication.md).

| writer | wrong | rate |
|---|---|---|
| **pubtype** | 19/30 | **63%** |
| abstract extraction | 9/30 | 30% |
| definitional | 2/30 | 7% |

**Prediction 9 was wrong in both halves.** Pubtype is wrong twice as often, and
"definitional" is the smallest bucket.

The two writers fail differently, and both failures are one sentence long:

- **pubtype** — NLM's `Comparative Study` is a **modifier, not a design**. It
  sits on bench work, animal work and prospective clinical studies alike. That
  one mapping is **116 of the 180 disagreements**. Worse, `28068207` and
  `36862198` are tagged **Randomized Controlled Trial with no human subjects**
  — specimens were randomised — so two lab studies sit at the top of the human
  evidence ladder today.
- **abstract extraction** — matches design words in sentences about something
  else: a PROSPERO registration, an ethics-approval protocol, a reference to a
  previous *in vitro* study, a recommendation for future RCTs, a physical
  "cross-section". Five of its nine errors.

**"Off-ladder 185" explained**, and prediction 10 confirmed: these are moves off
the human ladder entirely — 116 `level3a→invitro` and 14 `level3a→animal`.

**Recommendation: no automated reband from either writer.** Three separate,
measurable changes proposed instead; none made. Manifest text proposed for
`39743567` (expert consensus on apical microsurgery, currently at `level5`) and
`39487671` (IADT avulsion terminology consensus, currently at `level2` — a
clinical-trial rung for a terminology consensus).

**A count I could not reproduce:** the batch says 208 disagreements; I get
**180** against the same artefact, comparing the abstract writer's tier *key*
rather than its prose label. Comparing prose to keys inflates it to 272, which
is the likely origin. I am not presenting a number I cannot derive.

---

## Item E — whose teeth were these

**86 rows** labelled with a species, **9 of them on the human clinical ladder**
(rat and rabbit pulp-capping at `level2`, a dog pulpotomy comparison at
`level2`). The context line now opens `ANIMAL STUDY (<species>)`, before the
score it qualifies; `ANIMAL_PROMPT_BLOCK` tells the model to name the species
**in the citing sentence**; `rag._animal_label` classifies on the write-back so
new rows arrive labelled.

**Measured harm in the archive: 209 documents, 60 citations of an
animal-subject row, 53 prose claims, and 48 of those never say the subjects were
animals.** Prediction 13 said 5–20. Wrong, by more than double the top of the
range.

**Prediction 11 was also wrong** — I said "exactly 81, matching 2026-09-07". It
is 86, and the arithmetic is worth keeping: that run vetoed protected tiers
(`classic`, `cochrane`, `level1`) and only read rows with a usable abstract. The
veto is for a *migration that moves tiers*; labelling moves nothing, and a
`level1` systematic review of rodent models is exactly the row a clinician needs
the label on.

**Two false positives found by hand and fixed at the classifier**, both
labelling a HUMAN paper from a cue in a sentence about something else — the same
failure item D measured in the abstract extractor. A sentence-scope veto now
covers previous work, future work and recommendations.

### The species guard now applies to every lane

Pre-declared stop: *zero human rows lost, or revert*.

| | |
|---|---|
| absent from the guarded top-60 | 230 |
| **genuinely excluded by the guard** | **87** |
| merely re-ranked out of the window | 143 — not a loss |
| **excluded AND indexed `humans[mh]`** | **0** |

**My first A/B instrument was wrong and said REVERT.** It counted every PMID
absent from the guarded top-60 as a removal and found 147 "lost human rows" —
which `NOT (animals[mh] NOT humans[mh])` cannot produce, since it excludes only
records indexed animal AND NOT human. That contradiction is what gave it away.
Adding a NOT clause changes the query; PubMed's ranking is a function of the
query. The corrected instrument asks, per PMID, whether it survives the guard.
**A bad instrument nearly reverted a correct change.** That is rule 41.

---

## Items F2, B, G

- **F2** — the two legacy paraphrases are replaced by pointer text,
  `abstract_source = 'pointer'`. 2 rows, 0 changes to `quarantine_reason` or
  `redirect_to`. Retirement *hid* the paraphrase; this deletes it. Rows carrying
  a model-written summary: **0**.
- **B** — 13 files, 13 rows, 0 skipped, 0 mismatches, exactly as predicted. Two
  fixes were needed first: the CRLF repair above, and the row lookup, which was
  by manifest id and would have written the AAE's words back onto the *retired*
  row. It now follows `redirect_to`.
- **G** — rules 40 and 41 added; log A56 records three overturned premises and
  four instrument errors.

---

## What I got wrong, collected

Five predictions failed, and every one failed in the direction of me being
optimistic about my own instruments.

| # | predicted | actual |
|---|---|---|
| 4 | <40% identical terms | **0%** — right, far too generous |
| 8 | residual 10–20%, below 24% | **26%** — freezing terms changed nothing |
| 9 | abstract wronger; definitional largest | pubtype wronger 2:1; definitional **smallest** |
| 11 | exactly 81 animal rows | **86** |
| 13 | 5–20 harmed citations | **48** |

And three overturned premises, **all three mine** — including the 2026-09-07
conclusion that non-determinism was why the admission probes could not pass.

**Four instrument errors**, one of which was reproducing instrument error #4
from `AGENT_QUEUE.md` *verbatim*, with the identical symptom, one day after it
was written down. Reading the instrument-error log is not the same as checking
the instrument.

A shell heredoc silently ate backslashes **four times**, once leaving literal
backspace bytes inside a regex that `grep` could not see and
`inspect.getsource` rendered as innocuous — the function returned the same
wrong answer for every input while looking correct in every view of it. The
standing instruction to use the file tools for multi-line content exists for
exactly this, and each recurrence cost more than following it would have.

---

## Open for RB

1. **`ACP-PARAMETERS-OF-CARE-2020` → 32681591** — the batch's premise looks
   wrong; evidence above, one line to apply.
2. **`AAE-TRAUMA-2026` on probe 2's watch list** — its own scope says it is not
   about crown fractures. The done-when cannot be met while it is watched for.
3. **`ACP-ASYMPTOMATIC-EXTRACTION-2016`'s scope vocabulary** — "failing
   endodontic treatment" vs "failed root canal retreatment".
4. **Two lab studies at `level1`** (`28068207`, `36862198`), tagged RCT because
   specimens were randomised.
5. **48 stored claims** cite an animal study without saying so. The forward fix
   is shipped; the archive is not rewritten.
6. **The ~26% pool-noise floor** bounds what any retrieval A/B can ever show.

---

# Addendum — 2026-09-07

**Two of the six "Open for RB" items above are closed**, both by commit
`3224b76` (RB, advisory session), and both went the way the evidence pointed.

**Open item 2 — `AAE-TRAUMA-2026` on probe 2's watch list — closed.** The
report argued the crown-fracture done-when was unreachable because the
document's own manifest scope (`dental trauma, avulsion, luxation, root
fracture`) did not name crown fractures, so no scope rule could admit it. RB
confirmed the diagnosis and fixed it at the source: `AAE-TRAUMA-2026` and
`ESE-TRAUMA-2021` now carry the full injury spectrum — crown fracture,
crown-root fracture, intrusion, extrusion, replantation and the endodontic
sequelae. **The manifest was wrong, not the matcher.**

That means item C change 4's verdict — *"no admission rule met the bar, ship
nothing"* — was scored against a manifest that has since been corrected, and
rule (b) deserves re-scoring rather than standing as written. It is re-run as
**item E of the 2026-09-09 batch**; see `OVERNIGHT_REPORT_11.md` for whether
`AAE-TRAUMA-2026` and `IADT-FRACTURES-LUXATIONS-2020` are now admitted by scope
on 3 of 3 runs.

**Open item 1 — `ACP-PARAMETERS-OF-CARE-2020` → 32681591 — closed.** The batch
had pre-declared that a DOI search would find only an editorial, so the write
was held back and the evidence reported. RB accepted it: the record is now
keyed by **32681591**, the 145-page supplement (*J Prosthodont* 2020;29(S1):3-147,
no authors), and the editorial `32633458` is kept in the manifest note as the
citation trap it is. `unconfirmed_pmid` drops from 5 to 4.

The remaining four items — the ~26% pool-noise floor, the 48 unlabelled animal
citations, and the two lab studies at `level1` (`28068207`, `36862198`) — are
addressed by items C and B of the 2026-09-09 batch. The architecture question
raised in `eval/reports/a55_report.md` is answered by that batch's item A:
**routing goes live by default.**
