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
14. **A test must exercise the expression the production path evaluates**, never a
    restatement of it in the test or a helper. (Origin: A1 — deleting the coverage
    condition from the real gate conjunction in `app.py` left all 30 tests green,
    because every one asserted on the coverage functions or on a local copy of the
    decision. Same class as A4.) Where a decision is a conjunction, pin both that
    the new condition is a conjunct and that the existing conditions remain
    conjuncts.
15. **Any new append-only log gets its `conftest.py` redirect in the same commit
    that creates it.** (Origin: A13c did this on day one; the four audit logs that
    preceded it were each redirected only after a test run had already polluted the
    production record.)
16. **An adjudicated sample is frozen and committed before any change that could
    alter the pool it was drawn from.** A seed is not a freeze — the same seed over
    a changed pool returns different items, and hand verdicts then silently
    misalign. (Origin: A3's 40-claim sample was overwritten by a re-run and had to
    be rebuilt from git.)
17. **A gate that strips, vetoes or matches text is tested against the variants the
    corpus actually contains, not the canonical form.** Measure the real forms
    first; enumerate accepted values rather than wildcarding. (Origin: A16d — every
    Q3 test used a numeric impact factor, the model emitted `(IF: n/a)`, and only a
    live check caught it. The wildcard that would have matched it would also have
    eaten "(IF the canal is calcified…".)
18. **Any transform applied at read time must be idempotent**, and a test must
    assert it. (Origin: A16b made two archive routes re-render on every read, and
    `finalise_answer_text` was not idempotent — the status block quotes flagged
    claims, those quotes carry the quarantiner's vocabulary, and a second pass
    nested the trust banner inside the unverified block it reports on.)
19. **A score never decides membership; only ranking within a tier.** Relevance
    decides what enters a candidate set — similarity, coverage, question match.
    Score decides the order of what is already in. Using one where the other
    belongs is a category error, not a tuning choice. (Origin: A5b — the per-tier
    cap kept 25 of 60 level1 papers *by score*, cutting the single most on-point
    RCT at rank 54/60 in favour of position statements that were less similar to
    the question. That manufactured a false evidence gap three steps downstream.)
20. **A shared file is never replaced wholesale; changes are grafted additively.**
    `AGENT_QUEUE.md`, `CURO_HANDOVER.md` and `WORKLIST.md` have more than one
    writer. Before editing, read the version in the repo — not a local or
    downloaded copy — and assert afterwards that the sections you did not touch
    survived. (Origin: a dropped whole-file copy would have reverted §0 and
    deleted the 47-instance count Stage 5 L1 is keyed to, twice in one day.)

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

## §8b AMENDMENTS — added after Stage 1 completed

### A1 — The coverage gate must test question coverage, not just endodontic similarity
**New item. Run before Stage 4. Priority: high.**

Stage 1 Q7 measured something different from its own hypothesis, and the real
finding is worse. For the apixaban question, **live PubMed was never attempted**:
50 s of retrieval between two logged LLM calls, zero esearch rows.
`ENDO_DOMAIN_FILTER` never ran. Query generation was not the failure either — 6 of
7 generated terms carried apixaban / DOAC / warfarin vocabulary. The
**library-first coverage gate** passed all four of its conditions (14 papers above
the similarity floor against a minimum of 12) and short-circuited live retrieval.
**None of those 14 papers mentions anticoagulation.**

The gate measures similarity to the endodontic corpus, not whether the retrieved
set addresses the question asked. It is the same class as the verification banner:
a check that returns a confident pass on evidence it never actually examined.

- **A1a** Add a question-coverage condition. Extract distinctive entity terms from
  the generated search terms (drug names, device names, technique names,
  populations) and require that a minimum number of candidate papers contain at
  least one, in title or abstract. If that is not met, the gate must **not**
  short-circuit live PubMed regardless of similarity counts.
- **A1b** Log the gate verdict per question — pass/fail on **each** condition, the
  coverage term list, and hit counts. A silent short-circuit is standing rule §1.5.
- **A1c** Measure the cost consequence **before** applying: replay the gate offline
  across all stored questions and report how many would now go live, the projected
  added cost and latency per answer, and the distribution. Report it — **do not
  tune the threshold to hit a cost target.** If cost is the problem, that is RB's
  decision, not the gate's.
- **A1d** Tests: the apixaban fixture must fail coverage and route live; a
  genuinely well-covered question from the eval set must still short-circuit.
  Mutation-check both directions.

### A2 — Stage 4 amendment (supersedes parts of §6 S2 and S3)

- **S2** must record, per question, the coverage-gate verdict with each condition's
  result, and whether live PubMed was attempted. A question that never reached
  PubMed **cannot** be classified `DOMAIN FAILURE`. Add a fifth class:
  `GATE SHORT-CIRCUIT` — the library-first gate skipped live retrieval.
- **S3**'s shadow run must disable **both** the coverage gate **and**
  `ENDO_DOMAIN_FILTER`, reported separately, so the two enforcement points are
  measured independently. Measuring only the filter would measure a code path this
  entire class of question never reaches.

### A3 — Banner counts: adjudicate before deciding the display

Measured in Stage 1: the banner's second half appears on **22 of 22** stored
curricula (median 8 claims) and **88 of 113** Review answers (median 2).

**Do not tune the detector to reduce the number.** The question is whether the
number is *true*, not whether it is comfortable (standing rule §1.6).

- **A3a** Hand-adjudicate a random sample of 40 flagged claims (25 DL, 15 Review).
  Classify each as `TRUE DIRECTIVE UNCITED` (a dose, threshold, interval or
  imperative with no citation) / `NARRATIVE` (framing, transition or restatement —
  not directive; detector over-reach) / `CITED ELSEWHERE` (supported by a citation
  in an adjacent sentence the segmenter split away).
- **A3b** Report the split. Then and only then:
  - mostly `TRUE DIRECTIVE` → the defect is in **generation, not display**. Fix via
    Stage 2 item I; the banner stays as is and the count falls on its own.
  - substantial `NARRATIVE` → the directive test needs sharpening. That is detector
    **accuracy, not leniency** — sharpen the definition, re-measure, re-mutation-check.
  - substantial `CITED ELSEWHERE` → segmenter defect; fix the claim boundaries.
