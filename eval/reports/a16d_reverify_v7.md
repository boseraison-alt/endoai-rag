# A16d — re-verification on current HEAD, in the browser (2026-09-04)

> The prior GO was taken on `8da8823`, before A42 changed retrieval, before A15
> put the main search bar in front of the case thread, and before A22 changed
> how unsourced content is shaped. This re-runs it in the browser and reports
> what RENDERS.

Server: **port 5004**, no-reload (`endo-ai-measure`), `/health` verified against
HEAD before each run. Port 5003 is another session's `77867e1` and was never
touched. Screenshots in the session scratchpad under `shots/`.

Measurements are read off the laid-out DOM with `getBoundingClientRect` and
`getComputedStyle` — not from the API payload.

---

## Verdict

| mode | before tonight | now |
|---|---|---|
| **Literature** (cached) | GO | **GO** |
| **Curriculum** (stored) | NO-GO | **GO**, with one item for RB |
| **Case** (live) | **NO-GO** — thread rendered at 0px | **GO** on layout; answer path **unverified**, API out of credit |

Two of the three modes had regressed since the GO was taken, and neither
regression was visible through the API — which is why the item says *in the
browser*.

---

## 1. Literature — demo question 1, cached — **GO**

*"Single-visit versus multiple-visit root canal treatment for necrotic teeth
with apical periodontitis"* → cache hit, `$0.0000`, 11.3 s first ask.

| Stage 1 item | what renders | |
|---|---|---|
| Q1 banner second half | `⚠ Checked against abstracts: 13/13 consistent · 1 claim not from the evidence base` | PASS |
| Q3 impact factor | 0 occurrences of `(IF…` | PASS |
| Q4 raw marker | 0 occurrences of `[[` | PASS |
| Q5 bibliography = citations | cited **10**, bibliography **10**, symmetric difference **empty** | PASS |
| Q6 cross-tier sort | `Papers Retrieved — grouped by evidence tier`, strongest first | PASS |
| Q8 / A3c marking | 1 mark, and it no longer ends mid-word | PASS |
| A22f wording | 0 "wider literature" | PASS |
| literal `**` / `*` | 0 / 0 | PASS |

Evidence-shape chip `2 Cochrane · 3 RCT/SR · 2 Classic · 1 Prospective · 2
Cohort` = 10 = the bibliography, so the invariant the demo script asserts out
loud is true on screen.

### Two things the demo script should know

**a. `(ESE-QG-2023)` renders as a bare internal key.** The stored answer has it
as a plain parenthetical, not `[[PMID:ESE-QG-2023]]` — the model named an
authority document without wrapping it. So it is not a pill, it clicks nowhere,
and it is **not in the References block**: the answer cites 11 sources and lists
10. `_detect_uncited_author_mentions` returns `[]` for it with or without the
parenthetical, and that is correct — `_AUTHORITY_BODY_RE` belongs to the
quarantine footer, not to that gate. There is no gate to fix; the model wrote
the wrong form. Only demo question 1 of the five cached answers carries one.

**b. The runbook's Cochrane talking point is not on the surface.** The script
says question 1 "is answered citing the current Cochrane review (CD005296)".
`CD005296` appears nowhere in the rendering — the citation is PMID `36512807`
(Mergoni, Cochrane 2022), which *is* CD005296. The presenter would be asserting
a number the screen does not show.

### The demo cache is three days and four retrieval fixes stale

All four demo answers were generated **2026-09-01 18:46–18:49**, before A5b,
A30b, A31, A7, A42, A38, A33c and A34c.

| demo Q | distinct citations in the cached answer |
|---|---|
| 1 single vs multiple visit | 10 |
| 2 MTA vs Biodentine | 13 |
| 3 CBCT vs periapical | 12 |
| 4 retreatment vs microsurgery | 13 |
| (fallback) bisphosphonates | 8 |

Mean **12.0**. Current code measures **14–23, mean 18.4**, and a live case
answer generated tonight cited **21**. The demo is showing about two-thirds of
the references the engine now produces, none of A38's removed false claim and
none of A42's halved cost. Rule 25 pointed at the demo: the cache is a time
capsule, and it is currently a capsule of the worse engine.

**Regenerating the four demo answers needs API credit.** It is the single
highest-value thing to do before a demo.

---

## 2. Curriculum — `apicoectomy of mandibular teeth`, stored — **GO**

Opened through Profile → Deep Learning History, i.e. `/learn_history/<file>`,
the route A16b wired to re-render.

| | at the start of tonight | now |
|---|---|---|
| quarantine blocks | 17 | **14** |
| repeated per-block footers | 17 | 14 |
| A22c legend | **0** | **1** |
| A22b inline marks (`°`) | 1 | **5** |
| literal `**` | 3 | **0** |
| literal `*` | 94 | **0** |
| "From the wider literature" | 1 | **0** |
| raw `[[PMID:N]]` | 0 | **0** (was 30 mid-session — see below) |
| citation pills | 286 | **316** |
| uncited marks ending mid-word | 7 of 9 | **0** |
| **uncited-mark contrast inside a block** | **1.02 : 1** | **13.34 : 1** |
| uncited-mark contrast outside a block | 10.52 : 1 | 13.34 : 1 |
| impact factors | 0 | 0 |

