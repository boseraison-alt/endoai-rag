# Item 3 — the divergence audit, what is still open, and the agreement test

**Date:** 2026-09-05 · **Branch:** `fix/retrieval-blindspot`

There are four places an evidence base gets built, not two, and the audit
covers all four:

| # | builder | path |
|---|---|---|
| A | `endo_ai.build_evidence_base` | curriculum / CLI review |
| B | `app.build_evidence_base_with_progress` — **live branch** | Review, Case |
| C | `app.build_evidence_base_with_progress` — **library branch** | most warm questions |
| D | `app.build_differential_evidence` | Case differential |

---

## CLOSED since the audit

| divergence | class | closed |
|---|---|---|
| app.py's own hardcoded lane list, three lanes behind | RETRIEVAL | `432c460` |
| `PROVISIONAL_KEY` dropped at five wiring sites | RETRIEVAL | `9f864b1`, `6b4907e`, `0689407` |
| no cross-tier dedup on the curriculum path | RETRIEVAL | `0fb3993` |
| `TIER_FETCH_DEPTH` not forwarded on the live path | RETRIEVAL | `0fb3993` |
| `mode` not forwarded on the live path | RETRIEVAL | `0fb3993` |
| dead `question=` on `fetch_untyped_recent` | neither (dead) | `0fb3993` |
| `seen_pmids` not seeded with the Cochrane tier | RETRIEVAL | `75054dd` |
| `detect_outliers` never ran on the curriculum path | RENDERING | `75054dd` |
| live-fetched guideline carried no org/status/jurisdiction | RENDERING | `75054dd` |
| the live path showed Claude 26% of what it retrieved | RETRIEVAL | `8c11dec` |
| **PRISMA nominated by year on B/A/D and by relevance on C** | **RETRIEVAL** | **today, item 2** |
| **`fetch_papers` put no title/abstract on its scored dicts** | **RETRIEVAL** | **today, item 2** |

## STILL OPEN

### 1. The library branch applies no per-tier quality floor or quota cap — RETRIEVAL

**Deferred, and now for a measured reason.** Item 1a: the change takes 8 of 29
questions below `min_evidence_papers` 40 against a pre-declared stop threshold
of 5. Full analysis in `library_floor_29.md`. Not contained — it needs a design
for how two guards on different axes interact, which is not a batch item.

### 2. Search-term breadth differs between A and B/C — RETRIEVAL

B and C call `generate_multi_search_terms` and then `label_and_expand`; A uses
the single `smart_topic` from `generate_search_terms`. So a curriculum module
issues one term set per lane where a Review issues ~7.

**Deferred, not contained:** this is arguably by design — a curriculum's
breadth comes from having four modules with four topics — and changing it
multiplies curriculum retrieval cost by ~7 on a path that already costs $0.28
per run. It needs a cost measurement before it is even a candidate. Recorded
here because nothing else records it.

### 3. The review-mode early stop skips `observational` — RETRIEVAL

Carried over from the previous handover, **and addressed this batch by D1's
recency exemption** — see `early_stop_recency.md`. The lane is still skipped
for older papers by design; what changed is that recent papers in every weaker
lane now survive the early stop.

### 4. `apply_currency_tags` is not called on path A — NOT A DIVERGENCE (verified)

The previous session deferred this on the grounds that `fetch_papers` already
recomputes `is_old` and `age_years`. **Checked rather than trusted:**
`apply_currency_tags` sets exactly those two fields, by the same arithmetic
against the same `CURRENCY_THRESHOLD_YEARS`. The omission is genuinely a no-op.
Closing it as verified rather than leaving it on the list as a suspicion.

### 5. `build_currency_warning` — NOT A DIVERGENCE (verified)

Reached through `_build_evidence_context`, which every path shares. It looked
like a one-path call in the call-site count; it is not.

---

## The parity check that would have caught the app.py tier list

`tests/test_live_path_lane_parity.py`, two new classes.

**`TestTheTwoBuildersIssueTheSameLaneSet`** runs A and B offline with every
fetcher stubbed and asserts they requested the **same set of lane keys**. Not a
test of each — a test of their agreement. Every previous test in that file
asserts on one builder or on the source shape of one, which is exactly what let
the original defect through: three lane tests were green while the live path
had its own list three lanes behind.

Mutation-checked in both directions:

- **M6** — live path drops the `guideline` lane (the original defect,
  re-created): **KILLED**
- **M7** — curriculum path drops the provisional lane: **KILLED**

A second test asserts the agreed set equals what `tier_query_lanes()` declares,
plus `cochrane` and the provisional lane, and that it has at least 10 members —
rule 4, because an agreement test where both sides issue nothing passes.

**`TestEveryTierOrderLoopAccountsForTheProvisionalLane`** is
`grep -n "in TIER_ORDER"` written down. Every loop over `TIER_ORDER` must
either handle `PROVISIONAL_KEY` or carry a comment saying why it need not, so a
sixth wiring site cannot be added silently. Two loops had neither and now have
the reason stated:

- `app.py` library banding — no library row can carry the key, because the
  lane never writes back (pinned elsewhere). If write-back ever admits one,
  that loop is where it would vanish.
- `endo_ai.build_synthesis_order` — a provisional paper carries `score: None`,
  and `p.get("score", 0)` returns the None (the key is present), so one such
  paper raises `TypeError` and takes the answer down. The lane reaches the
  prompt through `_build_evidence_context` instead.

**M9** — deleting that second justification comment: **KILLED**.

### An instrument error inside this test, caught before it shipped

The checklist first scanned a fixed 22-line window around each loop, and
reported `app.py:1935` as a defect. It is not one: the differential merge
handles the lane 26 lines after its loop starts. Widening the window only moves
the boundary, so the scan is now scoped to the **enclosing function** — the
honest unit for "does the code that builds this evidence base deal with the
lane at all". Same family as standing rule 33.
