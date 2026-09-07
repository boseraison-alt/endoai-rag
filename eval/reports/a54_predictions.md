# A54 — predictions, committed before the diagnosis

Second competitor-comparison fixture set (the first was VPT: Sulaiman /
Komora / EFCD). Question: *MTA versus bioceramic as retrograde filling after
apicoectomy.*

## Fixtures, verified against PubMed before anything else

| # | PMID | paper | verified |
|---|---|---|---|
| F1 | **31078325** | Safi C, J Endod 2019 — MTA vs RRM root-end, RCT with CBCT | journal/year/author all match |
| F2 | **27986096** | Zhou W, J Endod 2017 — MTA vs iRoot BP Plus, RCT | match |
| F3 | **34499889** | Bliggenstorfer S, J Endod 2021 — periapical surgery in molars, 424 teeth | match |
| F4 | **38430316** | Dong X, Clin Oral Investig 2024 — iRoot BP Plus + iRoot SP, RCT | match |
| F5 | **42634020** | Hussain O, Clin Oral Investig 2026 — outcome and erosion, ≥4 yr | match |
| F6 | 42004800 | El Marakby MF, J Conserv Dent Endod 2026 — guided vs non-guided microsurgery | resolves; `Journal Article` only |
| F7 | 41555359 | Hattab A, BMC Oral Health 2026 — premixed vs manually mixed bioceramic | resolves; `Systematic Review, Meta-Analysis` |
| F8 | 38849637 | Knapp J, Clin Oral Investig 2024 — ex vivo, premixed putty | resolves; `Journal Article` only |

**The Hoang 2026 rule earned its keep twice.**

1. My first search used the full title as a `[Title]` phrase and returned
   **zero candidates for all five** of F1–F5. Reporting "not resolved" from
   that would have been the verification step failing in exactly the way it
   exists to prevent. Author + one distinctive title word resolves all five.
2. F4's author has a **2023 in-vitro paper on the same materials** (36746820).
   Taking the first hit would have pinned the wrong study.

## The two "retrieved but not cited" papers — the spec's hypothesis is FALSE

Neither is a root-end filling trial, so neither is a synthesis miss:

- **37815804** — *"Outcome of single-visit root canal treatment with or
  without MTAD"*, Int Endod J 2024. MTAD is an **irrigant**. Nothing to do
  with retrograde filling.
- **42063099** — *"Endodontic treatment outcomes in apical periodontitis
  cases by the lateral condensation versus warm vertical condensation"*,
  BMC Oral Health 2026. **Obturation technique**, not root-end filling.

The model was right not to cite either. They are evidence for the PRECISION
problem — off-topic papers sitting at the top of the RCT/SR tier — not
against the synthesis. **Predicted consequence: the 26% context fix does not
need re-checking here, because there is no synthesis miss to explain.**

## Predictions, before the diagnosis table

1. **F1, F2, F3 are vocabulary misses.** Their titles say *Root Repair
   Material* / *periapical surgery*, not *bioceramic*. Predicted: the lane
   query does NOT match them (`0` hits on `<lane query> AND <pmid>[uid]`).
2. **F6 is an untyped-recent miss** — `Journal Article` only, so no tier
   filter admits it; the provisional lane is its only route.
3. **F7 may be excluded as a lab review.** It IS typed
   `Systematic Review, Meta-Analysis`, so predicted: level1 MATCHES it and it
   was lost to ranking or the cap, not to the query. This contradicts the
   spec's guess that it was excluded at lane level, and is stated so the
   table can overturn one of us.
4. **Precision: fewer than half** of the 122 retrieved mention root-end /
   retrograde / apicoectomy / apicectomy / apical surgery / periradicular
   surgery / endodontic microsurgery.
5. **Snowballing (fix 2) recovers at least F1, F2, F3** from the reference
   lists of 34647617 and 40637350. If it does, ship it first — additive and
   deterministic.
6. **At least one lane ran the material group without the subject group.**
   If every lane ANDs subject with material, fix 3 is unnecessary and the
   drift is ranking, not query structure.

## Specialty block

7. Three guidelines cover apical surgery — ESE-S3-2023 (EU),
   AAE-TREATMENTSTANDARDS-2018 (US), FDSRCS-PERIRADICULAR-2020 (UK). Only
   ESE-S3-2023 appeared. Predicted cause: the scope match is word-bounded and
   literal, so *apicoectomy* in the question does not hit a scope term reading
   *apical surgery*. `SCOPE_SYNONYMS` should admit all three.
8. Negative pin: a pulpotomy question must **not** admit FDSRCS.
