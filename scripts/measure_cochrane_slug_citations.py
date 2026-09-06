"""Item A (2026-09-07) — who cites the two Cochrane slug rows?

Two Cochrane reviews are in the library twice: once by PMID at `cochrane` with
a score, once by manifest slug at `guideline` with score NULL. The slug rows
are about to be RETIRED, so the question that has to be answered first is
whether anything cites them — a retire that silently breaks a stored citation
is worse than the duplicate.

Counted per key, and the bare accessions are counted too: an answer can cite
`CD005296` without the `COCHRANE-` prefix, and a sweep for the prefixed form
alone would report a false zero.

Rule 34: the input is counted before any zero is reported.

    python scripts/measure_cochrane_slug_citations.py [--json OUT.json]
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

import rag  # noqa: E402

KEYS = {
    "COCHRANE-CD005296": "36512807",
    "COCHRANE-CD004969": "31145805",
    "CD005296": "36512807",
    "CD004969": "31145805",
}


def corpora():
    out = {}
    conn = rag.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, answer, papers FROM query_cache")
    out["query_cache"] = [("query_cache#%s" % r[0],
                           (r[1] or "") + "\n" + json.dumps(r[2] or {}))
                          for r in cur.fetchall()]
    cur.close()
    conn.close()
    for label, pat in (("answers/", "answers/*.txt"),
                       ("eval/logs/case_answers/", "eval/logs/case_answers/*.md")):
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
    ap.add_argument("--json", dest="json_out", default="")
    args = ap.parse_args()

    print("=" * 78)
    print("ITEM A — STORED ANSWERS CITING THE TWO COCHRANE SLUG ROWS")
    print("=" * 78)
    c = corpora()
    print("  THE INPUT")
    for k, v in c.items():
        print("    %-26s %4d stored answers" % (k, len(v)))
    total_answers = sum(len(v) for v in c.values())
    print("    %-26s %4d TOTAL" % ("", total_answers))
    print()

    findings = {}
    for key, target in KEYS.items():
        hits = []
        # Word-bounded so CD005296 does not also match inside
        # COCHRANE-CD005296 and double-count the same citation.
        rx = re.compile(r"(?<![A-Za-z0-9-])%s(?![A-Za-z0-9])" % re.escape(key))
        for corpus, items in c.items():
            for name, text in items:
                for m in rx.finditer(text):
                    ls = text.rfind("\n", 0, m.start()) + 1
                    le = text.find("\n", m.end())
                    line = text[ls: le if le > 0 else len(text)].strip()
                    # A BARE ACCESSION IS NOT A CITATION, and counting it as
                    # one overstates the blast radius of the retire. Cochrane
                    # article numbers are the journal's PAGE field, so
                    # `"pages": "CD005296"` appears inside the papers-JSON of
                    # the surviving PMID row. That is metadata about the row
                    # being kept, not a reference to the slug row being
                    # retired.
                    ctx = text[max(0, m.start() - 60): m.start()]
                    is_pages = bool(re.search(r'"pages"\s*:\s*"?$', ctx))
                    hits.append({"corpus": corpus, "where": name,
                                 "line": line[:220],
                                 "kind": "pages-field" if is_pages
                                         else "prose/citation"})
        findings[key] = {"target_pmid": target, "hits": hits}

    print("  PER KEY")
    print("  %-22s %-10s %10s %12s" % ("key", "-> pmid", "citations",
                                       "pages-field"))
    for key in ("COCHRANE-CD005296", "COCHRANE-CD004969",
                "CD005296", "CD004969"):
        f = findings[key]
        cites = [h for h in f["hits"] if h["kind"] != "pages-field"]
        pages = [h for h in f["hits"] if h["kind"] == "pages-field"]
        print("  %-22s %-10s %10d %12d"
              % (key, f["target_pmid"], len(cites), len(pages)))
    tot = sum(1 for f in findings.values() for h in f["hits"]
              if h["kind"] != "pages-field")
    totp = sum(1 for f in findings.values() for h in f["hits"]
               if h["kind"] == "pages-field")
    print("  %-22s %-10s %10d %12d" % ("", "TOTAL", tot, totp))

    if tot:
        print()
        print("  EVERY CITATION, VERBATIM")
        for key in findings:
            for h in findings[key]["hits"]:
                print("    [%s] %s" % (key, h["where"]))
                print("        %s" % h["line"])

    # Also: do the PMID rows themselves get cited? That is the number that says
    # whether the retire is invisible to readers or merely harmless.
    print()
    print("  FOR CONTRAST — citations of the PMID rows that survive")
    for pmid in ("36512807", "31145805"):
        n = 0
        rx = re.compile(r"(?<!\d)%s(?!\d)" % pmid)
        for corpus, items in c.items():
            for _name, text in items:
                n += len(rx.findall(text))
        print("    %-10s %d" % (pmid, n))

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        json.dump({"total_answers": total_answers,
                   "per_key": {k: len(v["hits"]) for k, v in findings.items()},
                   "findings": findings}, open(args.json_out, "w"), indent=1)
        print("\n  wrote %s" % args.json_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
