"""Item 3, isolated: the IF signal's effect with EVERYTHING ELSE held constant.

The obvious comparison — the warmed demo row against a fresh run — is
confounded. That row predates both the A49/A2 quarantine (item 2, which
removed twelve records from the pool) and this change, so its delta is
item 2 + item 3 + whatever synthesis does differently on any two runs.

This runs the same question TWICE on the SAME code, changing only whether
`IF={value}` is appended to the Top-paper-per-tier block. Retrieval is
performed once and the identical evidence object is passed to both arms, so
the pool, the scores and the tier order are byte-identical and the only
difference reaching Claude is the signal under test.

It is still n=1 per arm against a stochastic generator. A difference of one
or two citations is noise. What would be signal is a large move, or a change
in WHICH papers are cited — so both arms report their cited set.

Usage:  python scripts/isolate_if_effect.py "<question>"
"""
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import endo_ai                    # noqa: E402

PMID_RE = re.compile(r"\[\[PMID:\s*([A-Za-z0-9\-]+)\s*\]\]")
OUT = ROOT / "eval" / "reports" / "a49_if_removal"


def profile(text):
    c = PMID_RE.findall(text or "")
    return {"chars": len(text or ""), "citation_markers": len(c),
            "distinct_cited": sorted(set(c)), "n_distinct": len(set(c))}


_ORIG_BUILD = endo_ai._build_evidence_context


def _build_with_if(evidence):
    """The builder as it read BEFORE this item: IF= back on the per-tier block.

    This PATCHES the builder rather than passing the text through
    `context_block`, and the distinction is the whole validity of the
    measurement. `context_block` is additive — the first version of this
    script passed the with-IF context there, and the arm received the entire
    evidence base TWICE: 102,242 input tokens against the other arm's 27,514,
    at $1.77 against $1.06. It was measuring the cost of duplicated context,
    not the effect of the signal. The token counts are what gave it away.
    """
    ctx = _ORIG_BUILD(evidence)
    by_pmid = {str(p.get("pmid")): p for p in
               (evidence.get("_summary", {}).get("all_scored") or [])}

    def _add(m):
        p = by_pmid.get(m.group(1))
        jif = p.get("impact_factor") if p else None
        return m.group(0) if not jif else "%s, IF=%s)" % (m.group(0)[:-1], jif)

    # Only the per-tier block carries the per-paper parenthetical this targets.
    head, sep, tail = ctx.partition("Top paper per tier")
    if not sep:
        return ctx
    return head + sep + re.sub(r"PMID (\S+) — [^\n]*?\)", _add, tail)


def main():
    question = sys.argv[1]
    OUT.mkdir(parents=True, exist_ok=True)

    print("Retrieving ONCE; both arms synthesise over the same evidence.\n")
    evidence = endo_ai.build_evidence_base(question, mode="review")

    arms = {}
    for arm in ("without_if", "with_if"):
        print("\n" + "=" * 74)
        print("ARM: %s" % arm)
        print("=" * 74)
        endo_ai._build_evidence_context = (
            _build_with_if if arm == "with_if" else _ORIG_BUILD)
        t0 = time.perf_counter()
        try:
            text, cost = endo_ai.ask_clinical_question(question, evidence)
        finally:
            endo_ai._build_evidence_context = _ORIG_BUILD
        text = endo_ai.finalise_answer_text(text)
        if isinstance(text, tuple):
            text = text[0]
        p = profile(text)
        p["cost_usd"] = round(float(cost or 0), 4)
        p["elapsed_s"] = round(time.perf_counter() - t0, 1)
        arms[arm] = p
        (OUT / ("isolated_%s.md" % arm)).write_text(text, encoding="utf-8")

    a, b = arms["with_if"], arms["without_if"]
    gained = sorted(set(b["distinct_cited"]) - set(a["distinct_cited"]))
    lost = sorted(set(a["distinct_cited"]) - set(b["distinct_cited"]))
    payload = {"question": question, "arms": arms,
               "gained_without_if": gained, "lost_without_if": lost}
    (OUT / "isolated.json").write_text(json.dumps(payload, indent=1),
                                       encoding="utf-8")

    print("\n" + "=" * 74)
    print("ISOLATED EFFECT — same code, same evidence, signal on vs off")
    print("=" * 74)
    print("  %-24s %12s %12s" % ("", "with IF", "without IF"))
    for k in ("citation_markers", "n_distinct", "chars"):
        print("  %-24s %12s %12s" % (k, a[k], b[k]))
    print("  %-24s %12.4f %12.4f" % ("cost_usd", a["cost_usd"], b["cost_usd"]))
    print("  %-24s %12.1f %12.1f" % ("elapsed_s", a["elapsed_s"], b["elapsed_s"]))
    print("\n  cited only WITHOUT the signal (%d): %s"
          % (len(gained), ", ".join(gained[:20])))
    print("  cited only WITH the signal    (%d): %s"
          % (len(lost), ", ".join(lost[:20])))
    print("\nwrote %s" % (OUT / "isolated.json"))


if __name__ == "__main__":
    sys.exit(main() or 0)
