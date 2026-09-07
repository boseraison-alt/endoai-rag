# Batch 2026-09-08 — Item A: a PMID-keyed guideline row's own text is its PubMed abstract

Rule 40, and the instrument error that produced it. On 2026-09-07
`fetch_guideline_text.py` went to the **publisher's** page for every pointer row
and collected 29 HTTP 403s — aae.org and Wiley refuse automated fetches. 23 of
those rows carry a numeric PMID, and for those the document's own text was
already on PubMed, reachable through the same efetch client that read 200 rows
that same night without a single 403. The corpus was never the problem; the
instrument was pointed at the wrong source.

**Guideline pointers: 45 → 15.**

## Change 1 — PubMed abstracts for PMID-keyed rows

| | rows |
|---|---|
| candidates (numeric PMID, `level_key='guideline'`, no `abstract_source`) | 39 |
| abstract retrieved and stored | 32 |
| PubMed indexes no abstract → stays a pointer, `fetch_failed='pubmed_no_abstract'` | 7 |

Of the 23 the batch named: **16 with an abstract, 7 blank**. The batch predicted
16–19 — correct, at the bottom of the range. My own prediction was that the
blank list would not be only the five AAOM statements; it was not. The blanks
are `26320105`, the five AAOM Clinical Practice Statements, and `42569978`.
`17899726` and the two JADA council reports, which I flagged as likely blanks,
all carry abstracts.

A second run after the re-key covered the six newly PMID-keyed rows: **3 more
abstracts** (`30171768`, `33501680`, `33934366`), 3 blank.

### Where the 90 citeable guideline rows now get their words

| source | rows |
|---|---|
| `pubmed` | 35 |
| `org_page` | 27 |
| `org_page_browser` | 13 |
| pointer (no text) | 15 |

The 15 remaining pointers: 9 `pubmed_no_abstract`, 2 `http_403`,
2 `no_extractable_text`, 2 not yet attempted.

## Change 2 — resolving `unconfirmed_pmid` by DOI

9 records tried, **7 matched** on a normalised title comparison, **6 written**.
`unconfirmed_pmid`: **11 → 5**.

| manifest id | PMID | written |
|---|---|---|
| `AAE-VPT-2021` | 34352305 | yes |
| `ESE-ECR-2018` | 30171768 | yes |
| `ESE-TRAUMA-2021` | 33934366 | yes |
| `ESE-EXTRUSION-REPLANT-2021` | 33501680 | yes |
| `AAE-TRAUMA-2026` | 41941956 | yes |
| `AAE-MRONJ-2026` | 41985837 | yes |
| `ACP-PARAMETERS-OF-CARE-2020` | 32681591 | **held back** |

Still unconfirmed: `AAE-DIAGNOSIS-2009` (excluded by design — its PMID is the
companion Background and Perspectives paper, which the manifest's own note
records), `AAE-SINUSITIS-2018`, `ASDA-PARAMETERS-OF-CARE-2018`,
`ACP-PARAMETERS-OF-CARE-2020`, `AAOM-CPS-ANTIRESORPTIVE-2019`.

### The one held back — for RB, because the batch's premise looks wrong

The batch pre-declared `ACP-PARAMETERS-OF-CARE-2020` a no-match: *"the only
PubMed hit is an editorial; do not take it."* Its DOI resolves to **32681591**,
and the record is **J Prosthodont 2020;29(S1):3-147** — no authors, no
abstract. A 145-page supplement is the Parameters of Care itself, not an
editorial about it.

I did not take it. The instruction is explicit, and the asymmetry decides it:
declining leaves the status quo (the record stays a slug row), while taking it
wrongly writes a false accession into the manifest **and then** retires the slug
row with a redirect to it — a compounding error in exactly the field the
`unconfirmed_pmid` mechanism exists to protect. The evidence is here to be
reversed in one line if RB agrees.

## The re-key, and the defect it caused

