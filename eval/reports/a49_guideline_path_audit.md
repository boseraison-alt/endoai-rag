# A49 phase 0 — guideline path audit

Measure only; nothing was changed by this audit. Run:
`python scripts/audit_guideline_path.py --json out.json`
207 stored answer surfaces (`learn_history/`, `answers/`, `query_cache`),
3,208 library rows, the 60-entry verified manifest at `data/guidelines_seed.json`.

---

## A4 — `impact_factor` IS read, and it reaches the model

**Scoring and ranking do NOT read it.** `score_paper` uses the impact-factor
term only under `USE_IMPACT_FACTOR`, which defaults false and is asserted false
by `tests/test_no_journal_weighting.py` (which sweeps the term and shows the
score does not move). There is **no `ORDER BY impact_factor`, no sort key, no
cap** anywhere — grepped.

**But synthesis reads it.** `endo_ai.py:4743`, inside `_build_evidence_context`:

```python
jif = f", IF={p['impact_factor']}" if p.get('impact_factor') else ""
```

That string is appended to the "Top paper per tier" block, and that block is
sent to Claude on **all four answer paths**:

| caller | line | path |
|---|---|---|
| `ask_clinical_question` | 7595 | Literature |
| `ask_learn_question` | 7826 | Curriculum |
| `write_curriculum_module` | 8430 | Curriculum, per module |
| `ask_case_question` | 10071 | Case |

So the model is told each top paper's journal impact factor. Invariant 22 says
*"No journal-identity signal in scoring or ranking. Venue is metadata and
Cochrane-verification only."* The letter of it is kept — nothing ranks by IF —
but a journal-identity signal is being handed to the synthesiser, which is the
same class of influence one step later.

**1,572 of 3,208 rows (49.0%) carry a stored `impact_factor`**, so this fires on
roughly half of all evidence.

**Verdict: A49 is BOTH a data fix and a retrieval fix.** Removing the hardcoded
8.0 values is not sufficient — the read at 4743 has to go too, or the next
ingest path reintroduces the signal.

---

## The other headline — 103 stored answers cite a record matching no real document

**A2**, matching by organisation + subject + year against the manifest, never by
slug:

| verdict | n |
|---|---|
| verified match to a real document | **4** |
| WRONG YEAR — no such edition exists | **6** |
| NO SUCH DOCUMENT on that subject in a 60-entry manifest | **6** |

Every one of the 16 is stored at `level_key='guideline'`, score **90.0** (AAE) or
**87.0 / 50.4** (ESE), `impact_factor` **8.0 / 4.5**.

| slug | score | IF | cited in | verdict |
|---|---|---|---|---|
| AAE-PS-antibiotics | 90.0 | 8.0 | 6 | wrong year — stored 2023; real is AAE-ANTIBIOTICS-2017 (under_review) |
| AAE-PS-cbct | 90.0 | 8.0 | 12 | wrong year — stored 2021; real are 2025 (current), 2015 (superseded) |
| AAE-PS-cracked-tooth | 90.0 | 8.0 | 3 | **no such document** |
| AAE-PS-diagnosis | 90.0 | 8.0 | 11 | matches AAE-DIAGNOSIS-2009 (current) |
| AAE-PS-implant-v-endo | 90.0 | 8.0 | 9 | **no such document** |
| AAE-PS-isolation | 90.0 | 8.0 | 4 | **no such document** |
| AAE-PS-microscope | 90.0 | 8.0 | 7 | wrong year — stored 2012; real is 2020 |
| AAE-PS-obturation | 90.0 | 8.0 | 9 | **no such document** |
| AAE-PS-regenerative | 90.0 | 8.0 | 6 | wrong year — stored 2021; real are 2025, 2013 |
| AAE-PS-retreatment | 90.0 | 8.0 | 12 | **no such document** |
| AAE-PS-safety | 90.0 | 8.0 | 7 | **no such document** |
| AAE-PS-trauma | 90.0 | 8.0 | 1 | wrong year — stored 2020; real is 2026 |
| AAE-PS-vital-pulp | 90.0 | 8.0 | 9 | matches AAE-VPT-2021 (current) |
| ESE-PS-VPT-2019 | 87.0 | 4.5 | 22 | matches ESE-DEEPCARIES-2019 — **but its stored title is "Outcome of Primary Root Canal Treatment", which is neither VPT nor deep caries: the record disagrees with its own slug** |
| ESE-QG-2006 | 50.4 | 4.5 | 4 | id is in the manifest (superseded) |
| ESE-QG-2023 | 87.0 | 4.5 | 27 | wrong year — **there is no 2023 ESE Quality Guideline.** The 2023 document is ESE-S3-2023, a differently-named S3 guideline (PMID 37772327) |