- **A3c** Whatever the split, make the count **actionable rather than ambient**:
  flagged claims must be identifiable in the rendered answer (highlight or anchor)
  so the reader can see *which* sentences are unsourced. A number alone is a nag;
  a number that points at text is a tool.

May run alongside Stage 2.

### A4 — Build provenance check  *(COMPLETE — verdict: PRE-FIX)*

`/health` reported `082d67c`, four commits before Stage 1 began; the process ran
`debug=False` so Flask's reloader was off and it held the code read at 08:21.
Every Q3–Q6 symptom in the retreatment answer was a pre-fix artefact. **Nothing in
Q3–Q6 is incomplete.** Server restarted on `8da8823`. See A11 for the permanent fix.

### A5 — False gap declaration  *(A5a complete; A5b OPEN)*

Fixture: `eval/fixtures/review_retreatment_visits.md`. The answer asserted *"No
prospective study in this evidence base directly compares single- vs two-visit
retreatment protocols with adequate power."* Two directly on-point RCTs exist and
were not retrieved — Karaoğlan F, Miçooğulları Kurt S, Çalışkan MK, *Int Endod J*
2022 (100 single-rooted teeth, 88.6% vs 86.7% at 24 months) and Toia CC, Khoury RD,
Corazza BJM, Orozco EIF, Valera MC, *J Endod* 2022 (CBCT, 18-month follow-up).
Also missed: Schwendicke F, Göstemeyer G, *BMJ Open* 2017 (flare-up RR 2.13). All
are in core endodontic journals — **not** a domain-filter failure.

- **A5b — DONE (`9c611a5`), with its premise corrected.** Two of the three named
  papers were ALREADY in the library and still never reached the answer.
  Karaoglan 2022 was retrieved at similarity 0.648, cleared the floor, and was
  cut by the per-tier cap, which kept 25 of 60 level1 papers **by score** — it
  ranked 54th of 60, and 20 of the 25 kept were less similar to the question
  than the one dropped, led by AAE/ESE position statements at score 90.0/87.0
  (A7 arriving as a retrieval bug). `cap_by_relevance` now decides membership
  by similarity, orders by score, and logs what it drops. Toia 2022
  (PMID 34555421) really was absent and is ingested. Verified: the regenerated
  answer cites BOTH 2022 RCTs in its clinical recommendation and declares no
  evidence gap. **Schwendicke 2017 stays open** — below the floor on every
  generated query, a recall miss belonging to A14/A24, not to the cap.
  Original text below.

- **A5b — the original item.** A1 does not satisfy this. FIXTURE-retreatment does not flip the
  coverage gate: both concepts are covered at 9 and 19 papers. A5a identified a
  different mechanism (candidate cap + absent from library). Fix that mechanism and
  ingest the three papers with full provenance, dry-run with delta split first.
  **Done when this question retrieves the two 2022 RCTs.**
- **A5c — GAP-DECLARATION RULE.** No rendered statement may assert that evidence
  does not exist unless live PubMed was actually queried for that sub-question in
  that run. Where the coverage gate short-circuited, a gap sentence is forbidden
  and must be replaced with wording scoped to what was searched. Mutation-checked
  test on this fixture. This pre-empts the same failure in the planned
  "declare gaps instead of suppressing them" feature.

### A6 — Metadata integrity  *(premise corrected; superseded by A9)*

The IF field is internally consistent — 1,455 of 2,909 rows carry one and no
journal carries two values. The observed "Int Endod J at 4.0 and 4.5" was two
different papers, both mislabelled. The real defect: `format_paper_context_line`
carries **no journal name at all**, so every journal string in a Review reference
line is model-generated. Fixed by A9, not here.

### A7 — Position statements are not Level I

19 guideline rows. 15 hand-ingested ones sit in `level1` at 90.0/87.0, above every
Cochrane review in the library (36512807 is 73.7), while PubMed-indexed ESE
position statements score 50.4 and 30.9 across level1 and level5 — the same
document class treated three different ways. Assign guidelines and position
statements their own band per invariant 1 (tier by study design, never by score).
Report affected row count; dry-run with delta split before applying.

**Banding only. Change no score in this item** (see A12).

### A8 — Clinical comparison table  *(product improvement, lower priority)*

Where an answer resolves a two-option clinical choice, render a factor-by-option
table (factor | favours A | favours B) built **only** from cited claims, each cell
carrying its citation, obeying every existing chart/table gate. Zero-evidence cells
render as `—`, never as inference. Test on the retreatment fixture. Origin: the
competitor answer's practical-framing table, which Curo's synthesis contains as
prose and makes the reader assemble.

### A9 — The model writes prose, never metadata

Measured (A6): `format_paper_context_line` carries no journal name, so every
journal string in a Review REFERENCES line is model-generated. PMID 38145805 is
"Journal of dentistry" in the library and rendered "Int Endod J". The reference
list is the audit trail; generated metadata makes it decorative.

- **A9a** *(complete — see `eval/reports/a9a_reference_provenance.md`)* Field-by-
  field, surface-by-surface audit of DB-sourced vs model-supplied.
- **A9b** Assemble reference lines from stored provenance. The model supplies only
  the descriptive clause ("SR of contemporary NS retreatment; pooled healing…").
  Every other field renders from the row.
- **A9c** Test: no metadata field on any rendered surface originates from model
  output. Mutation-check by reintroducing one model-written field. Per standing
  rule §1.14, assert on the render path the product actually executes.
- **A9d** Propose for `CURO_HANDOVER.md` §2 as **invariant 12**:
  > The model writes prose, never metadata. Authors, journal, year, sample size,
  > follow-up and PMID render from the stored row on every surface. A metadata
  > field that reaches the page through model output is a defect regardless of
  > whether the value happens to be correct.

### A10 — Section-aware citation support (methods-as-findings)

Measured (Stage 2 item I): the hypertensive plain-lidocaine directive is cited to
PMID 40705444 and the sentence **is** in the abstract — as the trial's *method*
(the fixed setup of the hypertensive arm), not its finding. Every gate passes
because every gate asks "does the abstract say this?" and none asks "is this what
the paper found?" This is a gate class Curo does not have.

- **A10a** Extend `verify_citation_support` to classify the supporting sentence's
  role: background / methods / results / conclusions. Structured abstracts carry
  section labels; unstructured abstracts need a Haiku classification with the
  sentence in surrounding context.
