# Handover — Guidelines, Scoping, Contrarian Pass
**Date:** 2026-09-04 · **Repo HEAD at writing:** `7d3b834` · **Supplements:** `CHAT_HANDOVER.md`

Paste this whole file into a new advisory chat. It is self-contained: a fresh session
with no prior context can act on it.

---

## 0. Read this first — the urgent finding

**`ingest_aae_guidelines.py` (602 lines, repo root) is already ingesting guidelines, and
it violates three of Curo's own standing rules.** Its module docstring states the design
outright:

```
• level_key = "level1"  (guidelines are treated as top-tier evidence)
• score     = 88–95     (manually set — authoritative clinical consensus)
• impact_factor = 8.0   (guideline-tier authority weighting)
```

Confirmed at lines 397–402, 450–455, 540–545. Sixteen hardcoded records:

```
AAE-PS-antibiotics    AAE-PS-cbct           AAE-PS-cracked-tooth  AAE-PS-diagnosis
AAE-PS-implant-v-endo AAE-PS-isolation      AAE-PS-microscope     AAE-PS-obturation
AAE-PS-regenerative   AAE-PS-retreatment    AAE-PS-safety         AAE-PS-trauma
AAE-PS-vital-pulp     ESE-PS-VPT-2019       ESE-QG-2006           ESE-QG-2023
```

### What is wrong, in order of severity

**1. Fabricated source records.** `ESE-QG-2023` and `ESE-QG-2006` both exist as separate
records. There is no ESE Quality Guideline 2023 — the ESE's 2006 Quality Guidelines were
superseded by the **2023 S3-level clinical practice guideline** (PMID 37772327), a
differently-named document. `ESE-QG-2023` is a plausible-sounding identifier for a
document that does not exist. `AAE-PS-cbct` is dated 2021; the real AAE/AAOMR CBCT
statements are 2015 (superseded) and 2025 (current) — there is no 2021 version. **Verify
every one of the sixteen against the seed manifest before anything else.**

**2. Model-written summaries stored as source text.** The file's own comment: *"Summaries
are condensed from the official documents."* They are paraphrases, not abstracts.
`verify_citation_support` is therefore checking claims against a paraphrase rather than a
source — a hole directly under the grounding guarantee.

**3. Guidelines forced onto the tier ladder at `level1`.** This is the
score-as-membership category error fixed in A5b, recurring in a different file. A
guideline is not "level 1 evidence"; it is a specialty's stated position, a different
axis entirely.

**4. Hand-set scores of 85–90 that outrank real evidence.** In the VPT curriculum the
Schwendicke Cochrane review scored 81.5 and Coll 2025 scored 80.0. Hand-scored guideline
records at 85–90 therefore **outrank every genuine systematic review in the library**.

**5. `impact_factor` 4.5–8.0 as an authority weight.** Impact factor is a forbidden
signal. The landing-page copy was rewritten precisely because "ranked by citations &
impact factor" described something the engine is not allowed to use. It is hardcoded
here.

### The immediate consequence

This explains the `(ESE-QG-2023)` and `[PMID AAE-PS-diagnosis]` bare keys leaking into
citation slots. They are not rendering bugs. The system is citing records that exist in
the library but have no PMID, because the `id_slug` is being emitted into a PMID field.

**Do not delete this file.** It has real fetch machinery (eUtils, PMC OA, web scrape)
worth keeping. A49 rewrites how records are *classified and scored*, not how they are
*fetched*.

---

## 1. Where things stand

The demo is done. The overnight batch of 2026-09-04 closed the Case zero-height defect
(0px → 337px), completed A16d re-verification across all three modes, ran a detector
audit that recovered 13 false zeros across 82 detectors, repaired 30 orphaned list
numbers and 24 cut bold runs, and lifted uncited-mark contrast from 1.02:1 to 13.34:1.
The v6 re-baseline was correctly skipped — the code was not frozen and credit ran out.

Working tree is dirty (many modified files uncommitted). Last commits: `7d3b834`,
`09bbc10`, `6d41e1f`.

**Still open from before:** the v6 three-run baseline, A22e, A44c (the ~85-colour remap —
attended sessions only), the A37 gate distribution, and the curriculum module-heading
defect (Module 2's heading missing on some topics; subsections numbered 4a/4b/4c in all
four modules).

---

## 2. The competitive picture — what changed

**OpenEvidence shipped EvidenceGrade on 10 July 2026.** Confirmed via PR Newswire and
Fierce Healthcare. It grades and visualises evidence quality in real time, builds on
GRADE, and ships alongside a Cochrane partnership (March 2026) and deployments at
NewYork-Presbyterian, Columbia and Weill Cornell. The scale is A/B/C/D plus U
(ungradeable), applied per claim/answer. **Unconfirmed:** whether the UI shows a badge
per citation or one grade per answer — their user-guide page blocks fetching, and one
trade outlet describes it per-paper. Do not assert "theirs is answer-level" publicly.

