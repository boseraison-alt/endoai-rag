# A46a — what the v7 re-baseline should show, written before it runs

**Committed before `--update-baseline`. Anything that moves and is not predicted
here is the signal — that is the whole point, and it is the only way a
re-baseline is a test rather than a rubber stamp.**

`baseline_v6` was recorded **2026-08-31**, before A5b, A30b, A31, A7, A33c, A42
and A34c. It is stale by a large factor, and the direction is not uniform: some
cases should go sharply **up** and some sharply **down**, for different reasons.

---

## 1. What changed, and which metric each thing moves

| change | date | what it does to a retrieval-only run |
|---|---|---|
| **A5b / A30b** membership by relevance | 09-02/03 | **papers UP**, ~3.2× on library-routed cases — the biggest single effect, and it is *already* in the A35k column below |
| **A31** observational tier | 09-03 | **papers UP** on live cases; a new `observational` key appears in `per_tier` |
| **A7** guideline banding | 09-03 | `per_tier` shifts: level1 **down** ~21 rows across the corpus, new `guideline` key |
| **A42** evidence floor 0.60 + 40-paper guard | 09-03 | **papers DOWN**, library route only |
| **A34c** +92 AEJ rows | 09-03 | **papers UP slightly** where AEJ is on topic |
| **A33c** +1 Cochrane row | 09-03 | ~nothing: similarity 0.505, below the floor for its own fixture |
| A32, A33h-i, A38, A45, A22, A41b | 09-03 | **no effect on a retrieval-only run** — deleted dead code, live-path relaxation that fires under 5 hits, synthesis prompt text, a synthesis gate, answer rendering, and a lexicon that ships disabled |

## 2. Library-route cases — the floor applies, and the numbers are specific

The A35k candidate sets give the pool per question, so this is a number, not a
direction. **`predicted` is a floor**: those sets were collected before A34c
added 92 AEJ rows.

| case | v6 | post-A30 (A35k) | **predicted** | guard |
|---|---|---|---|---|
| sonic-vs-ultrasonic | 19–36 | 115 | **40** | ✔ |
| review-followup-immature-teeth | 20–29 | 140 | 66 | |
| bisphosphonate-extraction-vs-rct | *not in v6* | 133 | 65 | |
| cbct-vs-periapical | 33–37 | 119 | 71 | |
| bioceramic-vs-resin-sealer | 37–40 | 100 | 59 | |
| necrotic-virgin-tooth-young-adult | *not in v6* | 141 | 100 | |
| pips-vs-ultrasonic | 29–35 | 102 | 64 | |
| diabetes-outcomes | 33–42 | 97 | 63 | |
| review-newtopic-reset | 31–37 | 81 | 48 | |
| dens-evaginatus-prevention-followup | *not in v6* | 116 | 85 | |
| laser-root-canal-disinfection-library | 33–34 | 118 | 93 | |
| single-vs-multiple-visit | 36–41 | 120 | 96 | |
| dens-evaginatus-premolar-diagnostic | *not in v6* | 56 | **40** | ✔ |
| preemptive-nsaid | 40–43 | 86 | 73 | |
| regenerative-immature | 37–39 | 127 | 117 | |
| mta-vs-biodentine-pulpotomy | 34–35 | 123 | 116 | |
| naocl-concentration | 37–38 | 75 | 69 | |
| direct-pulp-capping | 35–35 | 110 | 110 | |

**Every library case should rise sharply against v6** — roughly 1.6×–3× — because
the membership fixes outweigh the floor. `direct-pulp-capping` is the extreme:
35 → ~110.

### The guard-bound cases, named as A46a requires

Two library-route cases have too few papers above 0.60 and take the
`min_evidence_papers` top-up, so they should report **exactly 40**:

- **sonic-vs-ultrasonic**
- **dens-evaginatus-premolar-diagnostic**

Four more were guard-bound in the A35k measurement but are **live-routed** in the
eval, so the guard cannot fire on them and they must *not* report 40:
`dens-invaginatus`, `case-opening-sparse`, `pregnancy`, `sdf-pulp-outcomes`.
**If any of those reports exactly 40, the floor has leaked onto the live path** —
that would be a real defect and the most valuable thing this run could find.

## 3. Live-route cases — the floor does NOT apply

`apply_evidence_floor` is in the library branch only. These eleven go through
`fetch_papers`, per-tier quotas and NCBI:

`apdt-primary-molars` · `bisphosphonates` · `case-opening-full` ·
`case-opening-sparse` · `cracked-tooth-prognosis` · `dens-invaginatus` ·
`intentional-replantation` · `laser-root-canal-disinfection-live` · `pregnancy` ·
`retreatment-vs-microsurgery` · `sdf-pulp-outcomes`

Predicted: **up modestly** from A31's observational tier and A34c, and otherwise
noisy. A14 is the dominant term here — live counts move up to 3× between runs on
the same question purely from term generation, which is why v6's own ranges are
so wide (`case-opening-sparse` 171–220, `cracked-tooth-prognosis` 30–94).
**No live case's movement should be attributed to anything without three runs
agreeing.**

## 4. `per_tier` — two structural changes

- a **`guideline`** key appears where level1 rows were rebanded (A7)
- an **`observational`** key appears on live cases (A31)

Neither existed when v6 was recorded, so their absence in v6 is not a fall to
zero.

## 5. What would surprise me

Written down so it cannot be rationalised afterwards:

1. **A live case reporting exactly 40 papers** — the floor leaking off the
   library branch.
2. **A library case going DOWN against v6.** The floor cuts ~33%, the membership
   fixes add ~220%; down would mean a membership fix regressed.
3. **`direct-pulp-capping` not landing near 110.** It is the one case where the
   floor removes nothing (A42a measured 110 → 110), so it isolates the
   membership fixes from the floor.
4. **`search_terms` or `hits_per_query` moving on library cases.** Nothing this
   session touched term generation on that route — the lexicon ships disabled
   (`reviewed_by_rb: false`). If they move, either the lexicon is live when it
   should not be, or A14 is larger than believed.
5. **A route flip.** The routing floor and `min_relevant` were deliberately left
   at 0.55/12 (rule 26). Any case changing route means the gate moved when it
   was not supposed to.
6. **`esearch_empty` rising on live cases** — A33h-i changed which group
   relaxation drops. It fires only under 5 hits, so it should be rare, but a
   rise would mean it is firing more than expected.

## 6. Method

Three runs, serial (rule 9), Curo's own server stopped first. v5 and v6 both
kept. Outcome committed beside this file, with each moved case marked
**predicted** or **unpredicted** — and the unpredicted ones are the finding.
