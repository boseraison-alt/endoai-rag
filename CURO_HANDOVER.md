# CURO — Session Handover & Next Steps

Start a FRESH Claude Code session and open with:

> Read CURO_HANDOVER.md, HANDOVER.md, and WORKLIST.md, then execute §5 of
> CURO_HANDOVER.md.

Do not continue the old session — it is near its context limit and will
auto-compact.

---

## 1. What Curo is right now (state as of tag `grounding-v1`)

An evidence-graded endodontics assistant: **2,350-paper** curated library (Neon
Postgres + pgvector) with per-paper provenance (evidence tier incl. in vitro,
COI tri-state, retraction/withdrawal/supersession, MEDLINE status,
pre-registration), live PubMed fallback with synonym-expanded queries and an
authority guarantee (Cochrane-tier + top Level I papers can never be dropped by
query variance), tier-banded synthesis with a fabrication validator + a
citation-support check **on all three answer paths**, streaming answers,
Review-mode conversation memory, case discussion on the full evidence engine,
and five export styles — audio/video/slides/podcast and a self-contained
reveal.js web deck — all generated from ONE cached slide-spec in the approved
dark design. **1,269 tests**, all mutation-checked. **25-case retrieval eval**
with a 3-run baseline (`eval/baseline_v6.json`, all 25 cases × 3 runs, 25/25
passing) and its run logs archived beside it in `eval/logs/`.
Backups: git bundle + DB export + full zip on OneDrive Desktop, GitHub live.

**The numbers that describe the current state:**

| | |
|---|---|
| citation-support flag rate, measured Review cases | **4.3%** (2/46), from 8.5% and 39.4% |
| library abstracts still truncated | **1** — PMID 25231145, whose PubMed abstract genuinely is 1,200 characters |
| mean stored abstract length | **1,631** chars (was 1,182) |
| library rows with no abstract in PubMed at all | 4, individually confirmed |
| retrieval baseline | `eval/baseline_v6.json` — 25 cases × 3 runs |
| Deep Learning support check, first ever measurement | **20.3%** (24/118) and **11.2%** (13/116) on two laser curricula |
| tests | 1,269 passing, 39 skipped |

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
(full abstracts end to end, baseline v6, DL support check).

Bundle: `~/OneDrive/Desktop/endo-ai-rag_backup.bundle`.

## 4. Backlog — prioritized, with source

### P1 (correctness / trust)

- **The synthesis prompt still has no grounding rule.** It mandates a
  `[[PMID:N]]` marker on every standalone clinical claim and says nothing about
  what to do when no retrieved paper supports one; the corrective-retry message
  pushes the same way. This is the remaining mechanism behind decorative
  citations, and the one that applies on the LIVE path. **This is the single
  highest-value item left** and it is §5[A] below.
- **The "longest paragraph" abstract heuristic still loses paragraphs.**
  `ingest_classics.py:219-232` and `app.py`'s `/api/abstract` both keep only
  the longest paragraph of a fetched abstract. Same data-loss class as the
  truncation just fixed, different mechanism, untouched by that fix.
- **112 library rows returned nothing from efetch** during the repair. 4 have
  no abstract in PubMed at all (confirmed individually); the other 108 were not
  investigated. Some may be book records or withdrawn entries; some may be a
  fetch bug.
- 8 library rows have an empty `title`, which now reaches the prompt as a blank
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
- Narration↔deck slide sync (13 segments vs 34 slides) — per-slide cuts.
- Cancelled exports log no TTS cost row for characters already spent.
- "apexification" pronunciation: needs a HUMAN listen (RB).
- `narration.strip_markdown_for_speech` does not strip blockquotes. Harmless
  today — every narration path rewrites through an LLM first — but a raw
  narration path would read the citation-support blocks aloud.

### P3 (before any real users)

- Single-process job store (restart kills jobs).
- Multi-user: auth, per-user history, the admin secret model.
- PHI/X-ray path stays OFF until a BAA exists (decision recorded).
- Second literature database (Embase/Scopus).
- Monthly maintenance loop: provenance backfill + rescore + eval.

## 5. Next batch — "overnight-2" (paste-ready for the fresh session)

Autonomous batch on `main`, tag `prompt-v1` at end. Standing rules from
`WORKLIST.md` §0/§6 apply in full **except the branch rule** — §6 still says
"never commit to `main`", which the last three batches have overridden by
explicit instruction. Work on `main`.

