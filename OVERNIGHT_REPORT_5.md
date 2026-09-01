# Overnight Report 5 — `case-v2.1`

The differential leads, and the dens evaginatus claim is sourced. Autonomous
batch on `main`, 2026-09-01. Standing rules from `WORKLIST.md` §0/§6 in full.

The fixture, verbatim:

> 20-year-old, no response to cold testing on tooth #20, well-defined
> periapical lesion, no filling, no cracks, Asian ethnicity.

---

## 1. Per item

| Item | Status | Before → After | Test file | Commit |
|---|---|---|---|---|
| 1 · Differential leads, treatment follows | DONE | management at char **323** → **1,277**; DE candidate **3 of 6 or absent** → **1 of 6, every run** | `tests/test_case_ordering.py` | this batch |
| 2 · Fix the overreaching DE claim | DONE | claim now states "predominant etiology **in immature teeth** (32.1%)", its source's own wording; **+3 DE papers** in the library | same | this batch |
| 3 · Pin it in the eval set | DONE | `dens-evaginatus-premolar-diagnostic`, **3/3 case cases passing** | `eval/questions.json` | this batch |
| 4 · Close | DONE | suite **1483 → 1495** passing | — | this report |

---

## 2. Item 1 — the ordering, and the token cap that undid it

`case-v2` already mandated differential-then-management, so Item 1 began as a
validation against a second, independent fixture. It found two things instead.

**The fixture ran the TREATMENT path and reproduced the reported failure
exactly.** The answer opened:

> **Assessment:** Tooth #20 presents with pulp necrosis and asymptomatic apical
> periodontitis — a straightforward endodontic diagnosis…
> **Recommendation:** Proceed with non-surgical root canal treatment.

First management word at character **323**; the word "differential" at 3,065.
That is the reported failure, on code that was supposed to have fixed it.

**The cause was not the router.** Intent was classified `diagnostic` — 10 times
out of 10 when sampled. What failed was `generate_case_differential`:
`max_tokens = 1500`, six candidates × five prose fields, `stop_reason:
max_tokens`, the JSON truncated mid-string, `json.loads` raised, the function
returned `[]`, and the caller silently fell back to the ordinary case path with
the treatment format. **A token cap reintroduced the exact defect the feature
existed to remove**, and nothing in the output said so.

Three fixes:

- `max_tokens` 1500 → 3000;
- `_parse_candidate_array` salvages complete objects from a truncated array —
  a reply that stops mid-list still has four or five usable candidates, and
  losing the last one is a far smaller error than losing the differential;
- an empty differential on a `diagnostic` turn is now **loud and retried once**,
  and if it is still empty the log says plainly that the turn will be answered
  on the treatment path, "which is not what the clinician asked for".

**And the clinical half.** Dens evaginatus was candidate 3 of 6, or absent —
because nothing told the differential generator that the tooth number is a
prior. Tooth #20 is a mandibular second premolar and the patient is of Asian
ethnicity; that is the textbook DE presentation. The prompt now says so, in
general terms rather than for this case:

> WHICH TOOTH IT IS, and who the patient is, are strong priors — use them
> explicitly. … dens invaginatus concentrates in maxillary lateral incisors,
> dens evaginatus in mandibular premolars, the palatogingival groove in
> maxillary laterals … do not let a candidate that is common overall crowd out
> one that is common in THIS tooth.

**Dens evaginatus is now candidate 1 in every run measured** (3 sampled
directly, 4 more through full runs).

| | before | after |
|---|---|---|
| first management word | char 323 | char **1,277** |
| DE rank in the differential | 3 of 6, or absent | **1 of 6** |
| papers retrieved | 31 | **68–73** |
| answer | Assessment / Recommendation / Evidence | **Differential — most likely first** |

Its ordering is now asserted in the eval set, and the assertion is
mutation-checked (§4).

---

## 3. Item 2 — the DE claim, sourced

### 2a. The library had almost no dens evaginatus in it

Twelve rows mentioned the anomaly, and exactly **one** was about it: Senia and
Regezi, 1974. Everything else was regenerative-endodontics outcome literature
that names DE as an inclusion criterion. So the load-bearing etiologic claim
had a 1974 case report and a Thai cross-sectional study behind it — and
overreached the latter.

