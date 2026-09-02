# CURO — Session Handover & Next Steps

Start a FRESH Claude Code session and open with:

> Read CURO_HANDOVER.md, HANDOVER.md, and WORKLIST.md, then execute §5 of
> CURO_HANDOVER.md.

Do not continue the old session — it is near its context limit and will
auto-compact.

---

## 1. What Curo is right now (state as of tag `case-v3`)

An evidence-graded endodontics assistant: **2,350-paper** curated library (Neon
Postgres + pgvector) with per-paper provenance (evidence tier incl. in vitro,
COI tri-state, retraction/withdrawal/supersession, MEDLINE status,
pre-registration), live PubMed fallback with synonym-expanded queries and an
authority guarantee (Cochrane-tier + top Level I papers can never be dropped by
query variance), tier-banded synthesis with a fabrication validator, a
grounding rule on all three synthesis prompts **reconciled with the
recommendation-traceability gate**, and a citation-support check on all three
answer paths that reads the whole abstract and **knows what shape of claim it
is judging**, streaming answers, Review-mode conversation memory, **case
discussion that tells a diagnostic question from a treatment one and answers
the first with a ranked, per-candidate-retrieved differential**, **streamed, with the guardrails
running underneath text the clinician is already reading**, and five
export styles — audio, video,
slides, podcast and a self-contained reveal.js web deck that auto-advances with
its own narration — all generated from ONE cached slide-spec in the approved
dark design. **1,510 tests**, all mutation-checked. **25-case retrieval eval**
with a 3-run baseline (`eval/baseline_v6.json`) whose harness measures the
citation-support flag rate per case, on both routes, and **excludes rows
written by another process**.
Backups: git bundle + DB export + full zip on OneDrive Desktop, GitHub live.

**The numbers that describe the current state:**

| | |
|---|---|
| citation-support flag rate, LIVE Review path | **0.0%** (0/51), from 20.6% (7/34) — p = 0.0011 |
| citation-support flag rate, library Review path | **~8.9%** (4/45) — quote this, not 4.3%; see the note below |
| citation-support flag rate, Deep Learning | **6.7%** (16/238), from 13.3% — p = 0.0217; the regression is closed |
| Deep Learning genuinely-unsupported rate, hand-judged | **2.1%** (5/238) — 69% of what the checker flags is artifact |
| Review attempt-1 pass rate, the case that reproduced the retry | **10/10**, from 3/10 — p = 0.0031 |
| cost per served Review answer, that case | **$0.5596**, from $0.9306 |
| cost per cold demo Review answer | **~$0.85** (five measured $0.68-$0.95), from ~$1.28 |
| cold curriculum | **7.5 min, $1.17** (was 8.0 min, $1.52) |
| claim units the checker understands | prose, decision-tree branch, table row, bold label, list item |
| longest claim unit on a curriculum | **469 chars**, from 2,403 |
| abstract excerpt the support judge sees | the whole abstract |
| retrieval baseline | `eval/baseline_v6.json` — 25 cases x 3 runs, unmoved |
| tests | **1,464** passing, 46 skipped (1,510 collected) |
| **`/health`** | reports the **git hash the process imported**, frozen at import. Check it before trusting any server. |
| case follow-ups: non-discriminating question rate | **0/20**, from 8/15 = 53% |
| the same question on the contrast case (68, on alendronate) | **10/10** asked — filtered by relevance, not deleted |
| diagnostic case answer | **6 candidates, 139 papers, $0.1801** (was 26 papers, $0.0724, no differential) |
| case eval cases | **4** (`--case-subset`), incl. the set's first FOLLOW-UP case |
| the dens evaginatus fixture | DE is candidate **1 of 6**, management at char 1,277 (was char 323); **0/16** support flags |
| case turn-2 time to first text | **14.4 s**, from 56.6 s — readable while the checks run |
| citations surviving a browser copy | **34 of 34**, from **0 of 34** |
| claims the case detector catches, prevention turn | **7**, from 2 — a protocol directive is a claim |
| the regenerated prevention turn | unattributed **7 → 2**, support flags **2/12 → 0/11**, no retry |
| library papers naming dens evaginatus | **24**, from 15 |

**Which run each rate comes from, because they are not all the same run.**
The library Review figure is the `grounding-v2` run. **Do not quote 4.3% as
the library baseline at all**: the same three cases measured 8.2%, 8.9% and
6.3% across one night, with nothing changed between the first two.

**What changed in `case-v3`.** Read `OVERNIGHT_REPORT_6.md`. The item
that started it — "the answers are full of uncited claims" — split into two
different bugs on measurement. The dominant one was a COPY bug: `.claim-cite`
carried `user-select: none`, so all 34 citations on screen became 0 citations
in the pasted text and every claim then looked uncited. The second was real
and smaller: the claim detector caught a claim by its NUMBERS, and a chairside
protocol is an INSTRUCTION — "Reduce occlusal contact on the tubercle",
"Screen the entire mouth for DE" — uncited and actionable with no statistic in
it. Four patterns added, plus `UNCITED_AUTHOR_MENTION` with no tolerance
count. A numeric directive now has three honest endings — cite it, cut it, or
label it "standard practice, not from the retrieved evidence base" — and the
label ACTUALLY WORKS, because a retry offered only "rephrase or delete" turned
7 unattributed claims into 8. Targeted retrieval found the prevention
literature the flat write-back floor of 50 had been hiding (the single most
on-point paper scored 35.4). And the case path now streams: turn-2 time to
first text 56.6 s -> 14.4 s, with the guardrails running underneath a readable
answer instead of a spinner, and follow-ups seeding retrieval with the papers
the previous turn cited — as CANDIDATES, after the routing gate, never as a
cache.

**What changed in `case-v2.1`.** Read `OVERNIGHT_REPORT_5.md`. Three things,
and the first was a defect `case-v2` had reintroduced: the differential
generator's `max_tokens` was too small for six candidates, the JSON truncated,
the parser returned nothing, and the turn fell back to the treatment path with
no error anywhere — so the fixture answered "Proceed with non-surgical root
canal treatment" on code that was supposed to have fixed exactly that. Second,
the differential now treats the TOOTH and the patient's demographics as priors,
which is what makes dens evaginatus the lead candidate on a mandibular premolar
instead of the third. Third, the synthesis scaffold lists which PMIDs were
retrieved for which candidate, which took the fixture's citation-support flags
from 1-3 to 0-2: without it a paper about cystic lesions carried three dens
invaginatus prevalence claims. The overreaching "leading cause of RCT in
premolars presenting without caries" is now stated at the strength its source
supports, "the predominant etiology in immature teeth (32.1%)".

**What changed in `case-v2`.** Read `OVERNIGHT_REPORT_4.md`. A case turn is now
classified `diagnostic` or `treatment` (failing open to treatment, the measured
path); a diagnostic turn generates 3-6 candidate CAUSES, retrieves once per
candidate through the same evidence engine, unions the results, and answers with
a ranked differential — features for and against each candidate, the cited
evidence, and a table mapping each discriminating test to the candidates it
settles — with management last and brief. Candidates with no literature stay in
the list and say so. The follow-up generator stopped working from a
treatment-planning checklist: a non-discriminating question in 0 of 20 runs,
from 8 of 15, while the SAME question is asked in 10 of 10 runs of the
68-year-old on alendronate. The case path has eval cases for the first time.

