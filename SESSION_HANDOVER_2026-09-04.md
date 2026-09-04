# SESSION HANDOVER — 2026-09-03 evening → 2026-09-04

Boot a new coding-agent chat with:

> Read `AGENT_QUEUE.md`, `SESSION_HANDOVER_2026-09-04.md` and `CURO_HANDOVER.md`.
> Continue from the ORDER section below.

**17 commits**, `121b1ea..8dddb75`. Suite **2245 passed, 50 skipped**.
Spend across the session **$49.52** over 557 model calls (Opus $41.82 — mostly
the A38d and A42b paired answer runs, $22.60 + $21.27).

---

## 1. THE ONE THING TO CARRY FORWARD

**Rule 25 was written this session and immediately proved itself: the number
that started six queue items no longer existed.**

A35's whole workstream — A35, A35a, A35f, A35j, A35k and A38's Defect 2 — chased
"Curo cites 9–11 of ~114". That figure came from 15 **cached** answers written
before A5b, A30b, A31 and A7. Measured on current code it is **14–23, mean
18.4**. RB's ~20-reference target was already met by the membership fixes.

Four more premises fell the same way. Running total: **twelve overturned by
measurement, five of them mine.**

| item | the premise | what was actually true |
|---|---|---|
| A33g | the scenario group needs OR-expansion | the 2/4 came from a HAND-WRITTEN term. Five generations, two framings, 0/4 (**mine**) |
| A35 | the quota is too small | the pool is already 114; removing it feeds level1, the lowest-citing tier |
| A33c | an ordinary ingestion gap | `ENDO_DOMAIN_FILTER` excludes it — the filter's first conviction after two exonerations |
| A34 | JOE is under-represented | JOE is retrieved ABOVE PubMed's share; **AEJ** was the gap |
| A38 Defect 2 | the PRISMA notice suppresses citations | removing it changed nothing (18.0 → 19.0) |
| A39 | the curriculum needs query diversity | it needs ONE term of art; 5 of 7 angles added 297 papers and zero targets |
| A42a | the 0.60 floor is free | free on DEEP pools; it gutted thin ones 103→6 until a guard was added (**mine**) |
| A42 | the floor is not the cost fix | it is: $2.67 → $1.59. I estimated where I was told to measure (**mine**) |

---

## 2. WHAT LANDED

**Cost, halved.** `evidence_floor` 0.60 with a `min_evidence_papers` 40 guard:
**$2.67 → $1.59 per Review answer, citations 18.0 → 19.0.** Split from
`similarity_floor` because that one also gates routing (rule 26). A45 then found
**67% of synthesis retries were one broken gate** — `UNCITED_AUTHOR_MENTION`
matching "MTA and Biodentine" — precision 3.7% across 819 corpus matches, now
100% at 62 matches.

**A38 — a false claim on 39% of every pool, removed.** The PRISMA notice told
synthesis that N papers were "already synthesised inside PMID X" with no topic
test. Where checkable it was true **2% of the time**. 1,294 flags → 1.

**A22b/c/f + A44m.** Quarantine has two levels by size (threshold 2, chosen from
the distribution), one legend instead of 56 repeated footers, and wording that
no longer claims the content is published. A closed five-role callout vocabulary
with an unknown role rendering as prose.

**Library: 3,072 → 3,164.** 92 AEJ papers (A34c) plus the 2026 Cochrane (A33c).

**A46 worked on its first outing.** The prediction committed before the run
caught a regression I had introduced — see §4.

---

## 3. STATE AND TRAPS

- **Servers.** Port **5003** is another chat's server on `77867e1`, idle all
  session — do not demo from it. Start yours with
  `preview_start {name: "endo-ai"}` (port 5000). It dies if a template changes
  under the dev reloader.
- **The lexicon ships DISABLED.** `eval/endodontic_lexicon.json` has
  `reviewed_by_rb: false`, and `load_lexicon()` returns `[]` until RB flips it.
  That flag is the gate, not a comment. **RB's review is outstanding.**
- **`baseline_v6` is stale and was NOT updated.** It predates A5b, A30b, A31,
  A7, A33c, A42 and A34c. Library cases now run 1.6–3× its ranges.
- **A14 is larger than it looks.** `pips-vs-ultrasonic` swung **40 → 112**
  between two runs of identical code. No single-run number is a fact.
- **Heredocs mangle backslashes in this shell.** It cost four separate repairs
  this session. Use the Write tool for any patch script containing a regex or an
  escaped newline — the previous handover says this and I ignored it.
