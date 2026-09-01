COMPLETE

# Overnight batch 2 — "grounding-v2"

Six items, all attempted, five landed with measurements and one (Item 2)
landed with its recorded hypothesis **falsified** and a different, real defect
fixed in its place.

**Headline.** The citation-support flag rate on the LIVE Review path —
measured for the first time in this project — went **20.6% (7/34) → 0.0%
(0/51)** across three changes, on a denominator that grew rather than shrank
(Fisher exact p = 0.0011). The library-pinned Review subset did not move, and
the Deep Learning path did not improve.

---

## 1. Per item

| Item | Status | Before → After | Test file | Commit |
|---|---|---|---|---|
| **1** Synthesis grounding rule | Done, measured on 3 strata | live **20.6% → 9.4%** (rule alone); library 8.2% → 8.9%; curriculum 8.5% → 13.3% | `tests/test_grounding_rule.py` | `0bf11a2` |
| **2** "Longest paragraph" heuristic | Done — hypothesis falsified, a different defect fixed | 0/198 abstracts lose anything; **179 rows** held a non-abstract, **124 healed** | `tests/test_abstract_selection.py` | `981c7a9`, `cee013e` |
| **3** DL flag-rate diagnosis | Done, all 37 flags classified, majority cause fixed | 81% checker artifact; genuinely-unsupported rate **3.0%**; DL 13.3% → 13.0% | `tests/test_support_check_sees_whole_abstract.py` | `c06dde1` |
| **4** Narration/slide sync | Done, verified end to end with real TTS | autoplay **off → on**; 21 segments == 21 slides, ffprobe 523.46s | `tests/test_deck_narration_sync.py` | `73dade5` |
| **5** Maintenance script | Built, dry-run end to end, **not scheduled** | n/a | `tests/test_monthly_maintenance.py` | `27dcd74` |
| **6** Close | Done | suite 1,269 → **1,377**; demo re-warmed; tag `grounding-v2` | — | — |

Commit hashes are the primary landing commit per item; several items also have
a measurement commit carrying only logs (`1885fef`, `b2b2839`, `24c1035`).
Two cross-cutting fixes have their own commits: `d137c90` (the eval-window
contamination and the half-marker) and `b6d47cd` (rescore backups + the
maintenance end-to-end run). The harness work that made the measurements
possible is `88e9105`, and the read-only measurement scripts are `3d5bf9f`.

---

## 2. Item 1 — the grounding rule

Every synthesis prompt mandated a `[[PMID:N]]` marker on every standalone
clinical claim and **none of them said what to do when no retrieved paper
supports one**. `_build_corrective_message` pushed the same way — "Add markers
from the evidence base, OR rephrase" — on a message the model receives *after*
being told its answer failed validation, which is the moment a decorative
citation is cheapest to add and hardest to notice.

One constant, `_GROUNDING_RULE`, spliced into all three synthesis prompts
(Review, curriculum module, case). It states that a marker is a factual claim
*about the paper*, asks the model to find the language it could quote if a
clinician asked "where does it say that?", and supplies the third option the
prompt was missing: cite a different paper, weaken the sentence to what this
one states, or write it unmarked. It does **not** relax the marker mandate.

Four named traps, each read off a real flagged pair from Item 3's
hand-judgement: a mechanism claim cited to an outcomes review; a numeric
parameter cited to a paper that does not report it; an argument from silence;
a finding generalised past the paper's scope.

### The numbers, all measured with the answer cache bypassed

**Live-pinned Review — five cases, the first measurement of this path.**

| case | before | + rule | + whole abstract | + collapsed fix |
|---|---|---|---|---|
| retreatment-vs-microsurgery | 2/8 25.0% | 0/2 0.0% | 0/3 0.0% | 0/3 0.0% |
| cracked-tooth-prognosis | 1/9 11.1% | 0/7 0.0% | 0/10 0.0% | 0/19 0.0% |
| bisphosphonates | 0/5 0.0% | 3/4 75.0% | 1/4 25.0% | 0/10 0.0% |
| pregnancy | 2/8 25.0% | 0/3 0.0% | 0/4 0.0% | 0/6 0.0% |
| intentional-replantation | 2/4 50.0% | 0/16 0.0% | 2/4 50.0% | 0/13 0.0% |
| **TOTAL** | **7/34 20.6%** | **3/32 9.4%** | **3/25 12.0%** | **0/51 0.0%** |

