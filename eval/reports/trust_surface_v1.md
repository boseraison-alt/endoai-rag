# `trust-surface-v1` — Stage 1 report

Fixture: `eval/fixtures/review_apixaban_apicectomy.md` (the Curo Review answer to
"eliquis in patients who needs apicectomy", captured verbatim).

Q1–Q6 and Q8 fixed with mutation-checked tests. Q7 measured; its hypothesis is
**partly confirmed and its explanation is wrong**, which is the most consequential
thing in this report.

| | before | after |
|---|---|---|
| tests | 1,686 passed / 50 skipped | **1,810 passed / 50 skipped** (+124) |
| mutants killed | — | **52 / 52** (3 only after the tests that let them survive were fixed) |
| suite wall clock | 5m43s | 3m28s |

Direct spend on this stage: **$0.0025** — two Haiku calls, to regenerate the
apixaban search terms for Q7.2. Everything else was measured offline against
stored answers and logs. No eval run (see *Eval delta*).

---

## The shape of the whole stage

Six of the eight items are the same defect wearing different clothes:

> **A presentation layer asserted something the engine never claimed.**

The banner asserted verification over text nothing had checked (Q1). The
answer asserted no distinction between what the library supports and what it
does not (Q2). The reference list asserted a journal metric that scoring does
not use (Q3). The bibliography asserted that 29 papers were drawn on when 7
were (Q5). The table asserted a cross-tier ranking the engine forbids (Q6).
The recommendation box asserted a caveat that was an empty template field (Q8).

Q4 is the odd one out and it is the most instructive: one shared regex knew
only one of the two id shapes the library actually stores, and **five of its six
consumers had never been told**. It is why the banner said 9/9 over ten cited
claims.

---

## Q1 — the banner counted what it checked, not what it did not

**Measured, before changing anything.** The answer rendered

```
CHECKED AGAINST ABSTRACTS: 9/9 CONSISTENT
```

directly above an uncited paragraph of drug directives: `>=4 hours after the
morning dose`, `tranexamic acid 4.8% mouthwash`, `CrCl <50 mL/min`, `age >75`,
`consider omitting the morning dose`, `Bridging with LMWH is not indicated for
apixaban`, `INR testing is not applicable`.

Both halves of that banner are true. `verify_citation_support` examines **cited**
claims, so an uncited claim is not one it disagreed with — it is one it never
saw. Presented alone, the count asserts verification over the whole answer.

**Why the existing gate did not catch it.** Two independent reasons, both measured:

```
_detect_unattributed_claims on the fixture        3 flagged
_EVMAP_MAX_UNATTRIBUTED (hard-fails ABOVE this)   3
```

It passed **by one claim**. And two of the directives were invisible to it in any
case — `Bridging with LMWH is not indicated for apixaban.` and `INR testing is
not applicable.` match none of the `_CLAIM_PATTERNS`, because those patterns
catch a claim by its **numbers** and a prescribing instruction need not contain any.

**Cause.** `verify_citation_support`'s denominator is the set of cited claims;
nothing counted the complement.

**What changed.** `_detect_uncited_directive_claims` — a **reporter, not a gate**.
It never blocks or rewrites; it produces the second number the banner must show.
Q2's decision is that Curo may answer beyond its evidence base, so the honest
handling of a labelled directive is to count it out loud, not to refuse it.

