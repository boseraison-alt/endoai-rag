"""
Measure the claim-unit split, before and after, on curriculum answers that
already exist (`guardrails-v1` Item 1).

WHY REPLAY AND NOT REGENERATE. The change under test is in the CHECKER, not
in the writer. Regenerating a curriculum to measure it puts an Opus sampling
difference between the two arms, and the difference this fix is expected to
make (13 flags out of 37) is smaller than the run-to-run spread already
recorded for these cases (11.7% and 15.0% on two curricula of the same
question, in the same run). Holding the ANSWER TEXT fixed and swapping only
the splitter is the only version of this experiment that can attribute its
own result.

The text used is the two stored curricula from the run that measured
32/240 = 13.3% — `eval/logs/item1_after_synthesis.log`, cases at 00:59 and
01:07 on 2026-09-01 — so the "before" arm here reproduces the population
behind the reported number rather than a fresh sample of it.

Two arms:
  before — `_split_claim_units` (prose only), the splitter as it shipped
  after  — `_split_claim_units_tagged`, decision-tree branches, table rows
           and bold-label sub-points as their own units

Both arms run the REAL `verify_citation_support` judge against the REAL
cached abstracts. `--extract-only` skips the judge and reports the pair
counts alone, which is free and is what the shape table needs.

Usage:
  python scripts/measure_claim_units.py --extract-only
  python scripts/measure_claim_units.py --arm before --out eval/logs/x.json
  python scripts/measure_claim_units.py --arm after  --out eval/logs/y.json
"""

import argparse
import collections
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import endo_ai  # noqa: E402

# The two curricula behind the 13.3% figure.
DEFAULT_SOURCES = [
    "learn_history/20260901_005932_use_of_lasers_in_root_canal_disinfection.json",
    "learn_history/20260901_010712_use_of_lasers_in_root_canal_disinfection.json",
]


# The checker's OWN rendered blocks must come out before re-extracting: they
# quote flagged claims verbatim, live `[[PMID:N]]` markers and all, so leaving
# them in feeds the previous run's output back through the extractor. Imported
# rather than re-implemented — `classify_dl_flags` already got this right, and
# a second copy is a second thing to be wrong.
from classify_dl_flags import _strip_support_blocks  # noqa: E402


def _pairs_before(answer: str):
    """[(claim, pmid, shape)] under the OLD prose-only splitter.

    Re-implements `_extract_claim_citation_pairs` over `_split_claim_units`
    rather than calling the shipped function, because the shipped function is
    the thing being changed. Every other step — sections, exemptions, the
    20-character floor, marker stripping — is the shipped code, so the two
    arms differ in exactly one place.
    """
    pairs = []
    for title, body in endo_ai._split_sections(answer or ""):
        if endo_ai._is_exempt_section(title):
            continue
        for sent in endo_ai._split_claim_units(body):
            s = sent.strip()
            if len(s) < 20:
                continue
            pmids = [m.group(1) for m in endo_ai._PMID_RE.finditer(s)]
            if not pmids:
                continue
            claim = endo_ai._PMID_RE.sub("", s).strip()
            claim = re.sub(r"\s{2,}", " ", claim)
            for pid in pmids:
                pairs.append((claim, pid, "prose"))
    return pairs


def _pairs_after(answer: str):
    return endo_ai._extract_claim_citation_pairs(answer, with_shape=True)


def _describe(pairs, label):
    shapes = collections.Counter(s for _c, _p, s in pairs)
    lens = [len(c) for c, _p, _s in pairs]
    print(f"\n{label}")
    print(f"  pairs            {len(pairs)}")
    print(f"  distinct PMIDs   {len({p for _c, p, _s in pairs})}")
    if lens:
        print(f"  claim length     mean {sum(lens)//len(lens)}  "
              f"max {max(lens)}  >1000 chars: {sum(1 for l in lens if l > 1000)}")
    for shape in endo_ai.CLAIM_SHAPES:
        if shapes.get(shape):
            print(f"    {shape:<14} {shapes[shape]}")
    return shapes


