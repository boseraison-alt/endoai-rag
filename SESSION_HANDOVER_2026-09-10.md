# SESSION HANDOVER — 2026-09-06 (one source of truth) → next

Boot a new coding-agent chat with:

> Read `AGENT_QUEUE.md`, `SESSION_HANDOVER_2026-09-10.md` and
> `HANDOVER_GUIDELINES_2026-09-04.md`. Continue from the ORDER section below.

**Branch `fix/retrieval-blindspot`, pushed.**
Suite **2626 passed, 52 skipped, 1 xfailed, 0 failed.** Working tree clean.

**RETRIEVAL AND THE PROMPT BOTH CHANGED THIS BATCH.** `retrieval-freeze-20260905b`
no longer describes HEAD: the guideline lane's query is broader, the early stop
has a recency exemption, and the prompt enumerates every lane. **The v7
baseline is stale** — see the ORDER.

---

## 0. STATE BEFORE TOUCHING ANYTHING

- **Ports unchanged for eight sessions.** 5000 ours (pid 49800). **5003 is
  another session's (pid 27692) — never kill it, never use it.**
- **Run the suite BARE.** `testpaths = tests presentations`.
- **The library changed:** `ESE-QG-2006` quarantined `duplicate_of:17180780`.
  Citeable guideline rows 56 → 55; nothing deleted.
