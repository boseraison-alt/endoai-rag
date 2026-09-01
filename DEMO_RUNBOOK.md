# Demo Runbook

Server: the launch config in `.claude/launch.json` (or `python app.py`).
`ADMIN_TOKEN` and `FLASK_SECRET_KEY` must be set for the sidebar delete button
and admin routes; the demo itself needs neither. All timings below were
re-measured on this machine on 2026-09-01, on the code tagged `grounding-v1`,
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
a cold build is **8.0 min at $1.52**, measured 2026-09-01).

- Every module now carries its own **citation-support status** line, checked
  against the papers' real abstracts. On the current build the six modules read
  between "1 of 30 flagged" and "5 of 30 flagged". Say: the check runs per
  module, and where a module's status did not survive the stitching step the
  system restates it in an appendix rather than letting it go quiet.

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

- Cached answer: **0.5-1.0s** (re-measured 2026-09-01 after the re-warm:
  1.0 / 0.5 / 0.5 / 0.5 / 0.5s, all five served from cache). Cold live Review
  question: **60-110s** (streaming starts ~15s; the five demo questions
  re-measured 108.6 / 99.0 / 60.8 / 78.9 / 75.9s). Cold curriculum: **8.0
  min**, $1.52.
- Cost per cold Review answer: **~$1.28** (the five re-measured
  $0.72-$1.73, total $6.39), up from ~$0.79. Two drivers, both worth naming if
  asked: these five questions retrieve 32-38 papers each and the prompt now
  carries every one of their abstracts (36.5k input tokens against 24.4k), and
  three of the five took a validation retry. That retry is the honest cost of
  the grounding rule — the model now leaves a claim unmarked rather than
  attaching a citation it cannot ground, and the recommendation-traceability
  gate then asks for the answer again. The earlier doubling is
  worth saying out loud if asked: the library used to send Claude a metadata
  line per paper and no abstract, so answers were written without the papers'
  content. Full abstracts now go into the prompt. The citation-support flag
  rate on the LIVE Review path is **0 of 51 cited claims flagged**, from 7 of
  34 before this batch; on the library path it is 3 of 48. Quote those, not
  the older 4.3% — the same three library cases measured 8.2%, 8.9% and 6.3%
  across one night with nothing changed between the first two, so 4.3% was a
  draw rather than a level.
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