**Library-pinned Review — the three cases behind the 39.4 → 8.5 → 4.3% history.**

| case | before | + rule | + whole abstract |
|---|---|---|---|
| single-vs-multiple-visit | 1/13 7.7% | 4/15 26.7% | 0/12 0.0% |
| naocl-concentration | 3/23 13.0% | 0/15 0.0% | 2/24 8.3% |
| pips-vs-ultrasonic | 0/13 0.0% | 0/15 0.0% | 1/12 8.3% |
| **TOTAL** | **4/49 8.2%** | **4/45 8.9%** | **3/48 6.3%** |

**Deep Learning — two laser curricula.**

| case | before | + rule | + whole abstract |
|---|---|---|---|
| laser-live | 7/116 6.0% | 14/120 11.7% | 15/120 12.5% |
| laser-library | 13/119 10.9% | 18/120 15.0% | 16/119 13.4% |
| **TOTAL** | **20/235 8.5%** | **32/240 13.3%** | **31/239 13.0%** |

### What is and is not significant

| comparison | p (Fisher exact, two-sided) |
|---|---|
| live, before vs all three fixes (7/34 vs 0/51) | **0.0011** |
| live, before vs grounding rule alone | 0.31 |
| curriculum, before vs grounding rule | 0.11 |
| library, before vs all fixes | 1.0 |

**Only the live endpoint is significant, and only for the three changes
together.** No single change carries its own p-value. The report claims
exactly that and no more.

### The target, and the number it was set against

The brief's target was "Review subset at or below 4.3%". The library subset
measured **8.2% on the same three cases at the start of tonight**, with
nothing changed in between — so **4.3% (2/46, 2026-08-31) was a favourable
draw**, not a level. Against tonight's own before-number the subset finished
at **6.3%**, which is lower; against 4.3% it is higher. Both numbers are
above, and neither movement is significant.

### The one thing that did move, and why it is not a citation-count artefact

A rule whose third option is "write the sentence unmarked" can lower a flag
rate by producing fewer citations. It did not: the live denominator went
**34 → 51**. Half as many flags on half again as many citations, then none.

---

## 3. Item 2 — the "longest paragraph" heuristic

**The recorded hypothesis is false.** `HANDOVER.md` had it that this heuristic
loses the conclusions of structured abstracts, the way the ingest truncation
did. Measured against efetch XML on 198 library PMIDs, 95 of them structured:

| | |
|---|---|
| abstracts losing >20 chars to the collapse | **0 of 198 (0.0%)** |
| abstracts losing a CONCLUSIONS section | **0 of 198 (0.0%)** |
| text the collapse keeps | **100.0%** |

PubMed's text renderer emits BACKGROUND / METHODS / RESULTS / CONCLUSIONS as
one blank-line-free block, so the "longest paragraph" *is* the whole
structured abstract. `scripts/measure_paragraph_collapse.py` records this, and
a test pins it so nobody fixes a loss that does not happen.

**A methodological note on that measurement.** Its first run drew `ORDER BY
pmid LIMIT 60` — the oldest 60 rows in the library, which are 1990s
single-paragraph abstracts and the one stratum the heuristic cannot hurt. It
reported 0.0% on a biased draw and the right answer for the wrong reason. The
draw is now `ORDER BY md5(pmid)` and the biased version is recorded in the
script's docstring.

### The real defect: over-capture, and it is live

"Longest paragraph" is a proxy for "the abstract", and two other blocks in a
PubMed text entry can be longer:

- **the author-affiliation list.** PMID 39743567, a consensus with ~30
  institutional addresses, stored **6,304 characters of university
  departments** in place of its 707-character abstract.
- **a foreign-language abstract**, printed under `Publisher:`. PMID 41337506's
  Portuguese version is longer than its English one.

Both reached synthesis as the paper's text **and** were written into
`abstract_cache`, which is what `verify_citation_support` reads. A paper whose
"abstract" is a list of addresses flags every claim cited to it, and the
clinician sees the flag with no way to know why.

