# Demo Runbook

Server: the launch config in `.claude/launch.json` (or `python app.py`).
`ADMIN_TOKEN` and `FLASK_SECRET_KEY` must be set for the sidebar delete button
and admin routes; the demo itself needs neither. All timings below were
measured on this machine on 2026-08-30, on the code tagged `mvp-demo-2`.

## 1. The four cached questions, in order

Ask each in **Review** mode, exactly as written — the cache matches the
question semantically, but exact text removes all doubt. Each returns in
**under 1 second** (measured 0.4s):

1. *Single-visit versus multiple-visit root canal treatment for necrotic teeth
   with apical periodontitis*
2. *MTA versus Biodentine for full pulpotomy in mature permanent teeth with
   irreversible pulpitis*
3. *CBCT versus periapical radiography for detecting apical periodontitis*
4. *Nonsurgical retreatment versus apical microsurgery for persistent apical
   periodontitis*

**What to click, on question 1:**
- A **citation pill** in the answer — it resolves to author names and opens the
  abstract popover. Say: every citation is checked against the actual abstract
  before the answer ships; the header chip shows the result.
- The **evidence-shape chip** in the header ("1 Cochrane · 25 RCT/SR · …") —
  say: the counts equal the bibliography, enforced in code, and this question
  is answered citing the current Cochrane review (CD005296) — the system
  guarantees journal-verified Cochrane evidence can't be dropped by search
  luck.
- A **COI badge** if one is visible in the bibliography ("INDUSTRY CONFLICT
  DECLARED") — say: read from the authors' own PubMed declaration, tri-state,
  never from product mentions.

## 2. The fallback live question

*Endodontic management in patients on bisphosphonates or antiresorptives* —
also cached now (0.4s). To show a genuinely LIVE run instead, ask any question
not on this page; expect **~60–70s total, first streamed text at ~13–17s**.
What the audience sees: "Searching PubMed" with a live query counter (parallel
tier fetches), then the answer **streams in**, recommendation box first, while
the header chips honestly read "checking…" until the citation checks finish on
the complete text.

## 3. The laser curriculum (Deep Learning mode)

*Use of lasers in root canal disinfection* in **Learn** mode — cached (0.4s;
a cold build is ~8.5 min at ~$1.4, down from 18 min).

- Scroll to **Module 3 (clinical technique/protocol)**: every numeric
  parameter (energies, concentrations, times) carries a citation. Say: a
  module that retrieves no evidence is **not generated** — the system renders
  "Module not generated — insufficient evidence retrieved" rather than
  inventing laser settings behind a disclaimer. That safeguard exists because
  an early version did exactly that, once.
- Show the **Final Verdict / synthesis** at the end: tier-ordered — a case
  series never overrides a Cochrane finding.

## 4. If something is slow

Say: "It's searching live literature — the cached path you just saw is what a
repeat question costs; a first-of-its-kind question pays one real PubMed sweep,
and the answer starts streaming as soon as the evidence is in."

## Numbers to quote if asked

- Cached answer: **<1s**. Cold live Review question: **~60–70s** (streaming
  starts ~15s). Cold curriculum: **~8.5 min**, ~$1.40.
- Library: ~2,300 papers, 8-tier evidence hierarchy, retracted/withdrawn/
  superseded/animal-model papers excluded or quarantined.
- Eval: 21-case regression set, 3 consecutive full retrieval passes, 5-case
  synthesis subset green including "must cite the Cochrane review" pins.
