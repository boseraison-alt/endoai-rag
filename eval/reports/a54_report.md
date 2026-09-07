# A54 — retrieval fixtures: MTA versus bioceramic as retrograde filling

Second competitor-comparison fixture set. Suite **2767 passed, 0 failed**.
Cost **$2.99**, of which $2.95 is the one authorised synthesis and its retry.

---

## Per fixture

| # | verified PMID | paper | diagnosis | recovered by |
|---|---|---|---|---|
| F1 | **31078325** | Safi 2019, J Endod | no lane matches — **surgery group** fails | **not recovered** |
| F2 | **27986096** | Zhou 2017, J Endod | no lane matches — surgery group fails | **not recovered** |
| F3 | **34499889** | Bliggenstorfer 2021, J Endod | matches level3a/3b/observational — **ranking/cap** | **not recovered** |
| F4 | **38430316** | Dong 2024, Clin Oral Investig | no lane matches — surgery group fails | **not recovered** |
| F5 | **42634020** | Hussain 2026, Clin Oral Investig | matches level3a — ranking/cap | **not recovered** |
| F6 | 42004800 | El Marakby 2026, JCDE | topic matches; `Journal Article` only — no tier admits it | not recovered |
| F7 | 41555359 | Hattab 2026, BMC Oral Health | no lane matches — surgery group fails | not recovered |
| F8 | 38849637 | Knapp 2024, Clin Oral Investig | no lane matches — surgery group fails | not recovered |

**The done-when is NOT met.** F1–F5 do not reach the pool on any run, and no
candidate in the item's fix menu can put them there. The reason is measured,
not inferred:

- **The question routes to the LIBRARY** (`[rag_gate] -> LIBRARY`). No lane
  query runs, so no term or lane fix touches this question at all.
- **None of the eight fixtures is in the library.** 0 of 8. They were never
  candidates on this route.
- Snowballing is the only route-independent candidate, and it recovers them
  only when a review that (a) is in the pool, (b) is nominated, and (c)
  publishes a reference list carries them. Across four runs the nominated
  review was 29681480, 20614042, 39455597 and others — **the Cochrane review
  that carries F1 and F2 was nominated on none of them.**

## Precision, before → after

| | before | after |
|---|---|---|
| papers in the pool | 66 | 82 |
| on topic | 30 | 39 |
| **off topic** | 36 | 43 |
| **off-topic share** | **55%** | **52%** |

Unchanged within noise. The off-topic set is the complaint verbatim:
apexification (25467231, 26911724, 22838228), pulpotomy in primary molars
(15858300), revascularisation (27805884, 28822564), obturation and sealers
(38963396, 27599002, 37085142), crowns on root-filled teeth (26403154), and
*"The Endodontic Space"* (36833161).

**They did not come from a broadened lane.** Tested directly: none matches the
strict level1 query, and none matches the broadened one. They come from the
library route's **embedding similarity** — "MTA in apexification" is simply
embedding-near "MTA as a root-end filling". Broadening was checked and
exonerated: it drops the trailing group, keeping material AND surgery.

## Lane structure — fix 3 is not needed

Every study lane ANDs all three groups. No lane runs the material group alone.
The guideline lane's narrowing to the subject group is item B's deliberate
design.

## The specialty block

| | before | after |
|---|---|---|
| guidelines in the block | 1 (ESE-S3-2023) | **3** |

All three reached the model's context — verified directly, not assumed:
`37772327` is in the guideline block's `text` and in the 148,867-character
evidence context. **The 26% context fix held.**

The answer used two of the three:

> **Specialty Guidelines & Position Statements**
>
> - **AAE (2018) — Treatment Standards** (current, US) — pointer record; read
>   at the AAE website. Position not quoted
>   [GL:AAE-TREATMENTSTANDARDS-2018 · AAE — Treatment Standards White Paper
>   (with 2019 Executive Summary) (2018; current; US)].
> - **FDS RCS (2020) — Periradicular Surgery guideline** (current, UK) —
>   pointer record; read at the RCS Faculty of Dental Surgery site. Position
>   not quoted [GL:FDSRCS-PERIRADICULAR-2020 · FDSRCS — Periradicular Surgery
>   (2020; current; UK)].

