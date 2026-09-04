# SESSION HANDOVER — overnight 2026-09-04

Boot a new coding-agent chat with:

> Read `AGENT_QUEUE.md`, `SESSION_HANDOVER_2026-09-05.md` and `CURO_HANDOVER.md`.
> Continue from the ORDER section below.

Branch `overnight/browser-block-and-baseline`, **7 commits**, `ae20d3e..HEAD`.
Suite **2288 passed, 50 skipped, 1 failed** — the one failure is external, see §0.

---

## 0. READ THIS FIRST — THE ANTHROPIC API IS OUT OF CREDIT

```
400 invalid_request_error — "Your credit balance is too low to access the
Anthropic API." Confirmed on claude-haiku-4-5, i.e. it is not a model or a
routing problem.
```

It ran out at **~01:00 on 2026-09-04**, mid-batch. This is the failure mode
`CURO_HANDOVER.md` §7 warns about; last time the first symptom was
`APIConnectionError` retries and a router "failing safe", so it went unnoticed.
This time it is an explicit billing message on a `/case_chat` job.

**Everything that generates is blocked**, and that is most of what remains:

| parked | why |
|---|---|
| the v6 three-run re-baseline (item 7) | needs ~3.5h of live retrieval + synthesis |
| A37's full distribution (item 5) | needs n≥5 live clarify calls per case fixture |
| A22e's re-render | needs one live curriculum, ~$1.17 |
| **regenerating the four demo answers** | **the highest-value item on this list** |
| the Case answer surface on current code | verified on layout only |

`tests/test_metadata_extraction.py::test_metadata_distribution_in_real_batch`
is the one red test. It makes a live call. **It fails identically with every
change from tonight stashed** — verified, not assumed. The tree is otherwise
green.

**Restore credit first. Nothing else in the queue moves without it.**

---

## 1. THE ONE THING TO CARRY FORWARD

**Three premises fell tonight, and all three were instrument errors rather than
wrong hypotheses. One of them was in the instrument I wrote to find the other
two.**

`scan_split_items.py` looked for a bare `N.` list number. The corpus writes it
bold — `**3.**`. It reported **0 split list items**, and on that zero A22a and
the literal `**` leak were re-filed as renderer defects and moved to the browser
lane. Corrected: **30 of 116 stored blocks orphan a list number, 24 cut a bold
run in half.** Both are text-layer, in `quarantine_unsourced_content`.

Then the audit script written to sweep for that whole class reported 15
"unjustified zeros" on its first run. Twelve were line-anchored patterns
compiled without `re.MULTILINE`, applied to whole documents — they can only ever
return zero. **The instrument built to detect the signature manufactured it.**

That is rules 33 and 34, both added to `AGENT_QUEUE.md` §1.

Running total: **fifteen premises overturned by measurement, seven of them
mine.**

---

## 2. WHAT LANDED

**The Case path was completely broken and nothing said so.** The thread rendered
at **zero height** — `.chat-container` 0px with a 115px user bubble and a 241px
assistant bubble inside it. `POST /case_chat` returned 200. Nothing errored. The
landing column's 531 of 623px starved a `flex:1; min-height:0` section down to
11px; it does not overlap the thread, it starves it. A regression from A15
(`de88e4a`), which made the main search bar a second entry point that skipped the
teardown. **0px → 337px**, verified against the running app on a real answer.

The eval cannot see it: `case-opening-full` goes through the API, gets its
clarify payload, and passes.

**82 detectors audited** across 199 stored answers and 3,061 stored abstracts.
13 read zero under the naive instrument and are non-zero corrected —
`_LIST_ITEM_RE` alone went 0 → 4,710. One genuine zero survives and is *kept*:
`_THRESHOLD_RE` guards an idiom this library does not contain (rule 34).

**The apicoectomy curriculum, start of session → now**, all read off the
laid-out page:

```
  literal `*`                    94 -> 0        literal `**`         3 -> 0
  "From the wider literature"    12 -> 0 (corpus-wide)
  orphaned list numbers          30 -> 0        cut bold runs       24 -> 0
  uncited marks ending mid-word 7/9 -> 0        A22c legend          0 -> 1
  uncited-mark contrast    1.02:1 -> 13.34:1    citation pills   286 -> 316
```

