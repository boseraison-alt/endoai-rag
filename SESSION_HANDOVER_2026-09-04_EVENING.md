# Curo — Advisory Session Handover
**Written:** 2026-09-04, updated 23:55 after the 6-hour batch
**Repo:** branch `fix/retrieval-blindspot`, HEAD `ed417c3`, pushed. Suite 2408 passed / 50 skipped / 2 xfailed / 0 failed.
**Supersedes:** `HANDOVER_GUIDELINES_2026-09-04.md` — §0 of that file contained an error, corrected here in §3.

Paste this whole file into a new advisory chat. It is self-contained. Read §1 and §2
before anything else.

---

## 0. How to use this file, and how RB works

**The working pattern.** RB runs a local coding agent that does all implementation.
This advisory chat does not write production code. It reads the agent's reports,
diagnoses by failure class, and writes paste-ready instruction batches. When tempted to
write Python for `endo_ai.py` or `app.py`, don't — you cannot see the real function
signatures, and wrong code costs more than no code.

**RB is an endodontist, not a software engineer**, and is very good at spotting a
hedged or padded answer. He types fast and terse; short messages are not impatience. He
responds well to being told plainly when something he proposed is wrong, and he has
corrected this chat's direction several times and been right each time.

**The single most important habit: measure before concluding.** The stated premise has
been overturned by measurement thirteen times (§9). Several were this chat's. When you
feel confident about a cause, write the prediction down and have the agent measure it.

**Numbering.** The agent owns the A-number sequence in `AGENT_QUEUE.md`. This chat once
drafted an "A48" that collided with an existing entry. Check the file first. A47 is
unused.

---

## 1. THE CENTRAL FINDING — the retrieval blind spot

Everything else is downstream of this. Diagnostic commit `4a4ae1d`, report at
`eval/reports/a49_missed_papers_diagnostic.md`.

**The live retrieval path cannot see the newest literature at all.**

A newly indexed paper carries `Journal Article` as its only publication type, because
MEDLINE has not yet assigned a study-design type. Every generated query ANDs a tier
filter, and **none of the eight tier filters admits a bare `Journal Article`**. So
there is a rolling window — the length of MEDLINE's indexing lag — in which no new
paper on any topic can enter the pool, however good the term generator becomes.

Worked case: **Sulaiman et al., PMID 42388091**, *"Effect of Pulpal Haemostasis Time on
Partial Pulpotomy Outcome in Cariously Exposed Mature Permanent Teeth With Symptomatic
Irreversible Pulpitis"*, Int Endod J, 2026-07-02. Its title carries five of the topic's
own terms and the generator produced queries matching it in two groups. Still
unreachable.

**Why it matters beyond one paper.** Papers that overturn a settled position are
disproportionately new. New paper → no pubtype → no tier → unreachable. The system is
structurally biased toward the settled view, and "not last year's evidence" — the
product's positioning line — is false in a precise structural way during exactly the
window it claims to own.

**Two further mechanisms, different from the above and from each other:**

**Komora, PMID 39117767** (network meta-analysis, 21 RCTs, bioactive materials) is
*already in the library* at `level1`, score 74.8. Cosine similarity to "vital pulp
therapy in adult teeth" was **0.5807 against `evidence_floor` 0.60 — cut by 0.0193**,
rank 325 of 3,162, far below `min_evidence_papers` 40 so the rescue branch cannot reach
it either. A42 measured that floor as "free — 18% of pool, 1.1% of citations"; that was
measured on citation counts, not on whether a specific on-point paper was lost.
Different questions. **The floor has not been changed and must not be on the basis of
one paper.** Komora's fixture deliberately still fails.

**EFCD-ESE-ORCA S3, PMID 42018467** — `practice guideline[pt]` and `guideline[pt]`
appeared in no tier filter. **Fixed by batch item 5; its fixture now passes.**

**And the chain closes:** `ingest_aae_guidelines.py` exists *because* the live path
could not reach guidelines. That workaround introduced sixteen hand-scored records,
twelve of which describe documents that do not exist or are misdated. The fabrication
was compensation for a structural gap, not carelessness.

