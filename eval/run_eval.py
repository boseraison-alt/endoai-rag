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
import re
import sys
import time
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
        return None, 0, 0, 0, 0
    total = n = empty = terms = failed = 0
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
            # http_status 0 = the request never got a response (DNS/network).
            # These are NOT empty results and must not be counted as queries:
            # a network outage would otherwise read as "every query matched
            # nothing", which is the malformed-query signature.
            if int(rec.get("http_status") or 0) == 0:
                failed += 1
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
    return total, n, empty, terms, failed


DIVIDED_MARKER = "The literature is currently divided on this topic"
MODULE_NOT_GENERATED = "Module not generated"
# Any numeric clinical parameter — concentrations, energies, times, ISO sizes.
NUMERIC_PARAM_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:%|mJ|mW|W|Hz|mm|mL|ml|mg|s\b|sec\b|min\b|month|year)",
    re.IGNORECASE)


def run_case_with_synthesis(case):
    """Run the FULL production path — retrieval plus LLM synthesis — through
    the Flask test client, so the answer-level assertions are evaluated against
    a real generated answer.

    This costs real money (~$1/case), which is why it is opt-in and limited to
    SYNTHESIS_SUBSET. It goes through /ask rather than calling the synthesiser
    directly so that the guardrails, validation and rendering are all exercised
    exactly as a clinician would hit them.
    """
    import endo_ai
    import app as app_mod

    endo_ai.LIBRARY_WRITE_BACK = False

    # /ask has no force_route parameter — pin it by wrapping the builder for
    # the duration of this case only.
    original = app_mod.build_evidence_base_with_progress
    pinned = case.get("force_route")

    def _pinned_builder(job_id, question, force_route=None, mode="review",
                        context_block="", prior_pmids=None):
        # Eval cases are single questions with no thread, so these are always
        # empty in practice — but they are forwarded rather than dropped, so a
        # future conversational case measures the real builder's behaviour.
        return original(job_id, question, force_route=pinned, mode=mode,
                        context_block=context_block, prior_pmids=prior_pmids)

    app_mod.build_evidence_base_with_progress = _pinned_builder
    try:
        client = app_mod.app.test_client()
        r = client.post("/ask", json={"question": case["question"],
                                      "mode": case.get("mode", "review"),
                                      "skip_clarify": True})
        if r.status_code != 200:
            raise RuntimeError(f"/ask returned {r.status_code}: {r.data[:200]}")
        job_id = r.get_json()["job_id"]
        for _ in range(4000):                       # generous: learn mode is slow
            st = client.get(f"/status/{job_id}").get_json()
            if st.get("status") in ("complete", "error", "aborted"):
                break
            time.sleep(0.5)
        else:
            raise TimeoutError("job did not finish")
    finally:
        app_mod.build_evidence_base_with_progress = original

    if st.get("status") != "complete":
        raise RuntimeError(f"job {st.get('status')}: {st.get('error')}")

    answer = st.get("answer") or ""
    exp = case.get("expect", {})
    failures = []

    for pmid in exp.get("must_cite_pmid", []):
        if pmid not in answer:
            failures.append(f"must_cite_pmid {pmid} not cited in the answer")

    for phrase in exp.get("must_contain", []):
        if phrase.lower() not in answer.lower():
            failures.append(f"must_contain {phrase!r} absent from the answer")
    for phrase in exp.get("must_not_contain", []):
        if phrase.lower() in answer.lower():
            failures.append(f"must_not_contain {phrase!r} present in the answer")

    banner = exp.get("banner", "any")
    has_banner = DIVIDED_MARKER.lower() in answer.lower()
    if banner == "divided" and not has_banner:
        failures.append("expected the divided-literature banner, none present")
    elif banner == "none" and has_banner:
        failures.append("divided-literature banner present but not expected")

    if exp.get("modules_non_empty") and MODULE_NOT_GENERATED.lower() in answer.lower():
        n = answer.lower().count(MODULE_NOT_GENERATED.lower())
        failures.append(f"{n} module(s) not generated for lack of evidence")

    # A module stating numeric clinical parameters with zero citations is the
    # failure that started all of this (invented Er:YAG settings behind a
    # disclaimer). Check per-section rather than per-answer.
    cap = exp.get("max_unsourced_numeric_modules")
    if cap is not None:
        unsourced = 0
        for section in re.split(r"\n##+ ", answer):
            if NUMERIC_PARAM_RE.search(section) and "[[PMID:" not in section:
                unsourced += 1
        if unsourced > cap:
            failures.append(f"{unsourced} section(s) state numeric clinical "
                            f"parameters with no citation (max {cap})")

    return {"route": pinned or "?", "papers": len(st.get("papers") or []),
            "per_tier": {}, "esearch_queries": 0, "esearch_hits": 0,
            "esearch_empty": 0, "esearch_hits_per_query": None,
            "search_terms_used": 0, "answer_chars": len(answer),
            "cost_usd": st.get("cost_usd"), "has_banner": has_banner}, failures


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

    # A conversational case carries the thread its question belongs to. The
    # block and the seed PMIDs are built by the SAME functions the app uses
    # (`build_context_block` / `context_prior_pmids`), so the case measures the
    # real conversational path rather than a re-implementation of it. Without
    # this, "What about in immature teeth?" is an eval case that tests nothing:
    # the string alone has no topic.
    exchanges = (case.get("context") or {}).get("exchanges") or []
    context_block = endo_ai.build_context_block(exchanges) if exchanges else ""
    prior_pmids = endo_ai.context_prior_pmids(exchanges) if exchanges else None

    offset = _audit_offset()
    evidence = build_evidence_base_with_progress(
        job_id, case["question"], force_route=case.get("force_route"),
        mode=case.get("mode", "review"),
        context_block=context_block, prior_pmids=prior_pmids) or {}
    esearch_total, n_queries, n_empty, n_terms, n_failed = _esearch_hits_since(offset)

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
        "esearch_failed": n_failed,
    }

    # Contamination guard: audit records carry no run identity, so any OTHER
    # process doing retrieval during this case (an agent verifying the UI, a
    # user in the app) bleeds into the offset window. The generator caps at 10
    # terms, so >10 level1 records can only mean interleaved runs — in which
    # case every esearch-derived number here is untrustworthy and asserting on
    # it would fail the case for someone else's queries.
    # A run where most requests never reached NCBI cannot be judged on its
    # retrieval numbers at all — they describe the network, not the queries.
    attempted = n_queries + n_failed
    network_broken = attempted > 0 and n_failed / attempted > 0.25
    if network_broken:
        print(f"  WARNING: {n_failed}/{attempted} esearch calls never reached NCBI "
              f"(network/DNS). Skipping esearch-based assertions — this run's "
              f"retrieval numbers are not meaningful. Re-run when the network is up.")

    contaminated = n_terms > 10 or network_broken
    if n_terms > 10:
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

    # ── Case mode sweeps every tier ──────────────────────────────────────
    # `EARLY_STOP_MIN_PAPERS` skips level2..level5 and invitro once
    # cochrane+level1 clear 15 papers. Review wants that; a case discussion of
    # an unusual presentation does not, because the case series it would skip
    # are often the only literature that exists. `min_tiers_below_level1`
    # counts tiers actually populated BELOW level1, which is the only way to
    # see from outside whether the early stop fired.
    floor = exp.get("min_tiers_below_level1")
    if floor is not None:
        lower = [t for t in TIER_ORDER
                 if t not in ("cochrane", "level1") and per_tier.get(t)]
        if len(lower) < floor:
            failures.append(
                f"only {len(lower)} tier(s) below level1 populated ({lower}) < "
                f"min_tiers_below_level1={floor} — the review-mode early stop "
                "appears to have fired on a case/learn sweep")

    # ── Conversation context ─────────────────────────────────────────────
    # A follow-up whose context did not reach the term generators produces
    # queries built from the bare follow-up string. The observable signature is
    # a paper set with nothing to do with the thread's topic, so the case names
    # a term the thread is about and the retrieved TITLES must contain it.
    topic_terms = [t.lower() for t in (exp.get("evidence_must_mention") or [])]
    if topic_terms:
        titles = " ".join(
            (p.get("title") or "").lower()
            for t in TIER_ORDER
            for p in ((evidence.get(t) or {}).get("scored") or []))
        # Live-path papers carry no title in the scored dict; fall back to the
        # annotated text block, which does.
        if not titles.strip():
            titles = " ".join(((evidence.get(t) or {}).get("text") or "").lower()
                              for t in TIER_ORDER)
        missing = [t for t in topic_terms if t not in titles]
        if missing:
            failures.append(
                f"no retrieved paper mentions {missing} — the conversation "
                "context did not reach the search-term generators")

    # A follow-up that RESETS to a new topic must not be dragged back to the
    # old one. Same measurement, opposite assertion.
    for term in (exp.get("evidence_must_not_be_dominated_by") or []):
        titles = [(p.get("title") or "").lower()
                  for t in TIER_ORDER
                  for p in ((evidence.get(t) or {}).get("scored") or [])]
        if titles:
            share = sum(term.lower() in ttl for ttl in titles) / len(titles)
            if share > 0.5:
                failures.append(
                    f"{share:.0%} of retrieved papers still mention {term!r} — a "
                    "new-topic question inherited the previous thread's topic")

    # A6: named papers that must survive query variance. Retrieval-side.
    want = exp.get("must_include_pmid") or []
    if want:
        got = {p.get("pmid") for t in TIER_ORDER
               for p in ((evidence.get(t) or {}).get("scored") or [])}
        missing = [x for x in want if x not in got]
        if missing:
            failures.append(f"must_include_pmid absent from the evidence base: "
                            f"{missing} — the authority guarantee did not hold")

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

    # ── The case-discussion opening ──────────────────────────────────────
    # One Haiku call, same order of cost as the search-term generator this
    # harness already pays for on every case — NOT synthesis. It is here
    # because the opening is the half of case mode that retrieval cannot see:
    # `generate_case_followups` decides whether the clinician is interrogated
    # about facts they already gave, and nothing downstream records that.
    clarify = exp.get("clarify")
    if clarify:
        try:
            questions = endo_ai.generate_case_followups(case["question"]) or []
        except Exception as e:                      # fail loudly, not silently
            questions = None
            failures.append(f"clarify gate raised {type(e).__name__}: {e}")
        if questions is not None:
            measured["clarify_questions"] = len(questions)
            lo, hi = clarify.get("count_between", [0, 99])
            if not (lo <= len(questions) <= hi):
                failures.append(
                    f"clarify asked {len(questions)} question(s), expected "
                    f"{lo}-{hi}: {questions}")
            blob = " ".join(questions).lower()
            asked = [t for t in (clarify.get("must_not_ask_about") or [])
                     if t.lower() in blob]
            if asked:
                failures.append(
                    f"clarify re-asked facts the description already states: "
                    f"{asked} in {questions}")
            if clarify.get("every_question_states_its_reason"):
                bare = [q for q in questions
                        if "—" not in q and " - " not in q and "–" not in q]
                if bare:
                    failures.append(f"clarify question(s) with no reason clause: {bare}")

    return measured, failures


