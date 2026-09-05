# A46a — what the v6 re-baseline should show, written before it runs

**Committed before the baseline. Anything that moves and is not predicted here
is the signal — that is the whole point, and it is the only way a re-baseline
is a test rather than a rubber stamp.**

**Written:** 2026-09-05, at tag `retrieval-freeze-20260905`, HEAD of
`fix/retrieval-blindspot`. **The baseline has NOT been run.** It is 3.5 h and
is the next batch on its own.

> **AMENDED 2026-09-05, re-tagged `retrieval-freeze-20260905b`.** Five citeable
> guideline rows had their fabricated or mis-scaled scores nulled
> (`AAE-PS-diagnosis` 90.0, `AAE-PS-vital-pulp` 90.0, `ESE-PS-VPT-2019` 87.0,
> `ESE-QG-2006` 50.4, `39578680` 59.3) and `ESE-PS-VPT-2019` was quarantined as
> `duplicate_of:30664240`, so the citeable corpus is one row smaller.
> **Nothing in the predictions below depends on guideline ordering**, and every
> prediction stands unchanged: the guideline tier's cap is 4–6 and selection
> within it is by relevance, not score, so nulling a score changes which
> guideline is listed first and not which are retrieved. The one place it could
> show is a **guideline citation count moving by ±1** on a question where the
> model previously followed the 90.0 as an authority signal — which is the
> defect being removed, and would be a welcome rather than a surprising result.

Reference point: `baseline_v6.json`, recorded **2026-08-31**, 25 cases × 3 runs,
retrieval-only. Everything below is measured against it and against the changes
since `8da8823`.

---

## 0. Read this before comparing anything

`baseline_v6.json` is **retrieval-only** — it records papers, esearch hits,
queries, terms and `per_tier`. It carries **no citation counts and no cost**.
Half of what the ORDER asks me to predict (mean citations, provisional
citations, guideline citations, cost) therefore cannot be compared against it
at all; those need a synthesis run. **Predictions are split accordingly**, and
a comparison that silently mixes the two harnesses will produce nonsense.

The eval set is **29 cases**; the baseline has **25**. Four cases postdate it.

---

## 1. What changed since `8da8823`, and which metric each moves

| change | effect on a RETRIEVAL run | effect on a SYNTHESIS run |
|---|---|---|
| live path showed 26% of retrieved evidence → **100%** | none (papers were always counted) | **large: citations UP** |
| per-tier cap moved onto the deduped list | **level1 papers DOWN** (73 → 18 on the measured case) | citations flat-to-up |
| provisional lane on **all** paths | small **papers UP**; new `provisional` key | **provisional citations 0 → nonzero** |
| guideline lane on **all** paths | **papers UP**; `guideline` key on live/case | **guideline citations 0 → nonzero** |
| observational lane reaches Review/Case | **papers UP**; new `observational` key on live | modest citations up |
| conflict gate | none | answer text only |
| IF removed | none | none |
| 12 records quarantined + 5 withdrawn/draft | **papers DOWN slightly** | citations down slightly |
| 60 guidelines ingested | **papers UP** on guideline-adjacent questions | guideline citations UP |
| **library floor — NOT SHIPPED (item 1)** | **none** | **none** |
| **PRISMA unified on relevance (item 2)** | **none** | **a different review is named on ~27 of 29** |
| **title/abstract on live scored dicts (item 2)** | none | **Case differential prompt changes — see §4** |
| supersession notice (item 4) | none | one line on ~13 guideline records |

---

## 2. Retrieval-only predictions, per route

**Library-routed cases (18 of 29).** Retrieval is **unchanged this batch** —
item 1 did not ship. Predicted movement vs v6 comes only from the corpus:
3,405 rows now, 17 quarantined, 60 guidelines in.

- papers per question: **+0 to +8**, driven by guideline rows entering the pool
- a `guideline` key appears in `per_tier` on most questions, typically **1–4**
- level1 **flat**; no cap or floor change landed here
- **6 of the 18 should not move at all.** If more than ~10 move by >10 papers,
  something shipped that I have not accounted for.

