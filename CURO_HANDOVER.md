# CURO — Session Handover & Next Steps

Start a FRESH Claude Code session and open with:

> Read CURO_HANDOVER.md, HANDOVER.md, and WORKLIST.md, then execute §5 of
> CURO_HANDOVER.md.

Do not continue the old session — it is near its context limit and will
auto-compact.

---

## 1. What Curo is right now (state as of tag `grounding-v2`)

An evidence-graded endodontics assistant: **2,350-paper** curated library (Neon
Postgres + pgvector) with per-paper provenance (evidence tier incl. in vitro,
COI tri-state, retraction/withdrawal/supersession, MEDLINE status,
pre-registration), live PubMed fallback with synonym-expanded queries and an
authority guarantee (Cochrane-tier + top Level I papers can never be dropped by
query variance), tier-banded synthesis with a fabrication validator, a
**grounding rule on all three synthesis prompts**, and a citation-support check
**on all three answer paths** that now reads the WHOLE abstract, streaming
answers, Review-mode conversation memory, case discussion on the full evidence
engine, and five export styles — audio/video/slides/podcast and a
self-contained reveal.js web deck that now **auto-advances with its own
narration** — all generated from ONE cached slide-spec in the approved dark
design. **1,377 tests**, all mutation-checked. **25-case retrieval eval** with
a 3-run baseline (`eval/baseline_v6.json`) whose harness now measures the
citation-support flag rate per case, on both routes.
Backups: git bundle + DB export + full zip on OneDrive Desktop, GitHub live.

**The numbers that describe the current state:**

| | |
|---|---|
| citation-support flag rate, LIVE Review path | **0.0%** (0/51), from 20.6% (7/34) — p = 0.0011 |
| citation-support flag rate, library Review path | **~8.9%** (4/45) — quote this, not 4.3%; see the note below |
| citation-support flag rate, Deep Learning | **13.3%** (32/240) — **a regression, under investigation**, from 8.5% before the grounding rule |
| Deep Learning genuinely-unsupported rate, hand-judged | **3.0%** (7/234) — 81% of what the checker flags is artifact |
| abstract excerpt the support judge sees | the **whole abstract** (was the first 1,200 chars) |
| stored rows whose "abstract" was not an abstract | **179 found, 124 healed**; 40 left are records PubMed has no abstract for |
| library abstracts still truncated | **1** — PMID 25231145, whose PubMed abstract genuinely is 1,200 characters |
| mean stored abstract length | **1,631** chars (was 1,182) |
| retrieval baseline | `eval/baseline_v6.json` — 25 cases x 3 runs |
| web-deck auto-advance | **ON** — 21 segments == 21 slides, verified with ffprobe |
| maintenance script | **built, dry-run end to end, NOT scheduled** — RB decides when it first runs `--apply` |
| tests | **1,377** passing, 39 skipped |
| **stale process** | **PID 35820 is still serving `grounding-v1` code.** Restart before trusting anything it serves or writes. Item 0 of the next batch. |

**Which run each rate comes from, because they are not all the same run.**
The library and Deep Learning figures above are the **grounding-rule** run,
which is the one that isolates the change RB approved. A later single run that
also carried the whole-abstract fix measured library **6.3%** (3/48) and DL
**13.0%** (31/239). Neither pair is significant on its own — library
before-vs-after is p = 1.0 and DL p = 0.11 — so the conservative figures are in
the table and the later ones are here. **Do not quote 4.3% as the library
baseline at all**: the same three cases measured 8.2%, 8.9% and 6.3% across one
night, with nothing changed between the first two.

**What changed in `grounding-v2`.** Read `OVERNIGHT_REPORT_2.md` for the whole
thing. In one paragraph: the synthesis prompts got a grounding rule saying what
a `[[PMID:N]]` marker asserts and what to do when nothing supports a claim; the
citation-support judge stopped being shown only the first 1,200 characters of
an abstract (the last truncation in the pipeline, sitting on the guardrail);
124 rows whose stored "abstract" was an author-affiliation list or a
foreign-language translation were healed; and the web deck records its own
per-slide narration so auto-advance works. All 37 Deep Learning citation flags
were hand-judged — 81% are artifacts of the checker, not bad citations. The
"longest paragraph loses conclusions" hypothesis that had been on the backlog
for three batches was **measured and found false**; the real defect was the
opposite one.

