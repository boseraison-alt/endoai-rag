# Overnight Report 7 — `dl-quality-v1`

Truncated modules, unchecked claims, and two citations adjudicated against
their own abstracts. Autonomous batch on `main`, 2026-09-01/02. Standing rules
from `WORKLIST.md` §0/§6 in full.

**The fixtures**, both rescued from `answers/` — which is gitignored, so each
existed as a single untracked file on one machine — and committed under
`eval/fixtures/curricula/`:

| | generated | question |
|---|---|---|
| `laser_disinfection_20260901_before.txt` | 13:58, on `guardrails-v1` | Use of lasers in root canal disinfection |
| `anesthesia_20260901_before.txt` | 20:36, on `f23e8c8` (`git_dirty`) | anesthesia for endodontics, different techniques… |

---

## 1. Per item

| Item | Status | Before → After | Test file | Commit |
|---|---|---|---|---|
| 1 · Truncation gate | see §2 | modules ending cut: **2 visible / 4 actual → 0** | `tests/test_module_truncation.py` (26) | |
| 2 · Remove the 30-claim cap | see §4 | unchecked claims **13 → 0** on each fixture | | |
| 3 · The Sabeti claim | DONE | adjudicated — **cut, not re-sourced** | `eval/logs/citation_adjudications.md` | `71af84b` |
| 4 · Cross-module consistency | | | | |
| 5 · Regenerate and re-measure | | | | |

---

## 2. Item 1 — the cap was the median

**Diagnosed from the cost log, not from the two visible symptoms.** The item
named two truncations: Module 4 ending "…irrigant extrusion when tips are not",
and Module 1's materials table ending mid-cell at "Wavelength 630". Both
reproduce. But the token counts say the problem is not two modules:

| | |
|---|---|
| `write_curriculum_module` calls ever logged | **190** |
| of those, stopped at exactly `max_tokens` | **164 = 86%** |
| median output length across the feature's whole history | **3,200 — the cap itself** |
| the laser run: all four modules **and both retries** | 3200 / 3200 / 3200 / 3200 / 3200 / 3200 |

Every module of that curriculum was cut. Two of them were cut somewhere a
reader can see.

**`stop_reason` appeared exactly once in `endo_ai.py`, inside a comment.**
Nothing read it. The API had been reporting the truncation on every call, in a
field the code mentions only in prose — bug class (d) in the output a clinician
reads end to end.

### Why a text detector exists alongside `stop_reason`

The stitcher is an LLM pass instructed to reproduce module bodies verbatim, and
it does not reproduce a truncation faithfully. Module 1's severed table row
reached the final document as

```
| **Laser — Diode (aPDT)** | Wavelength 630 |
```

— with a closing pipe its author never wrote. A structural check running after
the stitch would call that row well-formed. So the gate runs on module text
*before* stitching, and `detect_module_truncation` has to work from text alone.

**And the stitcher had already noticed.** In the anesthesia curriculum it
declined to reproduce two cut modules at all and wrote

> **[module body ends here as supplied]**

twice. That string appears **nowhere in this codebase**. The system detected
the truncation, told the reader in plain English, and nothing downstream parsed
it — a second signal, discarded like the first.

### The detector, and the direction that costs more

A false positive replaces a real module with a "not generated" notice, which is
worse than the truncation it prevents. So every rule fires only on something a
finished module cannot contain: an unclosed `[[PMID` marker, a table row with
fewer cells than its own header, or a paragraph whose last word is a
conjunction, article, preposition or auxiliary.

Measured over every stored curriculum:

| | |
|---|---|
| module bodies scanned | **100** |
| flagged | **5** |
| false positives | **0** |
| where the 5 sit | **all Module 4** |

All five verified by hand: three end at `[[PMID:` or `[[`, two end on "with"
and "not". The Module-4 concentration is itself the finding — modules 1–3 are
followed by the stitcher's transition paragraph, which papers over the cut in
the *rendered* document. Only the last module's damage is visible to a reader.

