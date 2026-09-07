"""Item A change 2 (2026-09-08) — resolve `unconfirmed_pmid` records by DOI.

Ten manifest records carry a DOI and journal that were verified while their
PubMed accession was not. A DOI search resolves the accession exactly — but
the accession is accepted ONLY when the PubMed title matches the manifest
title on a normalised comparison. A DOI that returns a PMID whose title is a
different document is a DOI transcription error, not a resolution, and taking
it would write an inference into the library as a fact.

`ACP-PARAMETERS-OF-CARE-2020` is pre-declared as a NO MATCH: its only PubMed
hit is an editorial. If it matches here, the normalisation is too loose and
that is the finding — not a resolution.

`AAE-DIAGNOSIS-2009` is excluded by design: its PMID is the companion
Background and Perspectives paper, which the manifest's own note records.

    python scripts/resolve_unconfirmed_by_doi.py            # report only
    python scripts/resolve_unconfirmed_by_doi.py --apply    # edit the manifest
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E  # noqa: E402

SEED = ROOT / "data" / "guidelines_seed.json"
TRY = ["AAE-VPT-2021", "ESE-ECR-2018", "ESE-TRAUMA-2021",
       "ESE-EXTRUSION-REPLANT-2021", "AAE-TRAUMA-2026", "AAE-MRONJ-2026",
       "AAE-REGENERATIVE-2013", "AAOM-CPS-ANTIRESORPTIVE-2019",
       "ACP-PARAMETERS-OF-CARE-2020"]
EXCLUDED = {"AAE-DIAGNOSIS-2009": "its PMID is the companion paper, by design"}

# EXCLUDED FROM THE WRITE, NOT FROM THE REPORT.
#
# The batch pre-declares ACP-PARAMETERS-OF-CARE-2020 a no-match: "the only
# PubMed hit is an editorial; do not take it." Its DOI resolves to 32681591,
# and the evidence says that premise is FALSE — J Prosthodont 2020, supplement
# S1, pages 3-147, no authors, no abstract. A 145-page corporate document is
# the Parameters of Care itself, not an editorial about it.
#
# It is still not taken. The instruction is explicit and the asymmetry decides
# it: declining leaves the status quo (the record stays a slug row, as today),
# while taking it wrongly writes a false accession into the manifest AND then
# retires the slug row with a redirect to it — a compounding error in the one
# field the `unconfirmed_pmid` mechanism exists to protect. The evidence goes
# in the report for RB to reverse.
EXCLUDED_FROM_WRITE = {
    "ACP-PARAMETERS-OF-CARE-2020":
        "batch pre-declared no-match; DOI resolves to 32681591, which the "
        "evidence shows is the document (J Prosthodont 2020;29(S1):3-147, no "
        "authors, no abstract), not an editorial. Reported, not written.",
}

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")


def norm(t):
    return _WS.sub(" ", _PUNCT.sub(" ", (t or "").lower())).strip()


def overlap(a, b):
    """Token overlap of the shorter title against the longer.

    Not equality: PubMed appends subtitles and strips punctuation differently.
    A match needs most of the SHORTER title's words to appear in the longer,
    which a different document cannot satisfy.
    """
    wa, wb = set(norm(a).split()), set(norm(b).split())
    if not wa or not wb:
        return 0.0
    short = wa if len(wa) <= len(wb) else wb
    return len(wa & wb) / len(short)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--threshold", type=float, default=0.80)
    args = ap.parse_args()

    man = json.loads(SEED.read_text(encoding="utf-8"))
    by_id = {g["id"]: g for g in man["guidelines"]}

    unconf = [g["id"] for g in man["guidelines"]
              if g.get("confidence") == "unconfirmed_pmid"]
    print("=" * 78)
    print("ITEM A CHANGE 2 — RESOLVE unconfirmed_pmid BY DOI  (%s)"
          % ("APPLY" if args.apply else "REPORT ONLY"))
    print("=" * 78)
    print("  unconfirmed_pmid records in the manifest: %d" % len(unconf))
    print("  excluded by design: %s" % EXCLUDED)
    print("  match threshold: %.2f token overlap of the shorter title"
          % args.threshold)
    print()

    results = []
    for gid in TRY:
        rec = by_id.get(gid)
        if not rec:
            print("  %-32s NOT IN THE MANIFEST" % gid)
            continue
        doi = (rec.get("doi") or "").strip()
        if not doi:
            print("  %-32s no DOI" % gid)
            results.append((gid, "", [], "", rec.get("title", ""), False))
            continue
        try:
            r = E.ncbi_get(f"{E.NCBI_EUTILS_BASE}/esearch.fcgi",
                           params=E._ncbi_params({
                               "db": "pubmed", "term": '"%s"[doi]' % doi,
                               "retmode": "json", "retmax": 5}), timeout=25)
            ids = [str(i) for i in
                   r.json().get("esearchresult", {}).get("idlist", [])]
        except Exception as ex:
            print("  %-32s esearch failed: %s" % (gid, ex))
            continue
        pm_title, match, chosen = "", False, ""
        if ids:
            recs = E._fetch_pubtypes_and_abstracts(ids)
            for p in ids:
                t = (recs.get(p) or {}).get("title", "")
                ov = overlap(t, rec.get("title", ""))
                if ov >= args.threshold:
                    pm_title, match, chosen = t, True, p
                    break
                if not pm_title:
                    pm_title = t
        results.append((gid, doi, ids, pm_title, rec.get("title", ""), match))
        print("  %-32s %s" % (gid, "MATCH -> %s" % chosen if match else "no match"))
        print("      doi   : %s" % doi)
        print("      pmids : %s" % (ids or "none"))
        if pm_title:
            print("      pubmed: %s" % pm_title[:88])
            print("      manif : %s" % (rec.get("title") or "")[:88])
            print("      overlap: %.2f" % overlap(pm_title, rec.get("title", "")))
        time.sleep(0.3)

    matched_all = [(g, i) for g, _d, ids, _pt, _mt, m in results if m
                   for i in [ids[0]]]
    matched = [(g, i) for g, i in matched_all if g not in EXCLUDED_FROM_WRITE]
    held = [(g, i) for g, i in matched_all if g in EXCLUDED_FROM_WRITE]
    print()
    print("  MATCHED: %d" % len(matched_all))
    for g, i in matched_all:
        print("    %-32s -> %-10s %s"
              % (g, i, "(HELD BACK)" if g in EXCLUDED_FROM_WRITE else ""))
    if held:
        print()
        print("  HELD BACK FROM THE WRITE — reported for RB, not applied:")
        for g, i in held:
            print("    %-32s -> %s" % (g, i))
            print("      %s" % EXCLUDED_FROM_WRITE[g])
    print()
    print("  WILL WRITE: %d" % len(matched))

    if args.apply and matched:
        # THE LINE IS REGENERATED FROM THE PARSED RECORD, not string-patched.
        #
        # The first version appended a `note` by string surgery:
        #   new.rstrip().rstrip("}").rstrip() + ', "note": "..." }'
        # Every record line ends `" },` — a trailing COMMA — so `rstrip("}")`
        # stripped nothing and the result was malformed JSON. It was written
        # to disk before the parse check caught it, and the manifest had to be
        # restored from a backup. Dumping the dict cannot produce invalid JSON.
        want = dict(matched)
        lines = SEED.read_text(encoding="utf-8").splitlines(True)
        out, n = [], 0
        for line in lines:
            gid = None
            for g in want:
                if '"id": "%s"' % g in line:
                    gid = g
                    break
            if gid is None:
                out.append(line)
                continue
            stripped = line.strip()
            trailing = "," if stripped.endswith(",") else ""
            rec = json.loads(stripped.rstrip(","))
            rec["pmid"] = want[gid]
            rec["confidence"] = "confirmed"
            note = ("PMID %s resolved by DOI search on 2026-09-08 "
                    "(esearch '<doi>[doi]', normalised title match)."
                    % want[gid])
            rec["note"] = (rec["note"] + " " + note) if rec.get("note") else note
            indent = line[:len(line) - len(line.lstrip())]
            out.append(indent + json.dumps(rec, ensure_ascii=False)
                       + trailing + "\n")
            n += 1
        text = "".join(out)
        json.loads(text)          # refuse to write anything unparseable
        SEED.write_text(text, encoding="utf-8")
        print("\n  APPLIED — %d manifest record(s) updated." % n)
    elif matched:
        print("\n  REPORT ONLY — re-run with --apply to edit the manifest.")

    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    json.dump([{"id": g, "doi": d, "pmids": i, "pubmed_title": pt,
                "manifest_title": mt, "match": m}
               for g, d, i, pt, mt, m in results],
              open("eval/reports/night10_doi_resolution.json", "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
