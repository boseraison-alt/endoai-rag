"""
A5b — the retreatment single-visit-versus-two-visit gap, closed at the source.

WHAT A5b ASSUMED, AND WHAT IS ACTUALLY TRUE. The item names three papers the
retreatment answer missed and attributes the miss to them being absent from the
library. Measured, that is right for one of the three and wrong for two:

  35488883  Karaoglan 2022, Int Endod J   PRESENT in the library
  28148534  Schwendicke 2017, BMJ Open    PRESENT in the library
  34555421  Toia 2022, J Endod            ABSENT  <- this script

So two thirds of the "missing" evidence was already ingested and still did not
reach the answer, by two different mechanisms, neither of them ingestion:

  * Karaoglan was RETRIEVED and cleared the 0.55 similarity floor at 0.648 —
    then was cut by the per-tier cap, which kept 25 of 60 level1 papers BY
    SCORE. It ranked 54th of 60 by score, and 20 of the 25 the cap kept were
    LESS similar to the question than the paper it dropped. Fixed in app.py:
    the cap now selects by relevance and orders by score.

  * Schwendicke appears in NO query's top 100 — a recall miss, not a cap. It is
    a single-visit-versus-multiple-visit paper on primary TREATMENT, and every
    generated term for this question is retreatment-heavy. That belongs with
    A14/A24 (query breadth), not here, and is reported rather than papered over.

This script therefore ingests exactly ONE paper, by PMID, through the normal
write-back path so it lands with the same tier assignment, quality floor and
provenance merge as any other row. A targeted gap gets a targeted fix; a
broadened query here would import the general retreatment corpus, which is the
trap `ingest_dens_evaginatus.py` documents.

    python scripts/ingest_retreatment_visits.py            # dry run
    python scripts/ingest_retreatment_visits.py --apply
"""

import argparse
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import endo_ai  # noqa: E402

# Named in A5b, and confirmed against the PubMed record rather than against the
# item's description of it (standing rule: ingest on the fetched record only).
WANTED = {
    "34555421": "Toia CC et al., J Endod 2022 — 1-visit vs 2-visit retreatment "
                "of teeth with persistent/secondary infection, RCT, 18-month "
                "follow-up",
}

# The two A5b names that turned out to be present. Re-checked every run: if one
# of these ever goes missing the report says so rather than the script silently
# ingesting one paper and calling the gap closed.
EXPECTED_PRESENT = {
    "35488883": "Karaoglan 2022, Int Endod J",
    "28148534": "Schwendicke & Gostemeyer 2017, BMJ Open",
}


def _rows(pmids):
    from rag import get_conn
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT pmid, year, level_key, score, journal, left(title, 70) "
            "FROM endo_papers_rag WHERE pmid = ANY(%s)", (list(pmids),))
        return {r[0]: r for r in cur.fetchall()}
    finally:
        cur.close()
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write into the library. Without it nothing is "
                         "written and the report is a dry run.")
    ap.add_argument("--out", default="eval/logs/a5b_retreatment_ingest.json")
    args = ap.parse_args()

    # This script does its own writing so the PMID filter sits between the
    # fetch and the write. `fetch_papers` broadens a query that returns
    # nothing, and a broadened retreatment query is the whole endodontic
    # corpus.
    endo_ai.LIBRARY_WRITE_BACK = False
    print("APPLY\n" if args.apply else "DRY RUN\n")

    before = _rows(list(WANTED) + list(EXPECTED_PRESENT))

    print("A5b's three named papers, before:")
    for pmid, label in list(EXPECTED_PRESENT.items()) + list(WANTED.items()):
        r = before.get(pmid)
        print("  %s  %-46s %s" % (pmid, label[:46],
                                  "PRESENT (%s, score %s)" % (r[2], r[3])
                                  if r else "ABSENT"))
    missing_expected = [p for p in EXPECTED_PRESENT if p not in before]
    if missing_expected:
        print("\n  !! %s was expected to be present and is not — A5b's "
              "mechanism has changed since it was measured." % missing_expected)

    # Fetch by PMID through the normal tier path so tier, COI, registry and
    # correction status are computed exactly as they would be on a live answer.
    todo = [p for p in WANTED if p not in before]
    if not todo:
        print("\nNothing to ingest — every named paper is already in the "
              "library. The gap is retrieval, not ingestion.")
        return

    found = {}
    for pmid in todo:
        term = "%s[uid]" % pmid
        for level_key, tier_filter in (
                ("level1", " OR ".join(endo_ai.LEVEL_1_TERMS)),
                ("level2", " OR ".join(endo_ai.LEVEL_2_TERMS)),
        ):
            try:
                _text, _ids, scored = endo_ai.fetch_papers(
                    term, tier_filter, "A5b targeted [%s]" % level_key,
                    level_key, mode="review", question=WANTED[pmid])
            except Exception as e:
                print("    XX %s %s: %s" % (pmid, level_key, e))
                continue
            for p in scored:
                # A broadened query cannot smuggle anything in: only the PMID
                # that was asked for is kept.
                if str(p.get("pmid")) == pmid:
                    found[pmid] = p
            if pmid in found:
                break

    print("\nfetched:")
    for pmid in todo:
        p = found.get(pmid)
        print("  %s  %s" % (pmid, "%s  score %s  %s" % (
            p.get("level_key"), p.get("score"), (p.get("title") or "")[:60])
            if p else "NOT RETURNED BY PUBMED — nothing written"))

    if args.apply and found:
        from rag import get_cached_abstracts_bulk, learn_from_live_results
        per_pmid = get_cached_abstracts_bulk(sorted(found))
        n = learn_from_live_results(
            list(found.values()), per_pmid,
            query_text="single visit versus two visit endodontic retreatment")
        print("\nwrote %d paper(s) into the library" % n)

    after = _rows(list(WANTED) + list(EXPECTED_PRESENT))
    added = [p for p in after if p not in before]
    print("\ndelta: %d row(s) added" % len(added))
    for pmid in added:
        r = after[pmid]
        print("  + %s  %s  %-8s score %s  %s" % (r[0], r[1], r[2], r[3], r[5]))
    if not args.apply:
        print("\n(dry run — nothing was written; re-run with --apply)")

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    io.open(out, "w", encoding="utf-8").write(json.dumps({
        "wanted": WANTED,
        "expected_present": EXPECTED_PRESENT,
        "before": {k: list(v) for k, v in before.items()},
        "after": {k: list(v) for k, v in after.items()},
        "added": added,
        "applied": bool(args.apply),
    }, indent=2))
    print("\nreport: %s" % args.out)


if __name__ == "__main__":
    main()
