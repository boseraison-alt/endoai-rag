# Item 1 — design extraction: the measurement that decides 4b

Replay:
`python scripts/measure_untyped_recent.py --json eval/reports/a49_untyped_recent_4a.json`
`python scripts/measure_design_all29.py --json eval/reports/a49_design_all29.json`
`python scripts/measure_design_extraction.py`  (the 1c control)

---

## 0. TWO WITHDRAWALS FIRST

### 4a's median of 426 is withdrawn. The real figure is 26.

The script that produced it was wrong in two ways at once:

1. It called `generate_search_terms(q)`, which returns the **single primary
   PubMed query as a STRING**, then sliced it `terms[:4]` — taking the first
   **four characters**. The queries issued were `("(") AND "last 18 months"[dp]`,
   `("l") AND …`. The list of topic groups comes from
   `generate_multi_search_terms(question, primary_term)`, a different function.
2. It omitted `ENDO_DOMAIN_FILTER`, which production ANDs into every query.

So it measured "recent papers anywhere in PubMed matching a single character".
The pool contained celery genomics, vanadium-oxide catalysis, *Fusarium*
fungal genetics and Chinese health policy in Africa. The `retmax=200` cap hid
it by holding every total near 600.

**Found by reading the abstracts the extractor could not classify** rather than
by trusting the count. That is the only reason it was found at all. Eighth
instrument error recorded in this project; the first of them mine.

Corrected, with production's own query shape:

```
  min 0 | p25 3 | MEDIAN 26 | p75 48 | max 307 | total 1,454
  [0,0,0,1,1,2,2,3,11,13,13,16,17,21,26,26,32,33,38,42,44,48,
   112,114,121,132,138,141,307]
```

The blind spot is **real but roughly 16× smaller** than reported. The median
now sits *under* the 40 that item 4a used as its affordability line.

### The guideline-lane volume figure (200–396/query) is withdrawn too

`scripts/measure_guideline_lane.py` had the identical `terms[:4]` defect.
**Item 5's conclusion is unaffected** — it rested on EFCD-ESE-ORCA being
unreachable, which was measured through explicit filter strings against
PubMed's own admission, not through that script.

---

## 1c. The negative control overturned its own premise

The batch specified: *"run the extractor on Sulaiman 42388091's abstract. If it
does not find the RCT design there, the extractor is broken."*

**Sulaiman is not an RCT.** Its abstract says:

> "This single centre, one-arm clinical trial was registered in the Clinical
> Trials Registry-India (CTRI/2023/06/054485)."

The strings `randomis`, `randomiz` and `randomly` **do not occur in it**. It is
a one-arm prospective clinical trial of 135 molars with 12-month follow-up.

Returning "RCT" for it would be inventing a design the authors never claimed —
the one thing 1b forbids. So the control asserts what the instruction was
reaching for: that the extractor reads the paper's **real stated design**, and
that the design **admits** it.

```
  extracted design : clinical trial (non-randomised) or prospective study
  rung             : level2
  matched phrase   : 'one-arm clinical trial'
  level2-or-above  : True        -> CONTROL PASSES
```

Sulaiman is still admitted, for the reason its authors actually gave.

---

## The adversarial audit, and what it caught

Ten independent judges audited the first extractor over 74 admitted records
and all 482 records of one question. It had a **~34% false-admission rate** and
a **~24% miss rate**. Every claim was then re-verified against the live PubMed
record before being acted on — one claim was **refuted** that way (40618152 was
already correctly vetoed as bench work) and was not "fixed".

### The finding that mattered, and it is pure domain knowledge

> **`RCT` in endodontics means ROOT CANAL TREATMENT.**

Not "randomised controlled trial". The pattern list matched `\bRCT\b` → level1,
and that single token promoted to Level I:

| PMID | what it actually is |
|---|---|
| 40509940 | *"…tooth survival: A retrospective cohort study"* |
| 39880187 | retrospective diagnostic cohort |
| 40213509 | a single case report |
| 40729775 | cross-sectional questionnaire of 90 dentists |

The token is gone. Spelled out, "randomised controlled trial" is unambiguous
and costs nothing.

### The other five confirmed false-admission modes

| mode | worked example |
|---|---|
| structured **commentary** — *Evidence-Based Dentistry* pieces whose "DESIGN: systematic review" describes **somebody else's** paper | 40258974, 41593409 |
| **protocol** not recognised — *"Systematic Review Protocol on…"*, no results | 40787614 |
| **economic model** — a Markov cost-effectiveness model drawing inputs from other people's reviews, admitted as one | 41188638 |
| **registration label** — `CLINICAL TRIAL NUMBER: Not applicable` read as evidence of a trial | 41249970 |
| **microbiological bench** — 48 teeth "randomly divided", inoculated with *E. faecalis*, never says "in vitro" | 40893990 |

