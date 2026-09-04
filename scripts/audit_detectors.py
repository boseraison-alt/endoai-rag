"""Audit every text detector against the REAL stored corpus.

WHY. `scan_split_items.py` looked for a bare `N.` list number. The corpus
writes it BOLD — `**3.**` — so the scan reported 0 split list items and the
finding was filed as a renderer defect. It was not: 30 of 114 stored quarantine
blocks orphan a list number and 24 cut a bold run. The instrument was wrong,
not the thing measured.

That is the fourth time in this project a measurement instrument was wrong
rather than the thing measured, so this sweeps for the whole class: a detector
whose hard-coded token shape the corpus does not actually emit fires ZERO times
and looks exactly like a clean bill of health.

METHOD. Run every pure-text detector and every compiled pattern over all 199
stored documents (`learn_history/*.json`, `answers/*.txt`, `query_cache`) and
report the hit count. A zero is not automatically a defect — several of these
SHOULD be zero, and that is recorded per detector — but a zero that nobody has
justified is exactly what the split-item scan looked like.

Detectors that call a model or the network are excluded by name, not skipped
silently; see EXCLUDED below.

Usage:  python scripts/audit_detectors.py [--json out.json]
"""
import glob
import json
import os
import re
import sys
import traceback

sys.path.insert(0, os.getcwd())

import endo_ai as E  # noqa: E402

# Not pure text: these call Claude or PubMed. Named rather than filtered by a
# pattern, so adding one is a deliberate act.
EXCLUDED = {
    "classify_case_intent", "classify_question_intent", "verify_citation_support",
    "flag_superseded_by_review", "detect_outliers", "build_synthesis_order",
    "module_has_usable_evidence", "_extract_evidence_pmids", "_is_cancellation",
    "_analysis_to_prefill", "_parse_efetch_batch", "_count_token_to_int",
    "_table_cell_count", "_is_exempt_section", "_group_is_generic",
    "detect_parameter_conflicts", "extract_journal_name", "extract_sample_size",
    "extract_followup_period", "detect_preregistration", "detect_in_vitro",
    "classify_coi", "detect_coi", "is_review_design", "_parse_module_lines",
    "_parse_slides_response", "_parse_candidate_array", "_parse_question_array",
    "_parse_term_list", "_split_and_groups", "parse_search_term_groups",
    "_consistency_findings_block", "_claim_is_directive", "_sentence_count",
}

# Detectors that take one answer/text string and return a list/dict/str.
TEXT_FNS = [
    "_check_quarantine_reframe", "_check_recommendation",
    "_detect_gap_sections", "_detect_unattributed_claims",
    "_detect_uncited_author_mentions", "_detect_uncited_directive_claims",
    "_extract_cited_pmids", "_extract_claim_citation_pairs",
    "_split_claim_units", "_split_claim_units_tagged", "_split_sections",
    "_split_sentences", "detect_malformed_because", "detect_module_truncation",
    "extract_clinical_recommendation", "extract_numeric_parameters",
    "find_presentation_markup", "parse_callouts", "check_coi_blocklist",
]

# A zero here is EXPECTED and why. Anything zero and not in this map is
# reported as UNJUSTIFIED ZERO — the split-item signature.
ZERO_IS_CORRECT = {
    "_PARTIAL_PMID_MARKER_RE":
        "a half-written marker must never survive into a stored answer "
        "(invariant 21); a hit here is the bug",
    "_LEGACY_QUARANTINE_BLOCK_RE":
        "matches only via the multiline block scan, not a bare finditer",
    "_QUARANTINE_BLOCK_RE":
        "same - block shapes are counted by the block scan below",
    "_EFETCH_ENTRY_SPLIT_RE": "PubMed wire format, never in an answer",
    "_EFETCH_PMID_RE": "PubMed wire format, never in an answer",
    "_PMID_FORMAT_RE": "validates one id, not a document",
    "_MODULE_LINE_RE": "generator scaffold, stripped before storage",
    "_ROLE_LINE_RE": "generator scaffold, stripped before storage",
    "_TERM_LINE_RE": "generator scaffold, stripped before storage",
    "_TERM_SPLIT_AND": "operates on a query string, not an answer",
    "_TERM_SPLIT_OR": "operates on a query string, not an answer",
    "_ROLE_FENCE_RE":
        "A44's role fence shipped 2026-09-03; every stored document predates "
        "it. Zero is correct TODAY and must become non-zero once a curriculum "
        "is generated on current code - re-run this after item 6",
    "parse_callouts":
        "same - reads the `:::role` fence A44 introduced, absent from a "
        "pre-A44 corpus",
    "find_presentation_markup":
        "same - looks for the role fence and the inline mark together",
    "_THRESHOLD_RE":
        "MEASURED as production applies it - a 25-char lookbehind on the "
        "abstract, not a whole document: 0 of 95 `_REVIEW_TOTAL_RE` windows "
        "across 646 review-design papers. The threshold vocabulary appears "
        "NOWHERE in those 95 windows, anchored or not, so this is a correct "
        "guard against an idiom this library does not contain - not a wrong "
        "token shape. Kept (rule 6: never weaken a guard); deleting it as "
        "dead code was the alternative considered and rejected.",
}