Applying the six resolutions re-keyed six slug rows onto their accessions.
Dry run and apply agreed exactly: **6 retires, 6 inserts, census delta 0**,
total rows 3443 → 3449. The redirect-chain repair fired once, re-pointing
`AAE-PS-vital-pulp` from `AAE-VPT-2021` straight to `34352305`. Redirect
chains after: **0**.

**Then the AAE's own words went missing, and nothing failed.** Citations follow
`redirect_to`; text does not. Retiring `AAE-VPT-2021` left the AAE's vital pulp
therapy text — browser-fetched precisely because aae.org 403s everything else —
on the quarantined row, while `34352305`, which had just inherited every
citation, had no abstract at all. PubMed has none for it either. The library
had quietly stopped being able to quote the AAE on vital pulp therapy, and the
re-key had silently undone item B's whole point for that document.

The repair is a pass in `ingest_guidelines_seed.py` that carries a retired row's
text to the row replacing it, **only into an empty target**, with the provenance
travelling alongside so it stays auditable. It runs over every redirect rather
than only fresh ones — the defect was found after the retire had already been
applied, and a pass that healed only new retires would have left it. Dry run and
apply both: **1 row, census delta 0**. Stranded documents after: **0**.

`test_no_text_is_stranded_on_a_retired_row` is now the alarm, and it proves it
can fail: it re-creates the exact defect in a transaction and rolls back.

## A second silent breakage: CRLF

Every one of the 13 browser-fetched files failed its sidecar hash, on a clean
`git status`, with nothing edited. Git stores them as LF and had materialised
them as **CRLF** on this Windows working tree, so each hashed differently while
being byte-identical in the repository. The next run of
`ingest_guideline_text_files.py` — item B, still to run — would have refused the
entire corpus.

The obvious fix, hashing with newlines normalised, would have weakened the one
check that makes the provenance chain worth having. Fixed at the storage layer
instead: `.gitattributes` marks `data/guideline_text/*` as `-text`, the files
were refreshed from git, and all 13 verify byte-exactly again. The ingest's
refusal message now names the CRLF case so this is legible in one line rather
than looking like corpus corruption.

## Tests

`tests/test_pubmed_abstract_fetch.py` — 17 tests. The usability rule is
**driven, not read**: `usable_abstract` was split out of the script so the test
calls it, and the mutation check moves `MIN_ABSTRACT_WORDS` to 1 and watches a
publisher's withdrawal notice become a guideline's stored text. Each database
property writes a violating row inside a transaction, asserts the detector
fires, and rolls back — including the batch's own check, *store a fetched
abstract without `abstract_source`, watch it fail*.

`TestNothingIsParaphrased` is green. Citeable rows carrying
`model_summary_legacy`: **0**.

### Nine tests repaired to identity, not re-pinned (rule 39)

The authorised re-key broke nine tests that had hard-coded `AAE-VPT-2021` as a
stable example of a citeable slug. None was re-pointed at a different literal —
each was repaired to the property it was actually asserting:

| test | was | now |
|---|---|---|
| `test_guideline_quarantine.CITEABLE_CONTROL` (3) | two named targets | the redirect chain resolved from the DB |
| `test_a_citeable_slug_still_resolves` | slug gate for both targets | branches on citation form — a PMID resolves as a citeable row |
| `test_gl_citation_form` GL/GL2 (2) | two named GL ids | two live slug-keyed rows, queried in a fixed order |
| ... its expected fields | `"ACP"`, `"2016"`, `"Vital Pulp Therapy"` | read from the same row the renderer reads |
| `test_rekey_redirect.test_an_unrelated_slug_is_untouched` | a named slug | any slug with no `redirect_to` |
| `test_cached_answers_render_current` (3) | literal cited sets | resolved one hop, as production does |

`test_guideline_text_provenance` also moved off the row key: those files are
named for the **manifest id**, which the re-key does not move, and the chain
check is scoped to citeable rows because a retired row's `guideline_id` is
deliberately blanked.

Full suite bare: **2783 passed, 52 skipped, 1 xfailed**.
