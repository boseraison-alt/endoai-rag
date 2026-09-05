"""Item 2 — PRISMA nominates by YEAR on one path and by RELEVANCE on the other.

MEASURE FIRST. Nothing is changed by this script.

`flag_superseded_by_review` picks the review to name in the PRISMA dedup
notice. It does not fork on the route explicitly; it forks on whether the
candidate papers carry a `similarity`:

    if any(sim > 0 for ...):  chosen by relevance
    else:                     chosen by year

Library-route papers come from cosine KNN and carry a similarity. Live-path
papers come from `fetch_papers` and do not. So the same function nominates by
relevance on one path and by year on the other, and A38 measured that the two
rules disagree on 26 of 29 questions.

WHAT THIS MEASURES, AND THE ONE VARIABLE IT HOLDS STILL. The two PATHS also
retrieve different papers, so comparing a live answer to a library answer would
move two variables at once (rule 22). This runs ONE library retrieval per
question and applies BOTH RULES to that single candidate pool, so the only
difference is the rule.

THE JUDGE IS BLIND, and that is the whole design. Cosine similarity cannot be
the judge: it is the relevance rule's own signal, so scoring the titles by
cosine would be asking the rule to mark its own exam. Instead each disagreement
goes to Haiku as the question plus two titles labelled A and B, with no year,
no PMID and no hint which rule produced which. The mapping is kept here and
applied after the verdict comes back.

THREE VOTES, WITH THE ORDER FLIPPED BETWEEN THEM, and the reason is standing
rule 3's cousin: an instrument that has never been observed to disagree with
itself is not known to be measuring anything. A judge that answers "A" twice
regardless of which review sits in slot A is exhibiting position bias, not
judgement. Flipping the presentation between votes makes that visible — a
position-biased judge splits 2-1 along slot lines and the disagreement is
recorded as a TIE rather than counted for whichever rule got lucky.

Usage:  python scripts/measure_prisma_nomination.py [--json OUT.json]
"""
import argparse
import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import anthropic                          # noqa: E402
import endo_ai as E                       # noqa: E402
import app as A                           # noqa: E402

JUDGE_SEED = 20260905


def collect_candidates(evidence):
    """The same candidate list `flag_superseded_by_review` builds."""
    out = []
    for tier_key in E.SR_TIER_KEYS:
        for p in (evidence.get(tier_key, {}) or {}).get("scored", []) or []:
            try:
                y = int(p.get("year", 0))
            except (ValueError, TypeError):
                continue
            if y > 0:
                out.append((p, y, float(p.get("similarity") or 0)))
    return out


def pick_relevance(cands):
    return max(cands, key=lambda c: (c[2], c[1]))


def pick_year(cands):
    return max(cands, key=lambda c: c[1])


def judge_once(question, title_a, title_b):
    """Which review is more on-topic for this question? Returns 'A', 'B', 'T' or ''."""
    client = anthropic.Anthropic(api_key=E._get_api_key())
    prompt = (
        "A clinician asked this question:\n\n"
        f"    {question}\n\n"
        "Two systematic reviews are candidates for being named as the review "
        "that best covers this question. Judge ONLY which review is more "
        "on-topic for the question, from its title.\n\n"
        f"A: {title_a}\n"
        f"B: {title_b}\n\n"
        "Answer with exactly one character: A or B. If they are genuinely "
        "equally on-topic, answer T."
    )
    r = E._invoke_claude(
        client, function_name="prisma_nomination_judge",
        model=E.MODELS["structured_fast"], max_tokens=4,
        messages=[{"role": "user", "content": prompt}])
    txt = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    txt = txt.strip().upper()[:1]
    return txt if txt in ("A", "B", "T") else ""