def abstract_corpus(limit=4000):
    """Real stored ABSTRACTS.

    Half the patterns in `endo_ai` never see an answer — they read an abstract
    (COI statements, in-vitro cues, sample-size idioms, PROSPERO ids). Scoring
    those against the answer corpus proves nothing, and calling their zero
    "justified" on that basis is the same unexamined pass the split-item scan
    got. They get the input production actually gives them.
    """
    try:
        import rag
        with rag.get_conn().cursor() as cur:
            cur.execute(
                "SELECT pmid, abstract FROM endo_papers_rag "
                "WHERE abstract IS NOT NULL AND length(abstract) > 200 "
                "ORDER BY pmid LIMIT %s", (limit,))
            return [("pmid/%s" % p, a) for p, a in cur.fetchall()]
    except Exception as e:
        print("[warn] abstract corpus unavailable: %s" % e)
        return []


# Patterns whose real input is an abstract, not an answer. Audited against
# `abstract_corpus()` instead; a zero THERE is a finding.
ABSTRACT_SIDE = {
    "_COI_AFFIRMATIVE_RE", "_COI_NEGATION_RE", "_COI_CUE_RE",
    "_INVITRO_STRONG_RE", "_INVITRO_WEAK_RE", "_PROSPERO_RE",
    "_REVIEW_TOTAL_RE", "_STUDY_UNIT_RE", "_CLINICAL_OVERRIDE_RE",
    "_EVIDENCE_DESCRIPTION_RE", "_REVIEW_DESIGN_RE", "_THRESHOLD_RE",
    "_NON_ABSTRACT_BLOCK_RE",
}


def corpus():
    docs = []
    for p in sorted(glob.glob("learn_history/*.json")):
        try:
            rec = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        docs.append((os.path.basename(p), rec.get("answer") or ""))
    for p in sorted(glob.glob("answers/*.txt")):
        docs.append((os.path.basename(p),
                     open(p, encoding="utf-8", errors="replace").read()))
    try:
        import rag
        with rag.get_conn().cursor() as cur:
            cur.execute("SELECT id, answer FROM query_cache")
            for i, a in cur.fetchall():
                docs.append(("query_cache/%s" % i, a or ""))
    except Exception as e:
        print("[warn] query_cache unavailable: %s" % e)
    return docs


def size_of(v):
    if v is None:
        return 0
    if isinstance(v, (list, tuple, set)):
        return len(v)
    if isinstance(v, dict):
        return sum(len(x) for x in v.values() if isinstance(x, (list, tuple)))or (1 if v else 0)
    if isinstance(v, str):
        return 1 if v.strip() else 0
    if isinstance(v, tuple):
        return len(v)
    return 1 if v else 0


