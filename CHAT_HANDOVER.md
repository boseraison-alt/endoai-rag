# CURO — ADVISORY CHAT HANDOVER

Boot file for a **new advisory chat with Claude** (not the coding agent).
Last updated after A19-A21 (UI v2, no interviews, follow-ups) landed.

Open the new chat with:

> Read `CHAT_HANDOVER.md` and `AGENT_QUEUE.md` from my endo-ai-rag repo. You are
> picking up the advisory role described in §1. The agent is working through
> `AGENT_QUEUE.md`; I'll paste its reports for you to assess.

Three files, three jobs — don't confuse them:

| File | For | Contains |
|---|---|---|
| `CHAT_HANDOVER.md` (this) | the advisory chat | how we work, state, open threads, decisions |
| `AGENT_QUEUE.md` | the local coding agent | five stages + amendments A1–A18, 18 standing rules |
| `CURO_HANDOVER.md` | the coding agent | product state, invariants, backlog |

---

## §1 THE WORKING PATTERN

RB (endodontist, boseraison@gmail.com) runs a **local Claude Code agent** at
`C:\Users\boser\endo-ai-rag` that does all the coding. The advisory chat does not
write production code. Its job is:

1. Read the agent's pasted reports and say what they actually mean.
2. Diagnose problems and name the underlying bug *class*, not just the instance.
3. Write **paste-ready autonomous batch instructions** — and **write them into
   `AGENT_QUEUE.md`**, not only into chat. (Learned the hard way: two addenda
   lived in chat scrollback only and the agent could not see them.)
4. Assess competitor outputs and clinical answers RB pastes in.
5. Push back when a request conflicts with the product's own principles.

Standing permissions: multiple parallel agents, no permission prompts, autonomous
overnight batches, ~$0.70/library-answer approved.

RB wants plain language, a clear recommendation rather than a menu, honest
disagreement, and batches the agent can run unattended. He often asks "explain in
simple words" — that request is real; answer in prose without jargon.

---

## §2 WHAT CURO IS

Evidence-graded endodontics assistant. Curated PubMed library (~2,900 rows, Neon
Postgres + pgvector) with per-paper provenance — tier, COI tri-state,
retraction/supersession, MEDLINE status, pre-registration. Live PubMed fallback
with synonym-expanded queries, each paper keeping its best similarity across
every query. Tier-banded synthesis
with a fabricated-PMID validator and a claim-vs-abstract support checker.

**Three modes, one search bar** (as of A15): Literature · Case · Curriculum —
internally `review` / `case` / `learn`. Case Assessment and Profile sit in the
top-right nav. Mode behaviour is one `MODES` table applied by one function, with
every surface asking `modeShows(mode, panel)`.

Models: **Opus** for synthesis, case reasoning, differentials, curriculum writing.
**Haiku** for search-term generation, the cache same-question gate, the
citation-support checker, routing. **MiniLM** (local, 384-dim) for embeddings.
**OpenAI tts-1-hd** for narration only.

Tier ladder, by study design and never by score: cochrane → level1 → level2 →
level3a → level3b → level4 → invitro → level5; `retracted` terminal; unlabelled
bands to level5.

Measured costs: Literature $0.54 · Case $0.12 · Curriculum median $1.33 (max
$6.51). Suite ~1,932 tests, all mutation-checked.

---

## §3 WHERE THINGS STAND

**Demo status: GO.** A16d verified all four demo questions are cached and render
every Stage 1 fix. Warm the process before presenting — first ask is 9.2 s, then
1.0 s (embedding-model load).

**Complete:** Stage 1 (`trust-surface-v1`, Q1–Q8) · Stage 2 M1/M2 (anesthesia
regenerated, 5,583 → 12,745 words) · A1 (coverage gate) · A3 (banner adjudication
+ sharpening) · A4 (build provenance) · A5a · A6 · A9a (audit) · A13 · A15 ·
A16 (cached answers) · **A19 (UI v2 to RB's sketch)** · **A20 (Literature never
interviews)** · **A21a–c, e (follow-up + New topic everywhere)**.