**What changed in `guardrails-v1`.** Read `OVERNIGHT_REPORT_3.md` for the whole
thing. In one paragraph: `/health` now reports the commit the process actually
imported, so "was that answer from the new code?" is a curl away; the
claim-unit splitter learned the four shapes a curriculum writes that a sentence
splitter cannot see, which took the Deep Learning flag rate from 13.3% to 6.7%
and closed the regression `grounding-v2` opened; the grounding rule and the
recommendation-traceability gate stopped contradicting each other in the Review
prompt, which took attempt-1 pass on the reproducing case from 3/10 to 10/10
and cost per served answer down 40% **with both gates untouched**; and
`cost_log.jsonl` rows now name their writer while `pubmed_audit.jsonl` finally
got the pid guard `evidence_mapping.jsonl` has had. All 16 remaining Deep
Learning flags were hand-judged: 5 are genuinely unsupported, and the largest
artifact class is new and is a prompt/checker collision of the same shape the
Review prompt just resolved.

**What changed in `grounding-v2`.** The synthesis prompts got a grounding rule
saying what a `[[PMID:N]]` marker asserts; the citation-support judge stopped
being shown only the first 1,200 characters of an abstract; 124 rows whose
stored "abstract" was an author-affiliation list were healed; and the web deck
records its own per-slide narration so auto-advance works.

**What changed in `grounding-v1`.** Every library abstract is now stored and
sent at full length. 1,342 of 2,350 rows (57%) had been cut at ingest at
exactly 1,000 or 1,200 characters — and structured abstracts put CONCLUSIONS
last, so the finding was the part that was missing.

## 2. Invariants — never regress these (each has a guarding test)

1. Tier hierarchy is by study design, never by score; unknown design bands to
   the weakest tier. Score ranks only within a tier.
2. Every plotted chart value appears verbatim in cited text; same quantity,
   same unit, no ranges-as-scalars, no unitless pairs assumed comparable, the
   sign is part of the number, **and the axis unit is the unit of the number
   actually plotted**. A chartless deck is a valid outcome.
3. No raw `[[PMID:N]]` on any rendered surface (speaker notes exempt).
4. COI = named commercial entity in a non-negated declaration sentence, applied
   once at rescore from stored `coi_status`.
5. Cochrane tier is journal-verified; withdrawn/superseded versions excluded on
   both paths.
6. Zero-evidence modules never render a numeric protocol.
7. Follow-up cache entries are partitioned by `context_hash`.
8. Case discussion never re-asks a fact present in the clinician's description.
9. Both deck exports consume the shared `slide_spec_cache`; content hash must
   match, and for one spec they must make the same chart/no-chart decision.
10. Cost is reported only beside hits-per-query and paper counts — never alone.
11. Both retrieval paths show Claude the same KIND of thing: the paper's text,
    not just its metadata. Assert on the BLOCK, never on the renderer.
12. An eval must not measure a stored artefact of an earlier run — not the
    library it writes back to, not the answer cache, not a pinned route it only
    requested. A synthesis case that cost $0 is a failure.
13. Abstract text never reaches a browser. `app._safe_papers` is the only
    enforcement point and must be applied at every exit that serialises papers.
14. **Abstracts are stored whole.** Caps belong at the `embed()` call sites and
    nowhere else. Six ingest paths violated this for the life of the project.
15. **Every generated answer states its citation-support outcome**, on all
    three paths, including "not available" — and per module on a curriculum,
    with an appendix for any block the stitcher drops.
16. **A claim unit ends where the claim ends.** A decision-tree branch, a table
    row, a bold-labelled sub-point and a list item are each ONE claim; the
    splitter must never hand a marker text it was not attached to. Un-merging
    makes the checker STRICTER — merged pairs were flagged less — so a change
    here that only lowers the flag rate is the defect, not the fix.
17. **A clinical recommendation is always traceable, and never at the cost of a
    marker the paper does not carry.** Where the evidence base does not address
    the question, the recommendation states the gap unmarked and cites what the
    evidence base DOES establish. Neither the grounding rule nor
    `_check_recommendation` may be weakened to make a retry go away.
18. **A diagnostic case turn answers with a differential, and the differential
    comes first.** "What could the cause be?" is not "what should I do?", and
    an answer that reaches management before it names a differential has
    answered a question nobody asked. A candidate with no literature stays in
    the list and says so — dropping it hides a cause behind the accident of
    what has been published. The intent router fails open to TREATMENT, which
    is the measured path.
19. **A differential ranks by THIS tooth and THIS patient, not by base rate.**
    A tooth number tells you which anomalies are even possible — dens
    invaginatus in maxillary laterals, dens evaginatus in mandibular premolars
    — and a candidate that is common overall must not crowd out one that is
    common in this tooth. And a paper retrieved for one candidate is not
    evidence for another: the synthesis scaffold states which PMIDs came from
    which candidate, because without it a paper about cystic lesions carried
    three dens invaginatus prevalence claims with counts that appear nowhere
    in it.

20. **A chairside instruction is a claim.** A numeric directive with no
    marker has exactly three honest endings — cite it, cut it, or label it
    "standard practice, not from the retrieved evidence base" — and the label
    must actually count as attribution, or the honest answer and the silent
    one are punished identically and the retry learns nothing. A named author
    with no marker anywhere in its claim unit is a validator FAILURE with no
    tolerance count: the model reached for a specific paper and did not wrap
    it. Attaching the nearest PMID clears the warning and misleads the reader,
    and the corrective message says so.
21. **Partial text is never checked, never shown as `answer`, and never
    reported as passing.** On every streaming path the guardrails run once on
    the text read off the FINAL message; `partial_answer` is a separate job
    field, cleared on completion, and `checks_status` stays `"pending"` for
    the whole stream. A half-written `[[PMID:312` reads as a fabrication. A
    follow-up may SEED retrieval with the PMIDs the previous turn cited — as
    candidates, after the routing gate — but no evidence base and no answer is
    ever cached or reused across turns.

