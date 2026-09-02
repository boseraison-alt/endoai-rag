# CURO — SESSION HANDOVER

**Written 2026-09-02, end of the agent session that ran Stage 1 and amendments
A1–A16.** Boot from this file plus `AGENT_QUEUE.md`; the queue is still the
single source of truth for what to do next, and this file says what happened,
what state the machine is in, and where the traps are.

```
HEAD            de88e4a
tag             trust-surface-v1  (Stage 1 complete)
tests           1,686 -> 1,932 passed, 50 skipped   (~6 min, serial)
spend today     $7.75 across 96 LLM calls
pushed          origin/main up to date; OneDrive bundle refreshed
```

---

## 1. Start here — three things to check before doing anything

**1. Is the server running the code you are reading?** Three false readings in
this project have come from a stale process (A4, and twice before).

```bash
curl -s http://127.0.0.1:5003/health
```

`git_revision` must match `git rev-parse --short HEAD`. The demo config
`endo-ai-noreload` runs `debug=False`, so **Flask caches templates and never
reloads Python** — every change to `templates/index.html` or any `.py` needs a
restart before it is visible. A16 and A15 were both verified only after one.
`git_dirty: true` with a matching revision is fine: the process runs the working
tree.

**2. `git status` before committing.** Two files in the tree are RB's, not the
agent's — `AGENT_QUEUE.md` and `eval/COMPARISON_QUESTIONS.md`. Use explicit
`git add <paths>`; `git add -A` swept `CHAT_HANDOVER.md` into a commit about the
trust banner earlier today.

**3. The Bash tool mangles backslashes.** Writing a regex through a heredoc
turned `\b` into a literal backspace byte (0x08) inside `endo_ai.py`, and the
pattern silently matched nothing. Write Python patches with the Write tool and
run the file; do not pipe regex source through the shell.

---

## 2. What was done

Every item has a report in `eval/reports/`. The reports carry the measurements;
this is the index.

| item | outcome | report |
|---|---|---|
| **Stage 1** Q1–Q8 | complete, tagged `trust-surface-v1` | `trust_surface_v1.md` |
| **Stage 2** M1–M2 | regenerated + re-observed; M3 open | `dl_quality_v2.md` |
| **A1** coverage gate | shipped, threshold 3 | `a1_coverage_gate.md` |
| **A3** banner counts | adjudicated, sharpened, made actionable | `a3_banner_adjudication.md` |
| **A4** build provenance | verdict PRE-FIX; server restarted | in `dl_quality_v2.md` |
| **A5a** missing RCTs | mechanism found; **A5b open** | `a5a_missed_rcts.md` |
| **A7** guideline banding | dry-run only, **not applied** | `a7_guideline_banding_dryrun.md` |
| **A9a** reference provenance | audit only; **A9b/c open** | `a9a_reference_provenance.md` |
| **A13** term degradation | measured; no generator change needed | `a13_term_degradation.md` |
| **A15** unified search bar | built and verified live | — |
| **A16** cached answers | fixed; demo **GO** | `a16_cached_answers.md` |

### The four findings that changed how the system is understood

**Q7 / A1 — the gate asked four questions about the corpus and none about the
question.** For the apixaban question, live PubMed was never attempted: zero
esearch rows for the whole run. `ENDO_DOMAIN_FILTER` never ran, and query
generation was not the failure — 6 of 7 generated terms carried apixaban / DOAC
vocabulary. The library-first gate passed all four conditions and
short-circuited, and **none of the retrieved papers mentioned anticoagulation**.
Every condition was satisfiable by the endodontic *half* of a two-part question.
Fixed by a fifth condition reading the query's own AND-groups.

**A5a — the missing RCT was retrieved, then discarded.** Karaoğlan *Int Endod J*
2022 (PMID 35488883) is in the library and was a KNN hit at similarity 0.648,
above the floor. Then `bucket = bucket[:MAX_RAG_PAPERS_PER_TIER]` cut it — 30 of
69 candidates discarded with no log, ranked by **score**, which is a
study-quality proxy, not relevance. Similarity is used as a gate and then thrown
away. The answer then declared no such study exists. **This is the deepest open
defect.**

**A16 — a cache is a time capsule.** `/history/<id>` and
`/learn_history/<file>` served stored answers with no normalisation at all, so
every server-side Stage 1 fix stopped at `/status`. 10 of 10 cache rows rendered
the whole retrieval pool as a bibliography.

**A9a — the model invents bibliographic metadata.**
`format_paper_context_line` shows the model no journal name, yet the REFERENCES
template asks for one. Every journal string in a Review reference list is
generated with no source; ~17% of recent ones are wrong. The catastrophic class
(a paper presented as a Cochrane review when it is not) ran at 39% in April/May
and is at **zero** since August.

---

## 3. State of the machine

**Server.** `endo-ai-noreload` on port 5003, `debug=False`. Restart with the
Browser pane's `preview_start`, or:

```bash
python -c "import app; app.app.run(debug=False, host='127.0.0.1', port=5003, threaded=True)"
```

**Demo — GO.** All four cached questions render every Stage 1 fix (A16d).
**Question 1 takes 9.2 s on the first ask and 1.0 s after** — embedding-model
load on a cold process. If the machine is restarted just before presenting, ask
question 1 once to warm it.

