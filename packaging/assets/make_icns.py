#!/usr/bin/env python3
"""Claude Usage Bar — "Usage Radar" icon.

Visual language (back → front):
  1. Dark charcoal disc with a subtle lighter centre (pseudo radial gradient)
  2. Thin outer orange ring            — Claude / Anthropic brand accent
  3. 270° speedometer gauge track      — dim, full span, gap at bottom
  4. 73% filled gauge arc (orange)     — usage-level metaphor
  5. Amber end-cap dot at fill tip     — live-progress cursor
  6. Inner concentric pulse arc        — radar / real-time feel
  7. Second inner pulse arc (≥256 px)  — extra depth
  8. Centre dot + Gaussian glow halo   — active-pulse indicator

Size tiers:
  ≤ 32 px  — border ring + pulsing centre dot only (pixel-crisp)
  64–128   — full gauge + single inner arc + glow cap
  ≥ 256    — all layers + multi-ring pulse + Gaussian halos

Output: packaging/assets/icon.icns
Run:    .venv/bin/python packaging/assets/make_icns.py

Requires: pillow (already in project .venv)
"""

from __future__ import annotations

import io
import math
import struct
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:
    print("pip install pillow", file=sys.stderr)
    sys.exit(1)

OUT = Path(__file__).parent / "icon.icns"

SIZES = [16, 32, 64, 128, 256, 512, 1024]
_ICNS_TAGS = {
    16: b"icp4", 32: b"icp5", 64: b"icp6",
    128: b"ic07", 256: b"ic08", 512: b"ic09", 1024: b"ic10",
}

# ── Palette ───────────────────────────────────────────────────────────────────
BG_MAIN = (28,  28,  30, 255)   # #1C1C1E — charcoal disc
ORANGE  = (255, 149,  0, 255)   # #FF9500 — Anthropic accent
AMBER   = (255, 210,  80, 255)  # end-cap / centre highlight
DIM_ORG = (255, 149,  0,  22)   # ghost gauge track

# ── Gauge geometry ────────────────────────────────────────────────────────────
# PIL angles: 0° = East (3 o'clock), increasing clockwise in screen space.
#   GAUGE_START = 135° → 7:30 clock position (lower-left)
#   GAUGE_END   = 45°  → 4:30 clock position (lower-right)
#   PIL wraps end < start → draws the 270° arc through the top, gap at bottom.
GAUGE_START = 135
GAUGE_END   = 45
GAUGE_SPAN  = 270   # degrees of total arc
FILL_PCT    = 0.73  # 73% usage displayed on the icon


def _bbox(cx: float, cy: float, r: float) -> list[float]:
    return [cx - r, cy - r, cx + r, cy + r]


def _polar(cx: float, cy: float, r: float, deg: float) -> tuple[float, float]:
    rad = math.radians(deg)
    return cx + r * math.cos(rad), cy + r * math.sin(rad)