**Sequencing.** [A] is the measured item and must run alone — it is the whole
point of the batch, and the last two batches attributed cleanly only because
they changed one thing at a time. [B], [C] and [D] are independent of it and of
each other and can run as parallel lanes with exclusive file ownership. [A]'s
before/after runs are strictly serial with every other eval run.

**The baseline to beat, so nobody has to go looking for it:** 2/46 = **4.3%**
across `single-vs-multiple-visit`, `naocl-concentration` and
`pips-vs-ultrasonic`, measured 2026-09-01 with the answer cache bypassed.

**[A] The grounding rule.** Add to the `ask_clinical_question` system prompt an
explicit instruction that a `[[PMID:N]]` marker asserts the cited paper states
the sentence, and that a claim no retrieved paper supports must be dropped or
written without a marker. Soften the unattributed-claims corrective message the
same way. **Measure it exactly as the last two batches measured their fixes**:
`--synthesis-subset --id` for `single-vs-multiple-visit`, `naocl-concentration`
and `pips-vs-ultrasonic` before and after, and add ONE live-pinned Review case
so the live path is measured too. Current baseline to beat: **2/46 = 4.3%**
across those three. Report the flag rate per case with the cost beside it.
Change nothing else in the same batch — the last two batches attributed cleanly
because they did not.

**[B] The longest-paragraph heuristic.** Fix `ingest_classics.py:219-232` and
`app.py`'s `/api/abstract` to keep the whole abstract, then measure how many
library rows are multi-paragraph-collapsed and repair them with the same
dry-run-then-apply shape as `scripts/repair_truncated_abstracts.py`. That
script is idempotent and resumable — verified: a second run reports 0 changes —
so model the new one on it, **including backing up every column it overwrites**
(see the standing rule added to `WORKLIST.md` §6; the abstract repair backed up
abstracts and not embeddings, and the old vectors are gone).

**[C] The 108 unexplained efetch misses.** Take the PMIDs the repair could not
fetch, classify them (book record / withdrawn / bad id / fetch bug), and fix
whichever is a bug. Also backfill the 8 empty titles while you are there — they
now reach the prompt as a blank line where the paper's subject should be.

**[D] Chase the DL flag rate.** The Deep Learning support check has now been
measured for the first time: 24/118 (20.3%) and 13/116 (11.2%) on two laser
curricula. Nobody has yet looked at WHY a curriculum module flags higher than a
Review answer. Hand-judge 20 flagged pairs from a curriculum the way §5[B] of
`eval-v5` did for Review, and report the split before fixing anything.

Report in §8 format; refresh bundle; tag `prompt-v1`.

### Environment notes the fresh session will otherwise rediscover the hard way

- Two server configs in `.claude/launch.json`. Use **`endo-ai-noreload`** (port
  5003). It does NOT pick up code changes — restart it after editing.
- **LibreOffice is not installed.** Render PPTX→PNG with PowerPoint COM from
  PowerShell (`$pres.Slides($n).Export($path, "PNG", 1280, 720)`).
- Bash heredocs mangle regex escapes AND line-continuation backslashes. This
  has now cost seven debugging cycles across three batches. **Use the
  Write/Edit tools for any Python containing a backslash or nested quotes.**
- Set `PYTHONIOENCODING=utf-8` on every python invocation.
- **Eval runs cannot overlap.** `run_eval` measures esearch from a byte offset
  into `pubmed_audit.jsonl`; any concurrent PubMed retrieval corrupts it.
  Library-pinned cases issue no esearch and are safe to run alongside.
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
   regenerated 2026-09-01 and the runbook timings are re-measured** — cold
   Review is now 55-120s and a cold curriculum 8.0 min at $1.52.
3. Decide when the vision/X-ray conversation with counsel happens.
4. **Keep the OneDrive backup zip private — it contains `.env`** — or re-zip
   without it.
5. Session hygiene: start new agent sessions from this file; `/compact` only at
   committed boundaries.
6. Decide whether to chase the last of the citation-support flag rate. It is
   4.3% on the measured Review cases, from 39.4% two batches ago. §5[A] is the
   remaining known mechanism; below a few percent the next gain probably costs
   more than it returns.
