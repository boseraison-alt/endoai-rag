"""
Snapshot library scores, then report what a rescore moved — SPLIT BY TIER.

`rescore_library.py` reports one delta distribution for the whole library plus
a review/primary split. That is the right split for a change to the review
scoring rule, and the wrong one for a change to the DATA every score is derived
from. The abstract repair rewrote 1,355 abstracts, and `score_paper` reads the
abstract twice — `extract_sample_size` and `is_review_design` — so a healed
conclusion can move a paper's sample size, its design classification, or both.
Whether that lands evenly across tiers or concentrates in one is the question a
whole-library median cannot answer.

    python scripts/score_delta_by_tier.py --snapshot before.json
    python scripts/rescore_library.py --apply
    python scripts/score_delta_by_tier.py --diff before.json

Read-only in both modes. It never writes to the library.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2.extras
from rag import get_conn


def _snapshot() -> dict:
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT pmid, COALESCE(level_key,'') AS level_key,
                          COALESCE(score,0) AS score,
                          sample_size,
                          length(COALESCE(abstract,'')) AS abstract_len
                   FROM endo_papers_rag""")
    rows = {r["pmid"]: {"level_key": r["level_key"],
                        "score": float(r["score"]),
                        "sample_size": r["sample_size"],
                        "abstract_len": r["abstract_len"]}
            for r in cur.fetchall()}
    cur.close()
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", metavar="PATH")
    ap.add_argument("--diff", metavar="PATH")
    ap.add_argument("--flag-above", type=float, default=5.0,
                    help="report any tier whose MEDIAN move exceeds this")
    args = ap.parse_args()

    if args.snapshot:
        rows = _snapshot()
        Path(args.snapshot).write_text(json.dumps(rows), encoding="utf-8")
        print(f"[snapshot] {len(rows)} rows -> {args.snapshot}")
        return 0

    if not args.diff:
        ap.error("give --snapshot PATH or --diff PATH")

    before = json.loads(Path(args.diff).read_text(encoding="utf-8"))
    after = _snapshot()

    by_tier: dict[str, list[float]] = {}
    n_moved = n_size = 0
    for pmid, a in after.items():
        b = before.get(pmid)
        if b is None:
            continue                       # written since the snapshot
        d = a["score"] - b["score"]
        by_tier.setdefault(a["level_key"] or "(none)", []).append(d)
        if abs(d) >= 0.05:
            n_moved += 1
        if a["sample_size"] != b["sample_size"]:
            n_size += 1

    print(f"{'tier':<12} {'n':>5} {'moved':>6} {'median':>8} {'mean':>8} "
          f"{'min':>8} {'max':>8}")
    print("-" * 60)
    flagged = []
    for tier, ds in sorted(by_tier.items(), key=lambda kv: -len(kv[1])):
        moved = [d for d in ds if abs(d) >= 0.05]
        med = statistics.median(ds) if ds else 0.0
        print(f"{tier:<12} {len(ds):>5} {len(moved):>6} {med:>+8.1f} "
              f"{statistics.mean(ds):>+8.1f} {min(ds):>+8.1f} {max(ds):>+8.1f}")
        if abs(med) > args.flag_above:
            flagged.append((tier, med))

    print(f"\nrows whose score moved at all : {n_moved}")
    print(f"rows whose sample_size changed: {n_size}")
    if flagged:
        print(f"\nINVESTIGATE — median move over ±{args.flag_above} in: "
              + ", ".join(f"{t} ({m:+.1f})" for t, m in flagged))
    else:
        print(f"\nNo tier's MEDIAN moved more than ±{args.flag_above}. "
              f"Individual papers still can; the medians are what was predicted "
              f"to stay small.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
