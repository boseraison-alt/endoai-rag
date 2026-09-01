# CURO — Session Handover & Next Steps

Start a FRESH Claude Code session and open with:

> Read CURO_HANDOVER.md, HANDOVER.md, and WORKLIST.md, then execute §5 of
> CURO_HANDOVER.md.

Do not continue the old session — it is near its context limit and will
auto-compact.

---

## 1. What Curo is right now (state as of tag `eval-v5`)

An evidence-graded endodontics assistant: 2,350-paper curated library (Neon
Postgres + pgvector) with per-paper provenance (evidence tier incl. in vitro,
COI tri-state, retraction/withdrawal/supersession, MEDLINE status,
pre-registration), live PubMed fallback with synonym-expanded queries and an
authority guarantee (Cochrane-tier + top Level I papers can never be dropped by
query variance), tier-banded synthesis with a fabrication validator +
citation-support check, streaming answers (~15 s to first text, 0.4 s cached),
Review-mode conversation memory (evidence-fresh follow-ups, cache-partitioned
by thread context), case discussion on the full evidence engine, and five
export styles — audio/video/slides/podcast (OpenAI tts-1-hd + dental
pronunciation dictionary) and a self-contained reveal.js web deck with clickable
PMID→abstract pills, all generated from ONE cached slide-spec (content-hash
asserted) in the approved dark design. **~1,219 tests**, all mutation-checked.
**25-case retrieval eval** with a 3-run baseline (`eval/baseline_v5.json`) and
the run logs kept beside it. Backups: git bundle + DB export + full zip on
OneDrive Desktop, GitHub remote live.

**What changed in the `eval-v5` batch.** The library evidence block was
carrying no paper text at all — only a metadata line per paper — so a
library-served answer was written from about a fifth of the input a live-served
one got. Fixed; the citation-support flag rate on three library-pinned Review
cases went 39.4% → 8.5%. The eval harness was also found to be measuring
CACHED answers in synthesis mode; that is fixed and guarded. Three deck P2s
(cascade overflow, blank REPORTED column, multi-arm comparisons) are closed,
and an adversarial verification pass on those found seven further chart
defects, all fixed. Full detail in `HANDOVER.md`.

## 2. Invariants — never regress these (each has a guarding test)

1. Tier hierarchy is by study design, never by score; unknown design bands to
   the weakest tier. Score ranks only within a tier.
2. Every plotted chart value appears verbatim in cited text; same quantity, same
   unit, no ranges-as-scalars, no unitless pairs assumed comparable, **and the
   sign is part of the number**. A chartless deck is a valid outcome.
3. No raw `[[PMID:N]]` on any rendered surface (speaker notes exempt).
4. COI = named commercial entity in a non-negated declaration sentence, applied
   once at rescore from stored `coi_status`.
5. Cochrane tier is journal-verified; withdrawn/superseded versions excluded on
   both paths.
6. Zero-evidence modules never render a numeric protocol.
7. Follow-up cache entries are partitioned by `context_hash`; a follow-up must
   never hit a context-free cache row.
8. Case discussion never re-asks a fact present in the clinician's description.
9. Both deck exports consume the shared `slide_spec_cache`; content hash must
   match, **and for one spec they must make the same chart/no-chart decision**.
10. Cost is reported only beside hits-per-query and paper counts — never alone.
11. **Both retrieval paths show Claude the same KIND of thing.** A library-served
    paper and a live-served one both reach the prompt with their text, not just
    their metadata. Assert on the BLOCK, never on the renderer.
12. **An eval must not measure a stored artefact of an earlier run** — not the
    library it writes back to, not the answer cache, not a pinned route it only
    requested. A synthesis case that cost $0 is a failure, not a pass.
13. **Abstract text never reaches a browser.** `app._safe_papers` is the only
    enforcement point and must be applied at every exit that serialises papers.

Recurring bug classes (see `HANDOVER.md`): trusted stored labels, untagged
PubMed query terms, batch-metadata applied per-paper, fail-open checks that show
nothing, tests that grep source instead of asserting on the prompt/data actually
used.

## 3. Tag timeline (rollback points)

