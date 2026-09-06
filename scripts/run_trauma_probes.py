"""Item D — the three probes, in two states.

STATE 1 (before the ingest) is already recorded in
`eval/reports/a49_seed_extension_ingest_part2.md`: no IADT guideline reached
any pool, and the guideline tier held a vascular-surgery guideline and a feline
veterinary one instead.

STATE 2 = database after item A's ingest, code BEFORE item B.
STATE 3 = database after A (and E), code after B, C and E.

The two states isolate the two causes. If state 2 already finds the IADT
guidelines, the ingest alone was enough and item B is a precision-only change.
If state 2 still misses them, the lane was the cause.

WHY STATE 3 IS NOT "AFTER B" ALONE, said plainly rather than implied: items C
and E shipped the same night, and both touch what a pool contains. C derives a
paper's tier from its publication types instead of the lane it was retrieved
under, which moves rows between tiers; E collapses co-published copies of one
guideline. State 3 is the shipped build, and the report says so.

COST. Probes 1 and 2 are RETRIEVAL ONLY -- everything item D asks of them
(pool by manifest id, which documents are present, whether a superseded record
leaked) is answerable from the evidence base without paying for synthesis.
Probe 3 asks whether the ANSWER labels two specialties' positions or blends
them, which is a question about prose, so probe 3 runs synthesis in both
states. Six retrievals, two syntheses, instead of six full Case runs.

    python scripts/run_trauma_probes.py --state 2
    python scripts/run_trauma_probes.py --state 3
    python scripts/run_trauma_probes.py --compare
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

PROBES = [
    ("probe1-avulsion",
     "Avulsed maxillary central incisor with a closed apex, replanted after "
     "40 minutes of extra-oral dry time. How should it be managed and what is "
     "the prognosis?"),
    ("probe2-crown-fracture",
     "Complicated crown fracture with pulp exposure in a mature premolar, "
     "6 hours old. What is the management?"),
    ("probe3-retreat-implant",
     "Mature molar with a failed root canal retreatment. The patient asks for "
     "extraction and an implant. How should this be decided?"),
]

# What each probe is watched for.
WATCH = {
    "probe1-avulsion": ["IADT-AVULSION-2020", "AAE-TRAUMA-2026",
                        "ESE-TRAUMA-2021"],
    "probe2-crown-fracture": ["IADT-FRACTURES-LUXATIONS-2020",
                              "AAE-TRAUMA-2026", "ESE-TRAUMA-2021"],
    "probe3-retreat-implant": ["ACP-ASYMPTOMATIC-EXTRACTION-2016",
                               "ESE-S3-2023", "AAE-TREATMENTSTANDARDS-2018"],
}
SUPERSEDED_IADT = ["IADT-AVULSION-2012", "IADT-AVULSION-2007",
                   "IADT-PRIMARY-2012", "IADT-PRIMARY-2007",
                   "IADT-FRACTURES-LUXATIONS-2012"]
# The off-domain documents from item B's watchlist.
OFFDOMAIN = {"41319038": "FelineVMA feline dental",
             "29268916": "Society for Vascular Surgery",
             "29729847": "SIOPE brain-tumour radiotherapy",
             "17446442": "AHA infective endocarditis 2007"}


def out_path(state):
    return "eval/reports/night8_item_d_state%s.json" % state


def run(state):
    from app import build_evidence_base_with_progress, jobs
    import endo_ai as E

    results = {}
    for pid, question in PROBES:
        print("=" * 78)
        print("STATE %s — %s" % (state, pid))
        print("=" * 78)
        job = "probe_%s_%s" % (state, pid)
        jobs[job] = {"status": "running", "steps": [], "progress": 0}
        ev = build_evidence_base_with_progress(job, question) or {}

        block = ev.get("guideline") or {}
        pool = block.get("scored") or []
        rec = {"question": question, "pool_size": len(pool), "rows": []}
        for p in pool:
            rec["rows"].append({
                "pmid": str(p.get("pmid") or ""),
                "guideline_id": p.get("guideline_id") or "",
                "status": p.get("guideline_status") or "",
                "org": p.get("guideline_org") or "",
                "title": (p.get("title") or "")[:90],
                "journal": (p.get("journal") or "")[:60],
            })
        gids = {r["guideline_id"] for r in rec["rows"] if r["guideline_id"]}
        rec["manifest_ids"] = sorted(gids)
        rec["watched_present"] = {w: (w in gids) for w in WATCH[pid]}
        rec["superseded_leaked"] = sorted(gids & set(SUPERSEDED_IADT))
        rec["offdomain_present"] = sorted(
            {r["pmid"] for r in rec["rows"]} & set(OFFDOMAIN))
        rec["tier_sizes"] = {
            k: len((v or {}).get("scored") or [])
            for k, v in ev.items()
            if isinstance(v, dict) and v.get("scored")}

        print("  guideline pool: %d" % rec["pool_size"])
        for r in rec["rows"]:
            print("    %-10s %-32s %-10s %s"
                  % (r["pmid"][:10], r["guideline_id"][:32] or "-",
                     r["status"] or "-", r["title"][:44]))
        print("  watched: %s" % rec["watched_present"])
        print("  superseded leaked: %s" % (rec["superseded_leaked"] or "none"))
        print("  off-domain: %s" % ([OFFDOMAIN[p] for p in rec["offdomain_present"]]
                                    or "none"))

        # Probe 3 only: the question is about the ANSWER's wording.
        if pid == "probe3-retreat-implant":
            print("\n  synthesising (probe 3 only — the question is about "
                  "whether the prose labels two specialties or blends them)")
            try:
                ans = E.ask_clinical_question(question, ev)
                text = ans if isinstance(ans, str) else (
                    ans.get("answer") if isinstance(ans, dict) else str(ans))
                rec["answer"] = text or ""
                Path("eval/reports").mkdir(parents=True, exist_ok=True)
                Path("eval/reports/night8_probe3_state%s.md" % state).write_text(
                    rec["answer"], encoding="utf-8")
                print("  answer: %d chars" % len(rec["answer"]))
            except Exception as ex:
                rec["answer"] = ""
                rec["answer_error"] = str(ex)
                print("  synthesis failed: %s" % ex)

        results[pid] = rec

    Path(out_path(state)).parent.mkdir(parents=True, exist_ok=True)
    json.dump(results, open(out_path(state), "w"), indent=1)
    print("\n  wrote %s" % out_path(state))


def compare():
    s2 = json.load(open(out_path(2)))
    s3 = json.load(open(out_path(3)))
    print("=" * 78)
    print("ITEM D — 3 PROBES x 3 STATES")
    print("=" * 78)
    print("  state 1 is from eval/reports/a49_seed_extension_ingest_part2.md:")
    print("    no IADT guideline reached ANY pool; the guideline tier held a")
    print("    vascular-surgery guideline and a feline veterinary one.")
    print()
    hdr = "  %-24s %-10s %-10s %-10s"
    print(hdr % ("", "state1", "state2", "state3"))
    for pid, _q in PROBES:
        a, b = s2.get(pid, {}), s3.get(pid, {})
        print("  --- %s" % pid)
        print(hdr % ("guideline pool size", "see above",
                     a.get("pool_size"), b.get("pool_size")))
        for w in WATCH[pid]:
            print(hdr % ("  " + w[:22], "no",
                         "YES" if a.get("watched_present", {}).get(w) else "no",
                         "YES" if b.get("watched_present", {}).get(w) else "no"))
        print(hdr % ("  superseded leaked", "n/a",
                     len(a.get("superseded_leaked") or []),
                     len(b.get("superseded_leaked") or [])))
        print(hdr % ("  off-domain rows", ">=1",
                     len(a.get("offdomain_present") or []),
                     len(b.get("offdomain_present") or [])))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="")  # any label; 2 and 3 are the 2026-09-06 states
    ap.add_argument("--compare", action="store_true")
    args = ap.parse_args()
    if args.compare:
        return compare()
    if not args.state:
        raise SystemExit("--state <label>, or --compare")
    run(args.state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
