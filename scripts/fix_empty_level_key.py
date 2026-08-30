"""
WORKLIST 4.7: give the library rows that carry no `level_key` a tier.

WHY THIS EXISTS
---------------
14 rows sit at level_key = ''. `level_key` drives the design axis at 39% of the
score, and app.py bands an unlabelled row to level5 ("An unlabelled paper has an
UNKNOWN design. Placing it in the weakest tier is the safe direction"), so these
rows are safe but silently under-weighted: an eight-year retrospective cohort of
206 teeth is handed to Claude labelled "Level V — Expert Opinion". They are also
skipped by scripts/rescore_library.py, which only rescores rows with a non-empty
level_key, so their stored scores are frozen at ingest time.

THE CLASSIFICATION LADDER — the order is the whole point
--------------------------------------------------------
1. MEDLINE publication types, but ONLY where MedlineCitation/@Status ==
   "MEDLINE". PublicationTypeList is assigned by NLM indexers; publisher-supplied
   records carry only ["Journal Article", "Review"] regardless of what the paper
   is. A previous pass keyed on pubtypes alone and would have demoted 45 genuine
   systematic reviews to Level V. This script REUSES
   reclassify_by_pubtype.map_pubtypes_to_tier() rather than writing a second
   mapping, so that gate cannot drift between the two migrations.

2. Title/abstract cues, for rows rung 1 cannot settle.

3. level5 plus a "needs review" note, where neither settles it.

WHAT RUNG 1 ACTUALLY RETURNED (measured 2026-08-30, all 14 rows)
-----------------------------------------------------------------
Nothing. Not one row. 13 of the 14 ARE MEDLINE-indexed, and every single one
carries only ['Journal Article'] (three of them plus 'Scoping Review', three
plus "Research Support, Non-U.S. Gov't"). NLM assigned no design publication
type to any of them.

That sharpens the recorded lesson rather than repeating it. MEDLINE status tells
you the publication type list is AUTHORITATIVE. It does not tell you the list is
INFORMATIVE. For observational endodontic work NLM routinely assigns no design
type at all, so a migration gated on "is it MEDLINE-indexed?" still classifies
nothing here. Rung 1 is kept anyway: it costs one efetch, it is the rung that
would fire on an RCT or a meta-analysis, and removing it would be removing the
guard, not the dead code.

RUNG 2 — precision over recall, and two guards that only ever DECLINE
----------------------------------------------------------------------
No text-based design classifier existed in this codebase to reuse: LEVEL_*_TERMS
are PubMed query filters, PUBTYPE_TO_LEVEL and map_pubtypes_to_tier() both key on
publication type, and is_review_design() only answers a yes/no about synthesis.
So the cue rules below are new. They follow the precision-first convention
WORKLIST 1.4 sets for the in-vitro classifier: a cue must be SELF-REFERENTIAL
("this retrospective study", "a retrospective cohort study" in the title), not a
mention of a design somewhere in the text.

  COMMENTARY GUARD. Evidence-Based Dentistry and the Journal of Evidence-Based
  Dental Practice publish structured CRITICAL SUMMARIES of other people's trials.
  Their abstracts open "DESIGN: The study is a prospective, double-blinded
  randomised control trial ..." — describing the summarised trial, not the paper
  in hand. PMID 39885347 in this very batch is one, and a naive
  "randomised controlled trial" cue would have installed a one-page commentary at
  Level I. This is bug class (c) in a new costume: metadata read off text that
  belongs to a different record. The guard sends these to level5 and never
  promotes anything.

  NON-HUMAN GUARD. PMID 40683315 is a 25-year retrospective cohort — of dogs, in
  the Journal of the American Veterinary Medical Association. The design cue is
  real; the TIER would be a lie, because this hierarchy ranks human clinical
  evidence and level3a outranks a human case series. There is no animal tier and
  WORKLIST 1.4 has not been done, so inventing one here is out of scope. Animal
  studies fall to rung 3 and are reported for a human.

  SCOPING REVIEWS are deliberately NOT auto-mapped, matching
  reclassify_by_pubtype.py: a scoping review charts a literature without effect
  estimates or quality appraisal, so it is neither Level I nor plainly Level V.
  They fall to rung 3. NOTE FOR WHOEVER PICKS THIS UP: 8 other scoping reviews in
  this library sit at level1 (HANDOVER open items). Putting these at level5 is
  the safe direction and preserves their current effective banding, but the two
  populations now disagree and one of them is wrong. That is a decision for RB,
  not for this script.

Changing level_key changes the design axis, so the stored score is stale
afterwards — and these rows were never rescored at all:

    python scripts/rescore_library.py --apply

must be run immediately after --apply.

Dry run by default. Idempotent: after --apply the row set is empty and a re-run
reports nothing to do.

Usage:
    python scripts/fix_empty_level_key.py                    # dry run
    python scripts/fix_empty_level_key.py --apply            # write
    python scripts/fix_empty_level_key.py --cache pt.json    # reuse a fetch
"""

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import psycopg2.extras

