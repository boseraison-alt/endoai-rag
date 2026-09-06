"""Item D (2026-09-07) — the DOCUMENT'S OWN WORDS for pointer records.

THE PROBLEM. A guideline PubMed does not index is stored as a POINTER: org,
title, year, status, URL, and no text. The model cannot state such a
document's position from the row, and on 2026-09-06 it stated one from its own
memory instead — the citation-support checker caught it, which is the right
detector firing on the wrong-shaped input.

WHAT IS AND IS NOT ALLOWED. Storing the ORGANISATION'S OWN summary, verbatim,
is not paraphrase. A model-written summary is, and stays forbidden:
`verify_citation_support` checking a claim against a paraphrase is a hole
directly under the grounding guarantee. Nothing in this script writes a word
that is not copied from the document.

WHAT IS TAKEN, in order of preference:
  1. a marked abstract / executive summary / summary of recommendations
  2. failing that, the first 300 words of the document body

Both are verbatim spans of the page's own extracted text, so a later check can
re-fetch and confirm the stored text is still a substring — which is the
provenance test this item ships.

Failures are RECORDED, not retried blindly: login-gated (the AAO CPG),
JS-only, 404 and timeout differ in what would fix them.

    python scripts/fetch_guideline_text.py                # dry run
    python scripts/fetch_guideline_text.py --apply
    python scripts/fetch_guideline_text.py --apply --minutes 90
"""
import argparse
import hashlib
import io
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests  # noqa: E402

import rag  # noqa: E402

# A FULL BROWSER HEADER SET, and the difference is not cosmetic. The first
# version sent User-Agent and Accept only, and every one of the first eight
# URLs came back 403 — which would have been reported as "the publishers block
# us" when it was in fact the request being obviously automated. Retested with
# the headers below: NICE, SDCEP, CGDent, gov.uk and IADT all returned 200.
# Only aae.org still refuses, which is a real finding about one host rather
# than a false one about all of them.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "application/pdf;q=0.9,image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "en-GB,en;q=0.9",
    # NO `br`. brotli is not installed in this environment, so advertising it
    # made servers send brotli and `requests` hand back undecoded bytes —
    # AAO-CPG-2023 "succeeded" with 75 words of mojibake and was recorded as
    # `no_extractable_text`, which blamed the page for my header.
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

MIN_WORDS = 40          # below this the "text" is a nav bar or a cookie notice
MAX_WORDS = 300

# Headings that mark a document's own summary, in preference order.
_SUMMARY_HEADS = [
    r"summary of recommendations", r"executive summary", r"key recommendations",
    r"abstract", r"summary", r"recommendations", r"introduction",
]

_LOGIN_CUES = re.compile(
    r"(sign in|log ?in|member login|subscribe to (?:view|read)|"
    r"purchase access|institutional access|create an account|"
    r"access denied|paywall)", re.I)
_JS_CUES = re.compile(
    r"(enable javascript|requires javascript|javascript is (?:required|disabled))",
    re.I)
# A 200 that is really a refusal. Recorded under its own reason rather than as
# "no extractable text", which blamed the document for the bot wall in front
# of it: prosthodontics.org returns an Imperva/Incapsula notice, aaom.com a
# consent wall, and both were being filed as if the page were empty.
_BLOCK_CUES = re.compile(
    r"(incapsula incident|imperva|request unsuccessful|"
    r"do not sell or share my personal information|"
    r"attention required|cloudflare|are you a robot|"
    r"access to this page has been denied)", re.I)
# Mojibake: a decode failure looks like text and is not. Cheap detector — the
# share of characters that are not printable ASCII/latin.
_MOJIBAKE = re.compile(r"[^\x09\x0a\x0d\x20-\x7e -ɏ‐-›]")


def _norm(text: str) -> str:
    """Collapse whitespace, deterministically.

    The stored text must be re-derivable from the live page for the
    provenance test, so normalisation has to be a pure function of the page —
    no dates, no ordering, nothing environmental.
    """
    t = (text or "").replace("\xa0", " ")
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r"\n{2,}", "\n", t)
    return t.strip()


