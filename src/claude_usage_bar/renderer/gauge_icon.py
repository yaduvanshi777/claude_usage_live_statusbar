"""Dynamic gauge icon — Pillow-based, writes to temp PNG on every tick.

Same visual language as packaging/assets/make_icns.py:
  - 270° arc, gap at bottom
  - GAUGE_START=135° (lower-left, 7:30 o'clock)
  - GAUGE_END=45°   (lower-right, 4:30 o'clock)
  - fill_end = (GAUGE_START + GAUGE_SPAN * fill_pct) % 360
  - PIL convention: 0°=east, angles increase clockwise in screen space;
    end < start → PIL draws the longer 270° path through the top.

Colour states (driven by fill_pct):
  NORMAL (< 80%)  — white on transparent, set as macOS template image
  AMBER  (80–99%) — orange #FF9500, non-template (forces visible colour)
  RED    (≥ 100%) — red   #FF3B30, non-template

Two alternating temp-file paths are used so rumps always detects a
change in the icon path and reloads the PNG from disk every tick.
"""

from __future__ import annotations

import io
import math
import tempfile
from enum import Enum
from pathlib import Path

from PIL import Image, ImageDraw

# ── Geometry (matches make_icns.py) ──────────────────────────────────────────
_SIZE        = 44          # 22 pt @2× Retina
_CX          = _SIZE / 2
_CY          = _SIZE / 2
_PAD         = _SIZE * 0.09
_R           = _SIZE / 2 - _PAD
_GAUGE_R     = _R * 0.76
_GAUGE_START = 135
_GAUGE_END   = 45
_GAUGE_SPAN  = 270
_TRACK_W     = max(1, round(_SIZE * 0.045))
_FILL_W      = max(2, round(_SIZE * 0.095))
_CAP_R       = max(1, round(_SIZE * 0.075))
_DOT_R       = max(1, round(_R * 0.22))

# ── Alternating temp-file paths (forces rumps to reload on each tick) ─────────
_TMP = [
    Path(tempfile.gettempdir()) / "claude-usage-bar-gauge-0.png",
    Path(tempfile.gettempdir()) / "claude-usage-bar-gauge-1.png",
]
_tick = 0   # module-level alternator


class GaugeState(Enum):
    NORMAL = "normal"   # white template image
    AMBER  = "amber"    # orange, non-template (only when budget explicitly set)
    RED    = "red"      # red,    non-template (only when budget explicitly set)


def gauge_state_for(fill_pct: float, budget_active: bool) -> GaugeState:
    """
    AMBER/RED only when the user has set budget_daily_usd > 0.
    Without an explicit budget the gauge stays white — purely informational.
    """
    if budget_active:
        if fill_pct >= 1.0:
            return GaugeState.RED
        if fill_pct >= 0.8:
            return GaugeState.AMBER
    return GaugeState.NORMAL


def render_gauge(fill_pct: float, budget_active: bool = False) -> tuple[str, GaugeState]:
    """
    Draw a 44×44 gauge PNG and return (path, GaugeState).

    fill_pct: 0.0 = empty, 1.0 = full budget / reference.
    budget_active: True only when user has set budget_daily_usd > 0.
    Caller uses the returned state to set template=True/False on the rumps app.
    """
    global _tick

    state    = gauge_state_for(fill_pct, budget_active)
    draw_pct = max(0.0, min(1.0, fill_pct))

    # Colour palette per state
    if state == GaugeState.RED:
        fg    = (255,  59,  48, 255)   # #FF3B30
        track = (255,  59,  48,  50)
    elif state == GaugeState.AMBER:
        fg    = (255, 149,   0, 255)   # #FF9500
        track = (255, 149,   0,  50)
    else:
        fg    = (255, 255, 255, 255)   # white (template)
        track = (255, 255, 255,  40)

    img  = Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def bbox(r: float) -> list[float]:
        return [_CX - r, _CY - r, _CX + r, _CY + r]

    def polar(r: float, deg: float) -> tuple[float, float]:
        rad = math.radians(deg)
        return _CX + r * math.cos(rad), _CY + r * math.sin(rad)

    # ── Background track (full 270° arc) ──────────────────────────────────────
    draw.arc(bbox(_GAUGE_R), start=_GAUGE_START, end=_GAUGE_END,
             fill=track, width=_TRACK_W)

    # ── Filled arc ────────────────────────────────────────────────────────────
    if draw_pct > 0.005:
        fill_end = (_GAUGE_START + _GAUGE_SPAN * draw_pct) % 360
        draw.arc(bbox(_GAUGE_R), start=_GAUGE_START, end=fill_end,
                 fill=fg, width=_FILL_W)

        # End-cap dot at fill tip
        ex, ey = polar(_GAUGE_R, fill_end)
        draw.ellipse(
            [ex - _CAP_R, ey - _CAP_R, ex + _CAP_R, ey + _CAP_R],
            fill=fg,
        )

    # ── Centre dot ────────────────────────────────────────────────────────────
    draw.ellipse(
        [_CX - _DOT_R, _CY - _DOT_R, _CX + _DOT_R, _CY + _DOT_R],
        fill=fg,
    )

    # ── Write to alternating temp file ────────────────────────────────────────
    path = _TMP[_tick % 2]
    _tick += 1
    img.save(str(path), "PNG")
    return str(path), state
