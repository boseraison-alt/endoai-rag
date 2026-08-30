"""
Retrieval-only probe: run the real evidence-base pipeline for a question and
report the tier shape, without paying for curriculum generation.

The expensive part of a run is the LLM synthesis, not the retrieval. This lets
the eval baseline's retrieval numbers be re-measured cheaply after a scoring or
tier change.

    python scripts/probe_retrieval.py "Use of lasers in root canal disinfection"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import build_evidence_base_with_progress, jobs
from endo_ai import TIER_ORDER

question = " ".join(sys.argv[1:]) or "Use of lasers in root canal disinfection"

job_id = "probe"
jobs[job_id] = {"status": "running", "steps": [], "progress": 0}

print(f"QUESTION: {question}\n" + "=" * 70)
evidence = build_evidence_base_with_progress(job_id, question) or {}

summary = evidence.get("_summary", {})

print("\n" + "=" * 70 + "\nTIER SHAPE\n" + "=" * 70)
total = 0
for tier in TIER_ORDER:
    block = evidence.get(tier)
    if not block:
        continue
    papers = block.get("scored") or []
    print(f"   {tier:<10} {len(papers):>4}   (source: {block.get('source', '?')})")
    total += len(papers)
print(f"   {'TOTAL':<10} {total:>4}")
print(f"   _summary.total_scored: {summary.get('total_scored')}   "
      f"avg score {summary.get('avg_score')}")

coch = (evidence.get("cochrane") or {}).get("scored") or []
print("\nCochrane-tier papers — every journal below must be the Cochrane Database:")
if not coch:
    print("   (none — correct for a topic Cochrane has not reviewed)")
for p in coch:
    jour = (p.get("journal") or "")
    ok = "OK " if "cochrane database" in jour.lower() else "BAD"
    print(f"   {ok} {p.get('pmid')}  {jour[:38]:<38} {(p.get('title') or '')[:40]}")