def judge_panel(question, t_rel, t_year, rng):
    """Three blind votes with the slot order flipped between them.

    Returns (winner, votes) where winner is 'relevance', 'year', 'tie' or
    'unparsed', and votes records what each vote said in RULE terms so a
    position-biased judge is visible in the record rather than averaged away.
    """
    votes, orders = [], []
    flip = rng.random() < 0.5
    for k in range(3):
        f = flip if k % 2 == 0 else (not flip)
        ta, tb = (t_year, t_rel) if f else (t_rel, t_year)
        try:
            v = judge_once(question, ta, tb)
        except Exception as ex:
            print("     vote %d failed: %s" % (k + 1, ex))
            v = ""
        if v == "T":
            votes.append("tie")
        elif v in ("A", "B"):
            picked_rel = (v == "B") if f else (v == "A")
            votes.append("relevance" if picked_rel else "year")
        else:
            votes.append("unparsed")
        orders.append("year-first" if f else "relevance-first")
    tally = {}
    for v in votes:
        tally[v] = tally.get(v, 0) + 1
    for k in ("relevance", "year"):
        if tally.get(k, 0) >= 2:
            return k, votes, orders
    return "tie", votes, orders


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_out", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    cases = json.load(open("eval/questions.json"))["cases"]
    if args.limit:
        cases = cases[:args.limit]

    E.LIBRARY_WRITE_BACK = False
    rng = random.Random(JUDGE_SEED)

    print("=" * 78)
    print("ITEM 2 — PRISMA NOMINATION: RELEVANCE vs YEAR, ONE POOL, BLIND JUDGE")
    print("=" * 78)
    print("measure only; nothing changed\n")

    rows = []
    for i, case in enumerate(cases, 1):
        qid, mode = case["id"], case.get("mode", "review")
        job_id = "prisma-%s" % qid
        A.jobs[job_id] = {"status": "running", "steps": [], "progress": 0}
        exchanges = (case.get("context") or {}).get("exchanges") or []
        ctx = E.build_context_block(exchanges) if exchanges else ""
        prior = E.context_prior_pmids(exchanges) if exchanges else None
        print("-" * 78)
        print("[%2d/%d] %s" % (i, len(cases), qid))
        try:
            ev = A.build_evidence_base_with_progress(
                job_id, case["question"], force_route="library",
                mode=mode, context_block=ctx, prior_pmids=prior) or {}
        except Exception as e:
            print("   RETRIEVAL FAILED: %s" % e)
            rows.append({"id": qid, "error": str(e)})
            continue

        cands = collect_candidates(ev)
        if not cands:
            print("   no SR candidates")
            rows.append({"id": qid, "n_candidates": 0, "differ": False})
            continue

        rp, ry, rsim = pick_relevance(cands)
        yp, yy, ysim = pick_year(cands)
        differ = str(rp.get("pmid")) != str(yp.get("pmid"))
        row = {
            "id": qid, "question": case["question"], "n_candidates": len(cands),
            "differ": differ,
            "relevance": {"pmid": rp.get("pmid"), "year": ry,
                          "sim": round(rsim, 3), "title": rp.get("title", "")},
            "year": {"pmid": yp.get("pmid"), "year": yy,
                     "sim": round(ysim, 3), "title": yp.get("title", "")},
        }
        if not differ:
            print("   AGREE  %s (%s)" % (rp.get("pmid"), ry))
            rows.append(row)
            continue

        winner, votes, orders = judge_panel(
            case["question"], rp.get("title", ""), yp.get("title", ""), rng)
        row["votes"] = votes
        row["vote_orders"] = orders
        row["unanimous"] = len(set(votes)) == 1
        row["winner"] = winner
        rows.append(row)
        print("   DIFFER  relevance=%s(%s,sim %.3f)  year=%s(%s,sim %.3f)  -> %s"
              % (rp.get("pmid"), ry, rsim, yp.get("pmid"), yy, ysim, winner.upper()))
        print("     votes: %s%s" % (", ".join(votes),
                                     "" if len(set(votes)) == 1 else "   SPLIT"))
        print("     relevance: %s" % (rp.get("title", "")[:70]))
        print("     year     : %s" % (yp.get("title", "")[:70]))

    ok = [r for r in rows if "error" not in r]
    diff = [r for r in ok if r.get("differ")]
    win = {}
    for r in diff:
        win[r.get("winner", "?")] = win.get(r.get("winner", "?"), 0) + 1

    print()
    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print("  questions measured                %d" % len(ok))
    print("  the two rules AGREE               %d" % len([r for r in ok if not r.get("differ")]))
    print("  the two rules DIFFER              %d" % len(diff))
    print()
    print("  Of the disagreements, the more on-topic review was chosen by:")
    for k in ("relevance", "year", "tie", "unparsed"):
        if win.get(k):
            print("     %-10s %3d   (%.0f%% of disagreements)"
                  % (k, win[k], 100.0 * win[k] / max(1, len(diff))))
    split = [r for r in diff if not r.get("unanimous", True)]
    print()
    print("  judge reliability: %d of %d disagreements were unanimous across the"
          % (len(diff) - len(split), len(diff)))
    print("  three flipped votes; %d split (recorded by majority, tie if none)"
          % len(split))

    if diff:
        msim = sum(r["relevance"]["sim"] for r in diff) / len(diff)
        ysim = sum(r["year"]["sim"] for r in diff) / len(diff)
        myr = sum(r["relevance"]["year"] for r in diff) / len(diff)
        yyr = sum(r["year"]["year"] for r in diff) / len(diff)
        print()
        print("  mean similarity of the nominated review: relevance %.3f  year %.3f"
              % (msim, ysim))
        print("  mean year of the nominated review:       relevance %.1f  year %.1f"
              % (myr, yyr))
        print()
        print("  (similarity is reported, NOT used to judge — it is the relevance")
        print("   rule's own signal and cannot mark its own exam.)")

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        json.dump(rows, open(args.json_out, "w"), indent=1)
        print("\n  wrote %s" % args.json_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
