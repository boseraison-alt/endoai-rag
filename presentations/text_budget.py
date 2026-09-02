"""
Curo — body budget, auto-split, and citation-marker handling
=============================================================
Spec §1.3 / §2.2. Two rules live here, and both are *rendering* rules:

  1. **Body budget.** A content-class slide carries at most 5 bullets of about
     25 words each, OR one table, OR one figure. Anything more overflows onto a
     continuation slide. Long tables split with the header row repeated.

  2. **No raw markers.** `[[PMID:12345]]` must never reach a slide. The marker
     is *extracted* into the slide's citation footer / PMID pills and removed
     from the visible run.

The prime rule for this whole phase is "rendering only, never authoring", and
it constrains the implementation in one non-obvious way: **an over-long bullet
is never truncated.** Cutting a 40-word bullet to 25 words would be editing
clinical text. Instead an over-long bullet simply *costs* more of the slide's
budget (ceil(words / 25) slots), so it pushes its neighbours onto the next
slide and arrives intact. The budget controls how much text shares a slide; it
never controls what the text says.
"""

from __future__ import annotations

import math
import re

from presentations.design_tokens import BODY_BUDGET

# ── Citation markers ──────────────────────────────────────────────────────────
# The generator emits `[[PMID:12345]]`, but real decks also contain the
# single-bracket `[PMID:12345]` variant and comma-joined lists. Match all of
# them: the rule is that no bracketed PMID marker of any shape reaches a slide.
# `trust-surface-v1` Q4: the id is NOT always numeric. Hand-ingested authority
# documents carry synthetic keys (`ESE-QG-2023`, `AAE-PS-obturation`,
# `NBK430685`) and the engine cites them with exactly this marker shape. While
# these patterns said `[0-9]`, `[[PMID:ESE-QG-2023]]` walked straight through
# the chokepoint and onto a rendered surface. Mirrors `endo_ai._PMID_ID_PAT`.
_PMID_KEY = r"(?:[0-9]{1,9}|[A-Za-z][A-Za-z0-9._-]{1,63})"
PMID_MARKER_RE = re.compile(
    r"\[{1,2}\s*PMIDS?\s*[:\-]?\s*(" + _PMID_KEY +
    r"(?:\s*[,;/]\s*" + _PMID_KEY + r")*)\s*\]{1,2}",
    re.IGNORECASE,
)

# A bare "PMID 12345" / "PMID: 12345" with no brackets. Rendered as a pill too,
# so the footer is the single place citations appear.
BARE_PMID_RE = re.compile(r"\bPMIDS?\s*[:\-]?\s*([0-9]{5,9})\b", re.IGNORECASE)

_WS_RE = re.compile(r"[ \t ]{2,}")
_ORPHAN_PUNCT_RE = re.compile(r"\s+([,.;:)\]])")
_EMPTY_BRACKET_RE = re.compile(r"\(\s*\)|\[\s*\]")


def extract_pmids(text: str) -> list[str]:
    """Return every PMID cited in `text`, in first-appearance order, deduped."""
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for match in PMID_MARKER_RE.finditer(text):
        for num in re.split(r"[,;/]", match.group(1)):
            num = num.strip()
            if num and num not in seen:
                seen.add(num)
                found.append(num)
    for match in BARE_PMID_RE.finditer(text):
        num = match.group(1).strip()
        if num and num not in seen:
            seen.add(num)
            found.append(num)
    return found


def strip_markers(text: str) -> str:
    """Remove every *bracketed* citation marker, leaving the prose untouched.

    This is the single chokepoint that enforces the no-raw-markers rule. It is
    called from `slide_helpers.add_textbox` / `add_multiline_textbox`, so a
    marker cannot reach a slide even from a pattern that forgot to sanitise.

    A **bare** "PMID 28294701" is deliberately left alone: that is the spec's
    own footer format ("Schulte-Lünzum et al. 2017 · Photomedicine and Laser
    Surgery · n = 100 · PMID 28294701", §1.3). Stripping it here would delete
    the citation the footer exists to show. Only the machine-readable
    `[[PMID:N]]` / `[PMID:N]` marker is forbidden on a slide.
    """
    if not text:
        return text or ""
    out = PMID_MARKER_RE.sub("", text)
    out = _EMPTY_BRACKET_RE.sub("", out)
    out = _ORPHAN_PUNCT_RE.sub(r"\1", out)
    out = _WS_RE.sub(" ", out)
    # Collapse the space a removed inline marker leaves behind mid-sentence.
    out = re.sub(r"\s+\n", "\n", out)
    return out.strip(" \t")


