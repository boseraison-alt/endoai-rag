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
21. **A queue item states a hypothesis and its test, not a conclusion.** Five
    premises have now been overturned by measurement — A5b (papers already in the
    library), A23/A24 (modules already retrieved separately), A32 (the guarantee
    could never fire), A33d (over- not under-specified), and A33d's own follow-up
    (two variables changed at once). Every one was diagnosed from a symptom rather
    than an instrumented mechanism. Write items as "measure X; if X then fix Y",
    and treat any item phrased as a conclusion as unverified until measured.
22. **Change one variable at a time when attributing a recovery.** (Origin: the
    131-pool comparison in A33d altered both the dropped group and the scenario
    vocabulary, and credited the wrong one.)

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
- **A31 STATUS (`pending commit`).** A31a-c are built and verified: the tier
  exists, is fetched, bands last, has its own floor (27, level4's, because a
  therapy-shaped scorer gives descriptive designs min 15.4 / median 33.5 /
  max 46.5), its own depth (100, because the tier query matches 771 papers)
  and its own quota (6/10/6). No existing quota or floor moved.
  **A31d is NOT met and is blocked on A24, not on this item.** With the module
  query as the syllabus currently generates it, PubMed ranks the wanted papers
  at 29 (Bi 2022), 66 (Jeon 2021) and 87 (MB resection level) out of a
  771-paper pool, and the tier's cap keeps the 10 most relevant. The class is
  now reachable; what is missing is a module query specific enough to rank
  them — which is exactly A24b. Inflating this tier's quota to force them in
  would flood the anatomy module with 80 descriptive papers and is not done.

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

### A32 — `ensure_authoritative` never fires  *(RB decision: do NOT let it reach below the floor)*

Measured: `usable()` requires similarity at or above the floor, and the `relevant`
list it is handed already contains every such candidate, so its re-inclusion set is
empty by construction. It has never printed its own log line. Three questions
tested, nothing added on any of them.

**Decision: it must not be "fixed" by reaching below the similarity floor.** On
apicoectomy 183 of 200 candidates sit below the floor; admitting high-tier papers
from there is precisely the error just removed from the cap and the ORDER BY —
letting authority override relevance, wearing a virtuous hat. A Cochrane review
about a different question is still about a different question.

The original intent was real and narrower than the implementation: a top-tier
paper should not be lost to *query variance*. So:

- **A32a** Redefine it as cross-query variance protection **above the floor**: a
  paper that clears the floor on ANY generated query, but is lost in the union
  merge or a cap, is restored. Never reaches below the floor on any query.
- **A32b** If that mechanism cannot be built cleanly, **delete it** and say so in
  the report. A guarantee that cannot fire is worse than no guarantee, because it
  gets described.
- **A32c — A17 dependency, check this first.** Does any rendered or explanatory
  surface claim an authority guarantee (that Cochrane-tier or top Level I papers
  can never be dropped)? If so, that copy has been false for as long as the
  function has been inert — the same defect class as "citations & impact factor".
  Fix the copy in the same commit as the code, and add it to A17's inventory.
- **A32 RESULT: DELETED (A32b), not redefined.** A32a's narrower mechanism has
  nothing left to protect. `multi_query_search` keeps the MAX similarity per
  PMID across every generated query, so one badly-embedding query cannot lose a
  paper another query found — measured on the retreatment question with a
  consistent query set, ZERO of the papers clearing the floor on at least one of
  8 queries failed to reach the merged candidate set, which cuts at 0.558
  against a floor of 0.55. And the caps below it now order by relevance (A5b,
  A30b), so anything they cut is cut because more relevant papers exist in its
  tier; restoring it would be authority overriding relevance.
  The protection that is real lives in two layers that work: the union-of-max,
  and the eval's `must_include_pmid` on 36512807.

