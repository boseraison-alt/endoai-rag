"""
Curo — chartable-data detector
===============================
Spec §1.5, and these are HARD rules, not preferences:

  * Every plotted value must appear **verbatim** in the cited source text.
  * Each chart carries its PMIDs in the footer.
  * **No chartable data -> no chart.** Never invent, never interpolate.

The detector is deliberately asymmetric in the same way the tier classifiers in
this codebase are: refusing to draw a chart that could have been drawn costs a
slide of visual interest, while drawing a chart from a number the source text
does not contain is exactly the failure this product exists to not have. So
every path here returns `None` unless the evidence for the chart is positive.

What it looks for (spec §2.3):
  * success percentages across arms   -> bar, or dot plot when near-equal
  * sample sizes                      -> bar
  * follow-up periods                 -> bar
  * per-tier counts                   -> evidence-shape stacked bar

"Verbatim" is strict. The numeric literal must appear in the source with the
same digits and the same decimal places, as a standalone number: `96.1` does
not match `96` and `96` does not match `961`. A rounded, re-derived or
re-expressed value fails the check and the chart is dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from presentations.design_tokens import TIER_ORDER, tier_key
from presentations.text_budget import extract_pmids, sanitize

# Unicode minus / en-dash used as minus in clinical prose.
_MINUS = {"−": "-", "–": "-", "‐": "-", "‑": "-"}

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _norm(text: str) -> str:
    if not text:
        return ""
    out = str(text)
    for bad, good in _MINUS.items():
        out = out.replace(bad, good)
    # thousands separators inside numbers: 1,200 -> 1200
    out = re.sub(r"(?<=\d),(?=\d{3}\b)", "", out)
    return out


def parse_number(raw: str) -> tuple[str, float] | None:
    """Return (literal, value) for the first number in `raw`, else None.

    `literal` is the number exactly as written (after minus/thousands
    normalisation) — that literal, not the float, is what must be found in the
    source text.
    """
    m = _NUM_RE.search(_norm(raw or ""))
    if not m:
        return None
    lit = m.group(0)
    try:
        return lit, float(lit)
    except ValueError:
        return None


def verbatim_in(literal: str, source_text: str) -> bool:
    """True iff `literal` appears in `source_text` as a standalone number.

    Guards both ends so `96` cannot match inside `961` or `96.1`, and `1.5`
    cannot match inside `21.53`.
    """
    if not literal or not source_text:
        return False
    src = _norm(source_text)
    pattern = r"(?<![\d.])" + re.escape(literal.lstrip("-")) + r"(?![\d.])"
    return bool(re.search(pattern, src))


@dataclass
class ChartSpec:
    """A chart that has passed the hard rules and may be rendered."""
    kind: str                       # "bar" | "dot" | "evidence_shape"
    labels: list[str]
    values: list[float]
    literals: list[str]             # the verbatim strings found in the source
    unit: str = ""
    title: str = ""
    axis_note: str | None = None    # required whenever the axis is truncated
    pmids: list[str] = field(default_factory=list)
    tier_keys: list[str] | None = None   # per-bar tier, for the ladder fills

    @property
    def is_multi_tier(self) -> bool:
        return bool(self.tier_keys)


# ── value harvesting ─────────────────────────────────────────────────────────

def _verified_pairs(pairs, source_text) -> list[tuple[str, str, float]] | None:
    """Keep (label, literal, value) only when EVERY value is verbatim in source.

    All-or-nothing on purpose: a chart in which one bar is sourced and another
    is not is worse than no chart, because the unsourced bar inherits the
    sourced one's credibility.
    """
    out: list[tuple[str, str, float]] = []
    for label, raw in pairs:
        parsed = parse_number(raw)
        if parsed is None:
            return None
        literal, value = parsed
        if not verbatim_in(literal, source_text):
            return None
        out.append((sanitize(str(label)).strip(), literal, value))
    return out or None


def _unit_of(raw: str) -> str:
    s = _norm(raw or "")
    if "%" in s:
        return "%"
    for token, unit in (("month", "months"), ("year", "years"),
                        ("week", "weeks"), ("day", "days")):
        if token in s.lower():
            return unit
    if re.search(r"\bn\s*=", s, re.I):
        return "n"
    return ""


def _choose_kind(values: list[float], unit: str) -> tuple[str, str | None]:
    """Bar from zero, or dot plot with an explicit axis note when near-equal.

    Spec §1.5: a truncated axis is allowed ONLY with an explicit note, and only
    for a near-equal comparison where a from-zero bar would show nothing.
    """
    if len(values) < 2:
        return "bar", None
    lo, hi = min(values), max(values)
    span = hi - lo
    if unit == "%" and lo >= 50 and span <= 10:
        floor = int(max(0, (lo - 2) // 5 * 5))
        return "dot", f"axis starts at {floor}"
    if lo > 0 and span / max(abs(hi), 1e-9) <= 0.08:
        floor = lo - span
        note_floor = int(floor) if float(floor).is_integer() else round(floor, 1)
        return "dot", f"axis starts at {note_floor}"
    return "bar", None


# ── per-spec detectors ───────────────────────────────────────────────────────

def _from_explicit_chart(spec: dict, source_text: str) -> ChartSpec | None:
    """A spec that already carries labels+values (legacy `chart_bar`, or an
    explicit `chart` block). Still subject to the verbatim rule."""
    chart = spec.get("chart") if isinstance(spec.get("chart"), dict) else None
    labels = (chart or spec).get("categories") or (chart or spec).get("labels")
    values = (chart or spec).get("values")
    if not labels or not values or len(labels) != len(values):
        return None
    pairs = list(zip(labels, [str(v) for v in values]))
    verified = _verified_pairs(pairs, source_text)
    if not verified:
        return None
    unit = (chart or spec).get("unit", "") or _unit_of(str(values[0]))
    vals = [v for _, _, v in verified]
    kind, note = _choose_kind(vals, unit)
    return ChartSpec(
        kind=kind,
        labels=[lbl for lbl, _, _ in verified],
        values=vals,
        literals=[lit for _, lit, _ in verified],
        unit=unit,
        title=sanitize(spec.get("title", "")),
        axis_note=note,
        pmids=_spec_pmids(spec),
    )


def _from_stat_panel(spec: dict, source_text: str) -> ChartSpec | None:
    """Two big numbers with labels — the "success percentage across arms" case."""
    pairs = []
    prim = spec.get("primary_stat")
    sec = spec.get("secondary_stat")
    if not prim or not sec:
        return None
    pairs.append((spec.get("primary_label") or "Arm 1", str(prim)))
    pairs.append((spec.get("secondary_label") or "Arm 2", str(sec)))
    verified = _verified_pairs(pairs, source_text)
    if not verified:
        return None
    unit = _unit_of(str(prim))
    vals = [v for _, _, v in verified]
    kind, note = _choose_kind(vals, unit)
    return ChartSpec(
        kind=kind,
        labels=[_short_label(lbl) for lbl, _, _ in verified],
        values=vals,
        literals=[lit for _, lit, _ in verified],
        unit=unit,
        title=sanitize(spec.get("title", "")),
        axis_note=note,
        pmids=_spec_pmids(spec),
    )


def _from_hierarchy(spec: dict, source_text: str) -> ChartSpec | None:
    """evidence_summary hierarchy rows carrying one stat each, with tiers."""
    rows = spec.get("hierarchy_rows") or []
    pairs, tiers = [], []
    for row in rows:
        if not isinstance(row, dict) or not row.get("stat"):
            continue
        pairs.append((row.get("tier_label") or row.get("description") or "",
                      str(row["stat"])))
        tiers.append(tier_key(row.get("tier_label")) or tier_key(row.get("tier")))
    if len(pairs) < 2:
        return None
    verified = _verified_pairs(pairs, source_text)
    if not verified:
        return None
    unit = _unit_of(pairs[0][1])
    vals = [v for _, _, v in verified]
    kind, note = _choose_kind(vals, unit)
    return ChartSpec(
        kind=kind,
        labels=[_short_label(lbl) for lbl, _, _ in verified],
        values=vals,
        literals=[lit for _, lit, _ in verified],
        unit=unit,
        title=sanitize(spec.get("title", "")),
        axis_note=note,
        pmids=_spec_pmids(spec),
        tier_keys=tiers if any(tiers) else None,
    )


def evidence_shape(tier_counts: dict) -> ChartSpec | None:
    """Per-tier paper counts -> the evidence-shape stacked bar.

    These counts are computed by the retrieval layer from the papers actually
    served, not read out of prose, so the verbatim rule does not apply: the
    source *is* the count. Returns None on an empty or all-zero breakdown.
    """
    if not tier_counts:
        return None
    labels, values, tiers = [], [], []
    for key in TIER_ORDER:
        n = int(tier_counts.get(key, 0) or 0)
        if n <= 0:
            continue
        from presentations.design_tokens import TIER_LABELS
        labels.append(TIER_LABELS[key])
        values.append(float(n))
        tiers.append(key)
    if not values:
        return None
    return ChartSpec(
        kind="evidence_shape",
        labels=labels,
        values=values,
        literals=[str(int(v)) for v in values],
        unit="papers",
        tier_keys=tiers,
    )


def tier_counts_from_papers(papers) -> dict:
    """Count papers per evidence tier, for the title slide's evidence shape.

    Reads `level_key` (the library's own column) and falls back to a `tier`
    field. A paper whose tier cannot be resolved is NOT guessed into a bucket —
    it is left out of the shape, so the bar under-reports rather than
    mislabels.
    """
    counts: dict[str, int] = {}
    for paper in papers or []:
        if not isinstance(paper, dict):
            continue
        key = tier_key(paper.get("level_key") or paper.get("tier")
                       or paper.get("level"))
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


def _short_label(text: str, max_words: int = 7) -> str:
    """Trim a *chart axis label* to fit the tick gutter.

    This is the one place text is shortened, and it is furniture, not content:
    an axis label is a pointer to the row, and the full sentence stays on the
    slide body and in the narration. Trimming is by whole words with an
    ellipsis so nothing reads as a rewritten claim.
    """
    words = sanitize(text).split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]) + "…"


def _spec_pmids(spec: dict) -> list[str]:
    blob = " ".join(
        str(v) for k, v in (spec or {}).items()
        if isinstance(v, str) and not k.startswith("_")
    )
    return extract_pmids(blob)


# ── public entry point ───────────────────────────────────────────────────────

_DETECTORS = (_from_explicit_chart, _from_stat_panel, _from_hierarchy)


def detect_chartable(spec: dict, source_text: str | None) -> ChartSpec | None:
    """Return a renderable ChartSpec for this slide, or None.

    `source_text` is the canonical answer/curriculum text the deck was built
    from. Without it there is nothing to verify against, so the answer is None:
    an unverifiable chart is not drawn.
    """
    if not isinstance(spec, dict) or not source_text:
        return None
    for detector in _DETECTORS:
        try:
            found = detector(spec, source_text)
        except Exception:
            found = None
        if found is not None and len(found.values) >= 2:
            return found
    return None


__all__ = [
    "ChartSpec", "detect_chartable", "evidence_shape",
    "tier_counts_from_papers",
    "verbatim_in", "parse_number",
]