| table | before | after |
|---|---|---|
| `endo_papers_rag` | 4 of 2,348 (0.17%) | **2 of 2,349 (0.09%)** |
| `abstract_cache` | 175 of 9,985 (1.75%) | **38 of 10,137 (0.37%)** |

124 rows rewritten from efetch XML. The 40 that remain are records PubMed
holds no abstract for at all — comments, letters, editorials — and are left
alone deliberately: blanking them would be a second data loss, and an empty
abstract silently *skips* that paper in the support check, so the guardrail
would go quiet rather than complain.

`_select_abstract_paragraph` is now shared by all four parsing sites, which
had each kept their own copy and already drifted.

**Backups, per the standing rule.** `endo_papers_rag_collapsed_backup`
(abstract, title, **embedding**) and `abstract_cache_collapsed_backup`
(abstract, title, source), run_id `collapsed_abstract_repair`. The embedding is
in that list because the two library rows were re-embedded afterwards — the
column the migration *writes*, not the column it is *about*.

Idempotent and resumable, verified the way the last repair was: a second dry
run after the apply reports 0 rows would change.

---

## 4. Item 3 — why Deep Learning flags higher

**All 37 flags from the two curricula were hand-judged, not a sample of 20.**
37 is the whole population of flags from the 24/118 and 13/116 runs, so there
is no sampling question. `eval/logs/dl_flag_verdicts.json` records a verdict
and a reason for every one; `scripts/classify_dl_flags.py` regenerates the
evidence.

| verdict | n | share |
|---|---|---|
| checker artifact — abstract tail withheld from the judge | 17 | 45.9% |
| checker artifact — the extracted "claim" is not one claim | 13 | 35.1% |
| **genuinely unsupported** | **7** | **18.9%** |
| abstract unusable | 0 | 0.0% |

**81% of Deep Learning flags are artifacts of the checker, not bad citations.**
Against the 234 pairs those two runs checked, the genuinely-unsupported rate
is **7/234 = 3.0%** — in line with Review's, not four times it.

So the answer to "why does a curriculum module flag higher than a Review
answer?" is largely **that it does not**. Two structural reasons explain the
gap, and both are consequences of the curriculum prompt's own requirements:

1. **A curriculum has sections Review does not.** The Decision Tree emits
   `IF / THEN / BECAUSE` across lines and the Clinical Protocol Summary emits
   table cells. `_extract_claim_citation_pairs` has no rule for either, so a
   seven-branch decision tree becomes ONE claim carrying seven papers'
   markers — seven flags from one blob. That is 13 of the 37.
2. **Curriculum claims are more numeric and more specific**, because the
   prompt mandates procedural specificity. They therefore cite deep-in-the-
   abstract RESULTS values — exactly the part a 1,200-character excerpt cuts.

### The majority cause, fixed

`_SUPPORT_ABSTRACT_CHARS = 1200` was harmless when written: 57% of the
library's abstracts were themselves cut at 1,000 or 1,200 at ingest, so there
was nothing past the cap. `grounding-v1` healed those rows to a mean of 1,631
characters and left the cap in place — **turning a no-op into the last
truncation in the pipeline, sitting on the guardrail.**

- **36 of the 37** flagged pairs cite a paper whose stored abstract exceeds
  1,200 characters.
- PMID 27759881 is a 6,724-character Cochrane review whose LLLT finding sits
  ~5,000 characters in. The judge was shown its search strategy.

The judge now receives the **whole abstract**, with the payload bounded by
**batching on item boundaries** rather than by cutting — an item split across
two requests would be a claim judged against half its evidence, which is the
same bug with a new cause. This makes the checker **stricter**, not looser: it
can now see a contradiction in a conclusion it never reached.

**Re-measured: curriculum 13.3% → 13.0%.** Not the reversal the mechanism
predicted. Reported as measured.

### A second fail-open closed in the same function

