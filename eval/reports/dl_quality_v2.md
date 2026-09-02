# `dl-quality-v2` — Stage 2 report

Fixtures: `eval/fixtures/curricula/anesthesia_20260901_before.txt` (pre-fix) and
`eval/fixtures/curricula/anesthesia_after.txt` (regenerated on the fixed
pipeline, this stage). Kept side by side, not replaced.

*Naming note:* the queue's M1 names the post-fix file
`eval/fixtures/anesthesia_curriculum_postfix.md`. It is written as
`eval/fixtures/curricula/anesthesia_after.txt` instead — the path and extension
`scripts/regenerate_curriculum.py` already uses for the laser fixture. One
convention, one file; duplicating it under a second name would give the stage
two documents that could drift.

---

## M1 — regenerated before auditing

```
                    before     after
  modules                4         4
  words              5,583    12,745
  truncated modules      1         0
  stitcher placeholders  2         0
  unchecked claims      13         0
  parameter conflicts    2         0
  malformed BECAUSE      0         0
  cited PMIDs           39        30
```

**$2.1239, 773 s.** Four modules written in parallel (255 s wall against 998 s
serial equivalent, 3.91×). Two of the four modules failed evidence-mapping on
their first attempt and passed on retry; the log shows the quarantine pass
firing live on the DL path for the first time (3 spans across the run).

**A bound on what M2 can conclude.** Only **9** of the cited PMIDs are shared
between the two documents — 30 dropped, 21 new. Retrieval regenerates its own
search terms and the library has had write-back since, so the two documents rest
on substantially different evidence bases. Any per-claim before/after comparison
is comparing two evidence bases, not two renderings of one. Where a defect has
disappeared below, I say whether it disappeared because it was *fixed*, because
the *content* went, or because the *paper* went.

---

## M2 — F–J re-observed on the post-fix document

| item | verdict |
|---|---|
| F — bibliography = citations | **CHANGED** — near set-equal; 1 uncited entry left |
| "N further cited claim(s) NOT checked" footers | **RESOLVED** |
| n=19,223 subgroup misattribution | **RESOLVED**, and correctly |
| 3.88 mm foramen directive (H) | **RESOLVED** — the claim is absent |
| plain-lidocaine hypertensive directive (I) | **CHANGED** — now cited, and the citation is the finding |
| IANB volume contradiction (J) | **CHANGED** — conflict gone because the content went |
| onset wait across modules (J) | **STILL PRESENT** |
| lip-numbness interval across modules (J) | **CHANGED** — conflict gone because the specifics went |
| endpoint discipline on success rates (G) | **STILL PRESENT** |

### F — bibliography vs citation set

```
                            before    after
  in-text cited PMIDs           39       30
  listed in REFERENCES           0       31
  listed but NOT cited           0        1     <- 28864219
  cited but NOT listed          39        0
```

`before` shows **0 listed** because the document was truncated before its
REFERENCES section ever rendered — which is itself the truncation defect, and
the reason the original F measurement could not have been made on that document.

The named offenders are gone: Sjögren 1990 (PMID 2084204) appears nowhere in the
post-fix document, and there are no AAE position-statement lines in REFERENCES.

**One residual**: PMID 28864219 is listed and never cited. That is the F
invariant, at a scale of 1 rather than 20.

Note these are two different surfaces. Stage 1 Q5 fixed the **browser
bibliography panel**, which was built from `job.papers` — that fix covers this
curriculum too and is already tested against it. The list measured here is the
**REFERENCES section the model writes into the answer**, which is a separate
artefact with the same invariant. M3 adds the assertion for it.

### The "N further cited claim(s) were NOT checked" footers

```
  before   3 footers, 13 unchecked claims
  after    0 footers,  0 unchecked claims
```

**RESOLVED** — by the removal of the 30-pair support cap in `dl-quality-v1`, not
by this stage. Every cited claim in the document was checked. Carried-forward
item "remove the 30-claim support cap if still present": it is not present.

### The Cochrane n=19,223 subgroup misattribution — RESOLVED, and correctly

Before, the whole-review n was attached to a subgroup result:

> "The Cochrane review (123 RCTs, n = 19,223) independently reported that 4%
> articaine … may be superior … (31% vs. 49% success; RR 1.60, 95% CI 1.10–2.32)"

After:

