"""Item E (2026-09-08) — A/B for extending the species guard to the paper lanes.

THE GUARD. `GUIDELINE_SPECIES_GUARD = " NOT (animals[mh] NOT humans[mh])"` has
been ANDed into the guideline lane since 2026-09-06. It removes only records
MeSH-indexed as animal WITHOUT also being indexed as human — so a study on both
survives, by construction. Item E asks whether it should also go on the paper
lanes.

THE PRE-DECLARED STOP: **zero human rows lost, or revert.** Recall is the thing
this system cannot trade away, and a guard that drops one human trial to remove
ten rat studies is a bad trade at any ratio.

WHY THIS IS NOT A POOL A/B. Item C measured the same-build noise floor at 26% of
pools (rule 38): re-running an identical query changes membership a quarter of
the time, all of it PubMed's own ranking. A before/after pool comparison at that
noise level cannot see a guard that removes a handful of rows. So this does not
compare pools.

Instead it asks the only question that matters, per row: of the PMIDs the guard
actually EXCLUDES, is any one of them indexed as human?

Note the word "actually". Absence from the guarded top-60 is NOT exclusion:
adding a NOT clause changes the query, PubMed's relevance ordering is a function
of the query, and records that still satisfy the filter get re-ranked out of the
window. Measured here: 230 PMIDs absent from the guarded list, of which only 87
are genuinely excluded and 143 merely moved. The first version of this script
conflated the two and returned a confident REVERT on 147 "lost human rows" that
the guard cannot exclude by construction. See `fails_the_guard`.

    python scripts/ab_species_guard_paper_lanes.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from measure_guideline_admission_rules import questions  # noqa: E402

GUARD = E.GUIDELINE_SPECIES_GUARD
RETMAX = 60


def esearch(term):
    r = E.ncbi_get(f"{E.NCBI_EUTILS_BASE}/esearch.fcgi",
                   params=E._ncbi_params({
                       "db": "pubmed", "term": term, "retmode": "json",
                       "retmax": RETMAX, "sort": "relevance"}), timeout=25)
    return [str(i) for i in
            r.json().get("esearchresult", {}).get("idlist", [])]


def fails_the_guard(pmids):
    """Which of these the guard ACTUALLY excludes.

    THE INSTRUMENT THIS REPLACES WAS WRONG, and it produced a confident REVERT.
    The first version called every PMID present in the unguarded top-60 and
    absent from the guarded top-60 a "removal", then checked those against
    humans[mh] and found 147 -- which is impossible by construction, because
    `NOT (animals[mh] NOT humans[mh])` excludes only records indexed animal AND
    NOT human. That contradiction is what gave it away.

    The cause: adding a NOT clause changes the QUERY, and PubMed's relevance
    ordering is a function of the query. Records that still satisfy the filter
    get re-ranked and fall out of the retmax window. Absence from a truncated
    ranked list is not exclusion. (Rule 33 again.)

    This asks the set-membership question directly, per PMID: does it survive
    the guard on its own? Deterministic, and ranking cannot touch it.
    """
    if not pmids:
        return set()
    survives = set()
    for i in range(0, len(pmids), 50):
        chunk = pmids[i:i + 50]
        term = "(%s)%s" % (" OR ".join("%s[uid]" % p for p in chunk), GUARD)
        try:
            survives |= set(esearch(term))
        except Exception as ex:
            print("    guard check failed for a chunk: %s" % ex)
    return set(pmids) - survives


def human_indexed(pmids):
    """Which of these PubMed itself indexes as humans[mh]."""
    if not pmids:
        return set()
    out = set()
    for i in range(0, len(pmids), 50):
        chunk = pmids[i:i + 50]
        term = "(%s) AND humans[mh]" % " OR ".join("%s[uid]" % p for p in chunk)
        try:
            out |= set(esearch(term))
        except Exception as ex:
            print("    humans[mh] check failed for a chunk: %s" % ex)
    return out


def main():
    qs = questions()
    print("=" * 78)
    print("ITEM E — SPECIES GUARD ON THE PAPER LANES  (A/B)")
    print("=" * 78)
    print("  guard  : %s" % GUARD.strip())
    print("  stop   : ZERO human rows lost, or revert")
    print("  questions: %d   retmax: %d" % (len(qs), RETMAX))
    print()

    removed_all, kept_total, rows = [], 0, []
    for qid, q in qs:
        try:
            term = E.generate_search_terms(q, mode="review")
            a = esearch(term)                      # without the guard
            b = esearch(term + GUARD)              # with it
        except Exception as ex:
            print("  %-28s FAILED: %s" % (qid[:28], ex))
            continue
        removed = [p for p in a if p not in set(b)]
        added = [p for p in b if p not in set(a)]
        kept_total += len(b)
        removed_all.extend(removed)
        rows.append({"id": qid, "without": len(a), "with": len(b),
                     "removed": removed, "added": added})
        print("  %-28s %3d -> %3d   removed %d%s"
              % (qid[:28], len(a), len(b), len(removed),
                 "   (+%d churn)" % len(added) if added else ""))

    uniq = sorted(set(removed_all))
    print()
    print("  PMIDs absent from the guarded top-%d : %d" % (RETMAX, len(uniq)))
    print("  ...of which the guard ACTUALLY excludes (asked per PMID):")
    excluded = sorted(fails_the_guard(uniq))
    reranked = len(uniq) - len(excluded)
    print("    genuinely excluded by the guard   : %d" % len(excluded))
    print("    merely re-ranked out of the window: %d  (not a loss)" % reranked)
    print()
    print("  checking the genuinely excluded against humans[mh] ...")
    human = human_indexed(excluded)
    print()
    print("  " + "-" * 70)
    print("  excluded and NOT human-indexed : %d" % (len(excluded) - len(human)))
    print("  excluded BUT human-indexed     : %d" % len(human))
    if human:
        print()
        print("  HUMAN ROWS LOST — the pre-declared stop. Guard NOT shipped:")
        for p in sorted(human)[:20]:
            print("    %s" % p)
    verdict = "SHIP" if not human else "REVERT — human rows lost"
    print()
    print("  VERDICT: %s" % verdict)

    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    json.dump({"guard": GUARD, "questions": len(rows),
               "absent_from_guarded_topN": len(uniq),
               "genuinely_excluded": excluded,
               "reranked_not_excluded": reranked,
               "removed_human_indexed": sorted(human),
               "verdict": verdict, "rows": rows},
              open("eval/reports/night10_species_guard_ab.json", "w",
                   encoding="utf-8"), indent=1)
    print("  wrote eval/reports/night10_species_guard_ab.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
