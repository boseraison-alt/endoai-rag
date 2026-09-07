"""A54 — what is actually in the pool for this question, and how much of it is
about root-end filling at all.

PRECISION, not recall. The comparison's complaint was not only that the
head-to-head trials were missing; it was that the pool was full of MTA papers
about pulp capping, revascularisation and apexification — MTA the material,
not MTA as a root-end filling.

OFF-TOPIC is measured on the paper's own words: an on-topic paper mentions
root-end, retrograde, apicoectomy, apicectomy, apical surgery, periradicular
surgery or endodontic microsurgery somewhere in its title or abstract. That is
the question's subject; a paper that never names it is not about it.

Terms are FROZEN (`eval/logs/a54_terms.json`), so the before and after arms
measure the change and not the generator's variance (rule 38).

    python scripts/a54_pool_precision.py --arm before
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E  # noqa: E402

QUESTION = "MTA versus bioceramic as retrograde filling after apicoectomy"
FIXTURES = {
    "F1": "31078325", "F2": "27986096", "F3": "34499889",
    "F4": "38430316", "F5": "42634020",
    "F6": "42004800", "F7": "41555359", "F8": "38849637",
}

ON_TOPIC = re.compile(
    r"(root[- ]end|retrograde|apico?ectom|apicectom|apical surgery|"
    r"periradicular surgery|periapical surgery|endodontic microsurgery|"
    r"apical microsurgery|root end resection|retrofill)", re.I)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="before")
    args = ap.parse_args()

    from app import build_evidence_base_with_progress, jobs
    job = "a54-%s" % args.arm
    jobs[job] = {"status": "running", "steps": [], "progress": 0}
    ev = build_evidence_base_with_progress(job, QUESTION) or {}

    pool = []
    for tier, block in ev.items():
        if not isinstance(block, dict):
            continue
        for p in (block.get("scored") or []):
            pool.append((tier, p))

    pmids = [str(p.get("pmid") or "") for _t, p in pool]
    print("=" * 78)
    print("A54 — POOL AND PRECISION,  ARM = %s" % args.arm.upper())
    print("=" * 78)
    print("  question: %s" % QUESTION)
    print("  papers in the pool: %d" % len(pool))
    by_tier = {}
    for t, _p in pool:
        by_tier[t] = by_tier.get(t, 0) + 1
    print("  by tier: %s" % dict(sorted(by_tier.items())))
    print()

    # ── the fixtures ──
    print("  FIXTURES IN THE POOL")
    present = {}
    for k, pmid in FIXTURES.items():
        hit = pmid in pmids
        present[k] = hit
        print("    %-3s %-10s %s" % (k, pmid, "PRESENT" if hit else "absent"))
    print("    -> %d of %d present" % (sum(present.values()), len(FIXTURES)))
    print()

    # ── precision ──
    texts = E._fetch_pubtypes_and_abstracts(
        [p for p in pmids if p.isdigit()])
    on, off, unknown = [], [], []
    for tier, p in pool:
        pmid = str(p.get("pmid") or "")
        rec = texts.get(pmid) or {}
        blob = " ".join([rec.get("title", "") or p.get("title", "") or "",
                         rec.get("abstract", "") or ""])
        if not blob.strip():
            unknown.append((tier, pmid, p.get("title", "")))
        elif ON_TOPIC.search(blob):
            on.append((tier, pmid))
        else:
            off.append((tier, pmid, (rec.get("title", "") or "")[:76]))

    n = len(on) + len(off)
    print("  PRECISION — does the paper name the question's subject at all?")
    print("    on topic            %3d" % len(on))
    print("    OFF TOPIC           %3d" % len(off))
    print("    no text to judge    %3d" % len(unknown))
    if n:
        print("    off-topic share     %.0f%% of the %d judgeable"
              % (100.0 * len(off) / n, n))
    print()
    print("  OFF-TOPIC PAPERS (first 25)")
    for tier, pmid, title in off[:25]:
        print("    %-13s %-10s %s" % (tier, pmid, title))

    out = {"arm": args.arm, "n_pool": len(pool), "by_tier": by_tier,
           "fixtures_present": present, "on_topic": len(on),
           "off_topic": len(off), "unknown": len(unknown),
           "off_topic_pmids": [p for _t, p, _x in off],
           "pool_pmids": pmids}
    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    json.dump(out, open("eval/reports/a54_pool_%s.json" % args.arm, "w"),
              indent=1)
    print("\n  wrote eval/reports/a54_pool_%s.json" % args.arm)
    return 0


if __name__ == "__main__":
    sys.exit(main())