- **A10b** A claim that is a clinical **directive** or an **effect** claim must be
  supported by results or conclusions. Support found only in methods or background
  is flagged `UNSUPPORTED_BY_ROLE` — a distinct class from the existing unsupported
  flag, reported separately so the two are never conflated.
- **A10c** Background-sourced support additionally catches citation-chain errors,
  where a background sentence restates another paper's result. Report those counts
  separately; they are a different clinical risk.
- **A10d** **Measure before enabling as a hard flag.** Replay across stored answers
  and report how many currently-passing citations would flip, **by surface**. Hand-
  adjudicate 20 of the flips before the flag goes live — a large flip rate may be
  correct (this class has never been checked) or may be a classifier failure, and
  only adjudication distinguishes them.
- **A10e** If it survives adjudication, propose as an invariant.

### A11 — Build provenance must be visible

Third stale-server false read in this project (A4, and twice previously).
`/health` already exposes the revision — that is not where it is needed.

- **A11a** Render the running git revision and process start time on the answer
  surface (footer is fine) and record both in every saved answer's provenance.
- **A11b** Log a loud warning at startup when the running revision != git HEAD.
- **A11c** Test: a saved answer always carries the revision that produced it.

### A12 — Decisions  *(RB, 2026-09-02)*

- **Impact factor column: do NOT drop it.** Q3 already removed IF from every
  rendered surface and from the model's context, so the column is inert. An
  irreversible schema change days before the demo buys nothing. Add a test
  asserting the column reaches no prompt and no rendered surface; revisit after
  the demo.
- **A7 scope: banding only.** Do not recompute any score in the same change. The
  15 hand-ingested guideline rows at 90.0/87.0 versus PubMed-indexed equivalents at
  50.4/30.9 is a separate scoring inconsistency: report it with numbers, propose a
  treatment, and wait. If banding and scores move together, neither outcome can be
  attributed.
- **A3 re-measure** on the corrected detector — the quarantine header/footer
  over-count inflated DL flag counts by ~50% (12 of 24 flags on the measured
  document). Re-measure the per-curriculum and per-answer medians **before**
  adjudicating the 40-claim sample.

### A13 — Term-generation degradation rate  *(new, small, measurement first)*

A1's first wiring routed **every degraded run** live: when term generation fails,
the primary term is the raw question, which parses as one long "concept" no title
contains, so coverage scored 0. Now fixed by abstaining below two AND-groups — but
abstention means a degraded run falls back to the library route, which is the less
cautious of the two.

- **A13a** Measure how often term generation degrades, across all stored runs.
  Report the rate and what the degraded output looks like.
- **A13b** If the rate is non-trivial, degradation is itself the defect — fix the
  generator (the tolerant-parser/retry path already exists for this class) rather
  than choosing a routing policy for a state that should not occur.
- **A13c** Whichever way it goes, a degraded run must be **logged and counted**
  (standing rule §1.5). Silent abstention is the same class as silent discard.

### A14 — Degraded EXTRA terms as a retrieval-breadth defect  *(new)*

A13a settled the routing question — 0 of 149 recoverable primary terms degraded, in
every month — and correctly concluded no generator change on that basis. The
remaining 6.0% (108 of 1,790 topics, 92 of them raw prose, present in 34.2% of
runs) sits entirely in the **extra** terms: the "different angles" that give union-
KNN its breadth. That is not a routing cost, but it is not nothing either.

**Why this is not filed away:** A5 has an unexplained miss of exactly this shape —
Schwendicke *BMJ Open* 2017 was absent from the retreatment answer while the two
2022 RCTs were missed by a different mechanism (cap + absent from library). A
degraded extra term is a live candidate for the vocabulary-miss class. Treat A14
and A5's vocabulary branch as possibly the same defect until measurement separates
them.

- **A14a** Metric is **hits-per-query**, per standing rule §1.12 — never cost alone.
  For a sample of runs containing a degraded extra term, measure hits-per-query for
  that term against its healthy siblings in the same run. Quantify what breadth is
  actually lost.
- **A14b** Check the trend claim before acting: monthly rates are 26.1% (Apr),
  25.0% (May), 25.0% (Jul), 4.5% (Aug), 6.8% (Sep). Something changed around
  August — identify what, since the residual ~6% may be a different failure from
  the 25% one and the fix may already exist.
- **A14c** Test whether a degraded extra term could have caused the Schwendicke
  miss specifically. If yes, A5's vocabulary branch closes here.
- **A14d** Fix only if A14a shows real lost breadth. A degraded extra term that
  still returns useful hits is not a defect. Report the numbers first.
- Note the report's own caveat: the sample is live runs only, since a library-routed
  run leaves no audit row. Generation precedes routing so the sample is unbiased by
  route, and A13c's counter closes the gap going forward — but say so in any
  conclusion drawn from it.

### A15 — Unified search bar and three modes  *(UI; RB-approved design)*

Design reference: the Curo Search Modes canvas (5 artboards — Literature, Case,
Curriculum, mode suggestion, answer view). Build to it. Everything below is
settled; do not redesign.

**A15a — mode model.** Replace the five-tab row with ONE search surface and three
mode chips: **Literature · Case · Curriculum** (internally `review`, `case`,
`learn` — keep the existing route names, change only the labels and the shell).
Case Assessment and Profile move OUT of the mode row into the top-right nav.
A single `mode` value drives everything; there is no per-mode panel visibility
logic beyond it (this is what produced the learn-list-on-case bug — see rule 14:
one predicate the tests execute, not per-branch show/hide).

**A15b — the bar.** One input. Placeholder changes with mode:
  Literature  — "Ask a clinical literature question…"
  Case        — "Describe the patient and the tooth — age, symptoms, findings,
                 what you have already done…"  (taller field, min-height ~92px)
  Curriculum  — "Name a topic to learn in depth…"
Delete the second input entirely. The current Case Discussion screen shows TWO
input areas (the grey "Describe your case — patient age/sex…" block and the
CASE DISCUSSION box below it); exactly one survives.

**A15c — state the wait before the commit.** A single line under the bar, per mode:
  Literature  · dot #1e4fa3 · "A graded answer with citations, every claim checked
                against its abstract" · "about 15 seconds"
  Case        · dot #17803f · "A differential and a plan — and it asks back only
                what would change the answer" · "about 30 seconds"
  Curriculum  · dot #5b3ca6 · "Four modules with a full graded bibliography" ·
                "takes several minutes — you can leave the page" in #a5680f, 600