Two jurisdictions, each labelled, **neither blended** — and both correctly
declared as pointer records rather than having a position invented for them.
**ESE-S3-2023 is absent from the section although it was in the block, in the
text and in the context**, and it is the only one of the three with stored
text. That is a synthesis choice, not a retrieval failure, and the done-when
asking for three jurisdictions each stated from stored text is **not met**.

---

## Predictions vs measurements

| # | prediction | measured | wrong by |
|---|---|---|---|
| 1 | F1, F2, F3 are vocabulary misses | F1, F2 yes; **F3 matches three lanes** | **class** |
| 1b | the gap is the MATERIAL group | the material group matches **all five**; the **surgery** group is the sole failure | **class** — and it is the item's own fix-1 premise |
| 2 | F6 is an untyped-recent miss | `Journal Article` only, topic matches | correct |
| 3 | F7: level1 matches, lost to ranking (vs the item's "excluded as invitro") | level1 *pubtype* matches but the **topic** does not | **both wrong** |
| 4 | off-topic share > 50% | 55% | correct |
| 5 | snowballing recovers ≥ F1, F2, F3 | recovers **F1, F2 only when that review is nominated** — it was not, on any run | **count and class** |
| 6 | a lane ran the material group alone | **no lane ran at all** | **class** |
| 7 | scope match is the cause of the 1-of-3 guidelines | correct, and FDSRCS needed **scope-matched admission**, not the flagship rule | correct |
| 8 | a pulpotomy question must not admit FDSRCS | holds | correct |

Six of nine wrong, five of them by class.

## Tests

`tests/test_a54_snowball_and_scope.py`, 14 tests. Four mutations, all caught —
**after two of them escaped the first version**, because those tests read
source instead of running it:

| mutation | result |
|---|---|
| scope synonyms disabled | 2 failed |
| admission reverted to flagships only | 1 failed *(only once the source-shape test was replaced by one driving `admit_scoped_guidelines`)* |
| an underivable reference defaulted onto `level5` | 1 failed *(only once replaced by a stubbed run)* |
| snowball reads top-N by score again | 1 failed |

## Found, not fixed

| severity | finding |
|---|---|
| **HIGH** | **A false coverage declaration.** The gate passed this question to the library on 200 hits while the library held **zero** of the head-to-head trials. Its own numbers show the imbalance it did not act on: **149 papers matched the material concept, 24 the surgery concept.** `min_concept_papers` is 3, so 24 passes comfortably. A gate that counted the *weakest* concept rather than the count of concepts above 3 would have gone live here. This is the A5 false-gap class in reverse, and it is the actual cause of the miss. Changing it is a retrieval-gate change needing its own A/B and RB's sign-off (standing decision). |
| **HIGH** | **The fixtures are not in the library.** The standing practice makes a missed paper a regression fixture; it does not put the paper in the corpus. Until F1–F5 are ingested, no library-routed question can cite them. |
| MEDIUM | **Snowballing is hostage to PubMed's reference linkage.** Of the reviews nominated across four runs, **most published no reference list at all** (0 refs). The mechanism is correct and fires; its yield is not something the code controls. |
| MEDIUM | **The term gap is real but unreachable from here.** `"endodontic microsurgery"` alone recovers F1, F2, F4 and F7 from the lane queries; `"root-end surgery"` recovers F8. Adding them to the generator is fix 1 done correctly — targeted at the **procedure**, not the material — but it changes only the live route, and per rule 38 it needs the full A/B on the 29 before adoption. Not shipped tonight. |

## Recommendation

The measured order is the reverse of the item's. The binding constraint is the
**corpus and the routing gate**, not the query:

1. **Ingest F1–F5** (a corpus fix; the standing practice already makes them
   fixtures).
2. **Make the coverage gate read its weakest concept**, with its own A/B.
3. Then the procedure-synonym term change, for questions that do go live.
