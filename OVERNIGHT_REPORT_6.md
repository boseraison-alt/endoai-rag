# Overnight Report 6 — `case-v3`

Uncited claims on the case path, and the latency that hid behind them.
Autonomous batch on `main`, 2026-09-01. Standing rules from `WORKLIST.md`
§0/§6 in full.

The fixture, throughout, is the clinician's own two-turn conversation:

> **Turn 1** — 20-year-old, no response to cold testing on tooth #20,
> well-defined periapical lesion, no filling, no cracks, Asian ethnicity.
>
> **Turn 2** — Is there anything a dentist can do to prevent it?

Both turns are committed under `eval/logs/case_answers/`, which is not
incidental: **case turns are persisted nowhere** — not `answers/`, not
`query_cache` — so the browser DOM and the server's in-memory job store were
the only copies of the conversation this batch is about.

---

## 1. Per item

| Item | Status | Before → After | Test file | Commit |
|---|---|---|---|---|
| A · Uncited claims in the stored answers — split, then fix the copy | DONE | citations in copied text **0 → 34 of 34**; the split: **26** copy-bug, **58** no-marker | `tests/test_citation_copy.py` (8 + 2 Playwright) | `387526e` |
| B · The case path gets Review's discipline | DONE | claims the detector catches **2 → 3** (turn 1), **2 → 7** (turn 2); 4 patterns added, `UNCITED_AUTHOR_MENTION` added | `tests/test_case_uncited_claims.py` (53) | `d32d558` |
| C · Targeted retrieval for DE management/prevention | DONE | papers naming the anomaly **15 → 24**; unattributed **7 → 2**, support flags **2/12 → 0/11** | same | `1894728` |
| D · Pin the prevention turn | DONE | `dens-evaginatus-prevention-followup` — the set's **first follow-up case**; PASS at attempt 1 | `eval/questions.json` | `25ace88` |
| E · Latency | DONE | turn-2 time-to-first-text **56.6s → 14.4s** | `tests/test_case_streaming.py` (24 → 25) | `ea6a54f` |

Suite: **1464 passed, 46 skipped** (1510 collected).

---

## 2. Item A — the dominant failure was a copy bug, not a citation bug

Measured live in the browser on the stored conversation, before anything
changed:

| | |
|---|---|
| citations rendered on screen | 34 |
| citations present in the copied text | **0** |
| characters shown | 18,045 |
| characters copied | 17,609 |
| delta | **436 — exactly the citations** |

`.claim-cite` carried `user-select: none`, so a native browser selection
skipped every one. Text pasted into a note carried the clinical claims and
none of the evidence, and every claim in it then looked uncited. **That is how
this item came to be filed**, and the split the item asked for is the reason
it did not stop there.

### The split (`scripts/analyze_case_uncited.py`, both turns)

| bucket | n |
|---|---|
| claims carrying a marker, lost only in the copy | **26** |
| claims with no marker at all | **58** |
| … of which the validator already flags | 4 |
| … of which it **misses a real clinical claim** | **6** → Item B |
| … background, `*Fits because:*`, `*Argues against:*` — take no marker by design | 48 |

Two different bugs needing opposite fixes. This item is the first.

### The fix, in two halves because either alone leaves a hole

`user-select: none` is gone, so the citation is part of the selection; and a
`copy` listener rewrites each citation **in the clipboard only** to
`[PMID N]`. The on-screen pill still reads "Sjögren U et al., J Endod.,
1990;16(10):498-504" — right for reading, far too long inline in a pasted
paragraph. The handler builds from `getRangeAt(0).cloneContents()`, which is
DOM-level and unaffected by `user-select`, so it is correct whether or not the
stylesheet cooperates.

Verified in the running app: pill renders, pill still clickable, computed
`user-select: auto`, clipboard plain text —

> Success rates exceed 86% for necrotic teeth with periapical lesions
> [PMID 2084204].

**Six mutants, six kills, browser half included.** The Playwright test drives
the shipped page, renders a marker through the page's own `renderAnswer`,
fires a real `copy` event and reads the clipboard back.

---

## 3. Item B — a chairside instruction is a claim

The original claim patterns catch a claim by its **numbers**. A chairside
protocol is an **instruction**, and an instruction can be entirely uncited and
entirely actionable without containing a statistic. Six went through untouched:

> "Reduce occlusal contact on the tubercle — selective equilibration…"
> "This is the single most impactful step."
> "Calcium hydroxide or MTA liner placement … is advocated in the literature."
> "Screen the entire mouth for DE."

**Four patterns added**: an appeal to the literature that cites nothing; an
imperative clinical instruction, anchored to the *start* of the claim unit so
"which would reduce the load" stays prose; a superlative about clinical
importance; and an interval written as a range.

