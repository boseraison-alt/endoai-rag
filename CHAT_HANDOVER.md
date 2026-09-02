# CURO — ADVISORY CHAT HANDOVER

Boot file for a **new advisory chat with Claude** (not the coding agent).

Open the new chat with:

> Read `CHAT_HANDOVER.md` and `AGENT_QUEUE.md` from my endo-ai-rag repo. You are
> picking up the advisory role described in §1. The agent is working through
> `AGENT_QUEUE.md`; I'll paste its reports for you to assess.

Three files, three jobs — don't confuse them:

| File | For | Contains |
|---|---|---|
| `CHAT_HANDOVER.md` (this) | the advisory chat | how we work, state, open threads, decisions |
| `AGENT_QUEUE.md` | the local coding agent | five stages of executable work, standing rules |
| `CURO_HANDOVER.md` | the coding agent | product state, invariants, backlog |

---

## §1 THE WORKING PATTERN

RB (endodontist, boseraison@gmail.com) runs a **local Claude Code agent** at
`C:\Users\boser\endo-ai-rag` that does all the coding. The advisory chat does not
write production code. Its job is:

1. Read the agent's pasted reports and say what they actually mean.
2. Diagnose problems and name the underlying bug *class*, not just the instance.
3. Write **paste-ready autonomous batch instructions** for the agent — the format
   is in `AGENT_QUEUE.md` §3–§7 and in RB's saved `agent-worklist` skill.
4. Assess competitor outputs and clinical answers RB pastes in.
5. Push back when a request conflicts with the product's own principles.

Standing permissions RB has granted: multiple parallel agents, no permission
prompts (`bypassPermissions`), autonomous overnight batches, ~$0.70 per
library-answer cost approved.

What RB wants from the advisory chat: plain language, a clear recommendation
rather than a menu, honest disagreement when warranted, and every batch written so
the agent can run it unattended overnight. RB frequently asks "explain in simple
words" — that request is real, answer it in prose without jargon.

---

## §2 WHAT CURO IS

An evidence-graded endodontics assistant. Curated PubMed library (~2,000+ papers,
Neon Postgres + pgvector) with per-paper provenance — evidence tier, COI tri-state,
retraction/supersession, MEDLINE status, pre-registration. Live PubMed fallback
with synonym-expanded queries and an authority guarantee. Tier-banded synthesis
with a fabricated-PMID validator and a claim-vs-abstract citation-support checker.
Streaming answers (~15 s to first text, 0.4 s cached). Three surfaces: Review
(literature question), Case discussion, Deep Learning curriculum. Five export
styles plus a self-contained reveal.js deck with clickable PMID→abstract pills, all
from one content-hash-shared slide spec in an approved dark design.

Models: **Opus** for synthesis, case reasoning, differentials, curriculum writing.
**Haiku** for search-term generation, the semantic-cache same-question gate, the
citation-support checker, routing. **MiniLM** (local, 384-dim) for embeddings and
cache similarity. **OpenAI tts-1-hd** for narration only.

Tier ladder, by study design and never by score: cochrane → level1 → level2 →
level3a → level3b → level4 → invitro → level5; `retracted` is terminal; unlabelled
bands to level5.

---

## §3 WHERE THINGS STAND

Last completed agent work: **dl-quality-v1 Item 5** — the laser curriculum
regenerated clean. The headline number: **5,653 → 12,555 words** on the same
question. Item 1 turned out to be four stacked defects, each exposed by fixing the
one before it: module writer capped at 3,200 (164 of 190 calls ever); stitcher
budget capped at 11,640 (23 of 26 calls ever); the SDK refusing long non-streaming
requests once the budget was corrected; a mid-stream connection drop escaping the
retry as a raw `httpx` error rather than `APIConnectionError`. Cost: $4.76 in
crashed attempts plus $2.51 for the clean run. 27 mutants killed, 50 tests in
`test_module_truncation.py`.

**The consequence that matters:** every critique of the *anesthesia* curriculum —
the Gemini review, the second-opinion comparison, the [F]–[J] defect list — judged
a document missing over half its text. `AGENT_QUEUE.md` Stage 2 [M] regenerates it
before auditing it, precisely so the agent doesn't fix bugs that no longer exist.

Everything outstanding is in `AGENT_QUEUE.md`, five stages, in priority order.
As of writing, **nothing in that file has been given to the agent yet**.

---

## §4 DECISIONS MADE — do not relitigate

- **No journal-identity weighting**, ever. RB asked for a slight JOE-over-IEJ
  preference on 2026-09-02 and, after being told it is impact-factor weighting by
  another name and contradicts the product's founding principle, chose the
  no-preference option. The remedy for missing canon papers is retrieval and
  ingestion fixes. Locked as invariant 11.
- **Out-of-domain content is quarantined and reframed** (2026-09-02), not refused
  and not silently mixed into cited prose. Curo may answer beyond its evidence
  base, but that content sits in a visually distinct `NOT FROM THE EVIDENCE BASE —
  UNVERIFIED` block, and the answer then returns to the endodontic decision it can
  support.
- **No scope or domain-filter widening** without the Stage 4 numbers and RB's
  sign-off.
- `monthly_maintenance.py` must not run `--apply` until after the demo.
- The X-ray / vision path stays **off** until a BAA exists.
- `cost_log.jsonl` is append-only.
- Never weaken a checker or gate to improve a number.

---

## §5 OPEN THREADS — what to expect back from the agent