### The miss that mattered, which is the same bug mirrored

Genuine randomised trials returned `unclear` because they failed a
human-subject word check — **dental trials count teeth, not always patients**
(40397221, 41941071, 42145341). A paper that *calls itself* a randomised
controlled trial is now self-evidencing; the human check is kept only for the
weaker "randomly divided" wording, which is where bench confusion actually
lives. Clinical-outcome markers (postoperative pain, VAS) were added too.

One further false veto: `extracted teeth` had demoted 42034624, a five-year
cohort study of **the reasons for tooth extraction**, to bench work. It now
requires a laboratory co-marker.

### After the fix, on the same records

**11 of 11 false positives rejected. 8 of 9 misses recovered.** The ninth
(41063117) self-describes as retrospective and is genuinely ambiguous; tuning
to a single case is how a detector stops generalising.

---

## 1d. The threshold test

One draw, all 29 questions, run over **4a's own stored PMID lists** so the
design count and the distribution come from the same sample. (The three-question
pass had used a different draw of the stochastic term generator —
`case-opening-sparse` returned 482 untyped papers there and 138 in the 4a run,
and comparing across draws would have been comparing two samples and calling
the difference a finding.)

```
  LEVEL2-OR-ABOVE PER QUERY
  min 0 | p25 0 | MEDIAN 4 | p75 7 | max 32 | total 180

  [0,0,0,0,0,0,0,0,0,1,1,3,3,3,4,4,5,5,5,6,7,7,10,11,12,17,20,24,32]
```

Rung totals across all 1,454 untyped-recent papers:

| rung | n | % |
|---|---|---|
| invitro | 693 | 47.7 |
| (none stated) | 229 | 15.7 |
| level1 | 119 | 8.2 |
| level3a | 116 | 8.0 |
| level4 | 107 | 7.4 |
| **level2** | **61** | **4.2** |
| animal | 44 | 3.0 |
| unclear | 36 | 2.5 |
| observational | 31 | 2.1 |
| level5 | 12 | 0.8 |
| protocol | 5 | 0.3 |

Nearly half of recent untyped endodontic literature is bench work, which is
what a heavily in-vitro specialty should look like and is a sanity check on the
extractor in its own right.

### VERDICT

**Threshold: ≤60 level2-or-above per query → build. Measured max: 30.**

Every one of the 29 questions clears it, most of them by an order of magnitude.
**BUILD 4b.**

The design filter is a real gate, not a formality: it removes **88.7%** of the
untyped-recent pool (1,454 → 164). It does so by reading what the authors
wrote, not by scoring anything.

---

## ROUND TWO — the fixed extractor was re-audited, and it was not finished

The obvious mistake after round one would have been to stop. The fixed
extractor was put back in front of independent judges over **all 133 admitted
papers**, and the verdict was blunt: *"Do not treat this fix as finished."*

**False-admission rate: 34% → 15%** (20 of 133). Roughly halved, on a
denominator 1.8× larger.

**The RCT mode is verifiably dead.** At least 15 abstracts in the after-set
still use `RCT` in the root-canal-treatment sense, and **not one** produced a
level1 verdict. Every surviving level1 traced to explicit random allocation of
humans.

But three things survived, and one of them was **introduced by the round-one
fix**:

| what | how it showed |
|---|---|
| **bench work, still admitted** — markers keyed to vocabulary these papers do not use | *"52 extracted mandibular molar distal roots"*, *"Sixty-four curved mesial root canals"*; four of five named micro-CT, SEM or a goniometer, and none said "in vitro" |
| **`comparative` had become the new `RCT`** — 11 of 20 survivors | admitted a wettability bench test, a micro-CT sealing study, a study of **19 alpacas**, and a bake-off between YOLOv8 and Faster R-CNN on 1,498 radiographs |
| **self-evidencing RCT removed the location check** — *my own fix* | 42641947, a **four-patient case series**, admitted at level1 on *"Further investigation through randomized controlled trials … are warranted"* |
| registration strings, half-fixed | *"(Clinical Trial: NCT06676358)"* overrode the abstract's own opening words, *"This cross-sectional study"* |
| no species check at all | two animal studies (alpacas, horses) entered a **human** clinical evidence pool |
| a design word losing to a timing word | *"This multicenter, CROSS-SECTIONAL prospective study"* admitted at level2 on "prospective" |

### What changed in response

- **Sentence scoping.** Design claims are now matched only against sentences
  describing the paper's *own* work. A phrase inside *"further trials are
  warranted"*, *"future studies should include…"*, *"the original trials from
  which the data were derived"* or *"there were more systematic reviews after
  2017"* is a statement about somebody else's study. This is the fix for the
  defect round one introduced, and it is scoped by **sentence** rather than by
  another keyword precisely because keywords were what broke it.