That last one is the **only survivor of three the item listed**, and the
mutation run is what established it. A mutant disabling "0.5 mm per visit" and
"every 6 months" passed every test — `\d+ mm` and `\d+ months` were already in
the original unit pattern. Only "6-8 week intervals" escapes, because "week"
there is singular and the original list holds plurals. The two redundant
alternatives were written, found unkillable, and **deleted**: a pattern no
input needs is the regex equivalent of a test that cannot fail.

**(a) Verified, not assumed.** `validate_evidence_mapping` takes no `mode`
parameter, `_EVMAP_MAX_UNATTRIBUTED` is one constant, and the case path calls
the same function Review does. Pinned by `TestTheCasePathUsesReviewsThresholds`
so a future mode argument fails loudly.

**(b) Three honest endings** for a numeric directive — cite it, cut it, or
label it "standard practice, not from the retrieved evidence base". The label
has to actually work: `_UNSOURCED_LABEL_RE` makes a labelled claim count as
attributed. Without it, the prompt offers a move that fails anyway, the honest
answer and the silent one are punished identically, and the retry learns
nothing.

**(c) `UNCITED_AUTHOR_MENTION`, with no tolerance count.** An unattributed
claim can be a background sentence read too eagerly; "Sjögren et al.
demonstrated…" with nothing to click is unambiguous — the model reached for a
specific paper and did not wrap it. One is enough. Stopwords keep "Scenario A
and Scenario B" and "Cochrane and PubMed" out of it, and a marker anywhere in
the same claim unit counts, so the ordinary "Sjögren et al. found X
[[PMID:N]]" is untouched. The corrective message forbids the cheap fix
explicitly — attaching the nearest PMID clears the warning and misleads the
reader.

| detector catches | before | after |
|---|---|---|
| turn 1 — differential | 2 | **3** |
| turn 2 — prevention | 2 | **7** |

Turn 2 now exceeds the limit of 3 and will retry. That is a real behaviour
change and the point of the item; Item C regenerates it.

**Twelve mutants, twelve kills.**

---

## 4. Item C — the write-back floor was hiding the literature

**The first apply run wrote zero papers, and that was the finding.** Retrieval
was never the problem: 27 papers cleared the relevance gate. 13 were already
in the library and **14 fell below `learn_from_live_results`' flat write-back
floor of 50**. Among the rejected:

| PMID | score | |
|---|---|---|
| 37506764 | 35.4 | Current Management of Dens Evaginatus Teeth Based on Pulpal Diagnosis |
| 16410059 | 23.1 | Dens evaginatus: literature review, pathophysiology, and comprehensive treatment regimen |
| 37180325 | 35.9 | Apexification of dens evaginatus in a mandibular premolar |

The first is the single most on-point paper in existence for the answer this
item is about — a management scheme organised by pulpal diagnosis, which is
exactly the Scenario A/B/C structure the model invented for itself and could
not cite.

This is `WORKLIST.md` §1.5's defect on the write-back path: *a flat floor of 50
culls entire fields whose best papers score in the 40s by construction*. Dens
evaginatus is such a field. It is a developmental anomaly; its literature is
narrative reviews and case series with no n, no follow-up and no control arm,
and it scores in the 20s and 30s **because of what it is**.

**The floor is not lowered globally.** That changes every topic with no
measurement behind it and belongs in its own batch. It is a `--min-score`
argument on one hand-written, topic-specific ingest that has already applied a
relevance gate: every paper admitted names the anomaly in its own title or
abstract, which is a stronger guarantee than the score was giving. Dry run
first, split printed, applied at 30.

| | |
|---|---|
| papers naming the anomaly, in the library | 15 → **24** |
| written | 10, incl. 37506764 and the apexification series |
| off-topic, gate-dropped | 21 (the zero-hit broadening again) |

### The regenerated prevention turn

Same conversation, turn 1 replayed verbatim so only turn 2 is new:

| | before | after |
|---|---|---|
| unattributed claims | 7 | **2** (limit 3 — passes, no retry) |
| citation-support flags | 2/12 | **0/11** |
| labelled-unsourced lines | 0 | **1** |
| uncited author mentions | 0 | 0 |

Step 1 now ends "standard practice, not from the retrieved evidence base" —
Item B's third ending being taken. Step 3 carries real figures with markers:
86.8% vs 34.3% for calcium hydroxide [[PMID:41339865]]. **The answer did not
retry despite the stricter detector: it labelled instead**, which is the
outcome the escape hatch was built for.

---

## 5. Item D — the set's first follow-up case

`dens-evaginatus-prevention-followup` replays turn 1 from the stored transcript
and generates only turn 2, because a follow-up inherits an intent, an evidence
base and a differential — and a case set that can only express turn 1 cannot
pin turn 2, which is where every defect in this batch lived.

