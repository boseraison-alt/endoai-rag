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

---

## Items 2–5 — what changed, and what it measured

| Item | Status | Before → After | Test file | Commit |
|---|---|---|---|---|
| 1 · Reproduce and diagnose | DONE | three defects, three mechanisms; only one was the predicted one | — | `ec9412c` |
| 2 · Intent split | DONE | one pipeline → `diagnostic` / `treatment`, failing open to treatment | `tests/test_case_differential.py` | `860d73e` |
| 3 · Differential-first retrieval | DONE | 26 → **139** papers, 3 → **12** candidate etiologies in retrieved titles | same | `860d73e` |
| 4 · Follow-up relevance | DONE | non-discriminating question **53% → 0%**; contrast case **10/10** | same | `860d73e` |
| 5 · Pin it | DONE | 2 new eval cases, **2/2 passing**, 0 support flags each | `eval/questions.json` | `9ce50a5` |
| 6 · Close | DONE | suite **1440 → 1483** passing, 44 skipped | — | this report |

---

## The 20-year-old case, before → after

Both runs are the production path through `/case_chat`, same question, verbatim.

| | before | after |
|---|---|---|
| intent classified | — (no such step) | **diagnostic** |
| candidates enumerated | — | **6** |
| papers retrieved | 26 | **139** |
| candidate etiologies in retrieved titles | 3 | **12** |
| answer length | 4,406 chars | **10,208** |
| first etiology word | char 116 | **char 2** |
| first management word | char 866 | **char 4,807** |
| cost | $0.0724 | $0.1742 |

### Before — the answer opened like this

> **Assessment:** A necrotic pulp in a 20-year-old with an intact, unrestored,
> caries-free tooth strongly points to a traumatic etiology as the primary
> cause…
>
> **Recommendation:** Conduct a thorough trauma history … Once necrosis is
> confirmed, conventional root canal treatment is the primary indicated
> intervention.

The etiology is one clause of one sentence. There is no differential, nothing
argues against anything, and no test is named against the candidate it would
settle — because the prompt had no section for any of that.

### After — the same question

> **Differential — most likely first**
>
> **1. Traumatic injury (luxation, concussion, or crown fracture)**
> - *Fits because:* A 20-year-old … sits squarely in the peak epidemiological
>   window for dental trauma … Patients at this age frequently forget or
>   minimise minor luxation events.
> - *Argues against:* No trauma history mentioned. If the tooth is a posterior
>   molar, trauma becomes less likely as the primary mechanism.
> - *Evidence:* Pulp necrosis risk after luxation is significantly increased in
>   the presence of concomitant crown fractures (HR 4.0, 95% CI 2.6–6.1) and
>   intrusion injuries (HR 2.3, 95% CI 1.2–4.1).
>
> **2. Dens invaginatus (dens in dente)** …
> - *Argues against:* … no mandibular involvement was found in a
>   10,000-patient radiographic study.
>
> **3. Dens evaginatus with tubercle attrition or fracture** …

and ends with a table mapping each test to the candidates it settles —
periapical radiograph, targeted trauma history, transillumination, CBCT, a
six-point periodontal chart, magnification — ordered by how much each narrows
the differential per unit of chair time. Management follows, in four sentences.

**Two of the six candidates had no literature at all**, and the answer says so
rather than dropping them:

> *Evidence:* No paper in this evidence base addresses idiopathic or herpes
> zoster-related pulp necrosis in this presentation.

That is deliberate. A cause worth considering does not stop being worth
considering because nobody has published on it, and the alternative — dropping
it — hides a differential behind the accident of the literature.

Full text of both eval-case answers is committed under
`eval/logs/case_answers/`.

---

## Cost per diagnostic answer

One full turn of each kind, every logged call attributed:

| | diagnostic (6 candidates) | treatment (single query) |
|---|---|---|
| synthesis | $0.1324 | $0.1156 |
| differential generation | $0.0202 | — |
| search-term generation | $0.0175 (**six** retrievals) | $0.0029 |
| citation-support check | $0.0074 | $0.0116 |
| follow-ups + intent routing | $0.0026 | $0.0028 |
| **total** | **$0.1801** | **$0.1329** |

