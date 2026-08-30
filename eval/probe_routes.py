"""
Measure which route each draft eval question NATURALLY takes, before pinning it.

WORKLIST §7 marks the library/live split as a clinical judgement call. This
does not replace that judgement — it supplies the measurement it should be
made against, so "well-covered" means the library demonstrably covers it today
rather than that someone expected it to.

Cheap: one Haiku call for search terms per question, one embedding, one vector
query. No PubMed, no synthesis.

    python eval/probe_routes.py            # all drafts
    python eval/probe_routes.py --json     # machine-readable
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# The §7 drafts. `expected` is the worklist's guess, kept so the probe can
# report where measurement and expectation disagree.
DRAFTS = [
    ("single-vs-multiple-visit", "Single-visit versus multiple-visit root canal treatment for necrotic teeth with apical periodontitis", "library"),
    ("mta-vs-biodentine-pulpotomy", "MTA versus Biodentine for full pulpotomy in mature permanent teeth with irreversible pulpitis", "library"),
    ("naocl-concentration", "Sodium hypochlorite concentration low versus high and outcome of primary root canal treatment", "library"),
    ("cbct-vs-periapical", "CBCT versus periapical radiography for detecting apical periodontitis", "library"),
    ("bioceramic-vs-resin-sealer", "Calcium silicate bioceramic sealers versus epoxy resin sealers outcomes", "library"),
    ("retreatment-vs-microsurgery", "Nonsurgical retreatment versus apical microsurgery for persistent apical periodontitis", "library"),
    ("direct-pulp-capping", "Vital pulp therapy direct pulp capping in cariously exposed mature permanent teeth", "library"),
    ("preemptive-nsaid", "Postoperative pain after root canal treatment preemptive NSAID versus placebo", "library"),
    ("regenerative-immature", "Regenerative endodontic procedures in immature necrotic teeth success and survival", "library"),
    ("cracked-tooth-prognosis", "Cracked tooth prognosis after root canal treatment by crack extent", "library"),
    ("laser-disinfection", "Use of lasers in root canal disinfection", "live"),
    ("apdt-primary-molars", "Antimicrobial photodynamic therapy as an adjunct in primary molars with necrotic pulps", "live"),
    ("bisphosphonates", "Endodontic management in patients on bisphosphonates or antiresorptives", "live"),
    ("pregnancy", "Root canal treatment in pregnancy timing and local anesthetic choice", "live"),
    ("pips-vs-ultrasonic", "Laser-activated irrigation PIPS SWEEPS versus ultrasonic activation periapical healing outcomes", "live"),
    ("intentional-replantation", "Intentional replantation for teeth unsuitable for surgery", "live"),
    ("sdf-pulp-outcomes", "Silver diamine fluoride and pulp outcomes in deep carious lesions in adult teeth", "live"),
    ("sonic-vs-ultrasonic", "Sonic versus ultrasonic irrigant activation bacterial reduction in vivo", "live"),
    ("dens-invaginatus", "Dens invaginatus type III management", "live"),
    ("diabetes-outcomes", "Endodontic outcomes in patients with diabetes healing of apical periodontitis", "live"),
]

# Mirrors build_evidence_base_with_progress's gate.
MIN_RAG_RESULTS = 20
RAG_SIMILARITY_FLOOR = 0.55
MIN_RAG_RELEVANT = 12
RAG_MAX_TOPIC_AGE_YEARS = 3


def probe(question):
    from datetime import datetime
    from endo_ai import generate_search_terms
    from rag import search as rag_search

    topic = generate_search_terms(question)
    hits = rag_search(topic, level_key=None, limit=100)
    relevant = [r for r in hits if float(r.get("similarity") or 0) >= RAG_SIMILARITY_FLOOR]
    high_tier = sum(1 for r in relevant
                    if (r.get("level_key") or "") in ("cochrane", "level1"))
    newest = max((int(r["year"]) for r in relevant
                  if str(r.get("year", "")).isdigit()), default=0)
    age = datetime.now().year - newest if newest else 99
    covers = (len(hits) >= MIN_RAG_RESULTS and len(relevant) >= MIN_RAG_RELEVANT
              and high_tier > 0 and age <= RAG_MAX_TOPIC_AGE_YEARS)
    return {"hits": len(hits), "relevant": len(relevant), "high_tier": high_tier,
            "newest_year": newest, "age": age, "route": "library" if covers else "live"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    out, disagreements = [], []
    for slug, question, expected in DRAFTS:
        try:
            m = probe(question)
        except Exception as e:
            print(f"  ERROR {slug}: {e}")
            continue
        m.update(id=slug, question=question, expected=expected)
        out.append(m)
        flag = "" if m["route"] == expected else "  <-- DISAGREES WITH DRAFT"
        if flag:
            disagreements.append(m)
        if not args.json:
            print(f"{slug:<28} measured={m['route']:<8} draft={expected:<8} "
                  f"relevant={m['relevant']:>3}/{m['hits']:<3} high_tier={m['high_tier']:>3} "
                  f"newest={m['newest_year']}{flag}")

    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"\n{len(disagreements)}/{len(out)} disagree with the draft expectation")
        for d in disagreements:
            print(f"   {d['id']}: draft says {d['expected']}, library actually "
                  f"{'covers' if d['route'] == 'library' else 'does not cover'} it")


if __name__ == "__main__":
    main()
