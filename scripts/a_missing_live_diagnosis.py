"""Item A — WHY papers from the bare query are absent from the assembled pool.

THE CLAIM THAT FAILED. Item A predicted the "missing live papers" fraction
would fall to zero by construction: if every question runs the live lanes, the
live set IS the pool. Measured on all 32: it is non-zero on every one.

WHAT THE HARNESS WAS ACTUALLY COMPARING, and this is the third instrument error
of its kind in three days. `a_live_default_measure.live_pmids` sends the BARE
generated term, retmax 40, sorted by relevance. The live lanes send something
else entirely — per-tier publication-type filters, `ENDO_DOMAIN_FILTER`, a
retracted exclusion, the species guard — and then apply per-tier quality floors
and caps. Two different queries cannot have the same answer, so "missing" was
measuring the difference between them and calling it a loss.

So this asks, per PMID, WHY it is absent — with rule 41's per-PMID test rather
than by diffing lists. Every reason is a legitimate filter or it is a real loss,
and the point of the table is to say which.

    python scripts/a_missing_live_diagnosis.py --n 4
"""
import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E  # noqa: E402
import rag  # noqa: E402


def esearch(term, retmax=60):
    r = E.ncbi_get(f"{E.NCBI_EUTILS_BASE}/esearch.fcgi",
                   params=E._ncbi_params({
                       "db": "pubmed", "term": term, "retmode": "json",
                       "retmax": retmax, "sort": "relevance"}), timeout=25)
    return [str(i) for i in
            r.json().get("esearchresult", {}).get("idlist", [])]


def satisfies(pmids, clause, joiner="AND"):
    """Which of these PMIDs satisfy `clause` — asked per PMID (rule 41).

    `joiner` EXISTS BECAUSE `AND (NOT ...)` RETURNS NOTHING. PubMed rejects a
    parenthesised clause that begins with NOT — it answers
    `outputmessages: ['NOT', 'No items found.']` and an empty set. The first
    version of this script used `AND (NOT "Retracted Publication"[pt] ...)`,
    so every in-domain PMID came back as failing the check, and the diagnosis
    read "97 of 155 missing papers are retracted (63%)". None of them was.

    Caught by testing the clause against a PMID known not to be retracted,
    which is the habit that catches all four of these: ask the instrument a
    question you already know the answer to.
    """
    if not pmids:
        return set()
    out = set()
    for i in range(0, len(pmids), 50):
        chunk = pmids[i:i + 50]
        ids = " OR ".join("%s[uid]" % p for p in chunk)
        term = ("(%s) %s" % (ids, clause) if joiner == "BARE"
                else "(%s) AND (%s)" % (ids, clause))
        try:
            out |= set(esearch(term, retmax=60))
        except Exception as ex:
            print("      check failed: %s" % ex)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4)
    args = ap.parse_args()

    data = json.loads((ROOT / "eval" / "reports" / "a_live_default.json")
                      .read_text(encoding="utf-8"))
    rows = [r for r in data["rows"] if r.get("route") == "LIVE"]
    rows.sort(key=lambda r: -(r.get("missing_from_pool") or 0))
    rows = rows[:args.n]

    print("=" * 78)
    print("ITEM A — WHY BARE-QUERY HITS ARE ABSENT FROM THE ASSEMBLED POOL")
    print("=" * 78)
    print("  questions diagnosed: %d (the worst by missing count)" % len(rows))
    print()

    tally = Counter()
    detail = []
    conn = rag.get_conn()
    cur = conn.cursor()
    for r in rows:
        q = r["question"]
        term = E.generate_search_terms(q, mode="review")
        lp = esearch(term, retmax=40)
        # Rebuild the pool for this question to identify what is actually in it.
        import app
        ev = app.build_evidence_base_with_progress("diag", q)
        pool = {str(p.get("pmid"))
                for p in (ev.get("_summary", {}) or {}).get("all_scored", [])}
        missing = [p for p in lp if p not in pool]
        if not missing:
            continue

        in_domain = satisfies(missing, E.ENDO_DOMAIN_FILTER)
        human = satisfies(missing, "NOT (animals[mh] NOT humans[mh])",
                          joiner="BARE")
        not_retracted = satisfies(
            missing, 'NOT "Retracted Publication"[pt] '
                     'NOT "Retraction of Publication"[pt]', joiner="BARE")
        cur.execute("SELECT pmid FROM endo_papers_rag WHERE pmid = ANY(%s)",
                    (missing,))
        in_library = {x[0] for x in cur.fetchall()}

        print("  %-30s %d missing of %d" % (r["id"][:30], len(missing), len(lp)))
        for p in missing:
            if p not in in_domain:
                why = "off-domain (fails ENDO_DOMAIN_FILTER)"
            elif p not in not_retracted:
                why = "retracted"
            elif p not in human:
                why = "animal-only (species guard)"
            elif p in in_library:
                why = "IN THE LIBRARY but not in the pool — a real loss"
            else:
                why = "no lane's publication-type filter matched it"
            tally[why] += 1
            detail.append({"question": r["id"], "pmid": p, "why": why})
        for why, n in Counter(d["why"] for d in detail
                              if d["question"] == r["id"]).most_common():
            print("      %-52s %3d" % (why, n))
        print()

    cur.close()
    conn.close()

    print("  " + "-" * 70)
    print("  ALL DIAGNOSED, BY REASON")
    total = sum(tally.values())
    for why, n in tally.most_common():
        print("    %-54s %3d  (%2.0f%%)" % (why, n, 100.0 * n / max(total, 1)))
    real = tally.get("IN THE LIBRARY but not in the pool — a real loss", 0)
    print()
    print("  legitimate filters : %d" % (total - real))
    print("  REAL LOSSES        : %d" % real)

    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    json.dump({"tally": dict(tally), "detail": detail},
              open("eval/reports/a_missing_live_diagnosis.json", "w",
                   encoding="utf-8"), indent=1)
    print("\n  wrote eval/reports/a_missing_live_diagnosis.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