**Multi-candidate retrieval is not the cost driver, and the brief expected it
to be.** All six candidates cleared the library gate, so six retrievals cost
1.7 cents in term generation and no PubMed traffic at all. The rise is the
synthesis prompt: 36.8k input tokens against 17.5k, because there are 139
papers to reason over instead of 26. A diagnostic answer costs about 35% more
than a treatment answer on the same engine, and about 2.4× the pre-batch case
answer — which was reasoning over a fifth of the evidence.

---

## Found, not fixed

| severity | finding |
|---|---|
| **MEDIUM** | **Overreaching etiologic claims survive into a diagnostic answer.** One run flagged 3 of 16 pairs, all the same shape: a general clinical statement marked to a foundational 1970s paper ("True retrograde pulpal necrosis is uncommon because…" → PMID 269259). Same class `guardrails-v1` catalogued as overreach. Two later runs flagged 0, so it is variance around a real tendency rather than a constant. The eval case caps flags at 4 as a blow-up guard; **`case-v2.1` owns tightening it to 0 by fixing the sourcing.** |
| **MEDIUM** | **A candidate's search topic is generated once and never checked.** If the differential names a candidate badly — "Idiopathic or occult cause (including undetected microbial access via extreme attrition)" — its retrieval inherits the bad topic. It returned 33 papers here, so nothing failed; nothing would have said so if it had returned 0 either, beyond the answer stating the gap. |
| **LOW** | **The differential is not shown to the clinician.** It is published on the job as `differential` and the trace reads it, but no template renders it. The answer carries the same content in prose, so nothing is lost — but a UI showing "searching literature for: dens invaginatus" during the two-minute retrieval would make the wait legible. |
| **LOW** | **`must_precede` matches the first occurrence of a substring, not a heading.** `["differential", "root canal treatment"]` would pass on an answer whose word "differential" merely appears in a treatment paragraph. Adequate while the diagnostic format mandates a `**Differential` heading; brittle if that changes. |
| **LOW** | Two corrections to my own measurement script in one batch, both in the same direction — a keyword classifier applied to the wrong patient, then applied to a reason clause instead of a question. A keyword list is a blunt instrument and its output has to be read before it is believed. |

---

## Decisions taken, with the alternative rejected

1. **The router fails open to TREATMENT.** *Rejected:* failing open to
   diagnostic, which would be "safer" in the sense of producing more reasoning.
   Treatment is the path that shipped and is measured; a Haiku hiccup should not
   send a routine follow-up down a new and more expensive path.
2. **One retrieval per candidate, sharing the library gate.** *Rejected:* one
   widened query naming all the candidates. That is the same single LLM call
   asked to be luckier, and Item 1 measured what its luck is worth — dens
   invaginatus in 2 runs of 8.
3. **A candidate with no literature stays in the differential.** *Rejected:*
   dropping it. The empty result is information, and it is the difference
   between "the literature disagrees" and "nobody has studied this".
4. **The follow-up assertions reuse the existing `clarify` block.** *Rejected:*
   the parallel `followups_must_*` keys I had already written. Two guards on one
   property is how the worse one ends up maintained — the same reasoning that
   deleted a duplicate `prior_pmids` test in `guardrails-v1`.
5. **The eval answer directory is `case_answers/`, not `answers/`.** *Rejected:*
   a `!` negation in `.gitignore`. A bare `answers/` matches at any depth, and a
   negation that has to be understood is worse than a name that does not
   collide.

---

## Cost

| what | cost |
|---|---|
| Item 1 traces and samples (2 traces, 42 follow-up samples, 8 query samples) | ~$0.90 |
| Items 2–4 validation (after-trace, 3 follow-up sample sets) | ~$0.70 |
| Item 5, three case-subset eval runs | ~$0.95 |
| **batch total** | **~$2.55** |

Two of the three eval runs were re-runs after an assertion of mine turned out
to be wrong. That is the cost of finding out, and it is the reason the harness
now saves the answers.
