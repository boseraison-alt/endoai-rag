"""Periodic library maintenance: backfill -> rescore -> retrieval eval -> report.

Live write-back is the only thing that adds rows to `endo_papers_rag` between
ingests, and it adds them WITHOUT provenance: `fetch_papers` fills title,
abstract, year, journal, score and level_key, but MEDLINE status, COI, erratum
/ retraction, pre-registration and `superseded_by` all come from a separate
efetch that only `scripts/backfill_pubmed_metadata.py` performs. So every month
the library grows a cohort of papers that are scored but unprovenanced, and a
retracted or superseded one among them is invisible to both retrieval paths.

The three steps have to run in this order and nobody should have to remember
why:

  1. BACKFILL provenance for the new arrivals only (`--since-days`). Cheap,
     network-bound, and it is what discovers a retraction.
  2. RESCORE. Provenance feeds scoring — the COI penalty is applied only at
     rescore, from the stored `coi_status` the backfill just wrote. Rescoring
     first would score the new rows against provenance they do not yet have.
  3. EVAL, retrieval-only, once. It measures whether steps 1 and 2 moved
     retrieval, and it is the only step that can say so. `--cheap` is implied:
     no synthesis, no LLM tokens.

DRY RUN IS THE DEFAULT and it is not a formality. Steps 1 and 2 write to every
row they touch; this repo has twice lost the identity of a migrated set by
running a write before a dry run. `--apply` is required to write, and the two
sub-scripts each keep their own `--apply` semantics, so a bug here cannot write
by accident — this script composes them, it does not reimplement them.

    python scripts/monthly_maintenance.py                  # dry run, no writes
    python scripts/monthly_maintenance.py --apply          # write
    python scripts/monthly_maintenance.py --skip-eval      # backfill+rescore only
    python scripts/monthly_maintenance.py --since-days 45

NOT SCHEDULED, deliberately. When this runs is a judgement about the demo
calendar and the Anthropic credit balance, and belongs to RB, not to a cron
line added by the script that wrote itself.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PY = sys.executable


def _run(label, argv, log_dir, timeout):
    """Run one maintenance stage as its own process and capture everything.

    A subprocess rather than an import for three reasons: each sub-script owns
    its own `--apply` gate and its own backup table, so composing them cannot
    weaken either; a stage that dies takes its own process down instead of the
    run; and the captured stdout IS the audit trail for a step that rewrote
    2,000 rows.
    """
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    print("  $ " + " ".join(str(a) for a in argv))
    t0 = time.perf_counter()
    try:
        # encoding is explicit: `text=True` alone decodes with the locale
        # codec, which on this Windows box is cp1252, and every em dash in a
        # sub-script's output came back as "â€”" in the captured log.
        proc = subprocess.run([PY, *[str(a) for a in argv]], cwd=str(ROOT),
                              capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace",
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        out, code = (proc.stdout or "") + (proc.stderr or ""), proc.returncode
    except subprocess.TimeoutExpired as e:
        out = ((e.stdout or "") if isinstance(e.stdout, str)
               else (e.stdout or b"").decode("utf-8", "replace"))
        out += f"\n*** TIMED OUT after {timeout}s ***"
        code = -1
    secs = time.perf_counter() - t0

    path = log_dir / f"{label.split()[0].lower()}.log"
    path.write_text(out, encoding="utf-8")
    tail = [l for l in out.splitlines() if l.strip()][-12:]
    for line in tail:
        print("    " + line[:160])
    print(f"  -> exit {code} in {secs:.0f}s, full output in {path}")
    return {"label": label, "argv": [str(a) for a in argv], "exit": code,
            "seconds": round(secs, 1), "log": str(path), "output": out}


# What each stage's output is worth pulling into the one-page report. Reported
# from the stage's own stdout rather than re-queried, so the report cannot
# disagree with the run it describes.
_METRICS = {
    "BACKFILL": [
        (re.compile(r"^\[pubmed\] (\d+) papers with numeric PMIDs", re.M),
         "papers examined"),
        (re.compile(r"^\s+(\d+)\s+RETRACTED\s*$", re.M), "RETRACTED"),
        (re.compile(r"^\s+(\d+)\s+SUPERSEDED by a newer version\s*$", re.M),
         "superseded"),
        (re.compile(r"^\s+(\d+)\s+coi:declared_conflict\s*$", re.M),
         "declared COI"),
        (re.compile(r"^\s+(\d+)\s+level_key inferred\s*$", re.M),
         "level_key inferred"),
    ],
    "RESCORE": [
        (re.compile(r"^\[rescore\] (\d+) papers eligible", re.M), "papers rescored"),
        (re.compile(r"^\[rescore\] changed: (\d+)", re.M), "scores changing"),
        # "nothing to change" carries no number, and reporting no row for it
        # would leave the report silent about a stage that ran clean. `0` is
        # the finding.
        (re.compile(r"^\[rescore\] (nothing) to change", re.M), "scores changing"),
    ],
    "EVAL": [
        (re.compile(r"^(\d+/\d+) cases passed", re.M), "cases passed"),
        (re.compile(r"^\s+(\d+) metric\(s\) outside the baseline range", re.M),
         "metrics off baseline"),
    ],
}


def _extract(stage, output):
    """(label, value) pairs pulled from a stage's own stdout.

    First match per label wins, so a later pattern is a fallback rather than a
    duplicate — `nothing to change` fills in the count that `changed: N` would
    otherwise have provided.
    """
    out, seen = [], set()
    for rx, label in _METRICS.get(stage, []):
        if label in seen:
            continue
        m = rx.search(output or "")
        if m:
            val = m.group(1)
            out.append((label, "0" if val == "nothing" else val))
            seen.add(label)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="actually write. Without it every stage runs its own "
                         "dry run and the database is untouched.")
    ap.add_argument("--since-days", type=int, default=35,
                    help="provenance window for new write-backs (default 35, "
                         "so a monthly run overlaps itself rather than leaving "
                         "a gap when it slips a few days)")
    ap.add_argument("--skip-eval", action="store_true",
                    help="skip the retrieval eval (it takes ~20 minutes and "
                         "issues PubMed searches)")
    ap.add_argument("--eval-baseline", default="baseline_v6.json")
    ap.add_argument("--out", default=None,
                    help="report path (default: eval/logs/maintenance_<stamp>/)")
    args = ap.parse_args()

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    log_dir = Path(args.out) if args.out else (ROOT / "eval" / "logs" /
                                               f"maintenance_{stamp}")
    log_dir.mkdir(parents=True, exist_ok=True)

    mode = "APPLY — this run WRITES" if args.apply else "DRY RUN — no writes"
    print(f"{'=' * 70}\nlibrary maintenance   {stamp}\n{mode}\n"
          f"provenance window: {args.since_days} days\noutput: {log_dir}\n{'=' * 70}")

    stages = []

    # ── 1. Provenance for the new arrivals ──
    argv = ["scripts/backfill_pubmed_metadata.py", "--since-days", args.since_days]
    if args.apply:
        argv.append("--apply")
    stages.append(_run("BACKFILL provenance for recent write-backs", argv,
                       log_dir, timeout=3600))

    # ── 2. Rescore ──
    # Runs even when the backfill changed nothing: the scoring model itself may
    # have moved since the last run, and a rescore that finds 0 rows to change
    # is a useful thing to have on the record.
    argv = ["scripts/rescore_library.py"]
    if args.apply:
        argv.append("--apply")
    stages.append(_run("RESCORE the library", argv, log_dir, timeout=3600))

    # ── 3. Retrieval eval, once ──
    if args.skip_eval:
        print("\nEVAL skipped (--skip-eval)")
    else:
        # Retrieval-only by construction. --synthesis-subset is NOT reachable
        # from here: a maintenance run must not generate answers, both because
        # of the cost and because an eval answer must never be left where a
        # clinician could be served it.
        argv = ["eval/run_eval.py", "--cheap", "--diff",
                "--baseline", args.eval_baseline]
        stages.append(_run("EVAL retrieval, one pass", argv, log_dir,
                           timeout=7200))

    # ── The one-page report ──
    lines = [f"# Library maintenance — {stamp}", "",
             f"**Mode:** {mode}  ",
             f"**Provenance window:** {args.since_days} days  ",
             f"**Logs:** `{log_dir}`", "",
             "| stage | exit | wall | what it found |",
             "|---|---|---|---|"]
    for st in stages:
        key = st["label"].split()[0]
        found = _extract(key, st["output"])
        cell = "; ".join(f"{v} {k}" for k, v in found) or "—"
        lines.append(f"| {st['label']} | {st['exit']} | {st['seconds']:.0f}s | {cell} |")

    failed = [s for s in stages if s["exit"] != 0]
    lines += ["", "## Outcome", ""]
    if failed:
        lines.append(f"**{len(failed)} stage(s) did not exit 0** — "
                     + ", ".join(s["label"].split()[0] for s in failed)
                     + ". Read the logs before trusting anything above.")
    else:
        lines.append("Every stage exited 0.")
    if not args.apply:
        lines += ["", "This was a DRY RUN. Nothing was written. Re-run with "
                  "`--apply` to make the changes the table above describes."]

    # Anything the backfill found that a human has to decide about. These are
    # the two states where a paper is still being served and should not be.
    back = next((s for s in stages if s["label"].startswith("BACKFILL")), None)
    if back:
        retr = re.search(r"^\s+(\d+)\s+RETRACTED\s*$", back["output"], re.M)
        sup  = re.search(r"^\s+(\d+)\s+SUPERSEDED by a newer version\s*$",
                         back["output"], re.M)
        if (retr and int(retr.group(1))) or (sup and int(sup.group(1))):
            lines += ["", "## Needs a human", "",
                      f"- {retr.group(1) if retr else 0} retracted and "
                      f"{sup.group(1) if sup else 0} superseded paper(s) were "
                      f"found among the new arrivals. Both are excluded from "
                      f"retrieval once the backfill is APPLIED — until then "
                      f"they are still being served."]

    report = log_dir / "report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (log_dir / "stages.json").write_text(
        json.dumps([{k: v for k, v in s.items() if k != "output"}
                    for s in stages], indent=2) + "\n", encoding="utf-8")

    print(f"\n{'=' * 70}")
    print("\n".join(lines))
    print(f"{'=' * 70}\nreport -> {report}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
