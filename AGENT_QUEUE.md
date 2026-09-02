# CURO — AGENT QUEUE (single source of truth)

Everything outstanding, in execution order. Self-contained: a fresh agent session
can boot from this file alone, together with `CURO_HANDOVER.md`, `HANDOVER.md` and
`WORKLIST.md`.

---

## §0 BEFORE STARTING — DONE (2026-09-02)

**Both fixtures now exist and are committed.** This section is kept as the record
of what they are and what depends on them.

1. `eval/fixtures/second_opinion_anesthesia_2026.md` — committed `5f887cb`
   The SR/MA-restricted anesthesia answer produced by a general-purpose model with
   web search (no PMIDs, journal + year citations only). Used by Stage 5.
   **47 citation instances in §§1-6**, which is inside Stage 5's expected 45-50,
   so [L1] does not trip its stop-and-report condition. Two parser traps already
   measured and written up in `CURO_HANDOVER.md` §5e: §7 is a protocol that
   RE-CITES §§1-6 in shorthand and must be linked rather than resolved, and §6's
   device table cites without brackets in five of seven rows — one of which is
   [L4]b's own liposomal-bupivacaine target.

2. `eval/fixtures/review_apixaban_apicectomy.md` — committed `959844e`
   The Curo Review-path answer to "Eliquis in patients who need apicectomy",
   including the header banner, the full body, the references block, the FULL
   BIBLIOGRAPHY list and the TOP PAPERS BY EVIDENCE SCORE table. Used by Stage 1.
   **It already contains live evidence for three Stage 1 items**, captured
   unedited: Q4's raw-marker leak (`[[PMID:ESE-QG-2023]]` rendered in double
   brackets while every other citation became a pill, because the renderer
   matches digits and the identifier has none); Q3's impact factors on a rendered
   surface (`(IF: 12.0)`, `(IF: 4.5)` throughout the references block); and Q6's
   cross-tier sort (the score table puts the 87/100 ESE statement above the
   Cochrane review at 73.3). Do not "fix" the fixture — it is the before-state.

Opening instruction for the agent session:

> Read `AGENT_QUEUE.md`, `CURO_HANDOVER.md`, `HANDOVER.md` and `WORKLIST.md`,
> then execute `AGENT_QUEUE.md` from §3 in order. Follow §1 standing rules on
> every item. Stop where a stage says STOP.

---

## §1 STANDING RULES — apply to every item

1. **Measure before changing.** Every fix is preceded by a measurement that
   identifies the cause. Do not fix a hypothesis.
2. **Dry-run all DB writes** and report the delta split before applying. Back up
   **every** column a migration overwrites, embeddings included.
3. **Mutation-check every new test.** A test that has never been observed to fail
   is not evidence.
4. **A test whose assertion can become vacuous must be paired with a test that
   fails when it does.** (Origin: the streaming assertion is only meaningful while
   the stitch budget exceeds the SDK non-streaming ceiling; a second test asserts
   the budget still crosses it.)
5. **Any component that discards, caps, filters or drops candidate content must
   log and count what it discarded.** Silent discard is a defect regardless of
   whether the surviving output looks correct. Three instances of this class in
   one night: module cap at 3,200, stitcher budget at 11,640, domain filter
   excluding 48 of 124 canon papers.
6. **Never weaken a checker, gate or guard to improve a number.** A failing gate
   is a finding. If a gate rejects correct work, the gate's *logic* is wrong —
   fix the logic, do not lower the bar.
7. **Real fixtures only.** No synthetic data standing in for real output.
8. **wip-commit before any destructive git operation.**
9. **Eval runs strictly serial.** Never two eval processes at once.
10. **Push and refresh the OneDrive bundle after every completed item.**
11. **Parallel agents never share files.** See §2 ownership table.
12. **Cost is reported beside hits-per-query and paper counts, never alone.**
13. **Never re-baseline silently.** Any eval case that moves is explained as code
    change or variance, in the report.

---

## §2 EXECUTION ORDER AND PARALLELISM

Sequential unless stated. Recommended: **two agents**.

| Agent | Stages | Owns these paths — no other agent may touch them |
|---|---|---|
| **A (main)** | 3 → 4 → 5 → 6 | `app.py`, `endo_ai.py`, `rag.py`, all templates/render layer, `webdeck/`, `presentations/`, `scripts/` |
| **B (audit)** | 7 only, may start immediately | `eval/fixtures/*`, `eval/reports/citation_audit_v1.md`, `eval/questions_border.json` is **not** B's — leave it |