**Stage 1 `trust-surface-v1`.** The one to watch. Curo rendered
`CHECKED AGAINST ABSTRACTS: 9/9 CONSISTENT` over an answer whose most actionable
paragraph — apixaban timing, tranexamic acid concentration, CrCl and age
thresholds — carried no citations at all. The checker only examines *cited* claims,
so uncited text is invisible to it and the banner asserted verification over
material nobody checked. Also fixes: impact factors being **displayed** in the
reference list (contradicts invariant 11 on screen); a raw `[[PMID:ESE-QG-2023]]`
leak; bibliography listing 29 papers for an answer citing 7; a score table sorting
across tiers so a position statement displays above a Cochrane review.

**Stage 4 `scope-measure-v1`.** Measurement only, ends in a memo and a decision for
RB. The question: should Curo read beyond endodontic journals. Current view — no to
"all dental journals", yes to topic-gated doors into adjacent specialties
(anesthesia, oral surgery, prostho, perio, radiology, oral medicine, paeds, oral
path), and **specialty guidelines (ESE/AAE/SDCEP/ADA) are probably higher value per
item than any journal expansion**. The numbers that decide it: the DOMAIN FAILURE
count in S2, and the per-domain relevance ratio in S3.

**Stage 5 `citation-audit-v1`.** Auditing ~50 citations from a competitor answer
that gave journal + year but no PMIDs. Hard rule baked in: unresolvable ≠
fabricated. The number that matters for the demo is **RESOLVED-but-PARTIAL** —
real paper, claim quietly broader than the abstract — because that's the failure a
reader can't see and a checker can.

**`ENDO_DOMAIN_FILTER`** excludes 48 of 124 Reader/OSU canon anesthesia papers and
is very likely also why the apixaban question retrieved nothing relevant. One root
cause, two symptoms. Do not let anyone widen it globally to fix a local problem.

---

## §6 COMPETITIVE FINDINGS

**vs OpenEvidence** (asked: Eliquis in a patient needing apicectomy). OpenEvidence
won, clearly — the question is a perioperative anticoagulation question that
happens to involve a tooth, and it had the right library (CHEST 2022 guidance) with
a real DOI. Curo had no relevant literature, said so correctly, then answered
anyway from general knowledge with no citations under a green verification tick.
**But** Curo asked the question OpenEvidence never asked: does this patient need
the surgery at all? It cited the Cochrane review (RR 1.15, 0.97–1.35) showing
non-surgical retreatment does about as well, making avoidance a legitimate option
in a bleeding-risk patient. That reframe is the differentiator in one sentence.
Strategic conclusion: **do not chase breadth.** Ingesting cardiology dissolves the
curation that makes Curo worth using.

**vs an SR/MA-restricted general model** (anesthesia). It beat Curo on presentation
— an evidence-level tag inline on every claim, explicit in-line flagging of its own
weak spots ("no SR/MA or RCT isolates this; consensus only. Flagged"), and honest
handling of conflicting meta-analyses. Curo has all that information and renders it
as bibliography badges instead. Two design lessons taken into the queue: tag
evidence level **at the point of claim**, and **declare** evidence gaps rather than
suppressing them (Curo's zero-evidence gate is silent, which is safe but teaches
the clinician nothing). What it could not do: a single verifiable PMID, or anything
resembling the COI flag Curo raised on its own Dentsply-funded source.

---

## §7 RECURRING BUG CLASSES — what to look for in every report

1. **Work discarded without a signal.** Module cap, stitcher budget, domain filter
   dropping 48 papers — three instances in one night. Anything that caps, filters
   or truncates must log and count what it dropped.
2. **Fail-open gates.** A check that shows nothing and therefore shows green. The
   verification banner over uncited claims is the worst instance so far.
3. **Assertions that can become vacuous.** A green test that has quietly lost the
   ability to fail buys false confidence. Now a standing rule: pair it with a test
   that fails when it goes vacuous.
4. **Batch metadata applied per-paper** (the original COI broadcast bug).
5. **Trusted stored labels** — verify against source, not against the database's
   own earlier guess.
6. **Untagged PubMed query terms** (`Cochrane Review[pt]` matching 180,686 records).
7. **Tests that grep source** instead of asserting on the prompt or data actually
   used at runtime.
8. **max_tokens truncation**, in every new form it takes.
9. **Retrieval pool leaking into presentation** — bibliographies, reference lists
   and "top papers" tables built from candidates rather than citations.

---

## §8 RB-ONLY ITEMS

1. **Re-zip the OneDrive backup without `.env`, and rotate all three secrets** —
   Anthropic key, OpenAI key, Neon database password. The current zip on the
   OneDrive Desktop contains live credentials; the git bundle beside it is safe
   (`.env` was never committed). **Still pending. Oldest open item.**
2. Save the two fixtures named in `AGENT_QUEUE.md` §0 before starting the agent.
3. Listen to 60 s of laser audio spanning "apexification" — confirm or clear the
   pronunciation flag.
4. Rehearse the demo on the presenting machine: 4 cached questions, 1 live, web
   deck citation click, video clip. Use the `endo-ai-noreload` config.
5. Decide the Stage 4 scope question when the memo lands.
6. Verify against full text before any of it reaches teaching material: buccal
   infiltration success being ~45–85% rather than 80–90%; articaine IO being
   evidence-supported (RCT, QuickSleeper, 81%); plain lidocaine being the wrong
   choice for the hypertensive branch.

---

## §9 SESSION HYGIENE

Start new advisory chats from this file rather than continuing long ones. Update
§3 and §5 whenever a stage completes. Keep `AGENT_QUEUE.md` as the single source of
truth for agent work — if a new batch is written, it goes in there rather than
living only in chat scrollback.
