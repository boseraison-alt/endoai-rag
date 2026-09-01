"""
Classify every citation-less claim in a case answer (`case-v3` Item A).

THE QUESTION. A clinician copied a case conversation out of the browser and
found claims with no citation on them. There are two very different reasons a
claim can look uncited, and they need opposite fixes:

  (1) STRIPPED IN COPY — the marker is in the model's text and rendered on
      screen, but the copied text lost it. `.claim-cite` carries
      `user-select: none`, so a native browser selection SKIPS the citation
      entirely. Measured on the live page: 34 citations visible, 34 citations
      in the copy = 0. Every one. The fix is a copy fix, not a prompt fix.

  (2) GENUINELY ABSENT — the model wrote a clinical claim and attached no
      marker. This is the real defect, and it is what `validate_evidence_mapping`
      is supposed to catch through `_detect_unattributed_claims`.

This script measures the split, and then measures the second thing that
matters: of the genuinely-absent claims, how many does the CURRENT detector
catch, and what shape are the ones it misses?

    python scripts/analyze_case_uncited.py
    python scripts/analyze_case_uncited.py --out eval/logs/case_uncited.json
"""

import argparse
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import endo_ai  # noqa: E402

TURNS = [
    ("turn 1 — differential",
     "eval/logs/case_answers/de_conversation_turn1_differential.md"),
    ("turn 2 — prevention",
     "eval/logs/case_answers/de_conversation_turn2_prevention.md"),
]

# Shapes of clinical claim the CURRENT `_CLAIM_PATTERNS` does not match. Each
# is a real sentence from these two turns, and each is a directive a clinician
# could act on chairside.
MISSED_SHAPES = {
    "numeric directive per visit/interval": re.compile(
        r"\b\d+(?:\.\d+)?\s*(?:mm|cm|ml|mg)\s+per\s+(?:visit|appointment|session)\b"
        r"|\bevery\s+\d+(?:\s*[-–]\s*\d+)?\s*(?:week|month|day|year)s?\b"
        r"|\b\d+\s*[-–]\s*\d+\s*(?:week|month|day)s?\s+intervals?\b", re.IGNORECASE),
    "named author without a marker": re.compile(
        r"\b[A-Z][a-zA-Zöäüéèç'’-]{2,}\s+(?:et al\.?|and\s+[A-Z][a-zA-Z'’-]{2,})\b"),
    "appeal to the literature": re.compile(
        r"\b(?:advocated|described|reported|documented|established|recommended|"
        r"supported|shown|demonstrated)\s+in\s+the\s+literature\b"
        r"|\bthe\s+literature\s+(?:advocates|supports|shows|describes|recommends)\b"
        r"|\bstudies\s+(?:have\s+)?(?:shown|demonstrated|reported)\b", re.IGNORECASE),
    "imperative clinical directive": re.compile(
        r"^\s*(?:\d+\.\s*)?(?:\*\*)?(?:Reduce|Apply|Place|Seal|Monitor|Refer|Screen|"
        r"Perform|Prescribe|Adjust|Remove|Restore|Instruct|Review|Repeat|Avoid|"
        r"Recontour|Equilibrat)\w*\b", re.IGNORECASE),
    "single most / critical superlative": re.compile(
        r"\b(?:the\s+single\s+most\s+\w+|is\s+critical|is\s+essential|is\s+mandatory|"
        r"most\s+impactful|key\s+determinant)\b", re.IGNORECASE),
}


def load(path):
    """The answer body, without this file's own header and blockquotes.

    The blockquote strip matters: the citation-support block quotes flagged
    claims verbatim WITH their markers, so leaving it in would count the
    checker's own output as cited claims.
    """
    raw = io.open(ROOT / path, encoding="utf-8").read()
    body = raw.split("\n---\n", 1)[-1]
    return "\n".join(l for l in body.split("\n")
                     if not l.lstrip().startswith(">"))


