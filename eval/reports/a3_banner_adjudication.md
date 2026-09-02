# A3 — banner counts: re-measure, adjudicate, sharpen, make actionable

## A3a — re-measure on the corrected detector (A12's prerequisite)

The quarantine header/footer over-count is gone: **0 furniture flags across 141
documents**. But its corpus effect was smaller than A12 assumed, because only
**2 of 141** stored documents carry a quarantine block at all — the over-count
was real (12 of 24 flags on the regenerated curriculum) and confined to
documents produced after Stage 1.

```
                docs   with >=1   median   mean    max
  Review         115        89         2    3.2     16      <- corrected detector
  DL              26        26         9    9.7     17
  Stage 1 said   113        88         2      —     16  (Review)
                  22        22         8      —     16  (DL)
```

So the medians were essentially unchanged by that correction alone. The
sharpening below is what moves them.

## A3a — the 40-claim adjudication

25 DL + 15 Review, drawn with seed 20260902 from the pre-sharpening pool
(252 DL / 370 Review flagged claims), frozen so the detector can be scored
against it.

```
  TRUE DIRECTIVE UNCITED   25   62.5%
  NARRATIVE                12   30.0%
  CITED ELSEWHERE           3    7.5%

  DL      n=25   TRUE 17 (68%)   NARRATIVE  7 (28%)   CITED ELSEWHERE 1
  Review  n=15   TRUE  8 (53%)   NARRATIVE  5 (33%)   CITED ELSEWHERE 2
```

**The over-reach is not spread evenly, and that is the whole finding:**

```
  deontic     n=13   TRUE  4   NARRATIVE  9   (69%)
  quantity    n=21   TRUE 15   NARRATIVE  3   (14%)
  imperative  n=6    TRUE  6   NARRATIVE  0   ( 0%)
```

An imperative verb opening a sentence is always an instruction. The narrative
claims are two recognisable shapes, both *about* the evidence rather than
instructing:

* the modal governs an **interpretation** — "should not be interpreted as
  mandating a switch", "clinicians must therefore distinguish", "should be
  framed as a considered alternative", "larger RCTs are required before";
* the sentence **describes the evidence base** — "Both sources converge…",
  "the key evidence gap", "≥8 systematic reviews… remarkably concordant".

A note on the `CITED ELSEWHERE` count. 31 of 40 claims had a citation in an
adjacent claim unit, but **adjacency is not attribution**: in a numbered
protocol, step 5 carrying a marker says nothing about step 6. Only 3 were real
segmenter splits, all of them merged pseudo-heading units.

## A3b — both branches applied

A3b's rule gives two outcomes and the split triggers both.

**Mostly TRUE (62.5%) → the defect is in generation, not display.** The banner
stays. Stage 2 item I is where the count falls from.

**Substantial NARRATIVE (30%) → sharpen the directive test.** Done, as accuracy
rather than leniency:

```
                        precision   recall of TRUE directives
  before                    62.5%                     100%
  after                     89.3%                     100%
```

**Zero true directives lost.** That is the standing-rule-§1.6 test, and it is
what makes this sharpening and not a lowered bar. It took three attempts:

1. The first cut vetoed any sentence mentioning the evidence, and **lost four
   real directives** — sentences that name the gap and then instruct: *"The
   evidence base does not specify a tolerance value … apply standard clinical
   practice (±0.5 mm of the radiographic apex)."* Fixed by applying the veto
   only when the sentence contains no clinical action verb.
2. The second cut put "evidence base" and "the literature" in the
   evidence-*description* veto — but those are the **unsourced-label**
   vocabulary, and Q1's design is that a labelled directive is still counted.
   It vetoed *"From the wider literature, not from the retrieved evidence base:
   the drug should not be routinely interrupted"*, which is a drug directive
   with a label on it. Caught by `test_the_unsourced_label_does_not_exempt_a_
   claim_here` — a Q1 test written for exactly that confusion.
3. The third holds.

Corpus after sharpening:

```
                docs   with >=1   median   mean    max
  Review         115        83         1    2.7     15
  DL              26        26         8    8.6     15
```

