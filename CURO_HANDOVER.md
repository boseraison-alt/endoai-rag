# CURO — Session Handover & Next Steps

Start a FRESH Claude Code session and open with:

> Read CURO_HANDOVER.md, HANDOVER.md, and WORKLIST.md, then execute §5 of
> CURO_HANDOVER.md.

Do not continue the old session — it is near its context limit and will
auto-compact.

---

## 1. What Curo is right now (state as of tag `guardrails-v1`)

An evidence-graded endodontics assistant: **2,350-paper** curated library (Neon
Postgres + pgvector) with per-paper provenance (evidence tier incl. in vitro,
COI tri-state, retraction/withdrawal/supersession, MEDLINE status,
pre-registration), live PubMed fallback with synonym-expanded queries and an
authority guarantee (Cochrane-tier + top Level I papers can never be dropped by
query variance), tier-banded synthesis with a fabrication validator, a
grounding rule on all three synthesis prompts **reconciled with the
recommendation-traceability gate**, and a citation-support check on all three
answer paths that reads the whole abstract and **knows what shape of claim it
is judging**, streaming answers, Review-mode conversation memory, case
discussion on the full evidence engine, and five export styles — audio, video,
slides, podcast and a self-contained reveal.js web deck that auto-advances with
its own narration — all generated from ONE cached slide-spec in the approved
dark design. **1,440 tests**, all mutation-checked. **25-case retrieval eval**
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
| tests | **1,440** passing, 39 skipped |
| **`/health`** | reports the **git hash the process imported**, frozen at import. Check it before trusting any server. |

**Which run each rate comes from, because they are not all the same run.**
The library Review figure is the `grounding-v2` run. **Do not quote 4.3% as
the library baseline at all**: the same three cases measured 8.2%, 8.9% and
6.3% across one night, with nothing changed between the first two.

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
`source` + `pubmed_audit` pid guard).

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
- **The case path has NO eval cases at all.** `--synthesis-subset` and
  `--live-subset` contain none, so `ask_case_question` is the one synthesis
  path whose grounding rule, retry behaviour and support-check outcome are
  entirely unmeasured. `max_tokens` was raised 2000 → 6000 on a measurement
  that has never been repeated either. **This is §5's batch.**
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
## 5. Next batch — "case-v2": diagnostic reasoning in case discussion

Autonomous batch on `main`, tag `case-v2` at end. Standing rules from
`WORKLIST.md` §0/§6 apply in full, **including the every-column backup rule**.
Commit + push per item; re-bundle after commits.

**CONTEXT — a real failure, reproduce it first.** Case: *"20-year-old,
necrotic tooth, no restoration, no caries — what could the cause be?"* The
actual output centred on endodontic management and AAE guidance, never on the
etiologic differential (dens invaginatus, unrecognised dental trauma,
palatal/radicular groove, crack, orthodontic history), and the follow-up
questions included **bisphosphonate use** — clinically implausible at 20 and
non-discriminating for this presentation.

**ITEM 1 — Reproduce and diagnose.** Run that exact case through
`/case_chat`. Capture: the composed search query, the esearch/RAG queries, the
evidence-base tier table, and the follow-up questions asked. Confirm the
hypothesis — retrieval fetched management literature because the query never
contained any candidate etiology. Record the trace in the report **before**
changing anything.

**ITEM 2 — Intent split in case mode.** Classify each case turn (Haiku,
fail-open to treatment): DIAGNOSTIC ("what is the cause / diagnosis / why did
this happen") vs TREATMENT ("what should I do"). Treatment keeps the current
path unchanged.

**ITEM 3 — Differential-first retrieval for DIAGNOSTIC turns.**
a. Generate a differential: 3–6 candidate causes from the case description
   (Sonnet), each with the case features supporting it. Clinical-reasoning
   scaffolding, not final content.
b. Retrieve PER CANDIDATE: run the existing evidence engine once per candidate
   (candidate name + case features as the topic), union the evidence bases, tag
   each paper with its candidate. Cap total cost: candidates share the library
   gate; live fallback per candidate only when the library is thin for it.
c. Synthesis prompt for diagnostic answers: ranked differential — for each
   candidate, the case features for and against, and the cited evidence;
   most-likely first; explicitly state what examination or imaging would
   discriminate (CBCT for invaginatus, transillumination for crack, trauma
   history). Every claim cited; all existing gates (validation,
   citation-support, grounding) apply unchanged.
d. The answer must OPEN with the differential, not with management. Management
   advice may follow only after the differential, briefly.

**ITEM 4 — Follow-up question relevance.** The case-followups generator must,
for each candidate question, check: *given THIS patient's age and presentation,
would the answer plausibly change the differential or the plan?* Questions
failing that are dropped. Discriminating questions for this case class (trauma
history, orthodontic history, tooth type/location, sinus tract, imaging
available) should surface; checklist questions that do not discriminate
(bisphosphonates at 20) must not. Keep the never-re-ask rule (invariant 8)
intact.

**ITEM 5 — Pin it.** Add two eval cases:
(a) this exact case, DIAGNOSTIC — `must_contain`: dens invaginatus AND at least
    two other candidate causes, differential before management; `must_not`: any
    bisphosphonate follow-up question;
(b) a contrast case: *"68-year-old, osteoporosis on alendronate, needs
    extraction vs RCT decision"* — the bisphosphonate question MUST appear
    there, proving Item 4 filters by relevance rather than by deleting the
    topic.
Mutation-check both.

**ITEM 6 — Close.** Full suite; run both new eval cases live; OVERNIGHT-style
report with the Item 1 trace, before/after transcripts of the 20-year-old case,
and cost per diagnostic answer (expect higher — multi-candidate retrieval —
report the number); update this file; bundle; push; tag `case-v2`.

**Carried into this batch from `guardrails-v1`, because they touch the same
prompts:** nothing. The four P1 prompt/checker findings above (the negative
claim, the meta claim, the composite principle, `_SUPPORT_MAX_PAIRS`) each
change a number this batch also moves, and they belong to their own batch.
Do not fold them in.


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
- **A running server is a writer.** Stop it before a measurement you intend to
  report, or expect the harness's "written by another process and EXCLUDED"
  note. `evidence_mapping.jsonl` and `pubmed_audit.jsonl` both carry a writer
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
- Set `PYTHONIOENCODING=utf-8` on every python invocation.
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