The handover's two named suspects are both confirmed: `ESE-QG-2023` names a
document that does not exist, and `AAE-PS-cbct` is dated to a year with no
edition.

---

## A1 — withdrawn Cochrane reviews

**None of the three is in the library.**

| CD | topic | in library |
|---|---|---|
| CD007997 | post-endodontic pain | no |
| CD005408 | root fracture | no |
| CD004623 | posts | no |

Searched by title and abstract text (`endo_papers_rag` has no `doi` column).
Zero stored answers cite them. **G1 is therefore prospective protection, not a
cleanup** — nothing is contaminated today, and the gate exists so that the next
ingest cannot introduce one.

---

## A3 — score contamination

```
  guideline rows   n=16     min 50.4   max 90.0
  evidence rows    n=3192   min  7.4   max 85.9   mean 55.0
```

**The severity number: a guideline row at 90.0 outranks 100% of the 3,192
evidence rows.** Not a majority — all of them. There is no real paper in the
library scoring 90 or above; the maximum any genuine study achieves is 85.9.

Thirteen of the sixteen sit at exactly 90.0.

| named comparison | score |
|---|---|
| a hardcoded AAE position statement | **90.0** |
| Coll 2025 (level1) | 80.0 |
| Schwendicke Cochrane (level1) | 79.4 |

Even the *lowest* guideline row (ESE-QG-2006 at 50.4, the only one that was
scored rather than hand-set) outranks 986 of 3,192 evidence rows (30.9%).

Note the tier is `level_key='guideline'`, not `level1` as the handover's reading
of the source suggested — so the tier taxonomy is not itself contaminated. The
contamination is entirely in `score`, which is the field that orders papers
*within* a tier and drives the "Top papers by evidence score" surface.

---

## A5 — bare-key leaks

```
  citation slots scanned across 207 stored answers   26,172
  slots holding a NON-PMID identifier                   471
  of those, resolving to a REAL LIBRARY ROW             432   across 16 keys
  not library keys (ordinary parentheticals, etc.)       39   across 10
```

**432, not two.** The two the handover named are the largest but far from alone:

| identifier | slots | documents |
|---|---|---|
| ESE-QG-2023 | 69 | 27 |
| ESE-PS-VPT-2019 | 63 | 22 |
| AAE-PS-cbct | 55 | 12 |
| AAE-PS-retreatment | 41 | 12 |
| AAE-PS-vital-pulp | 33 | 9 |
| AAE-PS-diagnosis | 31 | 11 |
| AAE-PS-safety | 27 | 7 |
| AAE-PS-implant-v-endo | 25 | 9 |
| AAE-PS-obturation | 23 | 9 |
| …6 more slugs | 51 | |

All 16 slugs leak. The 39 remaining slots are my slot regex sweeping up ordinary
hyphenated parentheticals — `(CBCT-measured)`, `(MTA-Angelus)`, `(DG-16)` — plus
12 instances of the literal placeholder `N` from `[[PMID:N]]` in prompt
documentation. Those are not defects and are excluded from the 432.

---

## Instrument errors made and corrected while running this audit

Recorded because rule 33 was added yesterday for exactly this, and it happened
three more times today.

1. **First A2 matcher** scored title overlap at ≥3 shared words. Titles here are
   mostly organisation boilerplate ("AAE Position Statement:"), so it matched
   everything against everything — it paired `AAE-PS-trauma` with
   `AAE-MICROSCOPES-2020` and `ESE-QG-2023` with `ESE-RESORPTION-2023`.
2. **The correction over-corrected.** Stripping "quality / consensus / report"
   as boilerplate left `ESE-QG-2006` with no content words, so it failed to match
   its own verbatim id in the manifest.
3. **A subject key that was too generous.** `AAE-PS-safety` matched
   `AAE-CASEDIFFICULTY-2022` because "difficulty" and "standards" were in its
   keyword list. Different document.

The shipped version uses **three independent signals** — verbatim id, subject +
organisation, then year — and reports which one decided, rather than collapsing
them into one fuzzy score that hides what fired.