22. **No journal-identity signal in scoring or ranking. Venue is metadata and
    Cochrane-verification only. Decided by RB 2026-09-02 (the JOE-vs-IEJ
    question); the remedy for missing canon papers is retrieval/ingestion
    fixes, never venue weight.**

    (RB's instruction numbered this 11. It is 22 here because this list has
    21 entries, and `endo_ai.py` comments and test names already cite
    "invariant 11" and "invariant 15" by number — renumbering would silently
    repoint every one of those references. The wording is RB's, verbatim.)

    Guarded by `tests/test_no_journal_weighting.py`, which RUNS the scoring
    path rather than grepping it: the impact-factor term is swept across its
    whole range and the score must not move. The positive control in that file
    is the load-bearing half — it flips `USE_IMPACT_FACTOR` and shows the same
    sweep DOES move the score, so the invariant is evidence rather than an
    assertion that would hold against a `score_paper` that ignored its
    arguments.

    `USE_IMPACT_FACTOR` predates the decision and still exists as an
    environment flag. It is off, a test asserts it is off, and turning it on
    is now a violation rather than a configuration choice.

Recurring bug classes (see `HANDOVER.md`): trusted stored labels, untagged
PubMed query terms, batch-metadata applied per-paper, fail-open checks that
show nothing, tests that grep source instead of asserting on the prompt/data
actually used.

## 3. Tag timeline (rollback points)

`mvp-demo` → `mvp-demo-2` → `presentation-v1` → `demo-polish` → `case-v1` →
`eval-v5` (baseline v5, library evidence block, deck P2s) → `grounding-v1`
(full abstracts end to end, baseline v6, DL support check) → `grounding-v2`
(grounding rule, whole-abstract support judge, collapsed-abstract repair,
web-deck auto-advance, maintenance script) → `guardrails-v1` (`/health` git
hash, the claim unit, the grounding/traceability reconciliation, `cost_log`
`source` + `pubmed_audit` pid guard) -> `case-v2` (diagnostic vs treatment
intent, differential-first retrieval, follow-up relevance, the first two case
eval cases) -> `case-v2.1` (the tooth as a prior, per-candidate paper
attribution, targeted dens evaginatus ingest, the ordering pinned) -> `case-v3`
(the copy bug behind "uncited claims", protocol directives as claims, the DE
prevention literature, the first follow-up eval case, streaming on the case
path).

Bundle: `~/OneDrive/Desktop/endo-ai-rag_backup.bundle`.

## 4. Backlog — prioritized, with source

### P1 (correctness / trust)

- **A true "the cited study did not report X" claim cannot pass the
  citation-support check.** 7 of the 16 remaining Deep Learning flags, and the
  largest single class now that the claim-unit artifact is gone.
  `_GROUNDING_RULE` explicitly instructs the model to write these — "take the
  number from the paper that reports it, **or state that the cited study did
  not report it**" — and the judge, asked "does this abstract support this
  claim?", correctly says no, because an abstract cannot state what it omits.
  Every one of the 7 is TRUE and names the right paper. This is the same
  collision `guardrails-v1` resolved for the CLINICAL RECOMMENDATION, in the
  shared constant rather than the Review prompt. **Recommended fix:** teach the
  judge a fourth verdict (`negative_claim` — the claim asserts the paper does
  NOT report something; supported iff the abstract indeed does not). Better
  than telling the prompt to write such statements unmarked, because it keeps
  the information and creates no new unmarked-claim class. Needs its own
  before/after; do not fold it into another synthesis change.
- **A claim about the EVIDENCE BASE carrying one paper's marker.** 2 of 16 —
  "the evidence base does not specify a minimum canal diameter", marked to one
  umbrella review. No single paper can support or refute it. Same family as
  the above and probably the same fix.
- **The Item 2 residual: a general principle composed across two papers.** 2 of
  10 after-arm recommendations cite a composite neither paper states alone
  ("outcome is governed by preoperative periapical status, coronal seal and
  restoration timing"). A prompt clause forbidding exactly that did not remove
  it. The unmeasured half: did the OLD prompt's retry produce better text, or
  the same composite? The before arm's retries were never generated. ~$3 to
  find out.
- **`_SUPPORT_MAX_PAIRS = 30` binds harder than it used to.** The four modules
  of the last live curriculum measured `total_pairs` 43 / 37 / 33 / 34 against
  `checked` 30 — **27 pairs of 147 (18%) never looked at**. The block names the
  remainder, so it is honest rather than silent. Raising it costs Haiku calls
  and nothing else; nobody has measured what it would find.
- **`table_row` claims flag at 40%** (6/15), by far the highest of the five
  shapes. A protocol-summary row is a terse parameter — "Irrigant contact time
  — Per canal, per cycle — 60 seconds" — and barely a proposition. Either the
  row needs its column header as context, or such rows should not carry
  markers. Newly visible, not newly caused.
- **The eval floor "0 sections state numeric clinical parameters with no
  citation" fails intermittently on the live laser case.** It failed in
  `guardrails-v1` and identically in the *pre-grounding-rule* baseline run of
  2026-09-01 (`eval/logs/item1_before_synthesis.log`). Pre-existing, but it
  means that case has never reliably passed.
- **112 library rows returned nothing from efetch** during the `grounding-v1`
  repair. 4 have no abstract in PubMed at all (confirmed individually); the
  other 108 were not investigated.
- **`ingest_aae_guidelines`'s PubMed harvest is live for the first time.** Its
  abstract fetcher had never returned anything; fixed in `grounding-v2`.
  **Dry-run that script before running it** — nobody has seen what it ingests.
- ~~The case path has NO eval cases at all~~ — **CLOSED (`case-v2`)**. Two
  cases now, run with `python eval/run_eval.py --case-subset`, and they are a
  PAIR: the 20-year-old forbids the bisphosphonate follow-up and the
  68-year-old requires it, so neither can be satisfied by deleting a topic.
  Both pass with 0 citation-support flags. `max_tokens` at 6000 is still on a
  measurement that has never been repeated.
- **A diagnostic case answer can still overreach its source.** Improved in
  `case-v2.1` by listing which PMIDs were retrieved for which candidate — the
  dens evaginatus fixture went from 1-3 flags to 0-2 — but the residual is the
  `artifact_negative` class, which is §5 Item 3.
- **`fetch_papers` broadens a zero-hit query into a DIFFERENT topic.** 23 of 48
  papers in the first dens evaginatus dry run did not mention the anomaly. The
  ingest script gates its write-back; the live path does not. §5 Item 1.
- **A `max_tokens` cap can silently disable a feature.** The differential
  returned `[]` on a truncated reply and the turn was answered on the treatment
  path with no error. Fixed there; the shape is generic. §5 Item 2.
- **A candidate's search topic is generated once and never checked.** A badly
  named candidate — "Idiopathic or occult cause (including undetected microbial
  access via extreme attrition)" — hands its retrieval a bad topic, and nothing
  reports it beyond the answer stating the gap.
- **The differential is not rendered to the clinician.** It is published on the
  job as `differential`; no template shows it. The answer carries the content
  in prose, but a UI showing "searching literature for: dens invaginatus"
  during the two-minute retrieval would make the wait legible.
- 8 library rows have an empty `title`, which reaches the prompt as a blank
  line where the paper's subject should be.
- **A handover that names a command should have run it.**
  `scripts/classify_dl_flags.py` raised `AttributeError` from the moment
  `grounding-v2` deleted `_SUPPORT_ABSTRACT_CHARS`, and this file went on
  telling the next session to run it for a whole batch. Fixed in
  `guardrails-v1`; the lesson is the general one.

**CLOSED in `guardrails-v1`:**

- ~~The running server is on stale code~~ — `/health` reports the commit the
  process imported, frozen at import. It caught a stale server writing into a
  measurement window the same day it landed.
- ~~The claim-unit artifact is 35% of Deep Learning citation flags~~ — four
  shapes taught, 13.3% → 6.7%, `artifact_unit` down from 13 of 37 to 2 of 16.
- ~~The grounding rule and the traceability gate pull in opposite
  directions~~ — reconciled in wording, 3/10 → 10/10 attempt-1, −40% cost,
  both gates untouched. Reasoning in `HANDOVER.md`.
- ~~The Deep Learning grounding regression is unexplained~~ — it was the claim
  unit. 6.7% is indistinguishable from the 8.5% pre-rule baseline (p = 0.49).
- ~~`cost_log.jsonl` has no `source` field~~ — every row names its writer;
  `/admin/costs` shows `product` by default and `by_source` always reports what
  the filter dropped. Historical rows untouched.
- ~~`pubmed_audit.jsonl` is unguarded shared state~~ — pid on every record, a
  redirectable path, exclusion in the harness, and the regression test the
  original `evidence_mapping` fix never got.
- ~~`prior_pmids` seeding is asserted nowhere~~ — **the premise was wrong.** It
  is asserted end to end by
  `tests/test_review_context.py::TestSeedsDoNotDecideTheRoute::test_a_thin_library_still_goes_live_with_seeds_available`,
  mutation-verified in `guardrails-v1`. A weaker duplicate was written and
  deleted.

### P2 (product polish)

- `_unit_of` — **DONE (`grounding-v1`)**, the axis unit now follows the
  plotted number.
- `case_convs` — **DONE**, deleted; it was written every case turn and read
  nowhere, uncapped, ~277 KB per client-supplied id.
- `_extract_claim_citation_pairs` — **DONE**, and the measurement reversed:
  merged claims were flagged LESS (37.6% vs 50.8%, p=0.002), so the defect was
  suppressing the guardrail, not blurring it.
- `arms` real-data coverage — **DONE**, `tests/fixtures/multi_arm_stat_panel.json`
  drives a real three-arm comparison through both exports.
- Narration↔deck slide sync — **DONE (`grounding-v2`)**. The deck records its
  own narration against its own spec, one segment per slide, and auto-advance
  is armed. Verified with real TTS and ffprobe: 21 segments == 21 slides,
  523.46s both ways. `narrate: auto` costs ~$0.25 and ~2 min per export that
  it did not before; `narrate: reuse` restores the old behaviour.
- Cancelled exports log no TTS cost row for characters already spent.
- "apexification" pronunciation: needs a HUMAN listen (RB).
- `narration.strip_markdown_for_speech` does not strip blockquotes. Harmless
  today — every narration path rewrites through an LLM first — but a raw
  narration path would read the citation-support blocks aloud. It DOES now
  strip a half-written `[[PMID:` fragment, which a real curriculum produced.

### P3 (before any real users)

- Single-process job store (restart kills jobs).
- Multi-user: auth, per-user history, the admin secret model.
- PHI/X-ray path stays OFF until a BAA exists (decision recorded).
- Second literature database (Embase/Scopus).
- Monthly maintenance loop — **BUILT (`grounding-v2`)**,
  `scripts/monthly_maintenance.py`, dry-run by default and deliberately
  **NOT scheduled**. Ran end to end clean: backfill 24s, rescore 10s, eval
  686s with 25/25 cases passing. RB decides when it first runs `--apply`.
## 5. THE QUEUE, in order

RB has queued four batches. They are listed here in the order they must run,
because two of them depend on artefacts the earlier ones produce.

| | batch | status | depends on |
|---|---|---|---|
| §5 | `dl-quality-v1` | Items 1-4 DONE, Item 5 (regenerate) in flight | — |
| §5b | `classics-v1` | [B1] and [C] DONE; [B2]-[B4] outstanding | — |
| §5c | `dl-quality-v2` | not started | the REGENERATED anesthesia curriculum, from `dl-quality-v1` Item 5 / `classics-v1` [B4] |
| §5e | `citation-audit-v1` | not started | `eval/fixtures/second_opinion_anesthesia_2026.md`, which exists |
| §5d | `retrieval-honesty-v1` | not started | displaced three times; still current |

`citation-audit-v1` has no dependency on the other three and could run at any
point. It is placed after `dl-quality-v2` only because it shares the anesthesia
subject matter and the deck pipeline, not because anything blocks it.

---

## 5a. Batch — "dl-quality-v1" (RB, queued 2026-09-01, verbatim)

Autonomous batch on `main`, tag `dl-quality-v1` at end. Standing rules from
`WORKLIST.md` §0/§6 apply in full. Commit + push per item; re-bundle after
commits.

> QUEUED — batch dl-quality-v1 (after current work; standing rules; tag at
> end).
> Fixture: the laser curriculum generated <today> — keep it as the
> before-state.
>
> ITEM 1 — Truncation gate in the stitcher. Module 4 ends mid-sentence ("when
> tips are not"); Module 1's materials table ends mid-cell ("Wavelength 630").
> Diagnose (expect stop_reason max_tokens, the case-v2.1 signature). Fix:
> raise/segment the cap AND add a stitcher gate rejecting any module whose
> text ends mid-sentence, mid-table-row, or mid-citation — regenerate that
> module once, else emit the module-not-generated notice. Mutation-check with
> a truncated fixture.
>
> ITEM 2 — Remove the 30-claim cap on the DL support check. Check every cited
> claim; report count + cost delta. Then re-check this curriculum in full and
> specifically adjudicate: PMID 27759881 cited for "no healing advantage for
> CBCT over radiography" — if misattributed (it is described elsewhere as the
> LLLT post-surgical Cochrane), the claim must be re-sourced or cut.
>
> ITEM 3 — The flagged Sabeti claim: verify author attribution and whether
> "noninferiority criteria" appears in or is fairly implied by the abstract of
> 40818665; restate at source strength (the DE-claim precedent).
>
> ITEM 4 — Cross-module consistency pass in the stitcher: after assembly, one
> Sonnet pass flags (a) numeric parameter conflicts between modules (e.g.,
> NaOCl 2/2.5/3/5.25%) → add one reconciling sentence citing which study used
> which; (b) decision-tree recommendations that conflict across modules →
> reconcile or explicitly note the tension; (c) malformed IF/THEN/BECAUSE (a
> BECAUSE containing only citations, no reason). This pass ANNOTATES and
> repairs formatting; it must not rewrite evidence claims. Tests for each
> detector; mutation-check.
>
> ITEM 5 — Regenerate the laser curriculum end-to-end; include before/after
> for: truncations (2→0), unchecked claims (13→0), the two adjudicated
> citations, consistency annotations added. Update eval DL case assertions: no
> mid-sentence module endings, zero unchecked claims. Report §8 format.

**The fixture is identified**: `answers/answer_20260901_135816.txt`, "Use of
lasers in root canal disinfection", 97 papers, generated 13:58 on
`guardrails-v1` during the demo re-warm. Both truncations reproduce in it —
`| **Laser — Diode (aPDT)** | Wavelength 630 |` at line 92 and "…irrigant
extrusion when tips are not" at line 302. Do not regenerate it before Item 5;
it is the before-state.

**Item 2 supersedes §6.7.** The `_SUPPORT_MAX_PAIRS = 30` judgement call that
was waiting on RB is now decided: remove the cap. §5b Item 4 covers the same
ground and should be reconciled with whatever this batch measures, not run
twice.


## 5b. Batch — "classics-v1" (RB, queued 2026-09-02, verbatim)

[A] is answered and [C] is DONE; [B1] is DONE (the corpus fixture exists).
[B2]-[B4] are outstanding.

> AUTONOMOUS BATCH — classics-v1
> Standing rules apply (WORKLIST.md §0/§6): measure before changing; dry-run
> all DB writes and report delta splits before applying; mutation-check every
> new test; real fixtures, not synthetic; wip-commit before any destructive git
> operation; push + refresh the OneDrive bundle after every completed item;
> eval runs strictly serial; never weaken a checker or gate to improve a
> number. Tag classics-v1 at the end. Report in §8 format.
>
> [A] BATCH STATUS RECONCILIATION (do this first, it gates everything)
> Check git log/tags for dl-quality-v1 and case-v3 completion. Three
> possibilities: 1. Not yet run -> run those queued batches to completion
> FIRST, then continue here. 2. Ran, but the anesthesia curriculum (generated
> after) still shows mid-sentence module endings ("...19.35 mm from the",
> "[module body ends here as supplied]") and support-check footers still say
> "N further cited claim(s) were NOT checked" -> the truncation gate and the
> 30-claim-cap removal FAILED on real output. Reproduce using the stored
> anesthesia curriculum spec/answer, find why the gate passed truncated text
> (likely: gate checks the stitcher input, not the final rendered module; or
> the retry path bypasses it), fix at the generation/stitch layer — never by
> relaxing the gate — and add the anesthesia curriculum as a stored regression
> fixture asserting: no module ends mid-sentence, no "ends here as supplied"
> marker, support-check footer reports 0 unchecked claims. 3. Ran and the
> paste predates the fix -> regenerate the anesthesia curriculum once, confirm
> clean, and say so in the report.
>
> [B] CLASSIC READER/OSU CORPUS AUDIT — measure first, then fix only the
> measured cause. Context: RB expected the classic Ohio State anesthesia corpus
> (Reader as senior author; first authors Nusstein, Fowler, Drum, and others;
> mostly J Endod, ~1990-2015: IANB success rates, anesthesia failure in
> irreversible pulpitis, supplemental intraosseous/intraligamentary/buccal-
> infiltration trials, articaine vs lidocaine) to appear in the anesthesia
> curriculum. Two OSU papers ARE cited (PMID 26831048, 25770038) — the question
> is the deeper canon.
> B1. Build the canonical list: query PubMed for ("Reader A"[Author] OR
>     "Nusstein J"[Author] OR "Drum M"[Author]) AND anesthesia-related terms,
>     restricted to J Endod / Oral Surg Oral Med Oral Pathol / Anesth Prog,
>     1985-2020. Dedupe to a list of ~30-60 PMIDs. Store as
>     eval/fixtures/osu_anesthesia_corpus.json.
> B2. For EVERY pmid in that list, report a table: in library? | tier assigned
>     | score + per-component breakdown | did the classics exemption fire? |
>     was it in the candidate pool for the anesthesia curriculum run? | if
>     dropped, at which stage (KNN similarity below floor / coverage gate /
>     candidate cap / tier filter)?
> B3. Fix ONLY what the table shows, in this priority: - If the classics
>     exemption is not firing on papers that qualify: fix the exemption logic;
>     mutation-checked test built on real rows from B2. - If the papers were
>     never ingested: ingest them with full provenance (tier from study design,
>     COI tri-state, MEDLINE status), dry-run first with delta split, then
>     apply. These are targeted adds, not a bulk import. - If retrieval
>     vocabulary misses them (e.g., query says "inferior alveolar nerve block"
>     but classics are indexed under other terms): extend the synonym groups;
>     show hits-per-query before/after. Do NOT add any journal-based weighting
>     anywhere — see [C].
> B4. Done when: regenerating the anesthesia curriculum cites the classic
>     corpus where clinically appropriate (report the before/after citation
>     lists), and the full retrieval eval shows no regression outside baseline
>     ranges. If a case moves, explain it — code change vs variance — do not
>     silently re-baseline.
>
> [C] LOCK THE NO-JOURNAL-WEIGHTING DECISION (RB decided today: no venue
> preference)
> C1. Add an invariant test asserting the scoring path takes no journal-identity
>     input: no journal name, ISSN, or venue-derived feature may reach
>     score_paper's arithmetic (journal is allowed ONLY for the Cochrane
>     journal-verification check and display metadata). Test must be built on
>     the actual scoring code path, not a source grep. Mutation-check it:
>     temporarily add a +1 JOE bonus and confirm the test fails, then revert.
> C2. Append to CURO_HANDOVER.md §2 invariants: "11. No journal-identity signal
>     in scoring or ranking. Venue is metadata and Cochrane-verification only.
>     Decided by RB 2026-09-02 (JOE-vs-IEJ question); the remedy for missing
>     canon papers is retrieval/ingestion fixes, never venue weight."
>
> Report per item: what was measured, what was changed, test counts
> before/after, eval deltas, cost. Refresh bundle, push, tag classics-v1.

