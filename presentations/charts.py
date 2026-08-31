"""
Curo — matplotlib chart rendering
==================================
Spec §1.5. Renders a verified `ChartSpec` (see chart_data.py) to a PNG on the
deck background, using the exact token hexes so a chart dropped into a slide is
indistinguishable from vector furniture.

Approved grammar, and nothing else:
  * **dot plot** for near-equal comparisons. A truncated axis is allowed only
    with the explicit axis note the detector supplies.
  * **bar** for magnitude comparisons from zero.
  * **evidence-shape stacked bar** (tier colours, 2px gaps, direct labels) for
    the paper-count breakdown.

Single-series marks use `CHART_SERIES_SINGLE` and only that. Multi-tier fills
use the ladder. Value labels are drawn in a *text* token, never in the series
colour, so a label never reads as part of the mark. Direct labels replace
legends; leader/grid lines are `leader`; axis text is `text_muted`.

matplotlib is imported lazily. If it is missing, `render_chart_png` returns
None and the caller falls back to the slide's text body — a missing chart
degrades the slide, it never breaks the deck.
"""

from __future__ import annotations

import io
import textwrap

from presentations.design_tokens import (
    COLORS, FONTS, SIZES_PX, TIER_CHART_FILL, TIER_CHART_FILL_LIGHT,
    CHART_SERIES_SINGLE, px_pt,
)

# Chart canvas, in inches, matching the body region of a content slide.
FIG_W_IN = 11.4
FIG_H_IN = 4.3
DPI = 160

_MPL_FONT = [FONTS["body"], "Segoe UI", "DejaVu Sans", "sans-serif"]


def _matplotlib():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        return plt
    except Exception:
        return None


def matplotlib_available() -> bool:
    return _matplotlib() is not None


def _fig_height(n_rows: int) -> float:
    """Canvas height for `n_rows` categories.

    Fixed-height figures make a two-bar chart render as two slabs filling the
    slide. Height tracks the row count instead, so bar thickness stays
    constant whether the chart has two rows or six.
    """
    return min(FIG_H_IN, max(1.5, 0.70 + 0.62 * max(1, n_rows)))


def _new_fig(plt, w=FIG_W_IN, h=FIG_H_IN, bg=None):
    bg = bg or COLORS["bg"]
    fig, ax = plt.subplots(figsize=(w, h), dpi=DPI)
    fig.patch.set_facecolor(bg)
    ax.set_facecolor(bg)
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    ax.tick_params(colors=COLORS["text_muted"], length=0,
                   labelsize=px_pt(SIZES_PX["axis"]))
    for lbl in ax.get_xticklabels() + ax.get_yticklabels():
        lbl.set_color(COLORS["text_muted"])
        lbl.set_fontfamily(_MPL_FONT)
    return fig, ax


def _to_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor(),
                bbox_inches="tight", pad_inches=0.12)
    import matplotlib.pyplot as plt
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _fills(chart) -> list[str]:
    if chart.tier_keys:
        return [
            TIER_CHART_FILL.get(t or "", CHART_SERIES_SINGLE)
            for t in chart.tier_keys
        ]
    return [CHART_SERIES_SINGLE] * len(chart.values)


def _wrap_labels(labels, width: int = 30) -> list[str]:
    """Wrap tick labels — matplotlib will not, and an unwrapped clinical label
    squeezes the plot area down to nothing."""
    return ["\n".join(textwrap.wrap(str(lbl), width)) or str(lbl)
            for lbl in labels]


def png_size(png_bytes: bytes) -> tuple[int, int] | None:
    """(width, height) in pixels, so a caller can fit the image to its box."""
    try:
        from PIL import Image
        with Image.open(io.BytesIO(png_bytes)) as im:
            return im.size
    except Exception:
        return None


def _fmt(literal: str, unit: str) -> str:
    if unit == "%":
        return f"{literal}%"
    if unit == "n":
        return f"n = {literal}"
    if unit:
        return f"{literal} {unit}"
    return literal


# ── bar (magnitude from zero) ────────────────────────────────────────────────

