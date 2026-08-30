"""
Retrieval eval harness.

Runs each case in questions.json through the real evidence pipeline and checks
the assertions in its `expect` block. Retrieval only — no curriculum synthesis,
so a full pass costs PubMed requests and embedding time but no LLM tokens.

    python eval/run_eval.py                  # every case
    python eval/run_eval.py --id laser-root-canal-disinfection-live
    python eval/run_eval.py --route live     # only cases pinned to a route
    python eval/run_eval.py --update-baseline  # rewrite baselines from this run

Why `force_route` exists at all: write-back silently rewrites what a case
measures. The laser regression was a live search-term failure, but the fixed run
wrote 196 papers into the library, so the same question then served from the
library and stopped exercising the generator that had broken. A case that does
not pin its route stops testing the thing it was written for, without failing.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

QUESTIONS = Path(__file__).parent / "questions.json"

SR_TIERS = ("cochrane", "level1")
RCT_TIERS = ("level1",)
COCHRANE_JOURNAL_HINTS = ("cochrane database", "cochrane db syst")


def load_cases():
    doc = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    return doc, doc["cases"]


AUDIT_LOG = ROOT / "pubmed_audit.jsonl"


def _audit_offset():
    return AUDIT_LOG.stat().st_size if AUDIT_LOG.exists() else 0


def _esearch_hits_since(offset):
    """Total PMIDs esearch returned across every query this run made.

    This is the number that actually collapsed in the laser regression: 5 across
    28 queries, against ~909 after the fix. It has to come from the audit log
    rather than from the evidence dict, because by the time papers reach the
    evidence dict they have already passed the per-tier quality threshold — a
    count taken there just shadows the final paper count and tells you nothing
    about whether the QUERY was broken.

    Returns (total_returned, n_queries, n_empty_queries).
    """
    if not AUDIT_LOG.exists():
        return None, 0, 0, 0
    total = n = empty = terms = 0
    with AUDIT_LOG.open("r", encoding="utf-8") as fh:
        fh.seek(offset)
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            got = int(rec.get("n_returned") or 0)
            total += got
            n += 1
            if got == 0:
                empty += 1
            # Each search term is fetched once per tier, so the number of
            # level1 records IS the term count for the run. This is how the
            # harness watches generator stability (1-term flapping was the
            # ±50% noise source) without needing a new field in the pipeline.
            if rec.get("level_key") == "level1":
                terms += 1
    return total, n, empty, terms


def run_case(case):
    """Execute one case's retrieval and return (measured, failures)."""
    import endo_ai
    from app import build_evidence_base_with_progress, jobs
    from endo_ai import TIER_ORDER

    # An eval run must not mutate the thing it measures. With write-back on,
    # the live cases deposit their results into the library, so case N+1 and
    # every later RUN see a different library than case N did — baselines
    # stop being reproducible and a "range over three runs" measures the
    # write-back, not the variance. It is also the dominant cost: embedding
    # several hundred new papers on CPU took longer than all the PubMed
    # traffic combined. Same reasoning as force_route, one layer down.
    endo_ai.LIBRARY_WRITE_BACK = False

    job_id = f"eval-{case['id']}"
    jobs[job_id] = {"status": "running", "steps": [], "progress": 0}

    offset = _audit_offset()
    evidence = build_evidence_base_with_progress(
        job_id, case["question"], force_route=case.get("force_route")) or {}
    esearch_total, n_queries, n_empty, n_terms = _esearch_hits_since(offset)

    per_tier, papers = {}, []
    for tier in TIER_ORDER:
        block = evidence.get(tier) or {}
        scored = block.get("scored") or []
        if scored:
            per_tier[tier] = len(scored)
            papers.extend(scored)

    sources = {(evidence.get(t) or {}).get("source")
               for t in TIER_ORDER if evidence.get(t)}
    route = "library" if sources == {"rag"} else ("live" if "pubmed" in sources
                                                  else "|".join(sorted(s for s in sources if s)))

    measured = {
        "route": route,
        "papers": len(papers),
        "per_tier": per_tier,
        "papers_kept_after_quality_filter":
            (evidence.get("_summary") or {}).get("distinct_pmids_retrieved"),
        "esearch_hits":    esearch_total,
        "esearch_queries": n_queries,
        "esearch_empty":   n_empty,
        # Hits PER QUERY, not total. generate_multi_search_terms is not
        # deterministic in how many terms it emits — observed 1 term (7 queries)
        # and 8 terms (56 queries) for the same question minutes apart — so a
        # total-hits threshold fails on term count rather than on query quality.
        # Per-query separates the two cleanly: the failing laser run managed
        # 0.2 hits/query, healthy runs 29-41.
        "esearch_hits_per_query": (esearch_total / n_queries) if n_queries else None,
        "search_terms_used": n_terms,
    }

    # Contamination guard: audit records carry no run identity, so any OTHER
    # process doing retrieval during this case (an agent verifying the UI, a
    # user in the app) bleeds into the offset window. The generator caps at 10
    # terms, so >10 level1 records can only mean interleaved runs — in which
    # case every esearch-derived number here is untrustworthy and asserting on
    # it would fail the case for someone else's queries.
    contaminated = n_terms > 10
    if contaminated:
        print(f"  WARNING: {n_terms} search terms in the audit window — a "
              f"concurrent retrieval is interleaved; skipping esearch-based "
              f"assertions for this run. Re-run when the app is idle.")

    exp = case.get("expect", {})
    failures = []

    want_route = exp.get("route")
    if want_route and want_route != "any" and route != want_route:
        failures.append(f"route={route!r}, expected {want_route!r}")

    if len(papers) < exp.get("min_papers", 0):
        failures.append(f"papers={len(papers)} < min_papers={exp['min_papers']}")

    n_sr = sum(per_tier.get(t, 0) for t in SR_TIERS)
    if n_sr < exp.get("min_sr", 0):
        failures.append(f"systematic reviews={n_sr} < min_sr={exp['min_sr']}")

    n_rct = sum(per_tier.get(t, 0) for t in RCT_TIERS)
    if n_rct < exp.get("min_rct", 0):
        failures.append(f"level1={n_rct} < min_rct={exp['min_rct']}")

    if exp.get("min_hits_per_query") is not None and not contaminated:
        if not n_queries:
            failures.append("min_hits_per_query set but no esearch calls were logged "
                            "(library route, or pubmed_audit.jsonl is not being written)")
        else:
            per_q = measured["esearch_hits_per_query"]
            if per_q < exp["min_hits_per_query"]:
                failures.append(
                    f"esearch returned {per_q:.1f} hits/query < {exp['min_hits_per_query']} "
                    f"({measured['esearch_hits']} over {n_queries} queries) — "
                    "the laser regression's real signature")

    if exp.get("min_terms") is not None and n_queries and not contaminated:
        if n_terms < exp["min_terms"]:
            failures.append(f"search_terms={n_terms} < min_terms={exp['min_terms']} "
                            "(generator degraded — check [search_terms] warnings)")

    # A FRACTION, not an absolute: with 7+ generated terms, the niche angle
    # terms crossed with narrow tier filters (case-control, case series)
    # legitimately return zeros. What distinguishes the malformed-query failure
    # is that MOST queries return nothing (25/28 = 89% in the laser
    # regression), not that some do.
    if exp.get("max_empty_fraction") is not None and n_queries and not contaminated:
        frac = n_empty / n_queries
        if frac > exp["max_empty_fraction"]:
            failures.append(f"{n_empty}/{n_queries} queries ({frac:.0%}) returned "
                            f"nothing (max {exp['max_empty_fraction']:.0%}) — when most "
                            "queries match no records the queries are malformed, "
                            "not the topic thin")

    # The check that would have caught "Cochrane Review[pt]" directly.
    if exp.get("cochrane_papers_must_be_cochrane_journal"):
        impostors = [
            (p.get("pmid"), p.get("journal"))
            for p in ((evidence.get("cochrane") or {}).get("scored") or [])
            if not any(h in (p.get("journal") or "").lower()
                       for h in COCHRANE_JOURNAL_HINTS)
        ]
        if impostors:
            failures.append(f"{len(impostors)} cochrane-tier paper(s) not from the "
                            f"Cochrane Database: {impostors[:5]}")

    return measured, failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", help="run only this case id")
    ap.add_argument("--route", help="run only cases pinned to this route")
    ap.add_argument("--update-baseline", action="store_true",
                    help="rewrite each case's baseline from this run")
    args = ap.parse_args()

    doc, cases = load_cases()
    if args.id:
        cases = [c for c in cases if c["id"] == args.id]
    if args.route:
        cases = [c for c in cases if c.get("force_route") == args.route]
    if not cases:
        print("no cases matched")
        return 1

    n_fail = 0
    for case in cases:
        pin = case.get("force_route")
        print(f"\n{'=' * 70}\n{case['id']}"
              f"{f'   [pinned: {pin}]' if pin else '   [route not pinned]'}\n{'=' * 70}")
        try:
            measured, failures = run_case(case)
        except Exception as e:
            print(f"  ERROR {type(e).__name__}: {e}")
            n_fail += 1
            continue

        print(f"  route  {measured['route']}")
        print(f"  papers {measured['papers']}   {measured['per_tier']}")
        if measured["esearch_queries"]:
            print(f"  esearch  {measured['esearch_hits']} hits over "
                  f"{measured['esearch_queries']} queries = "
                  f"{measured['esearch_hits_per_query']:.1f}/query "
                  f"({measured['esearch_empty']} returned nothing, "
                  f"{measured['search_terms_used']} search terms)")

        base = case.get("baseline") or {}
        if base.get("papers") is not None:
            delta = measured["papers"] - base["papers"]
            print(f"  vs baseline: {base['papers']} -> {measured['papers']} ({delta:+d})")

        if failures:
            n_fail += 1
            for f in failures:
                print(f"  FAIL  {f}")
        else:
            print("  PASS")

        if args.update_baseline:
            case["baseline"] = {**base, "route": measured["route"],
                                "papers": measured["papers"],
                                "per_tier": measured["per_tier"]}

    if args.update_baseline:
        QUESTIONS.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        print("\nbaselines rewritten")

    print(f"\n{len(cases) - n_fail}/{len(cases)} cases passed")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
