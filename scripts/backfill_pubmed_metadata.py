"""
Single-pass PubMed metadata backfill for the RAG library.

Re-fetching ~1,900 PMIDs is the expensive step, so ONE efetch XML call per
batch supplies everything we want from it:

    PublicationTypeList     -> level_key (evidence design)
    MedlineCitation Status  -> medline_indexed
    CommentsCorrectionsList -> has_erratum / has_retraction
                               (ErratumIn, CorrectedandRepublishedIn,
                                ExpressionOfConcernIn, RetractionIn)
    CoiStatement            -> coi_status / coi_flag / coi_funder
    DataBankList            -> registry (pre-registration)

Replaces the earlier two-pass approach (backfill_level_keys.py +
backfill_provenance.py), which fetched the same records twice.

Rate limit: NCBI allows 3 req/s without an API key, 10 req/s with one
(NCBI_API_KEY in .env). Batch size 200 keeps the URL well inside limits.

Usage:
    python scripts/backfill_pubmed_metadata.py            # dry run
    python scripts/backfill_pubmed_metadata.py --apply    # write
    python scripts/backfill_pubmed_metadata.py --limit 200
"""

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2.extras
from endo_ai import (_merge_corrections_and_registries, detect_preregistration,
                     classify_coi, COI_DECLARED_CONFLICT)
from rag import get_conn, setup_table

BATCH_SIZE = 200
SLEEP_S    = 0.4   # ~2.5 req/s — safe without an API key

# PubMed publication type -> evidence level, highest evidence first.
PUBTYPE_TO_LEVEL = [
    ("meta-analysis", "level1"), ("systematic review", "level1"),
    ("randomized controlled trial", "level1"), ("practice guideline", "level1"),
    ("guideline", "level1"), ("consensus development conference", "level1"),
    ("controlled clinical trial", "level2"), ("clinical trial, phase iv", "level2"),
    ("clinical trial, phase iii", "level2"), ("clinical trial", "level2"),
    ("multicenter study", "level2"),
    ("observational study", "level3a"), ("comparative study", "level3a"),
    ("evaluation study", "level3b"),
    ("case reports", "level4"),
    ("review", "level5"), ("editorial", "level5"),
    ("comment", "level5"), ("letter", "level5"),
]


def infer_level(pubtypes: list, journal: str) -> tuple:
    if "cochrane" in (journal or "").lower():
        return "cochrane", "journal:cochrane"
    lowered = [str(p).strip().lower() for p in (pubtypes or [])]
    for tag, level in PUBTYPE_TO_LEVEL:
        if tag in lowered:
            return level, tag
    return None, None


def fetch_all(pmids: list) -> dict:
    """One efetch XML call per batch; returns {pmid: {...signals...}}."""
    out = {}
    for i in range(0, len(pmids), BATCH_SIZE):
        chunk = pmids[i:i + BATCH_SIZE]
        meta = {p: {"medline_indexed": True, "has_erratum": False,
                    "has_retraction": False, "registry_ids": [],
                    "coi_statement": "", "pubtypes": []} for p in chunk}
        try:
            _merge_corrections_and_registries(chunk, meta)
        except Exception as e:
            print(f"  batch {i//BATCH_SIZE} failed: {e}")
        out.update(meta)
        print(f"  fetched {min(i+BATCH_SIZE, len(pmids))}/{len(pmids)}")
        time.sleep(SLEEP_S)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    setup_table()

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""
            SELECT pmid, journal, abstract, level_key, is_curated
            FROM endo_papers_rag
            WHERE pmid ~ '^[0-9]+$'
            ORDER BY pmid;
        """)
        rows = cur.fetchall()
        if args.limit:
            rows = rows[:args.limit]
        print(f"[pubmed] {len(rows)} papers with numeric PMIDs\n")
        if not rows:
            return 0

        info = fetch_all([r["pmid"] for r in rows])

        counts, tag_counts, registries = Counter(), Counter(), Counter()
        updates, retracted = [], []
        for r in rows:
            s = info.get(r["pmid"])
            if not s:
                counts["no PubMed data"] += 1
                continue

            # level_key: only fill when missing; never overwrite a known one
            level = r.get("level_key") or ""
            if not level:
                inferred, tag = infer_level(s["pubtypes"], s.get("journal") or r.get("journal") or "")
                if inferred:
                    level = inferred
                    tag_counts[f"{tag}  ->  {inferred}"] += 1
                    counts["level_key inferred"] += 1
                else:
                    counts["level_key still unknown"] += 1

            registered, source = detect_preregistration(
                level, s["registry_ids"], r.get("abstract") or ""
            )
            # Curated authority documents name manufacturers by their nature and
            # carry hand-assigned scores — never COI-classified or penalised.
            if r.get("is_curated"):
                coi_status, coi_funder = "declared_none", ""
            else:
                coi_status, coi_funder = classify_coi(
                    s.get("coi_statement") or "", r.get("abstract") or ""
                )
            coi_flag = coi_status == COI_DECLARED_CONFLICT

            counts[f"coi:{coi_status}"] += 1
            if not s["medline_indexed"]:
                counts["not MEDLINE-indexed"] += 1
            if s["has_erratum"]:
                counts["correction / expression of concern"] += 1
            if s["has_retraction"]:
                counts["RETRACTED"] += 1
                retracted.append(r["pmid"])
            if registered:
                counts["pre-registered"] += 1
                registries[source] += 1

            updates.append((level or None, s["medline_indexed"], s["has_erratum"],
                            s["has_retraction"], source if registered else "",
                            coi_flag, coi_funder, coi_status, r["pmid"]))

        if tag_counts:
            print("\n[pubmed] TAG -> LEVEL (only for papers missing a level):")
            for k, n in tag_counts.most_common():
                print(f"    {n:5}   {k}")

        print("\n[pubmed] signal distribution:")
        for k, n in counts.most_common():
            print(f"    {n:5}   {k}")
        if registries:
            print("\n[pubmed] registries:")
            for k, n in registries.most_common():
                print(f"    {n:5}   {k}")
        if retracted:
            print(f"\n[pubmed] *** {len(retracted)} RETRACTED: {', '.join(retracted[:10])}")

        print(f"\n[pubmed] rows to update: {len(updates)}")
        if not args.apply:
            print("\n[pubmed] DRY RUN — re-run with --apply to write.")
            return 0

        # The fetch pass outlives a pooled connection; take a fresh one.
        try:
            cur.close(); conn.close()
        except Exception:
            pass
        conn = get_conn()
        cur = conn.cursor()
        psycopg2.extras.execute_batch(cur, """
            UPDATE endo_papers_rag
            SET level_key = COALESCE(%s, level_key),
                medline_indexed = %s, has_erratum = %s, has_retraction = %s,
                registry = %s, coi_flag = %s, coi_funder = %s, coi_status = %s
            WHERE pmid = %s;
        """, updates, page_size=500)
        conn.commit()
        print(f"\n[pubmed] APPLIED — {len(updates)} rows updated.")
        print("[pubmed] NEXT: python scripts/rescore_library.py --apply")
        return 0

    except Exception as e:
        conn.rollback()
        print(f"[pubmed] FAILED: {e}")
        return 1
    finally:
        try:
            cur.close(); conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