**Open, roughly in priority order:** A5b + A5c · A7 apply · A9b/A9c · **A10** ·
A11 · A14 · A17 · A18 · **A21d** · Stage 2 G/H/J · Stage 3 (classics B3/B4, C) ·
Stage 4 (scope memo) · Stage 5 (citation audit).

**The UI is now the one in the Curo Search Modes canvas.** Thin top bar, centred
lockup with the real mark, one composer with the mode chips docked inside it,
three "what you get" cards per mode, History as a collapsed drawer, and a
follow-up composer plus New topic at the foot of every answer. The tagline is
**Evidence-Based Dental Educator**. A progress clock says how much longer.

**A10 is the one that matters most.** Everything else is polish, breadth or
measurement. A10 is a defect class with no existing defence: a citation that
resolves, whose sentence really is in the abstract, supporting a directive the
paper never concluded — because the sentence was the trial's *method*. Nothing
asks "is this what the paper found?" Found on the hypertensive plain-lidocaine
directive, PMID 40705444.

---

## §3b LATEST — the membership sweep and the eval (2026-09-03)

**One root cause explained three days of symptoms.** A score was deciding
*membership* in candidate sets, where only relevance should. Found in four places
and fixed in all of them: the per-tier library cap (A5b), `rag.search`'s
`ORDER BY (score*0.6 + similarity*40) LIMIT 100` (A30b), the live
`_apply_quality_threshold` cap, and `ensure_authoritative`. Standing rule 19 now
states the principle.

The retreatment case is the clearest illustration: 60 Level I papers cleared the
similarity floor, the cap kept 25 **by score**, and the single most on-point RCT
sat at rank 54 of 60 and was cut — in favour of position statements that were
*less similar to the question*, six of eight of them below the similarity floor
entirely. The answer then announced that no such trial existed. On the retreatment
fixture, 71 of 100 candidates change: mean similarity 0.551 → 0.635, mean score
78.3 → 61.0, and every paper leaving is a hand-assigned 90.0 guideline row.

**A fifth class, and a new one: the taxonomy could not express the thing.** All
seven tier filters name therapy or synthesis designs. Nothing matched a
cross-sectional, morphometric, imaging or diagnostic-accuracy study, so **46% of
the most relevant papers for an anatomy question were reachable by no tier filter
at any depth** — including the bony-lid technique paper. A31 added an
observational/descriptive tier banded last, floor 27, calibrated from measurement:
those papers score max 46.5, because a therapy-shaped scorer gives a descriptive
study no credit for a comparison it never made. **That is A25's argument as a
number rather than an assertion.**

**`ensure_authoritative` had never fired**, and three internal handover files
described the guarantee it never provided. Deleted, with the measurement written
where the function was. Eight green tests had sat on it because all eight called it
with `relevant=[]`, a state production never produces.

**Eval: retrieval 28/29 twice, synthesis 4/5.** 33 metrics moved, in two groups
with opposite causes — 17 retrieve more (median 3.2×, all library-routed, the fix
working) and 4 retrieve fewer, each moving in lockstep with its own search-term
count, which is A14's variance rather than a membership change.
`sdf-pulp-outcomes` fails in a full run and passes 3/3 in isolation:
**unattributed, deliberately not called clean.** The first eval run carried 22
contamination warnings from stray Flask servers; re-run clean at zero, both logs
committed.

**Also corrected: a claim about the harness had outlived the harness.**
`HANDOVER.md` and `questions.json` said answer-level assertions were inert and the
harness retrieval-only. The synthesis modes exist and do evaluate them — which is
how the one synthesis failure surfaced. Same class as A32c: an explanatory surface
describing a capability that had changed underneath it.

**Three inert checks found this week** — the verification banner over unchecked
claims, the 404 poll that never terminated, and the authority guarantee. None threw
an error; all three looked reassuring. The only way to find them is to ask whether
a check has ever actually fired.

---

## §4 DECISIONS MADE — do not relitigate