def _glow(rs: int, cx: float, cy: float,
          r: float, color: tuple, blur: float) -> Image.Image:
    """Return a compositable RGBA Gaussian-glow layer centred at (cx, cy)."""
    layer = Image.new("RGBA", (rs, rs), (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse(_bbox(cx, cy, r), fill=color)
    return layer.filter(ImageFilter.GaussianBlur(radius=blur))


def _render_frame(size: int) -> bytes:
    # Super-sample for crisp anti-aliasing at small sizes.
    scale = 4 if size <= 32 else (2 if size <= 128 else 1)
    rs = size * scale

    img  = Image.new("RGBA", (rs, rs), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx = cy = rs / 2
    pad = rs * 0.055
    R   = rs / 2 - pad      # disc radius

    # ── 1. Background disc ────────────────────────────────────────────────────
    draw.ellipse(_bbox(cx, cy, R), fill=BG_MAIN)

    # Pseudo radial gradient: soft lighter centre gives perceived depth.
    if size >= 64:
        img  = Image.alpha_composite(img, _glow(rs, cx, cy, R * 0.50,
                                                (65, 65, 72, 55), R * 0.38))
        draw = ImageDraw.Draw(img)

    # ── 2. Outer accent ring ──────────────────────────────────────────────────
    rw = max(1, round(rs * 0.028))
    draw.ellipse(_bbox(cx, cy, R), outline=ORANGE, width=rw)

    # ── Minimal tier (≤ 32 px) ───────────────────────────────────────────────
    if size <= 32:
        dot_r = round(R * 0.40)
        # Soft halo behind the centre dot.
        draw.ellipse(_bbox(cx, cy, round(R * 0.62)), fill=(255, 149, 0, 55))
        draw.ellipse(_bbox(cx, cy, dot_r), fill=ORANGE)
        # Small dark hole → looks like a ring indicator, not a filled blob.
        draw.ellipse(_bbox(cx, cy, round(dot_r * 0.38)), fill=BG_MAIN)

    # ── Full design (≥ 64 px) ────────────────────────────────────────────────
    else:
        gauge_r  = R * 0.72
        fill_end = (GAUGE_START + GAUGE_SPAN * FILL_PCT) % 360
        # fill_end ≈ 332° → ~2 o'clock position (upper-right)

        # ── 3. Gauge track — full 270° arc, very dim ──────────────────────────
        tw = max(2, round(rs * 0.036))
        draw.arc(_bbox(cx, cy, gauge_r),
                 start=GAUGE_START, end=GAUGE_END,
                 fill=DIM_ORG, width=tw)

        # ── 4. Gauge fill — bright orange, 73% of span ───────────────────────
        fw = max(2, round(rs * 0.056))
        draw.arc(_bbox(cx, cy, gauge_r),
                 start=GAUGE_START, end=fill_end,
                 fill=ORANGE, width=fw)

        # ── 5. Amber end-cap at live fill tip ─────────────────────────────────
        ex, ey = _polar(cx, cy, gauge_r, fill_end)
        cap_r  = max(2, round(rs * 0.037))
        # Soft glow behind the cap.
        img  = Image.alpha_composite(
            img, _glow(rs, ex, ey, cap_r * 2.8, (255, 215, 60, 85), cap_r * 1.5))
        draw = ImageDraw.Draw(img)
        draw.ellipse(_bbox(ex, ey, cap_r), fill=AMBER)

        # ── 6. Inner pulse arc — 47% radius, 80% of fill extent ──────────────
        pr        = R * 0.47
        pw        = max(1, round(rs * 0.020))
        pulse_end = (GAUGE_START + GAUGE_SPAN * FILL_PCT * 0.80) % 360
        draw.arc(_bbox(cx, cy, pr),
                 start=GAUGE_START, end=pulse_end,
                 fill=(255, 149, 0, 90), width=pw)

        # ── 7. Second inner pulse arc — 28% radius, 62% of fill ──────────────
        if size >= 256:
            pr2        = R * 0.28
            pw2        = max(1, round(rs * 0.014))
            pulse_end2 = (GAUGE_START + GAUGE_SPAN * FILL_PCT * 0.62) % 360
            draw.arc(_bbox(cx, cy, pr2),
                     start=GAUGE_START, end=pulse_end2,
                     fill=(255, 149, 0, 48), width=pw2)

        # ── 8. Centre dot + Gaussian glow halo ───────────────────────────────
        dot_r = max(2, round(R * 0.13))
        if size >= 128:
            img  = Image.alpha_composite(
                img, _glow(rs, cx, cy, dot_r * 3.5, (255, 175, 0, 95), dot_r * 1.9))
            draw = ImageDraw.Draw(img)
        else:
            draw.ellipse(_bbox(cx, cy, dot_r * 2.8), fill=(255, 149, 0, 50))
        draw.ellipse(_bbox(cx, cy, dot_r), fill=AMBER)

    # ── Downscale with Lanczos anti-aliasing if super-sampled ────────────────
    if scale > 1:
        img = img.resize((size, size), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_icns() -> None:
    chunks: list[bytes] = []
    for sz in SIZES:
        tag    = _ICNS_TAGS[sz]
        data   = _render_frame(sz)
        length = 8 + len(data)
        chunks.append(tag + struct.pack(">I", length) + data)

    body   = b"".join(chunks)
    header = b"icns" + struct.pack(">I", 8 + len(body))

    OUT.write_bytes(header + body)
    print(f"Written: {OUT}  ({OUT.stat().st_size:,} bytes)")


# ── Menu bar template PNG ─────────────────────────────────────────────────────
# macOS menu bar icons are "template images": alpha defines the shape, RGB is
# ignored — macOS paints them in the appropriate theme colour automatically.
# Standard size: 22 pt × 22 pt → 44 × 44 px at @2x Retina.

MENUBAR_OUT  = Path(__file__).parent / "menubar.png"
MENUBAR_SIZE = 44   # points × 2 (native Retina resolution)


def _render_menubar() -> bytes:
    """
    Render a 44×44 white-on-transparent template PNG for the menu bar.
    Simplified gauge: arc (73% fill) + end-cap dot + centre dot.
    No outer ring — too noisy at this scale.
    """
    rs   = MENUBAR_SIZE * 2   # super-sample at 2× for clean edges
    img  = Image.new("RGBA", (rs, rs), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx = cy = rs / 2
    pad = rs * 0.09
    R   = rs / 2 - pad

    W        = (255, 255, 255, 255)   # solid white — template image convention
    W_GHOST  = (255, 255, 255,  40)   # faint track

    gauge_r  = R * 0.76
    fill_end = (GAUGE_START + GAUGE_SPAN * FILL_PCT) % 360

    # Dim track (full 270° span)
    tw = max(1, round(rs * 0.045))
    draw.arc(_bbox(cx, cy, gauge_r),
             start=GAUGE_START, end=GAUGE_END,
             fill=W_GHOST, width=tw)

    # Bright fill arc
    fw = max(2, round(rs * 0.095))
    draw.arc(_bbox(cx, cy, gauge_r),
             start=GAUGE_START, end=fill_end,
             fill=W, width=fw)

    # End-cap dot at live fill tip
    ex, ey = _polar(cx, cy, gauge_r, fill_end)
    cap_r  = max(1, round(rs * 0.075))
    draw.ellipse(_bbox(ex, ey, cap_r), fill=W)

    # Centre dot
    dot_r = max(1, round(R * 0.22))
    draw.ellipse(_bbox(cx, cy, dot_r), fill=W)

    img = img.resize((MENUBAR_SIZE, MENUBAR_SIZE), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_menubar_png() -> None:
    data = _render_menubar()
    MENUBAR_OUT.write_bytes(data)
    print(f"Written: {MENUBAR_OUT}  ({MENUBAR_OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    build_icns()
    build_menubar_png()
