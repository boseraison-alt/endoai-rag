"""
Targeted ingest of the OSU / Reader anesthesia canon (`classics-v1` B3).

WHY THIS AND NOT A SCORING CHANGE. B2 measured the cause instead of guessing
it, and the answer was the plainest of the four the item allows for:

    in the library        5 of 124
    never ingested      119 of 124
    tiered "classic"      0 of 5    (the exemption has never fired on one)

The canon is not being down-ranked, mis-tiered, or lost to a similarity floor.
It is not there. So the fix is an ingest, and specifically NOT a venue weight —
invariant 22, decided by RB on 2026-09-02.

HOW IT DIFFERS FROM `ingest_dens_evaginatus.py`. That script had to find its
topic with synonym queries and then gate the results for relevance, because a
zero-hit tier query gets broadened into the general endodontic corpus. Here the
PMID list already exists as a reviewed fixture, so the query is the list
itself — `NNNNN[uid] OR ...` — and relevance is guaranteed by construction.
Every paper still goes through `fetch_papers`, so tier assignment, the per-tier
quality floor, COI, MEDLINE status and correction/retraction provenance are all
computed by the same code that ingests anything else. Nothing here hand-writes
a tier.

THE SCORE FLOOR IS THE REAL DECISION. `learn_from_live_results` has a flat
write-back floor of 50, and this corpus is 1987-2019: the recency term gives a
1998 paper 1.0 of 15, so a well-powered RCT from the canon lands in the 30s
BECAUSE IT IS OLD, which is the whole reason it is a classic. `case-v2.1` hit
the same wall on dens evaginatus and answered it the same way — a --min-score
on ONE hand-written, list-scoped ingest whose membership has already been
reviewed, never a global change to the floor. The global floor is
`WORKLIST.md` §1.5 and it wants its own measured batch.

    python scripts/ingest_osu_corpus.py                    # dry run
    python scripts/ingest_osu_corpus.py --min-score 30     # dry run, lower floor
    python scripts/ingest_osu_corpus.py --min-score 30 --apply
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import endo_ai  # noqa: E402
import rag  # noqa: E402

CORPUS = ROOT / "eval" / "fixtures" / "osu_anesthesia_corpus.json"
OUT = ROOT / "eval" / "logs" / "osu_ingest.json"
PRE = ROOT / "eval" / "logs" / "osu_ingest_pre_pmids.json"

# One tier filter per pass, exactly as `build_evidence_base` joins them, so a
# paper is tiered by the design filter it actually matches. Level 2 and 3b are
# included here unlike the DE ingest: this corpus IS trial literature, and
# prospective/case-control designs are where a good part of it lives.
TIERS = ("cochrane", "level1", "level2", "level3a", "level3b", "level4",
         "level5")


def tier_filter(level_key: str) -> str:
    if level_key == "cochrane":
        return endo_ai.COCHRANE_TERM
    terms = {
        "level1":  endo_ai.LEVEL_1_TERMS,
        "level2":  endo_ai.LEVEL_2_TERMS,
        "level3a": endo_ai.LEVEL_3A_TERMS,
        "level3b": endo_ai.LEVEL_3B_TERMS,
        "level4":  endo_ai.LEVEL_4_TERMS,
        "level5":  endo_ai.LEVEL_5_TERMS,
    }[level_key]
    return " OR ".join(terms)


def library_pmids(pmids: list) -> set:
    conn = rag.get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT pmid FROM endo_papers_rag WHERE pmid = ANY(%s)",
                    (list(pmids),))
        return {r[0] for r in cur.fetchall()}
    finally:
        cur.close()
        conn.close()


def row(p: dict) -> dict:
    return {"pmid": p.get("pmid"), "year": p.get("year"),
            "level_key": p.get("level_key"), "score": p.get("score"),
            "title": (p.get("title") or "")[:130],
            "has_abstract": bool((p.get("abstract") or "").strip())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--min-score", type=float, default=50.0)
    ap.add_argument("--batch", type=int, default=40,
                    help="PMIDs per esearch. The uid OR-list is long; this "
                         "keeps each query inside a sane URL length.")
    args = ap.parse_args()

    if not CORPUS.exists():
        sys.exit(f"missing {CORPUS} — run scripts/build_osu_corpus.py first")
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))["papers"]
    wanted = [p["pmid"] for p in corpus]
    wanted_set = set(wanted)

    print(f"{'APPLY' if args.apply else 'DRY RUN'}   "
          f"min_score={args.min_score}\n")
    print(f"corpus:            {len(wanted)}")

    before = library_pmids(wanted)
    print(f"already in library: {len(before)}")
    print(f"missing:            {len(wanted) - len(before)}\n")

    # The pre-insert PMID set, so the addition is exactly reversible.
    PRE.parent.mkdir(parents=True, exist_ok=True)
    PRE.write_text(json.dumps(sorted(before), indent=1), encoding="utf-8")

    # `fetch_papers`' own write-back is off; this script writes once, at the
    # end, after the split has been printed and reviewed.
    endo_ai.LIBRARY_WRITE_BACK = False

    found = {}
    for level_key in TIERS:
        tf = tier_filter(level_key)
        got = []
        for i in range(0, len(wanted), args.batch):
            chunk = wanted[i:i + args.batch]
            term = "(" + " OR ".join(f"{p}[uid]" for p in chunk) + ")"
            try:
                _text, _ids, scored = endo_ai.fetch_papers(
                    term, tf, f"OSU corpus [{level_key}]", level_key,
                    max_results=args.batch, mode="review",
                    question="endodontic local anesthesia")
            except Exception as e:
                print(f"    XX {level_key} batch {i}: {type(e).__name__}: {e}")
                continue
            got.extend(scored)
        # A paper can match more than one tier filter. Keep the FIRST, because
        # TIERS is ordered strongest-first — the same precedence the evidence
        # builder uses.
        new = 0
        for p in got:
            pmid = str(p.get("pmid"))
            if pmid in wanted_set and pmid not in found:
                found[pmid] = p
                new += 1
        print(f"  {level_key:<9} matched {len(got):>3}, "
              f"{new:>3} newly tiered here")

    print(f"\n{'=' * 60}")
    print(f"RESOLVED   {len(found)} of {len(wanted)} corpus papers")
    unresolved = sorted(wanted_set - set(found))
    print(f"UNRESOLVED {len(unresolved)} — matched no design filter at all")

    with_abs = {k: v for k, v in found.items()
                if (v.get("abstract") or "").strip()}
    print(f"WITH ABSTRACT {len(with_abs)} (a row without one is useless for "
          f"both retrieval and the support check)")

    already = {k for k in with_abs if k in before}
    candidates = {k: v for k, v in with_abs.items() if k not in before}
    above = {k: v for k, v in candidates.items()
             if (v.get("score") or 0) >= args.min_score}
    below = {k: v for k, v in candidates.items()
             if (v.get("score") or 0) < args.min_score}

    print(f"\nALREADY IN LIBRARY        {len(already)}")
    print(f"NEW, at or above {args.min_score:<5}    {len(above)}")
    print(f"NEW, below {args.min_score:<5}          {len(below)}  (NOT written)")

    tiers = Counter(v.get("level_key") for v in above.values())
    print("\ntiers of what would be written:")
    for t, n in tiers.most_common():
        print(f"   {t:<10} {n}")

    scores = sorted((v.get("score") or 0) for v in candidates.values())
    if scores:
        print(f"\ncandidate scores: min {scores[0]:.1f}  median "
              f"{scores[len(scores) // 2]:.1f}  max {scores[-1]:.1f}")

    print("\nA SAMPLE OF WHAT THE FLOOR WOULD REJECT:")
    for p in sorted(below.values(), key=lambda x: -(x.get("score") or 0))[:8]:
        print(f"   {p['pmid']}  {p.get('score', 0):>5.1f}  {p.get('year')}  "
              f"{(p.get('title') or '')[:76]}")

    payload = {
        "min_score": args.min_score,
        "corpus": len(wanted),
        "resolved": len(found),
        "unresolved": unresolved,
        "already_in_library": sorted(already),
        "would_write": [row(v) for v in sorted(
            above.values(), key=lambda x: -(x.get("score") or 0))],
        "below_floor": [row(v) for v in sorted(
            below.values(), key=lambda x: -(x.get("score") or 0))],
    }
    OUT.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        return

    written = rag.learn_from_live_results(
        list(above.values()), min_score=args.min_score,
        query_text="endodontic local anesthesia — OSU corpus ingest")
    print(f"\nWRITTEN: {written} row(s)")
    after = library_pmids(wanted)
    print(f"library rows from the corpus: {len(before)} -> {len(after)}")


if __name__ == "__main__":
    main()
