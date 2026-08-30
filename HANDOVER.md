# Handover — endo-ai-rag

A clinical endodontics RAG assistant. It retrieves primary literature from a
Neon/pgvector library or live PubMed, scores each paper, bands it by study
design, and asks Claude to synthesise an answer that cites only what it was
given. The product's entire claim is that the citations are real and the
evidence strength is honestly labelled.

Read `docs/architecture.html` for the system layout. This file covers what the
architecture diagram cannot: the failure modes this codebase actually has, and
why the tests are shaped the way they are.

---

## The three bug classes that keep recurring

### 1. PubMed query strings that are syntactically fine and semantically wrong

PubMed does not reject a malformed query. It guesses, and it tells you what it
guessed only if you ask for `querytranslation`. Four instances so far:

| String | What PubMed actually ran |
|---|---|
| `randomized controlled trial[pt] less quality` | `... AND less AND quality` — gutted Level II |
| `Cochrane Review[pt]` | `("cochran" OR "cochrane") AND Review[pt]` — matched every SR that mentions the Cochrane Library |
| `expert opinion` (untagged) | All-Fields match, ORing in any paper containing the phrase |
| bag-of-words module topics | six words ANDed together — 1 hit in all of PubMed |

All four looked correct in code review. `tests/test_tier_filter_syntax.py`
catches them: the offline half rejects untagged terms, trailing commentary and
unbalanced quoting; the network half (`RUN_NETWORK_TESTS=1`) sends each filter
to esearch and fails on anything landing in `[All Fields]`. It found the
`expert opinion` bug on its first run, before anyone knew it existed — which is
the argument for the whole category of test that asks an external system what
it understood rather than asserting on the string you sent.

**If you add or edit a tier filter, run the network tests.**

### 2. Fixing the code without fixing the stored data

`level_key` is written into the library at ingest and read back verbatim. A
retrieval-time fix protects new rows only; existing rows keep the wrong tier
forever. The Cochrane fix needed a code change *and* a 109-row migration
(`scripts/fix_cochrane_tier.py`) *and* a rescore, because `level_key` drives the
design axis at 39% weight.

**Any change to how a tier is assigned needs a matching migration. Take a
backup table first — the first Cochrane migration did not, and the identity of
the 109 affected rows is now unrecoverable.**

### 3. Trusting a PubMed field that is only populated for some records

`PublicationTypeList` is assigned by NLM indexers at MEDLINE indexing time.
Publisher-supplied records — most MDPI and Frontiers titles, and nearly
everything from the last ~18 months — carry only `["Journal Article", "Review"]`
no matter what the paper actually is. A reclassification keyed on publication
type alone would have demoted 45 genuine systematic reviews to Level V,
including papers with "A Systematic Review" in the title.

`scripts/reclassify_by_pubtype.py` therefore trusts pubtypes **only when
`MedlineCitation Status == "MEDLINE"`**, identifies Cochrane by journal before
looking at pubtypes at all, and declines (never promotes) on society guidelines,
which NLM does not tag either. Non-MEDLINE rows are reported, not touched.

The general lesson: before keying a migration on a metadata field, check what
fraction of your rows actually have it populated, and whether that fraction
correlates with anything (here: recency and publisher).

### 4. Green unit tests over a path nothing exercises end to end

Three live bugs shipped with a passing suite: `TIER_ORDER` unimported in
`app.py` (NameError on every question), write-back inserting empty `level_key`,
and the similarity floor gating the routing decision but not the evidence.
Unit tests imported the symbols directly and passed. `tests/test_end_to_end.py`
exists for this and should be extended rather than worked around.

Related: for anything that classifies text, build fixtures from production data
before trusting the suite. The COI detector passed its tests while 9 of 10
flagged papers were false positives; only a hand spot-check of real
`CoiStatement` values caught it.

---

## The eval set

`eval/questions.json` + `python eval/run_eval.py`. Retrieval only — no LLM
tokens.

**Every case must set `force_route`.** Write-back moves the ground under an
unpinned case: the laser case was written for a live search-term bug, the fixed
run wrote 196 papers into the library, and the same case silently started
testing the library path instead. It would have passed the next identical
regression. A topic worth testing both ways gets two cases, one pinned each way.

Cases 3–20 are unwritten and need clinical judgement about which topics the
library genuinely covers — guessing that makes the baseline measure assumptions.

---

## Cost

A four-module Deep Learning curriculum with real retrieval costs **~$1.18**
(measured 2026-08-29, `learn_history/` records `cost_usd` per run). The target
was $0.50. Quote $1.18 — it is the honest number.

The failing 5-paper run cost $0.60, i.e. it "met" the target by not retrieving
anything. Cost per run is not a quality metric and should never be optimised on
its own.

---

## Things deliberately not done

- **In vitro / ex vivo tier**, and a **tier-relative quality floor**. Both change
  how every paper ranks; doing them before the eval set is populated would
  freeze their effects into the baseline unmeasured.
- **Journal impact factor** is excluded from scoring (`USE_IMPACT_FACTOR`,
  default false) on PRISMA grounds — it measures the journal, not the paper.

## Stale evidence

Three separate ways a paper can be obsolete and still be served:

- **Retracted** — `has_retraction`, excluded from `search()` and filtered at the
  PubMed query level.
- **Withdrawn** — Cochrane retitles these `WITHDRAWN: ...` in PubMed and does
  *not* mark them retracted, so `has_retraction` misses them. Excluded by title
  match, which is canonical here rather than a heuristic.
- **Superseded** — every Cochrane update is a new PubMed record and the old ones
  stay indexed. 18 were being served, including a 2005 review superseded in 2019.
  `superseded_by` holds the PMID of the current version; chains resolve to the
  terminal version (CD005296 has three generations). `UpdateIn` is carried by the
  *older* record and names its successor; `UpdateOf` points backwards.

**The live PubMed path has no supersession concept.** It filters retractions at
query time but nothing parses `UpdateIn`, so a question that routes live can
still surface a stale Cochrane version. Same bug, other path, still open.

## Known open items

- 14 library rows carry no `level_key`. They band to the weakest tier, which is
  safe and pinned by `test_end_to_end.py`, but live write-back keeps producing
  them and the source has not been traced.
- `generate_multi_search_terms` is not stable in how many terms it emits — 1 term
  and 8 terms for the same question minutes apart, an 8x swing in retrieval
  breadth. The eval asserts floors only because of this.
- `endo_ai._merge_corrections_and_registries` iterates only `PubmedArticle`, so
  `PubmedBookArticle` records (StatPearls chapters) get no pubtypes, no MEDLINE
  status, no COI and no corrections. Three sit at Level I scoring 67.
- 11 rows tagged `Retracted Publication` remain at `level1`/`cochrane`. The
  retraction penalty is a 0.5x score multiplier, not a tier demotion; they are
  excluded from search, so this is presentation debt rather than exposure.
- 8 scoping reviews and 25 `Journal Article`-only rows sit at `level1` with no
  derivable design.