Three directive shapes: deontic (`should not be`, `is not indicated`, `is not
applicable`), imperative (`Omit …`, `Schedule …`), clinical quantity (a dose, a
concentration, an interval, a threshold). A **drug name alone fires nothing** —
otherwise every honest coverage disclaimer ("the retrieved evidence base does
not address apixaban") would inflate the number with exactly the sentences that
are being candid about the gap.

Unlike the validator's detector, `_UNSOURCED_LABEL_RE` does **not** exempt a
claim here. There the label is an escape hatch and must count, or the model
labels its content honestly and fails identically to the silent version. Here
the label is the thing being counted.

The count is computed on the answer text the status block attaches to, so every
surface carries it: browser, PDF, clipboard, deck, speaker notes.

**Before / after, rendered:**

```
before   ✓ Checked against abstracts: 9/9 consistent
after    ⚠ Checked against abstracts: 10/10 consistent
         · 6 claims not from the evidence base
```

(10, not 9 — Q4's denominator correction.) The block below the answer also
**names** the six, per standing rule 5.

**Fire rate**, across the 22 stored Deep Learning curricula: 197 of 2,883 claim
units, **6.8%**. Not a flood, not vacuous.

**Tests** 27. **Mutants** 13/13 killed — including the pair standing rule 4
requires: one that makes the banner warn unconditionally (killed by the
fully-cited fixture keeping its clean tick) and one that keeps the green tick
beside the warning half.

One mutant **survived first time**: an assertion looked for the directive
anywhere in the output rather than in the appended block, and the sentence was
still there — in the answer the block is attached to. Fixed, then killed.

---

## Q2 — out-of-domain content is quarantined and reframed

**Measured.** The answer's second paragraph opens `From the wider literature
(which this search did not return …)` and then delivers, in prose
indistinguishable from the cited paragraphs on either side of it, a complete
DOAC management protocol — bleeding-risk classification, a haemostatic-measures
list, a dosing interval, two patient thresholds, a bridging instruction. Nothing
in the rendering said which half of the answer the library stood behind.

**What changed.** The block is written **into the answer text, server-side**,
before anything reads it. Q2a requires it to survive every export path, and the
answer text is the one representation the PDF, the clipboard, the deck and the
narration all consume — so the browser *styles* the block, it does not create it.
Colours are the deck's dark tokens verbatim (`alert_bg #3a1520`, `alert_red
#f87171`), making it the only dark element in a light answer; a pale tinted box
in a page of pale tinted boxes is not unmissable.

**The boundary is the reframe.** The run starts at the label and extends forward
until a claim carries a citation — because a cited claim is, by definition, back
inside the evidence base. So Q2b ("never interleaved") and Q2c ("return to what
the library supports") are the same event. The fixture's own reframe — Cochrane
RR 1.15 (0.97–1.35), making non-surgical retreatment a legitimate option for a
patient at bleeding risk — is what closes the block. `UNREFRAMED_QUARANTINE`
makes that an element rather than an accident.

The run extends over **any** uncited unit, not only directive ones. That is what
pulls `Bridging with LMWH is not indicated` and `INR testing is not applicable`
— two short sentences with no numbers and no label of their own — into the block
with the paragraph they belong to. Leaving them outside would satisfy the letter
of the item and none of it: they are the two most quotable directives in the answer.

Interaction with the other checkers, both directions:

* quarantined content is **exempt** from the validator's unattributed-claim
  detector — the block header attributes it, structurally, and flagging it again
  would fail an answer for using the structure the prompt now requires;
* quarantined content is **still counted** by the banner's second number (Q2b:
  excluded from what was checked, never from what was not).

**Before / after, rendered** — the paragraph now sits in a bordered container
headed `⚠ NOT FROM THE EVIDENCE BASE — UNVERIFIED`, footed `Consult directly:
SDCEP · BSH · ACC/AHA — Curo has not retrieved or checked these sources`, with
the cited Cochrane reframe immediately below it. Verified end to end through the
shipped renderer.

**Tests** 29 (with Q8). **Mutants** 15/15 killed, including both
"delete-the-feature" directions.

---

## Q3 — impact factor removed from every rendered surface

**Measured.** `Cochrane Database Syst Rev (IF: 12.0)`, `Int Endod J (IF: 4.5)` in
the reference list; `IF 4.5` in the abstract popover.

**Cause — and it was upstream of the renderer.** The number was in
`format_paper_context_line` (`IF=12.0`) and the REFERENCES prompt template asked
for `Journal (IF: X.X)`. The model wrote what it was asked for. Stripping only
at the renderer would have left it free to reappear in prose, a table caption or
a speaker note.

**What changed.** Removed from the context line, from both REFERENCES templates,
and from the popover. `_SCORE_WEIGHTS_DESC` no longer tells the model the number
"is shown for reference only" — that sentence had become false.
`strip_impact_factor` cleans the answers already in the query cache; a cached
answer is a rendered surface.

It deliberately does **not** touch a bare `IF 4.5`, because a curriculum decision
tree is written as `IF … THEN … BECAUSE` rows. A mutant that widened the pattern
that far is killed by a test built on a real decision-tree row.

**Mutants** 5/5 killed.

---

## Q4 — the citation key was never only a number

**Measured.** `[[PMID:ESE-QG-2023]]` rendered raw in the Level I section.
`case-v3` fixed raw markers once and the fix held — because every patch spelled
the id as `(\d+)`.

**Cause.** `ingest_aae_guidelines.py` stores authority documents under synthetic
keys (`ESE-QG-2023`, `ESE-PS-VPT-2019`, `AAE-PS-obturation`); Bookshelf chapters
arrive as `NBK430685`. **Six consumers share `_PMID_RE` and exactly one had been
taught the other shape** — `validate_evidence_mapping` carried a local
`non_numeric` re-scan bolted on beside the shared pattern, which is precisely how
the two shapes drifted apart everywhere else.

The visible marker was the least of it:

* `_extract_claim_citation_pairs` built **no pair** for the ESE claim, so the
  banner read `9/9 CONSISTENT` over **ten** cited claims — a denominator that
  drops a citation without saying so;
* `_detect_unattributed_claims` read that sentence as carrying no marker;
* `presentations.text_budget.PMID_MARKER_RE`, the single chokepoint that is
  supposed to make a raw marker unable to reach a slide, let it through;
* `/api/abstract/<pmid>` answered **400** for a synthetic key, so rendering the
  pill without widening that guard would only have traded a raw marker for a
  dead one.

**What changed.** One pattern (`_PMID_ID_PAT`), mirrored once in the browser and
once on each deck path; the local re-scan deleted. A synthetic key never gets a
`pubmed.ncbi.nlm.nih.gov` href and is never sent to eutils.

**Before / after, rendered:**

```
before   ... guidance on DOAC management [[PMID:ESE-QG-2023]]
after    ... guidance on DOAC management ᴱˢᴱ ᵠᵘᵃˡᶦᵗʸ ᴳᵘᶦᵈᵉˡᶦⁿᵉˢ  (citation pill, opens the library copy)
```

**Tests** 40, asserted on **rendered output** rather than on a grep of the
template — a grep proves the pattern was edited; only the rendered string proves
the marker stopped reaching the page. **Mutants** 10/10 killed, including both
widening-too-far directions.

---

## Q5 — the bibliography was the retrieval pool

**Measured.** 29 papers listed, 7 cited. Sjögren 1990 was among the 22 — the same
uncited boilerplate the anesthesia curriculum carries. That is what shows the
defect is **structural, not a truncation artifact**, and that it affects Review as
well as Deep Learning.

**Cause.** The browser built the list from `job.papers`, which is
`evidence["_summary"]["all_scored"]` — the retrieval candidate pool. The deck
path already had this right (`webdeck.plan.build_reference_slides` takes
`cited_pmids`), which is why the defect was visible on one surface and not the other.

**What changed.** `assemble_bibliography(answer, papers)` is the one splitter, in
Python, beside the deck path. **In-text markers only** — a mutation showed the
fixture's own numbered reference list reproduced all seven ids on its own, which
means a padded reference list could re-inflate the bibliography it is supposed to
mirror. The pool is still disclosed, collapsed, under `Papers retrieved but NOT
cited in this answer`.

The evidence-shape chip now counts the same set the bibliography does — its
tooltip says "study designs behind this answer", and the designs behind an answer
are the ones it cited. **This moves a demo-visible number**: `1 COCHRANE · 25
RCT/SR · 1 CLASSIC · 2 COHORT` becomes the shape of the 7 cited papers.

**Mutants** 5/5 killed.

---

## Q6 — the table sorted across tiers

**Measured**, on the pool this answer actually had (reconstructed in
`tests/fixtures/apixaban_papers.json` from the answer's own table and bibliography):

```
score-only rank of the ESE position statement     1 of 29
score-only rank of the Cochrane review           29 of 29
```

In a table headed **"Top papers by evidence score"**, in an answer whose clinical
recommendation rests on that Cochrane review. Invariant 1: a score ranks only
*within* a tier. The engine has always been right about this; a table is a
ranking claim whatever its column header says.

**What changed.** Tier first, score within tier. An unknown tier sorts **last**,
not first. Each row names its tier, the column is labelled `Score / within tier`,
and the heading is now `Papers Retrieved — grouped by evidence tier` with a
caption saying a higher score in a weaker tier is not stronger evidence.

**Before / after, first row:** `ESE-QG-2023 · 87.0` → `27759881 · Cochrane · 73.3`.

**Mutants** 4/4 killed. One survived first time: the pool arrives already ordered
by score and `Array.prototype.sort` is stable, so a comparator that had discarded
the score entirely still produced a score-ordered result. The test now reverses
the input first.

---

## Q8 — the orphaned `not applicable.`

**Measured, not assumed.** Running the pre-fix caveat extractor on the fixture's
own recommendation:

```
trigger matched at : 1654
source sentence    : 'for apixaban. INR testing is not applicable.'
captured tail      : '.'
caveat rendered    : 'not applicable.'
```

**Cause.** `recRaw.match(/(?:does not apply|not applicable|…)\b([^.]*\.)/i)` — the
captured tail *is* the caveat. When the trigger phrase ends its sentence there is
no tail, so the box rendered a caveat line reading, in its entirety, `not
applicable.`

**What changed.** An empty field renders nothing. A real caveat ("This does not
apply when the canal is calcified beyond negotiation") still renders — the mutant
that deletes the feature outright is killed by that test.

---

## Q7 — why retrieval returned no anticoagulation literature (measure only)

**This is the item that changed my understanding, and its answer is not the
hypothesis.**

### 1. Was live PubMed attempted? **No.**

```
cost_log, 2026-09-02
  07:37:07  generate_search_terms          $0.0006
  07:37:12  generate_multi_search_terms    $0.0019
  07:38:02  ask_clinical_question          $0.6904
  07:38:05  verify_citation_support        $0.0101
                                    TOTAL  $0.7031

pubmed_audit (proof-of-fetch) rows in that hour   0
last pubmed_audit row anywhere                    2026-09-02T00:13:48
```

Fifty seconds of retrieval between 07:37:12 and 07:38:02 and **not one esearch**.
`fetch_papers` writes an audit row on every path, including failures.

### 2. Did the generated search terms carry the vocabulary? **Yes — 6 of 7.**

```
[0] apicectomy … AND (Eliquis OR apixaban OR "factor Xa inhibitor*" OR anticoagulant*) …
[1] "apicoectomy" … AND (apixaban OR "direct oral anticoagulant*" OR DOAC*) …
[3] (apicoectomy OR apicectomy) AND ("oral anticoagulant*" OR warfarin OR rivaroxaban …)
[6] "tooth extraction" OR "dentoalveolar surgery" … AND (apixaban OR DOAC*) …
```

**Query generation was not the failure.** The system asked exactly the right
questions and then never asked them of PubMed.

### 3. What the library returned, and the gate's verdict

```
raw KNN hits            200    gate needs >= 20    PASS
above similarity 0.55    14    gate needs >= 12    PASS  (by two)
high-tier among them     11    gate needs >= 1     PASS
newest on-topic year   2026    gate needs <= 3y    PASS

GATE VERDICT: LIBRARY — live PubMed skipped
```

And the finding that matters:

> **0 of the 14 papers above the similarity floor mention anticoagulation,
> bleeding, haemostasis or any DOAC anywhere in their title.**

The top hits are *histopathologic diagnosis of periapical lesions*, *conventional
vs guided apical microsurgery*, *periapical cysts of deciduous teeth*. Every one
is a good match for "apicectomy" and none of them is about the other half of the
question.

**The coverage gate measures endodontic similarity, not question coverage.** It
cannot detect that half the question has zero support, because every one of its
four conditions is satisfied by the endodontic half alone. It passed
`min_relevant` by two.

### 4. The hypothesis: is `ENDO_DOMAIN_FILTER` the mechanism? **No — but it would have been.**

`ENDO_DOMAIN_FILTER` is a **PubMed query string**, interpolated into
`fetch_papers`'s esearch term at `endo_ai.py:3062`. It is not a post-retrieval
filter and **it does not exist on the library path at all**. It never ran for this
question.

Two live probes of the same clinical query:

```
WITHOUT the endo domain filter    PubMed count = 133
WITH the endo domain filter       PubMed count =  19
                                  removes 114 of 133 (86%)
```

So the filter *would* have excluded 86% of the answering literature — had the
query ever gone live.

### Verdict, for Stage 4

The hypothesis is **partly confirmed, and it names the wrong mechanism**. There is
one root cause with **two independent enforcement points**, and this question hit
the one nobody was looking at:

1. **the library-first coverage gate** — fired here, silently, and skipped PubMed;
2. **`ENDO_DOMAIN_FILTER`** — did not fire here, and would have removed 86% of
   the answer if it had.

Both encode "endodontics only": the filter explicitly, the library implicitly,
because its corpus was ingested through the same constraint. Widening the filter
alone would **not** have fixed this question — the gate would still have served the
library and never reached the widened query.

Carried to Stage 4 (`scope-measure-v1`) as two things to measure separately:

* **S2** must record the **gate verdict** per question, not only whether PubMed was
  attempted — "live PubMed attempted: no" and "domain filter excluded N" are
  different failures and this question shows they can be confused.
* **S3**'s shadow run must disable the *coverage gate* as well as the filter, or it
  will measure a code path this class of question never reaches.

Standing rule 6: **no gate was weakened here.** Nothing about the gate was changed —
this stage was measurement only for Q7.

---

## Eval delta

**No eval was run for this stage.** Stage 1's done-when does not call for one, and
runs are serial and expensive. Instead the two changes that could move validator
behaviour were replayed **offline against all 138 stored answers** (`answers/`,
`learn_history/`, the curriculum fixtures):

```
validator verdict passed BEFORE   54 / 138
validator verdict passed AFTER    54 / 138
verdicts CHANGED                   0

answers that gain a quarantine block        2 / 138
 ...of which UNREFRAMED (would retry)       1   (already failing for another reason)

unattributed-claim count, net across corpus  -1
  (the pseudo-id claim now correctly counts as cited)
```

**The retry rate is unmoved on the historical corpus.** The new
`UNREFRAMED_QUARANTINE` condition can only fire on an answer that already carries
a quarantine block, and the labelling vocabulary is rare — it appears when the
question is out of domain, which is what it is for.

The first eval run (Stage 2 or Stage 3 B4) should still be read against this
baseline rather than the pre-stage one, and any case that moves explained there.

---

## Open questions / decisions for RB

**1. The banner's second number will show on most answers.** Measured across the
stored corpus:

| corpus | n | with ≥1 uncited directive | median | max |
|---|---|---|---|---|
| Review answers | 113 | 88 | **2** | 16 |
| Deep Learning curricula | 22 | **22** | **8** | 16 |
| curriculum fixtures | 3 | 3 | 16 | 19 |

On the Review path — the demo surface — the median is 2 and the apixaban fixture
is 6. On Deep Learning **every** curriculum shows it, median 8. These are real
uncited directive claims; the count is not inflated. But a warning that appears
on 22 of 22 curricula is ambient rather than alarming, and the honest options are
(a) show it as-is, (b) show it on Review and per-module on Deep Learning, or
(c) fix the underlying density on the DL path — which is Stage 2's item I.

I have **not** tuned the detector to make this number smaller (standing rule 6).
Deciding what the DL banner does is yours.

**2. The evidence-shape chip now describes the cited set, not the pool.** `1
COCHRANE · 25 RCT/SR · 1 CLASSIC · 2 COHORT` becomes the shape of 7 papers. More
honest, materially smaller, and visible in the demo. Say if you want the pool
count kept somewhere in the header.

**3. Q7's finding changes what Stage 4 must measure.** See the verdict above: the
scope question cannot be decided from filter numbers alone, because the gate that
actually fired is a different one.

**4. `CHAT_HANDOVER.md` was swept into the Q1 commit.** It was untracked when I
ran `git add -A`; it is a legitimate repo file and nothing was lost, but it is
recorded in a commit about the trust banner. Later commits in this stage use
explicit paths.

---

## Files touched

| file | why |
|---|---|
| `endo_ai.py` | `_PMID_ID_PAT`/`_REF_PMID_RE` (Q4); `_detect_uncited_directive_claims` (Q1); quarantine + reframe check (Q2); `strip_impact_factor` (Q3); `assemble_bibliography` (Q5); `finalise_answer_text` chokepoint; prompt rules |
| `app.py` | abstract route accepts synthetic keys (Q4); `cited_pmids` in `/status` (Q5); cached answers normalised on the way out (Q2/Q3) |
| `templates/index.html` | citation-key pattern + local-key rendering (Q4); banner second half (Q1); unverified block + CSS (Q2); popover IF removed (Q3); cited-set split and not-cited disclosure (Q5); tier-first table (Q6); empty caveat (Q8) |
| `presentations/text_budget.py`, `webdeck/citations.py` | the deck chokepoints saw one id shape (Q4) |
| `tests/js_harness.py` | one shared list of the JS declarations the renderer needs — a hand-maintained copy in three files went red twice in this batch |
| `tests/test_pseudo_pmid_keys.py`, `test_uncited_directives.py`, `test_quarantine_unsourced.py`, `test_bibliography_and_ranking.py` | 124 tests |
| `tests/fixtures/apixaban_papers.json` | the answer's own 29-paper pool, for Q6 |
