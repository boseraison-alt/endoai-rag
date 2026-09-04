# Detector audit — the instrument was wrong, not the corpus

> **The class:** a detector whose hard-coded token shape the corpus does not
> actually emit fires ZERO times, and a zero looks exactly like a clean bill of
> health. This is the fourth time in this project a measurement instrument was
> wrong rather than the thing it measured.

Run: `python scripts/audit_detectors.py --json out.json`
Corpora: **199 stored answers** (`learn_history/*.json`, `answers/*.txt`,
`query_cache`) and **3,061 stored abstracts** (`endo_papers_rag`).
**82 detectors audited** — 63 compiled patterns and 19 pure-text functions.

---

## 1. The defect that started it

`scan_split_items.py` looked for a bare list number:

```python
ORPHAN_NUM = re.compile(r"^(\d{1,2})\.\s*$", re.M)      # what it looked for
```

The corpus writes the number **bold**:

```
**3.**

> ⚠ **NOT FROM THE EVIDENCE BASE — UNVERIFIED**
> …
> Administer local anaesthesia**
```

| | orphaned list numbers | bold runs cut |
|---|---|---|
| bare `N.` (the shipped scan) | **0** | — |
| `(?:\*\*)?N\.(?:\*\*)?` (corrected) | **30 of 114** | **24 of 114** |

On that zero, A22a and the literal `**` leak were filed as *renderer* defects
and moved to the browser lane. They are text-layer defects in
`quarantine_unsourced_content`, and they are item 4.

## 2. The audit harness reproduced the same bug on its first run

The first sweep reported **15 unjustified zeros**. Twelve were line-anchored
patterns compiled *without* `re.MULTILINE` — `_LIST_ITEM_RE`, `_TABLE_ROW_RE`,
`_HRULE_RE` and friends — which production applies **one line at a time**. A
whole-document `findall` on `^…` can only ever return 0.

The instrument built to find the class manufactured the class. Corrected: a
pattern is now applied the way production applies it, and `applied_as` is
reported so nobody re-derives it.

**13 detectors were reported as zero by the naive instrument and are non-zero
under the corrected one:**

| detector | naive | corrected | why the naive count was 0 |
|---|---|---|---|
| `_LIST_ITEM_RE` | 0 | **4,710** | line-anchored, no `re.M` |
| `_LIST_MARKER` | 0 | **4,710** | line-anchored, no `re.M` |
| `_HRULE_RE` | 0 | **1,720** | line-anchored, no `re.M` |
| `_TABLE_ROW_LINE` | 0 | **1,628** | line-anchored, no `re.M` |
| `_TABLE_ROW_RE` | 0 | **1,626** | line-anchored, no `re.M` |
| `_INLINE_LABEL_RE` | 0 | **631** | line-anchored, no `re.M` |
| `_DTREE_OPEN_RE` | 0 | **610** | line-anchored, no `re.M` |
| `_TABLE_SEP_RE` | 0 | **155** | line-anchored, no `re.M` |
| `_DIRECTIVE_IMPERATIVE_RE` | 0 | **133** | line-anchored, no `re.M` |
| `_AUTHOR_ASSERTS_RE` | 0 | **94** | line-anchored, no `re.M` |
| `_NON_ABSTRACT_BLOCK_RE` | 0 | **3** | wrong corpus *and* line-anchored |
| `_STUDY_UNIT_RE` | 0 | **2** | wrong corpus *and* line-anchored |
| `_TRAILING_BRACKET_RE` | 0 | **2** | `$`-anchored, no `re.M` |

## 3. The second instrument error: the wrong corpus

Thirteen patterns never see an answer — they read an **abstract** (COI
statements, in-vitro cues, sample-size idioms, PROSPERO ids). Scoring them
against the answer corpus proves nothing, and the first pass called their zeros
"justified" *on that basis* — the same unexamined pass the split-item scan got.

They are now audited against 3,061 real abstracts, and **every one fires**:

| detector | on abstracts |
|---|---|
| `_REVIEW_DESIGN_RE` | 2,124 |
| `_EVIDENCE_DESCRIPTION_RE` | 1,489 |
| `_REVIEW_TOTAL_RE` | 386 |
| `_INVITRO_STRONG_RE` | 350 |
| `_INVITRO_WEAK_RE` | 295 |
| `_PROSPERO_RE` | 139 |
| `_COI_NEGATION_RE` | 98 |
| `_COI_CUE_RE` | 32 |
| `_COI_AFFIRMATIVE_RE` | 7 |
| `_NON_ABSTRACT_BLOCK_RE` | 3 |
| `_STUDY_UNIT_RE` | 2 |
| `_CLINICAL_OVERRIDE_RE` | 31 |

## 4. The one detector that is genuinely never fired — and why it stays

`_THRESHOLD_RE` is the only zero left after both corrections. Production applies
it to a **25-character lookbehind slice** of an abstract, so neither a
whole-document nor a per-line sweep reproduces its real call. Measured exactly
as `extract_sample_size` calls it:

