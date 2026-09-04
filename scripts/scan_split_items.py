"""A22a / the literal `**` leak — the CORRECTED split-list-item detector.

THE INSTRUMENT WAS WRONG, NOT THE CORPUS. The first version of this scan looked
for a bare `N.` line and reported **0 split list items** across the stored
corpus, on which strength A22a and the `**` leak were re-filed as *renderer*
defects and moved to the browser lane. The corpus writes the number **bold** —
`**3.**` — so the detector matched nothing. Corrected, the same corpus gives
**30 of 114** blocks orphaning a list number and **24 of 114** cutting a bold
run. Both defects are text-layer, in `quarantine_unsourced_content`.

Three independent fingerprints, counted separately so that no single one
carries the finding alone:

  orphan_number   a line that is ONLY a list number — bare `3.` or bold
                  `**3.**` — immediately followed by a quarantine block. The
                  step's number was separated from its text.
  odd_stars       a block whose body contains an ODD number of `**` runs: a
                  bold run was cut by the block boundary.
  orphan_close    a body line ending in `**` with no opener on it — the
                  literal `**` RB saw rendered.

Importable: `scan_text(text)` for one document, `scan_corpus()` for all of
them. `tests/test_split_list_items.py` pins the corpus totals at zero.

Usage:  python scripts/scan_split_items.py [--verbose]
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.getcwd())

# A quarantine block is a run of consecutive `>` lines containing a header, in
# either the current or the legacy shape. Both are matched: A16b re-renders the
# archive on every read, so the legacy shape is live on a demo surface.
QUARANTINE_HEADER = re.compile(
    r"^>\s*(?:⚠\s*)?\*\*(?:NOT FROM THE EVIDENCE BASE — UNVERIFIED"
    r"|NOT CHECKED — not from any paper Curo retrieved)\*\*", re.M)
BLOCK_RUN = re.compile(r"(?:^>[^\n]*\n)+", re.M)

# THE FIX. `(?:\*\*)?` on both sides — the corpus writes `**3.**`, and without
# these four characters this whole scan reports zero.
ORPHAN_NUM = re.compile(r"^(?:\*\*)?(\d{1,2})[.)](?:\*\*)?\s*$")

# Lines inside a block that are structure, not step text. Their `**` are the
# block's own furniture and must not count toward the bold-run parity.
FURNITURE = (
    "⚠ **NOT FROM", "**NOT CHECKED", "_General clinical", "_Passages marked",
    "**Consult directly:**",
)


def _blocks(text):
    """(start, end, body) for every quarantine block in `text`."""
    return [(m.start(), m.end(), m.group(0))
            for m in BLOCK_RUN.finditer(text or "")
            if QUARANTINE_HEADER.search(m.group(0))]


def _body_lines(block):
    out = []
    for ln in block.split("\n"):
        s = ln.lstrip(">").strip()
        if not s or s.startswith(FURNITURE):
            continue
        out.append(s)
    return out


def scan_text(text, name=""):
    res = {"doc": name, "blocks": 0, "orphan_number": 0,
           "odd_stars": 0, "orphan_close": 0, "examples": []}
    for start, _end, block in _blocks(text):
        res["blocks"] += 1

        before = [ln for ln in text[max(0, start - 60):start].split("\n")
                  if ln.strip()]
        if before and ORPHAN_NUM.match(before[-1].strip()):
            res["orphan_number"] += 1
            if len(res["examples"]) < 4:
                res["examples"].append(
                    "ORPHAN_NUM %s -> %s"
                    % (before[-1].strip(), block[:70].replace("\n", " ")))

        body = _body_lines(block)
        joined = "\n".join(body)
        if joined.count("**") % 2 == 1:
            res["odd_stars"] += 1
            if len(res["examples"]) < 8:
                res["examples"].append(
                    "ODD_STARS " + joined[:90].replace("\n", " "))
        if any(ln.endswith("**") and ln.count("**") == 1 for ln in body):
            res["orphan_close"] += 1
    return res


def corpus():
    docs = []
    for p in sorted(glob.glob("learn_history/*.json")):
        try:
            rec = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        docs.append((os.path.basename(p), rec.get("answer") or ""))
    for p in sorted(glob.glob("answers/*.txt")):
        docs.append((os.path.basename(p),
                     open(p, encoding="utf-8", errors="replace").read()))
    try:
        import rag
        with rag.get_conn().cursor() as cur:
            cur.execute("SELECT id, answer FROM query_cache")
            for i, a in cur.fetchall():
                docs.append(("query_cache/%s" % i, a or ""))
    except Exception as e:
        print("[warn] query_cache unavailable: %s" % e)
    return docs


def scan_corpus(docs=None):
    docs = corpus() if docs is None else docs
    per_doc = [scan_text(t, n) for n, t in docs]
    tot = {k: sum(d[k] for d in per_doc)
           for k in ("blocks", "orphan_number", "odd_stars", "orphan_close")}
    tot["documents"] = len(per_doc)
    tot["documents_with_a_block"] = sum(1 for d in per_doc if d["blocks"])
    tot["documents_affected"] = sum(
        1 for d in per_doc
        if d["orphan_number"] or d["odd_stars"] or d["orphan_close"])
    return tot, per_doc


def main():
    tot, per_doc = scan_corpus()
    print("documents scanned                        : %d" % tot["documents"])
    print("documents with a quarantine block        : %d"
          % tot["documents_with_a_block"])
    print("quarantine blocks total                  : %d" % tot["blocks"])
    print("blocks preceded by an ORPHAN LIST NUMBER : %d" % tot["orphan_number"])
    print("blocks with an ODD `**` count (cut bold) : %d" % tot["odd_stars"])
    print("blocks with an ORPHAN CLOSING `**` line  : %d" % tot["orphan_close"])
    print("documents affected                       : %d"
          % tot["documents_affected"])
    if "--verbose" in sys.argv:
        print()
        for d in sorted(per_doc,
                        key=lambda x: -(x["orphan_number"] + x["odd_stars"])):
            if not (d["orphan_number"] or d["odd_stars"] or d["orphan_close"]):
                continue
            print("%-60s blocks=%-3d orphan=%-3d odd=%-3d close=%d"
                  % (d["doc"][:60], d["blocks"], d["orphan_number"],
                     d["odd_stars"], d["orphan_close"]))
            for e in d["examples"][:3]:
                print("      " + e[:140])
    return 0


if __name__ == "__main__":
    sys.exit(main())
