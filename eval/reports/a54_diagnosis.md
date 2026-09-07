# A54 — the diagnosis table, and what it overturns

Question: *MTA versus bioceramic as retrograde filling after apicoectomy.*
Terms frozen in `eval/logs/a54_terms.json` (rule 38), so every arm and every
re-run measures the change and not the generator's variance.

The generator produced three AND-groups:

```
g0  MTA | mineral trioxide aggregate | bioceramic* | bioactive ceramic* | calcium silicate
g1  apicoectomy | apical surgery | surgical endodontics | periapical surgery
g2  retrograde filling | retrograde seal* | apical plug | root-end filling
```

---

## 1. THE QUESTION NEVER WENT TO PUBMED

```
[rag_gate] hits=200>=20 PASS | relevant=200>=12 PASS | high_tier=True PASS
           | newest=2026 age=0y<=3 PASS | concepts>=3 PASS
[rag_gate] -> LIBRARY
```

**No lane query ran.** The pool came from `multi_query_search` — embedding
similarity over the library, capped at 25 per tier with no per-tier quality
floor.

**And none of the eight fixtures is in the library.** 0 of 8.

So the fixtures were not lost to ranking, to a cap, or to a lane filter on
this question. They were never candidates, because the corpus does not hold
them and the gate decided the corpus was sufficient.

**The gate's own numbers say why it was wrong.** It counted 118 library papers
mentioning the material concept, but only **28** mentioning the surgery
concept and **31** the retrograde-filling concept. `min_concept_papers` is 3,
so 28 and 31 pass comfortably — and the gate concluded "covered" over a
library holding **zero** of the head-to-head trials that define the question.
This is the A5 false-gap class running in reverse: a **false coverage
declaration**.

## 2. THE LANE TABLE — what WOULD happen if it went live

Run anyway, because the fixtures must be reachable at all for any later fix
to matter. `<lane query> AND <pmid>[uid]`:

| fx | pmid | matched by | verdict |
|---|---|---|---|
| F1 | 31078325 | none | query cannot express it |
| F2 | 27986096 | none | query cannot express it |
| F3 | 34499889 | level3a, level3b, observational | **query matches** — lost to ranking/cap |
| F4 | 38430316 | none | query cannot express it |
| F5 | 42634020 | level3a | **query matches** — lost to ranking/cap |
| F6 | 42004800 | none | topic matches, but `Journal Article` only — no tier admits it |
| F7 | 41555359 | none | query cannot express it |
| F8 | 38849637 | none | query cannot express it |

Domain filter: **passes every one of the eight.** Not a domain-filter
exclusion. No date or species guard fired.

## 3. WHICH GROUP FAILS — and it is not the one the spec named

Each group tested alone against each missed fixture:

| fx | g0 material | g1 surgery | g2 filling |
|---|---|---|---|
| F1 | MATCH | **no** | MATCH |
| F2 | MATCH | **no** | MATCH |
| F4 | MATCH | **no** | MATCH |
| F7 | MATCH | **no** | MATCH |
| F8 | MATCH | **no** | MATCH |
| F6 | MATCH | MATCH | MATCH |

**The material group matches every single one.** The surgery group is the sole
point of failure in all five.

So **fix candidate 1 as written — material nomenclature expansion (*root
repair material*, *RRM*, *iRoot BP Plus*, *TotalFill*, *NeoPUTTY* …) — would
recover NONE of them.** `MTA` and `bioceramic*` already match unquoted across
title, abstract and MeSH; the titles saying "Root Repair Material" are found
by the material group anyway.

The missing vocabulary is the **procedure**. Candidate terms tested:

| candidate | F1 | F2 | F4 | F7 | F8 |
|---|---|---|---|---|---|
| `"endodontic microsurgery"` | YES | YES | YES | YES | – |
| `"root-end surgery"` | – | – | – | – | YES |
| `"apical microsurgery"` | – | – | – | – | – |
| `"periradicular surgery"` | – | – | – | – | – |
| `"endodontic surgery"` | – | – | – | – | – |

**One term — `"endodontic microsurgery"` — recovers four of the five.**

## 4. SNOWBALLING (fix 2), measured

Reference lists via `pubmed_reference_pmids`:

| review | in the pool? | refs known | fixtures inside |
|---|---|---|---|
| 34647617 Cochrane 2021, *Materials for retrograde filling* | **YES** | 74 | **F1, F2** |
| 40637350 Ibáñez-Aravena 2025 | no (in library, not in pool) | **0** | none |

The second review publishes **no reference list PubMed can see**, so it
contributes nothing — a limit of the mechanism worth stating rather than
discovering later.

**Snowballing is the only one of the three candidates that works on the route
this question actually takes.** The term fix changes lane queries, and no lane
ran. 24 cochrane/level1 reviews are already in this pool, so the mechanism has
a rich source here.

## 5. PRECISION, before

| | |
|---|---|
| papers in the pool | 66 |
| on topic (names root-end / retrograde / apicoectomy / apical surgery / …) | 30 |
| **off topic** | **36** |
| **off-topic share** | **55%** |

The off-topic set is exactly the complaint: apexification (25467231, 26911724,
22838228), pulpotomy in primary molars (15858300), revascularisation
(27805884, 28822564), obturation and sealers (38963396, 27599002, 37085142),
crowns on root-filled teeth (26403154), and *"The Endodontic Space"*
(36833161).

**They came from the library route's embedding similarity, not from a
broadened lane.** Tested directly: none of them matches the strict level1 lane
query, and none matches the broadened one either. "MTA in apexification" is
simply embedding-near "MTA as a root-end filling".

Broadening was checked and exonerated: for this query it drops the TRAILING
group (g2), keeping material AND surgery, and the resulting query still
excludes every off-topic paper listed above.

---

## Predictions vs measurement

| # | prediction | measured | verdict |
|---|---|---|---|
| 1 | F1, F2, F3 are vocabulary misses | F1, F2 yes; **F3 matches three lanes** | **wrong by class on F3** — it was a ranking loss, not vocabulary |
| 1b | the miss is the MATERIAL group lacking *root repair material* | the material group matches all five; **the SURGERY group is the sole failure** | **wrong by class**, and it is the spec's own fix-1 premise that fails with it |
| 2 | F6 is an untyped-recent miss | `Journal Article` only, topic matches, no tier admits it | correct |
| 3 | F7: level1 MATCHES it, lost to ranking (contradicting the spec's "excluded as invitro") | level1 *pubtype filter* matches, but the **topic** does not — neither the spec nor I were right | **both wrong** |
| 4 | off-topic share > 50% | 55% | correct |
| 5 | snowballing recovers at least F1, F2, F3 | F1, F2 only; F3 is not in either list, and the second review has no list at all | **partly wrong** |
| 6 | at least one lane ran the material group alone | **no lane ran at all** — the question routed to the library | **wrong by class**, and the reframing is the finding |

## What this decides

Ship **snowballing** first, as the spec ordered — but for a reason neither of
us gave: it is the only candidate that is **route-independent**, and this
question takes the library route.

Then the term fix, retargeted from the material group to the **procedure**
group, so the fixtures are reachable when a question does go live.

Fix 3 (subject AND material in every lane) is **not needed**: every study lane
already ANDs all three groups, and the guideline lane's narrowing to the
subject group is item B's deliberate design.
