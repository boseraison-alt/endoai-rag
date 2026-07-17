# Metadata Regression Test — 7-Day Verification Plan
Check off each task in the app (Tasks button, bottom-right corner).

## Day 1 · Apr 29 — Run the baseline test
Open a terminal in the `endo-ai-rag` folder and run:
```
pytest tests/
```
Expected: **1 passed, 2 skipped** — this is correct at this stage.
Read `tests/README_metadata_tests.md` to understand what the 2 skipped tests need.

---

## Day 2 · Apr 30 — Find 5 candidate PMIDs
Go to pubmed.ncbi.nlm.nih.gov and find one paper of each type:
1. In vitro study (bench research, no patients)
2. Small RCT (≤30 patients)
3. Large RCT (>100 patients)
4. Systematic review or meta-analysis
5. Case series

Write down the 5 PMIDs. Pick papers whose abstracts clearly state sample size and follow-up.

---

## Day 3 · May 1 — Verify each PMID on PubMed
For each PMID: open `pubmed.ncbi.nlm.nih.gov/<PMID>`, read the full abstract, record:
- **Exact patient count** (n=?). If abstract doesn't state it clearly → "unknown"
- **Follow-up in months**. If in vitro or not stated → "unknown"

Do not estimate. Do not use tooth count when you mean patient count.

---

## Day 4 · May 2 — Fill in the test fixture
Open `tests/test_metadata_extraction.py`, find `VERIFIED_FIXTURES`, and add your 5 entries:
```python
{
    "pmid": "12345678",
    "expected_sample_size": 45,      # int or "unknown"
    "expected_follow_up_months": 24, # int or "unknown"
    "verified_on": "2026-05-02",
    "notes": "RCT, 45 patients, 24mo FU. pubmed.ncbi.nlm.nih.gov/12345678"
},
```

---

## Day 5 · May 3 — Download XML fixture files
Run in the terminal:
```
python scripts/fetch_and_save_fixtures.py
```
Confirm `tests/fixtures/pubmed_xml/` contains 5 XML files (one per PMID).

---

## Day 6 · May 4 — Run the full test suite
```
pytest tests/ -v
```
Expected: **3 passed, 0 skipped**

If a test fails: re-read the abstract for that PMID — the extracted value should match what PubMed says. Do NOT change the expected value just to make the test pass without re-reading.

---

## Day 7 · May 5 — Visual check in the live app
1. Generate a Deep Learning report on any topic
2. Scroll to the bibliography
3. Confirm papers show **different** n= and follow-up values — no block-repetition

**PASS:** n=45, n=unknown, n=312, n=18... (each paper different)  
**FAIL:** Multiple consecutive unrelated papers with identical n= and follow-up → bug not fixed
