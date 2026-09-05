# Item 2 — the PRISMA nomination asymmetry, measured and unified

**Date:** 2026-09-05 · **Branch:** `fix/retrieval-blindspot`
**Verdict: RELEVANCE wins 23–4. Unified on relevance. Test-pinned.**
**Replay:** `python scripts/measure_prisma_nomination.py --json eval/reports/prisma_nomination.json`

---

## The measurement

| | |
|---|---|
| questions measured | 29 |
| the two rules **agree** | 2 |
| the two rules **differ** | **27** |
| of those, more on-topic review chosen by **relevance** | **23 (85%)** |
| of those, more on-topic review chosen by **year** | 4 (15%) |

Mean similarity of the nominated review: relevance 0.750, year 0.667.
Mean year of the nominated review: relevance 2019.0, year 2025.7.

**Unified on relevance**, as the ORDER expected. Year alone rewards the newest
review over the right one — the mean-year column shows the year rule doing
exactly that, nominating 2025–2026 reviews that the blind panel judged less
on-topic on 23 of 27 questions.

## How the judge was kept honest

Three things, each guarding a different way this measurement could have lied:

1. **One pool, two rules.** Comparing a live answer with a library answer
   would move two variables — the rule *and* the retrieved papers (rule 22).
   Each question ran ONE library retrieval and both rules were applied to that
   single candidate pool, so the rule is the only difference.
2. **Cosine could not be the judge.** Similarity is the relevance rule's own
   signal; scoring the titles by cosine would be asking the rule to mark its
   own exam. The judge is Haiku, given the question and two titles as A and B,
   with no year, no PMID and no hint which rule produced which.
3. **Three votes with the slot order flipped between them.** A judge that
   answers "A" regardless of which review is in slot A is showing position
   bias, not judgement. Flipping makes that visible: **20 of 27 disagreements
   were unanimous**, 7 split and were taken on majority.

## The fix, and the second defect it uncovered

The divergence was never an explicit fork on the route. It was this:

```python
if any(sim > 0 for ...):  chosen by relevance     # library rows, from cosine KNN
else:                     chosen by year          # live rows, from fetch_papers
```

So one function ran two rules, selected by which retrieval path happened to
run, and nothing asserted they agreed.

`flag_superseded_by_review` now takes `question=` and, where the route supplies
no similarity, embeds the question and the candidates with **`rag.embed`** —
the same model the library was indexed with — so the number is on the same
scale as a stored cosine rather than a second notion of similarity sharing a
name. All four production call sites pass it.

**The fix did not work on the first attempt, and the reason is the finding.**
The live path still degraded to year. The log said *"the question could not be
embedded"* — and that message was wrong. The question embedded fine:

```
[prisma] similarity backfill: 0 computed, 13 candidate(s) had no title
or abstract, 0 embedding call(s) failed
```

**`fetch_papers` never put `title` or `abstract` on its scored dicts.** A
live-path paper dict carried authors, journal, year, citations, sample size,
follow-up, impact factor and a score — and not what the paper was called. The
title reached Claude only through the separate `annotated_text` block, so
nothing reading the *dict* could see it. That is the same field pair, missing
for the same reason, as the library-side gap fixed on 2026-08-31.

Both are now added. `_safe_papers` whitelists what leaves the server and
neither field is on it, so the abstract still stops at the prompt.

**My own instrument error, recorded under rule 33's family:** the degraded
branch asserted a single cause for three different faults, and it sent me to
look at the embedder while the real fault was upstream in `fetch_papers`. The
branch now distinguishes *no question passed* / *no candidate could be given a
similarity* / *every computed similarity was zero*, and the backfill loop
counts what it dropped instead of `except: continue` (standing rule 5 — my code
was violating it).

## After the fix, on the live path

```
before: chosen by year — DEGRADED: no similarity on this route ...
after : chosen by relevance (19 similarities computed here)
```

## Tests

`tests/test_prisma_dedup.py`, two new classes, 9 tests, all mutation-checked:

- the live shape nominates by relevance once a question is passed **(M1 killed)**
- without a question it degrades to year and *says so* **(M2 killed)**
- a route that already has similarity is **not** re-embedded, and its stored
  cosine is not overwritten
- an embedding failure falls back rather than raising
- **every production call site passes a question (M3 killed)** — the parity
  assertion. The defect was never that either rule was wrong in isolation; it
  was that one function served two paths and nothing asserted they agreed. A
  test of each branch would have passed throughout. The regex excludes the
  `def` line (rule 33) and asserts it matched exactly 4 sites (rule 4 — a
  parity test that goes vacuous is worse than none).
- `fetch_papers` puts title and abstract on the scored dict **(M4 killed)**
- the similarity is computed over title AND abstract **(M5 killed)**
- the abstract still cannot reach the browser (rule 30)

Cost: one CPU embedding per SR candidate, bounded at `_SIM_BACKFILL_MAX` 40
against a quota-capped pool of 28, plus one for the question. Measured: 19
computed on a live review question.
