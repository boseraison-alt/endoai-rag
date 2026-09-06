# Night batch 2026-09-07 — predictions, committed BEFORE the writes

Branch `night-20260906`, continuing. Phase 0 verified before this file:
bundle `endo-ai-rag-20260906-night.bundle` records a complete history (HEAD
`81664be`); `db-20260906-night/endo_papers_rag.csv.gz` holds 3435 rows against
3435 live; fresh pre-A dump taken to `db-20260907-preA/`, 14 tables, 27574 rows,
all verified.

`091139d` pushed.

**Gated items: both read NOT AUTHORISED.** Item F is skipped entirely. Item E's
preconditions 1–5 run, because the batch marks them as measurement; nothing is
applied.

---

## Item A — retire the two Cochrane slug duplicates

The batch's prediction: **exactly 2 rows retired, 2 rows enriched, 0 tier
changes, 0 inserts, total rows unchanged at 3435, `cochrane` stays 21.**

Dry run agrees, after one correction I had to make first — **the first dry run
retired THREE rows, not two**, and the third was `ESE-QG-2006`.

That row is already quarantined by the A2 audit with the reason string
`duplicate_of:17180780`, and `guideline_id` already cleared. Retiring it again
would have overwritten that string with `re-keyed: this document is 17180780`
— the same fact in different words — and broken the two tests that pin the
exact string (`tests/test_guideline_score_invariant.py:128` and `:215`).

So an already-quarantined row is now **terminal**: it has been retired once, by
an earlier mechanism, and the ingest does not re-retire it. With that guard the
dry run retires exactly the two the prediction names.

| number | predicted | dry run |
|---|---|---|
| rows retired | 2 | 2 |
| rows enriched (the two Cochrane PMID rows) | 2 | 2, both stay `cochrane` with scores 73.7 / 63.7 |
| inserts | 0 | 0 |
| tier changes (`level_key` moves) | 0 | 0 |
| `cochrane` census | 21 | 21 |
| total raw rows | 3435 | 3435 |
| guideline census | — | 81 → 79 |

The guideline census falls by 2 and that is **not** a tier change: the two
retired rows keep `level_key='guideline'` and leave the *citeable* census
because they are now quarantined. Both numbers are reported so neither reads as
the other.

**Predicted stored-answer impact: none.** Measured before the change: 0 of 207
stored answers cite either slug key. The 4 bare-accession matches are the
`pages` field of the surviving PMID rows, not citations.

---

## Item B — `[[GL:<id>]]`

1. PMID-slot slugs after the rewrite: **0** on both syntheses. If the rewrite
   counter stays high, the prompt is not landing and I say so.
2. Stored answers containing `[[PMID:<non-numeric>]]` whose payload is a known
   guideline id: predicted **1–5**. Last night found exactly 1 in a probe
   answer, and the stored corpus predates the guideline ingest, so I expect few.
   A zero would mean my sweep is wrong, not that the corpus is clean.

## Item D — pointer text

3. Guideline rows with no abstract and a URL: predicted **40–50** (there are
   ~45 slug-keyed records). Fetch success predicted **below half** — most are
   organisation PDFs behind navigation, and the AAO CPG is login-gated.

## Item C — admission

4. The guideline lane returns top-k. Predicted k is a small constant (5–15) and
   the gap between "above the floor" and "admitted" is **> 0 on a majority of
   the 32**. If the gap is 0 everywhere, top-k is not the cause and FNF #4 has
   a different explanation.
5. `ESE-S3-2023` is above the floor on probe 3 but **not** in the admitted set.
   This is the specific claim item C exists to test; if it is above the floor
   AND admitted, the flagship rule is unnecessary.

## Item E preconditions

6. The two `retracted → level1` rows become terminal and the changed-row count
   falls from 437 by **exactly 2**, to 435, plus however many quarantined rows
   were also being moved (predicted 0 — the query already excludes them).
7. The 1280 "not derivable" shrinks by **up to 100** when the failed efetch
   batch is retried.
8. The gap between the sample's 26.9% and the dry run's 437/3323 (13.1%): the
   sample counted only rows where a tier COULD be derived (156 decidable), so
   26.9% is 42/156. The dry run's 437/3323 uses all candidates as the
   denominator. Predicted: 437/2043 decidable ≈ **21%**, still not 26.9%, and
   the residual is sampling error on n=156. Stated now so the arithmetic is
   checked rather than asserted afterwards.

## Item G

9. Distinct off-domain documents across the 32 pools: last night's watchlist
   found **4**. Predicted the blocklist is the right tool (tail ≤ 10).
10. Animal-subject rows in the library: predicted **20–80** across all tiers,
    and **< 10** reaching any of the 29 pools.