- **A32c ANSWER: no clinician-facing surface claimed it.** The claim lived in
  three INTERNAL files — `CURO_HANDOVER.md` ("Cochrane-tier + top Level I
  papers can never be dropped by query variance"), `CHAT_HANDOVER.md`, and
  `HANDOVER.md`'s "three layers now stand between a query and a lost
  authority". All three corrected in the same commit as the deletion. Nothing
  in the templates, decks, speaker notes or README made the claim, so no
  clinician was told it. **For A17's inventory: a handover file is an
  explanatory surface too** — it is what the next agent and the next
  conversation believe, and all three described a guarantee that had never
  fired.

- **Two more vacuous tests found and replaced.** `TestAuthorityGuarantee` in
  `test_retrieval_consistency.py` passed only because every case called the
  function with `relevant=[]`, a state the production path never produces; and
  `test_cochrane_below_the_floor_is_reinstated` used floor=0.50 against a
  similarity of 0.546, so it asserted the opposite of its own name. Replaced
  with tests of the union-of-max, which is the layer that actually protects.

- **A32d** Whatever is built or deleted, keep the test that pins the current
  defect deliberately, so a later change cannot silently reintroduce
  score-over-relevance here.

### A24 before the eval  *(RB decision, confirmed)*

The agent is right and this is exactly what A30d exists to prevent. **Do A24
first**, then ONE eval covering all four membership changes plus A31 and A24.
Running now would mean running twice.

A31d is correctly left unmet rather than forced. Note for the record: inflating
the new tier's quota to push Jeon through would have put ~80 descriptive papers
into an anatomy module — declining to do that is the right call, and A31d closes
via A24b (a module query specific enough to rank the wanted papers), not via
quota.

### Evidence for A25, recorded now

A31's calibration produced a number worth keeping: papers in the new
observational/descriptive tier score min 15.4 / median 33.5 / **max 46.5**,
because a therapy-shaped scorer gives a descriptive study no credit for a
comparison it never made. Level5's floor of 38 would have cut 34 of 50 of them,
including the paper the tier exists for.

That is A25's argument as a measurement rather than an assertion: the scorer, not
only the tier ladder, is shaped for therapy questions. Carry it into A25a.

---

### A33 — CORRECTION (2026-09-03): the premise was wrong, in the opposite direction

The agent measured before fixing and **A33d is disproved**. The query is not
under-specified; it is **over**-specified. The ceramic-crown AND-group collapses
the pool from 131 to 26 and removes the two most on-topic papers:

| query | pool | de Araújo 2021 | Aust Dent J orifice barriers |
|---|---|---|---|
| as generated (3 AND-groups incl. ceramic) | **26** | – | – |
| drop the ceramic group | 131 | rank 12 | rank 11 |
| scenario only, no material | 1261 | – | rank 41 |

Every tier returned 0–1 hits, so **the taxonomy was never the binding constraint
here** — A33a would not have surfaced Trautmann, because the query returns almost
nothing before any tier filter applies. `36661351` (Aust Dent J 2023, orifice
barriers) is already in the library at level1/65.9 and this query cannot reach it.

**This is a new failure mode and it belongs in HANDOVER: a query so specific that
it excludes the evidence that answers it.** Every previous retrieval finding was
about what happens to candidates *after* they are found. This one is upstream of
all of it, and it is the opposite of A24's diagnosis — which makes it the fourth
premise of mine that measurement has overturned, and worth saying plainly in the
report rather than quietly correcting.

- **A33h MEASURED, RULE REPORTED, NOT IMPLEMENTED (2026-09-03).** Reporting
  before implementing, as instructed — and the measurement overturned my own
  A33d conclusion as well as the original premise.

  **CORRECTION TO MY OWN REPORT.** I said the ceramic AND-group "collapses the
  pool 131 -> 26 and removes the two most on-topic papers", implying that
  dropping it recovers them. It does not. That measurement silently compared
  two different things: the 131-pool query was one I had hand-written with
  `"orifice barrier"` and `"intraorifice barrier"` added to the scenario group.
  The recovery came from the added VOCABULARY, not from dropping the group.
  Measured properly, with the domain filter and one variable at a time:

  ```
  3 groups, original vocab                    pool  14   recovered 0/4
  3 groups, ENRICHED scenario vocab           pool  29   recovered 0/4
  2 groups (drop ceramic), original vocab     pool  62   recovered 0/4
  2 groups (drop ceramic), ENRICHED vocab     pool 143   recovered 2/4
                                                     de Araujo @11, orifice barriers @12
  ```

  **Relaxation alone does not fix this fixture. Neither does vocabulary alone.
  Both are required.** A33g as written is necessary and insufficient.

  **Candidate relaxation signals, all measured on 4 real queries:**

  ```
  OR-arity (what _broaden_query uses today)   picks the best drop 1 of 4
  standalone PubMed frequency                 wrong: the ceramic group alone
                                              matches 6,811 records yet is the
                                              binding constraint in combination
  biggest pool gain if dropped                picks the SCENARIO group on the
                                              GIC query (318 vs 62) — which is
                                              the group that makes the question
                                              what it is. Dropping it returns
                                              generic GIC-in-endodontics, i.e.
                                              exactly the paediatric pool the
                                              old answer drowned in. REJECT.
  ```

  None of the cheap signals is correct. **Proposed rule: drop trailing groups
  first** — the generator writes subject, then scenario, then substrate, so the
  LAST group is the qualifier. On the GIC query that picks the ceramic group,
  which is right. **Evidence is n=1 and I am not implementing on that**; it
  needs validating against the apicoectomy, retreatment and laser queries
  before it becomes a rule.

  **Separate, certain finding: `BROADEN_THRESHOLD = 5` is far too low.** The GIC
  query returned 14-29 hits and never triggered broadening at all. Whatever
  order is chosen, the trigger has to fire before the order matters.

- **A33g** Fix at query construction: AND-groups must be **relaxable**. When a
  query returns below a threshold pool, drop the most restrictive group and retry
  before falling back to broader vocabulary. Report the pool size at each step;
  log every dropped group (rule 5).
- **A33h** Decide the relaxation ORDER by measurement, not intuition: which group
  is dropped first, and on what signal (fewest matching records? most specific
  substrate?). Report the rule before implementing it.
- **A33i** A33a (surveys in the observational tier) stands on its own merits but is
  **no longer justified by this fixture**. Say so, and justify it — or drop it —
  on the apicoectomy evidence alone.
- **A33c stands**: the 2026 Cochrane review `42444634` is absent from the library.
  Ingest with full provenance, dry-run first.
- **A33e** still needs the Curo answer; RB is pasting the fixtures.

### A33h — DECISIONS (RB, 2026-09-03)

**1. Validate before adopting. n=1 is not enough for a rule that runs on every
query** — and it is esearch-only, so it costs nothing but minutes. Validate
"trailing groups first" against the apicoectomy, retreatment and laser queries.

**2. But prefer a third option: stop inferring the qualifier from position.**
"Trailing groups first" works only because the generator happens to write
subject → scenario → substrate. That is a property of a *prompt*, not a guarantee;
if the generator ever reorders, the rule silently inverts and drops the scenario —
the exact outcome the measurement rejected. So:

- **A33h-i** Have the term generator **label each AND-group** with its role:
  `subject`, `scenario`, `qualifier`. Relaxation then drops the declared
  `qualifier` first, `scenario` never, `subject` never. Position becomes a
  fallback for un-labelled legacy queries, not the mechanism.
- **A33h-ii** Validate the labelling on the same four queries: does the generator
  label them the way a clinician would? Report the labels it produces before
  wiring relaxation to them.
- **A33h-iii** If labelling proves unreliable, fall back to validated
  trailing-group order and say so — but measure first.

**3. A33g's scope was too narrow, and the measurement says so.** Relaxation alone
recovers 0 of 4; enriched vocabulary alone recovers 0 of 4; **both together
recover 2 of 4.** A33g must therefore cover query *construction* as well as
relaxation — the scenario group needs its own synonym expansion (the way tier
queries already get OR-expanded), not just the option to drop a group. Report
recovery for each half and for both, on all four queries.

### A33j — `BROADEN_THRESHOLD` is the wrong shape, not just the wrong number

Certain finding: the GIC query returned 14–29 hits and never triggered broadening,
because the threshold is 5. But 5 is a *did-the-query-fail-entirely* check, not a
*is-this-enough-to-answer-from* check.

**Set it from what an answer needs, not from failure detection.** A35 targets ~20
cited references; after tier filters, similarity floors and per-tier caps, a pool
of 14 cannot produce that. Derive the threshold from the pipeline: measure, across
the 29 eval questions, the ratio of initial pool size to finally-cited papers, and
set the trigger so that a query whose pool cannot plausibly yield ~20 citable
papers broadens before it is answered from.

Report the distribution and the derived number together. **A33j and A35 must be
decided with each other's numbers in hand** — a reference target without a pool
big enough to meet it produces padding, which A35d forbids.

### A35 — Use the evidence you retrieved  *(RB, 2026-09-03)*

RB's observation: when there is no Level I evidence, Curo appears not to fall back
to Levels III–V — it declares a gap instead. The GIC/ceramic answer is the proof:
**45 papers retrieved, 2 cited**, both Level I and both paediatric, with "no
retrieved studies at these levels directly addressed…" written under Levels II–V.

RB wants a literature answer to carry **at least ~20 references**, and lower-tier
evidence to be used rather than discarded.

**Build the goal, not the number.** A hard minimum is a target that can be hit by
padding — citing papers that support nothing, to reach a count. That would make
answers worse while looking better, and it is the same shape as tuning a detector
to shrink a warning. So:

- **A35a — measure first.** Across the stored answers and the three failed
  fixtures, report retrieved-vs-cited by tier. How many retrieved papers were
  never cited, and what tier were they? That number, not the reference count, is
  the defect.
- **A35b — find the mechanism.** Determine why lower tiers are not used when the
  top tier is thin. Candidates: the synthesis prompt instructs leading with the
  highest available tier and treats lower tiers as supporting only; per-tier
  quotas leave few lower-tier papers in context; the tier-banding language pushes
  the model to declare a gap rather than descend. Report which, with the prompt
  text, before changing anything.
- **A35c — synthesis must descend.** When the top tier is absent or off-topic, the
  answer is built from the best tier that IS on topic, labelled as such. "No Level
  I evidence exists for this" is a statement about the literature and must follow
  A5c's rule; "the strongest evidence here is Level III" is a statement about what
  was found, and is what most answers should say.
- **A35d — the reference floor is a WARNING, not a quota.** Target ~20. If fewer
  papers genuinely support something, cite fewer and **say why on the page** —
  e.g. "12 of 45 retrieved papers were on topic; the rest addressed different
  populations or procedures." Never cite a paper that supports no claim in order
  to reach a number. Test both branches: a rich question reaches ~20+; a genuinely
  sparse one cites fewer and states the reason.
- **A35e** Report cost and latency impact — more cited papers means more synthesis
  context, and the library route already carries ~120 papers where it carried ~38.

### A36 — Question type determines the answer's shape  *(RB, 2026-09-03)*

RB: a **material** question should concentrate on the material's properties, its
use-case scenarios, and its advantages and disadvantages. A **clinical** question
should hone in on the clinical decision.

This is A25 arriving from the product side. RB has independently reached the same
conclusion the retrieval work reached: the *kind* of question changes what a good
answer looks like — and, per A25, what counts as the best evidence for it.

- **A36a** Classify the question at the start of the Literature path: material /
  technique, clinical decision, diagnosis, prognosis, or anatomy. Log the
  classification and show it in the answer's provenance so a wrong call is visible.
- **A36b** Give each class its own answer skeleton in the synthesis prompt. For a
  material question: properties, indications and use-case, advantages,
  disadvantages, and what it should NOT be used for. For a clinical question: the
  decision, what changes it, and what the evidence does not settle.
- **A36c** Feed the classification to A25a's measurement — this is the same axis,
  approached from the answer side rather than the ranking side, and the two must
  not end up with different taxonomies.
- **A36d** Test on the GIC fixture (material) and the retreatment fixture
  (clinical): each renders its own skeleton, and neither renders the other's.

### A37 — Literature may ask, but only to resolve genuine ambiguity  *(revises A20)*

RB, 2026-09-03: *"In literature, we don't have to ask a question every single time.
If the question is very clear, but if the question is not clear, then there need to
be follow-up questions… we need to know exactly what the question is about."*

This partially reverses A20, which removed all questions from the Literature path.
The gate is now the same one Case and Curriculum use — **ask only when the answer
would otherwise be built on a guess** — and its specific job here is to resolve
what A36 classifies: is this a material question or a clinical one?

- **A37a** Restore a clarifying gate on `review`, with the operative test written
  into the prompt: *"would a material-focused answer and a clinical-focused answer
  to this question be substantially different documents?"* If no, do not ask.
- **A37b** One round only, and always skippable — the existing
  "Skip — search now / Search with my answers" control stays.
- **A37c** **A20's test must be updated, not deleted.** It currently pins "review
  never asks". Replace with both branches: a clear question ("glass ionomer as
  access restoration through a ceramic crown" — material, unambiguous) goes
  straight to the answer; an ambiguous one asks exactly one narrowing question.
  Mutation-check both directions; this is the pair where a one-way test passes
  while the gate is stuck open or shut.
- **A37d — COPY.** The promise line under the Literature composer says *"no
  follow-up questions, just the answer"*, and the What You Get card carries the
  same claim. Both become false the moment this ships. Fix the copy in the SAME
  commit as the code, and add both to A17's inventory. Third time this week that
  copy has outlived the behaviour it described.

### A34 — Journal balance in the library  *(RB, 2026-09-03: measure before deciding)*

RB has asked again for a slight preference toward *Journal of Endodontics*. The
2026-09-02 decision was no-preference (invariant 11, pinned by test C1, and the
approved UI card says papers are graded "never by journal, citation count or
impact factor"). Rather than reopen that, **measure whether the perceived IEJ skew
is a ranking problem or a library problem.**

- **A34a** Report the journal distribution of the library: counts by journal
  overall and by tier, with JOE, IEJ, *Aust Endod J*, *Clin Oral Investig* and
  *J Dent* called out. Then the same distribution across the retrieved sets of the
  29 eval questions and the three failed fixtures.
- **A34b** State plainly whether JOE is under-represented **relative to what
  PubMed would return for the same queries**. That comparison is the whole point:
  a library skew is a stocking problem with an additive fix (A28), whereas a
  retrieval skew with a balanced library would be the only thing a ranking change
  could address.
- **A34c** If under-represented in the library: propose a targeted JOE ingestion
  (A26's backward citation chasing will also help, since JOE primary trials sit
  inside the reviews Curo already retrieves). **No scoring change, no invariant
  change** — this gets more JOE on the page without any journal signal entering
  the engine.
- **A34d** If the library is balanced and retrieval is not, report that too, with
  numbers, and stop for RB. Only then is a mechanism question worth reopening —
  and the options are a retrieval-stage guarantee (scores untouched, invariant 11
  survives) or a within-tier tie-breaker (invariant 11 repealed, C1 deleted, and
  the "never by journal" card rewritten before any demo). Do not implement either
  without an explicit decision.

### A33 — Materials/bench questions: A25's third and strongest instance  *(new fixture)*

Question asked: *"glass ionomer as permanent access restoration for access opening
through a ceramic crown after endodontic treatment."* Curo retrieved 45 papers and
cited **2**, both paediatric — an EAPD review of restorative materials in primary
teeth and a primary-molar pulpotomy RCT. Its own text: *"all Level I evidence
returned concerns restorative materials in primary dentition."*

A competitor answered it well from eleven sources, of which **not one is a
randomised trial**: an in vitro microleakage meta-analysis, three further in vitro
studies (crown retention after access, fracture strength after access simulation,
luting-cement microleakage), a **practitioner survey** (Trautmann 2001,
*Quintessence Int*), two narrative reviews on GIC in endodontics, and a 2026
Cochrane review on direct coronal restoration of permanent posterior teeth.

**This is the point.** No one will randomise a patient's ceramic crown, so the best
available evidence for this question *is* bench and survey evidence. Curo bands
in vitro second-from-bottom and (per A31) has no tier for surveys or descriptive
work at all. The literature that answers the question is either at the bottom of
the ladder or outside it, so the quotas filled with the only therapy-shaped papers
matching "glass ionomer restoration" — which live in paediatric dentistry.

Save both answers as `eval/fixtures/gic_access_ceramic_{curo,oe}.md`.

- **A33 STATUS, measured 2026-09-03 after A5b/A30b/A31/A7 landed: THE SYMPTOM NO
  LONGER REPRODUCES, and A33d's premise is the reverse of what was measured.**

  Regenerated on current code, same question, 37 papers, $1.31, 93 s. It now
  cites four papers, none paediatric, and declares no gap:

  ```
  27542693  level1   60.4  The effect of endodontic access on ALL-CERAMIC CROWNS: a systematic review
  35221127  level1   81.1  Clinical efficacy of resin-based direct posterior restorations and glass ionomer
  36661351  level1   65.9  ORIFICE BARRIERS to prevent coronal microleakage after root canal treatment
  40369057  level3a  55.4  Clinical and radiographic outcome of a bioceramic sealer
  ```

  The old answer's two paediatric citations are not in the pool at all any
  more. `36661351` — squarely on topic, and in the library the whole time — was
  being evicted by the score-weighted ORDER BY and cap that A30b and A5b fixed;
  the A7 banding removed the position statements that were holding its slot.
  The A20c assumption line and the quarantine/reframe both survive intact.

- **A33d — the premise is BACKWARDS. The query was OVER-specified, not
  under-specified.** It did carry the scenario. Measured on the term the
  generator produced:

  ```
  as generated, 3 AND-groups incl. ceramic     pool   26   neither named paper
  drop the ceramic group                       pool  131   de Araujo @12, orifice barriers @11
  scenario only, no material                   pool 1261   orifice barriers @41
  ```

  The ceramic-crown group collapses the pool from 131 to 26 and removes the two
  most on-topic papers. Every tier query returned 0-1 hits — **the taxonomy was
  never the binding constraint here, the topic query was.** Note the term
  generator also logged `capped to 3 AND-groups, dropped: ("ceramic crown" OR
  "porcelain crown" OR crown)` on the regenerated run, i.e. it dropped the
  over-specifying group itself and that is when the good papers arrived.

- **A33b answered.** de Araujo 2021 (PMID 35097115) is simply **absent from the
  library**, and no tier query reaches it because of the over-specification
  above, not because of its banding. It is an SR *of* in vitro studies; PubMed
  types it as a systematic review, so it would band `level1` on ingestion, which
  overstates it — worth raising with A25 rather than fixing by hand here.

- **A33c answered.** The 2026 Cochrane overview is **PMID 42444634**, absent
  from the library. Ordinary ingestion gap, not a taxonomy or ranking one.

- **A33a — still worth doing, but for a different reason than stated.** Adding
  surveys would NOT have surfaced Trautmann (PMIDs 11203998 / 11203999, and the
  year is 2000 not 2001): no query reaches it at any pool size tested, and a
  2000 Quintessence Int paper is thinly indexed. The taxonomy gap is real and
  A31-shaped, but it is not what caused this fixture's failure.

- **A33a** Extend A31's taxonomy: add **surveys and practice-consensus studies** to
  the observational/descriptive tier's retrieval filter. Trautmann 2001 is
  currently unreachable by any tier query, exactly as Jeon 2021 was.
- **A33b** Report why the in vitro tier did not surface the microleakage
  meta-analysis (de Araújo 2021, *Biomed Res Int*) — quota, floor, depth, or never
  retrieved. Note it is an SR **of** in vitro studies, so its own banding may be
  ambiguous; say which tier it lands in and whether that is right.
- **A33c** The missed 2026 Cochrane review on direct coronal restoration of
  permanent posterior teeth is a **separate, ordinary defect** — highest recognised
  tier, squarely on topic. Determine whether it is absent from the library or
  unreached by the live query, and fix accordingly.
- **A33d** Query vocabulary (A24 on the Literature path): the generated terms
  chased the *material* and lost the *scenario*. Report whether any query contained
  access cavity / coronal seal / intraorifice barrier / ceramic repair / silane. A
  question with a material AND a substrate AND a clinical scenario needs all three
  in the query set.
- **A33e** Precision: 45 retrieved, 2 citable. Report the retrieved-but-uncited
  distribution by tier for this fixture — a pool that is 96% unusable is a
  measurement worth having beside the recall numbers.
- **A33f — carry into A25a.** This is now the third documented instance of the
  therapy-hierarchy mismatch (anaesthesia diagnostic accuracy; apicoectomy anatomy;
  this). Unlike the first two it is not a topic but a **question class** —
  materials and technique — and a large share of restorative questions fall in it.
  A25a's classification must count how many eval and border questions are
  materials/bench questions, not only therapy/diagnosis/prognosis/anatomy.

**Note what worked:** the quarantine block contained substantially the correct
clinical answer (composite over a GIC base, HF etch + silane, GIC as intraorifice
barrier not occlusal surface) and was labelled unverified rather than dressed up.
Same shape as the apixaban answer — sound reasoning, failed retrieval, honest about
which was which. Do not "fix" this by making the model quieter.

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
- **A22f — "From the wider literature" overclaims, and contradicts its own
  header.** The quarantine block opens with "General clinical knowledge. No paper
  in this library was retrieved for it", then later says "From the wider literature
  (which this search did not return)". The second phrasing asserts the content IS
  in the published literature and merely went unretrieved — a claim about the
  literature that Curo cannot support. Some of it will be well-supported; some is
  convention that never was.
  Replace with wording that says only what is known, e.g. *"Not from any paper Curo
  checked — general clinical practice, from the model's own knowledge rather than
  from a source."* One framing per block, not two. Same class as A17: copy
  claiming more than the engine did. Test that no rendered surface asserts the
  existence of supporting literature for unsourced content.

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
