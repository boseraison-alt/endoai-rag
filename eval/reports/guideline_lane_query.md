# Item 2 — the guideline lane asks a guideline-shaped question

**Date:** 2026-09-06 · **Verdict: both thresholds passed. SHIPPED.**
**Replay:** `python scripts/measure_guideline_lane_query.py --json eval/reports/guideline_lane_query.json`

---

## The result

| | measured | threshold |
|---|---|---|
| lane empty rate, **full conjunction** | **23 of 29 (79%)** | — |
| lane empty rate, **subject group** | **1 of 29 (3%)** | < 50% → **PASS** |
| added esearch latency | **+0.09 s** per question | < 10 s → **PASS** |
| questions gaining a guideline | **22** | |
| questions losing one | **0** | |

**Both fixtures pass.**

| fixture | full conjunction | subject group |
|---|---|---|
| **PMID 37772327** ESE S3 2023 — retreatment vs apical microsurgery | 0 hits, absent | 28 hits, **present** |
| **PMID 26990236** ESE revitalisation 2016 — immature teeth | 0 hits, absent | 6 hits, **present** |

## The change

The lane inherited the study lanes' topic string — a three-group conjunction
naming the intervention, the subject and the population qualifier. That is the
right shape for finding trials and the wrong shape for finding guidelines,
because **a guideline is broad by construction.** "Treatment of pulpal and
apical disease: the ESE S3-level clinical practice guideline" cannot match a
query built to find trials about *nonsurgical retreatment AND apical
microsurgery AND persistent apical periodontitis*, even though it is the
guideline that answers the question.

The lane now gets the **subject group alone**. The study lanes are untouched
and a test pins that.

**Applied in `fetch_papers`**, the one point both retrieval paths pass through.
A broadening that lived in `app.py` would have reached Review and Case and not
the curriculum — the divergence class this codebase has spent three batches
removing.

### Measurement method

Two full 29-question runs minutes apart would move two things at once: the
query **and** whatever PubMed returned that minute. Instead each question's
terms are generated **once** and both queries are issued against them back to
back. The only difference is the topic half.

## I got the selection rule wrong first, and a test caught it

I assumed `_group_is_generic` marks the subject group. It is **all-or-nothing**
— every synonym must be corpus-wide — and a real subject group rarely
qualifies: `("root canal" OR endodontic* OR "root canal treatment")` scores
**2 of 3**, because the third is not in `_COVERAGE_GENERIC`.

So it returned False for *every* group on that query, and the length fallback
picked the five-synonym **scenario** group — the widest, and the wrong concept.
Selection is now by **generic share**, with length only breaking ties.

A second test caught that broadening could return an **empty** topic, which
would query the domain filter alone: every endodontic guideline on PubMed
regardless of the question. It now falls back to the unbroadened term — the
safe direction, because retrieving too little is the failure being fixed and
retrieving everything would be a new and worse one.

Both were assumptions about existing helpers that I did not check before using
them. That is standing rule 17's family: measure the real forms first.

## The 79% here vs the 86% reported yesterday

Different measurements of the same thing. Yesterday's 86% counted **every lane
query across the three baseline runs** (482 queries, 415 empty) — several
queries per question, one per generated search term. This counts **one query
per question** (29 of them), using the primary generated term. Same direction,
same conclusion, and neither is a correction of the other.

---

## FOUND, NOT FIXED

- **The library route is unaffected.** This widens what the *live* lane
  retrieves from PubMed. A guideline already in the library still has to clear
  the cosine floor to be served, and `review-followup-immature-teeth` — one of
  the two fixture questions — is **library-pinned**. The fixture that motivated
  the fix is not fixed for that route. Severity: medium; it needs the library
  route's guideline retrieval measured on its own axis.
- **1 of 29 questions still returns nothing** even on the subject group. Not
  investigated — with 22 questions gaining a guideline the remaining one is
  more likely a genuinely uncovered topic than a query defect, but that is an
  inference, not a measurement.