`_SUPPORT_MAX_PAIRS = 30` caps how many pairs are checked *at all*. The two
curricula measured 29/30/30/30 — three of four modules **at the cap** — and
the rendered block said "each of the 30 cited claims was checked" while 15
were never looked at. True, and misleading. `total_pairs` is now recorded and
the block names the remainder ("8 further cited claim(s) were NOT checked").
Invariant 15 requires the answer to state its outcome.

### Does the grounding rule reach module writing?

Yes — `_GROUNDING_RULE` is spliced into `write_curriculum_module`'s prompt and
`tests/test_grounding_rule.py::test_curriculum_module` asserts it on the
system prompt actually sent. The brief made that check conditional on the
majority cause being genuinely-unsupported claims; it is not (18.9%), so the
condition did not fire, but the rule is there and is measured on the two laser
cases above.

---

## 5. Item 4 — narration/slide sync

13 narration segments against 34 deck sections kept auto-advance off. The
refusal was **right** and is untouched: `load_narration` arms only when the
sidecar's segment count equals the spec slide count, because advancing 34
slides on 13 unrelated boundaries would look like it worked while showing the
clinician the wrong slide for the sentence being spoken.

What was missing is a sidecar that *can* match. A lecture render is cut on the
narration script's own structure, and nothing derivable from it describes the
spec — `char_start` indexes the spoken script, not the answer. So the deck now
records its own narration against its own spec, one section per slide, with
`pack_chunks(..., merge=False)` giving every boundary a measured duration
rather than one interpolated by character share.

**Verified end to end against a real cached spec, with real OpenAI TTS and
ffprobe** (not the stubbed fixture the unit tests use):

```
spec 01e071f7…  21 slides   8,357 spoken characters
segments in sidecar : 21          slides in spec : 21
ffprobe duration    : 523.46s     sidecar        : 523.46s
speech rate         : 16.0 chars/s     cost: $0.2507
contiguity          : gapless, ends exactly with the audio
load_narration      : synced=True, 21 cues, sync_note ''
```

**Auto-advance is on.** Three ways this could have silently half-worked, each
with a test: a slide with no speaker notes would be dropped by
`synthesize_lecture` and take every later cue off by one (it falls back to its
title); a map whose count does not match is discarded rather than used; a TTS
failure returns "" and the export still builds.

`narrate` on `/generate_webdeck`: `auto` (default — reuse a matching render,
else record), `reuse` (the previous behaviour, free), `per_slide`, `off`.

**`auto` costs one TTS pass the deck export did not spend before** — roughly
$0.25 and ~2 minutes on a 21-slide deck. `DEMO_RUNBOOK.md` is updated.

---

## 6. Item 5 — the maintenance script

`scripts/monthly_maintenance.py`: provenance backfill for new write-backs →
rescore → one retrieval eval → a one-page report. **Dry run is the default and
it is not scheduled.**

The order is load-bearing and now has a test rather than a comment: the COI
penalty is applied at rescore *from* the `coi_status` the backfill writes, so
rescoring first scores the new rows against provenance they do not have yet.

The composer's only safety job is not to defeat the sub-scripts' own `--apply`
gates, so the tests capture each stage's argv rather than reading the source.
The eval stage is pinned `--cheap`: a maintenance run must never generate an
answer, both for the cost and because an eval answer must not be left where a
clinician could be served it.

`--since-days` was added to `scripts/backfill_pubmed_metadata.py` so a periodic
run examines the new arrivals instead of re-fetching all 2,350 rows. NULL
`added_at` falls out of the window: "we don't know when this arrived" is not
"it arrived recently". The default window is **35 days, not 30** — a monthly
job that slips a week must re-examine the days it already saw rather than skip
them.

**End-to-end dry run, all three stages, 2026-09-01 02:21:**

| stage | exit | wall | what it found |
|---|---|---|---|
| BACKFILL provenance for recent write-backs | 0 | 24s | 467 papers examined, 1 declared COI |
| RESCORE the library | 0 | 10s | 2,337 rescored, **2 scores changing** |
| EVAL retrieval, one pass | 0 | 686s | **25/25 cases passed**, 17 metrics off baseline |

The two changing scores are the demonstration that the order is right: they are
the two library rows the collapsed-abstract repair healed, and the real
abstract carries a sample size the affiliation block did not. Applied
afterwards (+8.1 and +11.1), backed up to `endo_papers_rag_score_backup`.

