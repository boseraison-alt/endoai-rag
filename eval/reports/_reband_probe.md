# Item C — reband from publication types (DRY RUN)

No `--apply` exists on this script. Rebanding moves `level_key`, which
carries 39% of the score, which orders every pool — so it changes every
answer. RB decides with these numbers.

| | |
|---|---|
| candidate rows (numeric pmid, citeable, not curated) | 4 |
| derived == stored | 0 |
| not derivable from publication types | 3 |
| **would change** | **0** |

Derivation is `endo_ai.tier_from_pubtypes`, the same function the
write-back guard uses. Guideline publication types derive `guideline`,
not `level1`. `Review`-only records derive nothing — NLM does not
reliably tag society guidelines in dental journals, and a bare `Review`
would demote a consensus guideline to expert opinion.

## Totals by tier pair

| stored | derived | rows |
|---|---|---|

## Every row that would change

| pmid | stored | derived | score now | score after | why |
|---|---|---|---|---|---|