def looks_clinical(text):
    return [i for i, pat in enumerate(endo_ai._CLAIM_PATTERNS)
            if pat.search(text)]


def missed_shapes(text):
    return [name for name, pat in MISSED_SHAPES.items() if pat.search(text)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="eval/logs/case_uncited.json")
    args = ap.parse_args()

    report = {"turns": []}
    for label, path in TURNS:
        answer = load(path)
        print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")

        # The CHECKER's units (shape-aware) for the cited side, and the
        # VALIDATOR's units (prose-only) for the uncited side — because those
        # are the two splitters actually in use, and using one for both would
        # measure something the product does not do.
        cited_pairs = endo_ai._extract_claim_citation_pairs(answer)
        n_markers = len(endo_ai._PMID_RE.findall(answer))
        detected = endo_ai._detect_unattributed_claims(answer)

        with_marker, without_marker = [], []
        for title, body in endo_ai._split_sections(answer):
            if endo_ai._is_exempt_section(title):
                continue
            for unit in endo_ai._split_claim_units(body):
                u = unit.strip()
                if len(u) < 20:
                    continue
                (with_marker if endo_ai._PMID_RE.search(u)
                 else without_marker).append(u)

        # Of the unmarked units, which look like clinical claims at all?
        current_catch, newly_caught, neither = [], [], []
        det_texts = {d["sentence"][:60] for d in detected}
        for u in without_marker:
            hits = looks_clinical(u)
            shapes = missed_shapes(u)
            if hits:
                current_catch.append((u, hits, shapes))
            elif shapes:
                newly_caught.append((u, shapes))
            else:
                neither.append(u)

        print(f"  markers in the text                     {n_markers}")
        print(f"  claim-citation pairs the checker sees   {len(cited_pairs)}")
        print(f"  units WITH a marker  (stripped in copy) {len(with_marker)}")
        print(f"  units WITHOUT a marker                  {len(without_marker)}")
        print(f"    ... the detector already flags         {len(current_catch)}")
        print(f"    ... it MISSES, but a new pattern sees  {len(newly_caught)}")
        print(f"    ... neither (background/transition)    {len(neither)}")
        print(f"  validator's own n_unattributed          {len(detected)}")

        if newly_caught:
            print(f"\n  MISSED BY THE CURRENT DETECTOR:")
            for u, shapes in newly_caught:
                print(f"    [{', '.join(shapes)}]")
                print(f"      {u[:190]}")

        report["turns"].append({
            "label": label, "path": path,
            "markers_in_text": n_markers,
            "checker_pairs": len(cited_pairs),
            "units_with_marker": len(with_marker),
            "units_without_marker": len(without_marker),
            "detector_catches": len(current_catch),
            "detector_misses_but_new_pattern_catches": len(newly_caught),
            "neither": len(neither),
            "validator_n_unattributed": len(detected),
            "missed": [{"shapes": s, "text": u[:400]} for u, s in newly_caught],
            "detected_by_validator": [d["sentence"][:300] for d in detected],
        })

    tot_m = sum(t["units_with_marker"] for t in report["turns"])
    tot_u = sum(t["units_without_marker"] for t in report["turns"])
    tot_new = sum(t["detector_misses_but_new_pattern_catches"]
                  for t in report["turns"])
    print(f"\n{'=' * 70}")
    print(f"ITEM A SPLIT, both turns")
    print(f"  claims carrying a marker (LOST IN COPY, not absent)  {tot_m}")
    print(f"  claims with no marker at all                         {tot_u}")
    print(f"  of those, missed by the current detector             {tot_new}")

    if args.out:
        p = ROOT / args.out
        p.parent.mkdir(parents=True, exist_ok=True)
        io.open(p, "w", encoding="utf-8").write(
            json.dumps(report, indent=1, ensure_ascii=False))
        print(f"\nwrote {p}")


if __name__ == "__main__":
    main()