**The 1.02:1 is the one that mattered.** `.uncited-claim` set `color: inherit`;
inside the dark quarantine block that inherits near-white `#eef2fa` onto its own
pale amber ground. Six of ten marks were literally unreadable — the blank white
bars in the screenshot. Outside a block the same marks were fine, which is why
nothing caught it.

**A raw-marker regression, caused and caught in the same session.** Making the
legacy header's `⚠ ` prefix optional (rule 17 — 114 blocks carry it, 2 do not)
took `rawMarkers` from 0 to **30**. A block is stashed out of `renderAnswer`
before the citation replacer runs, so its contents were formatted by
`_unverifiedInline`, which knew nothing about citations. Invariant 3 had a hole
in it the whole time and was unreachable only because that block was never
recognised. Fixed by sharing one replacer; pills 286 → 316.

### Still open, for RB

**The quarantine block is dark on a light UI, and that is deliberate.**
`.unverified-block` is `#3a1520` ground with `#eef2fa` text, and the CSS comment
says why: *"the deck's dark tokens verbatim, so the same content reads
identically in the answer and on a slide"*. A22d says the opposite —
*"near-black on the pale ground (target ≥7:1) … this is a light UI, check that
no dark-theme token leaked in"*. The token did not leak; it was carried in on
purpose. **This is a design decision, not a bug, and it is RB's.** The 1.02:1
mark is fixed under either answer.

**14 blocks still carry 14 identical footers.** A22c replaced the per-block
footer with one legend, and the legend now appears — but only the 3 blocks that
were repaired got the current treatment. Converting *every* legacy block is
A22e/A44n's question and was deliberately left out of scope tonight; it would
change 88 blocks across the corpus.

---

## 3. Case — **GO on layout, answer path unverified**

### The thread rendered at zero height, and nothing errored

Typed the `case-opening-full` fixture into the composer in Case mode. `POST
/case_chat` → **200**. Nothing appeared on screen. The conversation was in the
DOM with no height:

```
  .chat-container            h = 0     (flex:1 1 0; min-height:0; overflow:auto)
    .chat-bubble user        h = 115
    .chat-bubble assistant   h = 241   ← the clarify question, fully rendered
  .case-section.active       h = 11
  .content                   h = 623
```

…because the landing column was still standing underneath it — `#lockup` 188 +
`#inputCard` 198 + `#welcomeSection` 125 + `#modePromise` 20 = **531 of 623px**.
`.case-section.active` is `flex:1; min-height:0`, so it got the 11px left over.
The landing does not *overlap* the thread; it **starves** it.

`submitQuestion`'s case branch called `sendCaseMessage()` and returned, never
taking the landing down. Before A15 (`de88e4a`) the only way into
`sendCaseMessage` was the thread's own send button, reached after `setMode` had
already laid the page out; A15 made the main bar a second entry point and that
path skipped the teardown.

**Fixed and verified against the running app on a real answer: 0px → 337px.**
The first attempt hid the whole `#inputCard` and trapped the user — A19 moved
the mode chips inside its composer bar, and they are the only route out of a
case thread. The card now survives as a slim mode switcher.

**The eval cannot see any of this.** `case-opening-full` goes through the API,
gets its clarify payload, and passes. Every case test asserts on the response.

### What was measured on a real case answer, before the credit ran out

One full live turn on the `case-opening-full` description, current code:

```
  papers retrieved        206        distinct citations       21
  citation pills           31        cost                 $0.7676
  intent            diagnostic       differential first        yes
  A22c legend               1        A22b inline marks (°)      5
  full quarantine blocks    0        raw [[PMID]]               0
  literal **                0        citation support   3 of 28 flagged
```

That is the current engine rendering correctly — differential first
(invariant 18), one legend, inline marks rather than boxes, and the "What Curo
did not check" section with its flagged claims quoted.

**32 literal `*` were on that answer**, all of them the differential's
`*Fits because:*` / `*Argues against:*` / `*Evidence:*` labels. That defect is
fixed (single-asterisk emphasis now renders), but **it has not been re-verified
on a live case answer**, because the Anthropic API ran out of credit at
01:00 and every generating path is blocked.

**What is unverified on the Case path:** the answer surface on current code.
The layout fix is verified against a real answer; the rendering fixes are
verified on the stored curriculum and by unit test, not on a fresh case answer.

---

## What this changes

1. **A22a and the `**` leak were text-layer, not renderer.** Overturned by
   measurement — see `detector_token_shape_audit.md`. Fixed: 30 orphaned list
   numbers and 24 cut bold runs → 0 on every served document.
2. **The Case path was demo-blocking** and is a regression from A15, now fixed
   with a Playwright test that measures the laid-out box.
3. **Regenerate the four demo answers before any demo** — needs credit.
4. **RB has one decision**: dark quarantine block (deck parity) vs A22d's pale
   block.