`mvp-demo` → `mvp-demo-2` (retrieval consistency + speed) → `presentation-v1`
(dark decks, web deck, narration) → `demo-polish` (chart prompt, video
narration) → `case-v1` (case engine + review memory) → `eval-v5` (baseline v5,
library evidence block, deck P2s).

Bundle: `~/OneDrive/Desktop/endo-ai-rag_backup.bundle`.

## 4. Backlog — prioritized, with source

### P1 (correctness / trust)

- **The synthesis prompt still has no grounding rule.** It mandates a
  `[[PMID:N]]` marker on every standalone clinical claim and says nothing about
  what to do when no retrieved paper supports one; the corrective-retry message
  pushes the same way. This is the SECOND mechanism behind unsupported
  citations and the one that still applies on the LIVE path, which flags at the
  same rate and never lacked abstracts. Deliberately left out of the `eval-v5`
  batch so the library-block measurement attributed to one change. **Do this
  next, and re-run the three library cases plus a live-pinned one.**
- **57% of library abstracts are truncated at ingest** (1342 of 2342; five call
  sites, `[:1000]` and `[:1200]`), and the CONCLUSIONS section is what gets
  cut — "conclusion" survives in 7.2% of truncated rows against 39.3% of whole
  ones. This caps the value of the block fix. Needs a re-ingest/repair pass, not
  a code change.
- **`verify_citation_support` never runs on the Deep Learning path.** Two call
  sites only: Review and Case. The longest, most citation-dense output the
  product makes is unchecked.
- Live-path PMID seeding for follow-ups (MEDIUM from `case-v1`): seeds must pass
  per-tier floors inside `fetch_papers()`.

### P2 (product polish)

- ~~`cascade_slide` body overflows through the footer~~ — **DONE (`eval-v5`).**
- ~~`evidence_summary` renders a blank "REPORTED" column~~ — **DONE.**
- ~~Multi-arm (>2) comparisons unreachable~~ — **DONE**, both exports, all
  gates. But no cached spec uses `arms` yet, so it has zero real-data coverage:
  generate a deck on a dose-response topic and look at it.
- `_unit_of` picks the wrong quantity's unit in "12 mm at 3 months" (returns
  `months`), so a chart can be axis-labelled from a number nobody plotted.
  Mislabelling, not invention; pre-existing on all three detectors.
- `case_convs` (`app.py:258`) is written, never read, and never capped.
- Narration↔deck slide sync (13 segments vs 34 slides) — needs per-slide
  narration cuts.
- Cancelled exports log no TTS cost row for characters already spent.
- "apexification" pronunciation: needs a HUMAN listen (RB), then a one-line
  dictionary edit if confirmed.
- `_extract_claim_citation_pairs` merges claims across bold pseudo-headings
  (36% of all pairs) and splits mid-sentence on "vs."/"e.g.". **Measured not to
  affect the flag rate** — fix for correctness, not for the metric.

### P3 (before any real users)

- Single-process job store (restart kills jobs) — document or move to a
  persistent queue.
- Multi-user: auth, per-user history, and the admin secret model.
- PHI/X-ray path stays OFF until a BAA exists (decision recorded).
- Second literature database (Embase/Scopus) if the "score like Cochrane" claim
  is to be strengthened.
- Library growth policy: write-back is on; schedule a monthly provenance
  backfill + rescore + eval run as a maintenance loop.

## 5. Next batch (paste-ready for the fresh session)

Autonomous batch on `main`, tag `prompt-v1` at end. Standing rules from
`WORKLIST.md` §0/§6 (measure first; dry-run DB writes with delta splits;
mutation-check every new test; real fixtures; wip-commit before destructive git;
push + re-bundle after every item; parallel agents never share files).

**[A] The grounding rule.** Add to the `ask_clinical_question` system prompt an
explicit instruction that a `[[PMID:N]]` marker asserts the cited paper states
the sentence, and that a claim no retrieved paper supports must be dropped or
written without a marker. Soften the unattributed-claims corrective message the
same way. **Measure it the way `eval-v5` measured the block fix**: run
`--synthesis-subset --id` for `single-vs-multiple-visit`, `naocl-concentration`
and `pips-vs-ultrasonic` before and after, and add ONE live-pinned Review case
to the subset so the live path is measured too. Report the flag rate per case,
and the cost beside it. Do not change anything else in the same batch.

