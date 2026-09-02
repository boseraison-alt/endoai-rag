"""
Regenerate a curriculum end to end and measure what changed
(`dl-quality-v1` Item 5).

Runs `build_deep_learning_module` in-process — no server, so `/health` drift
cannot make the result ambiguous — and writes both the markdown and a metrics
JSON beside it. The metrics are the ones the batch is accountable for:

  truncations            modules ending mid-sentence, mid-row or mid-citation
  stitcher placeholders  "[module body ends here as supplied]", which the
                         stitcher invents when handed a cut module
  unchecked claims       what the 30-pair cap used to hide
  parameter conflicts    cross-module concentration disagreements
  malformed BECAUSE      branches citing papers instead of giving a reason

Usage:
    python scripts/regenerate_curriculum.py --topic laser
    python scripts/regenerate_curriculum.py --question "..." --label anesthesia
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import endo_ai  # noqa: E402

OUT_DIR = ROOT / "eval" / "fixtures" / "curricula"

# The two stored fixtures' own questions, copied from their headers so a
# regeneration is comparable to its before-state rather than merely similar.
TOPICS = {
    "laser": ("Use of lasers in root canal disinfection",
              "laser_disinfection"),
    "anesthesia": ("anesthesia for endodontics, different techniques , when "
                   "to use what and newest material on the market",
                   "anesthesia"),
}

UNCHECKED_RE = re.compile(r"(\d+)\s+further cited claim\(s\)\s+were NOT checked")
SUPPLIED_MARKER = "ends here as supplied"


def modules_of(text: str) -> list:
    body = text.split("## Citation Support by Module")[0]
    parts = re.split("^(## [^" + chr(92) + "n]*)$", body, flags=re.M)
    out = []
    for i in range(1, len(parts), 2):
        head = parts[i].strip()
        if head.startswith("## Module") and len(parts[i + 1].split()) >= 40:
            out.append((head, parts[i + 1]))
    return out


def measure(text: str) -> dict:
    mods = modules_of(text)
    cut = [(h, endo_ai.detect_module_truncation(b)) for h, b in mods]
    conflicts = endo_ai.detect_parameter_conflicts(mods)
    return {
        "modules": len(mods),
        "words": len(text.split()),
        "truncated_modules": [
            {"module": h, "reason": r["reason"], "tail": r["tail"]}
            for h, r in cut if r["truncated"]],
        "stitcher_placeholders": text.count(SUPPLIED_MARKER),
        "unchecked_claims": sum(int(n) for n in UNCHECKED_RE.findall(text)),
        "module_not_generated": text.count("Module not generated"),
        "parameter_conflicts": [
            {"agent": c["agent"], "unit": c["unit"],
             "values": [v["value"] for v in c["values"]]}
            for c in conflicts],
        "malformed_because": endo_ai.detect_malformed_because(text),
        "cited_pmids": sorted(set(re.findall(r"\[\[PMID:(\d+)\]\]", text))),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", choices=sorted(TOPICS))
    ap.add_argument("--question")
    ap.add_argument("--label")
    ap.add_argument("--compare", help="path to the before-state fixture")
    args = ap.parse_args()

    if args.topic:
        question, label = TOPICS[args.topic]
    elif args.question and args.label:
        question, label = args.question, args.label
    else:
        ap.error("give --topic, or both --question and --label")

    before_path = Path(args.compare) if args.compare else \
        OUT_DIR / f"{label}_20260901_before.txt"

    print(f"QUESTION: {question}")
    print(f"BEFORE:   {before_path if before_path.exists() else '(none)'}\n")

    t0 = time.perf_counter()
    final, cost, _evidence = endo_ai.build_deep_learning_module(
        question, progress_cb=lambda p, m: print(f"  [{p:>3}%] {m}"))
    elapsed = time.perf_counter() - t0

    after_path = OUT_DIR / f"{label}_after.txt"
    after_path.parent.mkdir(parents=True, exist_ok=True)
    after_path.write_text(final, encoding="utf-8")

    after = measure(final)
    after["cost_usd"] = round(cost, 4)
    after["elapsed_s"] = round(elapsed, 1)
    payload = {"question": question, "after": after}

    if before_path.exists():
        payload["before"] = measure(
            before_path.read_text(encoding="utf-8", errors="replace"))

    metrics_path = OUT_DIR / f"{label}_regen_metrics.json"
    metrics_path.write_text(json.dumps(payload, indent=1), encoding="utf-8")

    print(f"\nwrote {after_path}")
    print(f"wrote {metrics_path}")
    print(f"\n{'':<26} {'before':>10} {'after':>10}")
    b = payload.get("before", {})
    for k in ("modules", "words", "stitcher_placeholders", "unchecked_claims",
              "module_not_generated"):
        print(f"  {k:<24} {str(b.get(k, '-')):>10} {str(after.get(k)):>10}")
    for k in ("truncated_modules", "parameter_conflicts", "malformed_because",
              "cited_pmids"):
        print(f"  {k:<24} {len(b.get(k, [])) if b else '-':>10} "
              f"{len(after.get(k, [])):>10}")
    print(f"\n  cost ${after['cost_usd']}   {after['elapsed_s']}s")


if __name__ == "__main__":
    main()