```
  review-design papers            646
  _REVIEW_TOTAL_RE windows         95
  _THRESHOLD_RE suppressed          0     (0.00%)
  threshold vocabulary anywhere
    in those 95 windows             0     ← not an anchoring problem
```

The vocabulary (`at least`, `minimum of`, `fewer than`, …) appears **nowhere**
in any of the 95 windows, anchored or not. So this is a correct guard against an
idiom this library does not currently contain — **not** a wrong token shape.

**Kept.** Rule 6: never weaken a guard to improve a number, and a guard whose
worst case is doing nothing costs nothing. *Alternative rejected:* deleting it
as measured-dead code, which would remove the protection the first abstract
containing "at least 10 patients" needs.

## 5. Justified zeros, each with its reason

| detector | why zero is correct |
|---|---|
| `_PARTIAL_PMID_MARKER_RE` (0 on the *block* sense) | a half-written marker must never reach storage (invariant 21) — a hit is the bug |
| `_ROLE_FENCE_RE`, `parse_callouts`, `find_presentation_markup` | A44's role fence shipped 2026-09-03; **every stored document predates it**. Zero is correct today and **must become non-zero** once a curriculum is generated on current code — re-run after item 6 |
| `_EFETCH_PMID_RE`, `_EFETCH_ENTRY_SPLIT_RE` | PubMed wire format, never in an answer |
| `_MODULE_LINE_RE`, `_ROLE_LINE_RE`, `_TERM_LINE_RE` | generator scaffold, stripped before storage |
| `_TERM_SPLIT_AND`, `_TERM_SPLIT_OR` | operate on a query string |
| `_PMID_FORMAT_RE` | validates one id, not a document |
| `_QUARANTINE_BLOCK_RE`, `_LEGACY_QUARANTINE_BLOCK_RE` | counted by the multiline block scan, not a bare `finditer` |

`_ROLE_FENCE_RE` is the one to watch: it is the only justified zero whose
justification **expires**. If a curriculum generated on current code still
scores 0, A44's fence is not being emitted and the callout vocabulary is dead.

---

## 6. Full table — every detector, pre and post

`pre` = the naive instrument (whole-document `findall`, answer corpus, every
detector). `post` = corrected application and corrected corpus. A **bold 0** in
`pre` is a detector the naive instrument would have declared dead.

