# Metadata Extraction Regression Tests

These tests are the tripwire for the per-PMID metadata isolation bug
([commit history](#)). They fail if extraction ever regresses to operating
on concatenated batch text instead of per-paper text.

## What's in this directory

| File | Purpose |
|------|---------|
| `test_metadata_extraction.py` | The tests. Pytest. |
| `conftest.py` | Pytest fixtures — `mock_pubmed_efetch_batch`, `real_pubmed_search_result`. |
| `scripts/fetch_and_save_fixtures.py` | One-time tool to fetch real PubMed XML and save to disk. Also prints abstracts for manual verification. |
| `fixtures/pubmed_xml/batch_*.txt` | Saved efetch abstract-text responses (created by the fetch script). Production `rettype=abstract&retmode=text` format — the exact input `_parse_efetch_batch` sees at runtime. |

## How to add a new fixture PMID

This is the workflow that keeps the test honest. Skip any step at your peril.

1. **Find a candidate PMID.** Search PubMed for a paper that exposes a study
   type not yet covered (in vitro, RCT, case series, meta-analysis, cohort).

2. **Verify the metadata against the actual abstract.**
   ```bash
   python scripts/fetch_and_save_fixtures.py --verify-only 12345678
   ```
   This prints the title, abstract, and a verification checklist. Read the
   abstract. Determine the actual sample size and follow-up.

   **Rules:**
   - Sample size = the n in THIS paper, not in any referenced literature.
   - In vitro studies → `"unknown"` (we don't assert n=80 teeth as a clinical n).
   - Meta-analyses → use the patient total stated in the abstract, not the
     count of included studies.
   - Follow-up in months. Use the upper bound if a range is given. In vitro → `"unknown"`.

3. **Add the PMID to `VERIFIED_FIXTURES` in `test_metadata_extraction.py`.**
   Fill in `expected_sample_size`, `expected_follow_up_months`, `study_type`,
   `verified_on` (today's date), and verification notes (PubMed URL + a one-line
   description).

4. **Add the PMID to `TARGET_PMIDS` in `scripts/fetch_and_save_fixtures.py`.**

5. **Save the batch XML fixture.**
   ```bash
   python scripts/fetch_and_save_fixtures.py
   ```
   This fetches a batch containing your new PMID alongside `FILLER_PMIDS` (a
   diverse set of 4-5 papers spanning study types) and saves the XML to
   `fixtures/pubmed_xml/batch_<PMID>.txt`. The batch is what tests use —
   isolating extraction inside a batch is the entire point.

6. **Run the test.**
   ```bash
   pytest tests/test_metadata_extraction.py -v
   ```
   Confirm your new fixture's test passes. If it fails, either:
   - The metadata you asserted is wrong → re-verify against the abstract.
   - The extractor has a real bug → fix the extractor.

## Why the fixture design is this paranoid

Three design decisions might look excessive but each prevents a specific failure mode:

**1. Tests run on batches, never on single papers.**
The bug we just fixed only manifests inside a batch. A test that calls
`extract_sample_size("paper A's abstract")` would have always passed even
during the bug. Saving real batch XML and running the parser-then-extractor
chain on it is the only reliable reproduction.

**2. Filler PMIDs span study types deliberately.**
If all 5 papers in a batch were RCTs with similar n, a "broadcast" bug might
not be visible. We pick fillers across in vitro / meta-analysis / RCT / case
series so the broadcast value would be obviously wrong for at least one
target.

**3. The verification protocol forces reading the actual abstract.**
LLM-generated test data is the leading cause of confidently wrong tests.
Every PMID in the fixture has a `verified_on` date and a URL. If you can't
fill those in, you don't add the entry.

## What to do if the test fails

The test fails in three scenarios. Each has a different fix:

**Scenario A: A specific per-PMID assertion fails.**
Either the extractor has a real bug, or the fixture metadata is wrong. Open
the PubMed URL from `verification_notes`, re-read the abstract, and decide.

**Scenario B: `test_no_block_repetition_in_batch_extraction` fails.**
The original bug has regressed. Multiple verified PMIDs are now extracting
to the same value. This is the canary. Fix the extraction code.

**Scenario C: `test_metadata_distribution_in_real_batch` fails.**
A real PubMed query returned a result set with suspiciously uniform metadata.
Either the bug regressed in a subtle way, or the query happened to return
genuinely homogeneous papers. Inspect the printed sample sizes and decide.

## Maintenance

- Fixtures don't expire. Once verified, they stay valid until PubMed changes
  the abstract (extremely rare).
- If you delete a paper from the fixture, also delete the corresponding
  `batch_<PMID>.txt` file.
- If you change the extractor's expected output type (e.g., return strings
  instead of ints), update both `VERIFIED_FIXTURES` and the assertions.
- Run the network test (`real_pubmed_search_result`) at least once per release
  even though it's slow. It catches bugs the offline tests can't.