- **No journal-identity weighting**, ever. RB asked for a JOE-over-IEJ preference
  on 2026-09-02 and, told it was impact-factor weighting by another name, chose
  the no-preference option. Invariant 11.
- **Out-of-domain content is quarantined and reframed**, not refused and not mixed
  into cited prose.
- **No scope or domain-filter widening** without Stage 4's numbers and RB's
  sign-off.
- **UI: Literature · Case · Curriculum**, Assessment and Profile out of the mode
  row. Settled and built.
- **The IF column stays** (inert, guarded); dropping it is a post-demo question.
- `monthly_maintenance.py` no `--apply` until after the demo. Vision path off
  until a BAA. `cost_log.jsonl` append-only. Never weaken a gate for a number.
- **A score never decides membership** (rule 19). Relevance decides what enters a
  candidate set; score orders what is already in. 2026-09-03.
- **Curriculum may ask, but only to narrow a topic too broad to teach from.**
  Literature asks nothing. Both branches tested. 2026-09-03.
- **The authority guarantee is deleted, not redesigned.** It must never reach
  below the similarity floor — that is rule 19 wearing a virtuous hat. The
  union-of-max across generated queries *is* the variance protection. 2026-09-03.
- **The observational/descriptive tier is banded last and stays there** until A25
  decides per-question-type ranking. Reachability now, ranking later, never in one
  commit. 2026-09-03.
- **The ~$2 bisect of the laser live/library split is approved** — the fixture
  guards a defect that shipped once, and "narrowed to two candidates" is not good
  enough before a demo. 2026-09-03.
- **`baseline_v6` is a deliberate re-baseline**, with the 17-case explanation
  committed beside it and `v5` kept. Not silent, so rule 13 is satisfied.
  2026-09-03.

---

## §5 OPEN THREADS

**A5b** — the retreatment question misses two directly on-point RCTs (Karaoğlan,
*Int Endod J* 2022; Toia, *J Endod* 2022) and Schwendicke *BMJ Open* 2017. A1 does
NOT fix it: both concepts are covered at 9 and 19 papers so the gate never fires.
A5a found a cap-plus-absent-from-library mechanism. Three distinct retrieval
failure modes now known: gate short-circuit, vocabulary miss, cap/ingestion.

**A10** — see §3. Measure the flip rate by surface before making it a hard flag;
a large flip rate may be correct (never checked before) or a classifier failure,
and only adjudication distinguishes them.

**A14** — 6% of *extra* search terms degrade (0% of primary terms). Possibly the
same defect as A5's unexplained Schwendicke miss. Metric is hits-per-query.

**A17/A18** — A19d replaced the specific card that claimed "citations & impact
factor", and the dead `reviewWhat` array that still carried "ranked 0-100 by
design, sample size, recency, citations and follow-up" went with it. **A17's
sweep of every OTHER explanatory surface is still open** — help text, tooltips,
the About panel, the export decks and speaker notes, the README. A18's
promise-line times are still my estimates: measured so far, only that an
uncached literature FOLLOW-UP takes 74 s.

**A20 left one decision for you.** Curriculum still asks clarifying questions
before it builds. A20's premise was that it does not; measured, it does, and
three stored curricula carry the answered block. Literature no longer asks.
Say the word and Curriculum stops too — a test currently pins the asymmetry so
the change cannot happen by accident.

**A21d — a follow-up costs about as much time as a first answer.** Measured:
74.0 s / $0.371 uncached, 1.0 s cached. The cause is that carried PMIDs SEED
retrieval without shortening it. Fixing that needs a recall check on the
follow-up eval cases first (serial eval, standing rule 9). Also open, and
smaller: both uncached seeded follow-ups run so far needed a synthesis retry
against a 12% historical baseline — n=2, cause unknown, and a retry roughly
doubles the cost of an answer.

**Stage 4** — the scope question: should Curo read beyond endodontic journals.
Current view: no to "all dental journals"; yes to topic-gated doors into adjacent
specialties; **specialty guidelines (ESE/AAE/SDCEP/ADA) are probably higher value
per item than any journal expansion.** Ends in a memo and RB's decision.

