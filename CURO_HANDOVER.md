# CURO — Session Handover & Next Steps

Start a FRESH Claude Code session and open with:

> Read CURO_HANDOVER.md, HANDOVER.md, and WORKLIST.md, then execute §5 of
> CURO_HANDOVER.md.

Do not continue the old session — it is near its context limit and will
auto-compact.

---

## 1. What Curo is right now (state as of tag `case-v1`)

An evidence-graded endodontics assistant: 2,000+ paper curated library (Neon
Postgres + pgvector) with per-paper provenance (evidence tier incl. in vitro,
COI tri-state, retraction/withdrawal/supersession, MEDLINE status,
pre-registration), live PubMed fallback with synonym-expanded queries and an
authority guarantee (Cochrane-tier + top Level I papers can never be dropped by
query variance), tier-banded synthesis with a fabrication validator +
citation-support check, streaming answers (~15 s to first text, 0.4 s cached),
Review-mode conversation memory (evidence-fresh follow-ups, cache-partitioned
by thread context), case discussion on the full evidence engine (19 citations /
6 tiers vs the old 2), and five export styles — audio/video/slides/podcast
(OpenAI tts-1-hd + dental pronunciation dictionary) and a self-contained
reveal.js web deck with clickable PMID→abstract pills, all generated from ONE
cached slide-spec (content-hash asserted) in the approved dark design. ~1,112
tests, all mutation-checked. 21-case retrieval eval with baselines. Backups: git
bundle + DB export + full zip on OneDrive Desktop, GitHub remote live.

## 2. Invariants — never regress these (each has a guarding test)

1. Tier hierarchy is by study design, never by score; unknown design bands to
   the weakest tier. Score ranks only within a tier.
2. Every plotted chart value appears verbatim in cited text; same quantity, same
   unit, no ranges-as-scalars, no unitless pairs assumed comparable. A chartless
   deck is a valid outcome.
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
   match.
10. Cost is reported only beside hits-per-query and paper counts — never alone.

Recurring bug classes (see `HANDOVER.md`): trusted stored labels, untagged
PubMed query terms, batch-metadata applied per-paper, fail-open checks that show
nothing, tests that grep source instead of asserting on the prompt/data actually
used.

## 3. Tag timeline (rollback points)

`mvp-demo` → `mvp-demo-2` (retrieval consistency + speed) → `presentation-v1`
(dark decks, web deck, narration) → `demo-polish` (chart prompt, video
narration) → `case-v1` (case engine + review memory).

Bundle: `~/OneDrive/Desktop/endo-ai-rag_backup.bundle`.

## 4. Backlog — prioritized, with source

### P1 (correctness / trust)

- Re-run the 21-case retrieval eval + 5-case synthesis subset against `case-v1`
  and store `baseline_v5`: the case/memory batch changed shared signatures
  (builder kwargs, intent stub arity) and the eval was last baselined
  pre-`case-v1`. Any drift must be explained, not accepted.
- Citation-support flag-rate fault assignment (30–60% on some questions):
  hand-judge 20 flagged pairs → decide checker-too-strict vs
  synthesis-unsupported vs threshold; fix the guilty side.
- ~~PPTX repair-dialog root cause~~ — **ALREADY DONE**, see the note below.
- Live-path PMID seeding for follow-ups (MEDIUM from `case-v1`): seeds must pass
  per-tier floors inside `fetch_papers()`.

> **Annotation added when this file was written.** The two conditionals in the
> original draft ("if the earlier single-item brief was not yet run" / "skip if
> already fixed — check git log first") are resolved: **the PPTX repair issue
> was fixed in `6fca4d3`**. Root cause was `<p:audioFile>`, which is not an
> element — audio is `<a:audioFile>` in the DrawingML namespace — plus three
> further defects in the autoplay `<p:timing>` block. The correct structure was
> read back off a file PowerPoint itself authored over COM, after three
> hand-authored attempts failed. `scripts/validate_pptx.py` plus 14 offline
> tests in `tests/test_pptx_package_validity.py` now guard it in the standard
> suite. A deck generated through `/generate_slides` and downloaded as a user
> would opens with no prompt. **§5[C] should be skipped.**

### P2 (product polish)

- `cascade_slide` body overflows through the footer (budget split doesn't fire
  on that layout).
- `evidence_summary` renders a blank "REPORTED" column when no row carries a
  stat.
- Multi-arm (>2) comparisons unreachable (`slide_patterns` drops
  `categories`/`values`) — blocks the laser deck's best chart.
- Narration↔deck slide sync (13 segments vs 34 slides) — needs per-slide
  narration cuts.
- Cancelled exports log no TTS cost row for characters already spent.
- "apexification" pronunciation: needs a HUMAN listen (RB), then a one-line
  dictionary edit if confirmed.
- Add case-mode and follow-up cases to the eval set (the harness only covers
  Review retrieval).

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

Autonomous batch on `main`, tag `eval-v5` at end. Standing rules from
`WORKLIST.md` §0/§6 (measure first; dry-run DB writes with delta splits;
mutation-check every new test; real fixtures; wip-commit before destructive git;
push + re-bundle after every item; parallel agents never share files).

**[A] Re-baseline.** Run the retrieval eval 3× and the synthesis subset 1×
against `case-v1`. Write `eval/baseline_v5.json` with ranges. Diff against v4:
explain every case that moved (code change vs variance) in the report. Add 4 new
eval cases: one case-discussion opening (sparse), one case-discussion (full),
one Review follow-up thread (laser → "in immature teeth?"), one New-topic reset.
Pin expected behaviours from tests already in the suite.

**[B] Citation-support fault assignment.** Sample 20 flagged claim–abstract
pairs from recent runs, classify each (claim truly unsupported / checker too
strict / abstract truncated), report the split, then fix ONLY the majority
cause. Done when the flag rate on the 5-case synthesis subset changes in the
direction the classification predicts.

**[C] PPTX well-formedness — SKIP.** Already fixed in `6fca4d3`; see the
annotation in §4. Verify with `python -m pytest tests/test_pptx_package_validity.py -q`
(14 tests) rather than re-diagnosing.

**[D] The three deck P2s:** `cascade_slide` overflow, blank REPORTED column,
multi-arm comparisons. Each: reproduce on a real spec, fix, **view the rendered
output**, mutation-checked test. Multi-arm must obey every chart gate (same
quantity, same unit, all values verbatim, PMIDs in footer).

Report in §8 format; refresh bundle; tag `eval-v5`.

### Environment notes the fresh session will otherwise rediscover the hard way

- Two server configs in `.claude/launch.json`. Use **`endo-ai-noreload`** (port
  5003): the auto-reloader kills in-flight export jobs. It does NOT pick up code
  changes — restart it after editing, or you will verify against stale code.
- **LibreOffice is not installed.** Render PPTX→PNG with PowerPoint COM from
  PowerShell (`$pres.Export($dir, "PNG", 1280, 720)`). `pdftoppm` is absent too.
- Bash heredocs mangle regex escapes (`\b`, `\d`, `\n`) — this has cost four
  debugging cycles. Use the Write/Edit tools for anything with backslashes.
- The browser-pane screenshot fails when the pane is hidden ("not compositing
  frames"). Fall back to `javascript_tool` / `read_page` and say so.
- Never let a test append to the live `cost_log.jsonl` (autouse-fixture
  precedent in `tests/test_narration.py`).
- The agent scratchpad is **shared, not per-agent** — one agent overwrote
  another's file mid-run. Scope scratch paths per agent.

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