**Live-routed cases (11 of 29).** These move most.

- `per_tier.level1` **DOWN sharply** — the cap now applies to the deduped list,
  so 73 → 18 on the case I measured. Expect **level1 halving or worse**
- total papers **DOWN** on level1-heavy questions, **UP** on questions where
  `observational` and `guideline` now contribute
- new keys `observational`, `guideline`, `provisional` on questions where none
  existed in v6
- esearch queries **UP** — three more lanes × ~7 terms

**Case-mode cases (6).** As live, plus the differential runs one retrieval per
candidate, so per-question papers stay the highest in the set.

## 3. Synthesis-run predictions, per question

These need a synthesis harness and have **no v6 counterpart**. Stated as
absolute predictions so they are falsifiable on first measurement.

| metric | Literature/Review | Case | Curriculum |
|---|---|---|---|
| mean citations | **18–26** | **20–30** | **34–46** |
| distinct papers cited | **16–24** | **18–27** | **30–42** |
| provisional citations | **0–2** | **0–2** | **1–3** |
| guideline citations | **1–4** | **1–3** | **2–6** |
| cost per question | **$0.10–0.22** | **$0.18–0.35** | **$1.10–1.60** |

The citation numbers assume the 26%→100% fix dominates. It is the single
largest change in this list and it multiplies what Claude can cite by ~3.8×
on the live path; the citation rate will not scale with it, but the ceiling
moved and citations should land materially above A35a's measured 14–23.

---

## 4. Six things that would surprise me

More than six, because two are specific enough to be worth separating.

1. **Provisional citations at zero across all 29.** The lane now runs on every
   path and is outside the early stop. Zero would mean it retrieves and is
   never cited — which would make it cost without benefit and would be the
   most important negative result available here.
2. **Guideline citations at zero on the live path.** 60 records are in and the
   lane survives the early stop specifically so they are reachable on
   well-covered questions. Zero would mean the lane is reachable and the model
   still ignores it — a prompt problem, not a retrieval one, and it would
   redirect the next batch entirely.
3. **level1 counts on live cases NOT falling.** The cap moved onto the deduped
   list; 73 → 18 was measured directly. If v6's live cases still show 60–80
   level1 papers, the fix is not on the path the eval exercises.
4. **Library-routed paper counts moving by more than ~10.** Item 1 did not
   ship. Large movement there means something else changed the library route
   and I did not notice — the most likely candidate being a write-back
   admitting rows I have not accounted for.
5. **Mean citations below 14.** That is A35a's *pre-fix* range. Landing there
   after a 3.8× increase in visible evidence would mean the bottleneck was
   never visibility, and every inference in this batch's §2 would need
   re-examining.
6. **Cost per Review question above $0.40.** Three added lanes are ~$0.02–0.05
   of retrieval. A jump to $0.40 would mean synthesis retries (A45), not
   retrieval — a different problem wearing this batch's clothes.
7. **The Case differential's citation count NOT rising.** Item 2 incidentally
   fixed live-sourced differential papers reaching Claude as a metadata line
   with no title and no abstract (`_scored_to_text`'s two emit loops found
   nothing to emit). That is the same defect the 2026-08-31 library fix
   measured at 39.4% → 8.5% on the citation-support flag rate. If Case
   citations do not move, either the differential rarely uses the live route,
   or that defect was smaller than the library one — and I would want to know
   which.
8. **Any question where `distinct_pmids_retrieved` is unchanged from v6 on a
   live route.** Three lanes were added. Unchanged means they returned nothing
   for that question, which is possible once and suspicious three times.

---

## 5. What I am deliberately NOT predicting

- **Answer quality.** No metric here measures it and I will not imply one does.
- **The eight questions item 1a put below 40 papers.** That change did not
  ship, so they are not in this baseline. They will matter for the batch that
  designs the floor's interaction with `min_evidence_papers`.
- **D1's recency exemption.** Not implemented (see `early_stop_recency.md`).
  If a future run shows weak-tier papers on early-stopped Review questions,
  that is D1 having shipped, not drift.