> "…a systematic review and meta-analysis of 123 RCTs (n=19,223), with an
> industry conflict declared by Dentsply (evidence scores reduced accordingly) —
> reported that 4% articaine … may be superior … (31% success with 2% lidocaine
> vs. 49% with 4% articaine; RR 1.60, 95% CI 1.10–2.32; **4 parallel studies, 203
> participants**; low-quality evidence)"

The subgroup's own n and study count are now stated beside the review's, and the
COI is declared. This is not a truncation artifact resolving — it is the model
having room to state both numbers. No test asserting the old defect (M3's rule);
the invariant it belongs to is G's, below.

### H — the 3.88 mm foramen directive — RESOLVED (absent)

Before: 5 mentions, including a directive step —

> "Use the preoperative periapical or panoramic radiograph to estimate foramen
> height: **target approximately 3.88 mm above the occlusal plane**…"

After: **0 mentions**, and no other `mean … mm` sentence anywhere.

It is gone because the paper is gone, not because a gate stopped it. Per M3 I do
**not** write a test asserting this defect — but the underlying invariant (a
population mean must not be rendered as a per-patient measurement when its cited
dispersion spans a clinically different action) has no gate at all, and the
before-fixture is a real document that violates it. M3 builds the gate on that.

### I — the plain-lidocaine hypertensive directive — the finding of this stage

**It is now cited.** 15 of the 16 claim units naming both hypertension and the
agent carry a marker; the 16th is a REFERENCES line. The citation is
**PMID 40705444** — Kothari et al., *Eur Endod J* 2025, a registered
double-blinded RCT, n=198 (99 hypertensive).

So the item's "uncited → extend the gate" branch does not apply. Its "cited but
unsupported → a `verify_citation_support` miss" branch does not apply either, and
that is the interesting part. I fetched the abstract. It says, verbatim:

> "For the hypertensive group, blood pressure was recorded, and inferior alveolar
> nerve block (IANB) comprising **1.8ml of 2% lignocaine without adrenaline** was
> administered."

The curriculum's sentence is in the abstract. `verify_citation_support` passes it,
and it is right to.

**But that sentence is the trial's METHOD, not its finding.** The trial compared
three *supplemental intraligamentary* agents; its conclusion is that diclofenac
sodium and ketorolac tromethamine beat lignocaine for supplemental ILI. Plain
lignocaine for the primary block was the study's **fixed experimental setup for
the hypertensive arm** — a design choice, not a result. The paper offers no
evidence that plain lignocaine is the correct primary block for a hypertensive
patient; it never tested that question.

The curriculum renders it as a recommendation:

> "For hypertensive patients: 1.8 mL of 2% lignocaine *without* adrenaline for
> the primary IANB [[PMID:40705444]]."

**This is a third branch the item did not anticipate: cited, verbatim-supported,
and wrong in force.** A method detail became a clinical instruction. Every
existing gate passes it, because every existing gate asks "does the abstract say
this?" and none asks "is this what the paper found?".

This bears directly on **§10 item 7** — "verify against full text… plain
lidocaine being the wrong hypertensive choice". The provenance question now has a
definite answer: the recommendation traces to a trial's control-arm setup. RB's
clinical verification is still needed; the citation cannot settle it either way.

### J — cross-module protocol consistency

**Onset wait — STILL PRESENT.** Four modules, three different values:

```
  before   M1: 20 min       M2: 10 min, 2-3 min   M3: 15 min
  after    M1: 3-5 min      M2: 10-15 min         M3: 20 min    M4: 20 min
```

A clinician reading modules 1 and 3 is told to wait 3–5 minutes and 20 minutes for
the same step. This is the item's target and it survived the regeneration.

**IANB volume — CHANGED, and not by reconciliation.** The before-document carried
the flat contradiction the item names:

* Module 1: "3.6 mL … produced significantly higher success than 1.8 mL (RR 1.94,
  95% CI 1.07–3.52)"
* Module 2: "Silva et al. (2019) found **no significant difference** in pulpal
  anesthesia between 1.8 mL and 3.6 mL"

The after-document states **neither side**. Modules 3 and 4 prescribe 1.8 mL
consistently, with 3.6 mL articaine buccal infiltration offered as a different
technique rather than a volume comparison. The contradiction is gone because the
conflicting content is gone — and with it the genuine literature conflict, which
item J says the curriculum **must** state and cite both sides of, once.

**Lip-numbness interval — CHANGED, same shape.** Before: 15–20 min (M1, M2) and
5 min (M3), plus "wait 15 minutes" (M3). After: one module says "Confirm lip
numbness before proceeding" with **no interval at all**, and one carries a
quarantined statement. The disagreement disappeared with the specifics.

