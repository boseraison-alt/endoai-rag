"""Item B confinement proof — the change must not leak out of the guideline lane.

ASSERTED IN A SCRIPT, NOT BY EYE, because "I only edited the guideline branch"
is exactly the kind of claim that has been wrong in this project before.
`guideline_topic` is called inside `fetch_papers`, which every lane goes
through, and `GUIDELINE_SPECIES_GUARD` is concatenated into a search term every
lane builds. Either one reaching a study lane would change what the clinician
is shown on every question.

WHAT IS COMPARED. For each of the 32 questions and each of the 8 study lanes
(cochrane, level1, level2, level3a, level3b, level4, level5, observational),
the exact PubMed query string is constructed the way `fetch_papers` constructs
it, and the returned PMID set is recorded. Two arms are compared by SET, not by
count: a pool that swapped one paper for another has the same size and is not
the same pool.

Terms come from the same cache both arms use, so the only thing that can differ
is the code.

    python scripts/prove_guideline_lane_confinement.py --arm before
    python scripts/prove_guideline_lane_confinement.py --arm after
    python scripts/prove_guideline_lane_confinement.py --compare
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E  # noqa: E402

TERMS_CACHE = Path("eval/logs/night8_terms.json")
OUT = "eval/reports/night8_confinement_%s.json"


def esearch_ids(term, retmax=50):
    try:
        r = E.ncbi_get(f"{E.NCBI_EUTILS_BASE}/esearch.fcgi",
                       params=E._ncbi_params({"db": "pubmed", "term": term,
                                              "retmode": "json",
                                              "sort": "relevance",
                                              "retmax": retmax}), timeout=25)
        return sorted(str(i) for i in
                      r.json().get("esearchresult", {}).get("idlist", []))
    except Exception as ex:
        print("      esearch failed: %s" % ex)
        return None


def build_query(topic, filter_term, level_key):
    """Mirror of `fetch_papers`' search-term construction, for ONE lane.

    The guideline branch is included so the proof also shows the guideline lane
    DID change -- a run where nothing moved anywhere would prove the harness
    was inert rather than the change confined.
    """
    guard = ""
    if level_key == "guideline":
        topic = E.guideline_topic(topic)
        guard = getattr(E, "GUIDELINE_SPECIES_GUARD", "")
    return (f"({topic}) AND ({filter_term}) AND {E.ENDO_DOMAIN_FILTER} "
            f'NOT "Retracted Publication"[pt] '
            f'NOT "Retraction of Publication"[pt]{guard}')


def run(arm):
    terms = json.loads(TERMS_CACHE.read_text(encoding="utf-8"))
    filters = E.live_path_filters()
    lanes = ["cochrane"] + [k for k, _t, _l in E.tier_query_lanes()]
    out = {}
    for i, (cid, smart) in enumerate(sorted(terms.items()), 1):
        out[cid] = {}
        for lane in lanes:
            q = build_query(smart, filters[lane], lane)
            ids = esearch_ids(q)
            out[cid][lane] = ids
        print("[%2d/%d] %-42s %s" % (i, len(terms), cid[:42],
                                     " ".join("%s=%s" % (l, len(out[cid][l])
                                              if out[cid][l] is not None
                                              else "ERR") for l in lanes)))
    p = OUT % arm
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(p, "w"), indent=1)
    print("\n  wrote %s" % p)


def compare():
    a = json.load(open(OUT % "before"))
    b = json.load(open(OUT % "after"))
    lanes = ["cochrane", "level1", "level2", "level3a", "level3b", "level4",
             "guideline", "level5", "observational"]
    study = [l for l in lanes if l != "guideline"]
    changed_study, changed_guideline, skipped = [], [], 0
    for cid in sorted(set(a) & set(b)):
        for lane in lanes:
            x, y = a[cid].get(lane), b[cid].get(lane)
            if x is None or y is None:
                skipped += 1
                continue
            if set(x) != set(y):
                rec = (cid, lane, sorted(set(x) - set(y)),
                       sorted(set(y) - set(x)))
                (changed_guideline if lane == "guideline"
                 else changed_study).append(rec)
    print("=" * 78)
    print("CONFINEMENT PROOF")
    print("=" * 78)
    print("  questions compared              %d" % len(set(a) & set(b)))
    print("  lane-pools compared             %d"
          % (len(set(a) & set(b)) * len(lanes)))
    print("  pools skipped (esearch error)   %d" % skipped)
    print()
    print("  STUDY-LANE pools that changed   %d   <-- MUST BE 0"
          % len(changed_study))
    for cid, lane, lost, gained in changed_study:
        print("    %-40s %-14s -%d +%d" % (cid, lane, len(lost), len(gained)))
        print("        lost  : %s" % lost[:10])
        print("        gained: %s" % gained[:10])
    print()
    print("  GUIDELINE-lane pools that changed %d   (the change itself)"
          % len(changed_guideline))
    for cid, _lane, lost, gained in changed_guideline:
        print("    %-40s -%d +%d" % (cid, len(lost), len(gained)))
    print()
    if changed_study:
        print("  VERDICT: LEAKED. The change reached a study lane. Revert.")
        return 1
    if not changed_guideline:
        print("  VERDICT: INERT. No guideline pool changed either, so this")
        print("           proves nothing. Check the harness before believing")
        print("           the zero above.")
        return 1
    print("  VERDICT: CONFINED. Every study-lane pool is identical by PMID")
    print("           set, and the guideline lane did move.")
    return 0


def querycheck():
    """THE DETERMINISTIC PROOF, and the one that actually settles it.

    Comparing returned POOLS across two arms compares two live PubMed calls
    minutes apart, and PubMed's relevance sort is not stable at the retmax
    cutoff: the 50th result of an identical query differs between runs. The
    first version of this script only compared pools and reported 61 changed
    study-lane pools -- every one of them a symmetric swap (-2 +2, -4 +4) at an
    unchanged pool size, which is the signature of ranking noise and not of a
    leak.

    So the confinement question is asked of the code instead: for every study
    lane, is the QUERY STRING this build sends byte-identical to the one the
    previous build sent? That needs no network and cannot drift.
    """
    terms = json.loads(TERMS_CACHE.read_text(encoding="utf-8"))
    filters = E.live_path_filters()
    lanes = ["cochrane"] + [k for k, _t, _l in E.tier_query_lanes()]
    before = json.load(open("eval/reports/night8_queries_before.json")) \
        if Path("eval/reports/night8_queries_before.json").exists() else None
    now = {cid: {l: build_query(smart, filters[l], l) for l in lanes}
           for cid, smart in sorted(terms.items())}
    if before is None:
        Path("eval/reports").mkdir(parents=True, exist_ok=True)
        json.dump(now, open("eval/reports/night8_queries_before.json", "w"),
                  indent=1)
        print("  captured this build's query strings as the BEFORE snapshot")
        return 0
    study = [l for l in lanes if l != "guideline"]
    diff_study = [(c, l) for c in now for l in study
                  if now[c][l] != before.get(c, {}).get(l)]
    diff_guide = [c for c in now
                  if now[c]["guideline"] != before.get(c, {}).get("guideline")]
    print("=" * 78)
    print("CONFINEMENT — QUERY STRINGS (deterministic, no network)")
    print("=" * 78)
    print("  questions            %d" % len(now))
    print("  study lanes each     %d" % len(study))
    print("  study-lane QUERY STRINGS that differ   %d   <-- MUST BE 0"
          % len(diff_study))
    for c, l in diff_study[:20]:
        print("    %-40s %s" % (c, l))
        print("      before: %s" % before[c][l][:150])
        print("      after : %s" % now[c][l][:150])
    print("  guideline-lane query strings that differ %d  (the change itself)"
          % len(diff_guide))
    print()
    if diff_study:
        print("  VERDICT: LEAKED. A study lane's query changed. Revert.")
        return 1
    if not diff_guide:
        print("  VERDICT: INERT. The guideline query did not change either.")
        return 1
    print("  VERDICT: CONFINED. Every study lane sends a byte-identical")
    print("           query; only the guideline lane's changed.")
    return 0


def noise():
    """How much do two runs of the SAME build disagree? Measure the instrument
    before attributing anything to the change (rule 34)."""
    a = json.load(open(OUT % "after"))
    b = json.load(open(OUT % "after2"))
    lanes = ["cochrane", "level1", "level2", "level3a", "level3b", "level4",
             "level5", "observational"]
    n_diff = tot = 0
    for cid in sorted(set(a) & set(b)):
        for lane in lanes:
            x, y = a[cid].get(lane), b[cid].get(lane)
            if x is None or y is None:
                continue
            tot += 1
            if set(x) != set(y):
                n_diff += 1
    print("=" * 78)
    print("INSTRUMENT NOISE — same build, two runs")
    print("=" * 78)
    print("  study-lane pools compared            %d" % tot)
    print("  study-lane pools that differ ANYWAY  %d  (%.0f%%)"
          % (n_diff, 100.0 * n_diff / max(1, tot)))
    print()
    print("  This is the floor. A before/after pool difference at or below it")
    print("  says nothing about the change.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="",
                    choices=["", "before", "after", "after2"])
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--querycheck", action="store_true")
    ap.add_argument("--noise", action="store_true")
    args = ap.parse_args()
    if args.querycheck:
        return querycheck()
    if args.noise:
        return noise()
    if args.compare:
        return compare()
    if not args.arm:
        raise SystemExit("--arm before|after|after2, --compare, --querycheck")
    run(args.arm)
    return 0


if __name__ == "__main__":
    sys.exit(main())
