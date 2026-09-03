# A33e — what the uncited 97% actually is, and the mechanism that made it

Measured 2026-09-03 on the GIC-through-a-ceramic-crown fixture, library route,
against the PMIDs the regenerated answer cited (`eval/logs/a33_regenerated.md`).

---

## 1. The distribution A33e asked for

87 papers reached synthesis. The answer cited 4 (3 are in today's pool; the
fourth, `40369057`, has since fallen out).

| tier | n | cited | uncited | best sim | median | worst |
|---|---|---|---|---|---|---|
| cochrane | 2 | 0 | 2 | 0.623 | 0.613 | 0.604 |
| level1 | 25 | 3 | 22 | 0.729 | 0.601 | 0.568 |
| classic | 3 | 0 | 3 | 0.689 | 0.565 | 0.552 |
| level2 | 10 | 0 | 10 | 0.613 | 0.564 | 0.554 |
| level3a | 11 | 0 | 11 | 0.652 | 0.568 | 0.554 |
| level3 | 9 | 0 | 9 | 0.607 | 0.566 | 0.553 |
| level4 | 10 | 0 | 10 | 0.591 | 0.564 | 0.554 |
| invitro | 11 | 0 | 11 | 0.610 | 0.565 | 0.551 |
| guideline | 1 | 0 | 1 | 0.567 | 0.567 | 0.567 |
| level5 | 5 | 0 | 5 | 0.588 | 0.569 | 0.553 |
| **TOTAL** | **87** | **3** | **84** | | | **97% unused** |

**Every citation came from level1.** Nine tiers supplied 62 papers and none of
them was used.

## 2. The uncited pool is not off-topic — but similarity is not relevance

32 of the 84 uncited papers are **more similar** to the question than the
least-similar paper the answer did cite (0.583).

The twelve most similar of them:

```
0.729  level1    Eight-year study on conventional glass ionomer and amalgam
0.689  classic   Light-cured glass ionomer cement as a retrograde root seal
0.679  level1    Two-year evaluation of class II resin-modified glass ionomer
0.653  level1    A split-mouth RCT of single crowns retained ...
0.652  level3a   Post and core restoration of endodontically treated teeth
0.651  level1    Success of an alternative for interim management of irrev. pulpitis
0.645  level1    Effectiveness of three minimal intervention approaches
0.634  level1    The effect of an intraorifice barrier and base under coronal rest.
0.630  level1    Stainless steel crown versus modified open-sandwich restoration
0.629  level1    A prospective, randomized, comparative clinical study of resin ...
0.623  cochrane  Single crowns versus conventional fillings for the restoration ...
0.614  level1    A randomized controlled clinical trial of the performance of ...
```

Read them: **most are on-vocabulary and off-question.** Class II restorations,
paediatric stainless-steel crowns, retrograde root seals, interim pulpitis
management — GIC and restoration words, a different clinical question. Perhaps
two are genuinely on-point (the intraorifice barrier and base paper at 0.634,
and arguably the eight-year GIC longevity study at 0.729).

**This is a caveat that lands on A35k's own numbers.** A35k counts 1,525
"inverted" papers — cut while less similar papers were admitted — and that count
is defined by cosine similarity. This fixture shows what a similarity inversion
often is: a paper about the same *words* rather than the same *question*. The
inversion is real as a rule-19 category error; it is weaker than it looks as an
argument that better evidence was turned away.

## 3. The mechanism that surfaced while measuring this

Ingesting one paper for A33c made this line appear:

```
[PRISMA dedup] flagged 30 primary studies as already synthesised
in newer SR (PMID 42444634, 2026; cutoff ≤ 2024)
```

`flag_superseded_by_review` takes the newest SR/MA **year** anywhere in
cochrane+level1, subtracts a 2-year buffer, and flags **every** level2 / 3a / 3b
/ 3 / 4 paper at or below that year. It then writes this into the synthesis
prompt:

> PRISMA DEDUP NOTICE: N primary studies in this evidence base are likely already
> synthesised inside the newer systematic review/meta-analysis PMID X (year). To
> avoid double-counting evidence, defer to the SR's pooled estimate when
> discussing those findings, and only cite the primary study independently if you
> need a methodological detail…

**There is no topic test anywhere in it.** The SR is chosen by year alone.

### How often it fires

Measured across the 29 eval questions on the same candidate sets as A35k:

**1,294 of 3,301 retrieved papers — 39% of everything retrieved — arrive at the
synthesis labelled "likely already synthesised, defer to the SR".**

Per question: median 39%, min 24%, max 53%. It fires on all 29.

### What it asserts on the worst question

`bisphosphonate-extraction-vs-rct-treatment`: **70 of 133 papers (53%)** are
told to defer to PMID 42512863 (2026) — *"Regenerative Potential of Biodentine
in Complex Endodontic Cases"*.

A sample of what that review is said to have already synthesised:

```
sim 0.714  level3a  2022  Periapical status in patients affected by osteoporosis
sim 0.698  level2   2022  Changes in size of periapical lesions after RCT
sim 0.695  level2   2021  RCT of compromised teeth as alternative to extraction
sim 0.681  level3a  2022  Radiographic predictors for MRONJ in oncologic patients
sim 0.680  level3b  2024  Endodontic and periapical status in osteoporosis
```

A Biodentine regeneration review did not synthesise the MRONJ radiographic
predictor literature. The claim is false, it is made in the prompt as fact, and
it is attached to an instruction to stand the paper down.

### Why this matters to A35

A35k concluded that supply is not the constraint and the question is a synthesis
judgement. This is a **synthesis-side mechanism, running on every answer, that
suppresses 39% of the pool on a year comparison.** It is the strongest candidate
yet for why Curo cites ~9–11 of ~114.

**Stated as a hypothesis, not a finding (rule 21).** The correlation is not
clean: A35a measured level3a cited at 46% and level3b at 54% — both are primary
tiers and both are heavily flagged — while level4, also flagged, is cited at 4%.
What is *established* here is that the system makes an unverifiable claim about
1,294 papers per eval sweep. Whether it changes citation behaviour needs its own
measurement, and that measurement is cheap: one answer generated with the notice
suppressed, against one with it.

### Not changed here

The mechanism is a product-behaviour decision, not a bug with an obvious correct
form. PRISMA dedup addresses something real — double-counting a trial and the
review that pooled it — and the fix is not obviously "delete it" (A32) nor
obviously "add a topic test", because whether an SR included a given paper is
not something the system can know from PubMed metadata.

Three options, none implemented:

1. **Choose the superseding SR by relevance, not by year.** The current choice
   is a rule-19-shaped error one more level up — an authority decision made by a
   proxy that does not know what was asked. Cheap, strictly better, does not fix
   the inclusion claim.
2. **Stop asserting inclusion.** Say a more recent review on the topic exists and
   to prefer its pooled estimate *where it pools the same outcome*, without
   naming N papers as already synthesised.
3. **Delete it**, with the measurement written where the function was, as A32
   did for `ensure_authoritative`.

**For RB.** Recommendation: (1) and (2) together — they are small, they remove a
false claim, and neither requires knowing an SR's inclusion list.
