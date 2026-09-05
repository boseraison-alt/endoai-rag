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

**Threshold: ≤60 level2-or-above per query → build. Measured max: 32.**

Every one of the 29 questions clears it, most of them by an order of magnitude.
**BUILD 4b.**

The design filter is a real gate, not a formality: it removes **87.6%** of the
untyped-recent pool (1,454 → 180). It does so by reading what the authors
wrote, not by scoring anything.
