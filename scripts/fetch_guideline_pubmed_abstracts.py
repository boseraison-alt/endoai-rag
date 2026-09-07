"""Item A (2026-09-08) — a PMID-keyed guideline row's own text is its PubMed
abstract.

THE INSTRUMENT ERROR THIS CORRECTS (rule 40). On 2026-09-07,
`fetch_guideline_text.py` went to the PUBLISHER's page for every pointer row
and collected 29 HTTP 403s — aae.org and Wiley refuse automated fetches. But
23 of those rows carry a numeric PMID, and for those the document's own text
is already on PubMed, through the same efetch client that read 200 rows that
same night without a single 403. The publisher's page is the fallback; PubMed
is the source.

WHERE PUBMED HAS NO ABSTRACT the row STAYS A POINTER and records
`fetch_failed = "pubmed_no_abstract"`. Short consensus statements and council
reports are frequently indexed without one, and inventing text for them is the
thing this whole path exists to prevent.

    python scripts/fetch_guideline_pubmed_abstracts.py            # DRY RUN
    python scripts/fetch_guideline_pubmed_abstracts.py --apply
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E  # noqa: E402
import rag           # noqa: E402

PUBMED_URL = "https://pubmed.ncbi.nlm.nih.gov/%s/"

# A PubMed record can carry a one-line publisher note in the abstract slot
# ("This article has been withdrawn.", a copyright line, a bare objective).
# Storing that as the document's text is worse than storing nothing: it looks
# like an abstract to every downstream reader and says nothing the pointer
# does not already say. 20 words is the floor for calling it text.
MIN_ABSTRACT_WORDS = 20


def usable_abstract(abstract):
    """True when PubMed's abstract slot holds enough to be the row's own text.

    Split out so the test can DRIVE this rule rather than read the source. An
    earlier guard in this repo was tested by asserting a call appeared between
    two lines; it passed with the call wrapped in `if False:`.
    """
    return len((abstract or "").split()) >= MIN_ABSTRACT_WORDS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = rag.get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT pmid, COALESCE(guideline_org,''), title,
               COALESCE(fetch_failed,'')
        FROM endo_papers_rag
        WHERE level_key = 'guideline'
          AND COALESCE(quarantine_reason,'') = ''
          AND pmid ~ '^[0-9]+$'
          AND COALESCE(abstract_source,'') = ''
        ORDER BY pmid
    """)
    rows = cur.fetchall()

    print("=" * 78)
    print("ITEM A — PUBMED ABSTRACTS FOR PMID-KEYED GUIDELINE ROWS  (%s)"
          % ("APPLY" if args.apply else "DRY RUN"))
    print("=" * 78)
    print("  candidate rows: %d" % len(rows))
    if not rows:
        print("  nothing to do")
        return 0

    pmids = [r[0] for r in rows]
    recs = E._fetch_pubtypes_and_abstracts(pmids)

    got, blank = [], []
    for pmid, org, title, prev_fail in rows:
        rec = recs.get(pmid) or {}
        abstract = (rec.get("abstract") or "").strip()
        if usable_abstract(abstract):
            got.append((pmid, org, abstract, rec))
        else:
            blank.append((pmid, org, title, len(abstract.split())))

    print()
    print("  %-10s %-8s %6s  %s" % ("pmid", "org", "words", "title"))
    for pmid, org, abstract, rec in got:
        print("  %-10s %-8s %6d  %s"
              % (pmid, org or "-", len(abstract.split()),
                 (rec.get("title") or "")[:52]))
    print()
    print("  NO ABSTRACT ON PUBMED — these stay pointers")
    for pmid, org, title, n in blank:
        print("  %-10s %-8s %6d  %s" % (pmid, org or "-", n, (title or "")[:52]))

    print()
    print("  with an abstract : %d" % len(got))
    print("  blank            : %d" % len(blank))

    if args.apply:
        today = datetime.now().date().isoformat()
        for pmid, _org, abstract, _rec in got:
            sha = hashlib.sha256(abstract.encode("utf-8")).hexdigest()
            cur.execute("""
                UPDATE endo_papers_rag SET
                    abstract = %s, abstract_source = 'pubmed',
                    abstract_fetched = %s, abstract_sha256 = %s,
                    abstract_url = %s, fetch_failed = ''
                WHERE pmid = %s
            """, (abstract, today, sha, PUBMED_URL % pmid, pmid))
        for pmid, _org, _t, _n in blank:
            cur.execute("UPDATE endo_papers_rag SET "
                        "fetch_failed = 'pubmed_no_abstract' WHERE pmid = %s",
                        (pmid,))
        conn.commit()
        print("\n  APPLIED.")
    else:
        print("\n  DRY RUN — nothing written.")

    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    json.dump({"with_abstract": [p for p, _o, _a, _r in got],
               "blank": [p for p, _o, _t, _n in blank]},
              open("eval/reports/night10_item_a.json", "w"), indent=1)
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
