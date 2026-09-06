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
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E  # noqa: E402
import rag           # noqa: E402


def fetch_pubtypes(pmids):
    out = {}
    B = 100
    for i in range(0, len(pmids), B):
        chunk = pmids[i:i + B]
        try:
            recs = E._fetch_pubtypes_and_abstracts(chunk)
        except Exception as ex:
            print("    [warn] pubtype fetch failed for a chunk: %s" % ex)
            recs = {}
        for p in chunk:
            out[p] = (recs.get(p) or {}).get("publication_types", []) or []
        print("    fetched %d/%d" % (min(i + B, len(pmids)), len(pmids)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="0 = every numeric-PMID citeable row")
    ap.add_argument("--out", default="eval/reports/c_reband_dryrun.md")
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
    if args.limit:
        rows = rows[:args.limit]

    print("=" * 78)
    print("ITEM C — REBAND FROM PUBLICATION TYPES.  DRY RUN. NO --apply.")
    print("=" * 78)
    print("  candidate rows (numeric pmid, citeable, not curated)  %d"
          % len(rows))

    pts = fetch_pubtypes([r[0] for r in rows])

    changes, pairs = [], Counter()
    undecidable = agree = 0
    for pmid, stored, score, journal, title in rows:
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