The 17 drifting metrics are a SINGLE run compared against three-run ranges —
search-term counts, hits/query and paper counts, in both directions, on
live-pinned cases. Every floor passed. The repair touched two library rows and
cannot move a paper count by four.

### A standing-rule violation found and fixed while using it

`rescore_library.py --apply` writes `score` **and** `sample_size` and took no
backup at all. Both are derivable, which is an argument for the backup being
cheap and not for skipping it: *derivable from what the row held at the time*
is the part that stops being true. It backs up now.

---

## 6b. Two defects the measurements themselves turned up

**An eval case's flag rate counted a pytest run's checks.**
`evidence_mapping.jsonl` is one file shared by every process on the machine,
and the harness computes a case's flag rate from a byte-offset window of it —
the same shape as `_esearch_hits_since` over `pubmed_audit.jsonl`. A `pytest`
run of `tests/test_end_to_end.py`, started while an eval was in flight, put
nine rows of `checked: 3, n_flagged: 0` inside one curriculum's window and
reported **16/146 = 11.0% for what was 16/119 = 13.4%**. Every number in this
report was reconciled against the raw log afterwards; that was the only
contaminated one, and it is corrected everywhere it appears.

Fixed twice, because either alone leaves a hole: `tests/conftest.py` redirects
both audit logs to a tmp path for the session (a test run must not append to
the record of what the product did — it had also been adding stubbed TTS rows
to `cost_log.jsonl`), and every support record carries its writer's `pid`, so
the harness EXCLUDES a foreign row rather than guessing. A timing heuristic was
written first and thrown away: the real burst was 1.3 s apart, which is also
what four curriculum modules finishing on a thread pool look like.

**A quoted claim could end in half a citation marker.** The support block
quotes a flagged claim at 140 characters, and a merged claim carries
`[[PMID:N]]` markers *inside* it, so the cut lands mid-marker. A curriculum
generated tonight rendered `... resolving by day 14 [[PMID:` and
`strip_markdown_for_speech` left that fragment in the narration script, where
TTS reads it out letter by letter — and it is a raw marker on a rendered
surface, which invariant 3 forbids. Fixed at the source (`_quote_claim`) and
defensively in narration; both patterns require the double bracket so prose
that says "a PMID marker" survives.

**It was found by an existing test**, `test_pmid_markers_are_never_spoken`,
whose fixture is the newest laser curriculum in `learn_history/`. It started
failing the moment this batch generated one with the shape. That is the
fixtures-from-real-data rule paying for itself.

---

## 7. Found, not fixed

