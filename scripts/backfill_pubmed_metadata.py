"""
Single-pass PubMed metadata backfill for the RAG library.

Re-fetching ~1,900 PMIDs is the expensive step, so ONE efetch XML call per
batch supplies everything we want from it:

    PublicationTypeList     -> level_key (evidence design)
    MedlineCitation Status  -> medline_indexed
    CommentsCorrectionsList -> has_erratum / has_retraction
                               (ErratumIn, CorrectedandRepublishedIn,
                                ExpressionOfConcernIn, RetractionIn)
                            -> superseded_by (UpdateIn)
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
import requests
from endo_ai import (_merge_corrections_and_registries, detect_preregistration,
                     classify_coi, COI_DECLARED_CONFLICT,
                     NCBI_EUTILS_BASE, _ncbi_params)
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


def _merge_update_relations(ids: list, metadata: dict) -> None:
    """Populate `superseded_by` from CommentsCorrections RefType="UpdateIn".

    Cochrane reviews are versioned. Each update is a brand-new PubMed record and
    the superseded versions are never withdrawn, retracted or retitled — the
    ONLY machine-readable sign that a record is out of date is this link.

    Direction matters and is easy to invert. Verified against the three
    published versions of "Single versus multiple visits for endodontic
    treatment of permanent teeth" (CD005296):

        27905673 (2016 version, pub3)
          <CommentsCorrections RefType="UpdateOf"> PMID 17943848  <- predecessor
          <CommentsCorrections RefType="UpdateIn"> PMID 36512807  <- SUCCESSOR
        36512807 (2022 version, pub4)
          <CommentsCorrections RefType="UpdateOf"> PMID 27905673  <- predecessor
          (no UpdateIn — this is the current version)

    So UpdateIn is carried by the OLDER record and names the newer one, which
    is exactly the value we store. UpdateOf points backwards and must be
    ignored: acting on it would flag every CURRENT review as stale and leave
    the obsolete ones in place — the precise inversion of the feature.

    Lives here rather than in endo_ai._merge_corrections_and_registries only
    because that module is owned elsewhere; it costs one extra efetch per batch
    (~10 requests for the whole library), not one per paper.

    Mutates `metadata` in place. Never raises on a per-record parse problem.
    Returns True when PubMed actually answered — the caller needs to tell
    "no successor" apart from "we never found out", because writing the former
    when the latter is true would un-flag a stale review.
    """
    if not ids:
        return True
    from defusedxml import ElementTree as DET

    resp = requests.get(
        f"{NCBI_EUTILS_BASE}/efetch.fcgi",
        params=_ncbi_params({"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}),
        timeout=25,
    )
    if resp.status_code != 200:
        return False
    root = DET.fromstring(resp.text)

    for article in root.iter("PubmedArticle"):
        pmid_el = article.find(".//MedlineCitation/PMID")
        if pmid_el is None or not pmid_el.text:
            continue
        pmid = pmid_el.text.strip()
        entry = metadata.get(pmid)
        if entry is None:
            continue

        successors = []
        for cc in article.iter("CommentsCorrections"):
            if (cc.get("RefType") or "").lower() != "updatein":
                continue
            # The referenced record's PMID is a <PMID> CHILD of
            # CommentsCorrections (not <RefPMID>, and not the citation's own
            # PMID, which hangs directly off MedlineCitation). PubMed omits it
            # when the successor is not itself indexed — RefSource-only entries
            # give us nothing to point at, so they are skipped.
            ref = cc.find("PMID")
            if ref is None or not (ref.text or "").strip():
                continue
            ref_pmid = ref.text.strip()
            if ref_pmid.isdigit() and ref_pmid != pmid:
                successors.append(ref_pmid)

        if successors:
            # A record normally names exactly one successor. When PubMed lists
            # several, the highest PMID is the most recently indexed one.
            entry["superseded_by"] = max(successors, key=int)

    return True


def _resolve_chains(info: dict) -> int:
    """Follow superseded_by to the END of each version chain.

    CD005296 exists as 2007 -> 2016 -> 2022, and each record names only its
    immediate successor. Left unresolved, the 2007 row would point a clinician
    at the 2016 version, which is itself obsolete. Returns how many pointers
    were advanced. Cycle-guarded — a malformed pair of records must not hang
    the backfill.
    """
    advanced = 0
    for pmid, entry in info.items():
        target = entry.get("superseded_by") or ""
        seen = {pmid}
        hops = 0
        while target and target not in seen and hops < 10:
            seen.add(target)
            nxt = (info.get(target) or {}).get("superseded_by") or ""
            if not nxt:
                break
            target, hops = nxt, hops + 1
        # A cycle can walk back round to the record itself; a row must never
        # declare itself its own replacement.
        if target and target != pmid and target != (entry.get("superseded_by") or ""):
            entry["superseded_by"] = target
            advanced += 1
    return advanced


def fetch_all(pmids: list) -> dict:
    """One efetch XML call per batch; returns {pmid: {...signals...}}."""
    out = {}
    for i in range(0, len(pmids), BATCH_SIZE):
        chunk = pmids[i:i + BATCH_SIZE]
        meta = {p: {"medline_indexed": True, "has_erratum": False,
                    "has_retraction": False, "registry_ids": [],
                    "coi_statement": "", "pubtypes": [],
                    "superseded_by": ""} for p in chunk}
        try:
            _merge_corrections_and_registries(chunk, meta)
        except Exception as e:
            print(f"  batch {i//BATCH_SIZE} failed: {e}")
        time.sleep(SLEEP_S)
        try:
            ok = _merge_update_relations(chunk, meta)
        except Exception as e:
            print(f"  batch {i//BATCH_SIZE} update-relations failed: {e}")
            ok = False
        if not ok:
            # UNKNOWN, not "current". None tells the writer to leave whatever
            # is already stored alone rather than clearing a real supersession
            # because one efetch happened to fail.
            print(f"  batch {i//BATCH_SIZE}: supersession unknown, leaving stored values")
            for m in meta.values():
                m["superseded_by"] = None
        out.update(meta)
        print(f"  fetched {min(i+BATCH_SIZE, len(pmids))}/{len(pmids)}")
        time.sleep(SLEEP_S)
    _resolve_chains(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only-superseded", action="store_true",
                    help="write ONLY the superseded_by column, leaving level_key / "
                         "score / COI columns untouched (safe alongside a "
                         "concurrent rescore)")
    args = ap.parse_args()

    setup_table()

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""
            SELECT pmid, title, year, journal, abstract, level_key, is_curated
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
        updates, retracted, superseded = [], [], []
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
            # None means "we could not find out" — passed through to SQL as
            # NULL so COALESCE leaves the stored value untouched.
            newer = s.get("superseded_by")
            if newer:
                counts["SUPERSEDED by a newer version"] += 1
                superseded.append((r["pmid"], newer, r.get("year"), r.get("title") or ""))

            updates.append((level or None, s["medline_indexed"], s["has_erratum"],
                            s["has_retraction"], source if registered else "",
                            coi_flag, coi_funder, coi_status, newer, r["pmid"]))

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
        if superseded:
            print(f"\n[pubmed] *** {len(superseded)} SUPERSEDED "
                  f"(a newer version of the same review is indexed):")
            for old, new, yr, title in sorted(superseded, key=lambda x: (x[3], x[2] or 0)):
                print(f"    {old}  ({yr})  ->  {new}   {title[:78]}")

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
        if args.only_superseded:
            # Narrow write: one column, and only for the rows whose value
            # actually changes. Leaves level_key / COI / registry alone so this
            # can run while the rescorer holds opinions about the same rows.
            narrow = [(u[8], u[9], u[8]) for u in updates if u[8] is not None]
            psycopg2.extras.execute_batch(cur, """
                UPDATE endo_papers_rag
                SET superseded_by = %s
                WHERE pmid = %s AND COALESCE(superseded_by, '') IS DISTINCT FROM %s;
            """, narrow, page_size=500)
            conn.commit()
            print(f"\n[pubmed] APPLIED (superseded_by only) — "
                  f"{len(superseded)} row(s) flagged as superseded.")
            return 0

        psycopg2.extras.execute_batch(cur, """
            UPDATE endo_papers_rag
            SET level_key = COALESCE(%s, level_key),
                medline_indexed = %s, has_erratum = %s, has_retraction = %s,
                registry = %s, coi_flag = %s, coi_funder = %s, coi_status = %s,
                -- NULL = "not determined this run"; keep what is stored.
                superseded_by = COALESCE(%s, superseded_by)
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