def has_raw_marker(text: str) -> bool:
    """True if `text` still contains a bracketed PMID marker.

    Bare "PMID 28294701" is the approved footer form and is not a raw marker.
    """
    if not text:
        return False
    return bool(PMID_MARKER_RE.search(text))


def sanitize(text: str) -> str:
    """strip_markers plus whitespace tidy — what every visible run goes through."""
    return strip_markers(str(text) if text is not None else "")


# ── Body budget ───────────────────────────────────────────────────────────────

def word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", sanitize(text)) if w])


def bullet_cost(text: str, max_words: int | None = None) -> int:
    """How many of the slide's 5 bullet slots this bullet consumes.

    One slot per `max_words` words (or part thereof), minimum one. This is what
    makes an over-long bullet split the *slide* instead of the *sentence*.
    """
    if max_words is None:
        max_words = BODY_BUDGET["max_words_per_bullet"]
    n = word_count(text)
    if n <= max_words:
        return 1
    return int(math.ceil(n / float(max_words)))


def split_bullets(
    bullets: list,
    *,
    max_bullets: int | None = None,
    max_words: int | None = None,
) -> list[list]:
    """Pack bullets into slide-sized pages. Never drops or truncates a bullet.

    Returns a list of pages; each page is a list of the original bullet objects
    (str or dict — untouched, so callers keep whatever structure they had).
    A single bullet costing more than a whole slide still gets its own page.
    """
    if max_bullets is None:
        max_bullets = BODY_BUDGET["max_bullets"]
    if max_words is None:
        max_words = BODY_BUDGET["max_words_per_bullet"]

    items = list(bullets or [])
    if not items:
        return [[]]

    costs = [bullet_cost(_bullet_text(i), max_words) for i in items]

    # Balance across the pages the budget already forces. Filling each page to
    # the cap and letting the remainder fall onto the last one produces an
    # orphan — four bullets then one. Spreading the same bullets over the same
    # number of pages costs nothing and never exceeds the cap.
    n_pages = 1
    while True:
        target = max(1, math.ceil(sum(costs) / float(n_pages)))
        target = min(max(target, max(costs)), max_bullets)
        packed = _pack(items, costs, target, max_bullets)
        if len(packed) <= n_pages:
            return packed
        n_pages += 1
        if n_pages > len(items):
            return _pack(items, costs, max_bullets, max_bullets)


def _pack(items, costs, target: int, hard_max: int) -> list[list]:
    pages: list[list] = []
    page: list = []
    used = 0
    for item, cost in zip(items, costs):
        if page and (used + cost > target or used + cost > hard_max
                     or len(page) >= hard_max):
            pages.append(page)
            page, used = [], 0
        page.append(item)
        used += cost
    if page:
        pages.append(page)
    return pages


def _bullet_text(item) -> str:
    """Best-effort visible text of a bullet, whatever shape it arrived in."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        parts = [
            item.get("header") or item.get("heading") or item.get("label") or "",
            item.get("body") or item.get("description") or item.get("text") or "",
        ]
        return " ".join(p for p in parts if p)
    return str(item)


def split_rows(rows: list, *, max_rows: int | None = None) -> list[list]:
    """Split table rows into pages. The caller repeats the header on each page."""
    if max_rows is None:
        max_rows = BODY_BUDGET["max_table_rows"]
    items = list(rows or [])
    if not items:
        return [[]]
    return [items[i:i + max_rows] for i in range(0, len(items), max_rows)]


def split_cards(cards: list, *, max_cards: int | None = None) -> list[list]:
    """Split a card grid (decision tree / takeaways) into pages."""
    if max_cards is None:
        max_cards = BODY_BUDGET["max_cards"]
    items = list(cards or [])
    if not items:
        return [[]]
    return [items[i:i + max_cards] for i in range(0, len(items), max_cards)]


CONTINUATION_ROLE = "CONTINUED"


def continuation_eyebrow(eyebrow: str, page_index: int) -> str:
    """Mark a continuation slide in the eyebrow's *slide role* slot (spec §1.3).

    The title is left exactly as authored — the deck says "continued" in the
    furniture, not by editing the clinical heading.
    """
    base = (eyebrow or "").strip()
    if page_index <= 0:
        return base
    return f"{base} · {CONTINUATION_ROLE}" if base else CONTINUATION_ROLE


__all__ = [
    "PMID_MARKER_RE", "BARE_PMID_RE",
    "extract_pmids", "strip_markers", "has_raw_marker", "sanitize",
    "word_count", "bullet_cost",
    "split_bullets", "split_rows", "split_cards",
    "CONTINUATION_ROLE", "continuation_eyebrow",
]
