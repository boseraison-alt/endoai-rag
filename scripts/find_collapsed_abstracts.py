"""Find rows whose stored "abstract" is not an abstract.

`endo_ai._parse_efetch_batch` (the live path, and the writer that fills
`abstract_cache`), `app.get_abstract`'s L3 fallback and
`ingest_classics._fetch_paper` all build an abstract by taking the LONGEST
paragraph of `rettype=abstract&retmode=text`.

Measured on 198 library PMIDs, that heuristic loses NOTHING to structured
abstracts — PubMed's text renderer emits BACKGROUND/METHODS/RESULTS/CONCLUSIONS
as one blank-line-free block, so the collapse keeps 100% of 95 structured
abstracts. The hypothesis recorded in HANDOVER — that it drops conclusions the
way the ingest truncation did — is false.

Its real failure is the opposite one. "Longest paragraph" is a proxy for "the
abstract" and two other blocks can be longer:

  * the AUTHOR AFFILIATION list. PMID 39743567 (a Chinese expert consensus with
    ~30 institutional addresses) stores 6,304 characters of university
    departments where its 707-character abstract should be.
  * a FOREIGN-LANGUAGE abstract. PubMed prints translations under `Publisher:`,
    and PMID 41337506's Portuguese version is longer than its English one.

Both reach synthesis as the paper's text, and both are written into
`abstract_cache`, which is what `verify_citation_support` reads. A paper whose
"abstract" is a list of addresses flags every claim cited to it, and the
clinician is shown the flag with no way to see why.

    python scripts/find_collapsed_abstracts.py            # report
    python scripts/find_collapsed_abstracts.py --csv out.csv

Read-only.
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The two blocks that outgrow an abstract in PubMed's text rendering. Anchored
# at the start: "Author information:" appearing mid-abstract is a paper about
# authorship, not a mis-parse.
_AFFIL_PREFIX = re.compile(r"^\s*Author information\s*:", re.IGNORECASE)
_XLAT_PREFIX  = re.compile(r"^\s*Publisher\s*:", re.IGNORECASE)
# An affiliation list is numbered "(1)...(2)...(3)..." — three markers inside
# the first 1200 characters is a shape no abstract has. The lookbehind is not
# decoration: without it `Bi(2)O(3)` in a bismuth-trioxide abstract matches
# twice and a perfectly good abstract is reported as a mis-parse. It was, on
# the first run.
_AFFIL_SHAPE  = re.compile(r"(?<![A-Za-z0-9])\(\d+\)[A-Z]")
# Comment/erratum blocks the renderer also emits as their own paragraph.
_COMMENT_PREFIX = re.compile(r"^\s*(Comment (in|on)|Erratum (in|for))\s*:",
                             re.IGNORECASE)


def classify(abstract):
    a = abstract or ""
    if _AFFIL_PREFIX.match(a):
        return "affiliation_block"
    if _XLAT_PREFIX.match(a):
        return "foreign_language"
    if _COMMENT_PREFIX.match(a):
        return "comment_block"
    if len(_AFFIL_SHAPE.findall(a[:1200])) >= 3:
        return "affiliation_shape"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    args = ap.parse_args()

    from rag import get_conn
    conn = get_conn()
    cur = conn.cursor()
    hits = []
    for table, extra in (("endo_papers_rag", ""), ("abstract_cache", "")):
        cur.execute(f"SELECT pmid, title, abstract FROM {table} "
                    f"WHERE abstract IS NOT NULL AND abstract <> '';")
        rows = cur.fetchall()
        bad = [(table, p, t, a, k) for p, t, a in rows if (k := classify(a))]
        print(f"{table}: {len(rows)} rows with an abstract, {len(bad)} mis-parsed "
              f"({100.0 * len(bad) / max(1, len(rows)):.2f}%)")
        for kind in ("affiliation_block", "foreign_language", "comment_block",
                     "affiliation_shape"):
            n = sum(1 for b in bad if b[4] == kind)
            if n:
                print(f"    {kind:20s} {n}")
        hits.extend(bad)
    cur.close()
    conn.close()

    print()
    for table, pmid, title, abstract, kind in hits:
        print(f"  [{kind}] {table} {pmid} len={len(abstract)}")
        print(f"      title: {(title or '(none)')[:110]}")
        print(f"      stored: {abstract[:150]!r}")

    if args.csv and hits:
        import csv
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["table", "pmid", "kind", "stored_len", "title"])
            for table, pmid, title, abstract, kind in hits:
                w.writerow([table, pmid, kind, len(abstract), title or ""])
        print(f"\ncsv -> {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
