# Overnight Report 4 — `case-v2`

Diagnostic reasoning in case discussion. Autonomous batch on `main`,
2026-09-01. Standing rules from `WORKLIST.md` §0/§6 in full.

---

## Item 1 — Reproduce and diagnose (the trace, recorded before any change)

The case, exactly as reported:

> 20-year-old, necrotic tooth, no restoration, no caries — what could the
> cause be?

### The first trace did not reproduce the failure, and that was the most useful thing about it

`scripts/trace_case.py`, one run on `909e87d`
(`eval/logs/case_trace_before.json`):

- follow-up questions: trauma history, periapical imaging, vitality testing —
  three discriminating questions, **no bisphosphonates**;
- the composed PubMed term contained `dens invaginatus OR "dens in dente" OR
  developmental OR anatomic* OR idiopathic`;
- the multi-query RAG set contained a dedicated
  `("dens invaginatus" OR "dens in dente" OR invagination …)` query;
- the retrieved titles contained *luxation*, *trauma*, *etiology*;
- the answer's first etiology word was at character **116** and its first
  management word at **866** — it led with etiology, and it named luxation,
  crown fracture, dens invaginatus and dens evaginatus.

On one sample this looks like a fixed bug. It is not. Both generators involved
are single LLM calls, and this repo has already been bitten once by treating a
stochastic generator's single sample as its behaviour — `WORKLIST` §1.1, the
search-term generator that returned 1 term and 8 terms for the same question
minutes apart and put ±50% noise under every eval number until it was fixed.
So both halves were sampled.

### Half one — the follow-up questions. Reproduces at 53%.

`scripts/sample_case_followups.py -n 15`
(`eval/logs/case_followups_before.json`):

| | |
|---|---|
| runs containing a **non-discriminating** question | **8/15 = 53%** |
| runs asking about **bisphosphonates** | **7/15 = 47%** |
| also seen | immunosuppression 7, head-and-neck radiation 4, uncontrolled diabetes 1, restorability 1 |

Wording, verbatim, from run 2 of 15:

> *"Are there any medical factors such as bisphosphonates, head-and-neck
> radiation, or immunosuppression? — these significantly alter treatment
> planning and prognosis"*

Asked of a 20-year-old.

**The mechanism is in the prompt and needs no inference.**
`generate_case_followups` is handed `_CASE_DECIDING_FACTS`, which is a
CHECKLIST, and the checklist reads:

```
- MEDICAL RED FLAGS — bisphosphonates/antiresorptives, head-and-neck radiation,
  immunosuppression, uncontrolled diabetes, anticoagulation, endocarditis risk.
```

The prompt then asks which of those facts are *"genuinely MISSING"*. For a
20-year-old with a necrotic tooth, bisphosphonate status **is** missing from
the description — literally, and uselessly. Nothing in the prompt asks the
second question, which is the one that matters: *would knowing it change the
differential or the plan?* Whether the model supplies that judgement on its own
is left to it, and it does so slightly better than half the time.

**And the questions that never get asked.** Across all 15 runs:

| topic | runs asked |
|---|---|
| trauma history | **15/15** |
| periapical imaging | **15/15** |
| vitality testing | 4/15 |
| **orthodontic history** | **0/15** |
| **which tooth / tooth type** | **0/15** |
| **sinus tract or swelling** | **0/15** |
| **developmental anomaly, groove, invagination** | **0/15** |
| **discoloration** | **0/15** |

The generator asks the two checklist items that happen to fit, and never asks
the five questions that would actually separate the candidate causes of a
necrotic virgin tooth in a young adult. It is not that it asks a bad question
53% of the time; it is that it is working from a treatment-planning checklist
in a diagnostic conversation.

### Half two — the retrieval. The brief's hypothesis is half right, and the half it gets wrong is the important one.

The hypothesis to confirm was: *retrieval fetched management literature because
the query never contained any candidate etiology.* Sampling the two query
generators 8 times (`eval/logs/case_query_terms_before.json`):

| candidate etiology | runs whose query mentions it |
|---|---|
| trauma / luxation / fracture | **8/8** |
| crack / infraction | 4/8 |
| generic "developmental anomaly" | 4/8 |
| **dens invaginatus** | **2/8** |
| orthodontic history | 2/8 |
| dens evaginatus | 1/8 |
| **palatogingival / radicular groove** | **0/8** |

So it is **not** true that the query never contains a candidate etiology —
trauma is in every single one. What is true, and is worse, is that **which
other candidates appear is a coin flip**. Dens invaginatus makes it into the
query one run in four. The palatogingival groove — a classic cause of exactly
this presentation — never does.

The first trace happened to land on a run where dens invaginatus appeared. That
is why it looked fixed.

**The consequence for the answer is structural, not stochastic.** A synthesis
prompt cannot rank a differential it has no evidence for, so on 6 runs in 8 the
model is reasoning about dens invaginatus, if at all, from parametric knowledge
with no paper behind it — and the grounding rule then correctly stops it
attaching a marker. The differential is squeezed out from the retrieval end.

### Half three — the answer has no differential by construction

Not stochastic at all: `ask_case_question`'s prompt mandates exactly four
sections.

```
**Assessment:** 1-2 sentences on your clinical interpretation.
**Recommendation:** Clear, actionable recommendation with rationale.
**Evidence:** the studies that actually bear on THIS case …
**Key Considerations:** Any caveats, red flags, alternative approaches …
```

There is no ranked differential, no per-candidate features-for-and-against, and
no "what would discriminate between these" section. The traced answer's
etiologic reasoning is one clause inside **Assessment**, and **Recommendation**
is a workup-plus-root-canal plan. Even on the lucky run — the one where
retrieval did surface dens invaginatus — the *form* of the answer is a
treatment plan, because that is the only form the prompt offers.

### Item 1 conclusion

Three defects, three different mechanisms, and only one of them is what the
brief predicted:

1. **The follow-up generator works from a treatment-planning checklist.** It
   asks a non-discriminating question 53% of the time and never asks the five
   questions that would separate this case's candidate causes. → Item 4.
2. **The candidate etiologies in the query are whatever one LLM call thought
   of.** Trauma always; dens invaginatus 25%; the palatogingival groove never.
   Not "no etiology" — *no systematic* etiology. → Items 2 and 3.
3. **The answer has no differential section to put one in.** Deterministic,
   and unaffected by anything retrieval does. → Item 3c/3d.

Trace and both samples committed before any code changed.
