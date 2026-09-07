# A55 — the library must not answer alone what it does not hold

Suite green at **2861 passed, 52 skipped, 1 xfailed**. Two of the five items
produced findings that outrank what they were asked to build.

---

## Item 1 — the false-coverage table

32 questions (29 eval cases → 28 unique, 3 probes, the A54 question), frozen
terms through the item C cache.

| | |
|---|---|
| routed LIBRARY | **27/32** |
| …with intersection < 10 | **19** (70% of LIBRARY-routed) |
| …missing live papers | **27 — all of them** |
| thin **and** missing live papers | 19/19 |
| **healthy intersection but still missing** | **8** |
| median fraction of the live set the library lacks | **80%** |

The A54 question: per-group `[87, 12, 26]`, weakest 12 — comfortably past
`min_concept_papers = 3` — and an intersection of **6**.

**My sharper prediction held**: the intersection is below 10 on the *majority*
of LIBRARY-routed questions, not merely a third. **My caveat held too, and it
is the more important half**: 8 questions with a healthy intersection are also
missing live papers, so the intersection is not a sufficient condition. It is
not really a necessary one either — see item 2.

### The finding that outranks the item

Every LIBRARY-routed question is missing live papers, and the correlation
between the intersection and how much is missing is **Pearson r = −0.22**.
`laser-root-canal-disinfection` has an intersection of 23 and misses 95% of the
live set; `single-vs-multiple-visit` has an intersection of 2 and misses 44%.

**The library route is systematically incomplete and the intersection barely
predicts it.** A55 asked for a threshold that separates good coverage from bad;
on this evidence no such separation exists, because there is no "good" class.

---

## Item 2 — the intersection gate. Shipped, with the error counts.

`min_intersection_papers = 10`, added to `RELEVANCE_GATE`, computed by
`endo_ai.question_intersection` — matched through the same `_term_in_text` the
per-concept counts use, so the two numbers are commensurable.

**A premise of the item was already shipped.** Item 2 asks to change the gate so
LIBRARY requires *every* concept group to clear `min_concept_papers`. `app.py`
already did exactly that (`weakest_cov >= MIN_CONCEPT_PAPERS`). The gate was not
misreading its weakest concept. The missing count was the intersection, and that
is the whole of what shipped here.

### The threshold, and why it is a trade rather than a discriminator

A55 asked for the value that re-routes every question missing live papers and no
question that is not. **No such value exists** — all 27 are missing papers.
Error counts, with "badly covered" = missing ≥75% of the live set:

| T | re-routed | stays LIBRARY | badly covered but kept | well covered but re-routed |
|---|---|---|---|---|
| 5 | 14 | 13 | 9 | 5 |
| **10** | **19** | **8** | **5** | **6** |
| 15 | 23 | 4 | 3 | 8 |

**Prediction 4 confirmed**: no value achieves zero errors in both directions.

10 ships because the two error classes are **not symmetric**. The change is
one-directional — everything failing the gate goes to the live path, a superset
of what the library would have returned — so a question re-routed unnecessarily
costs money and latency, while a question wrongly kept costs a clinician the
papers that answer them. RB may reasonably prefer 15, which trades 2 more
unnecessary live runs for 2 fewer badly-covered questions kept.

### Cost of re-routing, for RB

| | |
|---|---|
| added model spend per re-routed question | **$0.0062** |
| added latency | **40–75 s** (measured: 73.9 s and 40.6 s on two real questions) |
| questions re-routed at T=10 | 19 of 32 |

**Prediction 5 was wrong on cost**: I predicted $0.02–$0.10, and it is a third
of the bottom of that range. The live path's expense is *latency*, not tokens —
`ask_clinical_question` averages $0.75 and runs on both routes.

### Done-when — and it is now in tension with items 3 and 4

*"the A54 question routes LIVE and F1–F5 reach its pool on 3 of 3 cold-term
runs"*

Measured **immediately after item 2, before items 3 and 4**: routes LIVE on
**3/3**, intersection 9. That half passed.

Measured **after items 3 and 4**: routes **LIBRARY** on 3/3, intersection
**18** — because the better procedure synonyms and the three newly ingested RCTs
mean the library now genuinely holds papers about this question. F1, F2 and F4
reach the pool on **3/3**.

"Routes LIVE" was only ever a proxy for "the pool holds the papers that answer
the question". The proxy and the thing have come apart, and I am reporting that
rather than tuning a threshold until the proxy reads the way the item expected.
**The substantive done-when — the fixtures reach the pool — is met for the three
clinical fixtures that exist in the library.** F3 is present but below the 0.55
similarity floor; F5 was never ingested (see item 3).

---

## Item 3 — F1–F8 ingested through the write-back path

**Delta by tier: `level1` 1368 → 1371 (+3).** Dry run and apply agreed.

| fixture | PMID | pubtype derives | outcome |
|---|---|---|---|
| F1 | 31078325 | `level1` (RCT) | **written**, score 62.6 |
| F2 | 27986096 | `level1` (RCT) | **written**, score 58.1 |
| F3 | 34499889 | — | already present, `level3a` |
| F4 | 38430316 | `level1` (RCT) | **written**, score 67.0 |
| F5 | 42634020 | nothing | **not written** |
| F6 | 42004800 | nothing | **not written** |
| F7 | 41555359 | `level1` (meta-analysis) | **HELD BACK** |
| F8 | 38849637 | nothing | **not written** |

**F7 is held back and the reason is the same defect item D measured hours
earlier.** NLM tags it `Meta-Analysis`, which derives `level1`, but its abstract
says it *"compared the sealing ability and marginal adaptation"* — a
meta-analysis of **bench** outcomes. Writing it would put laboratory evidence at
the top of the human clinical ladder, joining `28068207` and `36862198` which
item D found there already. Reported for RB, not written.