### The three changes

1. **`CURRICULUM_MODULE_MAX_TOKENS = 6000`**, from 3200, shared by the first
   call and the validation retry. This is not the fix, and the constant's
   comment says so: a cap can always be reached, so raising it only makes the
   gate fire rarely instead of always.
2. **Regenerate once**, on either signal — `stop_reason == "max_tokens"` or the
   text detector. A regeneration, not a continuation: asking a model to carry
   on from a severed sentence produces two halves written under different
   remaining budgets, and the join is exactly where a numeric protocol loses
   its citation.
3. **The assembly gate.** If the text is still cut, the module is withheld and
   `_module_truncated_block` is rendered instead — deliberately *different*
   wording from the evidence-less notice, because saying the literature was
   thin when the truth is that we ran out of tokens is a lie in the direction
   that makes us look better.

### Found, not fixed — the modules were never 650 words

`CURRICULUM_WORDS_PER_MODULE = 650`. Measured on the laser fixture: **1,497 /
1,489 / 1,548 / 939** words, the last being the truncated one. The target has
been fiction for the life of the feature, and raising the cap does not make it
true — it lets the overrun complete. Changing the target changes the
curriculum's length contract and belongs in its own measured work.

---

## 3. Item 3 — the Sabeti claim, and what it invented

Full adjudication in `eval/logs/citation_adjudications.md`. The claim, under a
heading the module had already titled **Adverse Effects**:

> Sabeti et al. confirmed that the overall adverse event profile of LAI met
> noninferiority criteria versus UAI [[PMID:40818665]].

Three checks, because they fail separately:

| | |
|---|---|
| author attribution | **CORRECT** — Sabeti M is first author |
| "noninferiority criteria" | **ABSENT**, and not fairly implied — it is a random-effects *superiority* meta-analysis reported as an SMD. No margin, no equivalence test, the word appears nowhere |
| "overall adverse event profile" | **ABSENT** — the outcome is postoperative pain on a VAS; adverse events are not an outcome of the review at all |

The direction is wrong in a telling way: the paper does not report that LAI
fails to be worse, it reports that LAI is **better** — SMD −0.58; 95% CI −0.94
to −0.22; P = .0016.

**The adverse-event sentence has no source and is cut, not re-sourced.** The
module needed an adverse-events statement for a section it had already titled,
had no paper reporting adverse events, and manufactured one by reframing a
superiority result as a safety result. Re-pointing the marker at another paper
would clear the checker and keep the invention.

**The guardrail worked.** `verify_citation_support` flagged this claim on the
run that produced it. What failed is that a flagged claim still shipped inside
the curriculum with the flag rendered as an advisory footnote.

### The other citation: PMID 27759881 stands

Challenged on the grounds that it is *described elsewhere as the LLLT
post-surgical Cochrane*. It is — and it is also the CBCT one. PMID 27759881 is
a twenty-RCT Cochrane review (Del Fabbro et al. 2016) whose abstract covers
both arms, and it says in as many words:

> There was no evidence that using CBCT rather than radiography for
> preoperative evaluation was advantageous for healing (RR 1.02, 95% CI 0.70 to
> 1.47; one RCT, 39 participants; very low quality evidence)

Not misattributed. One paper, two sub-analyses, two names. The follow-through
is that the claim should carry the RR, the n and the quality grading, which the
source supplies and the curriculum dropped.

---

## 4. Item 2 — what the 30-pair cap was hiding

Measured from the fixtures' own rendered footers:

| curriculum | checked | total | **unchecked** |
|---|---|---|---|
| anesthesia | 117 | 130 | **13** |
| laser | 120 | 133 | **13** |

The cap binds on three of four modules in both. The block is honest about it —
"4 further cited claim(s) were NOT checked (the check covers the first 30)" —
which is invariant 15 doing its job, and is also the reason this was findable.

---

*(Items 4 and 5, and the final numbers for Items 1 and 2, follow.)*