**[A] is answered, and the answer is possibility 1 with a correction to
possibility 2.** `case-v3` is complete and tagged. `dl-quality-v1` was
mid-batch. The anesthesia curriculum was NOT generated after the fix: `/health`
reports the server that produced it as `f23e8c8`, `git_dirty: true`, imported
18:53 — before Item 1 existed. All three symptoms reproduce in the stored
fixture and all three are the before-state.

**One finding not in the item list**, and it matters for [J] as well:
`[module body ends here as supplied]` appears NOWHERE in this codebase. The
stitcher LLM invented it when handed a module cut mid-sentence — so the system
detected the truncation, said so in plain English, and nothing downstream
parsed it.


## 5c. Queued third — "dl-quality-v2" (RB, queued 2026-09-02, verbatim)

Runs after `classics-v1`. Its fixture is the REGENERATED anesthesia curriculum,
so `dl-quality-v1` Item 5 and `classics-v1` [B4] must both have produced one
first. Item [F]'s prerequisite is already answered: **there is no "Item 6
consolidated references" commit anywhere in the history** (`git log --all`
searched for reference/bibliography), so [F] is the "not landed -> land it"
branch, not the "it failed" branch.

> AUTONOMOUS BATCH ADDENDUM — dl-quality-v2
> Standing rules apply (measure first; never weaken a gate; mutation-check
> every test; real fixtures; push + re-bundle per item). Fixture for everything
> below: the stored anesthesia curriculum run. Tag dl-quality-v2 at end.
>
> [F] BIBLIOGRAPHY = CITATIONS, EXACTLY
> Measured claim: the anesthesia bibliography contains papers never cited in
> the text (AAE position statements on antibiotics/implants/regenerative endo,
> Sjogren 1990, Cochrane pulpotomy + antibiotic-prescribing reviews) while
> in-text PMIDs are absent from it. First check git log for Item 6
> (consolidated references, set-equality): not landed -> land it; landed -> it
> failed, diagnose. Likely cause: bibliography assembled from the retrieval
> candidate pool instead of citations extracted from the rendered modules.
> Fix: bibliography must be exactly the union of in-text PMIDs, ordered
> tier-then-score. Test: set-equality assertion on the anesthesia fixture, both
> directions (no uncited entry, no missing citation). Mutation-check by
> injecting one pool-only paper.
>
> [G] ENDPOINT-DEFINITION DISCIPLINE FOR SUCCESS RATES
> Measure first: across the anesthesia fixture, list every % success claim, the
> endpoint its cited abstract defines (lip numbness / EPT / pain-free access),
> and whether the rendered claim states it. Then: (a) synthesis prompt rule —
> a success % must carry its endpoint when the abstract states one, and two
> rates with different endpoints may not be juxtaposed as comparable without
> saying so; (b) extend verify_citation_support — flag a % claim that drops an
> endpoint qualifier present in the abstract. Report flag-rate impact on the
> 5-case synthesis subset (a rise here is a true positive, not a regression).
>
> [H] NO POPULATION MEAN AS A PER-PATIENT INSTRUCTION
> Anesthesia Module 4 turns a mean foramen position (3.88 mm above occlusal
> plane, cited range -3 to +10 mm) into a measurement step. Extend the
> ranges-as-scalars gate from charts to protocol text: a numeric directive
> derived from a central tendency whose cited dispersion spans a clinically
> different action must be rendered with the range, or not as a directive.
> Real-fixture test; mutation-check.
>
> [I] UNCITED CLINICAL DIRECTIVES ON THE DL PATH
> "1.8 mL plain lidocaine IANB for hypertensive patients" — determine whether
> it carries a citation. Uncited -> the recommendation-traceability gate does
> not cover the DL path; extend it (this is the case-v3 uncited-directive
> class, confirmed on curriculum output). Cited but unsupported -> a
> verify_citation_support miss; add the pair to the adjudication set in [B] and
> report the split. Do NOT hand-edit the clinical content — fix the gate and
> regenerate.
>
> [J] CROSS-MODULE PROTOCOL CONSISTENCY — concrete fixtures for the queued pass
> Assert on the regenerated anesthesia curriculum that these do not recur:
> IANB volume stated as conclusive in one module and as no-difference in
> another while a third prescribes the lower volume; onset wait differing
> across modules; lip-numbness check interval differing across modules;
> supplemental-injection order differing across modules. Where the literature
> genuinely conflicts, the curriculum must SAY it conflicts and cite both sides
> once — a single reconciled statement reused across modules — never state each
> side flatly in different modules. Test on the stored fixture; mutation-check
> by re-injecting one conflict.
>
> Report per item: measurement table, cause, fix, test counts, eval delta, cost.