**F5 and F6 are a real recall loss and are reported as one.** Both are genuine
clinical papers — F5 follows 137 teeth to periapical healing, F6 studies 24
patients — and the pubtype writer derives nothing from a bare `Journal Article`.
With no lane to fall back to, they are not ingested. Guessing a tier is the
defect A49 exists to undo, so nothing was guessed.

**Prediction 6 was wrong, and the titles alone overturned it.** I predicted none
would land at `invitro`. F7 and F8 are bench studies by their own abstracts —
*sealing ability*, *ninety root segments with an artificial fin*. **Two of
A54's eight "head-to-head papers" are not clinical evidence at all**, so A54's
recall target was partly the wrong target.

Two process defects in my own harness, both caught before any claim was made:
the first `--apply` run wrote **nothing** while reporting success, because I
passed `score=0.0` into a write-back path with a quality floor of 50 (fixed by
scoring the papers properly, **not** by lowering the floor, which A55 puts out of
scope); and `level_key_source` was written as `pubtype:pubtype:…`, repaired on
the three rows.

---

## Item 4 — procedure synonyms

One sentence in the generator prompt, general in form, with a worked
illustration in the style the prompt already uses for lasers.

**Rule 38, comparing query strings:** **0/32 unchanged**, far below the 90%
threshold, so this is a retrieval change and owes a full A/B.

**The first version of the sentence failed and the measurement caught it.** It
was abstract — "the contemporary or microscope-era name" — and changed all 32
queries while leaving the A54 surgery group at 3/8 synonyms, none of them in the
surgery group. Rewritten to name what a procedure group must contain and to
target six or more names.

| A54 question | synonyms present |
|---|---|
| before | **3/8** — `apicoectomy`, `root-end filling`, `retrograde filling` (all from the material and filling groups) |
| after | **8/8** — including `endodontic microsurgery` and `apical microsurgery` |

**Prediction 8 half-right**: ≥3 after, yes; "fewer than 2 before" was wrong — it
was 3, but none in the surgery group, which is what actually mattered.

### The full A/B, frozen terms both arms

| A54 fixture recall | before | after |
|---|---|---|
| **fixtures satisfying the query** | **3/8** (F3, F5, F6) | **6/8** (F1, F2, F4, F5, F6, F7) |
| in the top 60 only | 1/8 | 0/8 |

Gained exactly **F1, F2, F4, F7** — the four A54 said `"endodontic
microsurgery"` recovers. Lost F3. Pool size 60 → 60, so the recall was not
bought with a larger pool.

**And an instrument error, the second of the same kind in one session.** The
first version of this A/B read recall off the two top-60 lists and reported
**1/8 → 0/8, "REGRESSED"**. Both lists were full; the fixtures had simply moved
in the ranking. That is rule 41 — written earlier the same session, for the
species guard — failing to be applied one item later. Asked per fixture, recall
**doubled**.

Across all 32 questions: mean Jaccard 0.29, 4 pools grew, 7 shrank. Those
numbers sit near the 26% same-build noise floor and are reported as context, not
as a verdict.

---

## Item 5 — the specialty block rendered from data

`endo_ai.render_specialty_block(rows, model_sentences)` emits **every** admitted
guideline, in jurisdiction order, with organisation, title, status and year from
the row. The model contributes only the one sentence per row stating the
position.

A pointer row gets **"position not quoted"** and its URL — and the renderer
**discards a position sentence written for a pointer row**, which is the
hallucination the pointer mechanism exists to prevent.

Rendered on A54's three guidelines:

```
**Specialty Guidelines & Position Statements**

- **ESE** (EU) — Treatment of pulpal and apical disease: the ESE S3-level
  clinical practice guideline. — *current*, 2023
  - Recommends apical surgery where orthograde retreatment is not feasible.
- **FDSRCS** (UK) — Guidelines for Periradicular Surgery — *current*, 2020
  - position not quoted — pointer record; read it at <url>
- **AAE** (US) — AAE Treatment Standards White Paper — *current*, 2018
  - position not summarised in this answer
```

Three jurisdictions, all three present. A54's synthesis showed the model all
three and it listed two; which two is not a decision a model should be making.

---

## Tests

`tests/test_a55_intersection_gate.py` — 19 tests.

- The A54 question's **real** concept counts are the fixture: `[87, 12, 26]`,
  intersection 6. Mutation-checked as the item specifies — restore the
  concepts-only decision and it routes LIBRARY again.
- A structural pin: the intersection can never exceed the weakest group, which
  is what makes the two numbers commensurable.
- The specialty renderer is mutation-checked by dropping a row and watching the
  every-guideline assertion fail.
- Wiring tests for both, because a helper nothing calls is the defect rule 14
  exists for.

---

## For RB

1. **The architecture question A55 surfaces but does not settle.** The library
   holds ~20% of the relevant literature for the median question and the gate
   cannot tell which questions those are (r = −0.22). `min_intersection_papers`
   is a patch on a library-first design; whether that design is right at this
   library size is a bigger decision.
2. **`min_intersection_papers` at 15** instead of 10: 2 fewer badly-covered
   questions kept, 2 more unnecessary live runs.
3. **F7 (`41555359`)** — held back; one line to ingest if RB disagrees.
4. **F5 (`42634020`) and F6 (`42004800`)** — real clinical papers the pubtype
   writer cannot band. They need a manifest entry or a hand-adjudicated tier.
5. **Two of A54's fixtures are bench studies.** The A54 recall target should be
   restated as five clinical fixtures, not eight.
