"""Heal the rows whose stored "abstract" is not an abstract.

WHY
---
Four call sites build a paper's abstract by taking the LONGEST PARAGRAPH of
`rettype=abstract&retmode=text`: `endo_ai._parse_efetch_batch` (the live
retrieval path, and the writer that fills `abstract_cache`),
`app.get_abstract`'s L3 fallback, `ingest_classics._fetch_paper`, and — in a
third variant that keeps the whole entry — `ingest_aae_guidelines`.

The hypothesis on record was that this loses the conclusions of structured
abstracts, the way the ingest truncation did. Measured against efetch XML on
198 library PMIDs, 95 of them structured, it loses NOTHING: PubMed's text
renderer emits BACKGROUND/METHODS/RESULTS/CONCLUSIONS as one blank-line-free
block, so the collapse keeps 100%.

Its real failure is the opposite. "Longest paragraph" is a proxy for "the
abstract", and two other blocks in a PubMed text entry can be longer:

  * the AUTHOR AFFILIATION list — PMID 39743567, a Chinese expert consensus
    with ~30 institutional addresses, stores 6,304 characters of university
    departments in place of its 707-character abstract;
  * a FOREIGN-LANGUAGE abstract, printed under `Publisher:` — PMID 41337506's
    Portuguese version is longer than its English one.

Both reach synthesis as the paper's text, and both are written into
`abstract_cache`, which is what `verify_citation_support` reads. A paper whose
"abstract" is a list of addresses flags every claim cited to it, and the
clinician sees the flag with no way to know why.

WHAT IT DOES
------------
Finds every row in `endo_papers_rag` and `abstract_cache` whose abstract has a
mis-parse signature (`scripts/find_collapsed_abstracts.py` is the detector),
re-fetches those PMIDs from efetch XML, and replaces the stored text with the
`<AbstractText>` elements — which carry their section labels and cannot be an
affiliation block, because affiliations are not in that element.

Library rows are RE-EMBEDDED, because the stored vector was computed from text
the row no longer holds.

    python scripts/repair_collapsed_abstracts.py            # dry run
    python scripts/repair_collapsed_abstracts.py --apply    # write
    python scripts/repair_collapsed_abstracts.py --reembed-only

BACKUPS. Every column this writes is backed up first, derived ones included:
`endo_papers_rag.abstract`, `.title` and `.embedding`; `abstract_cache.abstract`,
`.title` and `.source`. The standing rule exists because the `grounding-v1`
repair backed up the abstracts it was thinking about and not the embeddings it
also overwrote, and those vectors are gone. Name the columns the script WRITES
and back up that list.
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2.extras
from defusedxml import ElementTree as DET

from endo_ai import NCBI_EUTILS_BASE, _ncbi_params, ncbi_get
from rag import get_conn
from scripts.find_collapsed_abstracts import classify

BATCH = 200
RUN_ID = "collapsed_abstract_repair"
LIB_BACKUP = "endo_papers_rag_collapsed_backup"
CACHE_BACKUP = "abstract_cache_collapsed_backup"


def fetch_from_xml(pmids: list[str]) -> dict[str, dict]:
    """{pmid: {"abstract", "title"}} from efetch XML.

    The whole point of this repair is that the text dump is a RENDERING and
    the XML is data. `<AbstractText>` cannot contain an affiliation block or a
    translation, because PubMed puts those in `<AffiliationInfo>` and
    `<OtherAbstract>`. No heuristic is needed and none is used.

    `MedlineCitation/PMID`, never `.//PMID`: a record's CommentsCorrectionsList
    carries the PMIDs of the papers it corrects, and a descendant search picked
    one of those up once already. `is None`, never `or`: a childless Element is
    falsy, and `find(a) or find(b)` silently discards `<PMID>12345</PMID>`.
    """
    params = _ncbi_params({"db": "pubmed", "id": ",".join(pmids),
                           "retmode": "xml"})
    resp = ncbi_get(f"{NCBI_EUTILS_BASE}/efetch.fcgi", params=params, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"efetch returned HTTP {resp.status_code}")

    out: dict[str, dict] = {}
    root = DET.fromstring(resp.text)
    for article in (list(root.iter("PubmedArticle"))
                    + list(root.iter("PubmedBookArticle"))):
        pmid_el = article.find("MedlineCitation/PMID")
        if pmid_el is None:
            pmid_el = article.find("BookDocument/PMID")
        if pmid_el is None or not (pmid_el.text or "").strip():
            continue
        pmid = pmid_el.text.strip()

        # `Abstract/AbstractText`, scoped — NOT `.//AbstractText`. A record's
        # OtherAbstract (the foreign-language translation that caused half of
        # these rows) also contains AbstractText children, and a descendant
        # search would pull the Portuguese back in through the fix.
        parts = []
        for node in article.iter("Abstract"):
            for at in node.findall("AbstractText"):
                text = "".join(at.itertext()).strip()
                if not text:
                    continue
                label = (at.get("Label") or "").strip()
                parts.append(f"{label}: {text}" if label else text)
        title_el = article.find("MedlineCitation/Article/ArticleTitle")
        if title_el is None:
            title_el = article.find("BookDocument/ArticleTitle")
        title = ("".join(title_el.itertext()).strip()
                 if title_el is not None else "")
        out[pmid] = {"abstract": " ".join(parts).strip(), "title": title}
    return out


def _collect(cur):
    """Every mis-parsed row in both tables, keyed by table."""
    found = {}
    for table in ("endo_papers_rag", "abstract_cache"):
        cur.execute(f"SELECT pmid, title, abstract FROM {table} "
                    f"WHERE abstract IS NOT NULL AND abstract <> '';")
        rows = [dict(r) for r in cur.fetchall()]
        bad = [r | {"kind": k} for r in rows if (k := classify(r["abstract"]))]
        found[table] = bad
        print(f"[collapsed] {table}: {len(rows)} rows with an abstract, "
              f"{len(bad)} mis-parsed ({100.0 * len(bad) / max(1, len(rows)):.2f}%)")
        kinds = {}
        for r in bad:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        for k, n in sorted(kinds.items()):
            print(f"    {k:20s} {n}")
    return found


def reembed_from_backup() -> int:
    """Re-embed every library row this repair changed. Idempotent."""
    from rag import embed

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(f"""SELECT r.pmid, r.title, r.abstract
                    FROM endo_papers_rag r
                    JOIN {LIB_BACKUP} b ON b.pmid = r.pmid
                    WHERE b.run_id = %s""", (RUN_ID,))
    rows = cur.fetchall()
    print(f"[reembed] {len(rows)} library rows changed by run_id={RUN_ID}")
    done = 0
    for row in rows:
        vec = embed(f"{row['title'] or ''}\n{row['abstract'] or ''}")
        cur.execute("UPDATE endo_papers_rag SET embedding = %s::vector "
                    "WHERE pmid = %s", (vec, row["pmid"]))
        done += 1
    conn.commit()
    cur.close()
    conn.close()
    print(f"[reembed] re-embedded {done} of {len(rows)}")
    return 0 if done == len(rows) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write changes (default: dry run)")
    ap.add_argument("--samples", type=int, default=8)
    ap.add_argument("--reembed-only", action="store_true",
                    help="skip the fetch; re-embed the library rows this "
                         "repair changed, read from the backup table")
    args = ap.parse_args()

    if args.reembed_only:
        return reembed_from_backup()

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    found = _collect(cur)

    pmids = sorted({r["pmid"] for rows in found.values() for r in rows
                    if str(r["pmid"]).isdigit()})
    print(f"\n[collapsed] {len(pmids)} distinct PMIDs to re-fetch from XML")
    if not pmids:
        print("[collapsed] nothing to do.")
        cur.close(); conn.close()
        return 0

    fetched: dict[str, dict] = {}
    t0 = time.time()
    for i in range(0, len(pmids), BATCH):
        chunk = pmids[i:i + BATCH]
        try:
            fetched.update(fetch_from_xml(chunk))
        except Exception as e:
            print(f"  [collapsed] batch {i // BATCH + 1} FAILED: "
                  f"{type(e).__name__}: {e}")
            continue
        print(f"  [collapsed] {len(fetched)}/{len(pmids)} fetched "
              f"({time.time() - t0:.0f}s)")
        time.sleep(0.4)

    # ── What would change ────────────────────────────────────────────────
    # A row changes only when the XML gives a NON-EMPTY abstract that is not
    # itself mis-parse-shaped. An empty result means PubMed holds no abstract
    # for that record, and blanking the row would be a second data loss on top
    # of the first — the affiliation block is wrong, but "nothing" is not
    # better and is harder to notice.
    plans, unfetched, still_bad = {}, [], []
    for table, rows in found.items():
        plan = []
        for r in rows:
            got = fetched.get(str(r["pmid"]))
            if not got or not got["abstract"]:
                unfetched.append((table, r["pmid"]))
                continue
            if classify(got["abstract"]):
                still_bad.append((table, r["pmid"]))
                continue
            plan.append({"pmid": r["pmid"],
                         "old_abstract": r["abstract"], "old_title": r["title"],
                         "new_abstract": got["abstract"],
                         "new_title": got["title"] or r["title"] or "",
                         "kind": r["kind"]})
        plans[table] = plan
        print(f"\n[collapsed] {table}: {len(plan)} row(s) would be rewritten")

    if unfetched:
        print(f"[collapsed] {len(unfetched)} row(s) had no usable abstract in "
              f"the XML and are LEFT ALONE: {unfetched[:6]}")
    if still_bad:
        print(f"[collapsed] {len(still_bad)} row(s) came back still matching a "
              f"mis-parse signature — left alone: {still_bad[:6]}")

    # Random samples, not the biggest deltas: a top-N sample sorted by gain
    # flatters itself, which is the lesson the 1.4/1.5 migrations left behind.
    rnd = random.Random(20260901)
    for table, plan in plans.items():
        for row in rnd.sample(plan, min(args.samples, len(plan))):
            print(f"\n--- {table} PMID {row['pmid']}  [{row['kind']}]  "
                  f"{len(row['old_abstract'])} -> {len(row['new_abstract'])} chars")
            print(f"    title  : {(row['new_title'] or '(none)')[:110]}")
            print(f"    BEFORE : {row['old_abstract'][:150]!r}")
            print(f"    AFTER  : {row['new_abstract'][:150]!r}")

    total = sum(len(p) for p in plans.values())
    if not args.apply:
        print(f"\n[collapsed] DRY RUN — nothing written. {total} row(s) would "
              f"change. Re-run with --apply once the samples read correctly.")
        cur.close(); conn.close()
        return 0
    if not total:
        print("\n[collapsed] nothing to apply.")
        cur.close(); conn.close()
        return 0

    # ── Backups: every column this writes, derived ones included ─────────
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {LIB_BACKUP} (
            pmid TEXT, abstract TEXT, title TEXT, embedding vector(384),
            run_id TEXT, backed_up_at TIMESTAMP DEFAULT NOW());""")
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {CACHE_BACKUP} (
            pmid TEXT, abstract TEXT, title TEXT, source TEXT,
            run_id TEXT, backed_up_at TIMESTAMP DEFAULT NOW());""")

    lib = plans.get("endo_papers_rag") or []
    if lib:
        # The embedding is copied from the LIVE row, not reconstructed: this
        # is the column the grounding-v1 repair lost by backing up the one it
        # was thinking about instead of the ones it wrote.
        psycopg2.extras.execute_batch(cur, f"""
            INSERT INTO {LIB_BACKUP} (pmid, abstract, title, embedding, run_id)
            SELECT pmid, abstract, title, embedding, %s
            FROM endo_papers_rag WHERE pmid = %s;""",
            [(RUN_ID, r["pmid"]) for r in lib])
        print(f"[collapsed] backed up {len(lib)} library row(s) "
              f"(abstract, title, embedding) -> {LIB_BACKUP}")

    cache = plans.get("abstract_cache") or []
    if cache:
        psycopg2.extras.execute_batch(cur, f"""
            INSERT INTO {CACHE_BACKUP} (pmid, abstract, title, source, run_id)
            SELECT pmid, abstract, title, source, %s
            FROM abstract_cache WHERE pmid = %s;""",
            [(RUN_ID, r["pmid"]) for r in cache])
        print(f"[collapsed] backed up {len(cache)} cache row(s) "
              f"(abstract, title, source) -> {CACHE_BACKUP}")
    conn.commit()

    # ── Write ────────────────────────────────────────────────────────────
    if lib:
        psycopg2.extras.execute_batch(cur, """
            UPDATE endo_papers_rag SET abstract = %s, title = %s
            WHERE pmid = %s;""",
            [(r["new_abstract"], r["new_title"], r["pmid"]) for r in lib])
    if cache:
        psycopg2.extras.execute_batch(cur, """
            UPDATE abstract_cache
            SET abstract = %s, title = %s, source = 'efetch_xml_repair'
            WHERE pmid = %s;""",
            [(r["new_abstract"], r["new_title"], r["pmid"]) for r in cache])
    conn.commit()
    print(f"[collapsed] wrote {len(lib)} library and {len(cache)} cache row(s)")
    cur.close()
    conn.close()

    if lib:
        return reembed_from_backup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