**The 1.02:1 was invisible text, not low contrast.** `.uncited-claim` set
`color: inherit`; inside the dark quarantine block that inherits near-white onto
its own pale amber ground. Six of ten marks were unreadable. Outside a block the
same marks measured 6.54–10.52:1, which is why nothing caught it.

**A regression I caused and caught in the same session.** Making the legacy
header's `⚠ ` prefix optional took raw `[[PMID:N]]` markers on screen from 0 to
**30**. A quarantine block is stashed out of `renderAnswer` before the citation
replacer runs, so its contents were formatted by `_unverifiedInline`, which knew
nothing about citations. **Invariant 3 had a hole in it the whole time** and was
unreachable only because that block was never recognised.

**A44b and A44d.** A sticky 212px TOC at ≥1080px on a 26,107px document with 32
headings, and a masthead chip row. Both are also instruments, and they agree
with each other about something nobody asked them: see §5.

---

## 3. STATE AND TRAPS

- **Use `endo-ai-measure` (port 5004) for any browser measurement.** It is
  `debug=False`, so a `.py` edit cannot restart it mid-run — which killed one
  case measurement tonight before I noticed. **It also means you must restart it
  after every template edit**: Jinja caches the template with `debug=False`, and
  I measured a stale page twice before working that out.
- Port **5003** is still the other session's `77867e1`. Untouched all night.
- **A case turn takes 4–8 minutes**, not the 30s the mode promise says. Three
  measurement scripts timed out at 300s with the answer already generating.
- **The clarify gate is variable**: the same `case-opening-full` description
  asked 2, then 1, then 0 questions on identical code. Any wait that assumes a
  clarify panel appears will hang forever when it asks zero.
- The clarify bubble is **replaced** by the answer, not followed by a second
  one. Waiting for two assistant bubbles waits forever.
- **`js_harness.RENDER_DEPS` drifted twice tonight** — once for `setMode`'s new
  helpers, once for `_citeMarkersToPills`. Its own docstring documents this
  exact failure. Any new top-level helper that `renderAnswer` or `setMode`
  reaches needs adding, or unrelated files go red with a `ReferenceError`.
- The A22f strip, the split-item repair and the header variant all run at READ
  time. **Stored rows are never mutated**, so all of it is reversible.

---

## 4. ORDER FOR THE NEXT SESSION

1. **Restore API credit.** Nothing below moves without it.
2. **Regenerate the four demo answers.** They date from 2026-09-01 18:46–18:49
   and cite 10/13/12/13 — mean **12.0**. Current code measures 14–23, mean 18.4,
   and a live case answer tonight cited 21. The demo currently shows two-thirds
   of the references the engine produces, none of A38's removed false claim and
   none of A42's halved cost. This is the highest-value pre-demo action.
3. **Item 7, the three-run v6 baseline**, on frozen code. A46's prediction is at
   `eval/reports/a46_prediction_v7.md`; re-confirm 5003 is not ours and report
   the contamination count for every run.
4. **Finish A37 (item 5)** at n≥5 per case fixture. The prediction is committed
   and held at n=5: the gate is variable, not broken — 1 of 3 runs at 2+. A
   count threshold needs RB.
5. **A22e**: one live curriculum, then report the block count. Read-time
   re-render already took the stored apicoectomy from 17 blocks to 14; the
   remaining 14 keep legacy footers because converting *every* legacy block was
   deliberately out of scope.
6. **Re-run `scripts/audit_detectors.py`** once a curriculum exists on current
   code. `_ROLE_FENCE_RE`, `parse_callouts` and `find_presentation_markup` score
   0 legitimately today because A44's fence postdates every stored document. If
   they are still 0 on new output, the callout vocabulary is dead.

---

## 5. FOUND, NOT FIXED

