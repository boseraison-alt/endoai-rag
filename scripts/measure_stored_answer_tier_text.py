"""Item A (2026-09-06 night batch) — the REALISED defect, measured on stored answers.

Nine IADT guidelines sat in the library banded as level1/level2 studies with
scores. The ingest fixes the TABLE. A stored answer is stored TEXT, written when
the table said something else, so the question this script answers is:

    after the ingest, does any stored answer still SAY "level2" / a score /
    an impact factor about a row the table now calls a guideline with no score?

WHY IT IS MEASURED AND NOT ASSUMED. Rule 34: report a zero only after measuring
the input it guards. So this prints, in order:

  1. how many stored answers exist, PER CORPUS                (the input)
  2. how many cite ANY of the nine PMIDs                      (the population)
  3. the exact rendered citation line, and the tier heading it sits under

A zero at step 3 means nothing unless steps 1 and 2 are non-zero and printed.

THE FIRST VERSION OF THIS SCRIPT REPORTED A CLEAN ZERO AND WAS WRONG.
It scanned `query_cache` (20 rows) and `eval/logs/case_answers/` (17 files) and
found nothing, which would have been reported as "no stored answer is affected".
It had never looked in `answers/` — 170 files, and the one answer the batch
names is `answers/answer_20260426_223750.txt`. The zero was the detector's, not
the corpus's. That is the sixth instrument error in this project and the reason
every corpus below is counted out loud before any zero is believed.

Usage:  python scripts/measure_stored_answer_tier_text.py [--json OUT.json]
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

# The nine reclassified accessions, from the handover's table. Real rows.
NINE = {
    "32472740": ("IADT-INTRO-2020", "level1", 54.8),
    "32475015": ("IADT-FRACTURES-LUXATIONS-2020", "level2", 47.0),
    "32460393": ("IADT-AVULSION-2020", "level2", 47.0),
    "32458553": ("IADT-PRIMARY-2020", "level2", 47.0),
    "22230724": ("IADT-FRACTURES-LUXATIONS-2012", "level2", 37.0),
    "22409417": ("IADT-AVULSION-2012", "level2", 38.1),
    "22583659": ("IADT-PRIMARY-2012", "level2", 38.1),
    "17511833": ("IADT-AVULSION-2007", "level2", 38.1),
    "17635351": ("IADT-PRIMARY-2007", "level2", 38.1),
}

# A rendered evidence score and a rendered impact factor. Both are stale the
# moment the row becomes a guideline: score is NULL and impact_factor is NULL.
SCORE_RE = re.compile(r"\(Score:\s*([\d.]+)\s*/\s*100\)", re.I)
IF_RE = re.compile(r"\(?\bIF:\s*([\d.]+)\)?", re.I)
# Tier headings as the renderer writes them.
HEADING_RE = re.compile(
    r"^\s*(?:\*\*|##+\s*)?(Level\s+(?:I|II|III|IV|V)[^\n*#]{0,40}|"
    r"Cochrane[^\n*#]{0,40}|Clinical Practice Guidelines?[^\n*#]{0,40}|"
    r"Where the specialty stands[^\n*#]{0,40})",
    re.I | re.M)


def corpora():
    """Every place a stored answer lives. Counted separately, on purpose."""
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
                       ("eval/logs/case_answers/",
                        "eval/logs/case_answers/*.md"),
                       ("eval/logs/curricula/", "eval/logs/curricula/*.md")):
        files = sorted(Path(".").glob(pat))
        items = []
        for p in files:
            try:
                items.append((str(p), p.read_text(encoding="utf-8",
                                                  errors="replace")))
            except Exception:
                pass
        out[label] = items
    return out


def heading_above(text, pos):
    best = None
    for m in HEADING_RE.finditer(text):
        if m.start() < pos:
            best = m.group(1).strip()
        else:
            break
    return best or "(no tier heading above the citation)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_out", default="")
    args = ap.parse_args()

    print("=" * 78)
    print("ITEM A — THE REALISED DEFECT, ON STORED ANSWERS")
    print("=" * 78)

    c = corpora()
    print("  THE INPUT — every corpus counted before any zero is reported")
    for k, v in c.items():
        print("    %-26s %4d stored answers" % (k, len(v)))
    print("    %-26s %4d TOTAL" % ("", sum(len(v) for v in c.values())))
    print()

    findings = []
    for pmid, (gid, was_tier, was_score) in sorted(NINE.items()):
        rec = {"pmid": pmid, "guideline_id": gid, "was_tier": was_tier,
               "was_score": was_score, "citations": []}
        for corpus, items in c.items():
            for name, text in items:
                for m in re.finditer(re.escape(pmid), text):
                    ls = text.rfind("\n", 0, m.start()) + 1
                    le = text.find("\n", m.end())
                    line = text[ls: le if le > 0 else len(text)].strip()
                    if not line:
                        continue
                    hit = {
                        "corpus": corpus, "where": name,
                        "line": line[:300],
                        "heading": heading_above(text, m.start()),
                        "score_rendered": SCORE_RE.findall(line),
                        "if_rendered": IF_RE.findall(line),
                    }
                    if not any(h["where"] == name and h["line"] == hit["line"]
                               for h in rec["citations"]):
                        rec["citations"].append(hit)
        findings.append(rec)

    print("  THE POPULATION — stored answers citing each of the nine")
    print("  %-10s %-30s %10s" % ("pmid", "guideline id", "citations"))
    for r in findings:
        print("  %-10s %-30s %10d"
              % (r["pmid"], r["guideline_id"], len(r["citations"])))
    tot = sum(len(r["citations"]) for r in findings)
    print("  %-10s %-30s %10d" % ("", "TOTAL", tot))
    print()

    n_score = n_if = 0
    if tot:
        print("  THE DEFECT — every rendered citation, verbatim")
        for r in findings:
            for h in r["citations"]:
                print("    %s  (%s)" % (r["pmid"], r["guideline_id"]))
                print("      file    : %s" % h["where"])
                print("      heading : %s" % h["heading"])
                print("      renders : %s" % h["line"])
                stale = []
                if h["score_rendered"]:
                    stale.append("SCORE %s (table now: NULL)"
                                 % ", ".join(h["score_rendered"]))
                    n_score += 1
                if h["if_rendered"]:
                    stale.append("IMPACT FACTOR %s (forbidden signal; "
                                 "table now: NULL)" % ", ".join(h["if_rendered"]))
                    n_if += 1
                print("      STALE   : %s" % ("; ".join(stale) or "none"))
                print()

    print("  BAKED-IN COUNT (the number item A asks for)")
    print("    rendered citations of the nine, across all corpora   %d" % tot)
    print("    of those rendering a SCORE the table no longer has   %d" % n_score)
    print("    of those rendering an IMPACT FACTOR                  %d" % n_if)

    print()
    print("  WHAT THE TABLE SAYS NOW")
    conn = rag.get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT pmid, level_key, score, impact_factor, guideline_id, "
        "guideline_org, guideline_status, guideline_jurisdiction, journal, "
        "COALESCE(quarantine_reason,''), COALESCE(superseded_by,'') "
        "FROM endo_papers_rag WHERE pmid = ANY(%s) ORDER BY pmid",
        (list(NINE),))
    for (pmid, lk, sc, iff, gid, org, st, jur, jrnl, qr, sup) in cur.fetchall():
        print("    %-10s level_key=%-10s score=%-6s impact_factor=%-5s"
              % (pmid, lk, sc, iff))
        print("               guideline_id=%-30s org=%-6s status=%-12s juris=%s"
              % (gid or "-", org or "-", st or "-", jur or "-"))
        print("               journal=%s" % (jrnl or "-")[:70])
        if qr:
            print("               QUARANTINED: %s" % qr[:64])
        if sup:
            print("               SUPERSEDED_BY: %s" % sup)
    cur.close()
    conn.close()

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        json.dump({"corpora": {k: len(v) for k, v in c.items()},
                   "total_citations": tot, "with_score": n_score,
                   "with_if": n_if, "findings": findings},
                  open(args.json_out, "w"), indent=1)
        print("\n  wrote %s" % args.json_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