# REUSED, not reimplemented: the MEDLINE authority gate lives in exactly one
# place so the two tier migrations cannot drift apart.
from reclassify_by_pubtype import fetch_pubtypes, map_pubtypes_to_tier
from rag import get_conn

BACKUP_TABLE = "endo_papers_rag_tier_backup"
RUN_ID_PREFIX = "empty_level_key_"

# ── Rung 2 cue vocabulary ────────────────────────────────────────────────────
# Journals whose research content is structured critical summaries of OTHER
# papers. Their abstracts describe the design of the summarised study.
COMMENTARY_JOURNALS = (
    "evidence-based dentistry",
    "evidence based dentistry",
    "journal of evidence-based dental practice",
    "journal of evidence based dental practice",
)

# The Evidence-Based Dentistry critical-summary abstract template. Matched as a
# second, journal-independent route into the same guard.
COMMENTARY_TEMPLATE_RE = re.compile(
    r"^\s*DESIGN\s*:.*?\bCASE SELECTION\s*:", re.IGNORECASE | re.DOTALL)

# Non-human subjects. Design cues on these records are real but the tier would
# not be: this hierarchy ranks human clinical evidence.
NONHUMAN_RE = re.compile(
    r"\b(dogs?|canine|cats?|feline|rats?|mice|murine|rabbits?|"
    r"sheep|swine|porcine|bovine|beagle)\b", re.IGNORECASE)
VETERINARY_JOURNAL_RE = re.compile(r"veterinary", re.IGNORECASE)

# Charts a literature without effect estimates or quality appraisal — this
# project has never assigned the design a tier. Same stance as
# reclassify_by_pubtype.UNMAPPED_SYNTHESIS_PUBTYPES.
SCOPING_RE = re.compile(r"\bscoping review\b", re.IGNORECASE)

# Self-referential design cues, strongest first. Each must name the paper in
# hand ("this ... study", "a ... study" in the title), never merely mention a
# design. Ordered so that a "randomised" phrase cannot be swallowed by a weaker
# rule below it.
CUE_RULES = [
    ("level1", "randomised controlled trial (self-referential)", re.compile(
        r"\b(this|the present)\s+(single[- ]cent(er|re)\s+|multi[- ]?cent(er|re)\s+)?"
        r"random(i[sz])?ed[- ](controlled[- ])?(clinical[- ])?trial\b|"
        r"\bthis\s+rct\b", re.IGNORECASE)),
    ("level1", "systematic review / meta-analysis (self-referential)", re.compile(
        r"\bthis\s+(systematic review|meta[- ]analys[ei]s)\b|"
        r"[:\-]\s*a\s+(systematic review|meta[- ]analysis)\b", re.IGNORECASE)),
    ("level3a", "retrospective cohort / retrospective study (self-referential)",
     re.compile(
        r"\b(this|the present)\s+retrospective\b|"
        r"\bretrospective(ly)?\s+(cohort\s+)?(stud(y|ies)|analys[ei]s|"
        r"review of|description|evaluat(ed|ion)|assess(ed|ment))\b|"
        r"\bwere\s+retrospectively\s+(evaluated|reviewed|analy[sz]ed|assessed)\b|"
        r"[:\-]\s*a\s+\d*[- ]?(year\s+)?retrospective\b",
        re.IGNORECASE)),
    ("level2", "prospective study (self-referential, not randomised)", re.compile(
        r"\b(this|the present)\s+prospective\b|"
        r"\baim of this prospective\b|"
        r"\bprospective(ly)?\s+(cohort\s+)?(stud(y|ies)|follow[- ]?up|"
        r"clinical stud(y|ies))\b|"
        r"[:\-]\s*a\s+prospective\b", re.IGNORECASE)),
    ("level4", "case report / case series (self-referential)", re.compile(
        r"\b(this|the present)\s+case (report|series)\b|"
        r"[:\-]\s*a\s+case (report|series)\b|"
        r"\bwe (report|present) (a|two|three|four|five) case", re.IGNORECASE)),
]