Agent B must run **no eval** and make **no DB writes** until Agent A signals
Stage 6 is finished (Stage 6 owns the eval harness and serial-run rule). If in
doubt, Agent B stops and reports rather than running anything under `eval/run_eval.py`.

Stage order rationale: Stage 3 is trust defects on the surface being demoed, and
two of its items are minutes of work. Stage 4 must not run before Stage 3 because
its fixtures are stale. Stage 6 ends in a decision for RB and must not be
pre-empted by implementation.

---

## §3 STAGE 1 — `trust-surface-v1`  (highest priority)

Fixture: `eval/fixtures/review_apixaban_apicectomy.md`. Tag `trust-surface-v1`.

### Q1 — The verification banner must not cover unchecked text

Measured defect: the answer rendered `CHECKED AGAINST ABSTRACTS: 9/9 CONSISTENT`
while an entire paragraph of drug directives (">=4 hours after the morning dose",
"tranexamic acid 4.8% mouthwash", "CrCl <50 mL/min", "age >75", "omit the morning
dose") carried **no citations** and was therefore never checked.
`verify_citation_support` examines cited claims only; uncited claims are invisible
to it, and the banner then asserts verification over the whole answer. This is a
fail-open gate on the most trust-critical surface in the product.

- **Q1a** Add an uncited-claim detector that runs on the **rendered** answer, not
  the model output. Segment into claims; classify each cited / uncited; count
  uncited claims that are *clinically directive* (contain a dose, drug name,
  interval, threshold, measurement, or an imperative verb).
- **Q1b** The banner reports **both** numbers and may never show an unqualified
  pass while directive uncited claims exist. Required form:
  `CHECKED AGAINST ABSTRACTS: 9/9 CONSISTENT · 6 CLAIMS NOT FROM THE EVIDENCE BASE`
  with the second half styled as a warning, not a tick.
- **Q1c** Tests, both directions, both mutation-checked: the apixaban fixture must
  **not** produce an unqualified pass; a fully-cited fixture must still show the
  clean tick (rule §1.4 — the gate must not become vacuous).

### Q2 — Out-of-domain content is quarantined and reframed  *(RB decision, 2026-09-02)*

Policy: Curo **may** answer beyond its evidence base, but that content is
visually and structurally separated, and the answer then returns to the decision
Curo can support.

- **Q2a** Render general-knowledge content in a distinct block: own container,
  warning border, explicit header `NOT FROM THE EVIDENCE BASE — UNVERIFIED`, and
  a footer naming the guidelines to consult. Use the dark design tokens. It must
  be unmissable at a glance and survive every export path.
- **Q2b** It may never be interleaved with cited prose in the same paragraph, and
  is excluded from the checked-claims denominator (it feeds Q1's second count).
- **Q2c** Preserve and *require* the reframe: after the quarantined block, state
  the endodontic decision the library does support. The fixture already does this
  well — Cochrane RR 1.15 (0.97–1.35) means non-surgical retreatment is a
  legitimate alternative in a bleeding-risk patient. Make it a required element,
  not an accident.
- **Q2d** Test on the fixture: quarantine block present and correctly bounded, no
  directive text outside it, cited reframe present. Mutation-check.

### Q3 — Remove impact factor from every rendered surface  *(invariant 11)*

`Cochrane Database Syst Rev (IF: 12.0)`, `Int Endod J (IF: 4.5)` appear in the
reference list. IF was removed from scoring by decision; displaying it
contradicts the stated method and the pitch. Strip IF from references,
bibliography, tables, tooltips, exports and speaker notes. Grep the templates
**and** assert on rendered output. Mutation-check by re-adding one.

### Q4 — Raw PMID leak on the Review path  *(invariant 3)*

`[[PMID:ESE-QG-2023]]` rendered raw in the Level I section. The existing case-v3
fix evidently does not cover non-numeric PMID keys (guideline / position-statement
pseudo-ids). Fix at the render layer for **all** key shapes; add the pseudo-id
form to the invariant test. Mutation-check.

### Q5 — Bibliography = citations, on the Review path too

The fixture lists **29 papers and cites 7**, including Sjögren 1990 — the same
uncited boilerplate seen in the anesthesia curriculum. This confirms the
bibliography defect is **structural, not a truncation artifact**, and affects
Review as well as Deep Learning.

Fix at the **shared bibliography assembler**, which must consume the in-text
citation set, not the retrieval candidate pool. Set-equality test in both
directions on **both** fixtures (apixaban Review answer; post-fix anesthesia
curriculum from Stage 2). Mutation-check by injecting one pool-only paper.

A separate, clearly-labelled "papers retrieved but not cited" disclosure is
allowed if that transparency is wanted — but it is not the bibliography and must
not be presented as one.

### Q6 — "Top papers by evidence score" table sorts across tiers

A position statement at 87.0 displays above the Cochrane review at 73.3.
Invariant 1: score ranks only *within* a tier. The engine is correct; the
presentation is not. Sort tier-first then score-within-tier, and label the score
column so it cannot be read as a cross-tier ranking. Test: a lower-tier paper
never renders above a higher-tier one regardless of score.

### Q7 — Why did retrieval return no anticoagulation literature  *(measure only)*

Report, do not fix. For the apixaban question, log every candidate excluded by
`ENDO_DOMAIN_FILTER` with its cause; separately report whether the generated
search terms ever included apixaban / DOAC / anticoagulant vocabulary, and
whether live PubMed was attempted.

Hypothesis to test explicitly: **the same global domain filter that excludes 48
of 124 canon anesthesia papers also excludes the oral-surgery and haematology
literature that answers this question.** If confirmed, record it as a second
independent symptom of one root cause and carry it into Stage 6.

### Q8 — Rendering

An orphaned `not applicable.` line follows the third paragraph of the fixture.
Find the empty-field template branch producing it; render nothing when the field
is empty. Test on the fixture.

**Stage 1 done when:** Q1–Q6 and Q8 fixed with mutation-checked tests, Q7
measured and reported, before/after rendered output included for Q1–Q4, Q6, Q8.
Push, re-bundle, tag `trust-surface-v1`.

---

## §4 STAGE 2 — `dl-quality-v2` (with sequencing correction)

### M — Regenerate the anesthesia curriculum before auditing it  *(do first)*

The dl-quality-v2 items F–J were written against anesthesia output produced
**before** the module-cap, stitcher-budget, streaming and mid-stream-retry fixes.
That document was truncated at two layers, so any defect observed in it may be a
truncation artifact rather than a synthesis defect. The laser regeneration went
from 5,653 to 12,555 words on the same question — over half the content was being
silently discarded, so every prior critique of the anesthesia curriculum judged a
half document.

- **M1** Regenerate on the fixed pipeline. Store as
  `eval/fixtures/anesthesia_curriculum_postfix.md` **alongside**, not replacing,
  the pre-fix version. Report the same before/after table used for laser:
  modules, words, truncated modules, unchecked claims, cited PMIDs.
- **M2** Re-observe each of F–J against the **post-fix** document. Report per
  item: `STILL PRESENT` / `RESOLVED BY TRUNCATION FIX` / `CHANGED (describe)`.
  Specifically re-check: bibliography-vs-citation set equality; the
  "N further cited claim(s) were NOT checked" footers; the IANB volume
  contradiction across modules; the differing onset waits and lip-numbness
  intervals; the 3.88 mm foramen directive; the plain-lidocaine hypertensive
  directive; the Cochrane n=19,223 subgroup misattribution.
- **M3** Run only the items still present. For anything resolved, say so and do
  **not** write a test asserting a defect that no longer occurs — but **do** add a
  regression test for the underlying invariant where one is missing.

*Note:* item F (bibliography set-equality) is already being fixed at the shared
assembler in Stage 1 Q5. Do not duplicate the fix; verify it holds on the
post-fix curriculum and add the second fixture to the existing test.

### G — Endpoint-definition discipline for success rates

Measure first: across the post-fix anesthesia fixture, list every `%` success
claim, the endpoint its cited abstract defines (lip numbness / EPT / pain-free
access), and whether the rendered claim states it. Then:

- Synthesis prompt rule: a success `%` must carry its endpoint when the abstract
  states one, and two rates with different endpoints may not be juxtaposed as
  comparable without saying so.
- Extend `verify_citation_support`: flag a `%` claim that drops an endpoint
  qualifier present in the abstract.

Report flag-rate impact on the 5-case synthesis subset. A rise here is a true
positive, not a regression.

### H — No population mean as a per-patient instruction

Module 4 turned a mean foramen position (3.88 mm above the occlusal plane, cited
range −3 to +10 mm) into a measurement step. Extend the ranges-as-scalars gate
from charts to protocol text: a numeric directive derived from a central tendency
whose cited dispersion spans a clinically different action must be rendered with
the range, or not as a directive. Real-fixture test; mutation-check.

### I — Uncited clinical directives on the DL path

"1.8 mL plain lidocaine IANB for hypertensive patients" — determine whether it
carries a citation. Uncited → the recommendation-traceability gate does not cover
the DL path; extend it (Stage 1 Q1 builds the detector — reuse it, do not write a
second one). Cited but unsupported → a `verify_citation_support` miss; add the
pair to the adjudication set and report the split. **Do not hand-edit the
clinical content** — fix the gate and regenerate.

### J — Cross-module protocol consistency

Assert on the regenerated curriculum that these do not recur: IANB volume stated
as conclusive in one module and as no-difference in another while a third
prescribes the lower volume; onset wait differing across modules; lip-numbness
check interval differing across modules; supplemental-injection order differing
across modules.

Where the literature genuinely conflicts, the curriculum must **say** it conflicts
and cite both sides once — a single reconciled statement reused across modules —
never state each side flatly in different modules. Test on the stored fixture;
mutation-check by re-injecting one conflict.

Also carry forward from dl-quality-v1: remove the 30-claim support cap if still
present, and adjudicate PMID 27759881 (CBCT misattribution) and the Sabeti
"noninferiority" overreach.

**Stage 2 done when:** M1–M3 reported, surviving items fixed with tests, eval
deltas explained. Tag `dl-quality-v2`.

---

## §5 STAGE 3 — `classics-v1` remainder

B1 and B2 are complete (124-paper canon list built; 48 excluded by
`ENDO_DOMAIN_FILTER`). Remaining:

### B3 — Fix only what the B2 table shows, **excluding the filter branch**

Priority order:

1. If the **classics exemption is not firing** on papers that qualify: fix the
   exemption logic. Mutation-checked test built on real rows from B2.
2. If the papers were **never ingested**: ingest with full provenance (tier from
   study design, COI tri-state, MEDLINE status, retraction/supersession check).
   Dry-run with delta split first. Targeted adds, not a bulk import.
3. If **retrieval vocabulary misses them** (query says "inferior alveolar nerve
   block" but classics are indexed under other terms): extend the synonym groups;
   show hits-per-query before and after.

**Do not widen `ENDO_DOMAIN_FILTER` in this stage.** The filter branch is deferred
to Stage 4's measurement and RB's decision. If the B2 table shows venue exclusion
is the *dominant* cause, say so and stop that branch — do not implement.

**No journal-identity weighting anywhere** (invariant 11).

### B4 — Verify

Regenerate the anesthesia curriculum (reuse the Stage 2 post-fix run if nothing
changed since) and report the before/after citation list: does the classic corpus
now appear where clinically appropriate? Full retrieval eval, serial, no
regression outside baseline ranges. Explain every case that moves.

### C — Lock the no-journal-weighting decision *(skip if already done — check git log)*

- **C1** Invariant test: the scoring path takes **no** journal-identity input. No
  journal name, ISSN or venue-derived feature may reach `score_paper`'s
  arithmetic. Journal is permitted **only** for the Cochrane journal-verification
  check and for display metadata. Built on the actual scoring code path, not a
  source grep. Mutation-check: temporarily add a +1 JOE bonus, confirm the test
  fails, revert.
- **C2** Append to `CURO_HANDOVER.md` §2:
  > **11.** No journal-identity signal in scoring or ranking. Venue is metadata
  > and Cochrane-verification only. Decided by RB 2026-09-02 (JOE-vs-IEJ
  > question); the remedy for missing canon papers is retrieval/ingestion fixes,
  > never venue weight.

Tag `classics-v1`.

---

## §6 STAGE 4 — `scope-measure-v1`  (MEASUREMENT ONLY — ends in a decision)

**No DB writes. No filter changes. No behaviour changes. No re-baselining.** Every
filter experiment is a **shadow** run: log what *would* have been retrieved,
change nothing about what the system actually returns.

**Purpose.** Decide from numbers whether Curo's literature scope stays
endodontics-only, widens to adjacent dental specialties (topic-gated), or widens
further. Two anecdotes prompted this — 48 of 124 canon anesthesia papers excluded,
and the apixaban answer retrieving nothing relevant. Neither is sufficient
justification on its own.

### S1 — Build a border-question set

`eval/questions_border.json`: 20–25 realistic questions an endodontist would ask
whose answers live at the edge of, or outside, endodontic journals. 2–3 per
domain, each tagged with its expected domain:

anesthesia · oral & maxillofacial surgery (apical surgery technique, medically
compromised patients, bleeding) · prosthodontics/restorative (post-endodontic
restoration, cuspal coverage, posts, cracked tooth) · periodontics (endo-perio
lesions, vertical root fracture) · oral radiology (CBCT interpretation and
dosimetry) · oral medicine / orofacial pain (non-odontogenic pain mimicking
pulpitis, atypical odontalgia) · paediatric dentistry (pulpotomy, immature apex,
regenerative endodontics) · oral pathology (differential of periapical
radiolucency — cysts, non-endodontic lesions).

Plus **3 out-of-dentistry controls**: the apixaban question, an MRONJ /
bisphosphonate question, an infective-endocarditis-prophylaxis question. These
must **not** be answerable by any dental journal — they exist to prove the
*routing* case, not the ingestion case.

### S2 — Classify every failure

Run the 25 existing eval questions and the border set with full filter logging.
Per question report: papers retrieved; papers excluded by `ENDO_DOMAIN_FILTER`
with cause; whether the coverage gate fired; whether live PubMed was attempted;
the generated search terms. Then classify each outcome as exactly one of:

- `ADEQUATE` — relevant evidence retrieved
- `DOMAIN FAILURE` — relevant literature exists but was excluded by the filter
- `RETRIEVAL FAILURE` — in-domain literature exists but the query missed it
- `TRUE GAP` — no literature exists at any scope (route, don't ingest)

Report the four-way split for the existing set and border set **separately**.
This split is the decision: `DOMAIN FAILURE` counts argue for widening;
`RETRIEVAL FAILURE` counts argue for fixing queries instead.

### S3 — Shadow run: what would widening actually admit

For every question in both sets, re-run retrieval with `ENDO_DOMAIN_FILTER`
disabled, **in shadow**: record candidate pools, return nothing to the user, write
nothing to the DB. Report the papers the filter currently excludes that widening
would admit.

Hand-classify a random sample of **100** admitted papers as `RELEVANT` (would
improve the answer) / `NOISE` (loosely related, would dilute) / `HARMFUL` (wrong
specialty, misleading). **Report the ratio per domain, not just overall** — the
question is whether some doors are worth opening and others are not.

Also report volume: additional papers per question, and estimated embedding +
scoring cost per answer at the wider scope.

### S4 — Guideline inventory  *(likely the cheapest win — measure it properly)*

Separately from journals, inventory authoritative specialty guidelines: ESE, AAE,
SDCEP, ADA, AAOMR and equivalent bodies. Report which are already in the library
(`ESE-QG-2023` is), which are absent, how many documents each body publishes that
touch endodontic practice, and whether each is retrievable via PubMed or needs
another ingestion path.

For each of the 3 out-of-dentistry controls, name the **specific guideline
document** that answers it and state whether Curo could have cited it. Estimate:
document count, ingestion effort, and how many S2 failures a guideline corpus
alone would convert to `ADEQUATE`.

### S5 — Recommendation memo, then **STOP**

`eval/reports/scope_measure_v1.md`: the S2 four-way splits, S3 relevance ratios by
domain plus cost/volume, S4 guideline inventory. Close with a ranked
recommendation of which specific domains (if any) justify a topic-gated door,
which do not, and where a guideline corpus beats a journal expansion. State
plainly what the numbers do **not** support.

**Implement no scope change. This stage ends with a decision for RB.**

Tag `scope-measure-v1`.

---

## §7 STAGE 5 — `citation-audit-v1`  (Agent B may start immediately)

Fixture: `eval/fixtures/second_opinion_anesthesia_2026.md` — a clinical answer
produced by a general-purpose model with web search, prompt-restricted to
SR/MA/NMA/RCT. It cites ~45–50 sources with **no PMIDs or DOIs**, only journal +
year + a reported statistic. Purpose: run those citations through Curo's existing
resolution and validation machinery and report factually how many survive. This
is a diagnostic **and** a demo asset. Build no new clinical content.

### L1 — Extract the citation manifest

Parse into `eval/fixtures/second_opinion_citations.json`, one record per citation
**instance** (same paper cited twice = two instances, linked by a shared
`resolved_id` once resolved). Fields: `claim_text` (verbatim sentence), `venue`,
`year`, `claimed_level` (NMA / SR-MA / SR-MA+TSA / RCT / diagnostic /
observational / consensus), `reported_stats` (every number verbatim with its
measure type — RR, OR, %, CI, SUCRA, I², n, P), `self_flagged`.

Report the extracted count and full manifest **before** doing anything else.
Expect ~45–52. Stop and report if far off — a bad parse invalidates everything
downstream.

**Parser corrections (already scoped — apply them):**

- **O1** A prior count found **47 instances in §§1–6**. Confirm whether that
  already includes the **5 bracket-less device-table citations in §6**. If not,
  the true count is ~52 and the parser is losing five before it starts —
  including L4b's own liposomal-bupivacaine target. Report the reconciled count
  explicitly.
- **O2** Parse at **claim level, never on bracket tags**. A citation instance is a
  claim carrying an attribution whether or not it is bracketed —
  "Cochrane: reduces pain vs placebo" and "Two phase III RCTs: 70 vs 155 min" are
  instances.
- **O3** §7's back-references (`[SR/MA+TSA ×2, NMA]`, `[NMA top rank; RCT 92.5%]`,
  `[consensus only]`) are **links** to instances in §§1–6, not new citations. Give
  them a distinct record type: they resolve to a parent instance id, are **never**
  sent to PubMed, and are excluded from the RESOLVED/AMBIGUOUS/NOT_FOUND
  denominators. Report them separately as internal-consistency checks — does each
  back-reference match the evidence level of the instance it points to? A mismatch
  is a real finding about the document.

### L2 — Resolve each citation against PubMed

Use the existing retrieval code paths, not ad-hoc queries. Classify each instance
as exactly one of `RESOLVED` (single unambiguous match on venue + year + claim
content) / `AMBIGUOUS` (plausible candidates, none uniquely determined) /
`NOT_FOUND` (no paper in that venue and year plausibly matches). Record the PMID,
the candidate PMIDs, or the exact queries tried.

> **CRITICAL — do not violate this; the value of the batch depends on it.**
> `AMBIGUOUS` and `NOT_FOUND` are **not evidence of fabrication**. Journal + year
> is genuinely insufficient to identify a paper, and Curo's own library coverage
> is finite. The report must state this explicitly and must never label an
> unresolved citation "fake", "hallucinated" or "fabricated". The only defensible
> claim is *"not verifiable from the information the document provides"*. Output
> that overstates this is a **failed item**, not a good finding.

### L3 — Value check on everything that resolved

Fetch the full abstract; run `verify_citation_support` plus a numeric check. Per
instance report: does every number in `reported_stats` appear verbatim in the
abstract, same quantity and same unit (apply the chart gates as text rules — no
range reported as a scalar, no unitless pair treated as comparable)? Does the
claim describe what the abstract reports, or transfer a whole-review figure to a
subgroup (the n=19,223 misattribution class)? Is `claimed_level` correct against
Curo's tier ladder, derived from study design — **never** from the document's own
tag?

Classify: `SUPPORTED` / `PARTIAL` (claim broader than the abstract) /
`UNSUPPORTED` / `NOT_CHECKABLE` (abstract too thin to judge).

### L4 — Targeted checks on known suspects

Report each individually and by name whatever the aggregate shows:

- **a.** "dexamethasone … RR 1.80; 95% CI from 1.35" — a CI with a lower bound and
  no upper bound is malformed. Determine whether the source reports a complete
  interval and what it is.
- **b.** The liposomal bupivacaine claim attributed to "Cochrane" with no review
  named — identify which review, or record that it cannot be identified.
- **c.** Every 2026-dated citation (at least *Int Endod J* 2026, *BMC
  Anesthesiol* 2026) — confirm whether a 2026 record exists, epub-ahead-of-print
  included.
- **d.** The two distinct "SR/MA, Cureus 2025" citations (cryotherapy; magnesium
  sulfate) — confirm they are two different papers, not one reused.
- **e.** The Zanjir NMA 52% / 5,094 figure and the *Int Endod J* 2021 3.6 mL
  RR 1.94 (1.07–3.52) — load-bearing for the document's protocol; check with
  particular care.

### L5 — Library action, additive only  *(requires Agent A's clearance)*

Papers that are `RESOLVED`, pass L3, and are absent from the library: ingest with
full provenance. **Dry-run with delta split reported before applying.** Do not
ingest anything `AMBIGUOUS` or `NOT_FOUND`. Do not ingest on the document's
description alone — only on the fetched record. Re-run the retrieval eval
serially afterwards and explain any case that moves.

### L6 — Report and demo asset

`eval/reports/citation_audit_v1.md`: counts (instances extracted; RESOLVED /
AMBIGUOUS / NOT_FOUND; and within RESOLVED the SUPPORTED / PARTIAL / UNSUPPORTED
/ NOT_CHECKABLE split); the full per-instance table; the five L4 findings; papers
newly ingested and eval deltas; and a plainly worded limitations paragraph
restating the L2 rule.

Then generate **one** slide into the existing dark deck pipeline via the shared
`slide_spec_cache` (both exports consume the same spec, content hash asserted): a
side-by-side of a single real example — the document's claim as written on the
left, Curo's checker output for the same claim on the right. Choose in this order
of preference: a `RESOLVED`-but-`PARTIAL` claim > a `RESOLVED`-but-`UNSUPPORTED`
claim > an `AMBIGUOUS` one labelled exactly *"not verifiable from the citation as
given"*.

Every value on the slide must appear verbatim in the cited text and obey all chart
gates. **If no example clears those gates, produce no slide and say so** — a
missing slide is a valid outcome and far better than an overclaiming one.

Tag `citation-audit-v1`.

---

## §8 REPORT FORMAT — every stage

For each item:

1. **What was measured** — the numbers observed before any change.
2. **Cause** — the actual defect, distinguished from the hypothesis.
3. **What changed** — files touched, one-line rationale each.
4. **Tests** — count before/after, and the mutation-check result for each new
   test (which mutant, killed or survived).
5. **Eval delta** — cases moved, each explained as code change or variance.
6. **Cost** — beside hits-per-query and paper counts, never alone. Report failed
   or crashed attempts separately and honestly.
7. **Anything that changed your understanding** rather than only your code.
8. **Open questions / decisions for RB.**

---

## §9 DECISIONS ALREADY MADE — respect these, do not relitigate

- **No journal-identity weighting** in scoring or ranking, ever. JOE-vs-IEJ asked
  and declined, 2026-09-02. Remedy for missing canon papers is retrieval and
  ingestion fixes.
- **Out-of-domain content is quarantined and reframed**, not refused and not
  silently mixed in. 2026-09-02.
- **No scope/filter widening without the Stage 4 numbers and RB's sign-off.**
- **`monthly_maintenance.py` must not run `--apply`** until after the demo.
- **The X-ray / vision path stays off** until a BAA exists.
- **`cost_log.jsonl` is append-only** — never edit historical rows.
- Cochrane tier is journal-verified; withdrawn and superseded versions excluded on
  both paths.
- Tier hierarchy is by study design, never by score; unknown design bands to the
  weakest tier.

---

## §10 WHAT ONLY RB CAN DO

1. **Re-zip the OneDrive backup without `.env`, and rotate all three secrets** —
   Anthropic key, OpenAI key, Neon database password. The current zip contains
   live credentials. The git bundle beside it is safe (`.env` was never committed).
2. Save the two fixtures in §0 before starting the agent.
3. Listen to 60 s of laser audio spanning "apexification" — confirm or clear the
   pronunciation flag.
4. Rehearse the demo on the presenting machine: 4 cached questions, 1 live, web
   deck citation click, video clip. Use the `endo-ai-noreload` config.
5. Decide the Stage 4 scope question once the memo lands.
6. Decide the first `monthly_maintenance.py --apply` date (after the demo).
7. Verify against full text, before any of it reaches teaching material: buccal
   infiltration success being ~45–85% rather than 80–90%; articaine IO being
   evidence-supported; plain lidocaine being the wrong hypertensive choice.