- **Backups, both verified:**
  `endo-ai-backups\endo-ai-rag-20260905-1520.bundle` (batch start),
  `…-20260905-item4.bundle` (end), and
  `db-20260905-1550\` — 14 tables, **26,233 rows**, taken before the one DB write.

---

## 1. THE ONE THING TO CARRY FORWARD

**A test that pins a source form reports a defect that is not there the moment
the form legitimately changes — and three of them did that this batch.**

- `def _run_tiers(tier_specs):` — pinned by exact signature; D1 added a
  parameter and four tests failed while the behaviour was correct.
- `_run_tiers([l for l in levels if l[0] == "guideline"])` — pinned as a
  one-line literal; D1 added the recency lanes to the same call and the test
  said the guideline lane was being skipped, while it was being fetched.
- The `TIER_ORDER` checklist's own window, twice over, in the previous batch.

Each was rewritten to assert the **property** (the function exists by name; the
guideline lane is in the early branch's fetch list). **The rule of thumb: pin
what the code must DO, and match source text only where the text IS the
behaviour** — as with the A/B-winning prompt wording, which is pinned verbatim
precisely because changing the words changes the result.

The mirror of it, also this batch: **two assumptions about existing helpers
that I did not check before building on them.** `_group_is_generic` is
all-or-nothing and does not mark a subject group; `guideline_topic` could
return an empty topic and query the whole domain. Both were caught by tests I
wrote, before either shipped. Rule 17's family — measure the real forms first.

---

## 2. WHAT LANDED

| item | outcome |
|---|---|
| **1a/1b** derived enumerations | **DONE** — one table, both enumerations, parity test |
| **1c** observational A/B | **PASS 3 of 5** after the first run proved unmeetable |
| **2** guideline lane query | **SHIPPED** — 79% → 3% empty, +0.09 s, both fixtures pass |
| **3** slug-id split | **DONE** — 1 re-keyable (and it was a duplicate), 30 stay, pinned |
| **4** D1 narrowed | **SHIPPED** — 11.1 papers, 14 s, both thresholds pass |

### Headline numbers

- **Observational A/B**: citations 2 → 5, guideline 14 → 15 (no regression),
  total 73 → 87, cost flat. Bar was ≥1 on 3 of 5 populated → **3 of 5**.
- **Guideline lane**: empty 23/29 → **1/29**; 22 questions gain a guideline,
  **0 lose one**; both fixtures (PMID 37772327, 26990236) go from absent to
  present.
- **D1 narrowed**: 24.6 papers/48 s → **11.1 papers/14 s**.

### The first observational A/B was inconclusive, not a failure

The batch pre-declared "≥1 on 3 of the 5 cases **where the tier is populated**"
using yesterday's five live Review cases. **The tier was populated on ONE.** The
bar was 3 of 1. The "18 of 29" figure that motivated the item is across all 29,
mostly library-routed, and does not describe that subset. Re-run on five cases
whose tier is populated in all three v7 runs — read from the baseline, not
guessed — it passes.

---

## 3. FOUND, NOT FIXED — with severities

- **18 real guideline documents cannot be cited on the library route.
  Severity: HIGH — now the largest constraint on the guideline path.** AAE
  position statements, SDCEP, NICE, CGDent: `confirmed` documents PubMed does
  not index, so they have no PMID and the prompt's `[[PMID:n]]` requirement
  excludes them. **The fix is a citation form, not retrieval** — A49 phase 1's
  `guidelines` table with `ORG-TOPIC-YEAR`. Test-pinned at exactly 30 slug rows
  so a later batch cannot quietly re-key them (inventing accessions) or
  quarantine them (removing real documents).
- **Item 2 helps the live route only. Severity: medium.** A guideline in the
  library still has to clear the cosine floor to be served, and
  `review-followup-immature-teeth` — one of the two fixture questions — is
  **library-pinned**. The fixture that motivated the fix is not fixed for that
  route.
- **1 of 29 questions still returns no guideline** even on the subject group.
  Probably a genuinely uncovered topic; not investigated, so that is an
  inference.
- **Two of the four A2-verified guideline records turned out redundant.**
  Verifying a document is real does not establish the ROW is needed, and
  nothing in A2 was asking that. Worth a look at the other two.
- **The recency window rounds outward** (18 months → 2 years) because PubMed
  gives a year. Deliberate and measured; noted so nobody reads 11.1 as an
  exactly-18-month figure.
- Unchanged: the library floor (parked, needs RB), the ~10.4 s embedding load
  on cold live processes, the extractor's ~77% recall.

---

## 4. DECISIONS, WITH THE ALTERNATIVE REJECTED

| decision | alternative rejected |
|---|---|
| enumerations from **`TIER_ORDER` + provisional** | the batch's literal `tier_query_lanes()`, which is the FETCH set and omits cochrane, classic, level3 and invitro — the lanes that only arrive from the library |
| non-rungs get headings but **are not ranked** | putting guidelines into a hierarchy the prompt tells the model to obey |
| the note table holds **no labels** | restating them, which is the duplication the table removes |
| A/B **re-run on a corrected population** | reporting "FAIL — revert" on an arithmetically unmeetable bar |
| subject group by **generic share** | `_group_is_generic` (all-or-nothing, picked the scenario group) and by length (same) |
| broadening in **`fetch_papers`** | app.py, which would reach Review and Case but not the curriculum |
| `ESE-QG-2006` **quarantined**, not re-keyed | re-keying, which would duplicate 17180780 |
| the 30 slug rows **left alone** | inventing accessions, or quarantining real documents |
| D1 narrowed to **level2 + level3a** | the full exemption (breached both thresholds) |
| harness **fixed** before claiming a pass | reporting "both thresholds pass" on a latency that measured the full sweep |

---

## 5. ORDER FOR THE NEXT SESSION

1. **Re-run the v7 baseline.** Retrieval changed twice (guideline query, D1)
   and the prompt changed. `baseline_v7.json` no longer describes HEAD.
   **Write the A46 prediction first, naming `baseline_v7` and its date**
   (rule 35). Predict: guideline tier populated on far more than 21 of 29;
   level2/level3a non-zero on early-stopped Review questions; +14 s per Review
   question.
2. **A citation form for the 18 non-indexed guidelines.** §3, first item.
   This is A51's precondition too: its guideline-vs-evidence divergence check
   cannot compare what the answer cannot cite.
3. **A51.** After this batch, guidelines are citeable on the live route, the
   prompt sees every lane and the harness counts every lane — the first time
   its divergence check has a complete picture.
4. Re-warm the demo cache. Prompt and retrieval both moved.
5. The library floor still needs its two-guard design.

---

## 6. REPLAY

```
python scripts/ab_lane_headings.py --json eval/reports/a49_lane_headings_ab.json
python scripts/measure_guideline_lane_query.py --json eval/reports/guideline_lane_query.json
python scripts/quarantine_duplicate_guidelines.py            # --apply, --restore
python scripts/measure_early_stop_recency.py --lanes level2,level3a
python eval/run_eval.py
```

Reports: `a49_lane_headings_ab.md`, `guideline_lane_query.md`,
`guideline_slug_ids.md`, `early_stop_recency.md` (full + amendment),
`a46b_baseline_v7_outcome.md`, `library_floor_29.md`.
