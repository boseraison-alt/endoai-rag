"""Item C — corpus-wide reband from publication types. DRY RUN ONLY.

There is deliberately no `--apply`. Rebanding changes `level_key` on rows
across the corpus, `level_key` carries 39% of the score through
`LEVEL_SCORES`, and the score orders every pool — so this changes every answer.
RB decides in the morning with the numbers in front of them. A batch that
applied it on its own judgement would be making a corpus-wide clinical change
overnight with nobody awake to read the delta.

WHAT IT PRINTS. For every row whose derived tier differs from its stored tier:
(pmid, stored, derived, score now, score after). Then the totals by tier pair.

THE DERIVATION IS `endo_ai.tier_from_pubtypes`, which is the same function the
write-back guard uses — not a second copy that can drift from it. Guideline
publication types derive `guideline`, NOT `level1`: the repo's older mapping in
`scripts/backfill_pubmed_metadata.py` predates the guideline tier and sends
them to the top of the evidence ladder.

`Review`-only records derive nothing, on purpose. NLM does not reliably tag
society guidelines in dental journals — PMID 32472740, the IADT 2020
introduction, carries only ["Journal Article", "Review"] — and mapping a bare
Review to level5 would demote consensus guidelines to expert opinion. Those
rows are counted as undecidable and left alone.

    python scripts/reband_from_pubtype.py [--limit N] [--out FILE.md]
"""
import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E  # noqa: E402
import rag           # noqa: E402