**What changed in `grounding-v1`.** Every library abstract is now stored and
sent at full length. 1,342 of 2,350 rows (57%) had been cut at ingest at
exactly 1,000 or 1,200 characters — and structured abstracts put CONCLUSIONS
last, so the finding was the part that was missing. Six ingest sites fixed,
1,355 rows re-fetched, re-embedded and rescored. Combined with the `eval-v5`
fix that put abstracts into the prompt at all, the citation-support flag rate
on the measured Review cases went **39.4% → 8.5% → 4.3%**. Deep Learning got
the support check it had never had (first measurement: 11–20% per curriculum).

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

Recurring bug classes (see `HANDOVER.md`): trusted stored labels, untagged
PubMed query terms, batch-metadata applied per-paper, fail-open checks that
show nothing, tests that grep source instead of asserting on the prompt/data
actually used.

## 3. Tag timeline (rollback points)

`mvp-demo` → `mvp-demo-2` → `presentation-v1` → `demo-polish` → `case-v1` →
`eval-v5` (baseline v5, library evidence block, deck P2s) → `grounding-v1`
(full abstracts end to end, baseline v6, DL support check) → `grounding-v2`
(grounding rule, whole-abstract support judge, collapsed-abstract repair,
web-deck auto-advance, maintenance script).

Bundle: `~/OneDrive/Desktop/endo-ai-rag_backup.bundle`.

## 4. Backlog — prioritized, with source

### P1 (correctness / trust)

- **P0 / Item 0 of the next batch — the running server is on stale code.**
  PID **35820** has been up since before `grounding-v2` and has the
  `grounding-v1` `endo_ai` imported; `endo-ai-noreload` does not pick up code
  changes by design. Anything it serves or writes back is pre-batch. There is
  no way to tell from the outside, which is the actual defect: **`/health`
  should report the git hash it is running.** Restart first, every time.
- **The grounding rule and the recommendation-traceability gate pull in
  opposite directions, and every collision costs a full retry.** The Review
  prompt requires the CLINICAL RECOMMENDATION to carry a `[[PMID:N]]` on its
  load-bearing claim; `_GROUNDING_RULE` says do not attach one you cannot
  ground. When both apply the model leaves it unmarked,
  `validate_evidence_mapping` fails the answer `UNTRACEABLE_RECOMMENDATION`,
  and a whole answer is regenerated at ~$0.34. **6 of 8 attempt-1 failures
  after the rule are that reason, against 0 of 2 before** (0/35 vs 6/89,
  Fisher p = 0.18 — directional, not proven), and it is the main reason a demo
  Review answer went from ~$0.79 to ~$1.28. It may be that the recommendation
  genuinely SHOULD always be traceable and the retry is the system working.
  Measure it; do not guess.
- **The claim-unit artifact is 35% of Deep Learning citation flags.**
  `_extract_claim_citation_pairs` has no rule for a curriculum's
  `IF / THEN / BECAUSE` decision tree or its Clinical Protocol Summary table,
  so a seven-branch tree becomes ONE claim carrying seven markers and produces
  seven flags from one blob. Hand-judged: 13 of 37 flags. It is the largest
  remaining single cause in this metric, and it needs its OWN batch — the last
  change to that splitter reversed its expected direction (merged claims were
  flagged LESS, p=0.002), so a confounded run would teach nothing.
