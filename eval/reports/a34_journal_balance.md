# A34 — journal balance: measured, and the perceived skew is real but inverted

Measured 2026-09-03. Library 3,036 rows; retrieval across the 29 eval questions
(3,301 paper-slots); PubMed across the same 29 questions (494 results).

**A34b's answer, plainly: JOE is NOT under-represented. It is retrieved at 16.2%
against PubMed's own 15.4% for the same questions. What is over-retrieved is
IEJ, at roughly twice its share of both the library and PubMed — and it happens
inside almost every tier, with no journal signal anywhere in the engine.**

---

## A34a.1 — the library

| journal | rows | % of library |
|---|---|---|
| Journal of Endodontics | 417 | 13.7% |
| International Endodontic Journal | 237 | 7.8% |
| Australian Endodontic Journal | 50 | 1.6% |
| Clinical Oral Investigations | 97 | 3.2% |
| Journal of Dentistry | 64 | 2.1% |
| Cochrane Database Syst Rev | 43 | 1.4% |
| everything else | 2,128 | 70.1% |

## A34a.2 — what retrieval puts in front of the model

| journal | slots | % of retrieval | % of library | ratio |
|---|---|---|---|---|
| Journal of Endodontics | 536 | 16.2% | 13.7% | 1.18 |
| **International Endodontic Journal** | **475** | **14.4%** | **7.8%** | **1.84** |
| Australian Endodontic Journal | 54 | 1.6% | 1.6% | 0.99 |
| Clinical Oral Investigations | 108 | 3.3% | 3.2% | 1.02 |
| Journal of Dentistry | 55 | 1.7% | 2.1% | 0.79 |
| Cochrane Database Syst Rev | 56 | 1.7% | 1.4% | 1.20 |

Every journal is retrieved at roughly its library share except IEJ, which is
retrieved at **1.84×** it.

## A34b — the comparison the item exists for

| journal | PubMed | % PubMed | % library | % retrieved | verdict |
|---|---|---|---|---|---|
| Journal of Endodontics | 76 | 15.4% | 13.7% | 16.2% | **balanced** |
| International Endodontic Journal | 36 | 7.3% | 7.8% | 14.4% | library balanced, **retrieval 2×** |
| **Australian Endodontic Journal** | 23 | **4.7%** | **1.6%** | 1.6% | **UNDER-STOCKED** |
| Clinical Oral Investigations | 12 | 2.4% | 3.2% | 3.3% | balanced |
| Journal of Dentistry | 11 | 2.2% | 2.1% | 1.7% | balanced |
| Cochrane Database Syst Rev | 1 | 0.2% | 1.4% | 1.7% | over-stocked (deliberately) |

The ratio a reader actually sees on the page:

| | JOE : IEJ |
|---|---|
| PubMed, these questions | **2.1 : 1** |
| the library | 1.76 : 1 |
| what retrieval shows | **1.13 : 1** |

That is the perceived skew, and it is a real one — but it is IEJ being lifted,
not JOE being held down.

**Method note.** The PubMed comparison uses each question's own text plus
`ENDO_DOMAIN_FILTER`, not the generated boolean. Using the generated boolean
would confound query style with journal mix, and journal mix is the question.
n = 494 across 29 questions, so the smaller journals' figures are coarse.

## The mechanism: it is not the tier quotas

If IEJ were riding a quota — IEJ is 52% level1 within its own rows, JOE 37% —
the lift would be concentrated in level1. It is not. IEJ is over-retrieved
**inside almost every tier**:

| tier | library JOE | library IEJ | retrieved JOE | retrieved IEJ | IEJ lift |
|---|---|---|---|---|---|
| level1 | 13.3% | 10.6% | 16.4% | 21.3% | 2.0× |
| level2 | 8.3% | 6.4% | 16.5% | 11.6% | 1.8× |
| level3a | 21.6% | 7.8% | 22.7% | 15.5% | 2.0× |
| level3b | 15.2% | 8.7% | 34.7% | 8.9% | 1.0× |
| level4 | 20.3% | 4.4% | 20.1% | 1.4% | **0.3×** |
| level5 | 5.3% | 11.8% | 7.2% | 33.8% | **2.9×** |
| guideline | 0% | 28.6% | 0% | 35.3% | 1.2× |

Membership inside a tier is decided by cosine similarity to the question. So the
finding is: **IEJ papers embed closer to the questions clinicians ask than JOE
papers in the same tier do** — most strongly at level5, where IEJ's narrative
reviews sit. No journal signal exists anywhere in the engine, invariant 11 is
intact, and this is a property of what the two journals publish.

The mirror image is level4, where JOE is retrieved at 20.1% and IEJ at 1.4% —
JOE's case reports are on-question and IEJ's are not.

## A34c / A34d — what follows

**A34d applies to JOE: the library is balanced and retrieval is not — but not in
the direction the item anticipated, and not against JOE.** JOE is already
retrieved slightly above its PubMed share. There is nothing for a JOE preference
to correct: a within-tier tie-breaker or a retrieval-stage guarantee would push
JOE above the field's own mix while repealing invariant 11 and rewriting the
"never by journal" card. **Recommendation: do not reopen the mechanism
question.** The measurement does not support it.

**A34c applies to a different journal.** *Australian Endodontic Journal* is the
one genuine stocking gap — 4.7% of what PubMed returns for these questions, 1.6%
of the library. That is additive ingestion with no scoring change and no
invariant touched, exactly A34c's shape, and it was not what anyone was looking
for.

**Stopping here for RB, as A34d requires.** Neither mechanism option is
implemented.
