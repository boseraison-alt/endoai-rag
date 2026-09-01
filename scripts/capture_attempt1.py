"""
Capture attempt-1 Review answers with the evidence base PINNED
(`guardrails-v1` Item 2).

THE QUESTION. The Review prompt requires the CLINICAL RECOMMENDATION to carry
a `[[PMID:N]]` marker on its load-bearing claim. `_GROUNDING_RULE` says do not
attach a marker you cannot ground, and offers "write it unmarked" as a correct
move. When both apply the model leaves the recommendation unmarked,
`validate_evidence_mapping` fails the answer `UNTRACEABLE_RECOMMENDATION`, and
a whole answer is regenerated at ~$0.44.

WHY THIS AND NOT `run_eval --synthesis-subset`. Three reasons, all about
attributing the result to the prompt:

  1. Retrieval is re-run per eval invocation, so two arms would differ in
     their evidence bases as well as in their prompts. Here the evidence is
     retrieved ONCE per question and reused by both arms, so the only
     difference is the wording under test.
  2. The eval retries a failed answer, which is the cost this item is about
     and is pure noise for measuring how often attempt 1 passes. This harness
     never retries: it records attempt 1 and stops.
  3. Repeats. Attempt-1 failure is a per-sample event at roughly 30%, so one
     pass over eight questions cannot separate two arms.

WHAT IT COSTS. One Opus synthesis is ~$0.45 (18.5k in, 2.3k out, measured
2026-09-01). No prompt caching, deliberately: cost per answer is one of the
numbers this item reports, and a cached run would report a number production
does not pay.

Usage:
  python scripts/capture_attempt1.py --pin            # retrieve + cache evidence
  python scripts/capture_attempt1.py --arm before --samples 3 \
      --out eval/logs/item2_attempt1_before.json
"""

import argparse
import collections
import json
import os
import pickle
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import endo_ai  # noqa: E402

PIN_DIR = ROOT / "eval" / "logs" / "pinned_evidence"

# The eight Review cases from the eval subsets — three library-pinned, five
# live-pinned. The two laser cases in SYNTHESIS_SUBSET are Deep Learning
# curricula and take a different synthesis path, so they are not here.
QUESTIONS = [
    ("single-vs-multiple-visit", "library",
     "Single-visit versus multiple-visit root canal treatment for necrotic "
     "teeth with apical periodontitis"),
    ("naocl-concentration", "library",
     "Sodium hypochlorite concentration, low versus high, and outcome of "
     "primary root canal treatment"),
    ("pips-vs-ultrasonic", "library",
     "Laser-activated irrigation (PIPS/SWEEPS) versus ultrasonic activation "
     "for periapical healing outcomes"),
    ("retreatment-vs-microsurgery", "live",
     "Nonsurgical retreatment versus apical microsurgery for persistent "
     "apical periodontitis"),
    ("cracked-tooth-prognosis", "live",
     "Cracked tooth: prognosis after root canal treatment by crack extent"),
    ("bisphosphonates", "live",
     "Endodontic management in patients on bisphosphonates or "
     "antiresorptives"),
    ("pregnancy", "live",
     "Root canal treatment in pregnancy: timing and local anaesthetic choice"),
    ("intentional-replantation", "live",
     "Intentional replantation for teeth unsuitable for surgery"),
]


def pin_all(only=None):
    """Retrieve each question's evidence once and pickle it.

    Pinned rather than re-retrieved so that the before and after arms are
    answering from the SAME papers. Retrieval is LLM-driven (search-term
    generation) and route-dependent, so re-running it between arms would put a
    different evidence base behind each one and there would be no way to say
    which change moved the number.
    """
    PIN_DIR.mkdir(parents=True, exist_ok=True)
    for cid, route, question in QUESTIONS:
        if only and cid not in only:
            continue
        path = PIN_DIR / f"{cid}.pkl"
        if path.exists():
            print(f"  [pin] {cid}: already pinned")
            continue
        print(f"  [pin] {cid} ({route}) — retrieving ...")
        t0 = time.perf_counter()
        # The route-pinned builder the eval uses, so this evidence base is the
        # same shape the measured cases see. Pinning matters for the same
        # reason it matters there: write-back and route drift make an
        # unpinned case measure a stored artefact of an earlier run.
        import app as app_mod
        evidence = app_mod.build_evidence_base_with_progress(
            f"pin-{cid}", question, force_route=route, mode="review")
        n = len(endo_ai._extract_evidence_pmids(evidence))
        path.write_bytes(pickle.dumps({"question": question, "route": route,
                                       "evidence": evidence}))
        print(f"        {n} papers, {time.perf_counter() - t0:.0f}s")


def load_pinned(cid):
    path = PIN_DIR / f"{cid}.pkl"
    if not path.exists():
        return None
    return pickle.loads(path.read_bytes())


class _StopBeforeRetry(Exception):
    """Raised inside the seam when the retry call is about to be made."""


