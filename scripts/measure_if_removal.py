"""Item 3 — what was the impact-factor signal actually doing to synthesis?

`_build_evidence_context` appended `IF={value}` to the Top-paper-per-tier
block on all four answer paths, and 1,572 of 3,208 library rows carry a
value. Removing it changes synthesis output and invalidates the warmed cache.
That is expected and acceptable — the demo has passed — but it must be
MEASURED rather than asserted, because "it probably made no difference" and
"it was silently steering half the evidence" are both plausible and only one
of them is true.

Runs one Literature question and one Curriculum question on the CURRENT code
and reports citation count and cost, against the stored before-state
produced by code that still carried the signal.

The comparison is honest about what it is: n=1 per mode, and synthesis is
stochastic, so a difference of one or two citations is noise. What would be
signal is a large move, or a change in WHICH papers are cited — so the run
reports the cited set, not only its size.

Usage:
  python scripts/measure_if_removal.py --mode review
  python scripts/measure_if_removal.py --mode learn
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

import endo_ai                    # noqa: E402
import psycopg2                   # noqa: E402
import psycopg2.extras            # noqa: E402
from rag import DATABASE_URL      # noqa: E402

OUT = ROOT / "eval" / "reports" / "a49_if_removal"

# The two rows the demo was rehearsed on, produced by code that still
# appended IF=. Comparing against them is comparing to the real before-state
# rather than to a fresh run of the old code, which would cost twice as much
# and still be n=1.
BEFORE_ROWS = {"review": 4127, "learn": 4471}

PMID_RE = re.compile(r"\[\[PMID:\s*([A-Za-z0-9\-]+)\s*\]\]")


def stored(row_id):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT question_text, answer FROM query_cache WHERE id = %s",
                (row_id,))
    r = cur.fetchone()
    conn.close()
    return r


def profile(text):
    cites = PMID_RE.findall(text or "")
    return {
        "chars": len(text or ""),
        "citation_markers": len(cites),
        "distinct_cited": sorted(set(cites)),
        "n_distinct": len(set(cites)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["review", "learn"], required=True)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    row = stored(BEFORE_ROWS[args.mode])
    if not row:
        print("FATAL: before-state row %s is gone" % BEFORE_ROWS[args.mode])
        return 2

    # The stored question carries a "[review] " / "[learn] " route prefix and,
    # for the curriculum, the clarifier Q&A appended by A37. Strip the prefix;
    # KEEP the clarifier text, because it was part of what the before-state
    # was generated from and dropping it would change the retrieval seed.
    q = row["question_text"]
    q = re.sub(r"^\[(review|learn|case)\]\s*", "", q)

    before = profile(row["answer"])
    print("=" * 74)
    print("ITEM 3 — IMPACT-FACTOR REMOVAL, mode=%s" % args.mode)
    print("=" * 74)
    print("question: %s" % q.splitlines()[0][:70])
    print("before  : %d citation markers, %d distinct, %d chars"
          % (before["citation_markers"], before["n_distinct"], before["chars"]))
    print("\nrunning on current code (the signal is gone) ...\n")

    t0 = time.perf_counter()
    if args.mode == "learn":
        text, cost, _ev = endo_ai.build_deep_learning_module(
            q, progress_cb=lambda p, m: print("  [%3d%%] %s" % (p, m)))
    else:
        # The same two calls app.py's review route makes, in the same order.
        # Retrieval first, then synthesis over what it returned — going
        # straight to ask_clinical_question would synthesise over nothing.
        evidence = endo_ai.build_evidence_base(q, mode="review")
        text, cost = endo_ai.ask_clinical_question(q, evidence)
    text = endo_ai.finalise_answer_text(text)
    if isinstance(text, tuple):
        text = text[0]
    elapsed = time.perf_counter() - t0

    after = profile(text)
    after["cost_usd"] = round(float(cost), 4)
    after["elapsed_s"] = round(elapsed, 1)

    gained = sorted(set(after["distinct_cited"]) - set(before["distinct_cited"]))
    lost = sorted(set(before["distinct_cited"]) - set(after["distinct_cited"]))

    payload = {"mode": args.mode, "question": q,
               "before_row": BEFORE_ROWS[args.mode],
               "before": before, "after": after,
               "gained_citations": gained, "lost_citations": lost}
    (OUT / ("%s.json" % args.mode)).write_text(
        json.dumps(payload, indent=1), encoding="utf-8")
    (OUT / ("%s_answer.md" % args.mode)).write_text(text, encoding="utf-8")

    print()
    print("  %-22s %10s %10s" % ("", "before", "after"))
    print("  %-22s %10d %10d" % ("citation markers",
                                 before["citation_markers"],
                                 after["citation_markers"]))
    print("  %-22s %10d %10d" % ("distinct papers cited",
                                 before["n_distinct"], after["n_distinct"]))
    print("  %-22s %10d %10d" % ("chars", before["chars"], after["chars"]))
    print("  %-22s %10s %10.4f" % ("cost USD", "(cached)", after["cost_usd"]))
    print("  %-22s %10s %10.1f" % ("elapsed s", "-", after["elapsed_s"]))
    print("\n  citations GAINED (%d): %s" % (len(gained), ", ".join(gained[:20])))
    print("  citations LOST   (%d): %s" % (len(lost), ", ".join(lost[:20])))
    print("\nwrote %s" % (OUT / ("%s.json" % args.mode)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