**[J] builds directly on `dl-quality-v1` Item 4**, which shipped the
deterministic detectors (`detect_parameter_conflicts`,
`detect_malformed_because`), the insertion-only annotation pass and
`consistency_guard`. [J]'s four fixtures are PROTOCOL conflicts rather than
concentration conflicts, so they need a detector of their own — the existing
one compares numbers attached to named agents, not recommendations attached to
clinical situations.


## 5e. Queued fourth — "citation-audit-v1" (RB, queued 2026-09-02, verbatim)

No dependency on the other batches. Its fixture,
`eval/fixtures/second_opinion_anesthesia_2026.md`, already exists in the repo.

> AUTONOMOUS BATCH — citation-audit-v1
> Standing rules apply (WORKLIST.md §0/§6): measure before changing; dry-run
> every DB write and report the delta split before applying; mutation-check
> every new test; real fixtures only; wip-commit before destructive git; push +
> refresh the OneDrive bundle at the end. Do NOT weaken any checker or gate
> during this batch. No journal-identity weighting anywhere (invariant 11).
> Tag citation-audit-v1.
>
> CONTEXT
> eval/fixtures/second_opinion_anesthesia_2026.md is a clinical answer produced
> by a general-purpose model with web search, restricted by its prompt to
> systematic reviews, meta-analyses, network meta-analyses and RCTs. It cites
> ~45-50 sources but gives NO PMIDs or DOIs — only journal + year + a reported
> statistic. The purpose of this batch is to run those citations through Curo's
> existing resolution and validation machinery and report, factually, how many
> survive. This is a diagnostic AND a demo asset. Build no new clinical content.
>
> [L1] EXTRACT THE CITATION MANIFEST
> Parse the fixture into eval/fixtures/second_opinion_citations.json, one record
> per citation INSTANCE (the same paper cited twice = two instances, linked by a
> shared resolved_id once resolved). Each record carries:
>   claim_text          the sentence the citation supports, verbatim
>   venue               journal string as written
>   year                as written
>   claimed_level       the bracketed tag: NMA / SR-MA / SR-MA+TSA / RCT /
>                       diagnostic / observational / consensus
>   reported_stats      every number in the claim, verbatim, with its unit or
>                       measure type (RR, OR, %, CI, SUCRA, I2, n, P)
>   self_flagged        true where the document itself flags the evidence as
>                       below its own stated bar
> Report the extracted count and the full manifest in the report before doing
> anything else. Expect roughly 45-50 instances; if the count is far off,
> stop and report rather than proceeding on a bad parse.
>
> [L2] RESOLVE EACH CITATION AGAINST PUBMED
> For each instance, search PubMed using the venue, year, and distinctive terms
> from the claim (design + population + intervention). Use the existing
> retrieval code paths, not ad-hoc queries. Classify every instance into exactly
> one of:
>   RESOLVED    a single paper matches venue + year + claim content unambiguously
>   AMBIGUOUS   plausible candidates exist but none is uniquely determined from
>               the information given
>   NOT_FOUND   no paper in that venue and year plausibly matches the claim
> Record the PMID for RESOLVED, the candidate PMIDs for AMBIGUOUS, and the exact
> queries tried for NOT_FOUND.
>
> CRITICAL METHODOLOGICAL RULE — do not violate this, the whole value of the
> batch depends on it: AMBIGUOUS AND NOT_FOUND ARE NOT EVIDENCE OF FABRICATION.
> Journal + year is genuinely insufficient to identify a paper, and Curo's own
> library coverage is finite. The report must state this explicitly and must
> never label an unresolved citation "fake", "hallucinated" or "fabricated". The
> only defensible claim is "not verifiable from the information the document
> provides". Any output that overstates this is a failed item, not a good
> finding.
>
> [L3] VALUE CHECK ON EVERYTHING THAT RESOLVED
> For each RESOLVED instance, fetch the full abstract and run the existing
> verify_citation_support path plus a numeric check. Report per instance:
>   - Does every number in reported_stats appear verbatim in the abstract, same
>     quantity and same unit? Apply the existing chart gates as text rules:
>     no range reported as a scalar, no unitless pair treated as comparable.
>   - Does the claim sentence describe what the abstract actually reports, or
>     does it transfer a figure from the whole review to a subgroup (the
>     n=19,223 misattribution class already seen in Curo's own anesthesia
>     output)?
>   - Is claimed_level correct against Curo's tier ladder for that paper,
>     derived from study design as always — never from the document's own tag?
> Classify each as SUPPORTED / PARTIAL (claim broader than the abstract) /
> UNSUPPORTED / NOT_CHECKABLE (abstract too thin to judge).
>
> [L4] TARGETED CHECKS ON KNOWN SUSPECTS
> Report these individually and by name, whatever the aggregate shows:
>   a. "dexamethasone ... RR 1.80; 95% CI from 1.35" — a confidence interval
>      with a lower bound and no upper bound is malformed. Determine whether the
>      source reports a complete interval and what it is.
>   b. The liposomal bupivacaine claim attributed to "Cochrane" with no review
>      named — identify which review, or record that it cannot be identified.
>   c. Every citation dated 2026 (at least: Int Endod J 2026, BMC Anesthesiol
>      2026) — confirm whether a 2026-dated record exists, including
>      epub-ahead-of-print.
>   d. The two distinct "SR/MA, Cureus 2025" citations (cryotherapy; magnesium
>      sulfate) — confirm they are two different papers, not one reused.
>   e. The Zanjir NMA 52% / 5,094 figure and the Int Endod J 2021 3.6 mL RR 1.94
>      (1.07-3.52) — these are load-bearing for the document's protocol; check
>      them with particular care.
>
> [L5] LIBRARY ACTION — additive only
> Papers that are RESOLVED, pass L3, and are absent from the library: ingest
> with full provenance (tier from study design, COI tri-state, MEDLINE status,
> retraction/supersession check). Dry-run with a delta split reported BEFORE
> applying. Do not ingest anything AMBIGUOUS or NOT_FOUND. Do not ingest on the
> strength of the document's description alone — only on the fetched record.
> After ingest, re-run the retrieval eval serially and report deltas against the
> current baseline; explain any case that moves.
>
> [L6] REPORT + DEMO ASSET
> Write eval/reports/citation_audit_v1.md containing:
>   - the counts: instances extracted, RESOLVED / AMBIGUOUS / NOT_FOUND, and
>     among RESOLVED the SUPPORTED / PARTIAL / UNSUPPORTED / NOT_CHECKABLE split
>   - the full per-instance table
>   - the five targeted findings from L4
>   - papers newly ingested, and eval deltas
>   - a plainly worded limitations paragraph restating the L2 rule
> Then generate ONE slide into the existing dark deck pipeline via the shared
> slide_spec_cache (both exports must consume the same spec, content hash
> asserted): a side-by-side of a single real example — the document's claim as
> written on the left, Curo's checker output for the same claim on the right.
> Pick the most defensible example available, in this order of preference:
> a RESOLVED-but-PARTIAL claim > a RESOLVED-but-UNSUPPORTED claim > an AMBIGUOUS
> one labelled exactly as "not verifiable from the citation as given". Every
> value on the slide must appear verbatim in the cited text and obey all chart
> gates. If no example clears those gates, produce NO slide and say so — a
> missing slide is a valid outcome and is far better than an overclaiming one.
>
> Report in §8 format. Refresh bundle, push, tag citation-audit-v1.

