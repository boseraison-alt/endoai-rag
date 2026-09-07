"""Item F2 (2026-09-08) — remove the paraphrase text itself, not just its reach.

TWO ROWS carry `abstract_source = 'model_summary_legacy'`: text a model wrote
ABOUT a document, stored where the document's own words belong. That is a hole
directly under the grounding guarantee — `verify_citation_support` checks a
claim against stored text, and checking it against a paraphrase Curo cannot
verify is worse than having no text at all.

BOTH ARE ALREADY RETIRED. On 2026-09-07 they were quarantined with `redirect_to`
set to their manifest records, and 32 stored answers that cited them now resolve
to `34352305` and `AAE-DIAGNOSIS-2009` at serve time. So they are already
unreachable by retrieval and uncitable.

This item goes further, and the difference is the point: retirement HID the
paraphrase, this DELETES it. A quarantined row is still a row, still readable by
anything that queries the table directly, and "unreachable today" is a fact
about today's query paths. The text is replaced by the same pointer form every
other un-fetched guideline record carries — organisation, title, year, status,
URL — so what remains is a link a clinician can follow rather than prose nobody
can verify.

THE RETIREMENT IS NOT UNDONE. `quarantine_reason` and `redirect_to` are left
exactly as they are: `quarantine_reason` is the undo, and the redirects are what
keep those 32 stored answers resolving.

    python scripts/replace_legacy_paraphrase_with_pointer.py            # DRY RUN
    python scripts/replace_legacy_paraphrase_with_pointer.py --apply
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import rag  # noqa: E402

SEED = ROOT / "data" / "guidelines_seed.json"


def pointer_text(rec, target):
    """The same shape `ingest_guidelines_seed.pointer_text` writes, plus the
    line that matters here: where the document's real text now lives."""
    lines = [
        "GUIDELINE RECORD — pointer only; Curo has not stored this document's "
        "text.",
        "Organisation: %s" % (rec.get("org") or "?"),
        "Title: %s" % (rec.get("title") or "?"),
        "Year: %s" % (rec.get("year") or "?"),
        "Status: %s" % (rec.get("status") or "?"),
        "Jurisdiction: %s" % (rec.get("jurisdiction") or "?"),
    ]
    if rec.get("url"):
        lines.append("Read it: %s" % rec["url"])
    lines.append(
        "RETIRED KEY — this record is now %s. The text stored here until "
        "2026-09-08 was a model-written summary, not the document's own words, "
        "and has been removed." % target)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    man = json.loads(SEED.read_text(encoding="utf-8"))["guidelines"]
    by_id = {g["id"]: g for g in man}
    by_pmid = {str(g.get("pmid") or ""): g for g in man if g.get("pmid")}

    conn = rag.get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT pmid, COALESCE(redirect_to,''), COALESCE(quarantine_reason,''),
               length(COALESCE(abstract,''))
        FROM endo_papers_rag
        WHERE abstract_source = 'model_summary_legacy'
        ORDER BY pmid
    """)
    rows = cur.fetchall()

    print("=" * 78)
    print("ITEM F2 — LEGACY PARAPHRASE -> POINTER  (%s)"
          % ("APPLY" if args.apply else "DRY RUN"))
    print("=" * 78)
    print("  rows carrying model_summary_legacy: %d" % len(rows))
    if not rows:
        print("  nothing to do")
        return 0

    today = datetime.now().date().isoformat()
    plan = []
    for pmid, redirect, quar, n in rows:
        rec = by_id.get(redirect) or by_pmid.get(redirect) or {}
        if not rec:
            print("  %-22s redirect %r names no manifest record — SKIPPED"
                  % (pmid, redirect))
            continue
        text = pointer_text(rec, redirect)
        plan.append((pmid, text, redirect, n))
        print()
        print("  %s" % pmid)
        print("    paraphrase now      : %d chars" % n)
        print("    replaced by pointer : %d chars -> %s" % (len(text), redirect))
        print("    quarantine_reason   : KEPT (%s...)" % quar[:44])
        print("    redirect_to         : KEPT (%s)" % redirect)

    print()
    print("  will rewrite %d row(s); 0 changes to quarantine_reason or "
          "redirect_to" % len(plan))

    if args.apply:
        for pmid, text, _r, _n in plan:
            cur.execute("""
                UPDATE endo_papers_rag SET
                    abstract = %s,
                    abstract_source = 'pointer',
                    abstract_fetched = %s,
                    abstract_sha256 = %s,
                    abstract_url = '',
                    fetch_failed = ''
                WHERE pmid = %s
            """, (text, today,
                  hashlib.sha256(text.encode("utf-8")).hexdigest(), pmid))
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM endo_papers_rag "
                    "WHERE abstract_source = 'model_summary_legacy'")
        left = cur.fetchone()[0]
        print("\n  APPLIED — %d rewritten. Rows still carrying a model-written "
              "summary: %d" % (len(plan), left))
    else:
        conn.rollback()
        print("\n  DRY RUN — nothing written.")

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
