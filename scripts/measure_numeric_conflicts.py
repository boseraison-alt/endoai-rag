"""Item 6 — how many stored curricula carry an internal numeric conflict?

A51(a). Same quantity, two different values, one document = flag. The
2026-09-04 18:13 VPT curriculum carries THREE haemostasis numbers: Module 1
"up to 10 minutes", Modules 3 and 4 "6 minutes", Module 2 "no threshold
established". A clinician reading Module 1's protocol and the Final Verdict's
decision rule is given different instructions.

MEASURE ONLY. Runs the EXISTING chart-gate logic
(`detect_parameter_conflicts`, built on `extract_numeric_parameters`) across
every stored curriculum and reports the count, which is the severity.

It also reports what that detector CANNOT see, because that turns out to be
the more important half of the answer -- see the report.

Usage:  python scripts/measure_numeric_conflicts.py [--json out.json]
"""
import glob
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import endo_ai as E                # noqa: E402
import psycopg2                    # noqa: E402
import psycopg2.extras             # noqa: E402
from rag import DATABASE_URL       # noqa: E402

# The haemostasis shape, for the "what the detector cannot see" half. This is
# a PROBE, not a proposed gate -- it exists to size the gap, and it is
# deliberately narrow: one named quantity, one unit family.
_HAEMOSTASIS_RE = re.compile(
    r"(?:h(?:a)?emostasis|h(?:a)?emorrhage\s+control|bleeding)[^.;]{0,80}?"
    r"(\d+(?:\.\d+)?)\s*(?:-|to|and)?\s*(\d+(?:\.\d+)?)?\s*(min(?:ute)?s?)"
    r"|(\d+(?:\.\d+)?)\s*(min(?:ute)?s?)[^.;]{0,80}?"
    r"(?:h(?:a)?emostasis|h(?:a)?emorrhage\s+control|bleeding)",
    re.I)


def modules_of(text):
    body = text.split("## Citation Support by Module")[0]
    parts = re.split(r"^(## [^\n]*)$", body, flags=re.M)
    out = []
    for i in range(1, len(parts), 2):
        head = parts[i].strip()
        if head.startswith("## Module") and len(parts[i + 1].split()) >= 40:
            out.append((head, parts[i + 1]))
    return out


def load_curricula():
    docs = []
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, question_text, answer FROM query_cache "
                "WHERE question_text LIKE '[learn]%' AND answer IS NOT NULL")
    for r in cur.fetchall():
        docs.append(("query_cache:%s" % r["id"], r["question_text"], r["answer"]))
    conn.close()

    for p in sorted(glob.glob("learn_history/*.json")):
        try:
            rec = json.loads(open(p, encoding="utf-8").read())
        except Exception:
            continue
        if rec.get("answer"):
            docs.append((p, rec.get("question", ""), rec["answer"]))
    for p in sorted(glob.glob("eval/fixtures/curricula/*.txt")):
        docs.append((p, "", open(p, encoding="utf-8", errors="replace").read()))
    return docs


def haemostasis_values(modules):
    """{value_in_minutes: [modules]} -- the probe, not a gate."""
    by_val = {}
    for title, text in modules:
        for m in _HAEMOSTASIS_RE.finditer(text):
            for g in (m.group(1), m.group(2), m.group(4)):
                if g:
                    by_val.setdefault(float(g), set()).add(title)
    return by_val


def main():
    docs = load_curricula()
    print("=" * 78)
    print("ITEM 6 — INTERNAL NUMERIC CONFLICTS IN STORED CURRICULA (measure only)")
    print("=" * 78)
    print("documents: %d\n" % len(docs))

    rows, n_conflict, n_haemo = [], 0, 0
    for name, question, text in docs:
        mods = modules_of(text)
        if not mods:
            continue
        conflicts = E.detect_parameter_conflicts(mods)
        haemo = haemostasis_values(mods)
        multi_haemo = {v: sorted(ms) for v, ms in haemo.items()}
        haemo_conflict = (len(haemo) >= 2
                          and len({m for ms in haemo.values() for m in ms}) >= 2)
        if conflicts:
            n_conflict += 1
        if haemo_conflict:
            n_haemo += 1
        rows.append({
            "doc": name, "question": (question or "")[:70],
            "modules": len(mods),
            "conflicts": conflicts,
            "n_conflicts": len(conflicts),
            "haemostasis_values": {str(k): v for k, v in multi_haemo.items()},
            "haemostasis_conflict": haemo_conflict,
        })
        flag = ""
        if conflicts:
            flag += "  CONC-CONFLICT x%d" % len(conflicts)
        if haemo_conflict:
            flag += "  HAEMOSTASIS x%d values" % len(haemo)
        print("  %-52s mods=%-3d%s" % (name[:52], len(mods), flag))

    print()
    print("=" * 78)
    print("RESULT")
    print("=" * 78)
    print("  curricula with modules parsed        %d" % len(rows))
    print("  carrying a CONCENTRATION conflict    %d   <- what the existing "
          "detector finds" % n_conflict)
    print("  carrying a HAEMOSTASIS-TIME conflict %d   <- what it CANNOT see"
          % n_haemo)
    print()
    for r in rows:
        if r["haemostasis_conflict"]:
            print("  %s" % r["doc"])
            for v, ms in sorted(r["haemostasis_values"].items(),
                                key=lambda x: float(x[0])):
                print("      %-6s min  %s" % (v, "; ".join(m[:44] for m in ms)))

    if "--json" in sys.argv:
        p = sys.argv[sys.argv.index("--json") + 1]
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).write_text(json.dumps(
            {"n_docs": len(rows), "n_concentration_conflicts": n_conflict,
             "n_haemostasis_conflicts": n_haemo, "rows": rows}, indent=1),
            encoding="utf-8")
        print("\nwrote %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