**Note for whoever runs it.** [L2]'s methodological rule is the load-bearing
part of this batch and it cuts against the instinct the rest of the repo
builds. Every other batch treats an unresolvable citation as a defect; here an
unresolvable citation is mostly a fact about what journal-plus-year can
identify. The existing machinery that comes closest is `verify_citation_support`
(does the abstract support the claim) and the fabrication half of
`validate_evidence_mapping` (was the PMID retrieved) — neither answers "does
this paper exist", and neither should be repurposed to imply it does.

Two pieces of it already exist and should be reused rather than rebuilt: the
claim-unit splitter (`_split_claim_units`) for [L1], because a citation's
supporting sentence is exactly a claim unit; and the chart gates
(invariant 2 — no range as a scalar, no unitless pair treated as comparable)
for [L3], which the item explicitly asks to apply as text rules.

## 5d. Queued last — "retrieval-honesty-v1" (paste-ready)

Autonomous batch on `main`, tag `retrieval-honesty-v1` at end. Standing rules
from `WORKLIST.md` §0/§6 apply in full, including the every-column backup rule.
Commit + push per item; re-bundle after commits.

**The theme.** Three of the last four batches ended with the same shape in
found-not-fixed: a step that silently substitutes something for what was asked
for, and nothing downstream can tell. Each is now measurable, and none has been
measured.

