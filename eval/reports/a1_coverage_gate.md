# A1 — the coverage gate must test question coverage

## What was measured, before changing anything

The library-first gate asked four questions and every one of them is about the
**corpus**, not the **question**: enough hits, enough above the similarity floor,
at least one high tier, not stale. All four are satisfiable by the endodontic
*half* of a two-part question.

On "eliquis in patients who needs apicectomy" all four passed and live PubMed was
never attempted. **Zero of the retrieved papers mention anticoagulation.**

## The condition (A1a)

`generate_search_terms` emits a PubMed boolean whose top-level AND-groups are the
question's concepts:

```
(apicectomy OR apicoectomy OR "periapical surgery")   <- the procedure
AND (apixaban OR Eliquis OR DOAC* OR "direct oral anticoagulant*")
AND (anticoagul* OR "bleeding risk" OR hemorrhage)
```

Each group is a hard requirement in the query the system would otherwise have
sent to PubMed. So requiring each to be **represented** in the candidate set is
not a new judgement about the question — it is the query's own structure applied
to what came back. Groups made only of corpus-wide vocabulary
(`"root canal" OR endodontic*`) are dropped: they are the tautology the old gate
was built on.

Measured on the real 200-candidate pools:

```
apixaban      apicectomy / apicoectomy / periapical surgery      6
              apixaban / Eliquis / DOAC*                         0   <-- NOT COVERED
retreatment   single visit / one visit / single appointment      9
              retreatment* / re-treatment                       19
```

## A1c — the cost consequence, measured before applying

**Model spend: $0.00 per answer.** `fetch_papers` makes no LLM call — verified in
source. Both routes make the same synthesis call. Routing live adds NCBI traffic
and time, not tokens.

**Latency**, from 9,369 real esearch calls in `pubmed_audit.jsonl` across 155
live runs:

```
per-esearch latency (ms)   min 383  p25 751  median 967  p75 1,349  p95 1,905  max 15,020
esearch calls per run      min 1    p25 7    median 8    p75 40     max 904
esearch phase wall (s)     min 16   p25 66   median 77   p75 171    max 3,719
```

This is a **lower bound**: efetch (metadata and abstracts) is not in the audit
log, and a live run does that too.

**Flip count**, replaying the condition over the 29 eval cases plus both
fixtures. 29 of 31 are routed to the library by the current gate:

| `min_concept_papers` | flips to live | % of library-routed |
|---|---|---|
| 1 | 2 | 7% |
| 2 | 3 | 10% |
| **3 (chosen)** | **3** | **10%** |
| 5 | 10 | 34% |
| 8 | 14 | 48% |
| 12 | 17 | 59% |

Distribution of the weakest concept's coverage, over the same 31 questions
(candidates above the similarity floor):

```
  0      ### 3
  1-2    ## 2
  3-5    ######### 9
  6-10   #### 4
  11-20  ###### 6
  >20    ####### 7
                    min 0  p25 3  median 6  p75 20  max 51
```

**Why 3, from the shape and not from a cost target.** The distribution has its
mode at 3–5 and its p25 at exactly 3. Between 3 and 5 the flip count triples
(3 → 10). 3 is the largest threshold that sits below the mode, so it separates
"a concept the library genuinely does not hold" from "a concept it holds thinly".
Any value 1–3 gives the same behaviour on this set; 3 is the most conservative of
those.

**Projected added cost per answer:** 10% of library-routed questions go live,
each adding a median 77 s (p25 66 s, p75 171 s) and **$0.00** of model spend.
Amortised over all answers that is roughly **+8 s mean latency, no added spend**.

## Are the flips true positives?

All three, checked individually:

| question | weakest concept | hits |
|---|---|---|
| FIXTURE-apixaban | apixaban / Eliquis / DOAC* | **0** |
| retreatment-vs-microsurgery | nonsurgical / conventional / orthograde retreatment | **0** |
| dens-evaginatus-prevention-followup | dens evaginatus | **1** |

No false positives at this threshold on this set. The second is the same
vocabulary-miss class as A5a's Schwendicke paper: the library holds the topic
under different words.

**FIXTURE-retreatment does not flip** — both its concepts are covered (9 and 19).
That is the honest prediction recorded in
[`a5a_missed_rcts.md`](a5a_missed_rcts.md): **A1 does not fix the retreatment
question**, because its defect is a per-tier cap discarding the on-point RCT
*after* retrieval. A5b's completion criterion needs the cap fix and an ingestion,
not this.

## A1b — the gate now says what it decided

```
[rag_gate] hits=200>=20 PASS | relevant=30>=12 PASS | high_tier=True PASS |
           newest=2026 age=0y<=3 PASS | concepts>=3 FAIL
  [rag_gate:coverage]    6 paper(s) mention ['apicectomy', 'apicoectomy', …]
  [rag_gate:coverage]    0 paper(s) mention ['apixaban', 'eliquis', 'doac*', …]   <-- NOT COVERED
[rag_gate] -> LIVE PUBMED
```

A gate that short-circuits live retrieval discards the entire live candidate pool.
Doing it silently was standing rule §1.5 — the same defect class as the module
cap, the stitcher budget, the domain filter and A5a's per-tier cap.

## A defect the test suite caught, and what it cost

The first wiring routed **every degraded run** to live PubMed. When term
generation fails, `generate_search_terms` falls back to the raw question —
`"Single visit versus multiple visit endodontic treatment?"` — which parses as
one group holding one 60-character string no title contains. Coverage scored 0
and the condition failed.

Ten `tests/test_end_to_end.py` tests went red, which is how it was found. That is
exactly the cost A1c exists to bound, and it would have been paid in latency on
every run whose term generation slipped.

Fixed by abstaining: a query with fewer than two AND-groups has no concept
decomposition to read, and a "synonym" longer than six words is prose that leaked
through the parser.

## Tests

33 new (`tests/test_coverage_gate.py`). Suite 1,814 → **1,844**.

**9/9 mutants killed**, two only after the tests that let them survive were
fixed:

* **M1 — the coverage condition deleted from the real gate expression: SURVIVED.**
  Every test asserted on the coverage *functions* and on a local restatement of
  the decision; nothing read the conjunction `app.py` actually evaluates. This is
  A4's "tests assert on the wrong surface" defect, in the item written to answer
  A4. Now `TestTheConditionIsActuallyWiredIntoTheGate` reads the real expression,
  and a companion test asserts the other four conditions are still conjuncts, so
  adding one cannot quietly remove another.
* **M3 — a degraded query failing instead of abstaining: SURVIVED**, masked by
  the six-word prose filter, which catches the long fallback for a different
  reason. Short fallbacks (`"Apixaban and apicectomy"`, `"dens evaginatus"`) now
  exercise the rule directly.

## Open for RB

The threshold is 3 and the numbers above are what chose it. If +8 s mean latency
is unacceptable, that is a cost decision, not a gate decision — say so and I will
report what a lower threshold gives up rather than tuning it quietly.
