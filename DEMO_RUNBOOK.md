# Demo Runbook

Server: the launch config in `.claude/launch.json` (or `python app.py`).
`ADMIN_TOKEN` and `FLASK_SECRET_KEY` must be set for the sidebar delete button
and admin routes; the demo itself needs neither. All timings below were
re-measured on this machine on 2026-09-01, on the code tagged `guardrails-v1`,
against the healed library (every abstract now stored at full length). The
cached answers below were regenerated at the same time, so the cache is warm
and the numbers are what the room will see.

## 1. The four cached questions, in order

Ask each in **Review** mode, exactly as written — the cache matches the
question semantically, but exact text removes all doubt. Each returns in
**under 1 second** (measured 0.5-1.0s on 2026-09-01):

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

*Use of lasers in root canal disinfection* in **Learn** mode — cached (0.5s;
a cold build is **7.5 min at $1.17**, re-measured 2026-09-01 after
`guardrails-v1`).

- Every module now carries its own **citation-support status** line, checked
  against the papers' real abstracts. On the currently cached build the four
  modules read **0, 0, 0 and 1 of 30 flagged** — re-measured 2026-09-01 after
  the claim-unit fix, where the same build previously ran 2-6 per module. Say:
  the check runs per module, and where a module's status did not survive the
  stitching step the system restates it in an appendix rather than letting it
  go quiet.
- If asked why a module says "30 checked" when it cited more: `_SUPPORT_MAX_PAIRS`
  caps the check at 30 pairs, and the block **names the remainder** rather than
  implying it checked everything. On this build the four modules had 34 / 31 /
  37 / 31 pairs, so 13 of 133 went unchecked and the answer says so.

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

- Cached answer: **0.5-1.0s** (re-measured 2026-09-01 after the `guardrails-v1`
  re-warm: 1.0 / 1.0 / 0.5 / 0.5 / 0.5 / 0.5s, all six served from cache —
  five Review answers and the curriculum). Cold live Review question:
  **55-70s** (streaming starts ~15s; the five re-measured 61.3 / 66.8 / 55.8 /
  69.4 / 60.3s). Cold curriculum: **7.5 min**, $1.17.
- Cost per cold Review answer: **~$0.85** (the five re-measured $0.68-$0.95,
  total $4.23). It was ~$1.28 before `guardrails-v1` and ~$0.79 before
  `grounding-v1`, and the round trip is worth being able to explain:

  - the rise to ~$1.28 was two things — these questions retrieve 31-43 papers
    each and the prompt now carries every one of their **abstracts** (the
    library used to send Claude a metadata line per paper and no abstract, so
    answers were written without the papers' content), and three of the five
    were taking a **validation retry**;
  - the fall back to ~$0.85 is the retry. The grounding rule and the
    recommendation-traceability gate were giving the model contradictory
    instructions where the evidence base did not cover the question: one asked
    for a marker on the recommendation, the other said not to attach one you
    cannot ground, and the answer was regenerated. Reconciling the wording —
    say what the evidence **does** establish, and cite that — took attempt-1
    pass from 3/10 to 10/10 on the reproducing question and cost per served
    answer from $0.93 to $0.56, **with both gates untouched**.

  The citation-support flag rate on the LIVE Review path is **0 of 51 cited
  claims flagged**, from 7 of 34; on the library path 3 of 48. On the Deep
  Learning curriculum it is **16 of 238 = 6.7%**, and of those 16 only **5 are
  genuinely unsupported** — every flag was read by hand. Quote those, not the
  older 4.3%: the same three library cases measured 8.2%, 8.9% and 6.3% across
  one night with nothing changed between the first two, so 4.3% was a draw
  rather than a level.
- Exports, measured: **web deck 152s** without narration; from 2026-09-01 the
  deck records its own per-slide narration by default, which adds ~2 min and
  ~$0.25 and is what turns **auto-advance on** (21 segments against 21 slides,
  verified with ffprobe). Post `{"narrate": "reuse"}` to `/generate_webdeck`
  for the old, free, non-advancing behaviour. **PPTX 22s.**
- Library: **2,350 papers**, 8-tier evidence hierarchy, retracted/withdrawn/
  superseded/animal-model papers excluded or quarantined. Every abstract is
  stored at full length (mean 1,631 characters, up from 1,182); 57% of them
  used to be cut off mid-word before their conclusions.
- Eval: 21-case regression set, 3 consecutive full retrieval passes, 5-case
  synthesis subset green including "must cite the Cochrane review" pins.