**ITEM 1 — A zero-hit query is broadened into a different topic.**
`fetch_papers` broadens once when a tier returns nothing. On an ordinary
question that widens the net; on a narrow one it changes the subject. Measured
incidentally in `case-v2.1`: a targeted dens evaginatus ingest cleared 48
papers through the quality floors and **23 of them did not mention the anomaly
at all** — "Single versus multiple visits for endodontic treatment", "Systemic
antibiotics for symptomatic apical periodontitis", "Materials for retrograde
filling in root canal therapy".

The ingest script gates its own write-back on relevance. **The live path does
not**, so a rare-presentation question can be answered out of general
endodontics with nothing saying the query changed.

Measure first: over the eval set plus a set of deliberately narrow questions,
how often does a broadened query return papers that do not contain the
distinctive term of the original? Then decide — a relevance gate on the
broadened result, or a badge on the tier saying "broadened; these papers may
be about the general topic", or both. Do not simply disable broadening: it was
added because thin tiers returned nothing at all.

**ITEM 2 — A `max_tokens` cap that silently disables a feature.**
`generate_case_differential` returned `[]` for a whole class of case because
its reply was truncated mid-JSON, and the turn was then answered on the
treatment path with no error anywhere. Fixed there — bigger cap, a parser that
salvages complete objects, a loud retry — but the shape is generic.

Sweep every JSON-returning generator: `generate_search_terms`,
`generate_multi_search_terms`, `generate_curriculum_syllabus`,
`generate_case_followups`, `classify_question_intent`, the slide-spec builder.
For each, ask two questions and answer them with a measurement, not a reading:
what is the observed output-token distribution against its cap, and what does
the caller do with a truncated reply? Anything that degrades to empty rather
than partial is bug class (d) with a token budget. Add the tolerant parse and
a one-line warning that names the function and the stop reason.

**ITEM 3 — The negative claim, and the judge's fourth verdict.**
This is the top P1 item and has been for two batches. A claim of the form "X
et al. did not report a final apical size", or "no paper in this evidence base
addresses Y", is TRUE, names the right paper, and **cannot pass the
citation-support check**, because an abstract cannot state what it omits. Seven
of the sixteen remaining Deep Learning flags are this, and it is the largest
class in the metric now that the claim-unit artifact is gone.

`_GROUNDING_RULE` explicitly asks for the move ("take the number from the paper
that reports it, or state that the cited study did not report it"), so the rule
and the checker disagree. Fix the CHECKER, not the rule: teach the judge a
fourth verdict — `negative_claim`, where the claim asserts the paper does NOT
report something, supported if and only if the abstract indeed does not.
Measure on the Deep Learning subset before and after with the artifact split
hand-judged, the way `eval/logs/dl_flag_verdicts_guardrails.json` was. Do NOT
weaken the checker in any other direction to make the number move.

**ITEM 4 — `_SUPPORT_MAX_PAIRS = 30`.**
It binds on every curriculum module and harder than it used to: the last live
run measured `total_pairs` 43 / 37 / 33 / 34 against `checked` 30 — **27 pairs
of 147, 18%, never looked at**. The rendered block names the remainder, so it
is honest rather than silent. Nobody has measured what raising it would find.
It costs Haiku calls (~$0.005 per 30 extra pairs) and nothing else. Raise it to
cover a full module, re-measure the Deep Learning flag rate, and report whether
the unchecked tail flags at the same rate as the checked head — if it does not,
the cap has been biasing the metric as well as limiting it.

**ITEM 5 — Close.** Full suite; `--case-subset` and `--synthesis-subset`;
report in §8 format; update this file; bundle; push; tag.

**Not in this batch, deliberately.** The Review path's composite-principle
residual (2 of 10 recommendations cite a general principle assembled across two
papers) needs the retry comparison first — generate the retries the OLD prompt
would have produced and check whether they were better or the same. That is a
~$3 experiment and its own small piece of work; folding it in here would put a
third change on the citation-support metric in one batch.


## 6. What only RB can do

1. Listen to 60 s of laser audio spanning "apexification" — confirm or clear
   the pronunciation flag.
2. Rehearse the demo on the presenting machine. **The cached answers AND the
   laser curriculum were re-warmed 2026-09-01 13:45 on `guardrails-v1`, and the
   runbook timings are re-measured** — cold Review **55-70s at ~$0.85** (down
   from ~$1.28; the retry that caused the rise is gone, and the runbook
   explains the round trip), cached 0.5-1.0s, cold curriculum **7.5 min at
   $1.17**. All six cached entries verified served-from-cache after the warm.
   The curriculum WAS regenerated this time: the claim-unit fix changes the
   citation-support line every module prints.
3. Decide when the vision/X-ray conversation with counsel happens.
4. **Keep the OneDrive backup zip private — it contains `.env`** — or re-zip
   without it.
5. Session hygiene: start new agent sessions from this file; `/compact` only at
   committed boundaries.
6. **Decisions already taken, do not re-open without a new reason.**
   `narrate: auto` stays on; `monthly_maintenance.py` first runs `--apply`
   AFTER the demo (it rescores, and a rescore DELETEs `query_cache` — the warm
   answers are the asset). Both are recorded with their reasoning in
   `HANDOVER.md`, "Decisions taken (RB, 2026-09-01)". The claim-unit question
   from that entry is now DONE (`guardrails-v1`), and the traceability question
   is decided and written up in `HANDOVER.md` under "Should a clinical
   recommendation always be traceable?" — yes, and the retry was avoidable.
7. **One judgement call is waiting**, and it is small: `_SUPPORT_MAX_PAIRS = 30`
   leaves 18% of a curriculum's cited claims unchecked (27 of 147 on the last
   run). The block says so honestly. Raising it costs Haiku calls (~$0.005 per
   30 extra pairs) and nothing else. Nobody has measured what it would find.