**The case failed on its first run and that was the point.** 7 unattributed
claims, and the retry produced **8**: the bonded-composite and
occlusal-adjustment steps rewritten in different words, still uncited. The
corrective message for `UNATTRIBUTED_CLAIMS` offered only "rephrase or delete"
— it never mentioned the label the *prompt* allows. The model had a third
honest ending available when writing and not when correcting, and a full Opus
regeneration arrived nowhere.

Re-run after the fix: **PASS at attempt 1**, 2 unattributed, 13 cited, 2/21
support flags, no retry.

**Harness, three additions:**

- `prior_turns`, inline or `content_file`, so a case can be a conversation. The
  referenced transcript is stripped of its provenance header — replaying that
  as the assistant's words would feed the model a note about itself.
- `max_unattributed` and `max_uncited_author_mentions`, read from the
  **product's own detectors** so the eval cannot drift from the validator it
  watches. `max_unattributed` is 3 — the product's own
  `_EVMAP_MAX_UNATTRIBUTED` — so the case fails exactly when the answer would.
- `check_claim_hygiene` is a **top-level function**, and that is not tidiness.
  Written inline, both checks survived a mutation to `if False:` with every
  test green, because the tests could assert the detector was *called* and
  never that its answer was compared to anything.

**Twenty mutants, twenty kills.**

---

## 6. Item E — readable at 14 s instead of 57 s

`scripts/measure_case_latency.py`, the DE two-turn fixture, three runs.

Before, all three timings on a turn were **identical**, because nothing reached
the job record until the answer, both guardrails and the support check had all
finished.

### Turn 2 — the follow-up

| | before | after streaming | after delta |
|---|---|---|---|
| time to first papers | 56.6 s | **11.1 s** | 13.3 s |
| **time to first text** | 56.6 s | **14.4 s** | 17.1 s |
| time to checks complete | 56.6 s | 55.3 s | 95.0 s\* |
| papers in the evidence base | 35 | 35 | 38 (15 carried) |
| cost | $0.121 | $0.121 | $0.222\* |

Wall time barely moved, **which is the point**. An answer that takes 55 s but
is readable at 14 s is a different product from one that shows a spinner for
55 s, and they have the same wall time. The 41-second guardrail tail now
happens underneath text the clinician is already reading.

\* the 95.0 s and the doubled cost are **not** the delta change. That run hit
an unrelated `FABRICATED_PMIDS` retry (PMID 18426478), confirmed in
`evidence_mapping.jsonl` — a second full synthesis. Reported as measured
rather than re-rolled until it looked better.

### Turn 1 — no claim is made

| run | first papers | first text | checks done | papers |
|---|---|---|---|---|
| before | 155.8 s | 155.8 s | 155.8 s | 63 |
| after streaming | 174.9 s | 179.2 s | 247.6 s | 136 |
| after delta | 92.1 s | 100.7 s | 159.8 s | 61 |

Turn-1 retrieval measured 155.8 / 174.9 / 92.1 s with 63 / 136 / 61 papers.
That spread is PubMed and the library, not this change, and a "92 vs 156"
improvement read off it would be noise. **The streaming benefit on turn 1 is
real but small in relative terms**, because turn 1 is retrieval-dominated: the
answer is readable ~9 s after the papers land either way, and the papers land
when they land.

### The three changes

1. **`ask_case_question` takes Review's three callbacks** — `stream_cb`,
   `abort_cb`, `phase_cb`, all defaulting to `None`, so every existing caller
   (the eval harness, the capture scripts) keeps the non-streaming path byte
   for byte.

2. **`phase_cb("checking")` fires when the model stops writing**, so the header
   chips say "checking…" for exactly the window in which that is true.

3. **Delta retrieval on follow-ups.** `case_prior_pmids` collects the PMIDs the
   earlier *assistant* turns cited and seeds them as candidates.

**The guardrail invariant is unchanged and is what most of the new tests exist
for.** `answer` is read off the final message, never off accumulated chunks,
and neither guardrail is reachable from inside `stream_cb` — a half-written
`[[PMID:312` reads as a fabrication and would warn the clinician about a good
answer. `partial_answer` is a separate job field from `answer`, cleared on
completion, and `checks_status` stays `"pending"` for the whole stream: the
chips never show a tick for text nobody has checked, which is **bug class (d)
in its worst form**.

**It is not a cache.** The evidence base is rebuilt every turn and no answer is
ever reused; only the candidate set carries. The seeds enter *after* the
routing gate, so a paper carried from the previous turn can never push a thin
topic onto the library route — context substituting for retrieval. Every gate
then applies to them unchanged.

**Thirteen mutants, thirteen kills** — after two survived the first run, and
both survivals were my tests' fault. See §8.

---

## 7. Decisions, with the alternatives rejected

