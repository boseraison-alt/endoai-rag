"""
Re-fetch every library abstract from PubMed at full length and heal the ones
that were truncated at ingest.

WHY
---
Six ingest call sites stored `abstract[:1000]` or `abstract[:1200]`, so 1,342
of 2,350 library rows (57.1%) hold an abstract cut mid-word. Structured
abstracts put RESULTS and CONCLUSIONS last, and the measurement shows exactly
that: the word "conclusion" survives in 7.2% of the truncated rows against
39.3% of the whole ones.

That was survivable while the library block sent Claude nothing but a metadata
line. It is not survivable now: `app._scored_to_text` feeds these abstracts to
the synthesis, so a truncated row is a paper that stops before it says what it
found. The ingest sites are fixed separately; this heals what is already
stored.

WHAT IT DOES
------------
Re-fetches EVERY row (not only the ones with the truncation signature — a
1,199-character abstract that was cut at 1,200 leaves no signature), compares
against what is stored, and replaces any abstract that came back longer.
Never shortens: PubMed occasionally returns a shorter record for a paper whose
stored text came from a fuller source, and losing text is the failure this
script exists to reverse.

Rows whose abstract changed are RE-EMBEDDED, because the stored vector was
computed from text that is no longer what the row says.

    python scripts/repair_truncated_abstracts.py                 # dry run
    python scripts/repair_truncated_abstracts.py --apply         # write
    python scripts/repair_truncated_abstracts.py --apply --limit 50

Dry run is the default and prints: how many rows would change, mean length
before and after, and ten sampled before/after pairs chosen to show a
conclusion being restored. Apply only when that sample reads correctly.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2.extras
from defusedxml import ElementTree as DET

from endo_ai import NCBI_EUTILS_BASE, _ncbi_params, ncbi_get
from rag import get_conn

BATCH = 200               # PMIDs per efetch call; NCBI's documented ceiling
RUN_ID = "abstract_repair"
BACKUP_TABLE = "endo_papers_rag_abstract_backup"


def fetch_abstracts(pmids: list[str]) -> dict[str, str]:
    """{pmid: full abstract} from efetch XML.

    XML, not `rettype=abstract&retmode=text`: the text dump is what the live
    path parses heuristically (longest paragraph >= 200 chars), and a
    heuristic is the wrong tool when the whole point is fidelity. The XML
    gives the abstract as tagged elements, with the section LABELS that make a
    structured abstract readable.
    """
    params = _ncbi_params({"db": "pubmed", "id": ",".join(pmids),
                           "retmode": "xml"})
    resp = ncbi_get(f"{NCBI_EUTILS_BASE}/efetch.fcgi", params=params, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"efetch returned HTTP {resp.status_code}")

    out: dict[str, str] = {}
    root = DET.fromstring(resp.text)
    # PubmedBookArticle (StatPearls and friends) carries its abstract in the
    # same shape one level over. Iterating both means a book record is healed
    # like any other rather than silently skipped.
    for article in list(root.iter("PubmedArticle")) + list(root.iter("PubmedBookArticle")):
        # EXPLICIT paths, not `.//PMID`. A record's `CommentsCorrectionsList`
        # carries `<PMID>` children of its own — the PMIDs of the papers it
        # corrects or updates — and a loose descendant search picked one of
        # those up (observed: PMID 2019, which is not in this library at all).
        # A wrong id here would silently write one paper's abstract onto
        # another's row, which is the worst outcome this script could have.
        #
        # `is None`, never `or`: an ElementTree element with no children is
        # FALSY, so `find(a) or find(b)` silently discards a perfectly good
        # `<PMID>12345</PMID>` and falls through to the second path. That
        # turned 2,241 fetched abstracts into 72 usable ones on the first run.
        pmid_el = article.find("MedlineCitation/PMID")
        if pmid_el is None:
            pmid_el = article.find("BookDocument/PMID")
        if pmid_el is None or not (pmid_el.text or "").strip():
            continue
        pmid = pmid_el.text.strip()
        parts: list[str] = []
        for node in article.iter("AbstractText"):
            text = "".join(node.itertext()).strip()
            if not text:
                continue
            label = (node.get("Label") or "").strip()
            parts.append(f"{label}: {text}" if label else text)
        if parts:
            out[pmid] = " ".join(parts).strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write changes (default: dry run)")
    ap.add_argument("--limit", type=int, default=None,
                    help="only consider the first N rows (for a smoke run)")
    ap.add_argument("--samples", type=int, default=10)
    args = ap.parse_args()

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""SELECT pmid, title, coalesce(abstract,'') AS abstract
                   FROM endo_papers_rag ORDER BY pmid""")
    rows = cur.fetchall()
    if args.limit:
        rows = rows[:args.limit]
    stored = {r["pmid"]: r for r in rows}
    print(f"[repair] {len(rows)} library rows to re-fetch, {BATCH} per efetch call")

    fetched: dict[str, str] = {}
    pmids = [r["pmid"] for r in rows]
    t0 = time.time()
    for i in range(0, len(pmids), BATCH):
        chunk = pmids[i:i + BATCH]
        try:
            got = fetch_abstracts(chunk)
        except Exception as e:                      # keep going; report at the end
            print(f"  [repair] batch {i // BATCH + 1} FAILED: {type(e).__name__}: {e}")
            continue
        fetched.update(got)
        print(f"  [repair] batch {i // BATCH + 1}/{(len(pmids) + BATCH - 1) // BATCH}: "
              f"{len(got)}/{len(chunk)} abstracts  ({len(fetched)} total, "
              f"{time.time() - t0:.0f}s)")

    # ── What would change ────────────────────────────────────────────────
    # LONGER only. PubMed sometimes returns a shorter record than what an
    # earlier source supplied, and this script must never lose text.
    changes = []
    stray = []
    for pmid, new in fetched.items():
        row = stored.get(pmid)
        if row is None:
            # Belt to the braces above: an id this run did not ask for can
            # never reach an UPDATE.
            stray.append(pmid)
            continue
        old = row["abstract"]
        if new and len(new) > len(old):
            changes.append((pmid, old, new))
    if stray:
        print(f"[repair] WARNING: efetch returned {len(stray)} PMIDs this run did "
              f"not request ({stray[:5]}) — ignored, not written.")

    missing = [p for p in pmids if p not in fetched]
    no_abstract = [p for p in missing if not stored[p]["abstract"]]

    def mean(xs):
        return (sum(xs) / len(xs)) if xs else 0.0

    before_all = [len(r["abstract"]) for r in rows]
    after_all = [len(fetched.get(p, "")) if (p in fetched and
                 len(fetched[p]) > len(stored[p]["abstract"]))
                 else len(stored[p]["abstract"]) for p in pmids]

    print(f"\n[repair] rows that would change : {len(changes)}")
    print(f"[repair] mean abstract length    : {mean(before_all):.0f} -> {mean(after_all):.0f} chars")
    print(f"[repair] mean over changed rows  : "
          f"{mean([len(o) for _p, o, _n in changes]):.0f} -> "
          f"{mean([len(n) for _p, _o, n in changes]):.0f} chars")
    print(f"[repair] PubMed returned nothing : {len(missing)} "
          f"(of which {len(no_abstract)} have no stored abstract either)")

    # Sample rows where a CONCLUSION is restored — the specific loss this
    # repair exists to reverse. Random, not top-N: a top-N sample sorted by
    # gain flatters itself (the 1.4/1.5 migrations learned this the hard way).
    restored = [c for c in changes
                if "conclusion" in c[2].lower() and "conclusion" not in c[1].lower()]
    print(f"[repair] conclusion restored in  : {len(restored)} rows")
    import random
    rnd = random.Random(20260831)
    for pmid, old, new in rnd.sample(restored, min(args.samples, len(restored))):
        print(f"\n--- PMID {pmid}  {len(old)} -> {len(new)} chars")
        print(f"    BEFORE ...{old[-110:]!r}")
        print(f"    AFTER  ...{new[len(old) - 40:len(old) + 220]!r}")

    if not args.apply:
        print(f"\n[repair] DRY RUN — nothing written. Re-run with --apply once the "
              f"sample above reads correctly.")
        cur.close()
        return 0

    if not changes:
        print("\n[repair] nothing to apply.")
        cur.close()
        return 0

    # ── Apply ────────────────────────────────────────────────────────────
    # Backup table first. The first Cochrane migration did not take one and the
    # identity of its 109 affected rows is unrecoverable.
    print(f"\n[repair] backing up {len(changes)} rows to {BACKUP_TABLE} ...")
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {BACKUP_TABLE} (
            pmid TEXT, abstract TEXT, run_id TEXT, backed_up_at TIMESTAMP DEFAULT NOW()
        );""")
    psycopg2.extras.execute_batch(cur, f"""
        INSERT INTO {BACKUP_TABLE} (pmid, abstract, run_id) VALUES (%s, %s, %s)""",
        [(p, o, RUN_ID) for p, o, _n in changes])

    print(f"[repair] writing {len(changes)} abstracts ...")
    psycopg2.extras.execute_batch(cur, """
        UPDATE endo_papers_rag SET abstract = %s WHERE pmid = %s""",
        [(n, p) for p, _o, n in changes])
    conn.commit()

    # ── Re-embed every changed row ───────────────────────────────────────
    # The stored vector was computed from text the row no longer holds. The
    # embedding text is `title\nabstract`, which is what `rag.learn_from_live_results`
    # (the live write-back path) already uses — so this converges the older
    # corpus-builder rows, which used `title + abstract[:400]`, onto the
    # convention the library is already accumulating rather than inventing a
    # third one. `embed()` caps at 2000 chars internally.
    from rag import embed
    print(f"[repair] re-embedding {len(changes)} rows ...")
    done = 0
    for pmid, _old, new in changes:
        vec = embed(f"{stored[pmid]['title'] or ''}\n{new}")
        cur.execute("UPDATE endo_papers_rag SET embedding = %s::vector WHERE pmid = %s",
                    (vec, pmid))
        done += 1
        if done % 200 == 0:
            conn.commit()
            print(f"  [repair] re-embedded {done}/{len(changes)}")
    conn.commit()
    print(f"[repair] re-embedded {done} rows "
          f"({'MATCHES' if done == len(changes) else 'MISMATCH against'} "
          f"{len(changes)} changed rows)")

    cur.close()
    print(f"\n[repair] done. Backup run_id = {RUN_ID}. "
          f"Rescore and invalidate the answer cache next.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
