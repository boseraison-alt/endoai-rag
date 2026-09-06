"""Item C (2026-09-06 night batch) — what actually writes `level_key`.

THE FINDING THIS MEASURES. Two mechanisms write `level_key`:

  * the pubtype backfill, from PublicationTypeList  -> the paper's DESIGN
  * live write-back, from `eff_level`               -> the LANE it was found by

`rag.learn_from_live_results` stores `p["level_key"]`, and the live path sets
that to `eff_level` at endo_ai.py:5171, commented "The tier this paper was
retrieved under". Write-back runs on every live query; the backfill runs when
someone runs it. So write-back decides what the column MEANS, and what it means
is "which query found this", which is not a tier.

That is how nine IADT consensus guidelines became level1/level2 studies.

WHAT THIS SCRIPT PRINTS
  1. every lane's PubMed filter string, and whether it contains a guideline
     publication type (the "door" question)
  2. the (derived -> stored) matrix on a random sample, since publication types
     are NOT stored per row in this schema
  3. how many mis-banded rows are cited by stored answers

A NOTE ON THE DERIVATION, because the repo's existing one is part of the bug.
`scripts/backfill_pubmed_metadata.py::PUBTYPE_TO_LEVEL` maps `practice
guideline`, `guideline` and `consensus development conference` to **level1**.
It was written before the `guideline` tier existed. Deriving with it would
"correct" a guideline onto the top of the evidence ladder, which is the
score-as-membership error running the other way. So this script derives with
BOTH and prints both: `derived_repo` (what the shipped mapping says) and
`derived_fixed` (guideline publication types -> `guideline`).

Usage:
    python scripts/measure_writeback_banding.py --sample 200
"""
import argparse
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E   # noqa: E402
import rag            # noqa: E402

GUIDELINE_PUBTYPES = {"practice guideline", "guideline",
                      "consensus development conference",
                      "consensus development conference, nih"}

# Same order as the repo's mapping, with the guideline types corrected to the
# tier that exists for them now.
PUBTYPE_TO_TIER_FIXED = [
    ("practice guideline", "guideline"),
    ("guideline", "guideline"),
    ("consensus development conference", "guideline"),
    ("consensus development conference, nih", "guideline"),
    ("meta-analysis", "level1"),
    ("systematic review", "level1"),
    ("randomized controlled trial", "level1"),
    ("controlled clinical trial", "level2"),
    ("clinical trial, phase iv", "level2"),
    ("clinical trial, phase iii", "level2"),
    ("clinical trial", "level2"),
    ("multicenter study", "level2"),
    ("observational study", "level3a"),
    ("comparative study", "level3a"),
    ("evaluation study", "level3b"),
    ("case reports", "level4"),
    ("review", "level5"),
    ("editorial", "level5"),
    ("comment", "level5"),
    ("letter", "level5"),
]