**Database.** Nothing was migrated. `endo_papers_rag` is untouched: 2,909 rows.
A7's banding is dry-run only.

**New logs.** `term_degradation.jsonl` (A13c) is gitignored and redirected in
`conftest.py`. Rule §1.15 now requires that redirect in the same commit.

**Fixtures added.** `eval/fixtures/review_retreatment_visits.md` (A5),
`eval/fixtures/curricula/anesthesia_after.txt` + metrics (Stage 2 M1),
`tests/fixtures/apixaban_papers.json` (Q6).

---

## 4. Open work, in the order the queue last set

1. **A5b** — the cap fix plus three ingestions (Karaoğlan 35488883 present but
   cut; Toia 34688794 absent; Schwendicke 28148534 present but unreached).
   Dry-run with delta split. **Done when the retreatment question retrieves
   both 2022 RCTs.** Note A5a's conclusion: this needs three separate fixes and
   A1 is not one of them — fix the cap first, since a gate that routes correctly
   into a stage discarding 43% of the pool has only moved the problem.
2. **A5c** — the gap-declaration rule. As written it keys on whether live
   PubMed was queried, which **would not have caught** the retreatment answer:
   the evidence was retrieved and discarded, not unsearched. It needs a second
   clause — no gap declared over a sub-question whose candidates were cut by a
   cap.
3. **A10** — section-aware citation support. A10d's flip count by surface is
   still owed, before the flag goes live.
4. **A9b/A9c**, **A11**, **A14**, **A7 apply**, **A8**.
5. **Stage 2 M3** (G, J-onset-wait), **Stage 3**, **Stage 4** (measurement only,
   ends in a decision for RB).

---

## 5. Decisions waiting on RB

* **The DL banner median did not move.** Review fell 2 → 1; Deep Learning stayed
  at 8 with 26 of 26 curricula flagging. A3b's rule says a mostly-TRUE split
  means the defect is in generation, so the count will not fall until Stage 2
  item I changes what the modules write. **It should not be made quiet by
  touching the detector.**
* **Item I is a gate class Curo does not have.** The hypertensive plain-lidocaine
  directive is cited to PMID 40705444, and the abstract does contain the
  sentence — as the trial's *method*, not its finding. Every gate passes it. A10
  is scoped for this; say whether it is wanted before the demo.
* **A7's scoring inconsistency**, reported and not acted on: 13 hand-ingested AAE
  statements score 90.0, above every Cochrane review in the library (max 85.9),
  while PubMed-indexed ESE position statements score 50.4 and 30.9. A12 says
  banding only, so the scores stand.
* **A9's scope widened by its own audit** — the recommendation is to stop the
  reference line being model-written at all, not to hand the model the journal.
  One open question there: whether the descriptive clause stays.
* **§10 item 7 is half-answered.** The plain-lidocaine hypertensive
  recommendation traces to a trial's control-arm setup, not to a finding about
  primary blocks. Full-text verification is still yours.

---

## 6. Traps this session hit, so the next one does not

* **A test that asserts around the production expression proves nothing.** A
  mutation deleting the coverage condition from the real gate in `app.py` left
  all 30 A1 tests green, because every one asserted on the helper functions or
  a local copy of the decision. This is now standing rule §1.14, and it happened
  *inside the item written to answer the same complaint in A4*.
* **A seed is not a freeze.** A3's 40-claim sample was drawn with a fixed seed,
  then the detector changed, then the same seed returned different claims and
  the hand verdicts silently misaligned. Rebuilt from git. Rule §1.16.
* **Test against the variants the corpus contains.** Every Q3 test used a
  numeric impact factor; the model writes `(IF: n/a)`. Only the live go/no-go
  caught it. Rule §1.17.
* **Read-time transforms must be idempotent.** `finalise_answer_text` was not:
  the status block quotes flagged claims, those quotes carry the quarantiner's
  vocabulary, and a second pass nested the trust banner inside the block it
  reports on. Rule §1.18.
* **Measure before believing a premise.** A6's stated premise (the IF field is
  unreliable) did not survive contact with the data — no journal carries two
  values. A13's premise (degradation is a routing problem) did not either — the
  primary term has never degraded in 149 runs. Both items changed shape after
  measurement, which is what §1.1 is for.
* **Check the checker.** Two of A16d's three NO-GO lines were my own test's
  false alarms. Correct the instrument, do not accommodate it.

---

## 7. How to run things

```bash
python -m pytest -q                      # ~6 min, serial
python -m pytest tests/test_x.py -q      # one file
python scripts/regenerate_curriculum.py --topic anesthesia --compare <before>
```

**Mutation checking** is not scripted into the repo. The harness used all
session lives in the session scratchpad and takes a JSON spec of
`{name, file, old, new, tests}`, applies one mutation, runs the tests, reverts.
Build anchors by **reading the exact source lines** rather than typing them —
several specs failed with `NO-ANCHOR` until they did. Worth promoting into
`scripts/` if the next session does more of it.

**Eval runs are strictly serial** (§1.9) and none was run this session; the
first one should be read against the current baseline, not the pre-Stage-1 one,
and every case that moves explained (§1.13).