Review's median falls 2 → 1; DL's stays at 8, which is consistent with A3b's
reading that the DL count is a **generation** problem, not a display one.

### The fixture count moved 6 → 5, and why

One claim on the apixaban fixture drops:

> "Two included trials compared surgical root-end resection with non-surgical
> retreatment and found no clear superiority for periapical healing at 1 year
> (RR 1.15, 95% CI 0.97–1.35)…"

It fired on `quantity` because of "at 1 year". It is an uncited claim —
`_detect_unattributed_claims` still flags it, and should — but it is not a
directive, and Q1a's remit is directives. The Stage 1 report already called it
"the one finding of a different character" in that set. Recorded in the test
file as `UNCITED_ON_THE_FIXTURE = 5` rather than silently re-baselined (§1.13).

## A3c — the count now points at the text

The status block already quotes the flagged claims verbatim as `> - "…"` lines,
so the renderer has the list without a new server field. Each is located in the
rendered answer and wrapped in a `<mark class="uncited-claim">`, and the
banner's second half is a control that scrolls to the first.

Verified live, on the cached apixaban answer:

```
⚠ CHECKED AGAINST ABSTRACTS: 9/9 CONSISTENT · 4 CLAIMS NOT FROM THE EVIDENCE BASE

marked in the answer:
  "From the wider literature (which this search did not return, …"
  "Standard practice is to either (a) proceed without interrupt…"
  "INR testing is not applicable."
  "Perioperative apixaban management for apicectomy should be g…"

none of the marked claims carries a citation.
```

## A defect found in the running app, not by a test

Asking the apixaban question through the restarted server returned it **from
cache**, and the banner read

```
✓ CHECKED AGAINST ABSTRACTS: 9/9 CONSISTENT
```

— a clean tick, over the four uncited directives whose quarantine block had
just rendered above it. `finalise_answer_text` runs on the cache-hit path and
strips impact factors and quarantines out-of-domain prose, but **every answer
in the cache carries a support block written before Q1 existed**, and nothing
re-ran the checker.

That is the exact defect Q1 exists to fix, surviving on the one path that never
regenerates the answer. `ensure_uncited_half` now adds the second number to a
pre-Q1 block, after quarantining so it counts the block's own contents.

Ordering is load-bearing and is pinned: the half quotes the flagged claims
verbatim, and those quotes carry the "from the wider literature" vocabulary the
quarantiner looks for — so counting first lets the quarantiner wrap the status
block itself, rendering the trust banner nested inside the unverified block it
is reporting on (`> > ✓ **Citation support: verified.**`). A mutation that
swapped the order produced exactly that.

## Tests

`tests/test_uncited_directives.py` 27 → **54**. Suite 1,860 → **1,887**.

Mutation results, 19 mutants across the three pieces:

| set | killed |
|---|---|
| sharpening (S1–S5) | **5/5** |
| A3c marking (C1–C5) | **5/5** |
| cached banner (K1–K5) | **4/5** |

Three survived first and were fixed by strengthening the test, not the code:

* **C5** — a probe matching any word still produced marks, and every assertion
  passed. Now the test asserts the mark lands on the claim it is counting, and
  that no *cited* claim is ever marked.
* **K2** — running the count before quarantining. Killed by the nesting
  assertion above.
* **S-series** anchors had to be rewritten after the conjunction was
  reformatted onto three lines.

**K5 is an equivalent mutant** and is recorded as such: removing the
`if not found: return answer` guard changes nothing, because
`_append_support_warnings` already renders an empty half for a count of zero
and the caller returns unchanged on an empty half. The guard is kept for
legibility.

## Open for RB

**The DL median did not move, and that is the finding.** Review fell 2 → 1;
Deep Learning stayed at 8 with 26 of 26 curricula flagging. A3b's rule says a
mostly-TRUE split means the defect is in generation — so the DL banner will keep
showing 8 until Stage 2 item I changes what the modules write. The banner is now
honest and actionable; it is not yet quiet, and it should not be made quiet by
touching the detector.
