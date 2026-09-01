"""How much abstract does the "longest paragraph" heuristic throw away?

Four call sites reduce a fetched abstract to its longest paragraph:
`endo_ai._parse_efetch_batch` (the LIVE retrieval path, and the writer that
populates `abstract_cache`), `app.get_abstract`'s L3 fallback,
`ingest_classics._fetch_paper`, and `ingest_aae_guidelines`. All four parse
`rettype=abstract&retmode=text`, which is a rendered citation page, not data.

This is the same data-loss class as the 1,000/1,200-character ingest cap fixed
in `grounding-v1` — a structured abstract puts CONCLUSIONS last — but it is a
SELECTION rather than a slice, so that fix does not touch it and the truncation
signature (a length landing on a round number) cannot detect it.

The measurement compares, per PMID, three things:
  * whole   — `<AbstractText>` elements from efetch XML, joined with their
              section labels. This is what the paper actually says.
  * collapse — what the production heuristic returns from the text dump.
  * delta   — characters lost, and whether a CONCLUSIONS section is among them.

    python scripts/measure_paragraph_collapse.py --sample 60

Read-only against PubMed and the database. Writes nothing.
"""
import argparse
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# Section labels PubMed uses for the part a truncation or a collapse is most
# likely to remove, and the part a clinical claim most often rests on.
_CONCLUSION_RE = re.compile(r"\b(conclusion|clinical significance|interpretation)",
                            re.IGNORECASE)


def _params(extra):
    import os
    p = {"db": "pubmed", "tool": "endo-ai-rag", "email": os.getenv("NCBI_EMAIL", "")}
    key = os.getenv("NCBI_API_KEY")
    if key:
        p["api_key"] = key
    p.update(extra)
    return p


def fetch_text(pmids):
    r = requests.get(f"{EUTILS}/efetch.fcgi", timeout=30, params=_params({
        "id": ",".join(pmids), "rettype": "abstract", "retmode": "text"}))
    r.raise_for_status()
    return r.text


def fetch_xml(pmids):
    """Whole abstracts, with their section labels, from the XML.

    `MedlineCitation/PMID` is explicit, never `.//PMID`: a record's
    CommentsCorrectionsList carries the PMIDs of the papers it corrects, and a
    descendant search returns whichever comes first. That bug wrote one
    paper's abstract onto another's row once already.
    """
    r = requests.get(f"{EUTILS}/efetch.fcgi", timeout=30, params=_params({
        "id": ",".join(pmids), "retmode": "xml"}))
    r.raise_for_status()
    root = ET.fromstring(r.text)
    out = {}
    for art in list(root.findall(".//PubmedArticle")) + list(root.findall(".//PubmedBookArticle")):
        pid_el = art.find("./MedlineCitation/PMID")
        if pid_el is None:
            pid_el = art.find("./BookDocument/PMID")
        if pid_el is None or not (pid_el.text or "").strip():
            continue
        parts = []
        for at in art.findall(".//Abstract/AbstractText"):
            label = (at.get("Label") or "").strip()
            # itertext(): an AbstractText can contain <i>/<sup> children, and
            # `.text` alone silently returns only the run before the first tag.
            body = "".join(at.itertext()).strip()
            if not body:
                continue
            parts.append(f"{label}: {body}" if label else body)
        out[pid_el.text.strip()] = " ".join(parts)
    return out


def collapse(entry_text):
    """The production heuristic, copied so the comparison measures IT.

    Deliberately duplicated rather than imported: importing would couple the
    measurement to whatever the code becomes, and the point is to record what
    the code did BEFORE the change.
    """
    paragraphs, current = [], []
    for line in entry_text.split("\n"):
        line = line.rstrip()
        if line.strip():
            current.append(line.strip())
        else:
            if current:
                paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    candidates = [p for p in paragraphs if len(p) >= 200]
    return max(candidates, key=len) if candidates else ""


