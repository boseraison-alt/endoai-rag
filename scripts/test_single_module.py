"""
Single-module test for the Clinical Application section.
Runs write_curriculum_module on ONE topic in isolation — no syllabus, no stitch.

Usage:
    python scripts/test_single_module.py
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from endo_ai import write_curriculum_module, build_evidence_base

TOPIC = "vital pulp therapy: indications, materials, and outcomes"
PARENT_QUESTION = "Vital pulp therapy in permanent teeth — when, how, and with what?"

module = {
    "title": "Vital Pulp Therapy: Indications, Materials, and Clinical Outcomes",
    "search_query": "vital pulp therapy MTA Biodentine RCT outcomes permanent teeth",
}

print(f"[test] Fetching evidence for: {module['search_query']}")
evidence = build_evidence_base(module["search_query"], mode="learn")

summary = evidence.get("_summary", {})
print(f"[test] Evidence fetched — {summary.get('total_scored', '?')} papers")

print(f"\n[test] Writing single module...")
script, cost = write_curriculum_module(module, evidence, PARENT_QUESTION, idx=1, total=1)

print(f"\n[test] Cost: ${cost:.4f}")
print(f"\n{'='*80}")
print("MODULE OUTPUT:")
print('='*80)
print(script)
print('='*80)

# Check for required sections
checks = [
    ("## Clinical Application", "Clinical Application heading"),
    ("### 4a. Procedural Protocol", "4a. Procedural Protocol subsection"),
    ("### 4b. Decision Tree", "4b. Decision Tree subsection"),
    ("### 4c. Materials & Instrumentation", "4c. Materials & Instrumentation subsection"),
    ("### Clinical Protocol Summary", "Clinical Protocol Summary table"),
    ("IF ", "Decision tree IF/THEN format"),
    ("THEN ", "Decision tree THEN keyword"),
    ("BECAUSE ", "Decision tree BECAUSE keyword"),
    ("[[PMID:", "PMID citations"),
]

print("\n[test] Section checks:")
all_pass = True
for needle, label in checks:
    found = needle in script
    status = "PASS" if found else "FAIL"
    if not found:
        all_pass = False
    print(f"  {status}: {label}")

print(f"\n[test] {'ALL CHECKS PASSED' if all_pass else 'SOME CHECKS FAILED'}")
word_count = len(script.split())
print(f"[test] Word count: {word_count} (target <=2000)")
