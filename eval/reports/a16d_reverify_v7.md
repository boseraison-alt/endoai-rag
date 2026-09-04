# A16d — re-verification on current HEAD, in the browser (2026-09-04)

> The prior GO was taken on `8da8823`, before A42 changed retrieval, before A15
> put the main search bar in front of the case thread, and before A22 changed
> how unsourced content is shaped. This re-runs it on `ae20d3e`, in the browser,
> and reports what RENDERS.

Server: port **5000**, `/health` → `ae20d3e`, `git_dirty: false`, own pid.
Port 5003 is another chat's server on `77867e1` and was not touched.

---

## Verdict

| path | verdict |
|---|---|
| **Literature (cached)** | **GO** — every Stage 1 fix renders. One cosmetic leak. |
| **Curriculum (stored)** | **NO-GO for the apicoectomy document** — A22b/c/f do not reach it, and 6 of its 10 uncited marks render at 1.02:1 (invisible). |
| **Case** | **NO-GO** — the whole thread renders at **zero height**. Deterministic. |

The prior GO stands only for the surface it was taken on. Two of the three modes
regressed after it, and neither regression is visible through the API — which is
why the item says *in the browser*.

---

## 1. Literature — demo question 1, cached — **GO**

*"Single-visit versus multiple-visit root canal treatment for necrotic teeth with
apical periodontitis"* → served from cache, `$0.0000`, ~13 s first ask.

Measured on the rendered DOM, not the API payload:

| Stage 1 item | what renders | verdict |
|---|---|---|
| Q1 banner second half | `⚠ Checked against abstracts: 13/13 consistent · 1 claim not from the evidence base` | PASS |
| Q3 impact factor | 0 occurrences of `(IF…` anywhere on the surface | PASS |
| Q4 raw marker | 0 occurrences of `[[` | PASS |
| Q5 bibliography = citations | cited set **== 10**, bibliography **== 10**, symmetric difference **empty** | PASS |
| Q6 cross-tier sort | `Papers Retrieved — grouped by evidence tier`, strongest tier first, with the within-tier note | PASS |
| Q8 / A3c marking | 1 `<mark class="uncited-claim">`, banner scrolls to it | PASS |
| A22 wording | 0 occurrences of "wider literature" | PASS |
| `**` leak | 0 | PASS |

Evidence-shape chip `2 Cochrane · 3 RCT/SR · 2 Classic · 1 Prospective · 2 Cohort`
= 10 = the bibliography, so the invariant the demo script asserts out loud is
true on screen.

### Two things the demo script should know

**a. `(ESE-QG-2023)` renders as a bare internal key.** The answer says *"The ESE
2023 Quality Guidelines explicitly state … consistent with the Cochrane
synthesis (ESE-QG-2023)."* The stored text has it as a **plain parenthetical**,
not `[[PMID:ESE-QG-2023]]` — the model named an authority document without
wrapping it. Consequences, all measured:

* it is not a pill, so it clicks nowhere;
* it is not in the References block — the answer cites 11 sources and lists 10;
* `_detect_uncited_author_mentions` returns `[]` for it, with or without the
  parenthetical, so no gate sees it. (`_AUTHORITY_BODY_RE` is used only by the
  quarantine footer, not by that gate — there is no gate gap to fix here, the
  model simply wrote the wrong form.)

Only demo question 1 of the five cached answers carries a bare key.

**b. The runbook's Cochrane talking point is not on the surface.** The script
says question 1 "is answered citing the current Cochrane review (CD005296)".
`CD005296` appears nowhere in the rendering — the citation is PMID `36512807`
(Mergoni, Cochrane 2022), which *is* CD005296, but the presenter would be
asserting a number the screen does not show.

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

Mean **12.0**. Current code measures **14–23, mean 18.4**. The demo is showing
about two-thirds of the references the engine now produces, and none of A38's
removed false claim or A42's halved cost. This is rule 25 pointed at the demo:
the cache is a time capsule, and it is currently a capsule of the worse engine.

---

## 2. Curriculum — `apicoectomy of mandibular teeth`, stored — **NO-GO**

Opened through Profile → Deep Learning History, i.e. the `/learn_history/<file>`
route A16b wired to re-render.

### 2.1 A22b/c/f do not reach a stored curriculum

Rendered counts:

```
  full quarantine blocks          17
  identical repeated footers      17      ("Consult directly: the specialty
                                           guidelines for this question …")
  legends                          0
  inline (thin-rule) treatments    0
```

That is the **pre-A22 state**, on the exact document A22 was written from. The
cause is deliberate and visible in the source: `_LEGACY_QUARANTINE_BLOCK_RE`
recognises the old shape *"so nothing written before today loses its block"* —
it preserves legacy blocks rather than converting them. `finalise_answer_text`
is called on this route, but it has nothing to do: `quarantine_unsourced_content`
sees the content is already quarantined and leaves it alone.

Only the block **header** updates, and only because the browser hard-codes it
(`index.html:5901`). The note and the footer come from the stored text.

So A22's headline — 56 footers become one legend — is true of newly generated
answers and false of every stored one. RB opening this curriculum in the demo
sees exactly what he complained about.

### 2.2 Six of ten uncited marks are invisible — 1.02:1

Contrast measured in the running app (A22d asks for exactly this), computed from
`getComputedStyle` on the live nodes:

| element | fg | bg | ratio |
|---|---|---|---|
| quarantine block ground | — | `#3a1520` | (page is `#ebedf4`) |
| block header | `#f87171` | `#3a1520` | **5.80** |
| block note / footer | `#aebad0` | `#3a1520` | 8.21 |
| block body | `#eef2fa` | `#3a1520` | 14.31 |
| **`.uncited-claim` inside a block** | `#eef2fa` | `#fdf3e3` | **1.02** |
| `.uncited-claim` outside a block | inherited ink | `#fdf3e3` | 6.54 – 10.52 |