def classify_by_cues(title: str, abstract: str, journal: str):
    """Rung 2 + rung 3: (level_key, reason, needs_review).

    Only ever returns a tier it can point at a self-referential phrase for.
    Anything else lands at level5 flagged for a human — the same direction
    app.py already bands an unlabelled row, so rung 3 never makes a row worse.
    """
    text = f"{title or ''}\n{abstract or ''}"
    jl = (journal or "").lower()

    # ── Guards. These DECLINE; they never promote. ──
    if any(j in jl for j in COMMENTARY_JOURNALS) or \
            COMMENTARY_TEMPLATE_RE.search(abstract or ""):
        return ("level5",
                "structured critical summary — the design described belongs to "
                "the paper being summarised, not to this record", False)

    if VETERINARY_JOURNAL_RE.search(jl) or NONHUMAN_RE.search(title or ""):
        return ("level5",
                "non-human subjects — design cue is real but this hierarchy "
                "ranks human clinical evidence and no animal tier exists",
                True)

    if SCOPING_RE.search(text):
        return ("level5",
                "scoping review — project defines no tier for this design "
                "(8 others sit at level1; see HANDOVER)",
                True)

    for level, reason, rx in CUE_RULES:
        m = rx.search(text)
        if m:
            return (level, f"{reason}: {m.group(0).strip()!r}", False)

    return ("level5", "no self-referential design cue in title or abstract",
            True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write the change (default: dry run)")
    ap.add_argument("--cache", default="",
                    help="JSON file of fetched pubtype records — read if it "
                         "exists, written after a fetch, so --apply classifies "
                         "the exact records the dry run reported on")
    args = ap.parse_args()

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""
            SELECT pmid, title, journal, year, abstract,
                   ROUND(COALESCE(score, 0)::numeric, 1) AS score,
                   COALESCE(is_curated, FALSE)      AS is_curated,
                   COALESCE(medline_indexed, TRUE)  AS stored_medline
              FROM endo_papers_rag
             WHERE COALESCE(level_key, '') = ''
             ORDER BY pmid;
        """)
        rows = cur.fetchall()
        print(f"[empty-tier] rows with no level_key: {len(rows)}")
        if not rows:
            print("[empty-tier] nothing to do — the library is fully labelled.")
            return 0

        curated = [r for r in rows if r["is_curated"]]
        if curated:
            print(f"[empty-tier] NOTE {len(curated)} of these are is_curated "
                  f"(hand-assigned scores); tier is still set, score is not "
                  f"recomputed by rescore_library.py")

        # ── Rung 1: MEDLINE-gated publication types ──
        cache_path = Path(args.cache) if args.cache else None
        fetched = {}
        if cache_path and cache_path.exists():
            fetched = json.loads(cache_path.read_text(encoding="utf-8"))
            print(f"[empty-tier] loaded {len(fetched)} cached record(s) from "
                  f"{cache_path}")
        missing = [r["pmid"] for r in rows if r["pmid"] not in fetched]
        if missing:
            print(f"[empty-tier] efetch PublicationTypeList + MedlineCitation "
                  f"status for {len(missing)} PMID(s)")
            fetched.update(fetch_pubtypes(missing))
            if cache_path:
                cache_path.write_text(json.dumps(fetched), encoding="utf-8")
                print(f"[empty-tier] cached to {cache_path}")

        decisions = []
        for r in rows:
            rec = fetched.get(r["pmid"]) or {}
            pts = rec.get("pubtypes") or []
            mi = bool(rec.get("medline_indexed", True))

            tier, why = map_pubtypes_to_tier(
                pts, r.get("journal") or "", mi, r.get("title") or "")
            if tier:
                rung, needs_review = 1, False
                why = f"pubtype[{'MEDLINE' if mi else 'publisher'}]: {why}"
            else:
                held = why
                tier, why, needs_review = classify_by_cues(
                    r.get("title") or "", r.get("abstract") or "",
                    r.get("journal") or "")
                rung = 3 if needs_review else 2
                why = f"{why}  [rung1 declined: {held}]"
            decisions.append({
                "row": r, "pubtypes": pts, "medline": mi,
                "tier": tier, "why": why, "rung": rung,
                "needs_review": needs_review,
            })

        # ── The full pre-write listing ──
        print("\n" + "=" * 78)
        print("EVERY AFFECTED ROW (before any write)")
        print("=" * 78)
        for d in decisions:
            r = d["row"]
            print(f"\n  PMID {r['pmid']}   {r['year']}   score {r['score']}")
            print(f"    title    : {(r.get('title') or '')[:88]}")
            print(f"    journal  : {(r.get('journal') or '(none)')[:72]}")
            print(f"    MEDLINE  : {'MEDLINE' if d['medline'] else 'NOT MEDLINE-INDEXED'}"
                  f"   (stored column said {r['stored_medline']})")
            print(f"    pubtypes : {d['pubtypes'] or '(none returned)'}")
            print(f"    -> TIER  : {d['tier']}   via rung {d['rung']}"
                  f"{'   ** NEEDS REVIEW **' if d['needs_review'] else ''}")
            print(f"    reason   : {d['why']}")

        # ── Delta split, by the dimension the change is supposed to affect ──
        by_tier = Counter(d["tier"] for d in decisions)
        by_rung = Counter(d["rung"] for d in decisions)
        print("\n" + "=" * 78)
        print("DELTA SPLIT — '' -> proposed tier")
        print("=" * 78)
        for tier, n in sorted(by_tier.items()):
            print(f"    {n:5}   ''  ->  {tier}")
        print(f"    {'-' * 5}")
        print(f"    {len(decisions):5}   TOTAL")
        print("\n    which ladder rung decided it:")
        for rung in sorted(by_rung):
            label = {1: "MEDLINE publication types",
                     2: "title/abstract cues",
                     3: "level5 + needs review"}[rung]
            print(f"    {by_rung[rung]:5}   rung {rung} — {label}")

        flagged = [d for d in decisions if d["needs_review"]]
        if flagged:
            print(f"\n    {len(flagged)} row(s) left at level5 NEEDING REVIEW "
                  f"(record these in HANDOVER.md):")
            for d in flagged:
                print(f"      {d['row']['pmid']}  "
                      f"{(d['row'].get('title') or '')[:62]}")

        if not args.apply:
            print("\n[empty-tier] DRY RUN — re-run with --apply to write, then "
                  "python scripts/rescore_library.py --apply")
            return 0

        # ── BACKUP FIRST ────────────────────────────────────────────────
        # The first tier migration in this repo took no backup and the identity
        # of its 109 rows is unrecoverable. Same table and shape as
        # scripts/fix_books_and_retracted.py, new run_id.
        run_id = RUN_ID_PREFIX + time.strftime("%Y%m%dT%H%M%S")
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {BACKUP_TABLE} (
                run_id    TEXT,
                pmid      TEXT,
                level_key TEXT,
                score     REAL,
                journal   TEXT,
                backed_up TIMESTAMP DEFAULT NOW()
            );
        """)
        cur.execute(f"""
            INSERT INTO {BACKUP_TABLE} (run_id, pmid, level_key, score, journal)
            SELECT %s, pmid, level_key, score, journal FROM endo_papers_rag
             WHERE pmid = ANY(%s);
        """, (run_id, [d["row"]["pmid"] for d in decisions]))
        conn.commit()
        print(f"\n[empty-tier] backed up {cur.rowcount} row(s) into "
              f"{BACKUP_TABLE} (run_id={run_id})")
        print(f"[empty-tier] restore with:\n"
              f"    UPDATE endo_papers_rag e\n"
              f"       SET level_key = b.level_key, score = b.score\n"
              f"      FROM {BACKUP_TABLE} b\n"
              f"     WHERE b.run_id = '{run_id}' AND b.pmid = e.pmid;")

        # Guarded on the empty level_key so a re-run after a partial failure
        # cannot overwrite a tier this script already wrote.
        psycopg2.extras.execute_batch(cur, """
            UPDATE endo_papers_rag SET level_key = %s
             WHERE pmid = %s AND COALESCE(level_key, '') = '';
        """, [(d["tier"], d["row"]["pmid"]) for d in decisions], page_size=200)
        conn.commit()
        print(f"[empty-tier] APPLIED — {len(decisions)} level_key(s) written.")

        cur.execute("SELECT COUNT(*) AS n FROM endo_papers_rag "
                    "WHERE COALESCE(level_key,'') = '';")
        print(f"[empty-tier] rows still unlabelled: {cur.fetchone()['n']}")

        # Cached answers embed their own paper list and tier ordering, so they
        # would keep serving the old banding until their TTL expired.
        cur.execute("DELETE FROM query_cache;")
        conn.commit()
        print(f"[empty-tier] invalidated {cur.rowcount} cached answer(s).")
        print("[empty-tier] NEXT: python scripts/rescore_library.py --apply")
        return 0

    except Exception as e:
        conn.rollback()
        print(f"[empty-tier] FAILED: {e}")
        return 1
    finally:
        try:
            cur.close(); conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