_ENTRY_SPLIT = re.compile(r"\n\n(?=\d+\.\s+[A-Z])")
_PMID_RE     = re.compile(r"^PMID:\s*(\d+)", re.MULTILINE)


def split_entries(raw):
    out = {}
    for entry in _ENTRY_SPLIT.split(raw or ""):
        m = _PMID_RE.search(entry)
        if m:
            out[m.group(1).strip()] = entry
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=60,
                    help="how many library PMIDs to measure")
    ap.add_argument("--batch", type=int, default=20)
    args = ap.parse_args()

    from rag import get_conn
    conn = get_conn()
    cur = conn.cursor()
    # Deterministic but SPREAD: `ORDER BY pmid` draws the oldest rows in the
    # library, which are 1990s single-paragraph abstracts — the one stratum the
    # collapse cannot hurt. The first run of this script measured exactly that
    # and reported 0% loss on a biased draw. md5 orders reproducibly without
    # correlating with age, journal or structure.
    cur.execute("""
        SELECT pmid FROM endo_papers_rag
        WHERE abstract IS NOT NULL AND length(abstract) > 200
        ORDER BY md5(pmid)
        LIMIT %s;
    """, (args.sample,))
    pmids = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    print(f"{len(pmids)} PMIDs sampled from the library\n")

    rows = []
    for i in range(0, len(pmids), args.batch):
        chunk = pmids[i:i + args.batch]
        try:
            text = fetch_text(chunk)
            xml  = fetch_xml(chunk)
        except Exception as e:
            print(f"  batch {i}: fetch failed ({e}) — skipped")
            continue
        entries = split_entries(text)
        for pmid in chunk:
            whole = (xml.get(pmid) or "").strip()
            coll  = collapse(entries.get(pmid, "")).strip()
            if not whole:
                continue
            rows.append((pmid, len(whole), len(coll), whole, coll))
        time.sleep(0.4)

    if not rows:
        print("nothing measured")
        return 1

    lost = [r for r in rows if r[2] < r[1] - 20]
    lost_concl = [r for r in lost
                  if _CONCLUSION_RE.search(r[3]) and not _CONCLUSION_RE.search(r[4])]
    print(f"{'pmid':>10} {'whole':>7} {'collapsed':>10} {'kept':>6}  conclusion lost")
    for pmid, lw, lc, whole, coll in rows:
        flag = ("YES" if (_CONCLUSION_RE.search(whole)
                          and not _CONCLUSION_RE.search(coll)) else "")
        print(f"{pmid:>10} {lw:>7} {lc:>10} {100.0 * lc / lw:>5.0f}%  {flag}")

    print(f"\n{len(rows)} measured")
    structured = [r for r in rows if re.search(r"\b[A-Z][A-Z /&-]{3,}:\s", r[3])]
    print(f"{len(structured)} of them are structured (labelled sections)")
    print(f"{len(lost)} ({100.0 * len(lost) / len(rows):.1f}%) lose more than 20 chars "
          f"to the collapse")
    print(f"{len(lost_concl)} ({100.0 * len(lost_concl) / len(rows):.1f}%) lose a "
          f"CONCLUSIONS / CLINICAL SIGNIFICANCE section entirely")
    kept = sum(r[2] for r in rows) / max(1, sum(r[1] for r in rows))
    print(f"the collapse keeps {100.0 * kept:.1f}% of the abstract text overall")

    # What the collapse actually drops, when it drops anything. A copyright
    # line is not the same finding as a conclusions paragraph, and reporting
    # one number for both would hide the difference that matters.
    if lost:
        print(f"\nthe {len(lost)} lossy rows, worst first:")
        for pmid, lw, lc, whole, coll in sorted(lost, key=lambda r: r[2] / r[1])[:25]:
            missing = whole
            for token in re.split(r"\s+", coll):
                pass
            print(f"  {pmid}  whole={lw} collapsed={lc} kept={100.0 * lc / lw:.0f}%")
            print(f"     whole  ...{whole[max(0, lc - 60):lc + 260]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
