"""
Re-derive `level_key` for the top-tier library rows from PubMed's
PublicationTypeList instead of guessing.

WHY THIS EXISTS
---------------
`COCHRANE_TERM` used to be "Cochrane Review[pt]", a publication type PubMed
does not have. It silently translated to

    ("cochran" OR "cochrane") AND "Review"[Publication Type]

so ANY review that merely mentioned searching the Cochrane Library landed in
the top tier. `scripts/fix_cochrane_tier.py --apply` then demoted 109 such
rows `cochrane -> level1` in one blanket UPDATE — which assumed every one of
them was a systematic review. A narrative review sitting at a false Level I
is still wrong, just less loudly.

SCOPE — deliberately a SUPERSET of those 109
--------------------------------------------
fix_cochrane_tier.py overwrote level_key in place with no backup and no audit
trail, so the individual 109 PMIDs are NOT recoverable and nothing
distinguishes them from rows that were already level1. This script therefore
reclassifies EVERY non-curated, numeric-PMID row currently at `level1` or
`cochrane`. That is more correct anyway: the same "a review is a review"
conflation can exist on rows the Cochrane bug never touched. The `cochrane`
rows are included as a correctness check — they are journal-identified, so
they must all come back as evidence syntheses and stay put.

MEDLINE AUTHORITY GATE — the part that matters most
---------------------------------------------------
"Systematic Review"[pt] and "Meta-Analysis"[pt] are assigned by NLM indexers
during MEDLINE indexing. Publisher-supplied records that have not been
MEDLINE-indexed (MedlineCitation Status != "MEDLINE" — most MDPI/Frontiers
records, and nearly everything from the last 18 months) carry only
"Journal Article" and "Review", NO MATTER WHAT THE PAPER ACTUALLY IS.

On this library that is not a corner case. A naive pubtype-only mapping
demoted 63 rows to level5, of which 53 were non-MEDLINE and 45 had titles
literally reading "... : A Systematic Review". Destroying 45 genuine
systematic reviews is a far worse outcome than the bug being fixed.

So: for a record that is NOT MEDLINE-indexed, a bare "Review" publication
type is NOT evidence of a narrative review. Those rows are reported as
unverifiable and left alone. A positively-asserted strong type (Systematic
Review / Meta-Analysis / RCT) is still trusted — an incomplete list omits
types, it does not invent them.

TARGET TIERS
------------
  journal is Cochrane Database        -> cochrane   (journal, never pubtype)
  Meta-Analysis / Network Meta-Analysis
    / Systematic Review               -> level1
  Guideline / Practice Guideline
    / Consensus Statement / Consensus
    Development Conference            -> level1     (see note)
  Randomized Controlled Trial         -> level1     (guard, see note)
  Case Reports                        -> level4     (precedence, see note)
  Review only, MEDLINE-indexed        -> level5     (narrative review)
  Review only, NOT MEDLINE-indexed    -> unchanged, reported
  Scoping Review only                 -> unchanged, reported (see note)
  anything else                       -> unchanged, reported

Why guidelines map to `level1` rather than a tier of their own: this project
has no separate guideline tier and one must not be invented. Anything absent
from `endo_ai.TIER_ORDER` is invisible to `_build_evidence_context()`, so a
new key would silently drop those papers before they ever reach Claude. The
project's existing convention for position statements and guidelines is
`level_key='level1'` — see ingest_aae_guidelines.py, which writes exactly
that for the 16 AAE/ESE documents ("guidelines are treated as top-tier
evidence"), and scripts/backfill_pubmed_metadata.py::PUBTYPE_TO_LEVEL, which
already maps "practice guideline"/"guideline"/"consensus development
conference" -> level1 for PubMed records. `is_curated` is NOT set here: it
means "hand-curated authority document with a hand-assigned score that
rescore_library.py must never recompute", which is not true of a
PubMed-indexed guideline.

Why RCT is guarded: Level I is RCTs *and* SRs (endo_ai.LEVEL_1_TERMS). A
record tagged both "Randomized Controlled Trial" and "Review" must not be
read as a narrative review and dumped into level5.

Why Case Reports outranks Review: a "case report and literature review" is a
case report. backfill_pubmed_metadata.py::PUBTYPE_TO_LEVEL already orders
"case reports" (level4) ahead of "review" (level5); this matches it.

Why Scoping Review is NOT auto-mapped: a scoping review charts the extent of
a literature without effect estimates or quality appraisal, so it is neither
Level I nor plainly Level V, and this project has never assigned it a tier.
Guessing one is exactly the failure mode being repaired, so these are
reported for a human instead.

THE GUIDELINE NON-DEMOTION GUARD
--------------------------------
NLM does not reliably tag society guidelines in dental journals with
"Guideline"[pt]: the IADT trauma guidelines (PMID 32472740) carry only
["Journal Article", "Review"], which the pubtype rule alone would demote to
Level V — expert opinion. The guard only ever DECLINES to demote: when a
MEDLINE-indexed record whose sole design type is "Review" has a title that
reads as an authoritative guideline / position statement, the row is left at
its current tier and reported for manual review. It never promotes anything
and never invents a tier, so a false positive costs a line in a report.

Changing level_key changes the design axis (LEVEL_SCORES 80 -> 10 for a
demotion to level5) at 39% weight, so the stored score is stale afterwards:

    python scripts/rescore_library.py --apply

must be run immediately after --apply. Dry run by default.

Usage:
    python scripts/reclassify_by_pubtype.py                  # dry run
    python scripts/reclassify_by_pubtype.py --apply          # write
    python scripts/reclassify_by_pubtype.py --cache pt.json  # reuse a fetch
"""

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2.extras

