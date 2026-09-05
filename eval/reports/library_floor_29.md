# Item 1a — the library route's per-tier quality floor, measured on 29 questions

**Date:** 2026-09-05 · **Branch:** `fix/retrieval-blindspot` · **Base:** `5f7d5d9`
**Verdict: THRESHOLD BREACHED. The floor was NOT shipped.**
**Replay:** `python scripts/measure_library_floor_29.py --json eval/reports/library_floor_29.json`

---

## The pre-declared threshold, and the number that met it

> *"Pre-declared threshold: if more than 5 of 29 questions fall below 40 after
> the floor, STOP — the floor interacts with the guard and that needs a design,
> not a batch."*

| | count | questions |
|---|---|---|
| below 40 **before** the floor | 2 | `pregnancy`, `intentional-replantation` |
| below 40 **after** the floor | **8** | + `apdt-primary-molars`, `sdf-pulp-outcomes`, `sonic-vs-ultrasonic`, `review-newtopic-reset`, `necrotic-virgin-tooth-young-adult-diagnostic`, `dens-evaginatus-premolar-diagnostic` |
| **newly** below 40, caused by the change | **6** | the six added above |

**8 > 5 on the stated metric, and 6 > 5 on the stricter newly-caused reading.
Both readings breach. The change is parked, not shipped.**

## What this measured, and why it is not the corpus number

`scripts/measure_library_route_floor.py` measured the defect against the
library: 516 of 3,346 rows sit below their own tier's floor. That is a
statement about stored rows. This is the statement about **answers**: what the
29 eval questions would actually be served, forced onto the library route.

Fidelity: `cap_by_relevance` was wrapped for the run so production handed over
its own pre-cap bucket per tier, and the "after" was computed with production's
own `_tier_floor`, `_tier_cap` and `cap_by_relevance`. The banding was not
re-implemented — copying those 15 lines is the instrument error this project
keeps making (rules 33, 34). The wrapper was verified rather than trusted:
**29 of 29 questions agreed** with the evidence base the function returned.

## Attribution — it is not the floor alone (rule 22)

The fix changes two things at once: it adds a per-tier quality floor **and**
replaces the flat cap of 25 with `MODE_TIER_QUOTAS`. Measured separately:

| variant | total papers, 29 questions | questions below 40 |
|---|---|---|
| today (flat 25, no floor) | 2,261 | 2 |
| **cap alone** (quotas, no floor) | 1,675 | **7** |
| **floor alone** (flat 25 kept) | 1,875 | **7** |
| both, NULL-exempt | 1,457 | 8 |
| both, strict | 1,421 | 8 |

**Each half independently puts 7 questions under the guard.** This is not a
floor problem that a cap tweak dodges, nor the reverse. Anyone who returns to
this and tries "just the cap" or "just the floor" as the conservative option
should read this row first: neither is conservative.

## The trap, now a number rather than a warning

A **strict** floor — reading the coalesced 0.0 that `rag_results_to_scored`
produces for a NULL score — cuts **44 of the 55 served guideline
paper-instances** across the 29 questions. The NULL-score exemption keeps all
44. The trap named in the previous handover is real and it is 80% of the
guideline evidence on this route.

## Per tier, what the change would remove (NULL-exempt variant)

| tier | removed |
|---|---|
| level1 | 197 |
| level3a | 165 |
| level4 | 119 |
| level5 | 106 |
| level3 | 84 |
| level2 | 61 |
| invitro | 48 |
| observational | 10 |
| guideline | 8 |
| level3b | 6 |

## Per question

