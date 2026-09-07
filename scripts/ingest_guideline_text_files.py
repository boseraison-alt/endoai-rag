"""Ingest `data/guideline_text/<id>.txt` — the organisation's own words.

WHY THESE FILES EXIST. 45 of 72 guideline pointer rows could not be fetched by
`scripts/fetch_guideline_text.py`: aae.org returns 403 to any non-browser
request and prosthodontics.org returns an Imperva notice. RB fetched 13 of them
through a real Chrome session and committed the text with a sidecar recording
where it came from. Nothing in those files is model-written; nothing here
writes a word that is not copied from them.

WHAT IS STORED, per the batch spec:

  1. The .txt bytes are hashed and checked against the sidecar's `sha256`.
     A MISMATCH REFUSES THE ROW — it does not warn. A file whose hash does not
     match its sidecar has been altered somewhere between Chrome and here, and
     "verbatim from the organisation" is the only claim this ingest makes.
  2. `[[PAGE n]]` marker lines are dropped. Those are RB's page breaks from
     pdf.js, not the document's words. Nothing else is removed — the PDFs'
     own running heads stay, because they ARE in the text layer.
  3. The body starts at the sidecar's `body_starts_with`, so the title block
     and the leading running head are skipped.
  4. If the document has a line that is exactly `Summary`, `SUMMARY`,
     `Conclusion`, `Conclusions` or `CONCLUSIONS`, the text runs from there to
     the next heading or to References. Otherwise it is the first 300 words
     from the body start.

  Provenance: `abstract_source = 'org_page_browser'`, plus the sidecar's
  `url`, `fetched_at` and `sha256`.

A NOTE ON `abstract_sha256`, because the column now means two things. For
`org_page` rows it hashes the STORED SPAN. For `org_page_browser` rows it
hashes the SOURCE FILE, as the batch specifies — so the chain that can be
re-verified is file -> sidecar -> row, not row -> live page.
`tests/test_guideline_text_provenance.py` checks that chain directly.

    python scripts/ingest_guideline_text_files.py            # DRY RUN
    python scripts/ingest_guideline_text_files.py --apply
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import rag  # noqa: E402

SRC = ROOT / "data" / "guideline_text"
MAX_WORDS = 300
SUMMARY_HEADS = {"Summary", "SUMMARY", "Conclusion", "Conclusions",
                 "CONCLUSIONS"}
STOP_HEADS = {"references", "reference list", "bibliography"}
_PAGE_MARKER = re.compile(r"^\s*\[\[PAGE \d+\]\]\s*$")


def looks_like_heading(line: str) -> bool:
    """A short, unpunctuated line — how these documents mark a section.

    AT MOST THREE WORDS, and that limit is measured rather than chosen. The AAE
    files are pdf.js text layers: hard-wrapped prose with NO blank lines
    anywhere, so an ordinary wrapped line looks structurally identical to a
    heading. At a six-word limit,

        "A pretreatment diagnosis of irreversible pulpitis"

    — the fourth line of the AAE-VPT-2021 summary — was read as the next
    heading and truncated that summary to 46 words. Every real section heading
    in these thirteen documents is one word (`Summary`, `Conclusion`,
    `References`, `Introduction`); three is already generous.

    Deliberately conservative in the same direction throughout: a summary that
    runs on a little is a smaller error than one cut short, because the stored
    text is the only thing standing between a clinician and "position not
    quoted".
    """
    s = line.strip()
    if not s:
        return False
    if s.lower().rstrip(":") in STOP_HEADS:
        return True
    if len(s.split()) > 3:
        return False
    if s[-1] in ".,;:?!)":
        return False
    return s[0].isupper() and not s[0].isdigit()


def extract(text: str, body_starts_with: str):
    """(stored_text, rule, notes). A verbatim span of `text`."""
    lines = [l for l in text.splitlines() if not _PAGE_MARKER.match(l)]
    n_pages = sum(1 for l in text.splitlines() if _PAGE_MARKER.match(l))

    # ── body start ──
    body_i = 0
    probe = " ".join((body_starts_with or "").split())
    if probe:
        flat = [" ".join(l.split()) for l in lines]
        for i in range(len(flat)):
            window = " ".join(flat[i:i + 6]).strip()
            if window.startswith(probe[:60]):
                body_i = i
                break
        else:
            first = probe.split()[0] if probe.split() else ""
            for i, l in enumerate(flat):
                if first and l.startswith(first):
                    body_i = i
                    break

    # ── rule 1: a marked summary or conclusion ──
    for i in range(body_i, len(lines)):
        if lines[i].strip() in SUMMARY_HEADS:
            out = []
            for j in range(i + 1, len(lines)):
                s = lines[j].strip()
                if s.lower().rstrip(":") in STOP_HEADS:
                    break
                if out and looks_like_heading(lines[j]):
                    break
                out.append(lines[j])
            # TRIM BACK TO THE LAST LINE THAT ENDS A SENTENCE.
            #
            # The AAE files carry the PDF's own running heads, and a summary
            # that ends mid-page is followed by the next page's furniture:
            # AAE-VPT-2021's summary ends at "...also warranted." — exactly
            # where RB's sidecar says it ends — and the span then ran on into
            # "Position StatementPage 5AAE Position S tatement – V ital Pulp
            # Therapy".
            #
            # Stopping at the `[[PAGE n]]` marker instead was measured and
            # rejected: all three PDF summaries cross a page break, and it
            # would have cut AAE-MICROSCOPES-2020's conclusion from 280 words
            # to the ~9 lines before its break. Trimming the TAIL removes
            # dangling furniture without touching a word inside the span.
            while out and not out[-1].strip().endswith((".", "?", "!", '."',
                                                        ".)", ".”")):
                out.pop()
            span = "\n".join(out).strip()
            if len(span.split()) >= 15:
                return span, "marked:%s" % lines[i].strip(), n_pages

    # ── rule 2: the first 300 words of the body ──
    body = "\n".join(lines[body_i:]).strip()
    words = body.split()
    if not words:
        return "", "empty", n_pages
    cut = " ".join(words[:MAX_WORDS])
    span = body[:len(cut)]
    if " " in span and len(words) > MAX_WORDS:
        span = span[:span.rfind(" ")]
    return span.strip(), "first_%d_words" % MAX_WORDS, n_pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    sidecars = sorted(SRC.glob("*.json"))
    print("=" * 78)
    print("GUIDELINE TEXT FILES -> LIBRARY  (%s)"
          % ("APPLY" if args.apply else "DRY RUN"))
    print("=" * 78)
    print("  sidecars found: %d" % len(sidecars))
    print()

    conn = rag.get_conn()
    cur = conn.cursor()

    updated = skipped = mismatched = missing = 0
    rows_out = []
    for sc in sidecars:
        meta = json.loads(sc.read_text(encoding="utf-8"))
        gid = meta["id"]
        txt = sc.with_suffix(".txt")
        if not txt.exists():
            print("  %-34s NO .txt" % gid)
            missing += 1
            continue

        # ── 1. hash gate: refuse, do not warn ──
        raw = txt.read_bytes()
        got = hashlib.sha256(raw).hexdigest()
        if got != (meta.get("sha256") or ""):
            print("  %-34s SHA256 MISMATCH" % gid)
            print("      sidecar %s" % meta.get("sha256"))
            print("      file    %s" % got)
            # NAME THE CRLF CASE. It presented as all thirteen files being
            # corrupt at once, on a clean `git status`, with nothing edited —
            # git had checked LF bytes out as CRLF. Diagnosing that from two
            # hex strings cost real time; the fix is `.gitattributes`, not a
            # looser hash.
            if hashlib.sha256(
                    raw.replace(b"
", b"
")).hexdigest() == meta.get(
                        "sha256"):
                print("      ^ the ONLY difference is CRLF line endings. Git "
                      "rewrote this file on checkout.")
                print("        Fix the checkout, not the hash: .gitattributes "
                      "carries `data/guideline_text/*.txt -text`;")
                print("        then `rm` these files and `git checkout -- "
                      "data/guideline_text/`.")
            mismatched += 1
            continue

        cur.execute("""SELECT pmid, COALESCE(abstract_source,''),
                              COALESCE(abstract,'')
                       FROM endo_papers_rag WHERE pmid = %s""", (gid,))
        row = cur.fetchone()
        if not row:
            print("  %-34s NO LIBRARY ROW" % gid)
            missing += 1
            continue
        _pmid, src_now, abs_now = row

        # ── skip rules ──
        # Already fetched by the earlier script, or carrying a real PubMed
        # abstract. A model_summary_legacy row is NOT skipped: replacing a
        # paraphrase with the document's own words is the whole point.
        if src_now == "org_page":
            print("  %-34s SKIP (already org_page)" % gid)
            skipped += 1
            continue
        if (src_now == "" and abs_now.strip()
                and not abs_now.startswith("GUIDELINE RECORD")):
            print("  %-34s SKIP (has PubMed text)" % gid)
            skipped += 1
            continue

        span, rule, n_pages = extract(txt.read_text(encoding="utf-8"),
                                      meta.get("body_starts_with", ""))
        if not span:
            print("  %-34s NO TEXT EXTRACTED" % gid)
            missing += 1
            continue

        rows_out.append((gid, rule, len(span.split()), n_pages,
                         src_now or "-"))
        print("  %-34s %-26s %4d words  (%d page markers dropped, was %s)"
              % (gid, rule[:26], len(span.split()), n_pages, src_now or "-"))
        if args.apply:
            cur.execute("""
                UPDATE endo_papers_rag SET
                    abstract = %s,
                    abstract_source = 'org_page_browser',
                    abstract_url = %s,
                    abstract_fetched = %s,
                    abstract_sha256 = %s,
                    fetch_failed = ''
                WHERE pmid = %s
            """, (span, meta.get("url", ""), meta.get("fetched_at", ""),
                  meta.get("sha256", ""), gid))
            conn.commit()
        updated += 1

    print()
    print("=" * 78)
    print("  files            %d" % len(sidecars))
    print("  rows updated     %d" % updated)
    print("  skipped          %d" % skipped)
    print("  sha256 mismatch  %d" % mismatched)
    print("  missing/no text  %d" % missing)
    by_rule = {}
    for _g, rule, _w, _p, _s in rows_out:
        by_rule[rule.split(":")[0]] = by_rule.get(rule.split(":")[0], 0) + 1
    print("  by rule          %s" % by_rule)
    print()
    if mismatched:
        print("  REFUSED: %d file(s) do not match their sidecar hash. Nothing "
              "was written for those rows." % mismatched)
    print("  %s" % ("APPLIED." if args.apply else
                    "DRY RUN — nothing written."))
    cur.close()
    conn.close()
    return 1 if mismatched else 0


if __name__ == "__main__":
    sys.exit(main())