# The five cases the synthesis subset runs. Chosen to cover both routes, both
# modes, and the two topics with a known regression history. Everything else
# stays retrieval-only: synthesis costs roughly $1 per case.
SYNTHESIS_SUBSET = [
    "laser-root-canal-disinfection-live",
    "laser-root-canal-disinfection-library",
    "single-vs-multiple-visit",
    "naocl-concentration",
    "pips-vs-ultrasonic",
]


# ── --diff ────────────────────────────────────────────────────────────────
# The flag was declared and then never read: `--diff` ran an ordinary eval,
# printed no table, and exited 0. That is the codebase's own bug class (d) —
# a check that fails open and shows nothing — living inside the harness whose
# job is to catch it. Everything below exists to make the flag mean what its
# help text says.
#
# Drift is REPORTED, never gated. Search terms are LLM-generated, so a count
# outside a three-run range is routine; the floors in each case's `expect`
# block are the gate, and they already set the exit code.

# Metric name in `measured` -> metric name in the baseline file.
_DIFF_METRICS = (
    ("papers", "papers"),
    ("search_terms_used", "search_terms"),
    ("esearch_hits_per_query", "hits_per_query"),
)


def _load_baseline(name):
    path = Path(name)
    if not path.is_absolute():
        path = Path(__file__).parent / name
    if not path.exists():
        print(f"WARNING: baseline {path} not found — --diff has nothing to "
              f"compare against.")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("cases", {})
    except (OSError, json.JSONDecodeError) as e:
        print(f"WARNING: baseline {path} unreadable ({e}) — --diff skipped.")
        return {}


