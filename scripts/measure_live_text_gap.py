"""How much of the retrieved evidence does the LIVE path actually show Claude?

`app.build_evidence_base_with_progress` fetches each tier once per search term
(~7 terms) and folds the results:

    level_scored.extend(new_scored)          # every term
    level_ids.extend(new_ids)                # every term
    if text and not level_text:              # FIRST term only
        level_text = text

`_build_evidence_context` renders `block["text"]` and nothing else, so the
prompt carries one term's papers per tier while `_summary` counts all of them.
The "Total papers: N" header, the average score and the "Top paper per tier"
panel are all computed from the full `scored` list.

This measures the gap: PMIDs present in the rendered text versus PMIDs in
`scored`, per tier, on a real live retrieval.

Measure only. Usage:
    python scripts/measure_live_text_gap.py ["question"] [--mode case]
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E                # noqa: E402
import app as A                    # noqa: E402

PMID_IN_TEXT = re.compile(r"PMID:?\s*(\d{5,9})")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    question = args[0] if args else (
        "sodium hypochlorite concentration for root canal irrigation")
    mode = "case" if "--mode" in sys.argv and "case" in sys.argv else "review"

    jid = "textgap"
    with A.jobs_lock:
        A.jobs[jid] = {"status": "running", "abort": False}
    ev = A.build_evidence_base_with_progress(jid, question,
                                             force_route="live", mode=mode)

    print()
    print("=" * 78)
    print("LIVE-PATH TEXT GAP — what reaches the prompt vs what was retrieved")
    print("=" * 78)
    print("question: %s" % question[:70])
    print("mode    : %s\n" % mode)
    print("  %-16s %8s %8s %8s   %s"
          % ("tier", "scored", "in text", "missing", ""))

    tot_scored = tot_text = 0
    rows = []
    for key in list(E.TIER_ORDER) + [E.PROVISIONAL_KEY]:
        block = ev.get(key) or {}
        scored = block.get("scored") or []
        if not scored:
            continue
        in_text = set(PMID_IN_TEXT.findall(block.get("text") or ""))
        have = {str(p.get("pmid")) for p in scored}
        shown = have & in_text
        missing = len(have) - len(shown)
        tot_scored += len(have)
        tot_text += len(shown)
        flag = "  <-- %d never shown" % missing if missing else ""
        print("  %-16s %8d %8d %8d%s"
              % (key, len(have), len(shown), missing, flag))
        rows.append({"tier": key, "scored": len(have), "in_text": len(shown),
                     "missing": missing})

    print("  %-16s %8d %8d %8d" % ("TOTAL", tot_scored, tot_text,
                                   tot_scored - tot_text))
    pct = (100.0 * tot_text / tot_scored) if tot_scored else 0
    print()
    print("  FRACTION OF RETRIEVED EVIDENCE THE MODEL ACTUALLY SEES: %.1f%%" % pct)
    summary = ev.get("_summary") or {}
    print("  ...while the header it is given says: Total papers: %s | Avg score: %s"
          % (summary.get("total_scored"), summary.get("avg_score")))

    out = ROOT / "eval" / "reports" / "a49_live_text_gap.json"
    out.write_text(json.dumps(
        {"question": question, "mode": mode, "rows": rows,
         "total_scored": tot_scored, "total_in_text": tot_text,
         "pct_shown": round(pct, 1),
         "header_total": summary.get("total_scored")}, indent=1),
        encoding="utf-8")
    print("\nwrote %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