from endo_ai import _COCHRANE_JOURNAL_HINTS, _merge_corrections_and_registries
from rag import get_conn

BATCH_SIZE = 200      # same batching as scripts/backfill_pubmed_metadata.py
SLEEP_S    = 0.4      # ~2.5 req/s — safe without an NCBI API key

BACKUP_TABLE = "endo_papers_rag_pubtype_backup"
SOURCE_TIERS = ("level1", "cochrane")

# Publication types that put / keep a row at level1, strongest signal first.
# Matched case-insensitively against PubMed's PublicationTypeList.
LEVEL1_PUBTYPES = (
    "meta-analysis",
    "network meta-analysis",
    "systematic review",
    "practice guideline",
    "guideline",
    "consensus development conference",
    "consensus development conference, nih",
    "consensus statement",
    "randomized controlled trial",
)

# Beats a co-occurring "Review": a case report with a literature review is a
# case report. Mirrors PUBTYPE_TO_LEVEL in backfill_pubmed_metadata.py.
CASE_PUBTYPES = ("case reports",)

# Present but NOT auto-mapped — reported for a human instead of guessed at.
UNMAPPED_SYNTHESIS_PUBTYPES = ("scoping review",)

# Alone, means a narrative review -> level5, but only on a MEDLINE-indexed
# record (see the MEDLINE authority gate above).
NARRATIVE_PUBTYPES = ("review",)

# Titles that read as an authoritative guideline / position statement. Used
# ONLY to decline an automatic demotion, never to promote. NLM omits
# "Guideline"[pt] from most dental society guidelines.
GUIDELINE_TITLE_RE = re.compile(
    r"\b(guidelines?|position statement|consensus statement|"
    r"consensus report|clinical recommendations?)\b",
    re.IGNORECASE,
)


def map_pubtypes_to_tier(pubtypes, journal: str = "",
                         medline_indexed: bool = True, title: str = ""):
    """Pure function: PubMed publication types -> (level_key, reason).

    Returns (None, reason) whenever the record carries no publication type
    this project can read as an evidence design, or carries one that is not
    trustworthy on this record. The caller must leave such rows alone and
    report them rather than guessing a tier.

    `journal` is checked first because the `cochrane` tier is defined by the
    journal, not by any publication type — a Cochrane review's pubtypes look
    like any other systematic review's.
    """
    jl = (journal or "").lower()
    if any(h in jl for h in _COCHRANE_JOURNAL_HINTS):
        return "cochrane", "journal:cochrane database"

    lowered = {str(p).strip().lower() for p in (pubtypes or []) if str(p).strip()}
    if not lowered:
        return None, "no publication types returned by PubMed"

    for tag in LEVEL1_PUBTYPES:
        if tag in lowered:
            return "level1", tag

    for tag in CASE_PUBTYPES:
        if tag in lowered:
            return "level4", tag

    for tag in UNMAPPED_SYNTHESIS_PUBTYPES:
        if tag in lowered:
            return None, f"{tag} — project defines no tier for this design"

    for tag in NARRATIVE_PUBTYPES:
        if tag in lowered:
            # NLM assigns "Systematic Review"/"Meta-Analysis" only at MEDLINE
            # indexing. On a publisher-supplied record a bare "Review" proves
            # nothing, so refuse to demote on it.
            if not medline_indexed:
                return None, ("review pubtype on a record that is NOT "
                              "MEDLINE-indexed — not authoritative")
            if GUIDELINE_TITLE_RE.search(title or ""):
                return None, ("review pubtype but the title reads as a "
                              "guideline / position statement")
            return "level5", f"{tag} (narrative)"

    return None, "no usable publication type"


