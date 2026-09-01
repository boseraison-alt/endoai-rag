"""
Regenerate the demo assets against the current library, and time them.

The rescore after the abstract repair invalidated every cached answer the demo
relies on, so the four Review questions in DEMO_RUNBOOK.md, the fallback
question and the laser curriculum all have to be rebuilt — otherwise the first
thing the demo does is pay for a cold run in front of an audience.

This drives the PRODUCTION path (`/ask` through the Flask test client), NOT the
eval path: the answer cache is left switched on, because a populated cache IS
the asset. Each question is then asked a SECOND time to measure the cached
timing the runbook quotes.

THE CACHE IS EVICTED FIRST, and that is not an optimisation. The last time this
script ran, a rescore had just DELETEd `query_cache`, so its "cold" pass really
was cold. Run it against a WARM cache and every cold pass is served from the
cache at $0 in half a second, the script prints its timings, and it re-warms
NOTHING while looking exactly like a success. That is invariant 12 — an eval
must not measure a stored artefact of an earlier run; a synthesis that cost $0
is a failure — pointed at the re-warm instead of at the eval. So each question's
entry is deleted before its cold pass, and a cold pass that comes back at
$0.0000 is a hard error rather than a line of output.

    python scripts/regenerate_demo_assets.py            # answers only
    python scripts/regenerate_demo_assets.py --decks    # + web deck and pptx
    python scripts/regenerate_demo_assets.py --keep-cache   # do not evict

Costs real money — roughly $0.70 per Review answer and $1.40 for the
curriculum.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

REVIEW_QUESTIONS = [
    "Single-visit versus multiple-visit root canal treatment for necrotic teeth "
    "with apical periodontitis",
    "MTA versus Biodentine for full pulpotomy in mature permanent teeth with "
    "irreversible pulpitis",
    "CBCT versus periapical radiography for detecting apical periodontitis",
    "Nonsurgical retreatment versus apical microsurgery for persistent apical "
    "periodontitis",
    "Endodontic management in patients on bisphosphonates or antiresorptives",
]
LEARN_QUESTION = "Use of lasers in root canal disinfection"


def evict(question: str, mode: str) -> int:
    """Delete this question's cached answer so the next ask is really cold.

    The same 0.99-cosine match `/cache/clear` uses, called directly rather than
    over HTTP so the script does not need ADMIN_TOKEN to do its own job.
    """
    from rag import get_conn, embed
    q_vec = embed(f"[{mode}] {question}")
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM query_cache "
                    "WHERE 1 - (question_embedding <=> %s::vector) >= 0.99;",
                    (q_vec,))
        n = cur.rowcount
        conn.commit()
        return n
    finally:
        cur.close()
        conn.close()


def _assert_really_cold(got: dict, what: str, keep_cache: bool) -> None:
    if got["cost"] == 0.0 and not keep_cache:
        raise SystemExit(
            f"COLD PASS COST $0 for {what} — it was served from the cache, so "
            f"nothing was re-warmed and the timings below are cache hits. "
            f"Cost is not a success metric, but a $0 synthesis is a failure "
            f"(WORKLIST §0.7, invariant 12).")


def ask(client, question: str, mode: str, timeout_s: int = 1800) -> dict:
    t0 = time.time()
    r = client.post("/ask", json={"question": question, "mode": mode,
                                  "skip_clarify": True})
    if r.status_code != 200:
        raise RuntimeError(f"/ask {r.status_code}: {r.data[:200]}")
    job_id = r.get_json()["job_id"]
    deadline = t0 + timeout_s
    while time.time() < deadline:
        st = client.get(f"/status/{job_id}").get_json()
        if st.get("status") in ("complete", "error", "aborted"):
            break
        time.sleep(0.5)
    else:
        raise TimeoutError(f"{question[:40]}… did not finish")
    if st.get("status") != "complete":
        raise RuntimeError(f"job {st.get('status')}: {st.get('error')}")
    return {"job_id": job_id, "wall_s": round(time.time() - t0, 1),
            "cost": float(st.get("cost_usd") or 0.0),
            "papers": len(st.get("papers") or []),
            "answer": st.get("answer") or "",
            "chars": len(st.get("answer") or "")}


def poll_export(client, audio_id: str, timeout_s: int = 1800) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        st = client.get(f"/audio_status/{audio_id}").get_json()
        if st.get("status") in ("complete", "error"):
            return {**st, "wall_s": round(time.time() - t0, 1)}
        time.sleep(2)
    return {"status": "timeout", "wall_s": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--decks", action="store_true",
                    help="also build the laser web deck and pptx")
    ap.add_argument("--reviews-only", action="store_true",
                    help="skip the curriculum. Re-warming after a change that "
                         "only touches Review saves $1.40 and eight minutes, "
                         "and leaves the cached curriculum exactly as the last "
                         "run left it — which is what the demo shows.")
    ap.add_argument("--keep-cache", action="store_true",
                    help="do NOT evict before the cold pass. Only for "
                         "measuring cache timings — the 'cold' numbers this "
                         "run prints are then cache hits, and it re-warms "
                         "nothing.")
    ap.add_argument("--out", default=None, help="write the timing JSON here")
    args = ap.parse_args()

    import app as app_mod
    client = app_mod.app.test_client()
    results = {"review": [], "learn": None, "cached": [], "exports": {}}

    for q in REVIEW_QUESTIONS:
        print(f"\n=== COLD  {q[:64]}…")
        if not args.keep_cache:
            print(f"    evicted {evict(q, 'review')} cached row(s)")
        got = ask(client, q, "review")
        _assert_really_cold(got, repr(q[:60]), args.keep_cache)
        print(f"    {got['wall_s']}s  ${got['cost']:.4f}  {got['papers']} papers  "
              f"{got['chars']} chars")
        results["review"].append({"question": q, **{k: got[k] for k in
                                  ("wall_s", "cost", "papers", "chars")}})

    learn = None
    if not args.reviews_only:
        print(f"\n=== COLD  [learn] {LEARN_QUESTION}")
        if not args.keep_cache:
            print(f"    evicted {evict(LEARN_QUESTION, 'learn')} cached row(s)")
        learn = ask(client, LEARN_QUESTION, "learn")
        _assert_really_cold(learn, "the curriculum", args.keep_cache)
        print(f"    {learn['wall_s']}s  ${learn['cost']:.4f}  {learn['papers']} papers")
        results["learn"] = {"question": LEARN_QUESTION,
                            **{k: learn[k] for k in ("wall_s", "cost", "papers", "chars")}}

    # Second pass: what the demo actually shows.
    for q in REVIEW_QUESTIONS + ([] if args.reviews_only else [LEARN_QUESTION]):
        mode = "learn" if q == LEARN_QUESTION else "review"
        got = ask(client, q, mode)
        served = got["cost"] == 0.0
        print(f"  CACHED {got['wall_s']}s  {'(from cache)' if served else '*** NOT CACHED ***'}"
              f"  {q[:52]}…")
        results["cached"].append({"question": q, "wall_s": got["wall_s"],
                                  "from_cache": served})

    if args.decks and learn is None:
        print("\n=== EXPORTS skipped: --decks needs the curriculum, and "
              "--reviews-only did not build one")
    elif args.decks:
        for kind, route in (("webdeck", "/generate_webdeck"),
                            ("pptx", "/generate_slides")):
            print(f"\n=== EXPORT {kind} for the laser curriculum")
            r = client.post(route, json={"job_id": learn["job_id"],
                                         "length_minutes": 10})
            if r.status_code != 200:
                print(f"    FAILED {r.status_code}: {r.data[:200]}")
                results["exports"][kind] = {"status": "error",
                                            "http": r.status_code}
                continue
            audio_id = r.get_json().get("audio_id") or r.get_json().get("job_id")
            st = poll_export(client, audio_id)
            print(f"    {st.get('status')} in {st.get('wall_s')}s -> "
                  f"{st.get('file_path')}")
            results["exports"][kind] = st

    total = (sum(x["cost"] for x in results["review"])
             + ((results["learn"] or {}).get("cost") or 0.0))
    print(f"\n[demo] total cold cost ${total:.2f}")
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"[demo] timings -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
