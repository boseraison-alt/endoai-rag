# A45 — retries are a cost driver, and one broken gate causes two thirds of them

Measured on **current code only** (rule 25): the 20 Review answers the A38d and
A42b probes generated today all ran on HEAD. `cost_log.jsonl` names retries
explicitly — `ask_clinical_question_retry`, `write_curriculum_module_retry` — so
the rate is a count, not an inference.

---

## A45a — the rate, and what a retry costs

| path | attempts | retries | rate | $ clean | $ retry | multiple |
|---|---|---|---|---|---|---|
| Review synthesis | 22 | 5 | **23%** | 1.472 | 1.542 | 2.05× |
| curriculum module | 8 | 6 | **75%** | 0.152 | 0.179 | 2.17× |

A retried Review answer pays **$1.472 for the attempt that is thrown away plus
$1.542 for the retry = $3.015** of synthesis, where a clean run pays $1.472.
Averaged across all runs at a 23% rate, that is **$0.35 per answer** of pure
waste.

The curriculum figure — **6 retries in 8 modules** — is on a small n but it is
three times the Review rate and worth its own look.

## A45b — attribution

| gate | retries | share |
|---|---|---|
| **UNCITED_AUTHOR_MENTION** | 2 | **67%** |
| UNATTRIBUTED_CLAIMS | 1 | 33% |

**One gate causes most retries.** Per A45b that is a prompt-or-logic problem,
not model variance. And the two examples name themselves:

```
UNCITED_AUTHOR_MENTION: 1 named author(s) with no [[PMID:N]] marker (MTA and Biodentine)
UNCITED_AUTHOR_MENTION: 1 named author(s) with no [[PMID:N]] marker (AAE and ESE)
```

Neither is an author.

## A45c — the gate's logic, measured before touching it (rule 17)

`_AUTHOR_MENTION_RE`'s second branch matches any *Capitalised* **and**
*Capitalised* pair. Endodontics is full of them. Across every stored answer,
curriculum and fixture:

**819 matches on that branch. About 30 are real author pairs. Precision 3.7%.**

The largest single false positive is **"RCTs and Systematic" at 156
occurrences** — from the tier label *"Level I — RCTs and Systematic Reviews"*,
which the product prints itself. Others: "MTA and Biodentine" (88),
"PIPS and SWEEPS" (52), "NaOCl and EDTA" (22), "AAE and ESE" (16),
"Photodiagnosis and Photodynamic" (13, a journal).

Capitalisation cannot separate those from "Byström and Sundqvist", and a
seven-word stopword list cannot hold a specialty's vocabulary.

### The fix is the logic, not the bar (rule 6)

It still takes exactly **one** uncited author to fail an answer. What changed is
what counts as one — two independent signals, either sufficient, ALL-CAPS
vetoing both:

1. **Both surnames are ones the library knows.** `endo_papers_rag.authors` holds
   thousands of real endodontic names. Diacritics are folded, because the library
   stores *Gostemeyer* and the answer writes *Göstemeyer* — that alone lost five
   real pairs in an earlier attempt.
2. **The sentence asserts something about them** — a possessive, or a reporting
   verb within three words. *"Fuss and Trope demonstrated"* is a citation whether
   or not the library holds a Fuss paper. This is the path that still catches a
   **hallucinated** author pair, which is the case that matters most.

Two entries came from measurement rather than imagination: **"Review"** added to
the stopwords (the only non-author the union kept, 2 of 64), and **`published`
removed** from the reporting verbs — a journal publishes, an author reports.

### Result on the same corpus

| | before | after |
|---|---|---|
| `and`-branch matches kept | 819 | **62** |
| of those, real author pairs | ~30 (3.7%) | **62 (100%)** |
| real pairs lost | — | none that either signal can see |

The `et al.` branch is untouched. It was never wrong.

## A45d — what this does to A42b's $0.30–$1.08

A42b bounded the floor's saving at $0.30–$1.08 because "the two biggest savings
are on runs that look retry-inflated." Checked against the transcripts:

```
$3.52 run (A38d OLD)   — retried: YES
$3.98 run (A42b 0.55)  — retried: YES
$3.74 run (A42b 0.55)  — retried: YES
```

**All three confirmed.** So the $1.08 was roughly $0.30 of floor plus $0.78 of
retry variance — and the retry variance is not noise to be averaged away, it is
this defect. Removing 67% of retries removes most of that $0.78 from *both*
arms, which is why the two numbers have to be read together (rule 12).

Expected effect, stated as a prediction rather than a claim: the retry rate
should fall from 23% toward ~8% (the UNATTRIBUTED_CLAIMS share alone), taking
~$0.23 per answer of waste with it. **Not yet measured** — it needs a fresh
paired run, and A46's discipline says predict first, then measure.

## Scope

n is small: 22 Review syntheses and 8 curriculum modules, all from one day's
probes. The corpus measurement behind the gate fix is large (819 matches across
every stored document) and does not depend on n. The **rate** does.