def _diff_case(cid, measured, base):
    """One row per metric that left the baseline's observed range."""
    if not base:
        return [(cid, "(no baseline)", "", "", "NEW CASE")]
    rows = []
    for got_key, base_key in _DIFF_METRICS:
        got = measured.get(got_key)
        rng = base.get(base_key)
        if got is None or not rng:
            continue
        lo, hi = rng.get("min"), rng.get("max")
        if lo is None or hi is None:
            continue
        if lo <= got <= hi:
            continue
        rows.append((cid, base_key, f"{lo:g}-{hi:g}", f"{got:g}",
                     "ABOVE" if got > hi else "BELOW"))
    routes = base.get("routes_observed") or []
    if routes and measured.get("route") not in routes:
        rows.append((cid, "route", "|".join(routes), str(measured.get("route")),
                     "CHANGED"))
    return rows


def _print_diff(name, rows, n_cases):
    print(f"\n{'=' * 70}\nDIFF vs {name}  ({n_cases} case(s) run)\n{'=' * 70}")
    if not rows:
        print("  every metric inside the range the baseline already observed")
        return
    print(f"  {'case':<38} {'metric':<16} {'baseline':>12} {'this run':>10}")
    for cid, metric, rng, got, direction in rows:
        print(f"  {cid:<38} {metric:<16} {rng:>12} {got:>10}  {direction}")
    print(f"\n  {len(rows)} metric(s) outside the baseline range. Ranges spot "
          f"drift; they do not gate — the exit code comes from the floors.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", help="run only this case id")
    ap.add_argument("--route", help="run only cases pinned to this route")
    ap.add_argument("--update-baseline", action="store_true",
                    help="rewrite each case's baseline from this run")
    ap.add_argument("--cheap", action="store_true",
                    help="retrieval only, no synthesis (this is the DEFAULT; "
                         "the flag exists to be explicit in scripts)")
    ap.add_argument("--synthesis-subset", action="store_true",
                    help="run the 5-case subset WITH LLM synthesis and evaluate "
                         "answer-level assertions. Costs real money (~$1/case).")
    ap.add_argument("--diff", action="store_true",
                    help="print a per-case table of this run against the stored "
                         "baseline ranges. Drift is REPORTED, not gated: the "
                         "floors in each case's expect block are what fail a "
                         "run, and they already do.")
    ap.add_argument("--baseline", default="baseline_v5.json",
                    help="baseline file --diff compares against "
                         "(default: baseline_v5.json, alongside this script)")
    args = ap.parse_args()

    doc, cases = load_cases()
    if args.synthesis_subset:
        cases = [c for c in cases if c["id"] in SYNTHESIS_SUBSET]
        missing = set(SYNTHESIS_SUBSET) - {c["id"] for c in cases}
        if missing:
            print(f"WARNING: subset ids not in questions.json: {sorted(missing)}")
    if args.id:
        cases = [c for c in cases if c["id"] == args.id]
    if args.route:
        cases = [c for c in cases if c.get("force_route") == args.route]
    if not cases:
        print("no cases matched")
        return 1

    mode_label = ("SYNTHESIS" if args.synthesis_subset else "RETRIEVAL-ONLY")
    print(f"mode: {mode_label}" + ("" if args.synthesis_subset else
          "  (no answers generated; must_contain / banner / modules_non_empty "
          "are NOT evaluated)"))

    baseline = _load_baseline(args.baseline) if args.diff else {}
    if args.diff and not baseline:
        print(f"WARNING: --diff found no cases in {args.baseline} — the table "
              f"below will be empty. That is a missing file, not a clean run.")
    diff_rows = []

    n_fail = 0
    for case in cases:
        pin = case.get("force_route")
        print(f"\n{'=' * 70}\n{case['id']}"
              f"{f'   [pinned: {pin}]' if pin else '   [route not pinned]'}\n{'=' * 70}")
        try:
            measured, failures = (run_case_with_synthesis(case)
                                  if args.synthesis_subset else run_case(case))
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
                  f"{measured['search_terms_used']} search terms"
                  + (f", {measured['esearch_failed']} NEVER SENT — network"
                     if measured.get("esearch_failed") else "") + ")")

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

        if args.diff:
            diff_rows.extend(_diff_case(case["id"], measured,
                                        baseline.get(case["id"])))

        if args.update_baseline:
            case["baseline"] = {**base, "route": measured["route"],
                                "papers": measured["papers"],
                                "per_tier": measured["per_tier"]}

    if args.update_baseline:
        QUESTIONS.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        print("\nbaselines rewritten")

    if args.diff:
        _print_diff(args.baseline, diff_rows, len(cases))

    print(f"\n{len(cases) - n_fail}/{len(cases)} cases passed  [{mode_label}]")
    if not args.synthesis_subset:
        print("NOTE: answer-level assertions (must_contain, must_not_contain, "
              "banner, modules_non_empty, max_unsourced_numeric_modules) were "
              "NOT evaluated. Run --synthesis-subset for those.")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