- **The curriculum generator's headings are wrong, and two independent
  instruments agree.** A44b's TOC and A44d's chip row both report **three**
  `## Module N` headings where the document claims four: the sequence is
  1, [unnamed], 3, 4. All four modules also number their subsections
  `4a / 4b / 4c` — the prompt's template numbering copied verbatim rather than
  renumbered. Five heading labels repeat verbatim. Generator work; needs a live
  curriculum to verify a fix. **Severity: moderate** — it is a teaching document
  and the numbering is part of the teaching.
- **`(ESE-QG-2023)` renders as a bare internal key** on demo question 1. The
  model wrote a plain parenthetical instead of `[[PMID:ESE-QG-2023]]`, so it is
  not a pill, clicks nowhere, and is not in the References block: the answer
  cites 11 sources and lists 10. No gate is wrong — `_detect_uncited_author_mentions`
  correctly returns `[]`, and `_AUTHORITY_BODY_RE` belongs to the quarantine
  footer, not that gate. **Severity: cosmetic, but it is on the demo surface.**
- **The runbook's Cochrane talking point is not on screen.** The script says
  question 1 cites CD005296; the page shows PMID 36512807, which *is* CD005296.
  The presenter would be asserting a number nobody can see. **Severity: low.**
- **A11's build hash is not in the archive.** `learn_history` records carry no
  build provenance, so A44d's masthead has no build chip. Emitting "unknown"
  would invent a field. Fix is at save time. **Severity: low.**
- **14 quarantine blocks still carry 14 identical footers** on the stored
  apicoectomy curriculum. A22c replaced the footer with one legend and the
  legend now renders, but only repaired blocks got the current treatment.
  Converting every legacy block is A22e/A44n's question — 88 blocks corpus-wide.
  **Severity: moderate, and RB has seen it.**
- **The eval asserts a fixed range on a stochastic quantity.**
  `clarify.count_between: [0,1]` fails about a third of the time by design. That
  is a harness question as much as a generator one. **Severity: it will keep
  producing false failures until someone decides.**

---

## 6. DECISIONS TAKEN, WITH THE ALTERNATIVE REJECTED

| decision | alternative rejected |
|---|---|
| A44b's TOC in the **history viewer only**, not the live answer card | doing both; the answer card is the demo surface and restructuring `.center-col` unattended days before a demo is not a good trade — and with no credit I could not generate a live curriculum to verify it |
| **A44c deferred entirely** (design tokens / dark mode) | doing it; it is a ~85-colour remap and the project's own memory records that a naive remap makes dim text invisible on light backgrounds. Not an unattended change |
| The split-item repair is **targeted** — only blocks preceded by an orphaned number | unwrapping every legacy block, which would rewrite 88 blocks nobody asked about and is A22e/A44n's question |
| `_THRESHOLD_RE` **kept** despite firing 0 of 95 | deleting it as measured-dead code, which removes the protection the first "at least 10 patients" abstract needs (rule 6) |
| The **dark quarantine block left alone**; only the invisible mark fixed | switching it to A22d's pale ground, which overturns a deliberate deck-parity decision that is RB's to make |
| Committed with **one red test** | blocking every remaining item on an external billing failure |

---

## 7. RB DECISION OUTSTANDING

**Dark quarantine block, or A22d's pale one?**

`.unverified-block` is `#3a1520` ground with `#eef2fa` text, and the CSS comment
states the reason: *"the deck's dark tokens verbatim, so the same content reads
identically in the answer and on a slide."* A22d specifies the opposite:
*"near-black on the pale ground (target ≥7:1) … this is a light UI, check that
no dark-theme token leaked in."*

The token did not leak. It was carried in on purpose. Both positions are
defensible and the code cannot hold both. **The 1.02:1 invisible mark inside it
is fixed under either answer**, so nothing is blocked on this — but the block is
the most visually dominant element on a curriculum and RB has already called the
boxes unreadable once.

Also outstanding from before: **the lexicon still ships disabled.**
`eval/endodontic_lexicon.json` has `reviewed_by_rb: false` and `load_lexicon()`
returns `[]` until RB flips it. A41b measured apicoectomy 1–2/5 → 4/5 on 3 of 3
runs with controls unchanged. Untouched tonight.
