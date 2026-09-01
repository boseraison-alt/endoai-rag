"""
Trace one case turn end to end, before changing anything (`case-v2` Item 1).

THE FAILURE THIS EXISTS TO REPRODUCE. Case: "20-year-old, necrotic tooth, no
restoration, no caries — what could the cause be?" The answer centred on
endodontic MANAGEMENT and AAE guidance and never produced the etiologic
differential a clinician asking "what could the cause be?" is asking for —
dens invaginatus, unrecognised trauma, a palatal/radicular groove, a crack, an
orthodontic history. The follow-up questions asked about bisphosphonate use,
which is implausible at 20 and discriminates nothing here.

THE HYPOTHESIS, to be confirmed or killed BEFORE any code changes: retrieval
fetched management literature because the composed query never contained a
candidate etiology. `run_case_chat` passes the raw case description to
`build_evidence_base_with_progress`, the term generators turn it into a query
about necrotic teeth and root canal treatment, and no paper about dens
invaginatus is ever a candidate. The synthesis prompt cannot rank a
differential out of an evidence base that contains none of the differential.

What this captures, in order:
  1. the follow-up questions `generate_case_followups` asks
  2. the composed PubMed search term (`generate_search_terms`)
  3. the multi-query RAG terms (`generate_multi_search_terms`)
  4. every esearch call the run makes, from `pubmed_audit.jsonl`, pid-filtered
  5. the evidence base by tier, with titles
  6. the answer, and where its first management sentence sits relative to its
     first etiology sentence

Read-only with respect to code. It spends real money on one case turn.

    python scripts/trace_case.py --out eval/logs/case_trace_before.json
"""

import argparse
import io
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import endo_ai  # noqa: E402

CASE = ("20-year-old, necrotic tooth, no restoration, no caries — what could "
        "the cause be?")

# Words that name a cause rather than a treatment. Used only for REPORTING —
# the trace records where they appear; it does not judge the answer.
ETIOLOGY_TERMS = [
    "dens invaginatus", "invaginatus", "dens in dente",
    "trauma", "traumatic", "luxation", "concussion", "avulsion",
    "palatogingival groove", "radicular groove", "palatal groove",
    "developmental groove",
    "crack", "cracked tooth", "infraction", "fracture",
    "orthodontic", "orthodontics",
    "dens evaginatus", "talon cusp",
    "anachoresis", "periodontal", "attrition", "bruxism",
    "aetiolog", "etiolog", "differential",
]
MANAGEMENT_TERMS = [
    "root canal treatment", "endodontic treatment", "obturation",
    "instrumentation", "irrigation", "sodium hypochlorite", "naocl",
    "apexification", "mta", "calcium hydroxide", "regenerative endodontic",
    "aae ", "guideline",
]


def _audit_offset():
    p = Path(endo_ai._PUBMED_AUDIT_LOG_PATH)
    return p.stat().st_size if p.exists() else 0


def _esearch_since(offset):
    """Every esearch this PROCESS made since `offset`. pid-filtered, for the
    same reason `run_eval` filters: this log is shared."""
    p = Path(endo_ai._PUBMED_AUDIT_LOG_PATH)
    if not p.exists():
        return []
    mine = os.getpid()
    out = []
    with p.open("r", encoding="utf-8") as fh:
        fh.seek(offset)
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("pid") is not None and int(rec["pid"]) != mine:
                continue
            out.append({k: rec.get(k) for k in
                        ("label", "level_key", "search_term", "n_returned",
                         "http_status")})
    return out