def render_bar(chart) -> bytes | None:
    plt = _matplotlib()
    if plt is None:
        return None
    fig, ax = _new_fig(plt, h=_fig_height(len(chart.values)))

    y = list(range(len(chart.values)))[::-1]
    ax.barh(y, chart.values, height=0.46, color=_fills(chart), zorder=3)

    ax.set_yticks(y)
    ax.set_yticklabels(_wrap_labels(chart.labels))
    ax.set_ylim(-0.7, len(chart.values) - 0.3)

    # A bar chart is anchored at zero — including when a value is negative
    # (effect sizes and mean differences routinely are). The axis therefore
    # spans zero to whichever end the data reaches, never just the positive
    # side, or a negative bar draws off-canvas.
    lo = min(0.0, min(chart.values))
    hi = max(0.0, max(chart.values))
    span = (hi - lo) or 1.0
    # Leave room on the negative side for the value label to sit outside the
    # bar without landing on top of the tick labels.
    ax.set_xlim(lo - span * (0.22 if lo < 0 else 0.06), hi + span * 0.26)
    if lo < 0:
        ax.axvline(0, color=COLORS["leader"], linewidth=1.0, zorder=2)
    ax.xaxis.grid(True, color=COLORS["leader"], linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.set_xticks([])

    # Direct value labels, in a text token — never the series colour.
    for yi, val, lit in zip(y, chart.values, chart.literals):
        if val < 0:
            tx, ha = val - span * 0.025, "right"
        else:
            tx, ha = val + span * 0.025, "left"
        ax.text(tx, yi, _fmt(lit, chart.unit), va="center", ha=ha,
                color=COLORS["text_body"], fontfamily=_MPL_FONT,
                fontsize=px_pt(16), fontweight="bold", zorder=4)

    _annotate(ax, chart)
    return _to_png(fig)


# ── dot plot (near-equal comparison, truncated axis + note) ──────────────────

def render_dot(chart) -> bytes | None:
    plt = _matplotlib()
    if plt is None:
        return None
    fig, ax = _new_fig(plt, h=_fig_height(len(chart.values)))

    y = list(range(len(chart.values)))[::-1]
    ax.set_ylim(-0.7, len(chart.values) - 0.3)
    lo, hi = min(chart.values), max(chart.values)
    span = (hi - lo) or (abs(hi) * 0.1 or 1.0)
    left = lo - span * 0.9
    right = hi + span * 1.4

    # Leader lines run from the axis to each dot, so the eye reads position.
    for yi, val in zip(y, chart.values):
        ax.plot([left, val], [yi, yi], color=COLORS["leader"],
                linewidth=1.0, zorder=2)
    ax.scatter(chart.values, y, s=190, color=_fills(chart), zorder=3,
               edgecolors=COLORS["bg"], linewidths=1.5)

    ax.set_yticks(y)
    ax.set_yticklabels(_wrap_labels(chart.labels))
    ax.set_xlim(left, right)
    ax.set_xticks([])

    for yi, val, lit in zip(y, chart.values, chart.literals):
        ax.text(val + span * 0.10, yi, _fmt(lit, chart.unit),
                va="center", ha="left",
                color=COLORS["text_body"], fontfamily=_MPL_FONT,
                fontsize=px_pt(16), fontweight="bold", zorder=4)

    _annotate(ax, chart, require_axis_note=True)
    return _to_png(fig)


# ── evidence-shape stacked bar ───────────────────────────────────────────────

def render_evidence_shape(chart, *, on_light_card: bool = False,
                          width_in: float = 11.4,
                          height_in: float = 1.30) -> bytes | None:
    """One horizontal stacked bar of tier segments with direct labels.

    `on_light_card=True` renders on the title slide's `#fcfcfd` card and uses
    the light-surface ladder, which is the set that passed the CVD validator.
    """
    plt = _matplotlib()
    if plt is None:
        return None
    bg = COLORS["light_card"] if on_light_card else COLORS["bg"]
    ladder = TIER_CHART_FILL_LIGHT if on_light_card else TIER_CHART_FILL
    ink = COLORS["light_card_ink"] if on_light_card else COLORS["text_body"]

    fig, ax = _new_fig(plt, w=width_in, h=height_in, bg=bg)
    ax.set_xticks([])
    ax.set_yticks([])

    total = sum(chart.values) or 1.0
    # 2px gaps at the spec's 1280px frame, expressed in data units.
    gap = total * (2.0 / 1280.0) * (1280.0 / (width_in * 96.0)) if width_in else 0
    x = 0.0
    for value, tier, label, lit in zip(
            chart.values, chart.tier_keys or [], chart.labels, chart.literals):
        w = max(value - gap, value * 0.4)
        ax.barh([0], [w], left=x, height=0.9,
                color=ladder.get(tier or "", CHART_SERIES_SINGLE), zorder=3)
        # Direct label inside the segment when it is wide enough to hold it.
        if w / total > 0.10:
            ax.text(x + w / 2, 0, lit, va="center", ha="center",
                    color=bg, fontfamily=_MPL_FONT,
                    fontsize=px_pt(13), fontweight="bold", zorder=4)
        x += value + gap

    ax.set_xlim(0, x)
    ax.set_ylim(-0.6, 0.6)
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.95, bottom=0.05)
    _ = ink
    return _to_png(fig)


def _annotate(ax, chart, *, require_axis_note: bool = False) -> None:
    """Axis note (mandatory on a truncated axis) and the unit caption."""
    note = chart.axis_note
    if require_axis_note and not note:
        note = "axis truncated"
    if note:
        ax.text(0.0, -0.14, note, transform=ax.transAxes,
                color=COLORS["text_muted"], fontfamily=_MPL_FONT,
                fontsize=px_pt(SIZES_PX["axis"]), ha="left", va="top")


_RENDERERS = {
    "bar": render_bar,
    "dot": render_dot,
    "evidence_shape": render_evidence_shape,
}


def render_chart_png(chart) -> bytes | None:
    """Render a verified ChartSpec to PNG bytes, or None if it cannot be drawn.

    Returning None is a normal outcome (matplotlib missing, unknown grammar) —
    the caller must fall back to text, never to a fabricated figure.
    """
    if chart is None:
        return None
    fn = _RENDERERS.get(chart.kind)
    if fn is None:
        return None
    try:
        return fn(chart)
    except Exception:
        return None


__all__ = [
    "render_chart_png", "render_bar", "render_dot", "render_evidence_shape",
    "matplotlib_available",
]