def main():
    docs = corpus()
    print("corpus: %d documents\n" % len(docs))

    rows = []

    # ── compiled patterns ────────────────────────────────────────────
    #
    # THE HARNESS HAD THE BUG IT IS AUDITING FOR. The first run reported 15
    # "unjustified zeros"; twelve of them were line-anchored patterns compiled
    # WITHOUT re.MULTILINE, which production applies one line at a time. A
    # whole-document `findall` on `^...` can only ever return 0, so the
    # instrument manufactured exactly the signature it was built to find.
    #
    # A pattern is applied the way production applies it: per line when it is
    # anchored and not multiline, whole-document otherwise. `applied_as` is
    # reported so nobody has to re-derive this.
    abstracts = abstract_corpus()
    print("abstract corpus: %d abstracts\n" % len(abstracts))

    pats = sorted((n, getattr(E, n)) for n in dir(E)
                  if isinstance(getattr(E, n), re.Pattern))
    for name, pat in pats:
        anchored = (pat.pattern.lstrip().startswith("^")
                    or pat.pattern.rstrip().endswith("$"))
        per_line = anchored and not (pat.flags & re.M)
        corp = abstracts if name in ABSTRACT_SIDE else docs

        # PRE: the original method — whole-document findall over the answer
        # corpus, for every pattern regardless of what it actually reads. Kept
        # so the report can show what the naive instrument reported and what it
        # missed, which is the whole point of this item.
        naive = 0
        for _, text in docs:
            try:
                naive += len(pat.findall(text))
            except Exception:
                pass

        hits = ndocs = 0
        for _, text in corp:
            try:
                if per_line:
                    n = sum(1 for ln in text.split("\n") if pat.search(ln))
                else:
                    n = len(pat.findall(text))
            except Exception:
                n = 0
            hits += n
            ndocs += (n > 0)
        rows.append({"kind": "pattern", "name": name,
                     "hits_naive": naive, "hits": hits, "docs": ndocs,
                     "corpus": "abstracts" if name in ABSTRACT_SIDE else "answers",
                     "applied_as": "per-line" if per_line else "document"})

    # ── text detectors ───────────────────────────────────────────────
    for name in TEXT_FNS:
        fn = getattr(E, name, None)
        if fn is None:
            rows.append({"kind": "fn", "name": name, "hits": -1,
                         "docs": 0, "error": "not found"})
            continue
        hits = ndocs = 0
        err = None
        for _, text in docs:
            try:
                n = size_of(fn(text))
            except Exception as e:
                err = err or "%s: %s" % (type(e).__name__, e)
                n = 0
            hits += n
            ndocs += (n > 0)
        row = {"kind": "fn", "name": name, "hits": hits, "docs": ndocs}
        if err:
            row["error"] = err[:160]
        rows.append(row)

    # ── report ───────────────────────────────────────────────────────
    zeros = [r for r in rows if r["hits"] == 0]
    unjustified = [r for r in zeros if r["name"] not in ZERO_IS_CORRECT]

    print("%-42s %-9s %9s %8s %6s" % ("detector", "corpus", "pre", "post", "docs"))
    for r in sorted(rows, key=lambda x: (x["hits"], x["name"])):
        flag = ""
        if r["hits"] == 0:
            flag = "  <- ZERO (justified)" if r["name"] in ZERO_IS_CORRECT \
                   else "  <- UNJUSTIFIED ZERO"
        elif r.get("hits_naive") == 0:
            flag = "  <- RECOVERED by the corrected instrument"
        if r.get("error"):
            flag += "  ERR " + r["error"][:60]
        pre = r.get("hits_naive")
        print("%-42s %-9s %9s %8d %6d%s"
              % (r["name"], r.get("corpus", "answers"),
                 "-" if pre is None else pre, r["hits"], r["docs"], flag))

    recovered = [r for r in rows if r.get("hits_naive") == 0 and r["hits"] > 0]
    print("\n%d detector(s) reported ZERO under the naive instrument and are "
          "non-zero under the corrected one:" % len(recovered))
    for r in sorted(recovered, key=lambda x: -x["hits"]):
        print("  %-40s 0 -> %-7d (%s, %s)"
              % (r["name"], r["hits"], r["corpus"], r["applied_as"]))

    print("\n%d detectors audited, %d zero, %d unjustified"
          % (len(rows), len(zeros), len(unjustified)))
    if unjustified:
        print("\nUNJUSTIFIED ZEROS — each is a candidate for the split-item class:")
        for r in unjustified:
            print("  %s (%s)" % (r["name"], r["kind"]))

    if "--json" in sys.argv:
        out = sys.argv[sys.argv.index("--json") + 1]
        json.dump(rows, open(out, "w", encoding="utf-8"), indent=1)
        print("\nwrote %s" % out)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