def fetch_pubtypes(pmids: list) -> dict:
    """{pmid: {"pubtypes": [...], "medline_indexed": bool}} via efetch.

    Reuses endo_ai._merge_corrections_and_registries, which already does the
    XML efetch through _ncbi_params() (tool/email/api_key) and parses both
    PublicationTypeList and MedlineCitation/@Status. No new HTTP layer here.
    """
    out = {}
    for i in range(0, len(pmids), BATCH_SIZE):
        chunk = pmids[i:i + BATCH_SIZE]
        meta = {p: {"medline_indexed": True, "has_erratum": False,
                    "has_retraction": False, "registry_ids": [],
                    "coi_statement": "", "pubtypes": []} for p in chunk}
        try:
            _merge_corrections_and_registries(chunk, meta)
        except Exception as e:
            print(f"  batch {i // BATCH_SIZE} failed: {e}")
        for p, m in meta.items():
            # A record absent from the response keeps the seeded defaults and
            # so has no pubtypes — it lands in the "reported, untouched"
            # bucket rather than being mapped off stale information.
            out[p] = {"pubtypes": m["pubtypes"],
                      "medline_indexed": bool(m["medline_indexed"])}
        print(f"  fetched {min(i + BATCH_SIZE, len(pmids))}/{len(pmids)}")
        time.sleep(SLEEP_S)
    return out