| Decision | Rejected alternative | Why |
|---|---|---|
| Clipboard gets `[PMID N]`; the pill keeps the full citation | Put the short form on screen too | The pill is right for reading; the long form is unreadable inline in a pasted paragraph. Different media, different rendering. |
| Build the copy text from `cloneContents()` | Rely on removing `user-select: none` | DOM-level, so it is correct whether or not the stylesheet cooperates. Removing the CSS alone would leave the fix one stylesheet edit from silently reverting. |
| A labelled claim counts as attributed | Count it and let the answer retry | Otherwise the prompt offers a move that fails anyway, and the honest answer and the silent one are punished identically. |
| `UNCITED_AUTHOR_MENTION` has no tolerance count | Fold it into `_EVMAP_MAX_UNATTRIBUTED` | A named author with no marker is unambiguous in a way a background sentence is not. One is enough. |
| Two of three interval patterns deleted | Ship all three | The mutation run showed no input reaches them — the original unit pattern already had `\d+ mm` and `\d+ months`. |
| `--min-score 30` on one topic-specific ingest | Lower the global write-back floor | Changing every topic with no measurement behind it. Belongs in its own batch. |
| Carry the candidate **set** across turns | Cache the evidence base, or the answer | A cached turn-1 base serving turn 3 answers the follow-up from the wrong literature. Explicitly out of scope per the item. |
| Report the 95.0 s and the $0.222 as measured | Re-run until the retry did not fire | The retry is a real event on this path; hiding it makes the table a worse description of the product. |

---

## 8. What went wrong in my own work

**Three source-inspection tests let mutants through, in one session.**
`check_precedence` (case-v2.1), `check_claim_hygiene` (Item D), and
`test_the_validator_runs_after_the_phase_callback` (Item E). All three had the
same shape: the test could prove the code was *written* and never that it
*executed*. The Item E one compared `src.index()` positions, so a mutant
replacing `if phase_cb is not None:` with `if False:` passed — the call still
appeared in the source, above the validator, and never ran. Replaced with a
behavioural fixture modelled on `tests/test_streaming.py`'s `wired`, recording
the actual call order.

**A mutant that reports `[SKIP]` is not a mutant that passed — and I nearly
counted it as one.** "Completion leaves the unchecked partial in place" matched
Review's identical completion block as well as the case path's, so it was
never applied. Anchored on `images = [],`.

**Item D silently reversed an ordering `guardrails-v1` had measured**, and the
full suite caught it, not me. The three-move corrective message put MARK first,
on a message the model receives *after* being told its answer failed — the
moment a decorative citation is cheapest to add. The label and the ordering are
both satisfiable at once: REPHRASE, LABEL, then the marker move carrying its
`ONLY where…` condition. Pinned by a new test that states the collision, so the
next edit to that message has to see both halves.

**A commit message of mine reported a suite size that was wrong.** Item B says
"1540 tests passing, 46 skipped". The true figure under `pytest tests/` is
**1510 collected, 1464 passing, 46 skipped**, and no test module was lost
between then and now (52 modules then, 53 now — this batch added one). The 1540
came from a differently-scoped invocation and should not have been quoted.

**An `OSError EINVAL` writing `endo_ai.py` mid-mutation left the file mutated**
and the restore unwritten, so the working tree kept a mutant. Detected via
failing tests, restored by hand, and the mutation harness now writes through a
verify-and-retry helper. A harness that cannot restore is worse than no
harness.

---

## 9. Found, not fixed

- **The unsourced label attaches to the claim unit it appears in**, so the two
  sub-sentences of a labelled multi-sentence step are still counted
  unattributed. Under the limit on the measured turn. Widening the label's
  scope to the paragraph would whitelist real claims, so it is reported rather
  than papered over.
- **The flat write-back floor of 50 still culls narrow fields** on every path
  other than the one topic-specific ingest given `--min-score`. This is
  `WORKLIST.md` §1.5 and it wants its own measured batch.
- **`fetch_papers` broadens a query when a tier returns zero hits**, which is
  sensible on an ordinary question and destructive on a narrow one — it
  produced 21 off-topic papers here, all caught by the ingest's own relevance
  gate. The general path has no such gate.
- **Turn-1 case latency is retrieval-dominated and unmeasured as a
  distribution.** Three runs spanning 92–175 s is not enough to say anything.
- **Case conversations are still persisted nowhere.** This batch committed two
  transcripts by hand so the analysis is reproducible; the product still keeps
  them only in the browser DOM and an in-memory job store.

---

## 10. Cost

| | |
|---|---|
| API spend, whole batch | **$1.88** |
| … scripts (measurement, ingest, capture, eval) | $1.46 |
| … product paths | $0.43 |
| LLM calls logged | 108 |

Measured from `cost_log.jsonl` using the `source` field `guardrails-v1` added,
over the window from the `case-v2.1` close to this report.