**Hoang et al. 2026 — DO NOT USE.** This chat relayed it from OpenEvidence's reference
list without verifying it. Not findable on PubMed by author, topic or pubtype. Excluded
from the fixtures and **test-pinned**: `test_hoang_is_not_a_fixture` fails if anyone
adds a fourth fixture. Not a conclusion that it doesn't exist — a refusal to build on
an unverified record, which is the same error the A2 audit found six times over,
mirrored.

---

## 2. The 6-hour batch — what landed, 2026-09-04 18:45–23:50

Six commits, `9936409..ed417c3`, pushed. Suite went 2329/50/0 → 2408/50/2.

### 2a. The headline: 4a killed 4b, correctly

**Median 426 untyped-recent papers per query, against a threshold of ~40 declared
before the run.** All 29 of 29 questions above 100.

```
min 243 | p25 377 | MEDIAN 426 | p75 471 | max 621 | total distinct 12,299
```

And it is a **floor, not an estimate**: each topic group was fetched at `retmax=200`,
fourteen questions sit pinned at that ceiling, and `generate_search_terms` capped eight
questions to three AND-groups. Both biases push the count down.

**4b was not built, and that was the right call.** Shipping the lane with an arbitrary
cap would have flipped Sulaiman's xfail and looked like progress while hiding the real
question. Sulaiman's fixture stays failing and stays accurate.

### 2b. The unblock path — gate on design, not relevance

The agent named the open question precisely: *what relevance signal is legitimate for a
paper with no design information?* The answer proposed in this chat, not yet measured:

**Don't gate on relevance. Gate on design, extracted from the abstract.** Similarity is
already disqualified — `evidence_floor` 0.60 loses Komora, a level-1 paper on the exact
topic, at 0.5807; a floor that lossy on tiered papers has no business gating untyped
ones. But those 426 papers are not untyped because they have no design. They are
untyped because MEDLINE hasn't got to them. The design is stated in the abstract in the
authors' own words. Extract it, and the untyped population becomes a tiered one, and
the existing tier machinery handles the rest. The lane stops being a new lane and
becomes **provisional tier assignment**.

**The measurement that decides it:** of the median 426 untyped-recent papers, how many
carry an explicit design statement in the abstract that would place them at level2 or
above? Expect a small fraction — most will be narrative reviews, in-vitro work, case
reports and editorials, which the ladder already ranks low. **Run it on three questions
first**; 4a's PMID lists are on disk, and fetching 12,299 abstracts is not the way to
find out.

Note the boundary: extracting a design the authors stated is **fact extraction**, not
scoring. It must not become scoring — no quality judgement, no number, no rank. Render
the tier as provisional and say why.

### 2c. Item 3 — an honest null result

The impact-factor leak at `endo_ai.py:4743` is removed. The measurement, with retrieval
run once and the identical evidence object passed to both arms:

| | with IF | without IF |
|---|---|---|
| citation markers | 18 | 14 |
| distinct papers cited | 10 | 11 |
| cost USD | 0.7669 | 0.7865 |
| input tokens | 35,373 | 35,338 |

Cited only without the signal: 1 paper. Cited only with it: 0.

**On this question the signal was not visibly steering which papers got cited.** n=1 per
arm against a stochastic generator; reported as noise-level rather than dressed up as a
win. **The removal stands regardless** — it was an invariant-22 violation and that
argument does not depend on measured effect. Do not let a null result argue it back in,
and do not spend a 29-question A/B establishing an effect size that would change
nothing.

### 2d. The rest

| # | status | result |
|---|---|---|
| 1 | done | 3 fixtures, strict-xfail, 4 mutations killed incl. 2 negative controls |
| 2 | done | guideline tier 21 → 9 citeable; 52 → 0 quarantined markers on served text; reversible |
| 3 | done | see above |
| 4a | done, measure only | median 426 vs threshold 40 |
| 4b | **not built** — 4a's own stop condition | — |
| 5 | done | EFCD fixture **flipped to passing**; guideline lane live |
| 6 | measured, not built | **25 of 36 stored curricula (69%) carry a same-quantity conflict** |
| 7 | not started | out of time |