**Consequence:** the competitive table's "Evidence graded by tier — Curo Yes /
OpenEvidence No" row is now false and falsifiable in thirty seconds. That slide was cut.

**Adopting GRADE is not the fix, and would make things worse.** GRADE rates certainty in
the evidence you *have*; inconsistency is a downgrade domain. Retrieve only one side of a
contested question and GRADE sees perfect consistency and rates it *up*. Run GRADE over
the VPT retrieval and it would have stamped high certainty on a contested threshold.

**The defensible position, which survives whatever they ship next:** nobody grades
evidence in dentistry; Curo tags study design, which is checkable from the abstract,
and never lets the model score a paper; and Curo issues CE credit.

---

## 3. What the two head-to-head comparisons revealed

### Case — Curo won decisively

Stem: 20-year-old Asian male, necrotic #20, no caries, restoration or crack, periapical
radiolucency.

OpenEvidence answered *what is this radiolucency* — granuloma 60%, radicular cyst 37–39%,
non-endodontic mimics, malignancy tail. Correct, well-sourced, and identical for a
65-year-old with a heavily restored tooth. It never engaged the actual puzzle.

Curo led with **dens evaginatus** — East Asian male, mandibular second premolar as the
most common site, silent tubercle-fracture mechanism — plus the bilateral point (examine
#29, >50% contralateral occurrence). OpenEvidence has no DE entry at all. Curo also gave
an explicit "argues against" per candidate and ranked discriminators by yield per unit
chair time.

**Where OpenEvidence was better:** the cannot-miss safety net — spreading odontogenic
infection, mandibular osteomyelitis, red flags (trismus, dysphagia, paresthesia, fever).
Curo said nothing about any of it. Take that on the chin; do not argue scope.

### Curriculum — OpenEvidence won, on currency

Curo's VPT curriculum builds the **6-minute haemostasis threshold** into nine places:
three decision branches, a key takeaway, an abort-treatment instruction. OpenEvidence
reported that it is contested — a 2026 IEJ trial (Sulaiman et al., *Effect of Pulpal
Haemostasis Time on Partial Pulpotomy Outcome*) found no association up to 15 minutes,
and the Hoang 2026 meta-analysis of 23 RCTs found bleeding time not clearly predictive.
Neither paper is among Curo's 37 references.

Curo's own document shows the strain: Modules 1 and 3 say six minutes, Module 4 says
four, and the Final Verdict invents a reconciliation that comes from no paper.

Also missed: Komora's network meta-analysis (21 RCTs, capping materials) and the
**EFCD-ESE-ORCA S3 Deep Caries Management guideline (PMID 42018467)** — the current
European guideline on the exact question Module 1 addresses.

**Where Curo was better, and it is not small:** the conflict-of-interest handling
(flagging Septodont's declared interest, docking that paper 15%, corroborating from a
conflict-free meta-analysis) is something no competitor does and no reviewer does by
hand. And Module 4's cross-module tension flag notices that Modules 1 and 4 disagree,
explains why both can be right, and specifies the trial that would settle it.

**Net: better teaching machine, weaker retrieval.** Better problem to have than the
reverse.

---

## 4. Root cause and the three proposed items

**Retrieval is seeded once, from the question.** `generate_search_terms` runs at the
front on the user's question; everything downstream is bounded by that one term set.
Nothing ever re-queries based on what the answer turned out to say. The claims needing
challenge do not exist until after synthesis, so no retrieval-time fix can reach them.

Ship order **A49 → A50 → A51**. A51 depends on A49. Nothing starts before the browser
block and the v6 baseline close.

### A49 — Guidelines as first-class objects (rewritten in light of §0)

Not "build guideline support." **Repair a guideline path that already exists and is
wrong.**

**Phase 1 — audit before touching anything.** Verify all sixteen hardcoded records
against `guidelines_seed.json`. Report: which correspond to real documents, which are
misdated, which do not exist. Count how many stored answers cite each. `ESE-QG-2023` and
`AAE-PS-cbct` (2021) are the two known suspects.

**Phase 2 — separate the channel.** A `guidelines` table with its own identifier scheme
(`ORG-TOPIC-YEAR`), independent of PMID. Fields per the seed manifest: `id`, `org`,
`title`, `year`, `status`, `supersedes[]`, `superseded_by`, `url`, `pmid` (nullable),
`doi`, `jurisdiction`, `scope[]`, `question`, `confidence`.

**The rule that matters most: a guideline is not on the tier ladder.** Remove
`level_key`, the hand-set `score`, and `impact_factor` from the guideline path entirely.
Guidelines rank by authority and jurisdiction, never by study design or score. Print the
delta split by tier when the rows move.

**Phase 3 — real text, not paraphrase.** Where a guideline is PubMed-indexed, use the
real abstract. Where it is not (NICE, SDCEP, CGDent, AAE PDFs), store no summary at all
rather than a model-written one, and render the record as a pointer: organisation,
title, year, status, URL. A pointer a clinician can follow is worth more than a
paraphrase Curo cannot verify.

**Hard gates, each pinned by a test:**
- A `withdrawn` guideline is never cited. **Three Cochrane endodontic reviews are
  withdrawn — CD007997, CD005408, CD004623 — and Cochrane sits at the top of the tier
  ladder.** Sweep for these three first; it is the highest-severity item in this document.
- A `superseded` guideline is never cited without a supersession notice naming its
  replacement. `AAE-AAOMR-CBCT-2015` is the live hazard: heavily cited, still reachable,
  replaced in 2025.
- A `draft` guideline is never presented as current (`AAE-ESE-DIAGNOSIS-2025`).
- `confidence: "unconfirmed_pmid"` is never emitted as `[PMID:N]` — 10 records. DOI and
  journal verified; accession number not.
- Jurisdiction is surfaced, never silently mixed. NICE CG64 and AHA-IE-2021 disagree on
  whether to give endocarditis prophylaxis at all. Both are current. Show both, labelled.

**Ingest:** dedupe against the paper table by PMID and **reclassify** rather than insert.
Expect PMID 41121563 and 40533920 to move — they are the AAPD permanent-teeth VPT
guideline and its supporting review, currently in the corpus as papers. That is how a
paediatric dentistry guideline became the top-scored anchor (80.0) of a
mature-permanent-teeth curriculum.

**Rendering — its own section, working title "Where the specialty stands."** Guidelines
lag the literature by years by construction, so **guideline-versus-evidence divergence
should be a first-class render state, not an edge case.** A section saying *the AAE
position (2021) says X; the 2026 trial evidence says Y* is something neither OpenEvidence
nor UpToDate produces.

### A50 — Scoping questions with a mandatory free-text field

**RB's requirement, non-negotiable: there must always be a place to type a separate
answer different from the options given.** Forced choice in clinical software produces
wrong answers, because the real case never fits the menu.

- At most two questions, only when the topic is genuinely broad.
- **Every question carries a free-text field. Always** — not conditional, not behind a
  disclosure, not an "Other" radio button. Alongside the options.
- Free-text feeds `generate_search_terms` directly. It is input, not decoration.
- Free-text is logged and reviewable: what people type is the list of options the system
  is missing.

Mode rules unchanged — Literature never interviews; Curriculum may ask only to narrow a
broad topic; Case asks only when relevance requires it.

**Measure first.** The A37 gate fired 0, 1, 0, 2, 3 across five runs — variable, not
broken. But it did **not** fire on "vital pulp therapy in permanent teeth," which is
maximally broad. **The bug is the breadth detector, not the question count.** Report how
often it fires on broad versus narrow topics before changing anything.

### A51 — Contrarian pass

Runs after synthesis, before finalisation. Four jobs:

**(a) Internal contradiction** — same quantity, two values, one document. Six minutes vs
four. Needs no retrieval; **cheapest check here, build it first.** Extend the existing
chart-gate logic, which already polices same quantity/unit and ranges-as-scalars.

**(b) Unsupported claims** — partly covered by the quarantine path. Report alongside.

**(c) External contradiction** — for each load-bearing claim, call
`generate_search_terms` **with the claim as input instead of the question**, run it down
the existing live path, union what returns. Almost no new machinery.

> **Do not tier-gate the contradiction against the supporting evidence.** An earlier
> draft said "surface at tier ≥ supporting evidence." Applied here that fails: Coll 2025
> is a systematic review, Sulaiman 2026 is a single RCT, the review outranks the trial,
> the contradiction is suppressed, the stale rule survives. **The tier ladder has no
> recency dimension.** Surface anything above the evidence floor and show both tiers and
> both dates.

**(d) Guideline-versus-evidence divergence** — requires A49.

**Load-bearing** = actionable (instructs the clinician to do or not do something) AND
appearing in 2+ of {decision-tree branch, protocol step, key takeaway, protocol summary
row}. Note this bar mostly only exists in Curriculum; decide explicitly whether
Literature gets a lower bar or no pass.

**Reuse, do not rebuild.** The divided-literature renderer already works — the
caries-removal and biomaterial passages are the two best-written sections of the VPT
curriculum. The gap was never presentation.

**Measure first.** Load-bearing claims per answer across the 29 eval questions (median
40+ = too loose to afford; 3–8 = tractable). Contradiction hit rate on a sample of 10.
Added latency and cost reported separately per mode — eight extra queries is nothing on a
37-minute curriculum and material on a 2-minute answer. **Rule 32: report how often the
pass finds nothing.**

---

## 5. The guideline manifest — what it is and how to use it

**File:** `data/guidelines_seed.json` — 60 documents, 22 organisations, every record
checked against a primary source.

**It is data, not an instruction.** It does not go into an agent's chat window. It goes
into the repo, and A49's ingest reads it from disk. Pasting 60 records into a prompt
wastes context and invites transcription errors.

**Statuses:** 49 current, 4 withdrawn, 3 superseded, 1 superseded_in_content, 1 draft,
1 under_review, 1 current_but_stale. 27 carry a confirmed PMID; **10 are
`unconfirmed_pmid` and must never be emitted as `[PMID:N]`.**

**Jurisdictions:** 23 US, 13 EU, 13 UK, 9 international, 2 US/EU. This matters — RB works
to ESE guidelines and uses Commonwealth spelling. A UK clinician shown only AAE/ADA
guidance has been given the wrong answer.

**The richest field is `superseded_by`.** A superseded guideline cited as current is a
clinical hazard, not a formatting defect.

**It is a seed, not a complete corpus.** Endodontics is covered thoroughly; the
cross-specialty entries are the ones touching endodontic practice (antibiotics, CBCT,
MRONJ, anticoagulants, acute pain, caries). Deliberately omitted as low yield: the ~50
FDI policy statements, the AAOMS white-paper series, AGD policies (AGD publishes no
clinical guidelines at all).

---

## 6. Do today, before any of the above

**Regression fixtures.** Four PMIDs OpenEvidence surfaced and Curo missed on the same
question. One test asserting a VPT curriculum surfaces them or records why not:

- **Sulaiman et al. 2026**, *Effect of Pulpal Haemostasis Time on Partial Pulpotomy
  Outcome*, Int Endod J — contests the haemostasis threshold
- **Hoang et al. 2026**, SR/MA of 23 RCTs, mature posterior irreversible pulpitis
- **Komora et al. 2024**, network meta-analysis, 21 RCTs, bioactive materials
- **EFCD-ESE-ORCA S3 Deep Caries Management, PMID 42018467**

**Make it a standing practice.** Every competitor comparison that surfaces a paper Curo
missed contributes its PMID as a fixture. Over a year that accumulates a test suite built
from real misses rather than invented ones. It is the only mechanism here that gets
stronger each time it catches you out.

**And the withdrawn-Cochrane sweep.** CD007997, CD005408, CD004623. Ten minutes, and you
need the number.

---

## 7. Standing decisions — do not re-litigate

- No journal weighting. JOE gets no preference. Asked and closed twice.
- Tier ladder is by study design, never by score. **Impact factor is a forbidden signal.**
- `similarity_floor` 0.55, `evidence_floor` 0.60, `min_evidence_papers` 40 — shipped.
- Two-regime broadening: above zero hits a declared qualifier beats position; at zero
  hits fewest-alternatives is dropped first.
- Literature never interviews. Curriculum may narrow a broad topic. Case asks only on
  relevance.
- Never weaken a checker, gate or threshold to improve a number. If a number will not
  move without weakening a gate, that is a finding, not a fix.
- Product name undecided. **Rename nothing.** Best current candidate is *Rung* (51 names
  screened; only Rung and Yardstick came back clear) — pending a trademark attorney's
  clearance search in UK/EU classes 9 and 44.
- Port 5003 belongs to another session. Never kill it, never use it.

### Corrections made this session — premises overturned by measurement

The measurement has overturned the stated premise nine times in this project. Two from
today:

1. "The `**` leak and A22a are renderer-side" — **wrong**, they reproduce in stored text.
2. "The `**N.**` detector found 0 split list items" — **wrong**, the detector looked for a
   bare `N.` while the corpus writes `**N.**`. The audit harness built to find that class
   of bug then contained the same bug (12 of 13 zero patterns line-anchored without
   `re.M`). Five instruments have now been wrong rather than the thing measured.

---

## 8. RB-only — nothing else can do these

- **Rotate the three keys** (Anthropic, OpenAI, Neon `DATABASE_URL`) and re-zip the
  OneDrive backup without `.env`. Oldest open item on the list.
- Trademark clearance search for *Rung* and *Yardstick*, UK/EU classes 9 and 44.
- Decide the quarantine block colour: A22d's pale spec (recommended — the app palette is
  light throughout) versus deck parity.
- Do not circulate the VPT curriculum to endodontists until A51 ships and the haemostasis
  sections are corrected.
