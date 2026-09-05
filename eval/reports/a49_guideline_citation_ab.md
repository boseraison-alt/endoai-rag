# Item 3 — why guidelines were retrieved and never cited

**Date:** 2026-09-05 · **Verdict: one line in the prompt. A/B PASSED 5 of 5.**
**Replay:** `python scripts/ab_guideline_prompt.py --json eval/reports/a49_guideline_citation_ab.json`

---

## 3a — the measurement, and the answer

The batch asked four questions. Three have unremarkable answers; the second
is the whole finding.

**Where does the guideline block land, and how is it labelled?**
Position **9 of 12** in `TIER_ORDER` — after `invitro`, before `level5` —
labelled `Specialty Guidelines & Position Statements (consensus, not a study)`.
It renders through `_build_evidence_context` like every other tier. Nothing
wrong here.

**Does the block carry enough to cite?**
Yes. `format_paper_context_line` emits PMID, authors, year, citations,
`NOT SCORED — a guideline is a specialty's stated position…` plus
`(org, status, jurisdiction)` and, since item 4 of the previous batch, the
supersession notice. Title and abstract follow it. A guideline reaching the
prompt is fully citable. Nothing wrong here either.

**Could "NOT SCORED" read as "do not use"?**
Possible, but it is not the binding constraint — see the A/B, where the same
"NOT SCORED" text was present in both arms and citations still rose.

**What does the prompt say about guidelines?** — **NOTHING. That is the answer.**

The synthesis prompt enumerates the tier ladder **twice**:

```
Synthesise the evidence in tier order: Cochrane -> Level I -> Level II ->
Level IIIa -> Level IIIb -> Level IV -> Level V.
```

and again as the literal set of headings the answer must be written under:

```
**Cochrane Reviews**
**Level I — RCTs and Systematic Reviews**
...
**Level V — Expert Opinion**
```

**Neither list mentions guidelines.** The model is handed a guideline block, an
instruction to write under named headings, and an instruction to *"skip levels
with no relevant evidence"* — and there is no heading a guideline can go under.

**This is the same defect class as `app.py`'s hardcoded lane list**: an
enumeration of the tiers that drifted behind retrieval. The retrieval was fixed
to reach guidelines; the prompt's own list of what to write about was never
updated. `observational`, `classic` and `invitro` are missing from that heading
list too — see FOUND NOT FIXED.

## 3b — the A/B

Retrieval ran **once** per question and the **same evidence object** was
deep-copied to both arms, so the prompt is the only variable. Two separate runs
would have moved retrieval as well, and PubMed is not deterministic between
them. The two system prompts were captured and verified to differ before
anything was spent — a flag that silently failed to toggle would have produced
a perfectly clean null result.

| case | guidelines retrieved | control | treated | delta |
|---|---|---|---|---|
| retreatment-vs-microsurgery | 1 | 1 | 1 | +0 |
| cracked-tooth-prognosis | 2 | 0 | 2 | **+2** |
| bisphosphonates | 2 | 2 | 2 | +0 |
| pregnancy | 2 | 1 | 1 | +0 |
| intentional-replantation | 2 | 1 | 2 | **+1** |

| | control | treated |
|---|---|---|
| guideline citations | 5 | **8** |
| total citations | 49 | 56 |
| answers carrying the guidelines heading | 3 | **5** |
| cost | $4.29 | $4.49 |
| mean citations per question | 9.8 | 11.2 |

**Pre-declared: ≥1 guideline citation per question on 3 of 5. Result: 5 of 5.
PASS.**

Total citations also rose (49 → 56) and cost rose 4.7%. Nothing was displaced —
guidelines were added to answers rather than substituted for trials.

### The change, and why it is worded the way it is

The batch was explicit: *do not instruct the model to cite guidelines; instruct
it on what they are.* A model told "cite guidelines" cites them irrelevantly.

The block tells it that a guideline is **a different axis, not a rung**: not a
study, carrying no score, so the tier hierarchy does not apply to it and it is
not "weak evidence" — it is what a professional body has formally stated, which
tells the clinician what the standard of care currently is in that
jurisdiction. And it names **divergence** as a first-class finding: guidelines
lag the literature by years by construction, so *"the AAE position (2021) says
X; the 2026 trial evidence says Y"* is information the clinician needs, not a
contradiction to resolve away. That is A49's "where the specialty stands".

It ships behind `GUIDELINE_PROMPT_ENABLED`, `True` in production, so the A/B is
reproducible.

---

## A correction to my own earlier number

Yesterday's report said **1 guideline citation across five live Review
questions**. That counted only PMIDs matching the manifest's 27 **confirmed**
accessions. Counting tier membership as well — a live-fetched guideline banded
to the `guideline` tier is a guideline whether or not it is in the manifest —
the control arm here shows **5 across five questions**.

**The baseline was better than I reported. The improvement is 5 → 8, not
1 → 8.** The qualitative finding is unchanged and the A/B is unaffected, since
both arms were counted the same way.

---

## FOUND, NOT FIXED

- **Three more lanes are missing from the same heading list.**
  `observational`, `classic` and `invitro` have no heading either, and the
  observational lane populates 18 of 29 questions. Only the guideline lane was
  changed, deliberately: one variable, so the A/B attributes cleanly (rule 22).
  **The same one-line fix almost certainly applies to all three, and it is now
  a known, measured gap rather than a suspicion.**
- **31 of 56 citeable guideline rows carry a slug id, not a PMID**, and the
  prompt requires `[[PMID:nnnnnnn]]`. Those rows **cannot be cited in the
  required format at all** on the library route. Live-fetched guidelines have
  real PMIDs, which is why the live-subset A/B was clean — the constraint is
  invisible there. **This is a second, independent mechanism and it is bigger
  than the prompt one on the route that answers most warm questions.** It needs
  an id scheme decision, not a prompt change.