**Supplemental-injection order** is consistent across all four modules after
(IO → ILI → intrapulpal), and was before.

So J's verdict is not "resolved". It is: **one conflict survives (onset wait), and
two disappeared because the curriculum stopped saying anything specific.** A
consistency detector that only looks for contradictions would score this document
better than the truncated one while it says less. M3's test asserts the presence
of a single reconciled statement, not merely the absence of two conflicting ones.

### G — endpoint discipline on success rates — STILL PRESENT

```
                              before    after
  %-claims                       113      174
  success %-claims                28       44
  ...naming their endpoint         2        9
  ...as a proportion              7%      20%
```

Improved threefold and still leaves **35 of 44** success percentages with no
endpoint. The document juxtaposes rates measured against different endpoints as
if comparable — e.g. "48% success for ILI" beside "92.1% success using a four-site
ILI technique" beside "IANB success from 40.8% to 59%", where the underlying
trials define success as lip numbness, EPT non-response and pain-free access
respectively.

---

## A regression this stage found in Stage 1's work

The regenerated curriculum is the first document produced *after* Stage 1, and
measuring it exposed a defect Stage 1 introduced.

`_detect_uncited_directive_claims` was reading the raw answer, so it counted the
quarantine block's own **furniture** — the header, the note, the "Consult
directly:" footer — as uncited clinical claims:

```
  total flagged in the regenerated curriculum   24
  ...that were quarantine furniture             12   (50%)
  after the fix                                 15   ( 0%)
```

Curo writes those lines to *label* unverified content. Counting them as unverified
content is circular, and it doubled the number on the one surface whose purpose is
to be believed. It was invisible in Stage 1 because no stored answer had a block
yet — **0 of 197** flags across the 22 stored curricula are furniture. Every
document generated from now on would have carried it.

`_quarantine_content_only` reduces a block to the prose inside it: the content is
still counted (Q2b), the furniture is not, and the block is separated from its
neighbours so a claim unit can no longer fuse the footer onto the numbered step
after it — real flags read `...checked against an abstract._ > > 4. **Deliver
primary...`.

4/4 mutants killed. One survived first: the test looked for a leftover `>`
character rather than for the fusion itself, so a mutant that stripped the
prefixes but dropped the blank lines passed it. It now asserts on an inline block
built from the module's own constants.

This also matters for **A3**: it removes a 50% over-count from the DL banner
numbers before the adjudication sample is drawn.

---

## Cost so far

```
  M1 regeneration            $2.1239   773 s
  M2 measurement             $0        (offline; one cached-abstract read)
  Stage 1 (for comparison)   $0.0025
```

Tests 1,810 → **1,813**.

---

## Carried into M3

Still present, so fixable:

1. **G** — endpoint discipline (35 of 44 success rates).
2. **J onset wait** — three values across four modules.
3. **F residual** — one uncited entry in the model-written REFERENCES list.
4. **H** — no gate exists for the invariant, even though this document no longer
   violates it; built on the before-fixture, which does.
5. **I** — a new gate class: a claim that quotes a trial's *method* as a
   recommendation. This is the one that needs design thought rather than a
   pattern, and I flag it for RB below.

Resolved, so no test asserting the defect: the unchecked-claim footers, the
n=19,223 misattribution, the 3.88 mm directive as written.

## Open questions for RB

**1. Item I is a gate class Curo does not have.** "Cited, verbatim-supported, wrong
in force" passes every check in the product. Detecting it in general means asking
whether a sentence quotes a paper's *method* or its *finding* — that is a real
piece of work, not a regex, and it belongs in its own batch rather than bolted
onto this one. Say whether you want it scoped.

**2. The J conflicts that vanished.** Two of the three named conflicts disappeared
because the curriculum stopped making the specific claims. That is not obviously
an improvement: the IANB-volume literature genuinely conflicts and the curriculum
now says nothing about it. Item J's own rule is that it must say so and cite both
sides once. Should M3's test require the reconciled statement to be *present*
(which will fail this document), or only that contradictions are absent?
I have assumed **present**, per the item's wording — tell me if that is too strong
for the demo timeline.

**3. §10 item 7 is now partly answered.** The plain-lidocaine hypertensive
recommendation traces to a trial's control-arm setup, not to any finding about
primary blocks. Your full-text verification is still the deciding step.