**Comparison set** — `eval/COMPARISON_QUESTIONS.md`: 12 questions plus one
Curo-only case, each with a written prediction, and a six-mark scoring sheet.
Not yet run.

---

## §6 COMPETITIVE FINDINGS

**vs OpenEvidence, apixaban/apicectomy.** OpenEvidence won — the question is
perioperative anticoagulation wearing a dental hat, and it had CHEST 2022 with a
DOI. Curo had nothing relevant, said so, then answered anyway from general
knowledge with no citations under a green tick (fixed by Q1/Q2). **But** Curo
asked what OpenEvidence never did: does this patient need the surgery at all —
citing Cochrane RR 1.15 for non-surgical retreatment. That reframe is the
differentiator.

**vs OpenEvidence, one-visit vs two-visit retreatment.** Curo won on substance:
it surfaced and adjudicated a three-way disagreement OpenEvidence smoothed over,
and caught that the Cochrane review pools primary treatment with retreatment and
so does not answer the question asked. It lost on retrieval (the two 2022 RCTs)
and declared a **false evidence gap** as a result — announcing a retrieval hole as
a literature hole, the exact hazard flagged when the gap-declaration feature was
specified.

**vs an SR/MA-restricted general model, anesthesia.** It beat Curo on presentation:
evidence-level tags inline on every claim, and in-line flagging of its own weak
spots. Curo has that information and buries it in badges. What it could not do: a
single verifiable PMID, or the COI flag Curo raised on its own Dentsply-funded
source.

**Strategic conclusion: do not chase breadth.** Ingesting cardiology dissolves the
curation that makes Curo worth using.

---

## §7 RECURRING BUG CLASSES — check every report against these

1. **Work discarded without a signal.** Module cap, stitcher budget, domain filter
   dropping 48 papers. Anything that caps, filters or truncates must log and count.
2. **Fail-open gates.** A check that shows nothing and therefore shows green — the
   verification banner over uncited claims is the worst instance.
3. **Assertions that can become vacuous.** Rule 14: test the expression the
   production path evaluates, not a restatement. Dead branches mask mutants.
4. **A cache is a time capsule of old behaviour.** Any change to a rendered surface
   must say what happens to what is already stored (A16).
5. **A retrieval hole announced as a literature hole** (A5's false gap).
6. **Methods-as-findings** — a real citation supporting a directive the paper never
   concluded (A10).
7. **Model-written metadata.** Journal names in Review reference lines are invented;
   the model must write prose, never metadata (A9).
8. **Explanatory copy claiming a method the engine does not use** (A17).
9. **Gates tested only against the canonical form** — `(IF: n/a)` slipped through
   every Q3 test because all of them used a number (rule 17).
10. Batch metadata applied per-paper · trusted stored labels · untagged PubMed
    query terms · tests that grep source · max_tokens truncation in new forms.

---

## §8 RB-ONLY ITEMS

1. **Re-zip the OneDrive backup without `.env`, and rotate all three secrets** —
   Anthropic key, OpenAI key, Neon password. The zip contains live credentials; the
   git bundle beside it is safe. **Still pending. Oldest open item.**
2. Rehearse the demo on the presenting machine: four cached questions, one live,
   web deck citation click, video clip. Warm the process first (§3).
3. Listen to 60 s of laser audio spanning "apexification" — confirm or clear the
   pronunciation flag.
4. Run the comparison set in `eval/COMPARISON_QUESTIONS.md` when there is time.
5. Decide the Stage 4 scope question when the memo lands.
6. Verify against full text before any of it reaches teaching material: buccal
   infiltration ~45–85% rather than 80–90%; articaine IO evidence-supported;
   plain lidocaine wrong for the hypertensive branch.

---

## §9 SESSION HYGIENE

Start new advisory chats from this file. Update §3 and §5 whenever a stage
completes. **Every new batch goes into `AGENT_QUEUE.md` and gets committed** — a
batch that lives only in chat scrollback does not exist as far as the agent is
concerned.
