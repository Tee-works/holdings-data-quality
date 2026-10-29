"""Inline SVG charts and diagrams for the case studies.

Plain SVG, no charting library: the page stays one static file, renders the same
in print, and every colour comes from the page's CSS variables so the charts
follow the light and dark themes.
"""

from __future__ import annotations

from html import escape

from markupsafe import Markup


def _bn(v: float) -> str:
    return f"${v / 1e9:,.1f}bn"


def _svg(w: int, h: int, body: str, label: str, wide: bool = True) -> Markup:
    """Wide charts keep a readable minimum width on phones and scroll sideways instead."""
    return Markup(
        f'<div class="chart-scroll"><svg viewBox="0 0 {w} {h}" role="img" aria-label="{escape(label)}" '
        f'preserveAspectRatio="xMidYMid meet" class="chart{" wide" if wide else ""}">{body}</svg></div>'
    )


def restatement_bars(context: list[dict]) -> Markup:
    """Value as restated, with the part that was counted twice stacked on top."""
    w, h, left, right, top, bottom = 720, 330, 58, 16, 40, 46
    peak = max(c["restated"] + c["counted_twice"] for c in context)
    scale_top = 500e9 if peak <= 500e9 else peak * 1.1
    plot_w, plot_h = w - left - right, h - top - bottom
    slot = plot_w / len(context)
    bar_w = min(64, slot * 0.56)

    def y(v):
        return top + plot_h * (1 - v / scale_top)

    out = []
    out.append(
        '<defs><pattern id="hatch" width="7" height="7" patternUnits="userSpaceOnUse" '
        'patternTransform="rotate(45)"><rect width="7" height="7" class="hatch-bg"/>'
        '<line x1="0" y1="0" x2="0" y2="7" class="hatch-line"/></pattern></defs>'
    )
    for t in range(0, int(scale_top / 1e9) + 1, 100):
        ty = y(t * 1e9)
        out.append(
            f'<line x1="{left}" x2="{w - right}" y1="{ty:.1f}" y2="{ty:.1f}" class="gridline"/>'
        )
        out.append(
            f'<text x="{left - 8}" y="{ty + 4:.1f}" text-anchor="end" class="axis">${t}bn</text>'
        )
    for i, c in enumerate(context):
        cx = left + slot * (i + 0.5)
        x = cx - bar_w / 2
        base_y, dup_y = y(c["restated"]), y(c["restated"] + c["counted_twice"])
        tip = f"{c['label']}: {_bn(c['restated'])} once"
        out.append(
            f'<rect x="{x:.1f}" y="{base_y:.1f}" width="{bar_w:.1f}" height="{top + plot_h - base_y:.1f}" '
            f'rx="3" class="bar-once"/>'
        )
        if c["counted_twice"]:
            tip += f", plus {_bn(c['counted_twice'])} counted twice"
            out.append(
                f'<rect x="{x:.1f}" y="{dup_y:.1f}" width="{bar_w:.1f}" height="{base_y - dup_y:.1f}" '
                f'rx="3" fill="url(#hatch)" class="bar-twice"/>'
            )
            share = c["counted_twice"] / (c["restated"] + c["counted_twice"])
            out.append(
                f'<text x="{cx:.1f}" y="{dup_y - 18:.1f}" text-anchor="middle" class="callout">'
                f"+{_bn(c['counted_twice'])}</text>"
                f'<text x="{cx:.1f}" y="{dup_y - 5:.1f}" text-anchor="middle" class="callout-sub">'
                f"{share:.0%} of report</text>"
            )
        out.append(
            f'<rect x="{cx - slot / 2:.1f}" y="{top}" width="{slot:.1f}" height="{plot_h}" class="hit" '
            f'data-tip="{escape(tip)}"/>'
        )
        out.append(
            f'<text x="{cx:.1f}" y="{h - bottom + 20}" text-anchor="middle" class="axis-x">{c["label"]}</text>'
        )
    lx = left
    out.append(
        f'<rect x="{lx}" y="8" width="12" height="12" rx="2" class="bar-once"/>'
        f'<text x="{lx + 18}" y="18" class="legend">Reported once (as restated)</text>'
        f'<rect x="{lx + 210}" y="8" width="12" height="12" rx="2" fill="url(#hatch)" class="bar-twice"/>'
        f'<text x="{lx + 228}" y="18" class="legend">Counted twice in the original report</text>'
    )
    return _svg(
        w, h, "".join(out), "Reported value by quarter, as restated, with the part counted twice"
    )


def containment_strip(strip: list[dict], threshold: float = 95.0) -> Markup:
    """Every entity in every report: what share of its book sits inside another entity's."""
    w, h, left, right, top = 720, 190, 24, 24, 36
    plot_w = w - left - right

    def x(p):
        return left + plot_w * p / 100

    out = []
    for t in range(0, 101, 25):
        out.append(
            f'<line x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top - 6}" y2="{h - 40}" class="gridline"/>'
        )
        out.append(
            f'<text x="{x(t):.1f}" y="{h - 22}" text-anchor="middle" class="axis">{t}%</text>'
        )
    normal = [s["pct"] for s in strip if not s["is_exception"]]
    if normal:
        lo, hi = min(normal), max(normal)
        out.append(
            f'<rect x="{x(lo):.1f}" y="{top}" width="{x(hi) - x(lo):.1f}" height="{h - 40 - top - 30}" '
            f'rx="6" class="band"/>'
            f'<text x="{(x(lo) + x(hi)) / 2:.1f}" y="{top - 12}" text-anchor="middle" class="band-label">'
            f"Normal overlap between L&amp;G entities: {lo:.0f}% to {hi:.0f}%</text>"
        )
    out.append(
        f'<line x1="{x(threshold):.1f}" x2="{x(threshold):.1f}" y1="{top - 4}" y2="{h - 40}" class="threshold"/>'
        f'<text x="{x(threshold) - 6:.1f}" y="{top - 12}" text-anchor="end" class="threshold-label">C19 flags at {threshold:.0f}%</text>'
    )
    lanes = 6
    for i, s in enumerate(sorted(strip, key=lambda s: s["pct"])):
        cy = top + 12 + (i % lanes) * 13
        cls = "dot-hit" if s["is_exception"] else "dot"
        tip = f"{s['period_label']} ({s['version_role']}): {s['pct']:.1f}% of one entity's positions inside another's"
        out.append(
            f'<circle cx="{x(s["pct"]):.1f}" cy="{cy}" r="5.5" class="{cls}" data-tip="{escape(tip)}"/>'
        )
    out.append(
        f'<text x="{left}" y="{h - 4}" class="axis">Share of an entity\'s positions also reported, '
        f"with at least as many shares, under another entity in the same report</text>"
    )
    return _svg(
        w, h, "".join(out), "Containment of each entity's book inside another's, across all reports"
    )
