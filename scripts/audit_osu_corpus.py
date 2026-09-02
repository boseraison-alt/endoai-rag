"""
Where did each OSU/Reader classic actually go? (`classics-v1` B2.)

Takes the denominator built by `scripts/build_osu_corpus.py` and answers, for
every paper in it: is it in the library, at what tier and score, did the
classics exemption apply, and — if it never reached an answer — at which stage
it dropped.

THE POINT IS TO FIX ONLY WHAT THIS TABLE SHOWS. "The canon is missing" has at
least four different causes with four different fixes (never ingested; ingested
but mis-tiered; ingested and correctly tiered but below the similarity floor
for the query that was asked; retrieved but cut by a candidate cap), and
guessing between them is how a scoring change gets made for a retrieval
problem.

Stage 1 (--library) is a read-only DB pass and is what B2's first four columns
need. Stage 2 (--retrieval) replays the anesthesia module queries through the
real retrieval path and records which corpus papers surface, which is the last
two columns. Stage 2 costs PubMed calls and embedding time; stage 1 costs
nothing.

Usage:
    python scripts/audit_osu_corpus.py --library
    python scripts/audit_osu_corpus.py --library --retrieval
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
OUT = ROOT / "eval" / "logs" / "osu_corpus_audit.json"

# The anesthesia curriculum's own module queries, so "was it in the candidate
# pool" means the pool for the run this batch is about — not for a query
# invented afterwards to make the number look better.
ANESTHESIA_QUERIES = [
    "local anesthesia pharmacology endodontics lidocaine articaine mechanism",
    "clinical assessment anesthetic failure irreversible pulpitis diagnosis",
    "supplemental anesthesia intraosseous intraligamentary buccal infiltration",
    "anesthesia outcomes success rates complications mandibular molar",
]


def load_corpus() -> list:
    if not CORPUS.exists():
        sys.exit(f"missing {CORPUS} — run scripts/build_osu_corpus.py first")
    return json.loads(CORPUS.read_text(encoding="utf-8"))["papers"]


def library_rows(pmids: list) -> dict:
    """Everything the library knows about these PMIDs, keyed by pmid."""
    conn = rag.get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT pmid, title, year, journal, level_key, score,
                      is_curated, sample_size, followup_months, citations,
                      medline_indexed, has_retraction,
                      length(COALESCE(abstract, '')) AS abstract_chars
               FROM endo_papers_rag WHERE pmid = ANY(%s)""",
            (list(pmids),))
        cols = [d[0] for d in cur.description]
        return {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}
    finally:
        cur.close()
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", action="store_true")
    ap.add_argument("--retrieval", action="store_true")
    args = ap.parse_args()
    if not (args.library or args.retrieval):
        ap.error("give --library and/or --retrieval")

    corpus = load_corpus()
    pmids = [p["pmid"] for p in corpus]
    print(f"corpus: {len(pmids)} paper(s)\n")

    rows = {p["pmid"]: {
        "pmid": p["pmid"], "year": p.get("year"), "title": p.get("title"),
        "journal": p.get("journal_abbrev") or p.get("journal"),
        "in_library": False,
    } for p in corpus}

    if args.library:
        found = library_rows(pmids)
        for pmid, r in rows.items():
            lib = found.get(pmid)
            if not lib:
                continue
            r.update({
                "in_library":     True,
                "level_key":      lib["level_key"],
                "score":          round(lib["score"] or 0, 1),
                "is_curated":     bool(lib["is_curated"]),
                "classic_tier":   lib["level_key"] == "classic",
                "sample_size":    lib["sample_size"],
                "followup_months": lib["followup_months"],
                "citations":      lib["citations"],
                "abstract_chars": lib["abstract_chars"],
                "has_retraction": bool(lib["has_retraction"]),
            })
            # The per-component breakdown, recomputed from the stored inputs so
            # the table shows WHY the score is what it is rather than only what
            # it is. The IF term is passed as 0: it is excluded from the score
            # (invariant 22) and passing a real value would imply otherwise.
            try:
                _total, parts = endo_ai.score_paper(
                    lib["level_key"], lib["year"], lib["citations"] or 0,
                    lib["sample_size"], lib["followup_months"], 0.0,
                    is_review=False)
                r["breakdown"] = parts
            except Exception as e:      # pragma: no cover
                r["breakdown"] = {"error": str(e)}

        n_in = sum(1 for r in rows.values() if r["in_library"])
        print(f"IN LIBRARY:      {n_in} of {len(rows)}")
        print(f"NOT IN LIBRARY:  {len(rows) - n_in}")
        tiers = Counter(r.get("level_key") for r in rows.values()
                        if r["in_library"])
        print("\ntiers assigned:")
        for t, n in tiers.most_common():
            print(f"   {str(t):<12} {n}")
        n_classic = sum(1 for r in rows.values() if r.get("classic_tier"))
        print(f"\nCLASSICS EXEMPTION (level_key == 'classic'): "
              f"{n_classic} of {n_in} library rows")
        scored = [r["score"] for r in rows.values() if r["in_library"]]
        if scored:
            scored.sort()
            print(f"scores: min {scored[0]}  median "
                  f"{scored[len(scored) // 2]}  max {scored[-1]}")
            print(f"below the write-back floor of 50: "
                  f"{sum(1 for s in scored if s < 50)} of {len(scored)}")

    if args.retrieval:
        print("\n" + "=" * 60)
        print("RETRIEVAL REPLAY — the anesthesia curriculum's own module queries")
        print("=" * 60)
        corpus_set = set(pmids)
        for q in ANESTHESIA_QUERIES:
            print(f"\n  query: {q[:70]}")
            try:
                ev = endo_ai.build_evidence_base(q, mode="learn")
            except Exception as e:
                print(f"    FAILED: {type(e).__name__}: {e}")
                continue
            got = {str(p.get("pmid")) for p in
                   (ev.get("_summary", {}) or {}).get("all_scored", [])}
            hit = sorted(corpus_set & got)
            print(f"    {len(got)} paper(s) retrieved; {len(hit)} from the "
                  f"OSU corpus")
            for pmid in hit:
                rows[pmid].setdefault("retrieved_for", []).append(q[:40])

        reached = [r for r in rows.values() if r.get("retrieved_for")]
        print(f"\nOSU papers reaching the candidate pool: "
              f"{len(reached)} of {len(rows)}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"n": len(rows),
                               "papers": sorted(rows.values(),
                                                key=lambda r: str(r["year"]))},
                              indent=1), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