PUBTYPE_TO_TIER_REPO = [
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


def derive(pubtypes, journal, table):
    if "cochrane" in (journal or "").lower():
        return "cochrane", "journal:cochrane"
    low = [str(p).strip().lower() for p in (pubtypes or [])]
    for tag, tier in table:
        if tag in low:
            return tier, tag
    return None, None


def fetch_pubtypes(pmids):
    """{pmid: [publication types]} through the repo's own PubMed client."""
    out = {}
    B = 200
    for i in range(0, len(pmids), B):
        chunk = pmids[i:i + B]
        meta = {p: {} for p in chunk}
        try:
            E._merge_corrections_and_registries(chunk, meta)
        except Exception as ex:
            print("    pubtype fetch failed for a chunk: %s" % ex)
        for p in chunk:
            out[p] = (meta.get(p) or {}).get("pubtypes", []) or []
        print("    fetched publication types %d/%d" % (min(i + B, len(pmids)),
                                                       len(pmids)))
    return out


def stored_answer_corpora():
    texts = []
    conn = rag.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, answer, papers FROM query_cache")
    for r in cur.fetchall():
        texts.append(("query_cache#%s" % r[0],
                      (r[1] or "") + "\n" + json.dumps(r[2] or {})))
    cur.close()
    conn.close()
    for pat in ("answers/*.txt", "eval/logs/case_answers/*.md"):
        for p in sorted(Path(".").glob(pat)):
            try:
                texts.append((str(p), p.read_text(encoding="utf-8",
                                                  errors="replace")))
            except Exception:
                pass
    return texts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20260906)
    ap.add_argument("--json", dest="json_out",
                    default="eval/reports/night8_item_c.json")
    args = ap.parse_args()

    print("=" * 78)
    print("ITEM C — WRITE-BACK STORES THE LANE, NOT THE DESIGN")
    print("=" * 78)

    # ── 1. THE DOOR ──
    print("\n1. EVERY LANE'S PUBMED FILTER STRING")
    door = []
    filters = E.live_path_filters()
    for key in ["cochrane"] + [k for k, _t, _l in E.tier_query_lanes()]:
        f = filters.get(key, "")
        low = f.lower()
        hit = sorted({g for g in GUIDELINE_PUBTYPES if g in low})
        if hit:
            door.append((key, hit))
        print("   %-14s %s" % (key, f))
        if hit:
            print("   %-14s ^^ CONTAINS a guideline publication type: %s"
                  % ("", ", ".join(hit)))
    print()
    if door:
        print("   DOOR: %s" % ", ".join("%s (%s)" % (k, ", ".join(h))
                                        for k, h in door))
    else:
        print("   NO lane filter contains a guideline publication type.")
        print("   So the door is NOT a pubtype door. The lanes that admitted")
        print("   the nine are level1 and level2 by their own filters, and the")
        print("   reason a guideline matched them is that write-back stored")
        print("   the LANE, not a derived design. Named below.")

    # Which lane admitted the nine, from what the rows were banded as.
    conn = rag.get_conn()
    cur = conn.cursor()
    NINE = ["32472740", "32475015", "32460393", "32458553", "22230724",
            "22409417", "22583659", "17511833", "17635351"]
    print("\n   THE NINE — the lane each was admitted under")
    cur.execute("SELECT pmid, level_key, guideline_id FROM endo_papers_rag "
                "WHERE pmid = ANY(%s) ORDER BY pmid", (NINE,))
    now = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    WAS = {"32472740": "level1", "32475015": "level2", "32460393": "level2",
           "32458553": "level2", "22230724": "level2", "22409417": "level2",
           "22583659": "level2", "17511833": "level2", "17635351": "level2"}
    for p in NINE:
        lk, gid = now.get(p, ("(absent)", ""))
        print("     %-10s admitted by lane %-8s  now %-10s  %s"
              % (p, WAS[p], lk, gid or ""))
    print("     -> IADT-INTRO-2020 (32472740) was admitted by the LEVEL1 lane:")
    print("        %s" % filters.get("level1", ""))
    print("     -> the other eight by the LEVEL2 lane:")
    print("        %s" % filters.get("level2", ""))

    # ── 2. THE MATRIX ──
    print("\n2. DERIVED vs STORED")
    cur.execute("SELECT column_name FROM information_schema.columns "
                "WHERE table_name='endo_papers_rag'")
    cols = {r[0] for r in cur.fetchall()}
    pt_stored = bool({"pubtypes", "publication_types", "pubtype"} & cols)
    print("   publication types stored per row? %s" % ("YES" if pt_stored
                                                       else "NO"))
    if not pt_stored:
        print("   -> the schema has no pubtype column (31 columns, checked).")
        print("      So this is measured on a RANDOM SAMPLE fetched live")
        print("      through the repo's own PubMed client, and NOT")
        print("      extrapolated beyond one decimal.")

    cur.execute("""SELECT pmid, level_key, journal FROM endo_papers_rag
                   WHERE pmid ~ '^[0-9]+$'
                     AND COALESCE(quarantine_reason,'') = ''""")
    allrows = cur.fetchall()
    print("   numeric-PMID citeable rows in table: %d" % len(allrows))
    rnd = random.Random(args.seed)
    sample = rnd.sample(allrows, min(args.sample, len(allrows)))
    print("   SAMPLE SIZE: %d (seed %d)" % (len(sample), args.seed))

    pts = fetch_pubtypes([r[0] for r in sample])

    matrix = defaultdict(Counter)
    matrix_repo = defaultdict(Counter)
    undecidable = 0
    guideline_typed_on_ladder = []
    for pmid, stored, journal in sample:
        types = pts.get(pmid, [])
        dfix, tagf = derive(types, journal, PUBTYPE_TO_TIER_FIXED)
        drepo, _ = derive(types, journal, PUBTYPE_TO_TIER_REPO)
        if dfix is None:
            undecidable += 1
        else:
            matrix[dfix][stored] += 1
        if drepo is not None:
            matrix_repo[drepo][stored] += 1
        low = {str(t).strip().lower() for t in types}
        if (low & GUIDELINE_PUBTYPES) and stored in E.TIER_ORDER \
                and stored != "guideline":
            guideline_typed_on_ladder.append((pmid, stored, sorted(low &
                                                                   GUIDELINE_PUBTYPES),
                                              journal))

    print("\n   (derived_fixed -> stored) MATRIX, n=%d" % len(sample))
    print("   %-12s %s" % ("derived", "stored ->"))
    agree = disagree = 0
    for d in sorted(matrix):
        for s, n in sorted(matrix[d].items(), key=lambda x: -x[1]):
            flag = "" if d == s else "   <-- disagrees"
            if d == s:
                agree += n
            else:
                disagree += n
            print("   %-12s %-14s %4d%s" % (d, s, n, flag))
    print("   %-12s %-14s %4d" % ("(no type)", "-", undecidable))
    print("\n   agree %d   disagree %d   undecidable %d   (n=%d)"
          % (agree, disagree, undecidable, len(sample)))
    if agree + disagree:
        print("   disagreement rate on decidable rows: %.1f%%"
              % (100.0 * disagree / (agree + disagree)))

    print("\n   ROWS CARRYING A GUIDELINE PUBLICATION TYPE BUT BANDED ON THE")
    print("   STUDY LADDER (the mis-banding, in the sample): %d"
          % len(guideline_typed_on_ladder))
    for pmid, stored, tags, journal in guideline_typed_on_ladder:
        print("     %-10s stored=%-9s pubtypes=%s  %s"
              % (pmid, stored, ",".join(tags), (journal or "")[:40]))

    # ── 3. CITED BY STORED ANSWERS ──
    print("\n3. MIS-BANDED ROWS CITED BY STORED ANSWERS")
    texts = stored_answer_corpora()
    print("   stored answers scanned: %d" % len(texts))
    cited = []
    for pmid, stored, _j in guideline_typed_on_ladder:
        n = sum(1 for _name, t in texts if re.search(r"\b%s\b" % pmid, t))
        if n:
            cited.append((pmid, stored, n))
    print("   of the %d mis-banded sample rows, cited by an answer: %d"
          % (len(guideline_typed_on_ladder), len(cited)))
    for pmid, stored, n in cited:
        print("     %-10s stored=%-9s cited in %d stored answer(s)"
              % (pmid, stored, n))

    Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
    json.dump({"sample_size": len(sample), "seed": args.seed,
               "agree": agree, "disagree": disagree,
               "undecidable": undecidable,
               "guideline_typed_on_ladder": guideline_typed_on_ladder,
               "cited": cited,
               "matrix": {d: dict(c) for d, c in matrix.items()},
               "matrix_repo_mapping": {d: dict(c)
                                       for d, c in matrix_repo.items()}},
              open(args.json_out, "w"), indent=1)
    print("\n  wrote %s" % args.json_out)
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
