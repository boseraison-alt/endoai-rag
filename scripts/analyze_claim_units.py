"""
Statistics for the Item 1 before/after replay.

The two arms are PAIRED and it would be wrong to test them as independent
samples: the pair count is identical (114 and 124), the per-PMID multiset is
identical, and the order is document order, so pair *i* in the before arm and
pair *i* in the after arm are the same citation in the same place, differing
only in how much text around it the judge was shown. McNemar's test is the one
that uses that.

Repeats are repeated measures on the SAME pairs, not new evidence, so pooling
them into one 714-vs-714 chi-square would manufacture significance out of
nothing. Two things are reported instead:

  - the per-run rates and their range, which is what "quote a range or quote
    the run" means here;
  - an exact McNemar over the pairs, with each pair's verdict taken as the
    MAJORITY of its three runs, so judge noise on a single pair does not
    become a discordant cell.
"""

import collections
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import endo_ai  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from measure_claim_units import (_pairs_before, _pairs_after,  # noqa: E402
                                 _strip_support_blocks, DEFAULT_SOURCES)


def binom_two_sided(b, c):
    """Exact McNemar: P(|X - n/2| >= |b - n/2|) for X ~ Bin(b + c, 0.5)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2.0 ** n)
    return min(1.0, 2.0 * tail)


def flags_by_key(path):
    """{(source, pmid, claim_prefix): times flagged} from one arm's json."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    counts = collections.Counter()
    runs = collections.Counter()
    for r in data["results"]:
        runs[r["source"]] += 1
        for f in r["flags"]:
            counts[(r["source"], f["pmid"], (f["claim"] or "")[:60])] += 1
    return data, counts, runs


def main():
    before_path = ROOT / "eval/logs/item1_claimunit_before.json"
    after_path = ROOT / "eval/logs/item1_claimunit_after.json"
    bdata, bflags, bruns = flags_by_key(before_path)
    adata, aflags, aruns = flags_by_key(after_path)

    print("PER-RUN RATES")
    for name, d in (("before", bdata), ("after", adata)):
        rates = [100.0 * f / c for f, c in d["per_run"].values()]
        print(f"  {name:<7} " + "  ".join(f"{r:.1f}%" for r in rates) +
              f"   pooled {d['total_flagged']}/{d['total_checked']} = "
              f"{100.0 * d['total_flagged'] / d['total_checked']:.1f}%")
    brates = [100.0 * f / c for f, c in bdata["per_run"].values()]
    arates = [100.0 * f / c for f, c in adata["per_run"].values()]
    separate = max(arates) < min(brates) or min(arates) > max(brates)
    print(f"  the two ranges {'do' if separate else 'do NOT'} separate")

    # ── Pair-level, majority of three runs ──
    per_source = {}
    for src in DEFAULT_SOURCES:
        answer = _strip_support_blocks(
            json.loads((ROOT / src).read_text(encoding="utf-8"))["answer"])
        per_source[src] = (_pairs_before(answer), _pairs_after(answer))

    b_only = a_only = both = neither = 0
    shape_of_changed = collections.Counter()
    for src, (bp, ap) in per_source.items():
        assert len(bp) == len(ap), f"{src}: arms are not aligned"
        for (bc, bpmid, _bs), (ac, apmid, ashape) in zip(bp, ap):
            assert bpmid == apmid, "pair order diverged — not paired data"
            bf = bflags[(src, bpmid, bc[:60])] * 2 > bruns[src]
            af = aflags[(src, apmid, ac[:400][:60])] * 2 > aruns[src]
            if bf and af:
                both += 1
            elif bf and not af:
                b_only += 1
                shape_of_changed[("cleared", ashape)] += 1
            elif af and not bf:
                a_only += 1
                shape_of_changed[("new", ashape)] += 1
            else:
                neither += 1

    n = both + b_only + a_only + neither
    p = binom_two_sided(b_only, a_only)
    print(f"\nMcNEMAR over {n} matched pairs (verdict = majority of 3 runs)")
    print(f"  flagged in both arms          {both}")
    print(f"  flagged BEFORE only (cleared) {b_only}")
    print(f"  flagged AFTER only (new)      {a_only}")
    print(f"  flagged in neither            {neither}")
    print(f"  exact two-sided p = {p:.5f}")

    print("\nWHICH SHAPE THE CHANGED PAIRS SIT ON (after-arm shape)")
    for (kind, shape), k in sorted(shape_of_changed.items(),
                                   key=lambda kv: -kv[1]):
        print(f"  {kind:<8} {shape:<14} {k}")

    print("\nFLAG RATE BY SHAPE, after arm, all runs pooled")
    for shape in endo_ai.CLAIM_SHAPES:
        if shape in adata["by_shape"]:
            f, c = adata["by_shape"][shape]
            print(f"  {shape:<14} {f}/{c} = {100.0 * f / c if c else 0:.1f}%")


if __name__ == "__main__":
    main()