- **Instruments and measurands as the bench signal.** No clinical trial reports
  a contact angle, a push-out bond strength or a goniometer reading.
- **`comparative` requires a human anchor**, behind the bench and animal vetoes.
- **`retrospective` beats `comparative`** — a retrospective comparative study is
  level3a that compared things, not level2 that happened to be retrospective.
- **Species check**, including alpaca, equine, ovine, camelid.
- **Scientometric/bibliometric surveys and model bake-offs** join the
  economic-model veto: all three consume other people's evidence rather than
  producing it.

### And a false veto the fix itself caused, caught the same way

`sealing ability` was added as a bench marker and immediately vetoed 41169767 —
whose title ends *"An in vivo study"* and whose abstract reads *"In this
prospective randomized trial, 52 patients with deep caries"*. Ambiguous
measurands (`sealing ability`, `fracture resistance`, `surface roughness`,
`marginal adaptation`) now count only alongside a specimen marker. That paper
is back at level1, and correctly labelled randomised rather than
non-randomised.

### Where it stands

Of the 19 records named across both audits, **16 are now correctly rejected**.
The three still admitted (40510995, 42656893, 42523855) are human comparative
studies the judges themselves called borderline or arguable — tuning to those
is how a detector stops generalising.

Round-two effect on the distribution:

```
                     round one    round two
  in vitro             47.7%        54.2%     better bench detection
  (none stated)        15.7%        11.8%
  unclear               2.5%         0.5%
  level2-or-above max     32           30
```

**The build/stop decision was never in doubt and is not now.** The judges make
the point themselves: false positives can only push the count *down*, never up,
so no plausible error rate crosses a threshold of 60 from a measured max of 30.
The direction that *could* have mattered is false negatives — genuine trials
being dropped.

---

## ROUND THREE — the false-negative rate, which is the direction that mattered

A stratified sample of **192 of the 858 rejected papers** was judged, covering
every bucket a paper can be turned away into (in vitro 105, none-stated 26,
level3a 17, level4 12, observational 9, animal 8, level5 6, unclear 6,
protocol 2, level3b 1).

```
  raw                    9 false negatives / 192 judged = 4.7%
  stratified estimate   ~42 genuine level2 papers turned away, of 858
                        (band roughly 21-79)
  recall                ~77%  -- the lane finds about three in four
```

**Zero level1 papers were missed anywhere in the sample.** No RCT, systematic
review or meta-analysis was dropped. Every one of the nine misses is level2.

**Where they concentrate, and it is not a veto over-firing.** Eight of nine sit
in `(none stated)` — abstracts where *no pattern fired at all* — and one in
`observational`. Every other bucket was clean: in vitro 0/105, retrospective
0/17, animal 0/8, and the commentary veto correctly rejected all three of the
hardest traps, papers quoting somebody else's RCT or systematic review
verbatim.

The systematic weakness is real and structural: **the extractor matches design
LABELS, never design DESCRIPTIONS.** All eight misses return nothing matched
while describing enrolment, arms, delivered treatment and scheduled follow-up
in plain prose — e.g. 39932469, 143 teeth in three material arms with 6- and
12-month follow-up.

**The obvious fix was tested and rejected — by the auditor, on the code.** The
proposal "read the title as design evidence" is a **no-op**: the title is
already in the haystack (`extract_stated_design` builds it as
`title + "\n" + abstract`). A probe of the real alternative — adding bare
clinical-study phrases plus trial-registration identifiers — recovers only 3
of the 8 known misses and sweeps in 5 others, one of which a judge confirmed
is a *correct* rejection. The remaining five carry no design label anywhere and
would need enrolment + intervention + follow-up inference, which a phrase
matcher cannot do at any vocabulary size. **Not built**, and this is the reason.

**Two instrument limits the audit surfaced, both now addressed or recorded:**

- `PROVISIONAL_FETCH_DEPTH` was 200 against a measured maximum of 307
  untyped-recent candidates, so ~107 candidates on that question were never
  shown to the extractor — misses outside every recall measurement because
  nothing ever judged them. **Raised to 400.**
- `PROVISIONAL_MAX_ADMITTED` is 40, which sits **below** item 1's affordability
  threshold of 60. The threshold test itself is unaffected —
  `measure_design_all29.py` applies no cap and its max was 30 — but the lane
  can never admit more than 40 however good recall becomes. Recorded in the
  constant's comment so "max 30 against a threshold of 60" is never read as
  headroom the lane would use.

**Bottom line:** the lane under-delivers by about 1.4 papers per question, a
1.26× volume gap. Real, bounded, and it changes no decision — recovering all of
it leaves the top question at ~38 against a threshold of 60.