| question | before | cap only | floor only | both | strict | <40 |
|---|---|---|---|---|---|---|
| laser-root-canal-disinfection-live | 75 | 53 | 63 | 42 | 42 | |
| laser-root-canal-disinfection-library | 85 | 56 | 74 | 46 | 46 | |
| single-vs-multiple-visit | 109 | 77 | 99 | 73 | 71 | |
| mta-vs-biodentine-pulpotomy | 120 | 78 | 97 | 73 | 71 | |
| naocl-concentration | 70 | 63 | 54 | 47 | 47 | |
| cbct-vs-periapical | 84 | 69 | 70 | 61 | 57 | |
| bioceramic-vs-resin-sealer | 106 | 80 | 80 | 69 | 69 | |
| retreatment-vs-microsurgery | 128 | 80 | 100 | 68 | 67 | |
| direct-pulp-capping | 103 | 74 | 87 | 68 | 65 | |
| preemptive-nsaid | 79 | 66 | 70 | 62 | 61 | |
| regenerative-immature | 121 | 68 | 97 | 62 | 58 | |
| cracked-tooth-prognosis | 80 | 59 | 65 | 48 | 48 | |
| apdt-primary-molars | 42 | 27 | 36 | 21 | 21 | **YES** |
| bisphosphonates | 55 | 46 | 50 | 44 | 41 | |
| pregnancy | 38 | 31 | 34 | 27 | 27 | YES (already) |
| pips-vs-ultrasonic | 75 | 65 | 68 | 60 | 60 | |
| intentional-replantation | 33 | 28 | 23 | 22 | 21 | YES (already) |
| sdf-pulp-outcomes | 40 | 36 | 35 | 31 | 29 | **YES** |
| sonic-vs-ultrasonic | 40 | 38 | 34 | 32 | 32 | **YES** |
| dens-invaginatus | 94 | 69 | 70 | 53 | 53 | |
| diabetes-outcomes | 96 | 66 | 85 | 62 | 61 | |
| case-opening-sparse | 88 | 66 | 74 | 62 | 62 | |
| case-opening-full | 132 | 80 | 111 | 74 | 71 | |
| review-followup-immature-teeth | 52 | 45 | 47 | 40 | 40 | |
| review-newtopic-reset | 51 | 44 | 40 | 33 | 33 | **YES** |
| necrotic-virgin-tooth-young-adult-diagnostic | 40 | 39 | 26 | 26 | 24 | **YES** |
| bisphosphonate-extraction-vs-rct-thread | 101 | 71 | 84 | 66 | 62 | |
| dens-evaginatus-premolar-diagnostic | 40 | 37 | 35 | 32 | 29 | **YES** |
| dens-evaginatus-prevention-followup | 84 | 64 | 67 | 53 | 53 | |

`review-followup-immature-teeth` lands on exactly 40 — one paper from tripping
the guard. Treat it as inside the blast radius, not outside it.

---

## Why the threshold is the right call here, stated plainly

The two guards are **on different axes and only one of them has a rescue.**

`apply_evidence_floor` runs on **similarity**, before banding, and its rescue
branch tops the pool back up to 40 most-similar rows — the guard rule 28 calls
monotone, because it can only ever add papers back. The quality floor would run
on **score**, after banding, on the pool that rescue already produced. Nothing
tops it up again. So on a thin topic the sequence is: similarity floor guts the
pool → rescue restores it to exactly 40 → quality floor cuts it to 26 → and no
guard in the system notices, because `min_evidence_papers` was already
satisfied upstream by a different measurement.

That is how `necrotic-virgin-tooth-young-adult-diagnostic` goes 40 → 26 and
`apdt-primary-molars` goes 42 → 21. These are the sparse diagnostic questions —
the ones with the least literature, where A5's false evidence gap is
manufactured. **Applying a quality floor without giving it its own rescue would
cut hardest exactly where the corpus is thinnest.**

The design this needs, and did not get in a batch:

1. **Does the quality floor get its own rescue?** A `MIN_PAPERS_KEPT`-style
   top-up already exists inside `_apply_quality_threshold` (top up to 3 with
   the next most relevant) but it is **per tier**, not per answer, so eight
   tiers of 3 is not a 40-paper pool. An answer-level rescue is a new guard.
2. **Or does `min_evidence_papers` move to the end of the pipeline**, where it
   would police the pool that actually reaches Claude rather than an
   intermediate one? That is the cleaner shape and the larger change — it also
   changes the live path, which currently satisfies the guard at a different
   point.
3. **Or do the sparse questions route live instead?** Seven of the eight are
   thin-topic questions. "The library does not cover this well enough to serve
   at quality" is arguably the correct verdict, and the routing gate is where
   it belongs — but that trades papers for PubMed cost on every warm question
   in the demo set, which is a product decision.

Option 3 is the one I would put to RB first: it uses a gate that already
exists, on the axis the decision actually belongs to, and it fails in the safe
direction. But it changes cost on the demo path, and that is not a call to make
inside a batch at 09:00 on the day of a freeze.

## Status

**PARKED, measured, not shipped.** No production code changed by item 1.
The comment at `app.py:1189` is updated with this verdict so the next reader
finds the 29-question number and not just the corpus one.