def _term_hits(text, terms):
    """[(term, first index)] for terms present, in order of appearance."""
    low = (text or "").lower()
    hits = [(t, low.index(t)) for t in terms if t in low]
    return sorted(hits, key=lambda kv: kv[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default=CASE)
    ap.add_argument("--out", default="eval/logs/case_trace.json")
    ap.add_argument("--label", default="before")
    args = ap.parse_args()

    trace = {"label": args.label, "case": args.case}
    print(f"=== CASE ===\n{args.case}\n")

    # 1. Follow-up questions --------------------------------------------
    t0 = time.perf_counter()
    from endo_ai import generate_case_followups
    followups = generate_case_followups(args.case)
    trace["followups"] = followups
    print(f"--- FOLLOW-UP QUESTIONS ({len(followups)}) ---")
    for q in followups:
        print(f"  - {q}")
    print()

    # 2 + 3. The composed queries ---------------------------------------
    smart = endo_ai.generate_search_terms(args.case)
    trace["search_term"] = smart
    print(f"--- COMPOSED PUBMED TERM ---\n  {smart}\n")

    try:
        multi = endo_ai.generate_multi_search_terms(args.case, smart)
    except TypeError:
        multi = endo_ai.generate_multi_search_terms(args.case)
    trace["multi_terms"] = multi
    print(f"--- MULTI-QUERY RAG TERMS ({len(multi)}) ---")
    for m in multi:
        print(f"  - {m}")
    print()

    # 4 + 5. The real retrieval the case path performs -------------------
    import app as app_mod
    off = _audit_offset()
    evidence = app_mod.build_evidence_base_with_progress(
        "trace-case", args.case, mode="case")
    trace["esearch"] = _esearch_since(off)

    tiers = {}
    for key in endo_ai.TIER_ORDER:
        block = evidence.get(key) or {}
        scored = block.get("scored") or []
        if scored:
            tiers[key] = [{"pmid": p.get("pmid"), "title": (p.get("title") or "")[:110],
                           "year": p.get("year"), "score": p.get("score")}
                          for p in scored]
    trace["tiers"] = tiers
    print("--- EVIDENCE BASE BY TIER ---")
    for key, papers in tiers.items():
        print(f"  {key}: {len(papers)}")
        for p in papers[:4]:
            print(f"      {p['pmid']}  {p['title']}")
    total = sum(len(v) for v in tiers.values())
    trace["n_papers"] = total
    print(f"  TOTAL {total} papers\n")

    # Does the evidence base contain any candidate etiology at all?
    all_titles = " ".join(p["title"] for v in tiers.values() for p in v).lower()
    trace["etiology_in_titles"] = [t for t, _i in
                                   _term_hits(all_titles, ETIOLOGY_TERMS)]
    print(f"--- ETIOLOGY TERMS IN RETRIEVED TITLES ---\n"
          f"  {trace['etiology_in_titles'] or 'NONE'}\n")

    # 6. The answer ------------------------------------------------------
    from endo_ai import ask_case_question
    answer, cost = ask_case_question([{"role": "user", "content": args.case}],
                                     evidence)
    trace["answer"] = answer
    trace["cost"] = cost
    trace["elapsed"] = round(time.perf_counter() - t0, 1)

    et = _term_hits(answer, ETIOLOGY_TERMS)
    mg = _term_hits(answer, MANAGEMENT_TERMS)
    trace["first_etiology"] = et[0] if et else None
    trace["first_management"] = mg[0] if mg else None
    trace["etiology_terms_in_answer"] = [t for t, _i in et]
    print(f"--- ANSWER ({len(answer)} chars, ${cost:.4f}) ---")
    print(answer[:2000])
    print("\n--- WHERE THE ANSWER STARTS ---")
    print(f"  first etiology term:   {et[0] if et else 'NONE'}")
    print(f"  first management term: {mg[0] if mg else 'NONE'}")
    if et and mg:
        print(f"  -> the answer leads with "
              f"{'ETIOLOGY' if et[0][1] < mg[0][1] else 'MANAGEMENT'}")
    elif mg:
        print("  -> the answer leads with MANAGEMENT and names no etiology at all")

    p = ROOT / args.out
    p.parent.mkdir(parents=True, exist_ok=True)
    io.open(p, "w", encoding="utf-8").write(
        json.dumps(trace, indent=1, ensure_ascii=False))
    print(f"\nwrote {p}")


if __name__ == "__main__":
    main()