Modes differ ~3x in cost and ~50x in time (one stored curriculum cost $6.51).
Read the figures from the real cost log rather than hardcoding, if cheap to do.

**A15d — one history, badged, collapsed.** Replace the per-mode panels with ONE
list: badge (LIT / CASE / CURRIC) · title · right-aligned metadata (papers · cost ·
age for Literature and Curriculum; turn count · age for Case). Four rows visible
with an "All N ▾" control in the header — the current panel occupies ~60% of the
viewport before anything can be typed.

**A15e — mode suggestion, never mode switching.** When the text in Literature mode
looks like a patient case (age + tooth + findings), render a strip attached under
the bar: "This reads like a patient case. Case mode gives a differential and a
plan." with [Switch to Case] and a plain "Stay in Literature". It appears once per
input, never blocks submit, and NOTHING may auto-switch a mode that costs $2.50.

**A15f — three defects visible in the current UI, fix with the layout:**
  1. Stored titles carry appended follow-up text — "vital pulp therapy in adults
     Additional clinical context provided by the clinician: Q1: Are you asking
     about a specific patient case (e.g., traumatized tooth…". Store the
     clinician's ORIGINAL question as the title; the appended context is not part
     of it. Backfill existing rows where the original is recoverable; where it is
     not, truncate at the marker rather than displaying it.
  2. Two "Use of lasers in root canal disinfection" rows (118 papers/$1.36 and
     51/$1.18) are indistinguishable. Either de-duplicate or show what differs.
  3. The double input in A15b.

**A15g — tokens (lifted from the running app, do not invent).**
  page #ebedf4 · surface #ffffff · border #dfe3ec · row divider #eef1f6 ·
  panel header #f7f8fb / #e7eaf1
  text #16264d / #253451 · secondary #5b6885 · muted #8a94a8 · placeholder #9aa1ac
  Literature #1e4fa3 on #e7eefb, border #bfd3f2
  Case #17803f / #176b3d on #ddf3e6, border #a9dcc2
  Curriculum #5b3ca6 on #eae5fa, border #c8bcee
  Warning #b57a19 / #8a5510 on #fdf1dc, border #ecc98a
  Body font stack 'Segoe UI', system-ui, -apple-system, sans-serif; the Curo mark
  and answer titles in Georgia serif. Radii 12px cards / 999px chips / 7-9px
  buttons. Shadow 0 1px 3px rgba(22,38,77,0.06).
  Tab emoji are replaced by inline SVG line icons in the accent colours.

**A15h** Verify in the RUNNING app after restart (rule: template caching), one
screenshot per mode, and only then write the tests. Mode visibility is asserted
through the single predicate the app evaluates (rule 14).

### A16 — Fixed surfaces do not reach cached answers  *(HIGH — collides with the demo)*

A3 found that a cached answer rendered the pre-Q1 clean tick, `✓ CHECKED AGAINST
ABSTRACTS: 9/9 CONSISTENT`, because the cache path never re-runs the support
block. That was fixed for Q1. **The general case was not.** A cached answer is a
time capsule of the rendering that produced it, so every Stage 1 fix is suspect on
the ~113 stored Review answers and 22 curricula.

This matters immediately: the demo plan is four CACHED questions and one live.

- **A16a** For each of Q1, Q2, Q3, Q4, Q5, Q6, Q8 and A3c, determine whether the
  fix reaches a CACHED answer. Test against real stored rows, not regenerated
  ones. Report a table: fix | reaches cache? | how many stored rows affected.
- **A16b** For each fix that does not reach cache, decide and implement one of:
  re-render the stored answer through the current renderer at read time (preferred
  where the fix is presentational — Q3, Q4, Q5, Q6, Q8, A3c all look
  presentational), or invalidate the affected rows so they regenerate. Never leave
  a stored answer rendering a surface that the current code would not produce.
- **A16c** Add a general test: a stored answer from before a rendering change must
  render as the current renderer would. Mutation-check by reverting one renderer
  fix and confirming the cached-path test fails too.
- **A16d** Report which of the four intended demo questions are cached and whether
  each now renders every fix. This is a go/no-go for the demo script.
- Note the class for HANDOVER.md: **a cache is a time capsule of old behaviour;
  any change to a rendered surface must say what happens to what is already
  stored.**

### A19 — UI v2, to RB's sketch  *(COMPLETE — `7ca4ffc`)*

Built to the republished canvas; verified in the running app with a screenshot
per mode plus the drawer open; 36 tests, 14 mutants, 0 survivors.

Four changes RB made while it was being built, all shipped:
the real Curo mark instead of the line-art tooth; the tagline is
**Evidence-Based Dental Educator**, not "Clinical Educator"; "no follow-up
questions, just the answer" is off the promise line; "answers are built from
abstracts, not full texts" is off the card. The cards were then lined up with
the composer (a pre-A19 rule capped the grid at 80% of its column) and made
smaller and duller than it. A **progress clock** was added on his instruction:
`elapsed 0:13 · about 2s left`, ticking on its own timer rather than on the
1.5s poll, so a stalled poll cannot make the page look dead; past the estimate
it stops predicting rather than counting negative, and Curriculum gets no
countdown at all.

**One deviation from "use the copy verbatim".** The canvas card read graded
"never by journal, citation count or impact factor". Citation velocity is 16%
of the within-tier score with the impact factor off, so the card ships without
that clause. Journal and IF are genuinely unused and stay disclaimed. A17c:
make the copy true, never make the engine match it. One word to put back if RB
disagrees.

**Original specification, kept as the record:**

RB hand-sketched the layout. Design reference: the Curo Search Modes canvas,
republished — 5 artboards (Literature, Case, Curriculum, History open, Answer
view). A15's `MODES` table and `modeShows()` predicate stay exactly as built;
this changes the arrangement, not the architecture.

- **A19a — bigger lockup, centred.** Tooth mark ~54px beside "Curo" at ~62px
  Georgia serif, tagline underneath. Thin top bar only: History tab far left,
  Case Assessment and the avatar far right. No tab strip.
- **A19b — tagline is now "Evidence-Based Clinical Educator"**, not "Assistant".
  RB's edit. Change it on every surface — page header, exports, decks, speaker
  notes, README, `/status`, page `<title>`. Fold this into A17's sweep.
- **A19c — one composer, chips docked inside it.** A single white card: the input
  area on top, and along its lower edge a toolbar carrying the three mode chips on
  the left and the submit button on the right. The chips are INSIDE the card, not
  floating above it. Case keeps a taller input (~118px vs ~74px).
- **A19d — "WHAT YOU GET": three cards below the composer**, changing per mode.
  Copy is in the canvas artboards; use it verbatim. Every claim on those cards
  must be true of the engine (this replaces the card that said papers are ranked
  by "citations & impact factor" — see A17).
- **A19e — History becomes a collapsed drawer.** Closed by default; the tab is
  top-left. Opening slides a ~380px panel over the left of the page: mode filter
  chips (All / Literature / Case / Curriculum), then rows carrying badge, age and
  what distinguishes them (paper count and cost, or turn count). Nothing on the
  landing screen competes with the question box — the recent list leaves the main
  view entirely.
- **A19f — minimal by default.** Landing screen holds the lockup, the composer,
  the promise line, and the three cards. Nothing else.
- **A19g** Verify each state in the RUNNING app after a restart, one screenshot
  per mode plus one with the drawer open, before writing tests.

### A20 — Literature never asks the clinician a question  *(COMPLETE — `08a5f6f`)*

**A20a's answer was not where the item looked.** The answer BODY was already
clean — the synthesis prompt has forbidden ending on a question since
`trust-surface-v1`, and 0 of 10 stored review answers contain one addressed to
the clinician. The CLARIFY GATE in `/ask` was the interviewer, and 3 of 11
cached rows still carry its answered block inside their question text, which is
also how it reached stored titles (A15f.1) and an export header. `/clarify` is
a dead route and the router's `needs_clarify` is logged and never acted on.

**The premise was also wrong.** The gate is not review-only — it fires for
`learn` too, and three stored curricula carry an answered clarification block.
Curriculum therefore KEEPS it, deliberately, and a test pins the asymmetry.
**That is a decision left for RB**, not one taken here.

11 tests, 6 mutants, 0 survivors.

**Original specification, kept as the record:**

RB: "no need to ask questions back when a lit review question is asked."

Literature answers; it does not interview. Any clarifying-question path on the
`review` route is removed — including a question rendered as part of the answer
body, or appended follow-up prompts. Where the question is genuinely ambiguous,
Curo answers the most reasonable reading and says in one line what it assumed.

Case keeps its relevance-gated questions — there the question is the work.
Curriculum already asks none.

- **A20a** Find every place the review path can emit a question back: prompt
  instructions, the follow-up generator, any post-processing that appends
  suggestions. Report them before changing anything.
- **A20b** Remove them from `review` only. Do not touch the case path's
  relevance gate.
- **A20c** Where an assumption is made, state it in one sentence — an assumption
  declared is not a question asked.
- **A20d** Test on a deliberately ambiguous literature question: the rendered
  answer contains no interrogative addressed to the clinician, and does contain a
  stated assumption. Mutation-check. The promise line already claims this
  ("no follow-up questions, just the answer"), so the copy and the behaviour must
  land together — a promise on screen the engine does not keep is A17's defect.

### A21 — Follow-up and New topic on every answer  *(a–c, e COMPLETE; d OPEN)*

Most of A21c was already built and covered by `test_review_context.py` — the
thread store, the context block, the cache's `context_hash` partition, "New
topic", the continues-from line, both directions. What A21 actually added:

- the two controls on every answer, in every mode. Curriculum had **neither**:
  its New topic button was explicitly hidden and it had no follow-up path.
- a curriculum follow-up is answered as a scoped literature question over the
  curriculum's own cited evidence (`prior_pmids`), never by rebuilding it.
  Measured: a curriculum carries **39** cited papers into the thread, a review
  answer **6**; the 60/12 caps never fired.
- `/thread/seed`. An answer opened from HISTORY was invisible to all of this —
  a follow-up on it was answered cold AND inherited whatever thread the page
  was last on. Both wrong, in opposite directions, so seeding clears and seeds
  in one step, and the client sends a reference rather than content.

23 tests, 12 mutants, 0 survivors.

**A21d — OPEN, and the numbers say it is worth doing.** Measured on the running
app: an uncached literature follow-up is **74.0 s / $0.371 / 45 papers**; a
cached one returns in **1.0 s**. RB's observation is confirmed — a follow-up
takes about as long as a first answer, because `prior_pmids` SEEDS the
candidate set without shortening retrieval. The optimisation is real but the
item requires a recall check on the follow-up eval cases before it lands, and
that is a serial eval run (standing rule 9). Not started.

**One open thread, small sample, do not act on it yet.** Both uncached seeded
follow-ups run today needed an `ask_clinical_question_retry` — the
evidence-mapping validator caught a citation outside the evidence — against a
historical baseline of 17 retries in 137 answers (12%). n=2, and the obvious
mechanism is ruled out: only `CONTEXT_PMIDS_PER_EXCHANGE`=8 PMIDs are ever
NAMED in the prompt, whatever the seed size. Worth measuring properly, because
a retry roughly doubles the cost of an answer.

**Original specification, kept as the record:**

Every answer ends with two controls: a **follow-up composer** and a **New topic**
button. See the Answer view artboard. This is **not** a contradiction of A20:
A20 stops Curo interviewing the clinician; A21 lets the clinician continue. Render
**no suggested-question chips** — those are Curo prompting by another name.

- **A21a** Both controls on all three modes. Case already threads; Review has
  memory; Curriculum has no follow-up path and needs one.
- **A21b — a Curriculum follow-up must NOT rebuild the curriculum.** Answer it as
  a scoped literature answer over that curriculum's own evidence set, going live
  only for what the new question adds. A follow-up that costs $1.33 and several
  minutes is a broken affordance. Report the cost and latency of a follow-up in
  each mode.
- **A21c — context integrity, both directions** (invariant 7). A follow-up carries
  the thread's `context_hash` and must never hit a context-free cache row; **New
  topic** clears context and must never inherit the previous thread's. Test both
  directions and mutation-check — this is the pair where a one-way test passes
  while half the feature is broken.
- **A21d — latency.** RB has already observed that every follow-up takes as long
  as a first answer. Reuse the thread's candidate pool and retrieve only what the
  new question adds; measure before and after with hits-per-query beside the time
  (rule 12), and confirm no loss of recall on the follow-up eval cases.
- **A21e** A follow-up answer is an answer: the verification banner, the
  quarantine block, the citation checks and the bibliography rules all apply
  identically. Test that a follow-up cannot render a surface a first answer would
  not.

### A20 (revision) — Curriculum may ask, but only to narrow a broad topic  *(RB, 2026-09-03)*

A20's premise that Curriculum asks no questions was wrong; the agent found it does.
RB's decision: **Curriculum keeps the ability to ask, gated the same way Case is.**
It may ask when the topic is genuinely too broad to teach without direction
("regenerative endodontics" — immature apex or mature? outcomes or technique?).
It must NOT ask on a topic already specific enough to build from. Literature still
asks nothing at all.

Test both branches on real topics: a broad one must produce a narrowing question;
a specific one ("apicoectomy of mandibular teeth") must go straight to building.
Mutation-check both directions — this is the pair where a one-way test passes while
the gate is stuck open or stuck shut.

---

### A30 — Sweep for score used where relevance belongs  *(new, from A5b; do early)*

A5b found the per-tier cap deciding *membership* by score, cutting the most
on-point RCT in the library at rank 54 of 60 in favour of position statements that
were less similar to the question. One category error, three days of symptoms:
the retreatment false gap, and probably part of A23's apicoectomy anatomy gap.

Standing rule 19 now states the principle. This item finds the other instances.

- **A30a** Enumerate every point between query and synthesis where a set is
  truncated, ordered, capped, deduplicated or selected: the union-KNN merge, the
  authority guarantee, the coverage gate's counts, per-tier caps, the synthesis
  context budget, the bibliography assembler, the follow-up seed pool. For each,
  report what the decision is *for* (membership or ranking) and what input it
  actually uses.
- **A30b** Fix any that decide membership by score, the same way A5b did:
  membership by relevance, order by score, log what is dropped (rule 5).
- **A30c** For each fix, report which papers enter and leave on the three failed
  fixtures, with similarities — not just counts. A swap that trades 20 papers at
  similarity 0.78–0.67 for 20 at 0.60 scoring 78–90 is the whole finding.
- **A30d** Full eval serially afterwards; explain every case that moves.

**Related and now urgent:** A7's guideline banding. The hand-assigned 90.0/87.0
scores on 15 guideline rows are not only a display problem — they were actively
evicting trials from the candidate pool. A12 still stands (band first, do not
recompute scores in the same change), but the scoring inconsistency A7 reported
(hand-ingested guidelines at 90.0 vs PubMed-indexed equivalents at 50.4 and 30.9)
should now be brought to RB with a proposal rather than parked.

---

### A31 — The tier taxonomy has no slot for observational/descriptive designs  *(BUILD IT — RB decision)*

A23a's mechanism, proven: the seven tier filters are all publication types or MeSH
terms for **therapy and synthesis** designs — RCT, systematic review, meta-analysis,
controlled clinical trial, prospective studies, retrospective studies, cohort
studies, case-control, case reports, review. **Nothing matches a cross-sectional,
descriptive, morphometric, imaging or diagnostic-accuracy study.** Jeon 2021 is
found by the module query, survives `ENDO_DOMAIN_FILTER`, and disappears at the
tier filter. **46% of the most relevant papers for that question are reachable by
no tier filter at all**, including the bony-lid technique paper A23 says is
"absent entirely".

This is a fifth failure class and a new bug class for HANDOVER.md: **the taxonomy
cannot express the thing, so it can never be retrieved.** It produces no error —
only a thinner answer — which is why three separate investigations blamed the
domain filter, the cap and the coverage gate before finding it.

**RB decision (2026-09-03): build it now, do not wait for A25.** Those designs are
currently *unreachable*, which is a hole in the net rather than a ranking problem;
banding them weakest is additive and reversible, and blocking a retrieval fix
behind a scoring redesign leaves every anatomy question answered badly meanwhile.

- **A31a** Add a retrieval filter for observational/descriptive designs
  (cross-sectional, morphometric/anatomical, imaging/diagnostic-accuracy). Keep it
  reasonably specific — report what a broad version would admit before choosing.
- **A31b** **Band at the weakest tier initially.** Nothing is promoted, nothing
  currently retrieved is displaced. A25 decides later whether an anatomy question
  should rank these higher; this item only makes them reachable. A12's discipline
  holds: reachability now, ranking later, never in one commit.
- **A31c** Confirm the new tier gets its own budget and cannot consume slots from
  level1 or above. Report papers admitted per tier before and after on the
  apicoectomy fixture.
- **A31d** Done when the regenerated apicoectomy curriculum can cite Jeon 2021 and
  the bony-lid papers. Note the existing protections still apply — invariant 6
  (zero-evidence modules render no numeric protocol) and tier banding mean a
  weakest-tier paper cannot drive a protocol on its own.
- **A31e** Also correct the record: `ENDO_DOMAIN_FILTER` has now been exonerated
  twice (Q7, A23a). Stage 4 should treat the venue-exclusion finding on its own
  merits rather than as an explanation for these gaps.

### A30d — sequencing the eval  *(RB decision)*

**Run one eval after the whole A30a sweep lands, not one per change.** Still open:
`ensure_authoritative` and `fetch_papers`' quality threshold, both of which decide
membership by score. Running now would mean running again. Approved: ~$13 and the
machine time, before the demo — retrieval that has changed twice today should not
be demonstrated unmeasured.

Batching makes attribution harder, so: if more cases move than can be explained
cleanly, bisect by reverting individual membership changes **on the affected cases
only** rather than re-running the full set.

---

## §8c CORPUS DEPTH — six levers  *(strategic; sequence at the end of §8c)*

Origin: three consecutive comparisons where Curo's reasoning beat the competitor
and its coverage lost — anesthesia, retreatment, mandibular apicoectomy. The
common failure is not synthesis, it is what reaches synthesis.

### A24 — Retrieve per module, not per curriculum

Measured on the apicoectomy curriculum: four modules (indications, diagnosis,
technique, outcomes) appear to share one query set, so the anatomy module was
written from a pile assembled for the topic as a whole.

- **A24a** Confirm the mechanism first (this is A23b): does each module generate
  its own search terms, or do all modules share the curriculum's?
- **A24b** If shared: generate terms per module from that module's own subject and
  retrieve separately. The anatomy module should be searching cortical thickness,
  mandibular canal proximity and mental foramen position; the outcomes module
  should be searching success rates and survival.
- **A24c** Cost is retrieval time, not model spend (A1c: `fetch_papers` makes no
  LLM call). Report added wall time per curriculum and hits-per-query per module.
- **A24d** Done when the regenerated apicoectomy curriculum's anatomy module cites
  anatomical papers it does not currently reach (see A23's named list).

### A25 — The tier ladder is a therapy hierarchy applied to every question

The single biggest correctness improvement available, and a design change rather
than a bug fix. Curo bands every paper as though the question were "does this
work?" — trials high, cross-sectional studies low. For a therapy question that is
right. For "how thick is the buccal plate at the second molar?" it is wrong: a
large, well-conducted CBCT morphometry study is the *best available* evidence for
that question, and Curo scores it around 50 and buries it. The same error made the
anesthesia answer apologise for a diagnostic-accuracy study ("flagged: not an RCT")
when that design is exactly correct for a diagnostic question.

Cochrane and GRADE both use question-type-specific hierarchies. Curo uses one.

- **A25a — measure before designing.** Classify the 25 eval questions plus the
  border set by question type: therapy / diagnosis / prognosis / prevalence-anatomy
  / harm. Report the distribution. If therapy dominates overwhelmingly, say so —
  the fix may not be worth its risk.
- **A25b** Propose a per-type ladder in the report and STOP for RB. Do not
  implement in the same item. Sketch: therapy keeps the current ladder;
  prevalence/anatomy puts large well-conducted cross-sectional and morphometric
  studies at the top; diagnosis puts cross-sectional accuracy studies with a
  reference standard at the top; prognosis puts inception cohorts at the top.
- **A25c** Whatever is built, invariant 1 survives in spirit: tier is assigned by
  study design *relative to the question type*, never by score, and score still
  ranks only within a tier. A paper's tier may now differ between two questions —
  that is correct and must be visible in the rendered tier label, not hidden.
- **A25d** This changes stored bands. Dry-run with delta split; back up every
  column; re-baseline the eval deliberately and explain every case that moves.

### A26 — Chase citations backwards from every retrieved systematic review

When Curo retrieves an SR it reads the review and stops. The studies inside it are
where the primary numbers and the classic papers live.

- **A26a** For each retrieved SR, fetch its included/cited primary studies via
  PubMed's linked-citation data. Report how many are already in the library and
  how many are new, on the three failed fixtures (anesthesia, retreatment,
  apicoectomy).
- **A26b** Verify the claim before building: would this have surfaced the
  Reader/OSU anesthesia canon, Karaoğlan and Toia 2022, and Setzer Part 1?
  If not, say so and stop — the item is justified by that specific test.
- **A26c** Ingest with full provenance, dry-run with delta split. Chase one level
  only; do not recurse.
- **A26d** Metric is hits-per-query and the named-paper test in A26b, not raw
  library growth.

### A27 — Read full text where it is legally free

Curo reads abstracts only, which is honest and is also a ceiling. Cortical
thickness gradients, anterior-loop lengths and subgroup numbers live in methods
and results, not abstracts.

- **A27a** Measure the ceiling first: for the three failed fixtures, how many
  cited papers have PMC open-access full text available?
- **A27b** Where available, retrieve and use full text; keep the abstract-only
  disclaimer accurate per paper — the rendered surface must say which papers were
  read in full and which were not (A9's principle: the page must not claim more
  than was done).
- **A27c** This also catches A10's population mismatches: a full text makes
  "wisdom teeth" and "maxillary MB root" unmissable. Re-run the three misattributed
  citations from A10's addendum against full text and report whether they would
  have been caught.
- **A27d** Report added cost and latency per answer. Respect PMC's terms and rate
  limits; open-access subset only.

### A28 — Seed the library deliberately

Growth is currently accidental — the library only grows where someone has already
asked. Take the questions an endodontist actually asks and stock them in advance.

- **A28a** Build a topic list of 30–40 questions: start from
  `eval/COMPARISON_QUESTIONS.md`, the eval set, the border set, and the stored
  history. RB reviews the list before ingestion.
- **A28b** For each, run the retrieval path and ingest what passes provenance
  checks. Dry-run with delta split; report papers added per topic.
- **A28c** Re-run the full eval afterwards and explain any case that moves.
  Growth that degrades precision is not growth.

### A29 — Guidelines and classification frameworks

Most are not in PubMed and need their own ingestion path. This is what makes an
answer read as expert rather than assembled, and it is what an out-of-domain
question should be referred to.

- **A29a** Consume Stage 4's S4 inventory rather than rebuilding it: ESE, AAE,
  SDCEP, ADA, AAOMR, AAOMS. Add the standard classification frameworks a
  specialist expects (e.g. Kim–Kratchman A/B/C for apical surgery case selection).
- **A29b** These are guidelines, not trials: band them per A7's guideline tier, and
  never let a position statement outrank a Cochrane review in any rendered
  ordering.
- **A29c** Where a question is out of Curo's domain, the quarantine block's
  "Consult directly:" line should name the specific document, not the body.

### Sequencing for §8c

A24 and A26 are cheap and are expected to recover most of the observed gap — do
them first, after A5b and A23. A25 is the largest improvement and the largest
risk: measure (A25a), propose, and wait for RB. A27, A28 and A29 are projects, not
fixes, and belong after the demo.

---

### A22 — The quarantine block is the wrong granularity and the wrong frequency

RB, on the apicoectomy curriculum: the boxes are unreadable and there are far too
many of them. He is right, and it is not only cosmetic. Measured from that output:
**~18 quarantine blocks across four modules**, several wrapping a SINGLE step of a
numbered list, and the identical footer *"Consult directly: the specialty
guidelines for this question — Curo has not retrieved or checked them"* repeated
~15 times verbatim. A warning that appears eighteen times is wallpaper — the same
ambient-versus-alarming failure identified for the banner in A3, now visual.

It also breaks the document. Step 3 renders as a bare "3." followed by a block
followed by orphaned text, and Markdown emphasis leaks as literal `**`
("Administer local anaesthesia** Inferior alveolar nerve block…").

- **A22a — never wrap part of a list item.** A numbered or bulleted step is
  atomic. If a step is unsourced, MARK the step; do not wrap it in a block that
  separates it from its number. Test on the apicoectomy fixture: no list item is
  split by a quarantine block, and no literal `**` survives rendering.
- **A22b — two levels, chosen by size.** A substantial unsourced passage (a
  paragraph or more) keeps the full block. A single unsourced sentence or step
  gets an INLINE treatment instead: a thin (2px) amber left rule and a small
  end-of-sentence marker, no header, no footer, no repeated boilerplate.
- **A22c — say it once per module.** One legend at the top of each module
  ("Passages marked ° are general clinical practice, not from the retrieved
  evidence base — Curo has not checked them against any abstract"), and one
  consolidated note at the end listing them. Delete the repeated per-block footer
  entirely.
- **A22d — contrast.** Body text inside any quarantine treatment must be near-black
  on the pale ground (target ≥7:1; the amber is for the rule and the label, never
  for body copy). Verify the rendered contrast ratio in the running app, not in
  the stylesheet. This is a light UI — check that no dark-theme token leaked in.
- **A22e** Re-render the apicoectomy curriculum after the change and report the
  block count before and after. If the count is still above ~5 per module, the
  problem is the generator emitting that much unsourced text, not the renderer —
  say so and hand it to A20/Stage 2 item I rather than shrinking the warning.

### A23 — Apicoectomy retrieval gap  *(new fixture, A5 class)*

Save the curriculum as `eval/fixtures/curriculum_mandibular_apicoectomy.md`. A
competitor answer on the same topic (saved beside it as `..._oe.md`) cites, and
Curo retrieved none of, the following — all core to this exact question:

- **Jeon KJ et al., Clin Oral Investig 2021** — CBCT anatomical analysis of
  mandibular posterior teeth *for endodontic microsurgery*: buccal cortical
  thickness ~1.7 mm at first premolar rising to 6.9–12.3 mm at the second molar
  distal root; apex-to-canal distance shortest at the second molar, <2 mm in
  8–11%. This is the single most on-topic paper for the question asked.
- **Mainkar A, Zhu Q, Safavi K, J Endod 2020** — altered sensation after
  mandibular premolar and molar periapical surgery: ~14% overall, 38% premolar
  vs 8% molar, OR 7.19. Curo cited only von Arx 2021 (12.9% / 22.6%).
- **Setzer FC et al., J Endod 2010 (Part 1)** — traditional vs microsurgery,
  94% vs 59%. Curo retrieved Part 2 only.
- **Bi C et al., J Endod 2022** and **Lee SM et al., J Endod 2020** — the bony
  lid / bone window technique, which exists specifically for thick mandibular
  cortex. Absent entirely.
- Kim–Kratchman A/B/C case classification; targeted EMS with 3D-printed guides;
  MRONJ/antiresorptive considerations; nerve-injury MANAGEMENT (extruded material
  removal, steroids, referral timing).

Meanwhile **55 papers were retrieved and not cited**, including pulpotomy,
wisdom-tooth and radiography-selection reviews. So this is a precision AND recall
failure on the same query.

- **A23a** Determine the mechanism, per A5a's method: gate short-circuit,
  vocabulary miss, cap, or absent from library. Report before fixing.
- **A23b** The curriculum's topic vocabulary ("mandibular", "inferior alveolar
  nerve", "mental foramen", "cortical thickness", "bony lid") should have driven
  retrieval. Check whether module-level topics generate their own search terms or
  whether all four modules share one query set.
- **A23c** Done when a regenerated curriculum cites the anatomical gradient
  papers. Report hits-per-query before and after.

### A10 (addendum) — Right finding, wrong population

Three citations in the apicoectomy curriculum support their claim *as a sentence*
while describing a different operation or a different tooth. Every gate passed.

1. **PMID 25069437** — Coulthard et al., *Surgical techniques for the removal of
   mandibular wisdom teeth* (Cochrane) — cited for **flap design and wound closure
   in apicoectomy** (triangular vs envelope, primary vs secondary closure). Third
   molar extraction evidence transplanted to periapical surgery.
2. **PMID 20478451** — Degerness & Bowles, on the **maxillary** molar mesiobuccal
   root — cited for isthmus anatomy in a **mandibular** apicoectomy protocol
   ("isthmus tissue increases substantially at 3.6 mm from the apex in MB roots").
   Also duplicated in the reference list (entries 2 and 40).
3. **PMID 29990391** — the injectable local anaesthetics Cochrane review — cited
   for what it *does not say*. Citing a paper for an absence is not support.

Extend A10's classifier: alongside background / methods / results / conclusions,
check **population and procedure match**. A claim about procedure X may not be
supported by a paper studying procedure Y, however well the sentence matches.
Flag as `POPULATION_MISMATCH`, reported separately. Measure the flip rate before
enabling, per A10d. Also add a reference-list de-duplication test.

### A17 — Sweep every explanatory surface for method claims  *(new, small, high value)*

A15 found the "WHAT YOU GET" card telling the clinician that papers are ranked by
"citations & impact factor" — the product describing its own method using the one
signal invariant 11 forbids. That is the second instance (the first was IF in the
reference list), and explanatory copy is the surface most likely to be read aloud.

- **A17a** Inventory every surface that *describes* how Curo works rather than
  answering a question: onboarding and empty-state copy, help text, tooltips, the
  About/method panel, `/status`, the export decks and speaker notes, README, and
  any demo script. List each method claim it makes, verbatim.
- **A17b** Check each against §2's invariants and the §9 decisions. Flag anything
  claiming a signal the engine does not use (impact factor, citation counts,
  journal prestige) or promising a check the engine does not perform.
- **A17c** Fix by making the copy true, never by weakening the engine to match it.
- **A17d** Test: no rendered surface asserts a ranking signal outside the tier
  ladder and the documented score components. Mutation-check.

### A18 — Verify the promise line against real latency  *(small)*

A15c's copy ships "about 15 seconds" (Literature), "about 30 seconds" (Case) and
"takes several minutes" (Curriculum) as written in the spec. Those were my
estimates, not measurements. Measured cost is Literature $0.54 / Case $0.12 /
Curriculum median $1.33, max $6.51 — so the ~3x framing holds on medians, but the
TIMES are unverified and a promise line that is wrong is worse than none.

Measure p50 and p90 wall time per mode from the real logs, separating cached from
uncached, and adjust the copy to the measured figure. Prefer an honest range over a
flattering point estimate. Note the cold-start effect A16 found (9.2 s first ask,
1.0 s after) and say whether the quoted figure assumes a warm process.

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