| Severity | Finding |
|---|---|
| **HIGH** | **The grounding rule and the recommendation-traceability gate now pull in opposite directions, and every collision costs a full retry.** The Review prompt requires the CLINICAL RECOMMENDATION to carry a `[[PMID:N]]` on its load-bearing claim; the rule says do not attach one you cannot ground. When both apply the model leaves it unmarked, `validate_evidence_mapping` fails the answer `UNTRACEABLE_RECOMMENDATION`, and a whole answer is regenerated at ~$0.34. **6 of the 8 attempt-1 failures after the rule are that reason, against 0 of 2 before** (0/35 vs 6/89, Fisher p = 0.18 — directional, not proven). It is also the main reason a demo Review answer went from ~$0.79 to ~$1.28. It may be that the recommendation genuinely *should* always be traceable, in which case the retry is the system working and the cost is the price. That is a question to measure, not to guess, and it needs a before/after of its own. |
| **HIGH** | **The claim-unit artifact is 35% of Deep Learning flags and is untouched.** `_extract_claim_citation_pairs` has no rule for a curriculum's `IF / THEN / BECAUSE` decision tree or its Clinical Protocol Summary table, so a seven-branch tree becomes one claim carrying seven markers and produces seven flags. Fixing it means changing the claim splitter, and HANDOVER already records that the last change to that splitter *reversed* the expected direction (merged claims were flagged LESS, p=0.002). It needs its own batch and its own before/after. |
| **HIGH** | **`ingest_aae_guidelines.pubmed_fetch_abstracts` had never returned anything** — its entry separator was `^(\d{5,9})\.` while PubMed numbers entries `1. `, `2. `. Verified against a real dump: zero entries; every record it fetched was then dropped by `len(abstract) < 60`. Fixed, which means **that ingest path is live again — dry-run that script before running it.** |
| MEDIUM | **`_SUPPORT_MAX_PAIRS = 30` still caps coverage on every curriculum module.** The block now says how many were skipped, but 8 of 38 pairs on one module are still unchecked. Raising the cap costs Haiku calls, not much; nobody has measured what it would find. |
| MEDIUM | **The test suite was writing to the production cost log.** 90 rows totalling **$5.70 of imaginary spend** were added to `cost_log.jsonl` tonight by `tests/test_deck_narration_sync.py`, whose stubbed TTS still priced itself against the real table. `tests/conftest.py` now redirects both audit logs, but the existing rows are still in the file and `/admin/costs` will show them. Not rewritten: an append-only audit log should not be edited after the fact. **Tonight's real spend is $21.29, not the $26.99 the log totals.** |
| MEDIUM | 39 `abstract_cache` rows and 2 library rows still hold an affiliation block, because PubMed holds no abstract for those records at all. They are comments and letters; the alternative is a blank abstract, which silently skips the paper in the support check. |
| LOW | The `run_eval` flag-rate window is now pid-guarded, but `pubmed_audit.jsonl` and `cost_log.jsonl` remain shared mutable state that any process can write. The same class will come back through a different file. |
| LOW | 108 of the 112 unexplained efetch misses from `grounding-v1` are still unexplained. Not in tonight's brief. |
| LOW | 8 library rows still have an empty `title`. Not in tonight's brief. |

---

## 8. Decisions taken, with what was rejected

1. **The grounding rule went into all three synthesis prompts, including the
   case path, which no eval subset measures.** *Rejected:* changing only the
   two measured prompts to keep attribution tidy. Leaving one synthesis path
   with a known mechanism for a decorative citation, so a table reads more
   cleanly, is the worse trade. It is called out in the code and here.

2. **The grounding rule was KEPT after it made the curriculum path worse**
   (8.5% → 13.3%, p = 0.11). *Rejected:* reverting on the proxy metric.
   Telling the model that a marker asserts the paper says this is correct on
   its own terms, the movement is not significant, and there is a specific
   mechanism — a rule that pushes toward quotable specifics, judged against an
   excerpt that stops before the specifics — which Item 3 then tested.

3. **The support judge gets the whole abstract, bounded by batching.**
   *Rejected:* raising `_SUPPORT_ABSTRACT_CHARS` to a bigger number. That is
   the same decision the ingest sites made at 1,000 and then 1,200, and it was
   wrong both times: the Cochrane review in this very sample is 6,724
   characters. Caps belong where a payload has to be bounded, and a payload
   can be bounded by splitting instead.

4. **Item 2 kept the text dump and fixed the SELECTION.** *Rejected:*
   switching the live path to efetch XML, which is what HANDOVER's own lesson
   prescribes. The measurement says the text dump loses nothing here; the XML
   change would invalidate the recorded-fixture corpus that
   `fetch_and_save_fixtures.py` documents as deliberately text-mode "to match
   production exactly"; and it would rewrite the hottest path in the product
   to fix a failure that a five-line exclusion list closes completely.

5. **A record whose only long block is excluded keeps that block.**
   *Rejected:* returning "" and letting the row be blank. An empty abstract
   silently *skips* that paper in `verify_citation_support` — the guardrail
   would go quiet instead of complaining, which is this repo's bug class (d).

6. **The eval-window contamination was fixed with a pid on every record.**
   *Rejected:* a timing heuristic, which was written first and thrown away —
   the real burst was 1.3 s apart, which is also what four curriculum modules
   finishing on a thread pool look like. A guard that cannot tell those apart
   would either miss the contamination or cry wolf on every curriculum.

7. **All 37 Deep Learning flags were judged, not the 20 the brief asked for.**
   *Rejected:* sampling 20 of 37. The population is small enough to read
   whole, and judging all of it removes the question of whether the sample was
   representative.

