"""Item C change 4 (2026-09-08) — three admission rules for the guideline block,
measured, with acceptance pre-declared by the batch.

    (a)  similarity above the floor, as shipped
    (b)  scope match only — a CURRENT guideline whose manifest `scope[]` shares
         >= 2 terms with the question's DOMAIN_NOUNS hits
    (c)  the union

Pre-declared acceptance: 3/3 on both probes, median block <= 8, max <= 25, no
superseded / withdrawn / draft admitted. Ship the first rule that meets it; if
only (c) does, ship (c). If none does, ship nothing and report the table.

WHY THIS COULD NOT BE MEASURED BEFORE TODAY. On 2026-09-07 three repeat runs of
probe 2 against the SAME build gave three different guideline pools, and the
report concluded: "the done-when is NOT met, and no admission rule can meet it —
the documents do not reliably reach the candidate set, because
`generate_search_terms` is non-deterministic and every similarity moves with the
boolean it writes." Item C's temperature-0 change is what makes rule (a)
measurable at all; before it, (a) was being scored against a coin toss.

The probe runs use a COLD cache (fresh terms each run), as the batch specifies —
that is the honest test of whether a rule survives regeneration, not just
whether the cache is doing the work.

    python scripts/measure_guideline_admission_rules.py
    python scripts/measure_guideline_admission_rules.py --runs 3
"""
import argparse
import json
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E  # noqa: E402
import rag           # noqa: E402
from app import RELEVANCE_GATE, multi_query_search  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from run_trauma_probes import PROBES, WATCH  # noqa: E402

FLOOR = RELEVANCE_GATE["similarity_floor"]
NOT_CURRENT = ("superseded", "superseded_in_content", "withdrawn", "draft")


def questions():
    """The 32: the 29 regression cases plus the 3 trauma probes."""
    cases = json.loads(
        (ROOT / "eval" / "questions.json").read_text(encoding="utf-8"))["cases"]
    out, seen = [], set()
    for c in cases:
        q = c["question"] if isinstance(c, dict) else c
        if q not in seen:
            seen.add(q)
            out.append((c.get("id", "case%d" % len(out)) if isinstance(c, dict)
                        else "case%d" % len(out), q))
    for pid, q in PROBES:
        if q not in seen:
            seen.add(q)
            out.append((pid, q))
    return out


def domain_nouns_in(question):
    """The question's DOMAIN_NOUNS hits — rule (b)'s left-hand side."""
    # `_DOMAIN_NOUN_RE` is ONE alternation over every noun, not a per-noun map,
    # so the hits are read off the matches rather than probed one at a time.
    q = (question or "").lower()
    return {m.group(0).lower() for m in E._DOMAIN_NOUN_RE.finditer(q)}


def manifest():
    if getattr(E, "_MANIFEST_BY_ID", None) is None:
        E._guideline_supersession_notice("")
    return E._MANIFEST_BY_ID or {}


def rule_a(question, terms=None):
    """Shipped: guideline rows the similarity floor admits.

    THROUGH `multi_query_search`, WHICH IS WHAT PRODUCTION CALLS. The first
    version of this function embedded the raw question and ranked guideline
    rows against that one vector, and reported median-above-floor = 0 for rows
    that were demonstrably reaching pools. That is instrument error #4 in
    AGENT_QUEUE.md, recorded on 2026-09-07 with the identical symptom, and I
    reproduced it exactly (rule 33).

    Production KNNs once per generated boolean AND once for the question, then
    keeps the best similarity per PMID — precisely because a well-formed
    boolean embeds FURTHER from a paper's prose than the clinician's own words
    do. Measuring against the question alone measures the wrong retrieval.
    """
    if terms is None:
        terms = [E.generate_search_terms(question, mode="review")]
    rows = multi_query_search(question, [t for t in terms if t], limit=100)
    out = set()
    for r in rows:
        if float(r.get("similarity") or 0) < FLOOR:
            continue
        if (r.get("level_key") or "") != "guideline":
            continue
        gid = (r.get("guideline_id") or "").strip()
        if gid:
            out.add(gid)
    return out


def rule_b(question, need=2):
    """Scope match only, >= `need` shared terms against the question's DOMAIN_NOUNS.

    STRICTER THAN THE SHIPPED SCOPE BYPASS, which admits on ONE scope term
    matching anywhere in the question text. Two independent domain nouns is a
    much harder thing for an unrelated question to satisfy by accident.
    """
    hits = domain_nouns_in(question)
    if not hits:
        return set()
    out = set()
    for gid, rec in manifest().items():
        if (rec.get("status") or "").lower() != "current":
            continue
        terms = set()
        for s in E._scope_terms_with_synonyms(rec.get("scope")):
            terms |= {w for w in s.lower().split() if len(w) > 2}
            terms.add(s.lower())
        if len(hits & terms) >= need:
            out.add(gid)
    return out


