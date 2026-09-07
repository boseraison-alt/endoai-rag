# A55 — predictions, committed before any measurement or code

## A premise of the item, checked first

Item 2 asks to "change the coverage decision to: LIBRARY only when **every**
concept group clears `min_concept_papers`". **That half is already shipped.**
`app.py` computes `weakest_cov = min(c["hits"] for c in coverage)` and requires
`weakest_cov >= MIN_CONCEPT_PAPERS`, which is exactly "every group clears it".

A54's own numbers confirm the gate behaved as written: 149 hits for the material
concept, 24 for the surgery concept, `min_concept_papers = 3`, weakest = 24,
pass. The gate was not failing to read its weakest concept. It was reading a
number that cannot answer the question being asked of it.

So item 2's real content is the **intersection** — and that is the part with no
existing implementation and no pre-declared threshold. Stated here so the report
does not later claim credit for shipping something that was already there.

## Item 1

1. **The intersection is below 10 on at least a third of LIBRARY-routed
   questions.** This is the item's own prediction and I expect it to hold. I
   add a sharper one: **the intersection will be below 10 on the majority, not
   a third**, because a three-group query asks for the conjunction of three
   independent concepts and a 3,449-row library is small for that. The
   per-group counts will look healthy on the same questions.
2. **Every LIBRARY-routed question with a thin intersection is missing live
   papers.** The item predicts this. I predict the converse is NOT clean —
   some questions with a *healthy* intersection will also be missing live
   papers, because the live path fetches from a corpus four orders of magnitude
   larger. If that holds, the intersection separates the *worst* cases but is
   not a sufficient condition, and the report must say so rather than
   presenting it as a clean discriminator.
3. **Route split**: of the 31 questions, I predict **more than half route
   LIBRARY**. Write-back means every question asked before is in the library.

## Item 2

4. **The chosen `min_intersection_papers` will not achieve zero errors in both
   directions.** I predict at least one question is missing live papers at a
   healthy intersection, or one with a thin intersection is not missing any. If
   no single value separates the two classes cleanly, I report the error counts
   at the best value and say the threshold is a trade, not a discriminator.
5. **Re-route cost.** The live path is the expensive one. I predict the
   re-routed set costs **$0.02–$0.10 and 20–60 s per question**, from the live
   path's own logs.

## Item 3

6. **F1–F8 tier prediction, committed before the write.** The eight are
   head-to-head clinical comparisons of MTA versus bioceramic root-end
   fillings. I predict the pubtype guard lands them as: **2–4 at `level1`**
   (those NLM tags RCT or meta-analysis), **2–4 at `level3a`** (comparative or
   observational studies), and **0 at `invitro`** — if any lands `invitro` the
   fixture set was mis-verified in A54, which would be a finding about A54, not
   about this ingest. Exact per-PMID predictions are in the item 3 section of
   the report before the write runs.

## Item 4

7. **Below 90% unchanged groups**, so by rule 38 this is a retrieval change and
   needs the full A/B. A prompt sentence that adds procedure synonyms changes
   the surgery group by construction on every question that names a procedure,
   and roughly a third of the 29 do.
8. **The A54 question's surgery group will carry ≥3 of the eight synonyms**
   after the change and **fewer than 2** before it.

## Item 5

9. **The renderer will change what the reader sees on more than the A54
   question.** A54 showed three guidelines and the model listed two; I predict
   the model omits at least one admitted guideline on **2 or more** of the 31
   questions today, so this is a general defect rather than one bad answer.

## Standing note on measurement

Item C measured the same-build pool-noise floor at **26%**. Any A/B in this item
that compares pool membership must clear that floor before claiming an effect.
Item 4's A/B compares **query strings**, where the floor is now zero, and that
is the only reason it can be run at all.
