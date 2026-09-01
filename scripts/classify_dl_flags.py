"""Assemble the Deep Learning citation-support flags for hand judgement.

The Deep Learning support check has been measured twice — 24/118 (20.3%) and
13/116 (11.2%) on two laser curricula — and nobody has looked at WHY a
curriculum module flags higher than a Review answer (4.3%). This script does
for Deep Learning exactly what CURO_HANDOVER §5[B] did for Review: recover the
FULL claim sentence beside the abstract the checker actually saw, so each pair
can be judged rather than guessed at.

Why the full claim has to be recovered: `evidence_mapping.jsonl` stores
`claim[:160]`, and a curriculum's claims are long. Judging a truncated claim
is judging a different claim.

Why the abstract has to be shown TWICE: `verify_citation_support` passes
`abstract[:_SUPPORT_ABSTRACT_CHARS]` (1200 chars) to the judge, while the
library now stores whole abstracts averaging 1,631 characters. A claim about a
paper's CONCLUSION can therefore be judged against an excerpt that stops
before the conclusion — which is the truncation bug this project just spent a
batch removing from ingest, still live inside the checker. The report prints
what the judge saw and what the row holds, so "checker artifact" can be
distinguished from "genuinely unsupported" instead of assumed.

    python scripts/classify_dl_flags.py            # write the worksheet
    python scripts/classify_dl_flags.py --summary  # counts only

Read-only. It touches no column and writes nothing but its worksheet.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EVMAP = ROOT / "evidence_mapping.jsonl"

# The two runs whose rates the handover records. Identified by summing the
# per-module `verify_citation_support` records inside each window: the first
# is 118 checked / 24 flagged, the second 116 / 13. Both are the same laser
# curriculum question, run 8 minutes apart.
RUNS = {
    "A": {
        "label":  "curriculum A — 24/118 = 20.3%",
        "from":   "2026-08-31T23:10:01",
        "to":     "2026-08-31T23:11:26",
        "answer": "learn_history/20260831_231522_use_of_lasers_in_root_canal_disinfection.json",
    },
    "B": {
        "label":  "curriculum B — 13/116 = 11.2%",
        "from":   "2026-08-31T23:18:02",
        "to":     "2026-08-31T23:19:18",
        "answer": "learn_history/20260831_232314_use_of_lasers_in_root_canal_disinfection.json",
    },
}


def _support_records(lo, hi):
    out = []
    with EVMAP.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("function") != "verify_citation_support":
                continue
            if lo <= rec.get("ts", "")[:19] <= hi:
                out.append(rec)
    return out


def _strip_support_blocks(text):
    """Drop the citation-support blocks before recovering claims.

    `_append_support_warnings` renders each flag as
    `> - [[PMID:N]] cited for: "<claim>"`, so the stitched curriculum carries
    the checker's own output back into the document — with live `[[PMID:N]]`
    markers in it. `_extract_claim_citation_pairs` cannot tell those from real
    citations, and matching a flag against them returns the warning block as
    the claim it is warning about.

    The checker itself never saw this: it runs on the module BEFORE the block
    is appended. This strip keeps the recovery honest about that. It is also a
    small finding in its own right — anything that re-runs the extractor over a
    rendered answer will count the warnings as citations.
    """
    return "\n".join(l for l in (text or "").splitlines()
                     if not l.lstrip().startswith(">"))


def _full_claims(answer_text):
    """Every (claim, pmid) pair the real extractor finds in the stitched answer.

    Uses `endo_ai._extract_claim_citation_pairs` rather than a re-implementation:
    the claim UNIT is the thing under investigation here, so a local
    approximation of it would answer a different question.
    """
    from endo_ai import _extract_claim_citation_pairs
    return _extract_claim_citation_pairs(_strip_support_blocks(answer_text))


def _match(flag, pairs):
    """Find the full claim behind a 160-char stored claim.

    Matched on the stored prefix AND the pmid: the same prefix can appear under
    two different citations (a decision-tree branch cites three papers on one
    line), and attaching the wrong pmid to a claim is precisely the error being
    investigated.
    """
    stub = (flag.get("claim") or "")[:150]
    pmid = str(flag.get("pmid"))
    hits = [c for c, p in pairs if str(p) == pmid and c.startswith(stub[:120])]
    if hits:
        return max(hits, key=len), "prefix"
    # The stitcher is an LLM told to reproduce module text verbatim, which is
    # not a guarantee. Fall back to the longest pair for that pmid that shares
    # a distinctive run of the stored claim.
    core = stub[20:90].strip()
    if core:
        hits = [c for c, p in pairs if str(p) == pmid and core in c]
        if hits:
            return max(hits, key=len), "fuzzy"
    return None, "unmatched"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--out", default="eval/logs/dl_flag_worksheet.md")
    args = ap.parse_args()

    from rag import get_cached_abstracts_bulk
    import endo_ai

    rows = []
    for key, run in RUNS.items():
        recs = _support_records(run["from"], run["to"])
        checked = sum(int(r.get("checked") or 0) for r in recs)
        flagged = sum(int(r.get("n_flagged") or 0) for r in recs)
        print(f"{run['label']}: {len(recs)} module checks, "
              f"{flagged}/{checked} = {100.0 * flagged / checked:.1f}%")
        doc = json.loads((ROOT / run["answer"]).read_text(encoding="utf-8"))
        pairs = _full_claims(doc.get("answer") or "")
        for mi, rec in enumerate(recs, 1):
            for flag in rec.get("flags") or []:
                full, how = _match(flag, pairs)
                rows.append({
                    "run": key, "module": mi, "pmid": str(flag["pmid"]),
                    "stored_claim": flag.get("claim") or "",
                    "full_claim": full or "", "matched": how,
                })

    pmids = sorted({r["pmid"] for r in rows})
    abstracts = get_cached_abstracts_bulk(pmids)
    print(f"\n{len(rows)} flagged pairs, {len(pmids)} distinct PMIDs, "
          f"{sum(1 for p in pmids if (abstracts.get(p) or {}).get('abstract'))} "
          f"with a stored abstract")

    cap = endo_ai._SUPPORT_ABSTRACT_CHARS
    over = [p for p in pmids
            if len(((abstracts.get(p) or {}).get("abstract") or "")) > cap]
    print(f"{len(over)} of {len(pmids)} cited abstracts are longer than the "
          f"checker's {cap}-char excerpt — the judge did not see the tail of "
          f"those, and a structured abstract puts CONCLUSIONS last")

    unmatched = [r for r in rows if r["matched"] == "unmatched"]
    print(f"{len(unmatched)} claim(s) could not be matched back to the stitched "
          f"answer (the stitcher rewrote them)")

    if args.summary:
        return 0

    out = [f"# Deep Learning citation-support flags — hand-judgement worksheet",
           "",
           f"{len(rows)} flagged claim-citation pairs from two laser curricula.",
           f"Checker excerpt cap: **{cap} chars**. "
           f"{len(over)}/{len(pmids)} cited abstracts exceed it.",
           ""]
    for i, r in enumerate(rows, 1):
        rec = abstracts.get(r["pmid"]) or {}
        ab = rec.get("abstract") or ""
        title = rec.get("title") or "(no title stored)"
        seen = ab[:cap]
        out += [
            f"## {i}. run {r['run']} module {r['module']} — PMID {r['pmid']}",
            "",
            f"**Cited paper:** {title}",
            "",
            f"**Claim ({r['matched']}):** {r['full_claim'] or r['stored_claim']}",
            "",
            f"**Abstract stored:** {len(ab)} chars. "
            f"**Judge saw:** {len(seen)} chars"
            + (f" — TAIL WITHHELD ({len(ab) - len(seen)} chars)" if len(ab) > cap else "")
            + ".",
            "",
            "```",
            seen if seen else "(no abstract stored)",
            "```",
            "",
        ]
        if len(ab) > cap:
            out += ["**Tail the judge did NOT see:**", "", "```", ab[cap:], "```", ""]
    path = ROOT / args.out
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"\nworksheet -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