def one_attempt(question, evidence):
    """One attempt-1 Review synthesis through the PRODUCTION path.

    `ask_clinical_question` has no attempt-1-only mode and should not grow
    one: a flag that changes what the synthesiser does is a flag the
    measurement then has to defend. Instead the harness stops the run at the
    module's single Claude seam — `_invoke_claude` — the moment the retry call
    is about to be made. Everything before that point is byte-identical to
    production, including the system prompt, the streaming call, the cost log
    row and the attempt-1 audit record.

    Costs are collected per function, so the synthesis is reported separately
    from the citation-support check that follows it on a PASSING answer and
    does not run on a failing one. Averaging the two together would make a
    failing sample look cheaper than a passing one, which is the opposite of
    the truth.
    """
    state = {"answer": None, "cost": collections.Counter()}

    real_invoke = endo_ai._invoke_claude
    real_log = endo_ai.log_llm_call

    def invoke_spy(client, *, function_name="claude", **kw):
        if function_name == "ask_clinical_question_retry":
            raise _StopBeforeRetry()
        resp = real_invoke(client, function_name=function_name, **kw)
        if function_name == "ask_clinical_question":
            state["answer"] = resp.content[0].text
        return resp

    def log_spy(fn, model, usage, **kw):
        c = real_log(fn, model, usage, **kw)
        state["cost"][fn] += c
        return c

    endo_ai._invoke_claude = invoke_spy
    endo_ai.log_llm_call = log_spy
    try:
        endo_ai.ask_clinical_question(question, evidence)
    except _StopBeforeRetry:
        pass
    finally:
        endo_ai._invoke_claude = real_invoke
        endo_ai.log_llm_call = real_log

    answer = state["answer"] or ""
    result = endo_ai.validate_evidence_mapping(answer, evidence)
    rec = result.get("recommendation") or {}
    return {
        "passed":         result["passed"],
        "score":          result["score"],
        "failure_reason": result.get("failure_reason"),
        "n_cited":        len(result.get("cited_pmids") or []),
        "n_fabricated":   len(result.get("fabricated_pmids") or []),
        "n_unattributed": len(result.get("unattributed_claims") or []),
        "unattributed_sample": [c.get("sentence", "")[:200] for c in
                                (result.get("unattributed_claims") or [])[:3]],
        "rec_present":      rec.get("present"),
        "rec_has_citation": rec.get("has_citation"),
        "rec_names_tier":   rec.get("names_tier"),
        "rec_text":         (rec.get("text") or "")[:1500],
        "cost":           state["cost"].get("ask_clinical_question", 0.0),
        "cost_all":       dict(state["cost"]),
        "answer_chars":   len(answer),
        "answer":         answer,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pin", action="store_true",
                    help="retrieve and cache the evidence base per question")
    ap.add_argument("--arm", default=None,
                    help="label for this run, e.g. before / after")
    ap.add_argument("--samples", type=int, default=3,
                    help="attempt-1 syntheses per question")
    ap.add_argument("--ids", nargs="*", default=None,
                    help="restrict to these case ids")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    ids = set(args.ids) if args.ids else None

    if args.pin:
        pin_all(ids)
        return

    if not args.arm:
        ap.error("--arm is required unless --pin")

    rows = []
    for cid, route, question in QUESTIONS:
        if ids and cid not in ids:
            continue
        pinned = load_pinned(cid)
        if not pinned:
            print(f"  [{cid}] NOT PINNED — run --pin first; skipping")
            continue
        for s in range(args.samples):
            t0 = time.perf_counter()
            try:
                row = one_attempt(question, pinned["evidence"])
            except Exception as e:
                print(f"  [{cid}] sample {s + 1}: ERROR {type(e).__name__}: {e}")
                continue
            row.update({"case": cid, "route": route, "arm": args.arm,
                        "sample": s + 1,
                        "elapsed": round(time.perf_counter() - t0, 1)})
            rows.append(row)
            tag = "PASS" if row["passed"] else \
                  (row["failure_reason"] or "FAIL").split(":")[0]
            print(f"  [{cid}] sample {s + 1}/{args.samples}: {tag:<28} "
                  f"score={row['score']:3}  rec_cite={row['rec_has_citation']}  "
                  f"${row['cost']:.4f}  {row['elapsed']:.0f}s")

    n = len(rows)
    npass = sum(1 for r in rows if r["passed"])
    cost = sum(r["cost"] for r in rows)
    reasons = collections.Counter(
        (r["failure_reason"] or "").split(":")[0] for r in rows if not r["passed"])
    print(f"\nARM {args.arm}: attempt-1 pass {npass}/{n} = "
          f"{100.0 * npass / n if n else 0:.1f}%")
    print(f"  mean cost per attempt-1  ${cost / n if n else 0:.4f}")
    print("  failure reasons: " + (", ".join(f"{k} x{v}" for k, v in
                                             reasons.most_common()) or "none"))
    # What a failing answer costs in production: attempt 1 plus the retry it
    # triggers. Reported next to the pass rate because the pass rate is the
    # only thing that makes the cost interpretable.
    mean = cost / n if n else 0
    nfail = n - npass
    print(f"  projected mean cost per SERVED answer (attempt-1 + retry on "
          f"failure): ${(cost + nfail * mean) / n if n else 0:.4f}")

    if args.out:
        p = ROOT / args.out
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "arm": args.arm, "samples": args.samples,
            "n": n, "n_passed": npass, "total_cost": cost,
            "failure_reasons": dict(reasons), "rows": rows},
            indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {p}")


if __name__ == "__main__":
    main()