**Item 6 is the cheapest high-value job in the backlog.** `detect_parameter_conflicts`
already finds those 25. It is called by `regenerate_curriculum.py` as a metric and by
**no answer path as a gate**. The detector isn't missing — the wiring is. Wire the
existing concentration detector as a gate first; treat time quantities as a separate,
harder job (see §6 caveats).

**Item 5 changes `ingest_aae_guidelines.py`'s status.** The live path can now reach
PubMed-indexed guidelines, so that file should be **narrowed** to documents PubMed does
not index — NICE, SDCEP, CGDent, AAE PDFs — not deleted. Its fetch machinery is worth
keeping.

### 2e. Backups and undo

- **Git bundle:** `C:\Users\boser\endo-ai-backups\endo-ai-rag-20260904-1845.bundle`,
  4.44 MB, verified "complete history", HEAD `9936409`
- **DB dump:** `C:\Users\boser\endo-ai-backups\db-20260904-1845\`, 13 tables,
  **21,360 rows**, every table verified `expected == written == reread`
- **Quarantine undo:** `python scripts/quarantine_unverified_guidelines.py --restore`
  (before-state in `endo_papers_rag_quarantine_backup`; the round trip is exercised as
  a mutation test, not merely claimed)

---

## 3. The A49 phase-0 audit — findings in full

Commit `19e9c08`, report `eval/reports/a49_guideline_path_audit.md`, script
`scripts/audit_guideline_path.py`. Measure-only.

**A4 — impact factor.** Scoring does **not** read it: `USE_IMPACT_FACTOR` off,
test-asserted off, no `ORDER BY`, no sort key, no cap. **Synthesis did** —
`endo_ai.py:4743` appended `IF={value}` to the Top-paper-per-tier block on all four
answer paths (`ask_clinical_question` 7595, `ask_learn_question` 7826,
`write_curriculum_module` 8430, `ask_case_question` 10071), firing on 1,572 of 3,208
rows. Removed by batch item 3. `format_paper_context_line` was already clean
(invariant 11). A console diagnostic at `endo_ai.py:4755` was deliberately kept — it
goes nowhere near the model context.

**A3 — severity.** A guideline row at 90.0 outranks **100% of the 3,192 evidence
rows**. No real paper scores above 85.9. Thirteen of sixteen sit at exactly 90.0,
against Coll 2025 at 80.0 and the Schwendicke Cochrane at 79.4.

**A2 — record verification**, matched by organisation + subject + year, never by slug:

| result | count |
|---|---|
| verified match to a real document | 4 of 16 |
| wrong year, no such edition | 6 |
| no such document on that subject | 6 |
| stored answers citing an unverifiable record | 103 |

`ESE-QG-2023` names a document that does not exist — the 2023 ESE document is the
differently-named S3 guideline, PMID 37772327. `AAE-PS-cbct` is dated 2021; real
editions are 2015 and 2025.

**A1 — withdrawn Cochrane reviews.** None of CD007997, CD005408, CD004623 is in the
library or cited anywhere. G1 is prospective protection, not cleanup.

**A5 — leaking slots.** 26,172 scanned across 207 stored answers; 471 hold a non-PMID
identifier, of which **432 resolve to a real library row** across all sixteen slugs.
39 were ordinary hyphenated parentheticals swept up by the regex. **That 430-of-432
distinction is why item 2 was scoped to twelve slugs and enforced on resolution rather
than shape** — a session reading only the audit commit would have sized it at 432 and
deleted 430 correct citations.

**Correction.** The previous handover said guidelines were forced onto the ladder at
`level1`, inferred from the module docstring. **Wrong.** `level_key='guideline'` is a
separate rung and the taxonomy is clean; the contamination is entirely in the **score**
field. That was this chat's error.

---

## 4. Competitive position

**OpenEvidence shipped EvidenceGrade 10 July 2026** — grades and visualises evidence
quality in real time, builds on GRADE, A/B/C/D plus U, per claim/answer. Alongside a
Cochrane partnership (March 2026) and deployments at NewYork-Presbyterian, Columbia and
Weill Cornell.

**Unconfirmed:** whether the UI shows a badge per citation or one grade per answer.
Their user-guide page blocks fetching; one trade outlet describes it per-paper. **Do
not assert "theirs is answer-level" publicly.**

**Adopting GRADE is not the fix and would make things worse.** GRADE rates certainty in
the evidence you *have*, and inconsistency is a downgrade domain — retrieve one side of
a contested question and it sees perfect consistency and rates it *up*. Applied to
Curo's VPT retrieval it would have stamped high certainty on a contested threshold.

**The defensible position:** nobody grades evidence in dentistry; Curo tags study
design, which is checkable from the abstract, and never lets the model score a paper;
and Curo issues CE credit. The competitive-table slide was cut from the deck.

---

## 5. The two head-to-head comparisons

**Case — Curo won decisively.** 20-year-old Asian male, necrotic #20, no caries,
restoration or crack, periapical radiolucency. OpenEvidence answered *what is this
radiolucency* — correct, well-sourced, and identical for a 65-year-old with a heavily
restored tooth. Curo led with **dens evaginatus**, the demographic, the site prevalence,
the silent tubercle-fracture mechanism, and the bilateral point (examine #29). Where
OpenEvidence was better: the cannot-miss safety net — spreading odontogenic infection,
mandibular osteomyelitis, red flags. Take that on the chin. Partially closed in the
2026-09-04 curriculum, which now flags systemic comorbidity in "When NOT to Apply".

**Curriculum — OpenEvidence won on currency.** The 6-minute haemostasis threshold was
stated as settled in nine places; OpenEvidence reported it contested. That triggered
the whole retrieval investigation. Where Curo was better: the conflict-of-interest
handling (flagging Septodont's declared interest, docking that paper 15%, corroborating
from a conflict-free meta-analysis) and the cross-module tension flag. No competitor
does either.

**The 18:13 re-run.** Better: the threshold is no longer stated as settled — the Final
Verdict now says it *"is not derived from a prospective study that enrolled consecutive
cases and measured haemostasis time as a prespecified primary predictor"*, reached by
reasoning rather than retrieval. The NaOCl concentration passage is the best writing in
the document. Module 3 flags improved 6/75 → 1/99. Not better: Sulaiman still absent;
unsourced claims 12 → 18; **three** haemostasis numbers now where there were two; five
*Pediatric Dentistry* papers in the top tier framing a curriculum titled *Adult Teeth*.

---

## 6. Open queue, with blocking

**Blocked:**
- **A51 contrarian pass is BLOCKED on 4b.** A contradiction query hits the same
  tier-filter wall, finds nothing, and looks like a settled literature — rule 32's
  failure mode engineered in.
- **v6 three-run baseline (~3.5h) blocked on code freeze.** Items 3 and 5 changed
  synthesis and retrieval.

**Order I would take:**
1. **The design-extraction measurement** (§2b) — three questions, from 4a's stored PMID
   lists. Unblocks 4b, which unblocks A51.
2. **Build 4b** on whatever that measurement supports.
3. **Wire `detect_parameter_conflicts` as a gate** — 69% hit rate, detector already
   exists. Caveats that killed shipping it in the batch: the haemostasis probe finds
   two of three values, misses "up to 10 minutes", cannot represent "no threshold
   established" at all, and `query_cache:4471` contradicts itself *inside a single
   module* (4 and 6 minutes, both Module 3), which kills any module-pair rule before
   it's written. Ship the concentration gate; treat time as a separate job.
4. **Narrow `ingest_aae_guidelines.py`** to documents PubMed does not index.
5. A51, once 4b lands. Measurement already specified: load-bearing claims per answer
   across the 29 (median 40+ = too loose; 3–8 = tractable), contradiction hit rate on a
   sample of ten. **Do not tier-gate contradictions against the supporting evidence** —
   a 2025 SR outranks a 2026 RCT and the stale rule survives. Surface anything above
   the floor and show both tiers and both dates.
6. A50 scoping questions, with a **mandatory free-text field** — RB's requirement,
   non-negotiable: *there must always be a place to type a separate answer different
   from the options given*. Measure the breadth detector first: the A37 gate did not
   fire on "vital pulp therapy in permanent teeth", which is maximally broad, so the
   breadth detector is the suspect, not the question count.
7. A22e, A44b–d remaining, A44n.
8. Curriculum generator: missing Module 2 heading on some topics; 4a/4b/4c repeated in
   all four modules.
9. v6 baseline on frozen code, A46 prediction committed first.
10. A44c colour remap — **attended sessions only**.
11. A47 (unused) — evidence-watch feature, blocked on the multi-user build.
12. Decision-table renderer for the IF/THEN/BECAUSE branches — spike only, 45 min,
    render as a **decision table not a flowchart** (the branches are parallel
    independent rules, not a traversal path), traceability built into the spike.

---

## 7. Standing decisions — do not re-litigate

- **No journal weighting.** JOE gets no preference. Closed twice.
- **Tier ladder is by study design, never by score.** Impact factor is forbidden
  (invariant 22).
- **Constants, shipped, do not change:** `similarity_floor` 0.55, `evidence_floor` 0.60,
  `min_evidence_papers` 40.
- **Two-regime broadening:** above zero hits a declared qualifier beats position; at
  zero hits fewest-alternatives goes first.
- **Modes:** Literature never interviews. Curriculum may ask only to narrow a broad
  topic. Case asks only when relevance requires it.
- **Never weaken a checker, gate or threshold to move a number.** If a number will not
  move without it, that is a finding, not a fix.
- **Port 5003 belongs to another session.** Re-confirm before any eval run — A38d's
  first eval carried 22 contamination warnings from exactly this cause.
- **Product name undecided. Rename nothing.** Best candidate **Rung**; 51 names
  screened, only Rung and Yardstick clear. Pending a trademark clearance search in
  **UK/EU classes 9 and 44**. Pitch line: *"like a rung on a ladder — every answer tells
  you which rung it came from."*
- **Deck deletions:** the competitive-landscape table (cut), "state-hour compliance
  tracking — Yes", "then CE issued", the named CE platforms unless contacted, "no
  independent education company exists… Yet", "AAE co-branded course", "Advisory board
  forming".

---

## 8. Architecture and files

Semantic cache (MiniLM 384-dim, cosine ≥0.92 plus a Haiku same-question gate,
`context_hash` partition) → library coverage gate → union-KNN with per-query max
similarity → live PubMed 7-tier retrieval → write-back with provenance. **Opus** for
synthesis, case reasoning, differentials, curriculum; **Haiku** for search terms, cache
gate, citation-support checker, routing; **MiniLM** local for embeddings; **OpenAI
tts-1-hd** for narration only.

**Tier ladder:** `cochrane → level1 → level2 → level3a → level3b → level4 → invitro →
level5 → observational`, `retracted` terminal, `guideline` a separate rung.

**Guardrails:** fabricated-PMID validator, `verify_citation_support`, `_GROUNDING_RULE`,
chart gates, the no-raw-`[[PMID:N]]` invariant (3), the quarantine block.

**Files:** `AGENT_QUEUE.md` (34 standing rules) · `data/guidelines_seed.json` (60
verified guidelines, 22 orgs; **10 carry `confidence: "unconfirmed_pmid"` and must
never be emitted as `[PMID:N]`**) · `scripts/audit_guideline_path.py` ·
`scripts/quarantine_unverified_guidelines.py` · `eval/reports/a49_*.md`,
`eval/reports/a51a_numeric_conflicts.md` · `ingest_aae_guidelines.py` (**do not
delete** — narrow it) · `eval/run_eval.py` (29 questions) · `tests/test_g1_withdrawn.py`,
`test_g2_citation_resolution.py`, `test_missed_paper_fixtures.py`,
`test_guideline_quarantine.py`, `test_no_journal_identity_in_context.py`,
`test_guideline_lane.py`.

---

## 9. Overturned premises — the project's most valuable log

Thirteen times the stated premise was wrong and measurement corrected it. Several were
this chat's.

| # | premise | what was true |
|---|---|---|
| 1 | three papers missing from the library | two were already in it; the cap was cutting them |
| 2 | modules share one query set | they retrieved separately; the cause was the tier taxonomy |
| 3 | narrow the authority guarantee | it could never fire at all; deleted |
| 4 | the query lost the scenario | **over**-specified; three AND-groups collapsed the pool 131→26 |
| 5 | level1 precision defect | denominator artifact; level1 supplies 59% of citations |
| 6 | the quota is too small | measurement showed neither |
| 7 | the answer is in A38d's ten runs | those were the deep-pool questions |
| 8 | the `**` leak is renderer-side | text-layer, in stored text |
| 9 | 0 split list items | the detector looked for bare `N.`; the corpus writes `**N.**` |
| 10 | the detector audit found 15 unjustified zeros | **its own harness had the bug it audited for** — 12 of 13 line-anchored without `re.M` |
| 11 | guidelines forced onto the ladder at level1 | `level_key='guideline'` is a separate rung — **this chat's error** |
| 12 | Hoang 2026 exists | not findable on PubMed; relayed unverified — **this chat's error** |
| 13 | score penalises new papers at retrieval | ranking doesn't read IF; the tier filter excludes untyped papers entirely |

**Seven instrument errors**, three caught mid-run in the A2 matcher, and the seventh
found by a new detection mode: the with-IF measurement arm showed 102,242 input tokens
against 27,514 and $1.77 against $1.06, because `context_block` **appends** rather than
replaces and that arm received the evidence twice. **Cost implausibility as an
instrument check** is worth adding alongside rule 32.

Also caught before it shipped: a naive offline pubtype matcher would have reported "no
tier admits EFCD", when in fact `review[pt]` explodes down the publication-type tree
and admits `Practice Guideline` — which is why the diagnostic found it at rank 521 and
not absent. The fixtures now record a **measured** admission map rather than a
restatement of the filters.

**The pattern is consistent enough to be a rule: when a number looks wrong, suspect the
instrument before the thing measured.**

---

## 10. RB-only — nothing else can do these

- **Rotate three keys** — Anthropic, OpenAI, Neon `DATABASE_URL` — and re-zip the
  OneDrive backup **without `.env`**. Oldest open item; live keys still in that zip.
- **Trademark clearance search** for *Rung*, alternate *Yardstick*, UK and EU classes 9
  and 44. Further screening in chat has hit diminishing returns at 51 names.
- **Supply the correct title for `ESE-PS-VPT-2019`.** It resolves to a real document
  (ESE-DEEPCARIES-2019) but is stored under *"Outcome of Primary Root Canal
  Treatment"*, which is neither. The agent refused to retitle it, correctly — choosing
  a replacement title is inventing bibliographic data, the same error being cleaned up.
  This is a five-minute human lookup and it is the worst remaining record, because it
  looks right.
- **Decide the quarantine block colour** — A22d's pale spec (recommended) versus deck
  parity. Not blocking.
- **Do not circulate the VPT curriculum to endodontists** until the haemostasis
  sections are corrected.
- Verify or discard **Hoang 2026**.

---

## 11. Instructions for the next session

**Start with the design-extraction measurement (§2b).** It is the single item that
unblocks the most: 4b, then A51, then the whole "predictably catch what we miss"
programme. Three questions, from 4a's stored PMID lists, not 12,299 abstracts.

**Then wire the conflict gate (§6 item 3).** 69% hit rate on a detector that already
exists is the cheapest real improvement available.

**How this chat has failed before — do not repeat:**
- Writing production code blind.
- Assigning A-numbers without checking `AGENT_QUEUE.md`.
- Relaying a citation without verifying it exists (premise 12).
- Being confident about a cause before the agent measured it (premises 11, 13).
- Proposing a fix correct in principle and wrong in ordering — the tier-gating mistake
  in the first draft of A51 is the clearest example.

**What this chat is useful for:** diagnosing by failure class rather than symptom;
noticing when two findings are the same finding; catching sequencing errors (A48 before
the lane, the invariant deferred to a later phase of the flowchart spike); and research
the agent cannot do — competitor verification, the guideline corpus, trademark
screening.

**A note on how to read the agent's reports.** It reports null results honestly (§2c),
declines to ship when its own pre-declared threshold says stop (§2a), and catches its
own instrument errors. Take its numbers at face value and spend your attention on
ordering and on what it could not see from inside the repo.