## 7. Environment notes the fresh session will otherwise rediscover the hard way

- Two server configs in `.claude/launch.json`. Use **`endo-ai-noreload`** (port
  5003). It does NOT pick up code changes — restart it after editing. **Check
  `curl -s localhost:5003/health` against `git rev-parse --short HEAD` before
  trusting anything it serves or writes**; `git_revision` is frozen at import,
  so a mismatch means the process is old. This is not theoretical: during
  `guardrails-v1` a server started 80 minutes earlier wrote 13 pairs into an
  eval measurement window, and was identified by exactly this field.
- **A running server is a writer, AND RB MAY BE USING IT.** During the
  `case-v3` close, an eval subset run and a live Deep Learning curriculum
  collided: the harness excluded 58 foreign citation-support pairs and then
  the fourth case died on `WinError 10054 — connection forcibly closed`, which
  the pid guard cannot prevent because the contention is for the PubMed and
  Anthropic rate limits, not the log file. **Check for a live job before you
  kill or restart anything** — `curl -s localhost:PORT/status/<job>` — and
  re-run the affected case rather than killing the user's work. The stale 5003
  server had been idle for 97 minutes and then served a real user question;
  "idle" is not "abandoned". Stop a server before a measurement you intend to
  report, or expect the "written by another process and EXCLUDED" note. `evidence_mapping.jsonl` and `pubmed_audit.jsonl` both carry a writer
  pid now, and both readers exclude foreign rows and say so.
- **Eval runs cannot overlap, and NEITHER CAN A PYTEST RUN.** `tests/conftest.py`
  redirects all three audit logs to tmp, so the suite no longer contaminates —
  but it still hits the same PubMed rate limit. Do not run the suite during a
  measurement you intend to report.
- **LibreOffice is not installed.** Render PPTX→PNG with PowerPoint COM from
  PowerShell (`$pres.Slides($n).Export($path, "PNG", 1280, 720)`).
- Bash heredocs mangle regex escapes AND line-continuation backslashes. This
  has now cost eight debugging cycles across four batches. **Use the
  Write/Edit tools for any Python containing a backslash or nested quotes** —
  and for any multi-line string replacement, which is where it bit again in
  `guardrails-v1`.
- **A MUTATION HARNESS MUST NEVER RUN WHILE A GENERATION IS IN FLIGHT.** It
  rewrites `endo_ai.py` once per mutant. An already-imported module is safe,
  but anything imported lazily inside a function is not, and the failure would
  be silent and unreproducible. Done carelessly once during `dl-quality-v1`;
  the generation survived, which is luck rather than a guarantee.
- **A `` written through a shell heredoc arrives as 0x08, a BACKSPACE.** The
  regex compiles, runs, and matches nothing — a filter that never fires. It
  happened to `_PARAM_AGENT_HEAD` in `dl-quality-v1` and survived two repair
  attempts. Build any regex line with `chr(92)` so no backslash literal passes
  through the shell, and scan for it with:
  `[n for n in dir(endo_ai) if isinstance(getattr(endo_ai,n), re.Pattern) and chr(8) in getattr(endo_ai,n).pattern]`
- Set `PYTHONIOENCODING=utf-8` on every python invocation. `PYTHONUTF8=1`
  additionally fixes the SOURCE decoding of a script piped in on stdin —
  without it, a heredoc containing `…` or `—` is mangled before Python parses
  it, and the failure looks like a string that will not match.
- **A `[SKIP] anchor found N times` from a mutation harness is an UNKILLED
  mutant, not a passing one.** It was never applied. Two anchors in `case-v3`
  matched both the Review and the case completion blocks, which are identical
  but for one line.
- **A mutation harness must clean strays BETWEEN mutants, not at the end.** A
  file leaked by mutant N is in mutant N+1's "before" state, and a before/after
  comparison then passes while the leak is happening.
- **THE HARNESS MUST REFUSE TO START ON A RED BASELINE.** `dl-quality-v1`'s
  first run reported 16 kills of 16 and proved nothing: it named a test file
  that did not exist, so pytest exited non-zero on every mutant for that
  reason. `restored: DIRTY` on the last line was the only clue. With a green
  baseline the same 16 mutants produced 5 survivors.
- **Keep the mutant test list to the files that hold the assertions.** Adding
  two merely-related curriculum test files took each mutant from 2s to 75s and
  the run from 40 seconds to an hour.
- **When a mutant survives, it is one of three things and they need different
  fixes:** a weak test (rewrite it behaviourally), a broken mutant (`frozenset()
  or frozenset(...)` returns the second operand and mutates nothing), or
  REDUNDANT CODE — measure whether the line changes any real verdict, and if it
  does not, delete it.
- **A same-length mutation can leave a stale `.pyc`.** `rm -rf __pycache__`
  after every mutation restore.
- **Never truth-test an ElementTree element.** `find(a) or find(b)` discards a
  valid childless `<PMID>12345</PMID>`. Use `is None`. And never use `.//PMID`
  on a PubMed record — the CommentsCorrectionsList has PMIDs of its own.
- **The judge is not deterministic.** Two runs of `verify_citation_support`
  over the identical 238 pairs returned 19 and 29 flags (8.0% and 12.2%).
  Any before/after on this metric needs repeats per arm, or it cannot
  attribute anything smaller than that spread.
- **Never put a real PMID in a prompt example.** A worked example naming two
  PMIDs from the evidence base of the question being measured scored 10/10 and
  the model copied those two PMIDs 27 times in 10 answers. Describe the shape.
- **The re-warm evicts before its cold pass**, and a $0 cold pass is now a hard
  error. It did not, and against a warm cache it would have re-warmed nothing
  while printing a full set of timings.
- Watch the Anthropic credit balance. It ran out mid-batch on 2026-08-31; the
  first symptom was `APIConnectionError` retries and a router "failing safe",
  not a billing message. `guardrails-v1` cost **$36.37**, of which $22.51 is
  labelled `source: script` in `cost_log.jsonl` — measurement, not product.
- Parallel agents: give each lane exclusive file ownership and a per-agent
  scratch directory, and stage commits BY FILENAME — `git add -A` in one lane
  sweeps another lane's half-finished work.