8. **The deck's `narrate` default is `auto`, which spends TTS the export did
   not spend before.** *Rejected:* defaulting to `reuse` and leaving
   auto-advance off unless asked. The item's goal was to enable auto-advance;
   a flag that is off by default does not. `reuse` is still one request field
   away and the runbook records the timing change.

---

## 9. Baseline changes

- **No `eval/baseline_v6.json` metric moved**, because no retrieval-only run
  was re-baselined tonight. The three synthesis subsets are not part of that
  baseline.
- **The citation-support flag rate is now a harness metric**, printed per case
  and per run by `eval/run_eval.py`. It was previously read by hand out of
  console scrollback. `--live-subset` is new.
- **`4.3%` should stop being quoted as the Review baseline.** The same three
  cases measured 8.2% tonight with nothing changed. Quote a range or quote the
  run.

---

## 10. Verification

- **Full suite: 1,377 passed, 39 skipped**, exit 0 (from 1,269 at
  `grounding-v1`).
- **Every new test mutation-checked**: 33 mutations across the batch, all
  killed. Three were rejected and rewritten because the first version of the
  mutation did not kill anything — the anchoring test needed a competing
  block before it could see the difference, and a stale `.pyc` masked one
  restore (same-length mutation, same mtime second).
- **Item 4 verified against a real render**, not a stub: 21 segments == 21
  slides, ffprobe agreeing with the sidecar to 0.00s.
- **The abstract repair is idempotent**: a second dry run after the apply
  reports 0 rows would change.
- **The maintenance script ran end to end in dry run**, all three stages,
  25/25 eval cases passing.
- **The demo Review answers were re-warmed** against the healed library after
  the rescore invalidated the cache: five cold answers at 60.8-108.6s and
  $6.39, all five then served from cache at 0.5-1.0s. `DEMO_RUNBOOK.md` carries
  the new timings and the new ~$1.28 per-answer cost.
- **Every number in this report was reconciled against the raw
  `evidence_mapping.jsonl`** after the contamination in §6b was found. One
  figure was wrong (16/146 → 16/119) and is corrected everywhere it appears.

---

## 11. Cost

**$29.86** of real spend across 348 real API calls.

| what | calls | cost |
|---|---|---|
| Review synthesis, including 8 validation retries | 44 | $21.03 |
| curriculum modules, retries, stitching, syllabus | 53 | $7.73 |
| citation-support checks | 62 | $0.62 |
| deck narration, real TTS (Item 4 verification) | 1 | $0.25 |
| search terms, routing, everything else | 188 | $0.23 |

Beside the counts, as the rule requires: those calls produced **nine eval
passes** (three synthesis subsets, four live subsets, one 25-case retrieval
eval, one maintenance dry run) covering **1,175 claim–citation pairs checked**
across 26 Review answers and six curricula, plus the five demo answers
re-warmed at $6.39.

**$6.39 of the total is the demo re-warm, and $21.03 is Review synthesis** —
this batch's measurements were Review-heavy by design, because that is where
the metric lives.

`cost_log.jsonl` totals **$35.56** because 90 rows worth **$5.70** are stubbed
TTS from `tests/test_deck_narration_sync.py`, whose fake `_speak_openai` still
priced itself against the real table. `tests/conftest.py` now redirects the
cost log for the whole session; the existing rows were left in place rather
than editing an append-only audit log. See §7.

## 12. Decisions needed from RB

1. **Chase the claim-unit artifact?** It is 35% of Deep Learning flags — the
   largest remaining single cause anywhere in this metric. *Recommendation:
   yes, but as its own batch with its own before/after*, because the last
   change to that splitter reversed the expected direction and a confounded
   run would teach nothing.
2. **Is `narrate: auto` the right default for the web deck?** It buys
   auto-advance for ~$0.25 and ~2 minutes per export. *Recommendation: yes*,
   and the runbook now quotes the new timing.
3. **When should `monthly_maintenance.py` run?** It is built, tested and
   deliberately unscheduled. *Recommendation: after the demo*, in `--apply`
   mode, with the report read by hand the first time.
4. Still outstanding from `grounding-v1`: the "apexification" pronunciation
   needs a human ear.