def fetch_pubtypes(pmids):
    """({pmid: [types]}, {pmid: abstract}) — both come from the same fetch, so
    split 3 costs no extra call."""
    out, abstracts = {}, {}
    B = 100
    for i in range(0, len(pmids), B):
        chunk = pmids[i:i + B]
        # PRECONDITION 2 — RETRY A FAILED BATCH. The 2026-09-06 run lost one
        # batch to "Response ended prematurely" and reported up to 100 rows as
        # "not derivable", which blamed the corpus for a dropped connection.
        recs = {}
        for attempt in (1, 2, 3):
            try:
                recs = E._fetch_pubtypes_and_abstracts(chunk)
                if recs:
                    break
            except Exception as ex:
                print("    [warn] pubtype fetch failed (attempt %d): %s"
                      % (attempt, ex))
                time.sleep(2 * attempt)
        if not recs:
            print("    [warn] chunk of %d could not be fetched after 3 tries"
                  % len(chunk))
        for p in chunk:
            out[p] = (recs.get(p) or {}).get("publication_types", []) or []
            abstracts[p] = (recs.get(p) or {}).get("abstract", "") or ""
        print("    fetched %d/%d" % (min(i + B, len(pmids)), len(pmids)))
    return out, abstracts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="0 = every numeric-PMID citeable row")
    ap.add_argument("--out", default="eval/reports/c_reband_dryrun.md")
    ap.add_argument("--pmids", default="",
                    help="comma-separated PMIDs; restricts the run so a test "
                         "can exercise the terminal guard without fetching "
                         "3,323 rows")
    args = ap.parse_args()

    conn = rag.get_conn()
    cur = conn.cursor()
    cur.execute("""SELECT pmid, level_key, score, journal, title
                   FROM endo_papers_rag
                   WHERE pmid ~ '^[0-9]+$'
                     AND COALESCE(quarantine_reason,'') = ''
                     AND NOT COALESCE(is_curated, FALSE)
                   ORDER BY pmid""")
    rows = cur.fetchall()
    if args.pmids:
        want = {p.strip() for p in args.pmids.split(",") if p.strip()}
        rows = [r for r in rows if r[0] in want]
    if args.limit:
        rows = rows[:args.limit]

    print("=" * 78)
    print("ITEM C — REBAND FROM PUBLICATION TYPES.  DRY RUN. NO --apply.")
    print("=" * 78)
    print("  candidate rows (numeric pmid, citeable, not curated)  %d"
          % len(rows))

    pts, abstracts = fetch_pubtypes([r[0] for r in rows])

    changes, pairs = [], Counter()
    undecidable = agree = 0
    terminal = []
    for pmid, stored, score, journal, title in rows:
        # ITEM E PRECONDITION 1 (2026-09-07) — TERMINAL STATUSES.
        #
        # `retracted` is not a tier this can move a row off. A retracted paper
        # is retracted whatever its publication types say, and the 2026-09-06
        # dry run would have moved two of them to `level1` — promoting
        # retracted work to the top of the evidence ladder, which is the worst
        # single move this script could make.
        #
        # A quarantined row is likewise terminal: it has been taken out of
        # retrieval deliberately, and rebanding it would silently re-band a
        # row somebody removed on purpose. (The query already excludes
        # quarantined rows; the check is here so that widening the query can
        # never re-admit them by accident.)
        if stored == "retracted":
            terminal.append((pmid, stored, "retracted"))
            continue
        derived, why = E.tier_from_pubtypes(pts.get(pmid), journal or "")
        if derived is None:
            undecidable += 1
            continue
        if derived == stored:
            agree += 1
            continue
        after = None if derived == "guideline" else E.LEVEL_SCORES.get(derived)
        changes.append({"pmid": pmid, "stored": stored, "derived": derived,
                        "why": why, "score_now": score,
                        "design_rung_now": E.LEVEL_SCORES.get(stored),
                        "design_rung_after": after,
                        "journal": journal, "title": (title or "")[:90]})
        pairs[(stored, derived)] += 1

    print("  TERMINAL, never moved (retracted / quarantined)       %d"
          % len(terminal))
    for pmid, stored, why in terminal:
        print("      %-10s %-12s %s" % (pmid, stored, why))
    print("  derived == stored (agree)                             %d" % agree)
    print("  no publication types / not derivable                  %d"
          % undecidable)
    print("  WOULD CHANGE                                          %d"
          % len(changes))
    decidable = agree + len(changes)
    if decidable < 0.5 * len(rows):
        print()
        print("  *** NOT REPORTING A RATE: only %d of %d rows were decidable,"
              % (decidable, len(rows)))
        print("      so the fetch failed rather than the corpus being untyped.")

    # ── PRECONDITION 3 — the three splits ──
    LADDER = ["level5", "level4", "level3b", "level3", "level3a",
              "level2", "level1", "cochrane"]

    def direction(stored, derived):
        if derived == "guideline":
            return "to guideline"
        if stored not in LADDER or derived not in LADDER:
            return "off-ladder"
        return "up" if LADDER.index(derived) > LADDER.index(stored) else "down"

    by_dir = Counter(direction(c["stored"], c["derived"]) for c in changes)
    by_agree = Counter()
    for c in changes:
        st = E.extract_stated_design(abstracts.get(c["pmid"], "") or "")             if hasattr(E, "extract_stated_design") else None
        stated = ""
        if isinstance(st, dict):
            stated = (st.get("design") or "").lower()
        elif isinstance(st, tuple) and st:
            stated = str(st[0] or "").lower()
        if not stated:
            by_agree["no extraction"] += 1
            c["abstract_design"] = ""
        else:
            c["abstract_design"] = stated
            hit = (stated in (c["derived"] or "")) or                   (c["derived"] == "level1" and
                   ("systematic review" in stated or "meta-analysis" in stated
                    or "randomi" in stated)) or                   (c["derived"] == "level4" and "case" in stated)
            by_agree["agree" if hit else "disagree"] += 1

    print()
    print("  SPLIT 2 — BY DIRECTION")
    for k, n in by_dir.most_common():
        print("    %-16s %5d" % (k, n))
    print()
    print("  SPLIT 3 — vs THE ABSTRACT-EXTRACTED DESIGN")
    for k, n in by_agree.most_common():
        print("    %-16s %5d" % (k, n))

    # ── PRECONDITION 4 — manifest candidates ──
    man_ids = set()
    try:
        import json as _json
        man = _json.load(open("data/guidelines_seed.json", encoding="utf-8"))
        for g in man["guidelines"]:
            if g.get("pmid"):
                man_ids.add(str(g["pmid"]))
            for a in (g.get("alt_pmid") or []):
                man_ids.add(str(a))
    except Exception as ex:
        print("  [warn] manifest unreadable: %s" % ex)
    candidates = [c for c in changes
                  if c["derived"] == "guideline" and c["pmid"] not in man_ids]
    print()
    print("  MANIFEST CANDIDATES — pubtype says guideline, no manifest record")
    print("  (NOT moved. The manifest is the only authority on what is a")
    print("   guideline; these are for RB to consider adding.)  %d"
          % len(candidates))
    for c in candidates:
        print("    %-10s %-4s %-34s %s"
              % (c["pmid"], "", (c["journal"] or "")[:34], c["title"][:60]))

    print()
    print("  TOTALS BY TIER PAIR  (stored -> derived)")
    for (s, d), n in pairs.most_common():
        print("    %-14s -> %-14s %5d   %s"
              % (s, d, n,
                 "ONTO the guideline rung" if d == "guideline" else ""))

    print()
    print("  EVERY ROW THAT WOULD CHANGE")
    print("  %-10s %-13s %-13s %8s %8s  %s"
          % ("pmid", "stored", "derived", "score", "after", "why"))
    for c in changes:
        print("  %-10s %-13s %-13s %8s %8s  %s"
              % (c["pmid"], c["stored"], c["derived"],
                 c["score_now"],
                 "NULL" if c["derived"] == "guideline" else "rescore",
                 c["why"]))

    lines = [
        "# Item C — reband from publication types (DRY RUN)",
        "",
        "No `--apply` exists on this script. Rebanding moves `level_key`, which",
        "carries 39% of the score, which orders every pool — so it changes every",
        "answer. RB decides with these numbers.",
        "",
        "| | |",
        "|---|---|",
        "| candidate rows (numeric pmid, citeable, not curated) | %d |" % len(rows),
        "| derived == stored | %d |" % agree,
        "| not derivable from publication types | %d |" % undecidable,
        "| **would change** | **%d** |" % len(changes),
        "",
        "Derivation is `endo_ai.tier_from_pubtypes`, the same function the",
        "write-back guard uses. Guideline publication types derive `guideline`,",
        "not `level1`. `Review`-only records derive nothing — NLM does not",
        "reliably tag society guidelines in dental journals, and a bare `Review`",
        "would demote a consensus guideline to expert opinion.",
        "",
        "## Totals by tier pair",
        "",
        "| stored | derived | rows |",
        "|---|---|---|",
    ]
    for (s, d), n in pairs.most_common():
        lines.append("| %s | %s | %d |" % (s, d, n))
    lines += ["", "## Every row that would change", "",
              "| pmid | stored | derived | score now | score after | why |",
              "|---|---|---|---|---|---|"]
    for c in changes:
        lines.append("| %s | %s | %s | %s | %s | %s |"
                     % (c["pmid"], c["stored"], c["derived"], c["score_now"],
                        "NULL" if c["derived"] == "guideline" else "rescore",
                        c["why"]))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    json.dump(changes, open(args.out.replace(".md", ".json"), "w"), indent=1)
    print("\n  wrote %s" % args.out)
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
