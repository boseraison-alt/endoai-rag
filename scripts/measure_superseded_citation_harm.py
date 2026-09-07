"""Item 3 — the harm realised: stored answers citing the five leaked rows.

The leak count says how often a superseded guideline reached the CONTEXT. This
says how often it reached a CLINICIAN, which is the number that matters.

Two things are counted, and they are different:

  cited            a stored answer cites one of the five
  cited unnoticed  ...and the SERVED rendering carries no supersession notice
                   anywhere in the citing sentence

The second is the harm. `_guideline_supersession_notice` exists precisely so a
superseded document is never served as a current position, and the whole point
of measuring the rendered text rather than the stored text is that the notice is
applied on the way out — the same principle as the redirect rewrite and the
animal label.

Every corpus is counted out loud before anything is reported (rule 34).

    python scripts/measure_superseded_citation_harm.py
"""
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
import rag  # noqa: E402

LEAKED = {
    "22409417": "IADT-AVULSION-2012",
    "17180780": "ESE-QG-2006",
    "17511833": "IADT-AVULSION-2007",
    "22230724": "IADT-FRACTURES-LUXATIONS-2012",
    "30664240": "ESE-DEEPCARIES-2019",
}
CITE = re.compile(r"\[\[PMID:(\d+)\]\]|\[PMID:\s*(\d+)\]|\[\[GL:([^\]]+)\]\]")
# What a supersession notice looks like once rendered, in any of its forms.
NOTICE = re.compile(
    r"supersed|replaced by|withdrawn|no longer current|superseded by", re.I)


def sentences(text):
    return re.split(r"(?<=[.!?])\s+", text or "")


def corpora():
    out = {}
    d = ROOT / "answers"
    out["answers/"] = sorted(d.glob("*.txt")) if d.exists() else []
    d = ROOT / "eval" / "logs" / "case_answers"
    out["eval/logs/case_answers/"] = sorted(d.glob("*")) if d.exists() else []
    d = ROOT / "eval" / "logs" / "curricula"
    out["eval/logs/curricula/"] = sorted(d.glob("*")) if d.exists() else []
    return out


def main():
    print("=" * 78)
    print("ITEM 3 — THE HARM REALISED: STORED ANSWERS CITING THE FIVE")
    print("=" * 78)
    for pmid, gid in LEAKED.items():
        print("  %-10s %s" % (pmid, gid))
    print()
    print("  CORPORA COUNTED (rule 34)")
    files = corpora()
    for name, fs in files.items():
        print("    %-28s %4d files" % (name, len(fs)))
    conn = rag.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM query_cache")
    print("    %-28s %4d rows" % ("query_cache", cur.fetchone()[0]))
    print()

    docs = cited = unnoticed = 0
    hits, examples = [], []

    def scan(label, ident, stored):
        nonlocal docs, cited, unnoticed
        docs += 1
        if not any(p in stored or g in stored
                   for p, g in LEAKED.items()):
            return
        # THE SERVED TEXT, not the stored text: the notice is applied on the
        # way out, so measuring the file would count harm the reader never saw.
        try:
            out = E.finalise_answer_text(stored)
            served = out[0] if isinstance(out, tuple) else out
        except Exception:
            served = stored
        for sent in sentences(served):
            found = set()
            for m in CITE.finditer(sent):
                key = m.group(1) or m.group(2) or (m.group(3) or "").strip()
                if key in LEAKED:
                    found.add(key)
                elif key in LEAKED.values():
                    found.add(key)
            if not found:
                continue
            cited += 1
            if not NOTICE.search(sent):
                unnoticed += 1
                hits.append({"corpus": label, "id": ident,
                             "keys": sorted(found),
                             "sentence": " ".join(sent.split())[:200]})
                if len(examples) < 4:
                    examples.append((ident, sorted(found),
                                     " ".join(sent.split())[:170]))

    for name, fs in files.items():
        for f in fs:
            try:
                scan(name, f.name,
                     f.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                pass
    cur.execute("SELECT id, answer FROM query_cache")
    for rid, ans in cur.fetchall():
        scan("query_cache", "id=%s" % rid, ans or "")
    cur.close()
    conn.close()

    print("  documents scanned                       : %d" % docs)
    print("  citing sentences naming one of the five : %d" % cited)
    print("  ...WITHOUT a supersession notice        : %d" % unnoticed)
    print()
    if examples:
        print("  THE HARM, in the served sentence:")
        for ident, keys, sent in examples:
            print("    %s  %s" % (ident, ", ".join(keys)))
            print("      \"%s\"" % sent)
            print()
    else:
        print("  None. Note the denominator: this is a real zero only if")
        print("  `citing sentences` above is non-zero.")

    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    json.dump({"leaked": LEAKED, "documents": docs, "cited": cited,
               "unnoticed": unnoticed, "hits": hits},
              open("eval/reports/item3_superseded_citation_harm.json", "w",
                   encoding="utf-8"), indent=1)
    print("  wrote eval/reports/item3_superseded_citation_harm.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
