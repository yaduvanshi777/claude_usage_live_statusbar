#!/usr/bin/env python3
"""
Generate Claude Usage Bar.icns from scratch using only stdlib + Pillow.

Output: packaging/assets/icon.icns
Run:    python3 packaging/assets/make_icns.py

Requires: pip install pillow
"""

from __future__ import annotations

import struct
import io
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("pip install pillow", file=sys.stderr)
    sys.exit(1)

OUT = Path(__file__).parent / "icon.icns"

# ICNS sizes required for Retina + standard display
SIZES = [16, 32, 64, 128, 256, 512, 1024]

# OSType tags for each pixel size
_ICNS_TAGS = {
    16:   b"icp4",
    32:   b"icp5",
    64:   b"icp6",
    128:  b"ic07",
    256:  b"ic08",
    512:  b"ic09",
    1024: b"ic10",
}


def _render_frame(size: int) -> bytes:
    """Render one PNG frame at the given pixel size."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = max(2, size // 12)
    r = size - pad * 2

    # Background circle — dark charcoal
    draw.ellipse([pad, pad, pad + r, pad + r], fill="#1C1C1E")

    # Accent ring — Claude orange/amber
    ring = max(1, size // 20)
    draw.ellipse([pad, pad, pad + r, pad + r], outline="#FF9500", width=ring)

    # "C" letterform — white, centred
    cx, cy = size // 2, size // 2
    cr = int(r * 0.30)
    lw = max(1, size // 16)
    gap_angle = 60  # degrees of gap on the right side

    # PIL arc: angles measured clockwise from 3-o'clock
    draw.arc(
        [cx - cr, cy - cr, cx + cr, cy + cr],
        start=gap_angle // 2,
        end=360 - gap_angle // 2,
        fill="white",
        width=lw,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_icns() -> None:
    chunks: list[bytes] = []
    for sz in SIZES:
        tag = _ICNS_TAGS[sz]
        data = _render_frame(sz)
        # Each ICNS chunk: 4-byte OSType + 4-byte length (including header)
        length = 8 + len(data)
        chunks.append(tag + struct.pack(">I", length) + data)

    body = b"".join(chunks)
    # ICNS file header: magic + total file length
    header = b"icns" + struct.pack(">I", 8 + len(body))

    OUT.write_bytes(header + body)
    print(f"Written: {OUT}  ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    build_icns()