def page_text(url, timeout=25):
    """(text, kind, error). Plain text of an HTML page or a PDF."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout,
                         allow_redirects=True)
    except Exception as ex:
        return "", "", "fetch_error: %s" % type(ex).__name__
    if r.status_code != 200:
        return "", "", "http_%d" % r.status_code
    ctype = (r.headers.get("Content-Type") or "").lower()

    if "pdf" in ctype or url.lower().endswith(".pdf"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(r.content))
            parts = []
            for page in reader.pages[:12]:
                parts.append(page.extract_text() or "")
                if sum(len(p.split()) for p in parts) > 1200:
                    break
            return _norm("\n".join(parts)), "pdf", ""
        except Exception as ex:
            return "", "pdf", "pdf_parse_error: %s" % type(ex).__name__

    html = r.text or ""
    if _JS_CUES.search(html) and len(html) < 40000:
        return "", "html", "js_only"
    try:
        import lxml.html as LH
        doc = LH.fromstring(html)
        for bad in doc.xpath("//script|//style|//nav|//header|//footer|//noscript"):
            bad.getparent().remove(bad)
        main = doc.xpath("//main|//article|//div[@role='main']")
        node = main[0] if main else doc
        return _norm(node.text_content()), "html", ""
    except Exception as ex:
        return "", "html", "html_parse_error: %s" % type(ex).__name__


def extract_summary(text):
    """(span, how). A verbatim span of `text`: the document's own summary if
    it marks one, else its first 300 words."""
    if not text:
        return "", ""
    low = text.lower()
    for head in _SUMMARY_HEADS:
        m = re.search(r"(?:^|\n)\s*%s\b[ :.\-]*\n?" % head, low)
        if not m:
            continue
        start = m.end()
        span = text[start: start + 4000]
        words = span.split()
        if len(words) >= MIN_WORDS:
            cut = " ".join(words[:MAX_WORDS])
            # Snap back to a verbatim substring of the ORIGINAL text: joining
            # split words would silently rewrite the whitespace and break the
            # provenance check.
            idx = text.find(words[0], start - 1)
            if idx >= 0:
                approx = text[idx: idx + len(cut) + 200]
                # trim to the last full word inside the budget
                out = approx[:len(cut)]
                out = out[:out.rfind(" ")] if " " in out else out
                if len(out.split()) >= MIN_WORDS:
                    return out.strip(), "marked:%s" % head.replace(r"\s", " ")
    words = text.split()
    if len(words) < MIN_WORDS:
        return "", ""
    cut = " ".join(words[:MAX_WORDS])
    out = text[:len(cut)]
    out = out[:out.rfind(" ")] if " " in out else out
    return out.strip(), "first_%d_words" % MAX_WORDS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--minutes", type=float, default=90.0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--retry-failed", action="store_true",
                    help="only rows that already failed; never re-fetch a "
                         "row whose text is already stored")
    args = ap.parse_args()

    conn = rag.get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT pmid, COALESCE(guideline_org,''), title,
               COALESCE(guideline_url,''), COALESCE(abstract,'')
        FROM endo_papers_rag
        WHERE level_key = 'guideline'
          AND COALESCE(quarantine_reason,'') = ''
          AND COALESCE(guideline_url,'') <> ''
          AND (abstract IS NULL OR abstract LIKE 'GUIDELINE RECORD%%')
          AND (%s = FALSE OR COALESCE(fetch_failed,'') <> '')
        ORDER BY COALESCE(guideline_org,''), pmid
    """, (bool(args.retry_failed),))
    rows = cur.fetchall()
    if args.limit:
        rows = rows[:args.limit]

    print("=" * 78)
    print("ITEM D — THE DOCUMENT'S OWN WORDS  (%s)"
          % ("APPLY" if args.apply else "DRY RUN"))
    print("=" * 78)
    print("  pointer rows with a URL: %d" % len(rows))
    print("  time box: %.0f minutes" % args.minutes)
    print()

    t0 = time.time()
    by_org = defaultdict(lambda: {"fetched": 0, "failed": 0, "reasons": []})
    done = timed_out = 0
    for i, (pmid, org, title, url, _abs) in enumerate(rows, 1):
        if (time.time() - t0) / 60.0 > args.minutes:
            timed_out = len(rows) - i + 1
            print("  TIME BOX REACHED — %d rows not attempted" % timed_out)
            break
        text, kind, err = page_text(url)
        if not err and text:
            head = text[:3000]
            if _BLOCK_CUES.search(head):
                err = "bot_blocked"
            elif _LOGIN_CUES.search(head) and len(text.split()) < 400:
                err = "login_gated"
            elif len(_MOJIBAKE.findall(head)) > len(head) * 0.15:
                err = "undecodable_response"
        span, how = ("", "") if err else extract_summary(text)
        if not err and not span:
            err = "no_extractable_text"

        if err:
            by_org[org or "(none)"]["failed"] += 1
            by_org[org or "(none)"]["reasons"].append(err)
            print("  [%2d/%d] %-30s FAIL %-22s %s"
                  % (i, len(rows), pmid[:30], err, url[:44]))
            if args.apply:
                cur.execute("UPDATE endo_papers_rag SET fetch_failed=%s "
                            "WHERE pmid=%s", (err, pmid))
                conn.commit()
        else:
            by_org[org or "(none)"]["fetched"] += 1
            done += 1
            sha = hashlib.sha256(span.encode("utf-8")).hexdigest()
            print("  [%2d/%d] %-30s OK   %-22s %d words"
                  % (i, len(rows), pmid[:30], how[:22], len(span.split())))
            if args.apply:
                cur.execute("""
                    UPDATE endo_papers_rag SET
                        abstract = %s, abstract_source = 'org_page',
                        abstract_fetched = %s, abstract_sha256 = %s,
                        abstract_url = %s, fetch_failed = ''
                    WHERE pmid = %s
                """, (span, datetime.now().date().isoformat(), sha, url, pmid))
                conn.commit()
        time.sleep(1.0)

    print()
    print("=" * 78)
    print("BY ORGANISATION")
    print("=" * 78)
    print("  %-12s %8s %8s  %s" % ("org", "fetched", "failed", "reasons"))
    for org in sorted(by_org):
        d = by_org[org]
        reasons = ", ".join(sorted(set(d["reasons"])))[:60]
        print("  %-12s %8d %8d  %s" % (org, d["fetched"], d["failed"], reasons))
    tot_f = sum(d["fetched"] for d in by_org.values())
    tot_x = sum(d["failed"] for d in by_org.values())
    print("  %-12s %8d %8d" % ("TOTAL", tot_f, tot_x))
    if timed_out:
        print("  %-12s %8s %8s  %d rows not attempted (time box)"
              % ("(untried)", "-", "-", timed_out))
    print()
    print("  %s" % ("APPLIED." if args.apply else "DRY RUN — nothing written."))
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