- **`_SUPPORT_MAX_PAIRS = 30` still caps coverage on every curriculum module.**
  The rendered block now names the remainder ("8 further cited claim(s) were
  NOT checked"), so it is honest rather than silent, but 8 of 38 pairs on one
  real module still go unchecked. Raising it costs Haiku calls and nothing
  else; nobody has measured what it would find.
- **112 library rows returned nothing from efetch** during the `grounding-v1`
  repair. 4 have no abstract in PubMed at all (confirmed individually); the
  other 108 were not investigated. Some may be book records or withdrawn
  entries; some may be a fetch bug.
- **`ingest_aae_guidelines`'s PubMed harvest is live for the first time.** Its
  abstract fetcher had never returned anything (entry separator `^(\d{5,9})\.`
  against PubMed's `1. `, `2. `), so every record it fetched was dropped by
  `len(abstract) < 60`. Fixed in `grounding-v2`. **Dry-run that script before
  running it** — nobody has seen what it ingests.
- **`pubmed_audit.jsonl` and `cost_log.jsonl` are still unguarded shared
  state.** `evidence_mapping.jsonl` now carries a pid on every
  citation-support record because a concurrent pytest run corrupted an eval
  measurement through it. The same class will come back through the other two.
  `cost_log.jsonl` currently holds **$5.70 of imaginary spend** from stubbed
  TTS in the test suite; the suite no longer writes there, and the rows were
  left in place rather than editing an append-only log.
- **The Deep Learning grounding regression is unexplained.** 8.5% -> 13.3%
  after the rule (p = 0.11, not significant, not dismissible either). The
  whole-abstract fix was expected to reverse it and moved it to 13.0%. Two
  candidates remain and neither is tested: the rule makes claims more numeric
  and more specific, so they cite deeper into abstracts; or the curriculum's
  claim UNIT amplifies each marker into several flags, so the same behaviour
  costs more flags here than on Review. Re-measure after the claim-unit fix
  before theorising further.
- **The case path has NO eval cases at all.** `--synthesis-subset` and
  `--live-subset` contain none, so `ask_case_question` is the one synthesis
  path whose grounding rule, retry behaviour and support-check outcome are
  entirely unmeasured. `max_tokens` was raised 2000 -> 6000 on a measurement
  that has never been repeated either.
- **Live-path PMID seeding.** `prior_pmids` seeds the candidate set only
  AFTER the routing gate has decided, and that ordering is the safety
  property — seeding before it would let a thread's earlier papers drag the
  route. It is correct today and load-bearing, and it is written down in one
  docstring and asserted nowhere. Needs a test that fails if the two are
  reordered.
- **`cost_log.jsonl` has no `source` field**, so a stubbed row and a real one
  are indistinguishable after the fact. The test suite wrote **$5.70 of
  imaginary spend** into it before `tests/conftest.py` redirected the path,
  and those rows are still there and still counted by `/admin/costs`. Adding
  `source` (`product` / `test` / `script`) lets the reader filter instead of
  requiring the log to be edited — an append-only audit log should not be
  rewritten after the fact.
- 8 library rows have an empty `title`, which reaches the prompt as a blank
  line where the paper's subject should be.

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
## 5. Next batch — "guardrails-v1" (paste-ready for the fresh session)

Autonomous batch on `main`, tag `guardrails-v1` at end. Standing rules from
`WORKLIST.md` §0/§6 apply in full, **including the every-column backup rule**.
Work on `main` (§6's "never commit to `main`" is superseded, as it has been for
the last five batches).

**The baselines to beat, so nobody has to go looking for them.** Measured
2026-09-01 with the answer cache bypassed, `python eval/run_eval.py
--synthesis-subset` and `--live-subset`. The harness prints these per case now.

| stratum | rate | note |
|---|---|---|
| Review, live-pinned (5 cases) | **0/51 = 0.0%** | do not regress this |
| Review, library-pinned (3 cases) | **4/45 = 8.9%** | 6.3% on a later single run |
| Deep Learning (2 laser curricula) | **32/240 = 13.3%** | was 8.5%; Item 3 |

**Do not quote 4.3% as the library baseline.** The same three cases measured
8.2%, 8.9% and 6.3% across one night with nothing changed between the first
two.

**Sequencing.** Item 0 first and alone. Items 1 and 2 both change measured
behaviour and must NOT share a run — 1 before 2, each with its own
before/after. Item 3 is a re-measurement that depends on Item 1 having landed.
Item 4 is independent and can run alongside anything (it owns the `cost_log`
plumbing and a test file, nothing else). Item 5 closes.

---

**ITEM 0 — Restart the server, and make it impossible to be fooled again.**

PID **35820** has been serving `grounding-v1` code throughout the whole of
`grounding-v2`; `endo-ai-noreload` does not pick up changes by design, and
nothing about the running process says which commit it is. Kill it, restart
it, and then close the actual defect: **`/health` must report the git hash it
is running** — resolved at import time, not per request. A request-time
shell-out reports the WORKING TREE, which is the opposite of what you want to
know. Add a test that the field is present and non-empty.

Five minutes, and it retires a whole class of "was that answer from the new
code?" that has now cost two batches.

**ITEM 1 — The claim unit. Runs alone.**

`_extract_claim_citation_pairs` treats a curriculum's `IF / THEN / BECAUSE`
decision tree and its `### Clinical Protocol Summary` table as ordinary prose,
so a seven-branch tree becomes ONE claim carrying seven papers' markers and
every one of them is judged against the whole blob. That is **13 of the 37**
hand-judged Deep Learning flags — the largest single remaining cause in this
metric. `eval/logs/dl_flag_verdicts.json` holds the per-flag reasoning;
`scripts/classify_dl_flags.py` regenerates the evidence.

Teach the splitter two shapes: a decision-tree branch ends at the next
`**IF**`, and a table row is its own claim. Measure with `--synthesis-subset`
before and after, and **report the split by shape** — decision tree, table
cell, prose — not just the total.

**This item must not share a batch with anything else that touches synthesis.**
The last change to this splitter reversed its expected direction: merged claims
were flagged LESS, 37.6% vs 50.8%, p=0.002, because a longer blob gives the
judge more surface on which to find something supported. A confounded run
teaches nothing.

**ITEM 2 — Reconcile the grounding rule with the traceability gate.**

The Review prompt requires the CLINICAL RECOMMENDATION to carry a `[[PMID:N]]`
on its load-bearing claim. `_GROUNDING_RULE` says do not attach one you cannot
ground. When both apply, the model leaves it unmarked,
`validate_evidence_mapping` fails the answer `UNTRACEABLE_RECOMMENDATION`, and
a whole answer is regenerated at ~$0.34. **6 of 8 attempt-1 failures after the
rule are that reason, against 0 of 2 before** (0/35 vs 6/89, p = 0.18 —
directional, not proven). It is the main reason a demo Review answer went from
~$0.79 to ~$1.28.

Decide it as a question about the PRODUCT, not about the metric: should a
clinical recommendation ALWAYS be traceable to a paper? If yes, the retry is
the system working and the cost is the price — write that in `HANDOVER.md` and
close the item. If no, the recommendation needs a way to say "this rests on the
evidence base as a whole" that the validator accepts and the renderer shows.
**Measure the retry rate and the cost per answer before and after, either way.**
Do not weaken the validator to make the retry go away.

**ITEM 3 — Re-measure the Deep Learning regression.**

8.5% → 13.3% after the grounding rule (p = 0.11: not significant, not
dismissible either). The whole-abstract fix was expected to reverse it and
moved it only to 13.0%. Two untested candidates remain: the rule makes claims
more numeric and more specific so they cite deeper into abstracts, or the
curriculum's claim UNIT amplifies one marker into several flags.

**Item 1 tests the second directly**, so run this AFTER it lands: regenerate
both laser curricula and report the rate with the artifact/genuine split,
hand-judged the way `eval/logs/dl_flag_verdicts.json` was. If it is still ~13%
with the claim unit fixed, the first candidate is what is left — and that is a
prompt question, not a checker question.

**ITEM 4 — A `source` field on `cost_log.jsonl`, and the last shared log gets
its contamination guard.**

A stubbed test row and a real product call are indistinguishable in that file
after the fact. The suite wrote **$5.70 of imaginary spend** into it before
`tests/conftest.py` redirected the path, and those rows are still there and
still counted by `/admin/costs`. Add `source` (`product` / `test` / `script`),
defaulting to `product`, and have `/admin/costs` show `product` by default
while still able to show everything. **Do not edit the historical rows** — an
append-only audit log is not rewritten after the fact. Rows without the field
read as `product`, and the $5.70 is documented in `OVERNIGHT_REPORT_2.md` §7.

Then close the class. `evidence_mapping.jsonl` carries a writer `pid` on every
citation-support record because a concurrent pytest run corrupted an eval
measurement through it. `pubmed_audit.jsonl` has the same shape and no guard.
Give it the same treatment, and add the test that would have caught the
original: a foreign-pid row inside a case's window must be excluded, and four
curriculum modules landing in the same second must NOT be.

While there: `prior_pmids` seeds the live candidate set only AFTER the routing
gate has decided, and that ordering IS the safety property — seeding first
would let a thread's earlier papers drag the route. It is correct today,
load-bearing, written down in one docstring and asserted nowhere. Add the test
that fails if the two are reordered.

**ITEM 5 — Close.**

Full suite. Re-warm SELECTIVELY: Items 1–3 change what Review and the
curriculum serve, so if any of them lands, run `python
scripts/regenerate_demo_assets.py --reviews-only` (~$6.40, ~8 min), and
regenerate the laser curriculum ONLY if Item 1 or Item 3 changed it. Items 0
and 4 change nothing that is served — do not pay for a re-warm on their
account. Then `OVERNIGHT_REPORT_3.md` in §8 format, update this file, refresh
the bundle, verify it, push, tag `guardrails-v1`.

**Not in this batch, deliberately.** The case path has no eval cases at all,
so `ask_case_question` is the one synthesis path whose grounding rule, retry
behaviour and support-check outcome are entirely unmeasured. Adding cases means
writing them, pinning them and baselining them — its own piece of work, and it
would confound every measurement above if done alongside. It is the first item
of the batch after this one.

### Environment notes the fresh session will otherwise rediscover the hard way

- Two server configs in `.claude/launch.json`. Use **`endo-ai-noreload`** (port
  5003). It does NOT pick up code changes — restart it after editing.
  **A server started before 2026-09-01 02:00 is still running `grounding-v1`
  code**: PID 35820 was up throughout this batch and has the pre-batch
  `endo_ai` imported. Restart it before trusting anything it serves or
  writes.
- **LibreOffice is not installed.** Render PPTX→PNG with PowerPoint COM from
  PowerShell (`$pres.Slides($n).Export($path, "PNG", 1280, 720)`).
- Bash heredocs mangle regex escapes AND line-continuation backslashes. This
  has now cost seven debugging cycles across three batches. **Use the
  Write/Edit tools for any Python containing a backslash or nested quotes.**
- Set `PYTHONIOENCODING=utf-8` on every python invocation.
- **Eval runs cannot overlap, and NEITHER CAN A PYTEST RUN.** `run_eval`
  measures esearch from a byte offset into `pubmed_audit.jsonl` and the
  citation-support flag rate from one into `evidence_mapping.jsonl`. Any
  concurrent PubMed retrieval corrupts the first; any concurrent
  `tests/test_end_to_end.py` used to corrupt the second, and did — nine rows
  inside one case's window turned 16/119 into 16/146. The suite now writes its
  audit logs to a tmp path and each support record carries its writer's pid, so
  the harness excludes foreign rows and says so. **Still: do not run the suite
  during a measurement you intend to report.**
- **A same-length mutation can leave a stale `.pyc`.** `cp` restoring a file
  whose size and mtime-second match the mutated one means Python reuses the
  cached bytecode and the "restored" run is still the mutant. `rm -rf
  __pycache__` after every mutation restore.
- **Never truth-test an ElementTree element.** `find(a) or find(b)` discards a
  valid childless `<PMID>12345</PMID>` because elements are falsy. Use
  `is None`. And never use `.//PMID` on a PubMed record — the
  CommentsCorrectionsList has PMIDs of its own.
- Watch the Anthropic credit balance. It ran out mid-batch on 2026-08-31; the
  first symptom was `APIConnectionError` retries and a router "failing safe",
  not a billing message.
- Parallel agents: give each lane exclusive file ownership and a per-agent
  scratch directory, and stage commits BY FILENAME — `git add -A` in one lane
  sweeps another lane's half-finished work. When a lane needs a file it does
  not own, it reports the patch and the orchestrator applies it after the
  owning lane lands. That worked cleanly across four lanes this batch.

## 6. What only RB can do

1. Listen to 60 s of laser audio spanning "apexification" — confirm or clear
   the pronunciation flag.
2. Rehearse the demo on the presenting machine. **The cached answers were
   re-warmed 2026-09-01 02:45 after the rescore invalidated them, and the
   runbook timings are re-measured** — cold Review 60-110s at ~$1.28 (up from
   ~$0.79; the drivers are named in the runbook), cached 0.5-1.0s, cold
   curriculum 8.0 min at $1.52. The laser curriculum was NOT regenerated: no
   change this batch touched what it serves.
3. Decide when the vision/X-ray conversation with counsel happens.
4. **Keep the OneDrive backup zip private — it contains `.env`** — or re-zip
   without it.
5. Session hygiene: start new agent sessions from this file; `/compact` only at
   committed boundaries.
6. **Three questions that used to sit here are now DECIDED** — the claim-unit
   fix as its own batch, `narrate: auto` staying on, and
   `monthly_maintenance.py` first running `--apply` after the demo. They are
   recorded with their reasoning in `HANDOVER.md`, "Decisions taken (RB,
   2026-09-01)", and queued as §5 Items 1 and 5 above. Do not re-open them
   without a reason that is not already in that entry.