def _judge(pairs, cap):
    """Run the real judge over `pairs`, returning per-pair verdicts.

    Calls `verify_citation_support` on a synthetic answer? No — that would
    re-run the splitter. The pairs are handed to the judge directly through
    the same batching and the same prompt, by monkeypatching the extractor for
    the duration of the call. The judge, the abstracts, the model and the
    batching are therefore identical between arms; only the pair list differs.
    """
    fake_answer = "## Replay\nplaceholder [[PMID:1]] for the extractor.\n"
    # 3-tuples: `verify_citation_support` normalises a 2-tuple to `prose`, and
    # in the BEFORE arm that is the truth — there were no shapes. In the AFTER
    # arm the shapes are the measurement, so they must survive the handoff.
    tuples = [(c, p, s) for c, p, s in pairs]

    original = endo_ai._extract_claim_citation_pairs
    original_cap = endo_ai._SUPPORT_MAX_PAIRS
    endo_ai._extract_claim_citation_pairs = lambda *a, **kw: list(tuples)
    endo_ai._SUPPORT_MAX_PAIRS = cap
    try:
        return endo_ai.verify_citation_support(fake_answer, {})
    finally:
        endo_ai._extract_claim_citation_pairs = original
        endo_ai._SUPPORT_MAX_PAIRS = original_cap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=("before", "after"), default=None)
    ap.add_argument("--extract-only", action="store_true")
    ap.add_argument("--sources", nargs="*", default=DEFAULT_SOURCES)
    ap.add_argument("--cap", type=int, default=100000,
                    help="_SUPPORT_MAX_PAIRS for the replay. Default is "
                         "effectively uncapped: a 30-cap would compare two "
                         "different 30-pair prefixes, not two splitters.")
    ap.add_argument("--repeat", type=int, default=1,
                    help="Judge each arm N times. The judge is not "
                         "deterministic: two runs over the SAME 238 pairs "
                         "with the SAME splitter returned 19 and 29 flags "
                         "(8.0%% and 12.2%%). One run per arm cannot "
                         "attribute a difference smaller than that spread, "
                         "which is the mistake `4.3%% was a draw, not a "
                         "level` records in HANDOVER.md.")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    per_source = []
    for src in args.sources:
        path = ROOT / src
        answer = json.loads(path.read_text(encoding="utf-8"))["answer"]
        answer = _strip_support_blocks(answer)
        rec = {"source": src,
               "before": _pairs_before(answer),
               "after":  _pairs_after(answer)}
        per_source.append(rec)
        print(f"\n=== {path.name} ({len(answer)} chars) ===")
        _describe(rec["before"], "BEFORE (prose-only splitter)")
        _describe(rec["after"], "AFTER  (shape-aware splitter)")

        b = collections.Counter(p for _c, p, _s in rec["before"])
        a = collections.Counter(p for _c, p, _s in rec["after"])
        if b != a:
            diff = {k: (b.get(k, 0), a.get(k, 0))
                    for k in set(b) | set(a) if b.get(k) != a.get(k)}
            print(f"  !! PMID MULTISET CHANGED: {diff}")
        else:
            print("  PMID multiset identical (no citation lost or gained)")

    if args.extract_only or not args.arm:
        return

    results = []
    for run_i in range(args.repeat):
      for rec in per_source:
        pairs = rec[args.arm]
        print(f"\njudging {len(pairs)} pairs from {rec['source']} "
              f"[{args.arm}] run {run_i + 1}/{args.repeat} ...")
        out = _judge(pairs, args.cap)
        # The checker records the split itself now, denominator included. Read
        # it from there rather than recomputing, so this script cannot
        # disagree with the audit log about its own measurement.
        shape_stats = out.get("by_shape") or {}
        by_shape = collections.Counter(
            {k: v["checked"] for k, v in shape_stats.items()})
        flagged_by_shape = collections.Counter(
            {k: v["flagged"] for k, v in shape_stats.items()})
        print(f"  checked {out['checked']}  flagged {len(out.get('flags', []))}"
              f"  cost ${out.get('cost', 0):.4f}  status {out.get('status')}")
        for shape in endo_ai.CLAIM_SHAPES:
            if by_shape.get(shape):
                print(f"    {shape:<14} {flagged_by_shape[shape]}/{by_shape[shape]}")
        results.append({
            "source":   rec["source"],
            "arm":      args.arm,
            "pairs":    len(pairs),
            "checked":  out.get("checked"),
            "flagged":  len(out.get("flags", [])),
            "cost":     out.get("cost"),
            "status":   out.get("status"),
            "by_shape": dict(by_shape),
            "flagged_by_shape": dict(flagged_by_shape),
            "flags": [{"pmid": f.get("pmid"), "shape": f.get("shape"),
                       "claim": f.get("claim"), "verdict": f.get("verdict")}
                      for f in out.get("flags", [])],
        })

    tot_c = sum(r["checked"] or 0 for r in results)
    tot_f = sum(r["flagged"] for r in results)
    print(f"\nTOTAL [{args.arm}]  {tot_f}/{tot_c} = "
          f"{100.0 * tot_f / tot_c if tot_c else 0:.1f}%  "
          f"(${sum(r['cost'] or 0 for r in results):.4f})")

    # Per run, so the spread is visible rather than averaged away. Quote a
    # range or quote the run — the same discipline the 4.3% draw earned.
    per_run = collections.defaultdict(lambda: [0, 0])
    n_src = len(per_source)
    for i, r in enumerate(results):
        agg = per_run[i // n_src]
        agg[0] += r["flagged"]
        agg[1] += r["checked"] or 0
    print("  per run: " + "  ".join(
        f"{f}/{c} = {100.0 * f / c if c else 0:.1f}%"
        for _k, (f, c) in sorted(per_run.items())))

    shape_tot = collections.defaultdict(lambda: [0, 0])
    for r in results:
        for shape, n in r["by_shape"].items():
            shape_tot[shape][1] += n
        for shape, n in r["flagged_by_shape"].items():
            shape_tot[shape][0] += n
    print("  by shape (all runs pooled):")
    for shape in endo_ai.CLAIM_SHAPES:
        if shape in shape_tot:
            f, c = shape_tot[shape]
            print(f"    {shape:<14} {f}/{c} = "
                  f"{100.0 * f / c if c else 0:.1f}%")

    if args.out:
        out_path = ROOT / args.out
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(
            {"arm": args.arm, "cap": args.cap, "repeat": args.repeat,
             "sources": args.sources,
             "total_checked": tot_c, "total_flagged": tot_f,
             "per_run": {str(k): v for k, v in sorted(per_run.items())},
             "by_shape": {k: v for k, v in shape_tot.items()},
             "results": results}, indent=1, ensure_ascii=False),
            encoding="utf-8")
        print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
