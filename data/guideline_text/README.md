# data/guideline_text — organisation-hosted guideline text, fetched through RB's Chrome

Files come in pairs, named by MANIFEST ID (data/guidelines_seed.json), not by
library key:

  <id>.txt   the page/document text exactly as Chrome rendered it, UTF-8.
             Site navigation and footer are removed; the document body is
             verbatim, untouched, including its own headings, numbering and
             reference list. Nothing is model-written.
  <id>.json  {"id", "url", "fetched_at" (UTC), "method": "chrome_dom_text",
              "sha256" (of the .txt bytes), "trimmed", "body_starts_with"}

`body_starts_with` is the first words of the document body, so an ingest that
wants the document's own summary can locate the body without guessing.
Where a document has a marked SUMMARY / Abstract / Executive Summary section,
that section is the one to store as the abstract; otherwise the first 300
words of the body.

Fetched by the advisory session (Claude in Chrome on RB's machine) because
these hosts return 403 / Imperva to non-browser fetches.
