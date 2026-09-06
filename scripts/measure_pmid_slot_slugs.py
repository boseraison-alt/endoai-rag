"""Item B — stored answers carrying a guideline id inside a PMID marker.

These are the answers the rewrite repairs at SERVE time, without rewriting a
single stored row. The number matters twice: it says how much of the stored
corpus was affected, and — served through `finalise_answer_text` — it shows
what a clinician now sees where they previously saw a raw `[[PMID:ACP-...]]`.

Rule 34: the input is counted before any zero.

    python scripts/measure_pmid_slot_slugs.py [--serve]
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E  # noqa: E402
import rag           # noqa: E402


def corpora():
    out = {}
    conn = rag.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, answer FROM query_cache")
    out["query_cache"] = [("query_cache#%s" % r[0], r[1] or "")
                          for r in cur.fetchall()]
    cur.close()
    conn.close()
    for label, pat in (("answers/", "answers/*.txt"),
                       ("eval/logs/case_answers/",
                        "eval/logs/case_answers/*.md"),
                       ("eval/reports/", "eval/reports/night8_probe3_*.md")):
        items = []
        for p in sorted(Path(".").glob(pat)):
            try:
                items.append((str(p), p.read_text(encoding="utf-8",
                                                  errors="replace")))
            except Exception:
                pass
        out[label] = items
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true",
                    help="run one affected answer through finalise_answer_text")
    args = ap.parse_args()

    known = E._known_synthetic_keys() or set()
    print("=" * 78)
    print("ITEM B — GUIDELINE IDS SITTING IN A PMID SLOT, IN STORED ANSWERS")
    print("=" * 78)
    print("  citeable non-numeric keys in the library  %d" % len(known))

    c = corpora()
    print("  THE INPUT")
    for k, v in c.items():
        print("    %-26s %4d" % (k, len(v)))
    print("    %-26s %4d TOTAL" % ("", sum(len(v) for v in c.values())))
    print()

    rx = re.compile(r"\[\[PMID:\s*(" + E._PMID_ID_PAT + r")\s*\]\]")
    affected, all_nonnumeric = [], {}
    for corpus, items in c.items():
        for name, text in items:
            ids = [m.group(1).strip() for m in rx.finditer(text)]
            nonnum = [i for i in ids if not i.isdigit()]
            for i in nonnum:
                all_nonnumeric.setdefault(i, 0)
                all_nonnumeric[i] += 1
            known_gl = [i for i in nonnum if i in known]
            if known_gl:
                affected.append({"corpus": corpus, "where": name,
                                 "ids": known_gl, "total_markers": len(ids)})

    print("  ALL non-numeric payloads found in a PMID slot:")
    if not all_nonnumeric:
        print("    none")
    for i, n in sorted(all_nonnumeric.items(), key=lambda x: -x[1]):
        print("    %-40s x%-3d %s" % (i, n,
              "KNOWN guideline id -> rewritten" if i in known
              else "not a known id -> dropped by G2, as before"))
    print()
    print("  stored answers containing a KNOWN guideline id in a PMID slot: %d"
          % len(affected))
    for a in affected:
        print("    %-52s %s" % (a["where"][:52], a["ids"]))

    if args.serve and affected:
        target = affected[0]
        print()
        print("  SERVING %s THROUGH finalise_answer_text" % target["where"])
        raw = dict((n, t) for _c, items in c.items() for n, t in items)[
            target["where"]]
        gid = target["ids"][0]
        m = re.search(r"[^\n]*\[\[PMID:\s*%s\s*\]\][^\n]*" % re.escape(gid),
                      raw)
        print("    BEFORE: %s" % (m.group(0).strip()[:220] if m else "?"))
        out, _blocks = E.finalise_answer_text(raw)
        short = re.sub(r"[-A-Z0-9]{4,}", "", gid)
        m2 = None
        for line in out.splitlines():
            if "ACP" in line or "AAE" in line or "ESE" in line:
                if any(w in line for w in ("—", "(20")):
                    m2 = line
                    break
        print("    AFTER : %s" % (m2.strip()[:260] if m2 else
                                  "(no rendered guideline line found)"))
        assert "[[PMID:%s]]" % gid not in out, "the slug survived the finaliser"
        print("    the raw [[PMID:%s]] is gone from the served answer" % gid)

    return 0


if __name__ == "__main__":
    sys.exit(main())
