"""
Per-turn latency of a case conversation (`case-v3` Item E).

WHAT IS BEING MEASURED, and why these two numbers rather than wall time.

  time-to-first-text     when the clinician can start READING. Before Item E
                         this equals time-to-complete, because the case path
                         published nothing until the whole answer, both
                         guardrails and the support check had finished.
  time-to-checks-done    when the header chips stop saying "checking…". The
                         answer is already on screen by then; this is the tail
                         the clinician does not have to wait through.

Wall time alone hides the whole point. An answer that takes 60 s but is
readable at 18 s is a different product from one that shows nothing for 60 s,
and they have identical wall times.

The process is warmed first — one throwaway retrieval — because the embedding
model loads on first use and a cold load lands entirely in turn 1, which is
exactly where a naive measurement would report a 20-second "improvement" that
is really just the second run.

    python scripts/measure_case_latency.py --label before
    python scripts/measure_case_latency.py --label after --out eval/logs/x.json
"""

import argparse
import io
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TURN1 = ("20 year old make of asian origin presents with necrotic tooth #20 "
         "with no visible signs of cracks or restorations. Radiographs show "
         "periapical radiolucency and patient denies any history of trauma. "
         "tooth on contra lateral side is also root canal treated. What could "
         "be the etiology for necrosis")
TURN2 = ("oh i do see a possible dens evaginatu sin tooth #20. Is there "
         "anything a dentist can do to present pulp necrosis from setting in?")

POLL_S = 0.25


def run_turn(client, messages, label):
    """Post one turn and watch the job record until it completes.

    Polls `/status` rather than instrumenting the synthesiser, because the
    question is what a BROWSER can see and when — a callback that fires
    server-side but never reaches the job record is not a latency improvement.
    """
    t0 = time.perf_counter()
    r = client.post("/case_chat", json={"messages": messages,
                                        "skip_clarify": True})
    assert r.status_code == 200, r.data[:300]
    job = r.get_json()["job_id"]

    first_text = None          # first non-empty partial_answer OR answer
    first_papers = None        # papers published (citations can resolve)
    checks_done = None
    st = {}
    while True:
        st = client.get(f"/status/{job}").get_json()
        now = time.perf_counter() - t0
        if first_papers is None and (st.get("papers") or []):
            first_papers = now
        if first_text is None and (st.get("partial_answer") or st.get("answer")):
            first_text = now
        if checks_done is None and st.get("checks_status") == "complete":
            checks_done = now
        if st.get("status") in ("complete", "error", "aborted"):
            break
        if now > 1800:
            raise TimeoutError(f"{label}: turn did not finish")
        time.sleep(POLL_S)

    total = time.perf_counter() - t0
    answer = st.get("answer") or ""
    if checks_done is None:
        # No streaming: the checks finish with everything else, so the honest
        # reading is "at the end", not "never".
        checks_done = total
    if first_text is None:
        first_text = total
    return {
        "label": label,
        "status": st.get("status"),
        "intent": st.get("case_intent"),
        "papers": len(st.get("papers") or []),
        "cost": st.get("cost_usd"),
        "answer_chars": len(answer),
        "time_to_first_papers": round(first_papers if first_papers else total, 1),
        "time_to_first_text": round(first_text, 1),
        "time_to_checks_done": round(checks_done, 1),
        "time_total": round(total, 1),
        "answer": answer,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="before")
    ap.add_argument("--out", default=None)
    ap.add_argument("--skip-warm", action="store_true")
    args = ap.parse_args()

    import app as app_mod
    client = app_mod.app.test_client()

    if not args.skip_warm:
        # The embedding model loads on first use, ~15-20 s, and it would land
        # entirely inside turn 1.
        print("warming (embedding model + DB pool)...")
        t = time.perf_counter()
        from rag import embed
        embed("warm up the sentence transformer")
        print(f"  warm in {time.perf_counter() - t:.1f}s\n")

    turns = []
    print(f"=== TURN 1 ({args.label}) — diagnostic ===")
    t1 = run_turn(client, [{"role": "user", "content": TURN1}], "turn1")
    turns.append(t1)
    print(f"  first papers {t1['time_to_first_papers']:>6.1f}s   "
          f"first text {t1['time_to_first_text']:>6.1f}s   "
          f"checks done {t1['time_to_checks_done']:>6.1f}s   "
          f"total {t1['time_total']:>6.1f}s")

    print(f"\n=== TURN 2 ({args.label}) — prevention follow-up ===")
    t2 = run_turn(client, [
        {"role": "user", "content": TURN1},
        {"role": "assistant", "content": t1["answer"]},
        {"role": "user", "content": TURN2}], "turn2")
    turns.append(t2)
    print(f"  first papers {t2['time_to_first_papers']:>6.1f}s   "
          f"first text {t2['time_to_first_text']:>6.1f}s   "
          f"checks done {t2['time_to_checks_done']:>6.1f}s   "
          f"total {t2['time_total']:>6.1f}s")

    print(f"\n  turn 2 papers: {t2['papers']}   intent: {t2['intent']}")
    print(f"  total cost: ${sum(float(t.get('cost') or 0) for t in turns):.4f}")

    if args.out:
        p = ROOT / args.out
        p.parent.mkdir(parents=True, exist_ok=True)
        io.open(p, "w", encoding="utf-8").write(json.dumps(
            {"label": args.label, "turns": turns}, indent=1, ensure_ascii=False))
        print(f"wrote {p}")


if __name__ == "__main__":
    main()