def citeable(gids):
    """Only rows that actually exist and can be cited count as admitted."""
    if not gids:
        return set()
    conn = rag.get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT guideline_id FROM endo_papers_rag
        WHERE guideline_id = ANY(%s)
          AND COALESCE(quarantine_reason,'') = ''
          AND COALESCE(superseded_by,'') = ''
    """, (list(gids),))
    out = {r[0] for r in cur.fetchall()}
    cur.close()
    conn.close()
    return out


def bad_status(gids):
    m = manifest()
    return {g for g in gids
            if (m.get(g, {}).get("status") or "").lower() in NOT_CURRENT}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()

    qs = questions()
    print("=" * 78)
    print("ITEM C CHANGE 4 — GUIDELINE ADMISSION RULES (a) / (b) / (c)")
    print("=" * 78)
    print("  questions: %d   similarity floor: %.2f" % (len(qs), FLOOR))
    print("  acceptance: 3/3 both probes, median <= 8, max <= 25, "
          "no superseded/withdrawn/draft")
    print()

    # `b1` is the SHIPPED scope bypass (>= 1 shared term). It is measured and
    # reported for comparison so the cost of the batch's >= 2 threshold is
    # visible, and it is NOT a shipping candidate: the batch names (a), (b) and
    # (c), and inventing a fourth rule that happens to pass would be tuning to
    # the target.
    sizes = {"a": [], "b": [], "c": [], "b1": []}
    violations = {"a": set(), "b": set(), "c": set(), "b1": set()}
    per_q = []
    for qid, q in qs:
        a = citeable(rule_a(q))
        b = citeable(rule_b(q))
        b1 = citeable(rule_b(q, need=1))     # DIAGNOSTIC ONLY — see below
        c = a | b
        for k, s in (("a", a), ("b", b), ("c", c), ("b1", b1)):
            sizes[k].append(len(s))
            violations[k] |= bad_status(s)
        per_q.append({"id": qid, "question": q,
                      "a": sorted(a), "b": sorted(b), "c": sorted(c)})
        print("  %-28s a=%-3d b=%-3d c=%-3d" % (qid[:28], len(a), len(b), len(c)))

    print()
    print("  %-6s %8s %8s %8s %s" % ("rule", "median", "max", "mean", "bad status"))
    verdict = {}
    for k in ("a", "b", "c", "b1"):
        med = statistics.median(sizes[k]) if sizes[k] else 0
        mx = max(sizes[k]) if sizes[k] else 0
        mean = sum(sizes[k]) / len(sizes[k]) if sizes[k] else 0
        ok = med <= 8 and mx <= 25 and not violations[k]
        verdict[k] = {"median": med, "max": mx, "mean": round(mean, 1),
                      "bad": sorted(violations[k]), "size_ok": ok}
        print("  %-5s %8.1f %8d %8.1f %s"
              % ("(%s)" % k + ("*" if k == "b1" else ""),
                 med, mx, mean, sorted(violations[k]) or "none"))
    print("  * (b1) is the shipped >=1 scope bypass — reported for comparison,")
    print("    NOT a shipping candidate; the batch names (a), (b), (c).")

    # ── the probes, COLD CACHE, `runs` times ──────────────────────────────
    print()
    print("  PROBES — %d runs each, term cache COLD (fresh terms every run)"
          % args.runs)
    probe_ids = ["probe2-crown-fracture", "probe3-retreat-implant"]
    probe_q = {pid: q for pid, q in PROBES}
    probe_res = {k: {} for k in ("a", "b", "c", "b1")}
    for pid in probe_ids:
        want = set(WATCH[pid])
        got = {"a": [], "b": [], "c": [], "b1": []}
        for r in range(args.runs):
            prev = E.TERM_CACHE_ENABLED
            E.TERM_CACHE_ENABLED = False      # cold: regenerate every run
            try:
                fresh = [E.generate_search_terms(probe_q[pid], mode="review")]
                a = citeable(rule_a(probe_q[pid], terms=fresh))
                b = citeable(rule_b(probe_q[pid]))
                b1 = citeable(rule_b(probe_q[pid], need=1))
            finally:
                E.TERM_CACHE_ENABLED = prev
            c = a | b
            for k, s in (("a", a), ("b", b), ("c", c), ("b1", b1)):
                got[k].append(want <= s)
        for k in ("a", "b", "c", "b1"):
            n = sum(1 for x in got[k] if x)
            probe_res[k][pid] = n
            print("    (%s) %-26s %d/%d   watched: %s"
                  % (k, pid, n, args.runs, ", ".join(sorted(want))))

    print()
    print("  VERDICT")
    shipped = None
    for k in ("a", "b", "c"):
        probes_ok = all(probe_res[k][p] == args.runs for p in probe_ids)
        passes = verdict[k]["size_ok"] and probes_ok
        verdict[k]["probes"] = {p: probe_res[k][p] for p in probe_ids}
        verdict[k]["passes"] = passes
        print("    (%s) size %s   probes %s   -> %s"
              % (k, "ok" if verdict[k]["size_ok"] else "FAIL",
                 "ok" if probes_ok else "FAIL",
                 "PASSES" if passes else "fails"))
        if passes and shipped is None:
            shipped = k
    print()
    print("  SHIP: %s" % (("rule (%s)" % shipped) if shipped
                          else "NOTHING — no rule met the pre-declared bar"))

    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    json.dump({"floor": FLOOR, "runs": args.runs, "verdict": verdict,
               "ship": shipped, "per_question": per_q},
              open("eval/reports/night10_admission_rules.json", "w",
                   encoding="utf-8"), indent=1)
    print("  wrote eval/reports/night10_admission_rules.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
