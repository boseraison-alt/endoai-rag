"""Item E (2026-09-08) — label every animal-subject row, and say which species.

WHY A LABEL AND NOT A REBAND. These rows are not wrong to be in the library; a
dog-model regeneration study is real evidence about regeneration. They are wrong
to reach a clinician's answer looking like human clinical evidence. The label
travels with the row into the context block, so the model and the reader both
see what the subjects were.

THE PROTECTED-TIER VETO IS DELIBERATELY BYPASSED HERE, and this is the one
judgement in this script. `detect_animal_subject` short-circuits on `classic`,
`cochrane` and `level1` — a veto written for a MIGRATION that moves tiers,
where touching a protected rung is the danger. Labelling moves nothing. With
the veto on, the count is 56 and `2321557` ("An investigation of lymphatic
vessels in the FELINE dental pulp", level_key=classic) reaches a pool with no
indication that its subjects were cats. With it off the row is labelled.
Labelling a protected row costs nothing; hiding it costs a clinician.

THE COUNT IS 86, NOT THE 81 RECORDED ON 2026-09-07, and the arithmetic is:

    81   the 2026-09-07 figure, over the 3,353 rows with a readable abstract
   +26   rows in protected tiers, which that run's veto skipped
    +7   rows that fire on their TITLE alone, which that run never scanned
    -2   false positives removed today by the sentence-scope veto
   ----
    86   two rows also moved tier since, which nets the arithmetic out exactly

The two removed are 26275599 ("...of HUMAN MOLARS", cue from a sentence about
somebody else's bovine-muscle experiment) and 24331984 ("HUMAN cytomegalovirus
...", cue from "Further studies... should provide more data"). Both were found
by adjudicating the rows on the human clinical ladder by hand, which is where a
wrong label actually harms someone.

    python scripts/backfill_animal_subject.py            # DRY RUN
    python scripts/backfill_animal_subject.py --apply
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

import rag  # noqa: E402
from animal_species import species_from_reason  # noqa: E402
from animal_subjects import detect_animal_subject  # noqa: E402

HUMAN_LADDER = {"cochrane", "level1", "level2", "level3a", "level3b",
                "level3", "level4"}


def classify_all(cur):
    cur.execute("""
        SELECT pmid, COALESCE(title,''), COALESCE(abstract,''),
               COALESCE(journal,''), COALESCE(level_key,''),
               COALESCE(animal_subject,'')
        FROM endo_papers_rag
    """)
    out = []
    for pmid, title, abstract, journal, level, current in cur.fetchall():
        # NO level_key PASSED — the protected-tier veto is for retiering.
        is_animal, why = detect_animal_subject(title, abstract, journal)
        species = species_from_reason(why) if is_animal else ""
        # A VETERINARY-JOURNAL HIT NAMES NO SPECIES, but the title often does.
        # 41493880 is "...in Dogs Undergoing Dental Procedures" in a veterinary
        # journal: correctly animal, and "unspecified" when the title says dog.
        # Only the title is consulted, never the abstract, because a title is
        # about this study by construction.
        if is_animal and species == "unspecified":
            from_title = species_from_reason(title)
            if from_title != "unspecified":
                species = from_title
                why = "%s; species from title" % why
        out.append({"pmid": pmid, "level_key": level, "title": title,
                    "is_animal": is_animal, "why": why, "species": species,
                    "current": current})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = rag.get_conn()
    cur = conn.cursor()
    cur.execute("""
        ALTER TABLE endo_papers_rag
        ADD COLUMN IF NOT EXISTS animal_subject TEXT DEFAULT '';
    """)
    cur.execute("""
        ALTER TABLE endo_papers_rag
        ADD COLUMN IF NOT EXISTS animal_subject_why TEXT DEFAULT '';
    """)
    conn.commit()

    rows = classify_all(cur)
    animal = [r for r in rows if r["is_animal"]]
    changes = [r for r in animal if r["current"] != r["species"]]
    clears = [r for r in rows
              if not r["is_animal"] and r["current"]]

    print("=" * 78)
    print("ITEM E — ANIMAL-SUBJECT BACKFILL  (%s)"
          % ("APPLY" if args.apply else "DRY RUN"))
    print("=" * 78)
    print("  rows scanned                : %d" % len(rows))
    print("  ANIMAL-SUBJECT rows         : %d" % len(animal))
    print("  labels to write             : %d" % len(changes))
    print("  stale labels to clear       : %d" % len(clears))
    print()
    print("  BY SPECIES")
    for k, v in Counter(r["species"] for r in animal).most_common():
        print("    %-14s %3d" % (k, v))
    print()
    print("  BY TIER")
    for k, v in Counter(r["level_key"] for r in animal).most_common():
        mark = "   <-- on the human clinical ladder" if k in HUMAN_LADDER else ""
        print("    %-14s %3d%s" % (k, v, mark))
    on_ladder = [r for r in animal if r["level_key"] in HUMAN_LADDER]
    print()
    print("  ON THE HUMAN CLINICAL LADDER: %d" % len(on_ladder))
    for r in on_ladder:
        print("    %-10s %-8s %-11s %s"
              % (r["pmid"], r["level_key"], r["species"], r["title"][:52]))

    if args.apply:
        for r in changes:
            cur.execute("""
                UPDATE endo_papers_rag
                SET animal_subject = %s, animal_subject_why = %s
                WHERE pmid = %s
            """, (r["species"], r["why"], r["pmid"]))
        for r in clears:
            cur.execute("""
                UPDATE endo_papers_rag
                SET animal_subject = '', animal_subject_why = ''
                WHERE pmid = %s
            """, (r["pmid"],))
        conn.commit()
        print("\n  APPLIED — %d labelled, %d cleared."
              % (len(changes), len(clears)))
    else:
        conn.rollback()
        print("\n  DRY RUN — nothing written.")

    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    json.dump({"scanned": len(rows), "animal": len(animal),
               "on_human_ladder": len(on_ladder),
               "by_species": dict(Counter(r["species"] for r in animal)),
               "by_tier": dict(Counter(r["level_key"] for r in animal)),
               "rows": [{k: r[k] for k in
                         ("pmid", "level_key", "species", "why", "title")}
                        for r in animal]},
              open("eval/reports/night10_animal_backfill.json", "w",
                   encoding="utf-8"), indent=1)
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
