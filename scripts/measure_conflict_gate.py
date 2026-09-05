"""Item 3 — does the surfacing gate fire on the 25 and stay silent on the 11?

THE FALSE-POSITIVE CHECK MATTERS MORE THAN THE TRUE POSITIVES. A notice on a
document that has no conflict teaches a reader to ignore the notice, and then
it protects nobody on the 25 that do. So this reports both directions and the
clean-document count is the one to read first.

Runs the REAL serve path -- `endo_ai.finalise_answer_text` -- over every
stored curriculum, not the detector in isolation, because the question is
whether a reader sees the block (standing rule 14).

Usage:  python scripts/measure_conflict_gate.py [--json out.json]
"""
import glob
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E               # noqa: E402
import psycopg2                   # noqa: E402
import psycopg2.extras            # noqa: E402
from rag import DATABASE_URL      # noqa: E402


def load_curricula():
    docs = []
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, answer FROM query_cache "
                "WHERE question_text LIKE '[learn]%' AND answer IS NOT NULL")
    for r in cur.fetchall():
        docs.append(("query_cache:%s" % r["id"], r["answer"]))
    conn.close()
    for p in sorted(glob.glob("learn_history/*.json")):
        try:
            rec = json.loads(open(p, encoding="utf-8").read())
        except Exception:
            continue
        if rec.get("answer"):
            docs.append((p, rec["answer"]))
    for p in sorted(glob.glob("eval/fixtures/curricula/*.txt")):
        docs.append((p, open(p, encoding="utf-8", errors="replace").read()))
    return docs


def main():
    docs = load_curricula()
    fired, silent, skipped = [], [], []
    idempotent = True

    for name, text in docs:
        mods = E.curriculum_modules(text)
        if len(mods) < 2:
            skipped.append(name)
            continue
        conflicts = E.detect_parameter_conflicts(mods)
        out = E.finalise_answer_text(text)
        served = out[0] if isinstance(out, tuple) else out
        has_block = E._CONFLICT_HEADER in served

        # Idempotence: re-rendering what was already served must not stack a
        # second notice. finalise_answer_text runs on every view of a stored
        # row, so this is the property that decides whether it is safe there.
        again = E.finalise_answer_text(served)
        again = again[0] if isinstance(again, tuple) else again
        if again.count(E._CONFLICT_HEADER) != served.count(E._CONFLICT_HEADER):
            idempotent = False
            print("  *** NOT IDEMPOTENT: %s" % name)

        rec = {"doc": name, "modules": len(mods),
               "n_conflicts": len(conflicts), "block_rendered": has_block,
               "conflicts": [{"agent": c["agent"], "unit": c["unit"],
                              "values": [v["value"] for v in c["values"]]}
                             for c in conflicts]}
        (fired if has_block else silent).append(rec)

    print("=" * 78)
    print("ITEM 3 — CONFLICT SURFACING GATE, MEASURED ON THE SERVE PATH")
    print("=" * 78)
    print("  curricula with >=2 modules      %d" % (len(fired) + len(silent)))
    print("  documents skipped (not a curriculum) %d" % len(skipped))
    print()
    print("  BLOCK RENDERED (true positives)  %d" % len(fired))
    print("  NO BLOCK (must be clean)         %d" % len(silent))
    print("  idempotent on re-render          %s" % idempotent)
    print()

    print("  --- FALSE-POSITIVE CHECK: every silent document must have 0 conflicts")
    bad = [r for r in silent if r["n_conflicts"]]
    for r in silent:
        print("    %-54s conflicts=%d" % (r["doc"][:54], r["n_conflicts"]))
    print("    -> %s" % ("CLEAN: no silent document has a conflict"
                         if not bad else
                         "*** %d silent documents DO have conflicts" % len(bad)))
    print()
    print("  --- FALSE-NEGATIVE CHECK: every firing document must have >=1")
    miss = [r for r in fired if not r["n_conflicts"]]
    print("    -> %s" % ("CLEAN: every rendered block has a detected conflict"
                         if not miss else
                         "*** %d blocks rendered with no conflict" % len(miss)))
    print()
    print("  --- what the 25 actually disagree about")
    for r in fired[:30]:
        for c in r["conflicts"]:
            print("    %-46s %-22s %s"
                  % (r["doc"][-46:], c["agent"], c["values"]))

    if "--json" in sys.argv:
        p = sys.argv[sys.argv.index("--json") + 1]
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).write_text(json.dumps(
            {"fired": fired, "silent": silent, "skipped": skipped,
             "idempotent": idempotent}, indent=1), encoding="utf-8")
        print("\nwrote %s" % p)
    return 0 if (not bad and not miss and idempotent) else 1


if __name__ == "__main__":
    sys.exit(main())