`.uncited-claim` sets `color: inherit`. Inside `.unverified-block` that inherits
`#eef2fa` — near-white — onto its own pale amber ground. **6 of the 10 marks on
this curriculum are white-on-cream and cannot be read at all.** They are the
white bars in the screenshot.

This is rule 30 again: a styling change (the dark quarantine block) created a
fail-open interaction with a marker that was fine on its own.

### 2.3 The dark block contradicts A22d, deliberately

`.unverified-block` is `#3a1520` ground with `#eef2fa` text, and the CSS comment
says why: *"Colours are the deck's dark tokens verbatim … so the same content
reads identically in the answer and on a slide."* A22d says the opposite —
*"near-black on the pale ground (target ≥7:1; the amber is for the rule and the
label, never for body copy). This is a light UI — check that no dark-theme token
leaked in."*

The token did not leak; it was carried in on purpose, for deck parity. **This is
a decision for RB, not a bug to fix unilaterally** — but the 1.02:1 mark in 2.2
is a bug either way, and disappears the moment the block is pale.

### 2.4 The `**` leak and A22a reproduce in STORED TEXT — the premise was wrong

The previous session recorded: *"A22a and the `**` leak do NOT reproduce in
stored text — 0 split list items … They are renderer defects. RB has recorded
mis-filing them to the text layer as his error."*

**That measurement was wrong, and the mis-filing was right.** The detector
looked for a bare `N.` line. The corpus writes the number **bold** — `**3.**` —
so it matched nothing.

Scanned across 199 stored documents (`learn_history/*.json`, `answers/*.txt`,
`query_cache`):

```
  documents with a quarantine block                        14
  quarantine blocks total                                 114
  blocks preceded by an ORPHAN LIST NUMBER                 30      (26%)
  blocks with an ODD `**` count — a bold run cut in half   24      (21%)
  blocks with an orphan closing `**` line                  24
```

The stored apicoectomy text, verbatim:

```
**3.**

> ⚠ **NOT FROM THE EVIDENCE BASE — UNVERIFIED**
> …
> Administer local anaesthesia**
> Inferior alveolar nerve block plus long buccal infiltration …
```

The source was `3. **Administer local anaesthesia**\nInferior alveolar …`. The
quarantiner cut between the number and the step, and again inside the `**…**`
run — which orphans the closing `**` and is exactly the literal `**` RB saw
rendered. Both of RB's observations are one defect, and it is **server-side**,
in `quarantine_unsourced_content`, not in the renderer.

**Ownership moves back to the text layer (Agent R / `endo_ai.py`).** The browser
cannot fix this: by the time the renderer sees it, the list number and its step
are in different blocks.

Three `**` survive into the rendered curriculum today, all of this shape.

---

## 3. Case — `case-opening-full` description, live — **NO-GO**

Typed the `case-opening-full` fixture description into the composer in Case mode
and submitted. `POST /case_chat` → **200**. Nothing appeared on screen.

The content is in the DOM. It has **zero height**:

```
  .chat-container            h = 0      (flex:1 1 0; min-height:0; overflow:auto)
    .chat-bubble user        h = 115
    .chat-bubble assistant   h = 241    ← the clarify question, fully rendered
  .case-section.active       h = 11
  .content                   h = 623
```

…because the landing column is still up underneath it:

```
  #lockup          188      #inputCard    198
  #welcomeSection  125      #modePromise   20      = 531 of 623
```

`.case-section.active { flex: 1; min-height: 0 }` therefore gets the 11px left
over, and its scroll container collapses to nothing.

**Cause, in one line:** `submitQuestion()`'s case branch
(`index.html:4791`) calls `sendCaseMessage()` and returns — it never calls
`setLandingVisible(false)` and never hides `#inputCard`. `sendCaseMessage()`
hides `#caseWelcome`, the *in-thread* hint, which is a different element.

**When it started:** `de88e4a` (A15, 2026-09-02) — *"one search bar, three
modes"*. Before A15 the only entry to `sendCaseMessage()` was the thread's own
`#caseSendBtn`, reached after the mode switch had already laid the page out.
A15 added the main bar as a second entry point and that path skips the teardown.

**Confirmed by counterfactual**, in the live page: hiding `#lockup`,
`#inputCard`, `#welcomeSection` and `#modePromise` by hand takes
`.chat-container` from 0 → 412px and the thread renders correctly — user bubble,
clarify panel, answer box, Skip / Search buttons, composer. Screenshot taken.

**The eval cannot see this.** `case-opening-full` runs through the API, gets its
clarify payload, and passes. Every case test asserts on the response.

### Incidental, from the same turn (feeds 2b)

A37's clarify gate asked **1** question — *"Any history of trauma to this tooth…"*
— against `count_between: [0, 1]`. That is a **PASS**, where the v7 smoke run
recorded 2. Second observation, opposite outcome: the gate is variable, and 2b's
instruction to measure across all case fixtures before tuning is the right call.
The question also avoided all four forbidden tokens.

---

## What this changes

1. **A22a and the `**` leak go back to Agent R / `endo_ai.py`.** Overturned
   premise #13, and the measurement that overturned it is above.
2. **The Case path is demo-blocking and is a four-line fix** in the browser
   layer — but it is a *regression*, so it needs a test that fails without it.
3. **The four demo answers should be regenerated** before any demo, or the room
   sees the pre-A42 engine.
4. **RB has one decision to make**: dark quarantine block (deck parity) vs
   A22d's pale block. The 1.02:1 mark must be fixed under either.