- **`test_all_three_named_papers_now_enter_the_candidate_pool`** failed once in
  a full run and passed in isolation and on re-run. Same signature as
  `sdf-pulp-outcomes`. Unattributed, filed to A14.

---

## 4. ORDER FOR THE NEXT SESSION

RB's order, with step 1 done:

1. ~~**One clean eval run** as a smoke test~~ — **DONE, 28/29, zero
   contamination.** The three fixed cases hold in a full-run context
   (`pregnancy` 22, `intentional-replantation` 22, `sdf-pulp-outcomes` 17, all
   PASS, refusal rate 0). The single failure is `case-opening-full`:
   *clarify asked 2 questions, expected 0-1* — not retrieval, and it is item 2b.
   Log: `eval/logs/v7_smoke.log`.

2. **The browser block** — nothing here has been started.
   - **2a. A16d re-verification FIRST.** The existing GO was taken on `8da8823`,
     before A42 changed retrieval and A22 changed rendering. It is stale and it
     gates a live investor demo. Re-verify on current HEAD **in the browser**,
     one Literature + one Case + one Curriculum. Report what RENDERS, not what
     the API returns. The four demo questions are in `DEMO_RUNBOOK.md` lines
     17–22; the prior report is `eval/reports/a16_cached_answers.md`.
   - **2b. `case-opening-full`.** Measure how often A37's gate asks 2+ across
     ALL case fixtures before changing anything. Do not tune from one failure.
   - **2c.** A22a (list splitting), the literal `**` leak, A22d contrast (≥7:1,
     measured in the running app), A22e re-render, A44b–d, A44n.

     **A22a and the `**` leak do NOT reproduce in stored text** — 0 split list
     items, and the 42–55 "literal `**`" per document are well-formed bold
     headings my regex mis-read. They are renderer defects. RB has recorded
     mis-filing them to the text layer as his error.

3. **The three-run v6 baseline**, once, on frozen code. Confirm 5003 is idle and
   re-read the contamination guard first (it is a pid check — `eval/run_eval.py`
   line ~75). A46's prediction is committed at
   `eval/reports/a46_prediction_v7.md`; compare against it and mark every moved
   case predicted or unpredicted.

Then A10, A26, A25a.

---

## 5. OPEN, NEEDING RB

- **The lexicon needs review** (§3). Seven entries, each justified by a fixture.
  Flipping `reviewed_by_rb` to true turns it on; A41b measured apicoectomy
  1–2/5 → **4/5 on 3 of 3 runs**, controls unchanged.
- **A38b's topic-proximity threshold is NOT measurable** from the data — SR-to-
  paper cosine is 0.757 median for 10 verified papers and 0.619 for 1,284
  unverified, on n=10. Not invented. The notice no longer names papers, so
  nothing needs gating.
- **A35 is closed as a supply question.** Five explanations eliminated. Whether
  ~19 citations is too few is a synthesis judgement.
- **`multi_query_search` returns a hard 200 candidates** (A40). It hit 200 on
  29 of 29 questions and all 200 cleared the floor on 14 of 29. Recorded, not
  changed — A35k says supply is not the constraint.
- **A7's scoring inconsistency stands.** Hand-ingested guidelines carry 90.0,
  PubMed-indexed equivalents 30.9–50.4.
- **`35097115` (de Araújo) is held back** under A12 — it would band level1 on
  its Meta-Analysis type but is an SR *of in vitro studies*.
  `--apply-contested` writes it once A25 decides.
- **The GIC fixture is still 0/4.** The generator reaches for
  `direct coronal restoration` — matching the QUESTION's words — over
  `orifice barrier`, whose value is that it does *not*. That is the harder half
  of A41 and nothing has solved it.

---

## 6. RULES ADDED THIS SESSION

25–32, all from measured failures. The three that changed how I worked:

- **25** measure on current code — a stored answer is evidence about the code
  that produced it.
- **30** a styling change can create a fail-open gate; enumerate what reads the
  shape you are changing.
- **32** instrument the REFUSAL rate of every guard, not just its correctness
  when it fires. A33h-i refused **145 of 254** attempts and every test asserted
  what it did when it fired.

The two-regime broadening rule is written out in `AGENT_QUEUE.md` because it is
subtle: above zero hits a declared qualifier wins; at zero hits the narrowest
group goes, because the objective is recall, not semantics.