def _print_table(title: str, counter: Counter, total: int = 0):
    print(f"\n{title}")
    for k, n in counter.most_common():
        print(f"    {n:5}   {k}")
    if total:
        print(f"    {'-' * 5}")
        print(f"    {total:5}   TOTAL")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write the change (default: dry run)")
    ap.add_argument("--cache", default="",
                    help="JSON file of fetched records — read if it exists, "
                         "written after a fetch, so --apply reclassifies the "
                         "exact records the dry run reported on")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""
            SELECT pmid, title, journal, year, level_key,
                   ROUND(COALESCE(score, 0)::numeric, 1) AS score
              FROM endo_papers_rag
             WHERE level_key = ANY(%s)
               AND COALESCE(is_curated, FALSE) = FALSE
               AND pmid ~ '^[0-9]+$'
             ORDER BY score DESC NULLS LAST, pmid;
        """, (list(SOURCE_TIERS),))
        rows = cur.fetchall()
        if args.limit:
            rows = rows[:args.limit]

        in_scope = Counter(r["level_key"] for r in rows)
        print(f"[reclassify] scope: every non-curated numeric-PMID row at "
              f"{' or '.join(SOURCE_TIERS)}")
        for k, n in sorted(in_scope.items()):
            print(f"             {n:5}   currently {k}")
        print(f"             {len(rows):5}   TOTAL in scope")
        print("[reclassify] NOTE: the 109 rows fix_cochrane_tier.py demoted are "
              "not individually\n             recoverable (in-place UPDATE, no "
              "audit trail). This scope is a superset.")
        if not rows:
            return 0

        cur.execute("""
            SELECT COUNT(*) AS n FROM endo_papers_rag
             WHERE level_key = ANY(%s)
               AND (COALESCE(is_curated, FALSE) OR pmid !~ '^[0-9]+$');
        """, (list(SOURCE_TIERS),))
        print(f"[reclassify] excluded (curated / non-numeric PMID, hand-assigned "
              f"scores): {cur.fetchone()['n']}")

        cache_path = Path(args.cache) if args.cache else None
        fetched = {}
        if cache_path and cache_path.exists():
            fetched = json.loads(cache_path.read_text(encoding="utf-8"))
            print(f"\n[reclassify] loaded {len(fetched)} cached record(s) from "
                  f"{cache_path}")
        missing = [r["pmid"] for r in rows if r["pmid"] not in fetched]
        if missing:
            print(f"\n[reclassify] efetch PublicationTypeList for {len(missing)} PMIDs")
            fetched.update(fetch_pubtypes(missing))
            if cache_path:
                cache_path.write_text(json.dumps(fetched), encoding="utf-8")
                print(f"[reclassify] cached to {cache_path}")

        moves        = Counter()      # "old -> new"
        reasons      = Counter()      # pubtype -> target, for every row
        held         = Counter()      # why a row was left alone
        by_journal   = defaultdict(Counter)
        unchanged    = 0
        untouched    = []
        updates, demoted_rows = [], []
        medline_n    = 0

        for r in rows:
            rec = fetched.get(r["pmid"]) or {}
            pts = rec.get("pubtypes") or []
            mi  = bool(rec.get("medline_indexed", True))
            medline_n += 1 if mi else 0
            new, reason = map_pubtypes_to_tier(
                pts, r.get("journal") or "", mi, r.get("title") or ""
            )
            if new is None:
                untouched.append((r, reason, mi))
                held[reason] += 1
                continue
            reasons[f"{reason}  ->  {new}"] += 1
            old = r["level_key"]
            if new == old:
                unchanged += 1
                continue
            moves[f"{old}  ->  {new}"] += 1
            by_journal[f"{old}  ->  {new}"][r.get("journal") or "(none)"] += 1
            updates.append((new, r["pmid"]))
            if new in ("level4", "level5"):
                demoted_rows.append((r, new))

        print(f"[reclassify] MEDLINE-indexed in scope: {medline_n} / {len(rows)} "
              f"({len(rows) - medline_n} publisher-supplied, pubtypes not authoritative)")

        print("\n" + "=" * 72)
        print("SPLIT (before any write)")
        print("=" * 72)
        _print_table("[reclassify] publication type -> target tier "
                     "(all classifiable rows):", reasons,
                     total=sum(reasons.values()))
        _print_table("[reclassify] TIER CHANGES:", moves, total=sum(moves.values()))
        _print_table("[reclassify] LEFT ALONE — no usable / non-authoritative "
                     "publication type:", held, total=sum(held.values()))
        print(f"\n[reclassify] unchanged (already the right tier) : {unchanged}")
        print(f"[reclassify] changing tier                      : {len(updates)}")
        print(f"[reclassify] left alone, reported               : {len(untouched)}")

        if untouched:
            print("\n[reclassify] rows left alone (REVIEW THESE BY HAND):")
            for r, reason, mi in untouched:
                print(f"    {r['score']:>5}  {r['pmid']}  {r['level_key']:<8} "
                      f"medline={str(mi):<5} {(r.get('journal') or '')[:24]:<24} "
                      f"{reason[:46]:<46} {(r.get('title') or '')[:40]}")

        for move, journals in sorted(by_journal.items()):
            _print_table(f"[reclassify] per-journal breakdown — {move} "
                         f"({sum(journals.values())} rows):", journals)

        if demoted_rows:
            print("\n[reclassify] 15 HIGHEST-SCORING DEMOTIONS "
                  "(leaving the top tier):")
            for r, new in sorted(demoted_rows,
                                 key=lambda x: float(x[0]["score"] or 0),
                                 reverse=True)[:15]:
                print(f"    {r['score']:>5}  {r['pmid']}  {r['year']}  -> {new}  "
                      f"{(r.get('journal') or '')[:30]:<30} "
                      f"{(r.get('title') or '')[:66]}")

        if not args.apply:
            print("\n[reclassify] DRY RUN — re-run with --apply to write, then "
                  "python scripts/rescore_library.py --apply")
            return 0

        if not updates:
            print("\n[reclassify] nothing to write")
            return 0

        # ── BACKUP FIRST ────────────────────────────────────────────────
        # fix_cochrane_tier.py overwrote level_key with no way back. This
        # migration is reversible: pmid plus the level_key and score as they
        # stood immediately before the UPDATE, for every row in scope (not
        # only the changed ones), so a restore is a single UPDATE ... FROM.
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {BACKUP_TABLE} (
                pmid          TEXT NOT NULL,
                old_level_key TEXT,
                old_score     REAL,
                backed_up_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                run_id        TEXT NOT NULL
            );
        """)
        run_id = time.strftime("%Y%m%dT%H%M%S")
        psycopg2.extras.execute_batch(cur, f"""
            INSERT INTO {BACKUP_TABLE} (pmid, old_level_key, old_score, run_id)
            VALUES (%s, %s, %s, %s);
        """, [(r["pmid"], r["level_key"], float(r["score"] or 0), run_id)
              for r in rows], page_size=500)
        conn.commit()
        print(f"\n[reclassify] backed up {len(rows)} row(s) into {BACKUP_TABLE} "
              f"(run_id={run_id})")
        print(f"[reclassify] restore with:\n"
              f"    UPDATE endo_papers_rag t\n"
              f"       SET level_key = b.old_level_key, score = b.old_score\n"
              f"      FROM {BACKUP_TABLE} b\n"
              f"     WHERE b.pmid = t.pmid AND b.run_id = '{run_id}';")

        psycopg2.extras.execute_batch(cur, """
            UPDATE endo_papers_rag SET level_key = %s WHERE pmid = %s;
        """, updates, page_size=500)
        conn.commit()
        print(f"[reclassify] APPLIED — {len(updates)} level_key(s) rewritten.")

        # Cached answers embed their own paper list and tier ordering, so they
        # would keep serving the old tiering until their TTL expired.
        cur.execute("DELETE FROM query_cache;")
        conn.commit()
        print(f"[reclassify] invalidated {cur.rowcount} cached answer(s).")
        print("[reclassify] NEXT: python scripts/rescore_library.py --apply")
        return 0

    except Exception as e:
        conn.rollback()
        print(f"[reclassify] FAILED: {e}")
        return 1
    finally:
        try:
            cur.close(); conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