**[B] Abstract repair.** Measure how many of the 1342 truncated rows are
re-fetchable from PubMed today, then write `scripts/repair_truncated_abstracts.py`
— dry-run by default, printing the delta split by tier and 20 random
before/after samples for review, idempotent, backup table first. Apply only
after the sample reads correctly. Then re-run the three cases from [A] and say
whether the flag rate moved again. Fix the five ingest call sites so new rows
are not truncated.

**[C] The citation-support check on the Learn path.** `ask_learn_question` and
the curriculum path have no call to `verify_citation_support`. Add it where the
answer is final, honour the existing fail-open contract, and make the outcome
visible in the curriculum the way it is in a Review answer. Measure the flag
rate on one curriculum run — it has never been measured.

**[D] Two more runs of the four new eval cases.** `case-opening-sparse`,
`case-opening-full`, `review-followup-immature-teeth` and
`review-newtopic-reset` have ONE observation each in `eval/baseline_v5.json`
(flagged there in `cases_with_one_run`). Run them twice more, fold in, and
remove the flag. Cheap, and it is what makes the other three items measurable.

Report in §8 format; refresh bundle; tag `prompt-v1`.

### Environment notes the fresh session will otherwise rediscover the hard way

- Two server configs in `.claude/launch.json`. Use **`endo-ai-noreload`** (port
  5003): the auto-reloader kills in-flight export jobs. It does NOT pick up code
  changes — restart it after editing, or you will verify against stale code.
- **LibreOffice is not installed.** Render PPTX→PNG with PowerPoint COM from
  PowerShell (`$pres.Export($dir, "PNG", 1280, 720)`). `pdftoppm` is absent too.
- Bash heredocs mangle regex escapes (`\b`, `\d`, `\n`) **and line-continuation
  backslashes** — this cost three more debugging cycles in the `eval-v5` batch,
  on top of the four before it. Use the Write/Edit tools for any Python
  containing a backslash or nested quotes.
- Set `PYTHONIOENCODING=utf-8` on every python invocation. The console is
  cp1252 and this codebase is full of em-dashes; without it, scripts crash on
  `print`, not on the work.
- **Eval runs cannot overlap.** `run_eval` measures esearch from a byte offset
  into `pubmed_audit.jsonl`, so any concurrent PubMed retrieval — a second eval,
  the app, an agent — lands in the window and corrupts the numbers. Run them
  strictly one at a time. Library-pinned cases issue no esearch and are safe to
  run alongside.
- The browser-pane screenshot fails when the pane is hidden ("not compositing
  frames"). Fall back to `javascript_tool` / `read_page` and say so.
- Never let a test append to the live `cost_log.jsonl` (autouse-fixture
  precedent in `tests/test_narration.py`).
- The agent scratchpad is **shared, not per-agent** — one agent overwrote
  another's file mid-run. Scope scratch paths per agent.
- Watch the Anthropic credit balance. It ran out mid-batch on 2026-08-31; the
  first symptom was `APIConnectionError` retries and an intent router "failing
  safe", not a billing message, and ~20 minutes of work was lost re-running a
  measurement.

## 6. What only RB can do

1. Listen to 60 s of laser audio spanning "apexification" — confirm or clear the
   pronunciation flag.
2. Rehearse the demo on the presenting machine: 4 cached questions, 1 live
   (bisphosphonates), web deck citation click, video clip. Use the
   `endo-ai-noreload` config.
3. Decide when the vision/X-ray feature conversation with counsel happens
   (feature stays off until then).
4. **Keep the OneDrive backup zip private — it contains `.env` with live API
   keys and the Neon connection string** — or re-zip without `.env`.
5. Session hygiene: start new agent sessions from this file rather than
   continuing long ones; `/compact` only at committed boundaries.
6. Decide whether the doubled cost of a library answer (~$0.36 → ~$0.70) is
   acceptable. It bought the flag rate going 39.4% → 8.5%, and the alternative
   was answers written from metadata alone — but it is a real recurring cost and
   it is your call, not the agent's.
