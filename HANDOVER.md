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

## The four recurring bug classes

Every serious bug this codebase has shipped is an instance of one of these
four. Each entry gives a one-line detector — the question to ask of any diff —
and the test file that guards it.

### (a) A tier label trusted from a stored column

**Detector: any read path that uses `level_key` without asking where it was
written.**
**Guard: `tests/test_end_to_end.py` (banding assertions, unlabelled-row
fixture) plus the audit scripts (`scripts/audit_laser_run.py`,
`scripts/reclassify_by_pubtype.py`, `scripts/rescore_library.py`).**

`level_key` is written into the library at ingest and read back verbatim, and
it drives the design axis at 39% weight — so every writer's bug becomes every
reader's bug, silently. A retrieval-time fix protects new rows only; existing
rows keep the wrong tier forever. The Cochrane fix needed a code change *and*
a 109-row migration (`scripts/fix_cochrane_tier.py`) *and* a rescore. The
score-banding workaround in `app.py` was the same class from the other side:
it promoted papers across tiers by score because 37% of rows had no
`level_key` to trust.

**Any change to how a tier is assigned needs a matching migration. Take a
backup table first — the first Cochrane migration did not, and the identity of
the 109 affected rows is now unrecoverable.**

### (b) Untagged or annotated terms in PubMed queries

**Detector: any query term without a field tag (`[pt]`, `[tiab]`, …) or with
trailing text after the tag.**
**Guard: `tests/test_tier_filter_syntax.py` (offline half rejects untagged
terms, trailing commentary and unbalanced quoting; network half sends each
filter to esearch under `RUN_NETWORK_TESTS=1` and fails on anything landing
in `[All Fields]`).**

PubMed does not reject a malformed query. It guesses, and it tells you what it
guessed only if you ask for `querytranslation`. Four instances so far:

| String | What PubMed actually ran |
|---|---|
| `randomized controlled trial[pt] less quality` | `... AND less AND quality` — gutted Level II |
| `Cochrane Review[pt]` | `("cochran" OR "cochrane") AND Review[pt]` — matched every SR that mentions the Cochrane Library |
| `expert opinion` (untagged) | All-Fields match, ORing in any paper containing the phrase |
| bag-of-words module topics | six words ANDed together — 1 hit in all of PubMed |

All four looked correct in code review. The network half found the `expert
opinion` bug on its first run, before anyone knew it existed — which is the
argument for the whole category of test that asks an external system what it
understood rather than asserting on the string you sent.

**If you add or edit a tier filter, run the network tests.**

### (c) Metadata computed on a batch, applied per paper

**Detector: any classifier called once per efetch batch whose result lands on
individual papers.**
**Guard: `tests/test_coi_scoping.py` (and the batch-shaped fixtures in
`tests/conftest.py`, which always test extraction inside a batch of
different-shaped papers, never on a single paper alone).**

efetch returns many `PubmedArticle` records in one XML document. Anything that
runs on "the response" instead of "the record" — a COI classifier, a pubtype
extractor, a MEDLINE-status check — stamps one paper's answer onto the whole
batch. The COI detector shipped exactly this way: it passed its unit tests
(single-paper fixtures) while 9 of 10 flagged papers in production were false
positives; only a hand spot-check of real `CoiStatement` values caught it.

For anything that classifies text, build fixtures from production data before
trusting the suite.

### (d) A check that fails open and shows nothing

**Detector: any guard whose failure branch produces no user-visible output.**
**Guard: the citation-support-status test in `tests/test_end_to_end.py`
(`test_citation_support_status_is_stated` — the answer must state the check's
outcome, including "not available", never silence).**

A validation that catches nothing and says nothing is indistinguishable from a
validation that ran clean. Instances: the clarify gate swallowing exceptions
and proceeding, the citation-support check whose absence looked identical to a
pass, and — before this pass — an admin-auth design where an unset token would
have meant "no auth" instead of "no access". The rule now enforced in
`app.py`: a disabled or failed check must return an explicit refusal (admin
routes 403 when `ADMIN_TOKEN` is unset; X-ray uploads are rejected when
metadata stripping fails) or an explicit "not available" in the output.

### Related lesson: trusting a PubMed field that is only populated for some records

Not one of the four, but it burned a migration and shapes
`scripts/reclassify_by_pubtype.py`. `PublicationTypeList` is assigned by NLM
indexers at MEDLINE indexing time. Publisher-supplied records — most MDPI and
Frontiers titles, and nearly everything from the last ~18 months — carry only
`["Journal Article", "Review"]` no matter what the paper actually is. A
reclassification keyed on publication type alone would have demoted 45 genuine
systematic reviews to Level V, including papers with "A Systematic Review" in
the title.

`scripts/reclassify_by_pubtype.py` therefore trusts pubtypes **only when
`MedlineCitation Status == "MEDLINE"`**, identifies Cochrane by journal before
looking at pubtypes at all, and declines (never promotes) on society guidelines,
which NLM does not tag either. Non-MEDLINE rows are reported, not touched.

The general lesson: before keying a migration on a metadata field, check what
fraction of your rows actually have it populated, and whether that fraction
correlates with anything (here: recency and publisher).

### Related lesson: green unit tests over a path nothing exercises end to end

Three live bugs shipped with a passing suite: `TIER_ORDER` unimported in
`app.py` (NameError on every question), write-back inserting empty `level_key`
(class (a)), and the similarity floor gating the routing decision but not the
evidence (class (d) in spirit — the check ran and changed nothing visible).
Unit tests imported the symbols directly and passed. `tests/test_end_to_end.py`
exists for this and should be extended rather than worked around.

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

## X-ray / vision path — OFF by default, BAA required to enable

`POST /api/analyze-xray` sends a patient radiograph to a third-party vision
API (Gemini 2.5 Pro, GPT-4o fallback). Patient imagery is PHI. The route ships
disabled and returns 403 until `ENABLE_XRAY=true` is set — and **setting it in
any production deployment requires a Business Associate Agreement (BAA) with
the vision provider first**. This is a decision already taken (WORKLIST §5);
do not re-litigate it in code.

When enabled, `app.py` re-encodes every upload to strip EXIF/GPS/PNG-text
metadata (DICOM-to-JPEG exporters routinely embed patient name/DOB there;
stripping failure rejects the upload rather than forwarding raw bytes), and
the `tooth_hint` field is sanitized to a bare tooth designation so free-text
case narrative never travels with the image. `tests/test_xray_gating.py` pins
all three properties. Note the app accepts PNG/JPG only — raw DICOM uploads
are rejected by extension, so DICOM tag stripping is deliberately out of
scope until someone adds a DICOM ingest path (which would need its own
de-identification pass, not just this one).

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