| detector | kind | corpus | applied as | pre | post |
|---|---|---|---|---|---|
| `_split_sentences` | fn | answers | — | — | 49824 |
| `_split_claim_units_tagged` | fn | answers | — | — | 20860 |
| `_split_claim_units` | fn | answers | — | — | 14254 |
| `_FINISHED_TAIL` | pattern | answers | per-line | 34 | 13960 |
| `_NUMERIC_PARAM_RE` | pattern | answers | document | 13366 | 13366 |
| `_ANY_CITATION_RE` | pattern | answers | document | 12864 | 12864 |
| `_REF_PMID_RE` | pattern | answers | document | 12864 | 12864 |
| `_PARAGRAPH_SPLIT_RE` | pattern | answers | document | 12146 | 12146 |
| `_SENTENCE_SPLIT_RE` | pattern | answers | document | 12025 | 12025 |
| `_PARTIAL_PMID_MARKER_RE` | pattern | answers | document | 10938 | 10938 |
| `_PMID_RE` | pattern | answers | document | 10925 | 10925 |
| `_extract_cited_pmids` | fn | answers | — | — | 10925 |
| `_extract_claim_citation_pairs` | fn | answers | — | — | 10617 |
| `_PARAM_RATE_WORD` | pattern | answers | document | 7920 | 7920 |
| `_CLINICAL_QUANTITY_RE` | pattern | answers | document | 6653 | 6653 |
| `_TIER_CLAIM_RE` | pattern | answers | document | 6490 | 6490 |
| `_PARAM_AGENT_HEAD` | pattern | answers | document | 6182 | 6182 |
| `_CLINICAL_ACTION_RE` | pattern | answers | document | 5290 | 5290 |
| `_DRUG_VOCAB_RE` | pattern | answers | document | 5114 | 5114 |
| `_LIST_ITEM_RE` | pattern | answers | per-line | **0** | 4710 |
| `_LIST_MARKER` | pattern | answers | per-line | **0** | 4710 |
| `_AUTHOR_MENTION_RE` | pattern | answers | document | 4551 | 4551 |
| `_TERM_SPLIT_OR` | pattern | answers | document | 3070 | 3070 |
| `_EVIDENCE_DESCRIPTION_RE` | pattern | abstracts | document | 5496 | 2547 |
| `_PSEUDO_HEADING_RE` | pattern | answers | document | 2408 | 2408 |
| `_split_sections` | fn | answers | — | — | 1846 |
| `extract_numeric_parameters` | fn | answers | — | — | 1807 |
| `_PARAM_FWD` | pattern | answers | document | 1770 | 1770 |
| `_ATX_HEADING_RE` | pattern | answers | per-line | 41 | 1737 |
| `_HRULE_RE` | pattern | answers | per-line | **0** | 1720 |
| `_HEADING_RE` | pattern | answers | document | 1660 | 1660 |
| `_TABLE_ROW_LINE` | pattern | answers | per-line | **0** | 1628 |
| `_TABLE_ROW_RE` | pattern | answers | per-line | **0** | 1626 |
| `_REVIEW_DESIGN_RE` | pattern | abstracts | document | 2124 | 1491 |
| `_detect_unattributed_claims` | fn | answers | — | — | 1047 |
| `_DIRECTIVE_DEONTIC_RE` | pattern | answers | document | 965 | 965 |
| `_detect_uncited_directive_claims` | fn | answers | — | — | 957 |
| `_AUTHORITY_BODY_RE` | pattern | answers | document | 943 | 943 |
| `_IF_DISPLAY_RE` | pattern | answers | document | 779 | 779 |
| `_INLINE_LABEL_RE` | pattern | answers | per-line | **0** | 631 |
| `_DTREE_OPEN_RE` | pattern | answers | per-line | **0** | 610 |
| `_COI_NEGATION_RE` | pattern | abstracts | document | 98 | 570 |
| `_INVITRO_WEAK_RE` | pattern | abstracts | document | 295 | 557 |
| `_BECAUSE_RE` | pattern | answers | document | 539 | 539 |
| `_INVITRO_STRONG_RE` | pattern | abstracts | document | 350 | 464 |
| `_CLINICAL_OVERRIDE_RE` | pattern | abstracts | document | 31 | 458 |
| `check_coi_blocklist` | fn | answers | — | — | 398 |
| `_REVIEW_TOTAL_RE` | pattern | abstracts | document | 112 | 386 |
| `_UNSOURCED_LABEL_RE` | pattern | answers | document | 374 | 374 |
| `_detect_uncited_author_mentions` | fn | answers | — | — | 350 |
| `_PARAM_BWD` | pattern | answers | document | 322 | 322 |
| `_SUPPORT_BLOCK_RE` | pattern | answers | document | 288 | 288 |
| `_check_recommendation` | fn | answers | — | — | 222 |
| `detect_module_truncation` | fn | answers | — | — | 199 |
| `_detect_gap_sections` | fn | answers | — | — | 178 |
| `_TABLE_SEP_RE` | pattern | answers | per-line | **0** | 155 |
| `_PROSPERO_RE` | pattern | abstracts | document | 6 | 139 |
| `_DIRECTIVE_IMPERATIVE_RE` | pattern | answers | per-line | **0** | 133 |
| `extract_clinical_recommendation` | fn | answers | — | — | 129 |
| `_EPISTEMIC_DIRECTIVE_RE` | pattern | answers | document | 116 | 116 |
| `_LEGACY_QUARANTINE_BLOCK_RE` | pattern | answers | document | 112 | 112 |
| `_AUTHOR_ASSERTS_RE` | pattern | answers | per-line | **0** | 94 |
| `_UNCITED_HALF_RE` | pattern | answers | document | 56 | 56 |
| `_COI_CUE_RE` | pattern | abstracts | document | 95 | 32 |
| `_check_quarantine_reframe` | fn | answers | — | — | 14 |
| `_COI_AFFIRMATIVE_RE` | pattern | abstracts | document | 4 | 7 |
| `detect_malformed_because` | fn | answers | — | — | 6 |
| `_NON_ABSTRACT_BLOCK_RE` | pattern | abstracts | per-line | **0** | 3 |
| `_EFETCH_ENTRY_SPLIT_RE` | pattern | answers | document | 2 | 2 |
| `_STUDY_UNIT_RE` | pattern | abstracts | per-line | **0** | 2 |
| `_TRAILING_BRACKET_RE` | pattern | answers | per-line | **0** | 2 |
| `_EFETCH_PMID_RE` | pattern | answers | document | 0 | 0 |
| `_MODULE_LINE_RE` | pattern | answers | document | 0 | 0 |
| `_PMID_FORMAT_RE` | pattern | answers | per-line | 0 | 0 |
| `_QUARANTINE_BLOCK_RE` | pattern | answers | document | 0 | 0 |
| `_ROLE_FENCE_RE` | pattern | answers | document | 0 | 0 |
| `_ROLE_LINE_RE` | pattern | answers | document | 0 | 0 |
| `_TERM_LINE_RE` | pattern | answers | document | 0 | 0 |
| `_TERM_SPLIT_AND` | pattern | answers | document | 0 | 0 |
| `_THRESHOLD_RE` | pattern | abstracts | per-line | 0 | 0 |
| `find_presentation_markup` | fn | answers | — | — | 0 |
| `parse_callouts` | fn | answers | — | — | 0 |
