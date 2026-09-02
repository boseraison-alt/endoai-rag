# A9a — reference-line provenance audit

**Measurement only. Nothing changed.** Read-only over 117 stored documents with a
`## REFERENCES` section (1,405 model-written reference lines) and the live
library. No API calls.

---

## 1. What the model is shown, per path

The Review and Case paths build their evidence block from
`format_paper_context_line`:

```
PMID: 38145805 | Authors: Olivieri JG, Encinas M | Year: 2024 |
Citations: 12 | n=240 | 12mo follow-up | Evidence Score: 81.7/100
```

| field | Review / Case | Deep Learning stitcher |
|---|---|---|
| pmid | shown | shown |
| authors | shown | shown |
| year | shown | shown |
| sample size | shown | — |
| follow-up | shown | — |
| citations | shown | — |
| score | shown | shown |
| tier | — | shown |
| **journal** | **NOT SHOWN** | shown |
| volume / issue / pages | **NOT SHOWN** | **NOT SHOWN** |
| title | **NOT SHOWN** | **NOT SHOWN** |

So on the Review path **every journal name in the REFERENCES block is generated
with no source**. The model is recalling it from the PMID, or inferring it from
the topic. It is not reading it.

## 2. Where each rendered surface gets its fields

| surface | source |
|---|---|
| browser bibliography line | **DB** — pmid, authors, year, n, follow-up, score |
| papers table row | **DB** — pmid, tier, year, authors, journal, n, follow-up, score |
| inline citation pill | **DB** — authors, year, journal/abbrev, volume, issue, pages |
| abstract popover | **DB** + `/api/abstract` |
| deck reference slides | **DB** — `build_reference_slides(papers_list, cited_pmids)` |
| **answer REFERENCES section** | **MODEL-WRITTEN. No DB field reaches it.** |

One surface out of six is prose. It is also the one a clinician copies into a
note, and the only one that survives into a plain-text export.

## 3. Model-written lines vs the library

Compared word-by-word with a prefix rule, so `Int Endod J` counts as agreeing
with `International endodontic journal` and `J Endod` does not.

**The aggregate is confounded and should not be quoted.** The library has been
rescored and re-backfilled since the older answers were written
(`endo_papers_rag_score_backup` exists), so a disagreement on a April answer may
be the library moving, not the model erring. Split by document age:

| period | journal (never shown) | score (shown) | n (shown) | year (shown) |
|---|---|---|---|---|
| 2026-04/05 | 119/227 = **52.4%** | 263/319 = 82.4% | 38/72 = 52.8% | 0% |
| 2026-08 | 60/199 = **30.2%** | 133/696 = 19.1% | 21/324 = 6.5% | 0% |
| **2026-09-01/02** | **28/161 = 17.4%** | 28/274 = 10.2% | 6/147 = 4.1% | 0% |

Today's two answers, where the library has not moved at all since:

```
answer_20260902_073805 (apixaban)     journal 0/6 wrong    score 0/7 wrong
answer_20260902_105256 (retreatment)  journal 1/9 wrong    score 0/13 wrong
```

The one wrong journal today is the one you spotted: **PMID 38145805 — written
"Int Endod J", the library holds "Journal of dentistry".**

**Read the score and n columns as upper bounds, not model-error rates.** Those
two fields ARE shown to the model, they agree on recent answers, and the
historical disagreement is mostly the rescore. The journal column has no such
excuse: the model is never shown it, and 1 in 6 recent ones is wrong.

## 4. The error class that matters, and its trend

A paper attributed to *Cochrane Database of Systematic Reviews* when it is not.
In a product whose entire thesis is evidence tiering, this is the worst
available error: the reader upgrades the paper's tier on sight.

| period | lines written as "Cochrane…" | of which NOT Cochrane papers |
|---|---|---|
| 2026-04/05 | 38 | **15 (39%)** |
| 2026-08 | 34 | **0** |
| 2026-09-01/02 | 35 | **0** |

11 distinct papers were falsely presented as Cochrane reviews in the spring —
including PMID 39117767 (*Scientific reports*) and 37195330 (*Oral health &
preventive dentistry*). **The class has been closed since August.** I have not
identified which change closed it; it is not one of Stage 1's.

So: the structural hole is open, the catastrophic symptom is gone, and a
moderate one (≈17% wrong journals) remains.

---

## Cause

`format_paper_context_line` omits journal, volume, issue, pages and title, and
the REFERENCES prompt template asks the model to write a bibliographic line
anyway:

```
1. [PMID: 12345678] Author AB, Author CD et al. — Brief description.
   Journal, Year. Follow-up: X months. n=XX. (Score: XX/100)
```

The template requests a field the context does not contain. The model complies,
because complying is what it does.

This is the same shape as Q3: the fix for the impact factor was to stop putting
the number in front of the model, not to strip it afterwards. Here the field is
absent and asked for, which is the mirror image and produces invention instead
of repetition.

## What I recommend, and why it widens A9

**Do not give the model the journal.** That would make the number more accurate
and leave the surface model-written, which is the actual defect: bibliographic
metadata should never be prose. Build the reference line from the paper record,
the way the bibliography panel, the papers table, the citation pill and the deck
reference slides already do — five surfaces already do this correctly and one
does not.

That is a larger change than "add a field", and it is why this audit was worth
doing before A9's fix was scoped:

* the REFERENCES section stops being model output and becomes rendered data;
* the prompt stops asking for it, so the model spends no tokens on it;
* `assemble_bibliography` (Q5) already computes exactly the right set, so the
  ordering and the membership are already solved;
* one field genuinely is the model's to write — the "Brief description" clause —
  and that is a claim about the paper, so it stays in the checked-claims set.

**Open question for RB:** the description clause is the only part of a reference
line that should remain model-written. Do you want it kept (it is genuinely
useful — "Cochrane review of 47 RCTs; no difference in radiological failure") or
dropped in favour of the paper's own title? Keeping it means the reference list
still contains an unverified sentence per paper; dropping it loses the one thing
the list adds over a bare citation.