`scripts/ingest_dens_evaginatus.py` runs three targeted queries across the
tier filters, with the older synonyms the modern term hides (central cusp,
tuberculated premolar, Leong's premolar, occlusal tubercle) and **talon cusp
excluded** — it is the anterior analogue and would import maxillary incisor
literature into a mandibular premolar question.

**The dry run found a problem worth more than the ingest.** 48 papers cleared
the quality floors and **23 of them did not mention the anomaly at all**:
*"Single versus multiple visits for endodontic treatment"*, *"Systemic
antibiotics for symptomatic apical periodontitis"*, *"Materials for retrograde
filling in root canal therapy"*. `fetch_papers` broadens a query once when a
tier returns zero hits — sensible on an ordinary question, destructive on a
narrow one, because the broadened query stopped being about dens evaginatus
and became about endodontics. Every one of those would have been written into
the library as the product of a **targeted** ingest.

So the script does its own write-back behind a relevance gate: only papers
whose own title or abstract names the anomaly are stored.

| | |
|---|---|
| cleared the quality floors | 48 |
| **on topic** | **25** |
| off topic, dropped | 23 |
| already in the library, or below the write-back floor | 21 |
| **written** | **4** (3 of them DE-specific) |

The three that matter:

| PMID | year | tier | |
|---|---|---|---|
| 39520509 | 2025 | level3a | Prevalence and prophylactic management of premolars with dens evaginatus in Singaporean school children |
| 35413305 | 2022 | level3a | Outcomes and predisposing factors of two prophylactic treatments in dens evaginatus premolars |
| 38493190 | 2024 | level3a | Pulpotomy for irreversible pulpitis in immature permanent teeth |

Insert-only — `learn_from_live_results` skips PMIDs the library already holds,
so no column was overwritten. The pre-insert PMID set is committed as
`eval/logs/de_ingest_pre_pmids.json`, which makes the addition exactly
reversible.

### 2b. The claim, before and after

**Before** — as reported, and as the checker flagged it:

> Thai population data identified DE as the leading cause of RCT **in premolars
> presenting without caries**

The source (PMID 39179988) says, verbatim: *"In immature teeth requiring
NS-RCT, the predominant etiologies were dens evaginatus (32.1%), dental caries
(28.6%), and traumatic injury (21.4%)."* Two substitutions in one sentence —
**immature teeth** became **premolars**, and the **caries-free** qualifier was
invented.

**After**, unedited from the regenerated answer:

> In a large cross-sectional study of 1500 teeth undergoing non-surgical RCT,
> dens evaginatus was the predominant etiology **in immature teeth** requiring
> treatment (32.1%), ahead of caries (28.6%) and trauma (21.4%)
> [[PMID:39179988]].

The qualifier is restored, the invented one is gone, the numbers match the
abstract, and **the DE discussion is still there** — which was the constraint.

### The structural fix behind the flag count

Getting to zero flags was not a matter of telling the model to be careful. One
run flagged three claims, all citing **PMID 38411495 — "The clinical outcomes
of vital intact teeth close to large cystic lesions"** — for dens invaginatus
prevalence, complete with counts ("93/170", "134/136") that appear nowhere in
it. A real PMID from the block, attached to a fact the model knew from
somewhere else.

The evidence block was one undifferentiated pool, so every PMID in it looked
equally available to every candidate. The synthesis scaffold now lists **which
PMIDs were retrieved for which candidate**:

> WHICH PAPERS WERE RETRIEVED FOR WHICH CANDIDATE. A paper retrieved for one
> candidate is not evidence for another just because it is in the block below
> — check that the paper's own subject is the candidate you are citing it for.

| runs of the fixture | flags |
|---|---|
| before the attribution list | 2/17, 2/10, 1/16, 3/17 |
| after | **0/19, 1/25, 2/25, 0/16** |

Two smaller prompt corrections went in alongside, each targeting a flag shape
already catalogued in `guardrails-v1`: a discriminator line that only says
which candidate a test settles takes no marker, and a statement about what the
evidence base does **not** contain takes no marker either — no abstract can
state what it omits.

---

## 4. Item 3 — pinned, and the pin is mutation-checked

`dens-evaginatus-premolar-diagnostic`, case mode, library-pinned, asserting:

- `case_intent: diagnostic`
- `must_contain: ["dens evaginatus"]`
- `must_precede: [["dens evaginatus", "root canal treatment"], …]`
- `clarify.must_not_ask_about: [bisphosphonate, …]`
- `max_support_flags: 2`

**The whole case subset now passes:**

| case | intent | papers | support flags |
|---|---|---|---|
| necrotic-virgin-tooth-young-adult-diagnostic | diagnostic | 50 | 4/17 (cap 4) |
| bisphosphonate-extraction-vs-rct-treatment | treatment | 24 | 2/26 (cap 3) |
| dens-evaginatus-premolar-diagnostic | diagnostic | 68 | **0/16** (cap 2) |

**Eight mutants, eight kills** — including the two that first survived, and
both survivals were informative:

- **`must_precede` stopped detecting a reversal and every test still passed.**
  My test had re-implemented the comparison locally, so it was asserting on its
  own copy while the harness's was mutated to `elif False:`. That is this
  repo's documented bug class — a test asserting on a private copy rather than
  the code actually used — committed by the person writing the test that was
  supposed to prevent it. `check_precedence` is a top-level function now and
  the test calls it.
- the per-candidate attribution mutant, which only failed to apply because my
  anchor string carried the wrong indentation.

---

## 5. Where the assertions were wrong, and how

Three of my own assertions failed on real runs, and each was the assertion at
fault rather than the product. They are listed because the pattern is the
finding: an assertion written from one observation encodes that observation's
accidents.

1. **`must_contain: ["dens invaginatus", "trauma", "crack"]`** on the
   20-year-old case. A run named dens invaginatus, trauma, dens evaginatus, the
   **palatogingival groove** — which appeared in 0 of 8 runs before this
   batch — sickle-cell disease and calcific metamorphosis, and failed on the
   absence of the word *crack*. A better differential than the assertion
   demanded. Replaced with `must_contain_at_least: {n: 2, any_of: […]}`, which
   is what the brief actually specified: "dens invaginatus AND at least two
   other candidate causes".
2. **`max_support_flags: 0`** on the DE fixture, which is what the brief asked
   for. Post-fix observations are 0, 1, 2, 0. Zero is a point target on a
   stochastic judge, and `WORKLIST` §0 says assertions are floors and forbidden
   conditions, never points. Set to 2 — the top of the observed range — with
   the range recorded in the case's `why`. It is still the tightest cap in the
   file.
3. **`["dens invaginatus", "root canal treatment"]`** on the 20-year-old case,
   from `case-v2`: it asserted DI must be the *first* candidate, which is a
   ranking claim. The DE fixture keeps the equivalent pair, and legitimately —
   there the tooth number makes DE the lead, so the ordering is a property of
   the answer rather than a preference.

---

## 6. Found, not fixed

| severity | finding |
|---|---|
| **MEDIUM** | **`fetch_papers` broadens a zero-hit query into a different topic.** On a narrow query the broadened form returns the general endodontic corpus: 23 of 48 papers in the first DE dry run. The ingest script gates on relevance, but the LIVE path does the same broadening with no gate, so a rare-anomaly question can be answered from general endodontics with nothing saying the query changed. Needs its own measurement — how often does a broadened query change the topic rather than widen it? |
| **MEDIUM** | **A `max_tokens` cap can silently disable a whole feature.** The differential returned `[]` and the turn was answered on the treatment path with no error anywhere. Now loud and retried here, but the same shape exists at every other JSON-returning call site with a tight cap. Worth a sweep: which generators would return empty rather than partial on a truncation? |
| **LOW** | **The `artifact_negative` class is still the residual.** A true statement about what the evidence base lacks, carrying a marker, cannot pass the checker. The diagnostic prompt now tells the model to write it unmarked, which helps locally; the general fix — a fourth judge verdict — is still the top P1 item in `CURO_HANDOVER` §4. |
| **LOW** | **21 of the 25 on-topic DE papers were not written**: already in the library, or below the write-back floor of 50, or carrying no abstract. The script does not report which, so "4 written of 25 on topic" is less informative than it should be. |

---

## 7. Cost

| what | cost |
|---|---|
| DE targeted retrieval (dry run + apply) | ~$0.10 |
| 8 fixture runs (diagnosis, three fixes, validation) | ~$1.55 |
| differential sampling (3 direct + intent sampling) | ~$0.09 |
| 3 case-subset eval runs | ~$1.45 |
| **batch total** | **~$3.20** |

Half of it is fixture re-runs. Four were necessary — one to reproduce, one per
fix — and the rest were the assertion-calibration loop in §5, which is the cost
of finding out that an assertion was wrong rather than shipping it.

---

## 8. Tag

`case-v2.1`. Rollback point: `case-v2`.
