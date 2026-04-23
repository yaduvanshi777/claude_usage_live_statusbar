"""Dynamic gauge icon rendered in-memory for the macOS menu bar.

Draws a circular arc gauge using Core Graphics (via ctypes) — no temp files,
no Pillow dependency at runtime, no disk I/O on every tick.

Arc geometry (matches make_icns.py):
    Start: 135° (south-west)   End: 45° (south-east)   Span: 270°
    0% fill → empty arc        100% fill → full arc

Colour states:
    NORMAL  (0–79%)  — white template image, macOS adapts to light/dark
    AMBER   (80–99%) — orange  #FF9500, non-template (forces colour)
    RED     (≥100%)  — red     #FF3B30, non-template

The returned NSImage has pixel size 44×44 (22 pt @ 2×) to match the
standard macOS menu bar icon slot.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import math
from enum import Enum

# ── Gauge geometry ────────────────────────────────────────────────────────────
_SIZE        = 44      # pixels (22 pt @ 2× Retina)
_STROKE      = 4.5     # arc stroke width
_RADIUS      = 16.0    # arc centre-radius
_CX          = _SIZE / 2
_CY          = _SIZE / 2
_START_DEG   = 135.0   # start angle (south-west), measured from +X axis CCW
_SPAN_DEG    = 270.0   # total arc span


class GaugeState(Enum):
    NORMAL = "normal"   # white template
    AMBER  = "amber"    # orange, non-template
    RED    = "red"      # red, non-template


def _pct_to_state(fill_pct: float) -> GaugeState:
    if fill_pct >= 1.0:
        return GaugeState.RED
    if fill_pct >= 0.8:
        return GaugeState.AMBER
    return GaugeState.NORMAL


# ── Lazy-loaded ObjC bridge ───────────────────────────────────────────────────
_objc: ctypes.CDLL | None = None
_cg:   ctypes.CDLL | None = None


def _load_libs() -> tuple[ctypes.CDLL, ctypes.CDLL]:
    global _objc, _cg
    if _objc is None:
        _objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        _objc.objc_getClass.restype = ctypes.c_void_p
        _objc.sel_registerName.restype = ctypes.c_void_p
        _objc.objc_msgSend.restype = ctypes.c_void_p
        _objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    if _cg is None:
        _cg = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreGraphics"))
    return _objc, _cg


def _sel(name: str) -> ctypes.c_void_p:
    objc, _ = _load_libs()
    return objc.sel_registerName(name.encode())


def _cls(name: str) -> ctypes.c_void_p:
    objc, _ = _load_libs()
    return objc.objc_getClass(name.encode())


def _msg(receiver, selector, *args):
    objc, _ = _load_libs()
    # Build the variadic call: each extra arg can be void_p or double
    argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [
        ctypes.c_double if isinstance(a, float) else ctypes.c_void_p for a in args
    ]
    objc.objc_msgSend.argtypes = argtypes
    return objc.objc_msgSend(receiver, selector, *args)


# ── Public API ────────────────────────────────────────────────────────────────

def render_gauge_nsimage(fill_pct: float) -> tuple[object, GaugeState]:
    """
    Render a 44×44 gauge arc into an NSImage and return (nsimage_ptr, GaugeState).

    Caller (macos.py) sets rumps app.icon = nsimage_ptr and app.template
    based on the returned state.
    """
    state = _pct_to_state(fill_pct)
    fill_pct = max(0.0, min(1.0, fill_pct))

    try:
        return _render_cg(fill_pct, state), state
    except Exception:
        # Graceful fallback — return None so caller keeps the existing icon
        return None, state


def _render_cg(fill_pct: float, state: GaugeState) -> object:
    """Draw using Core Graphics + NSImage."""
    objc, cg = _load_libs()

    size_struct = (ctypes.c_double * 2)(_SIZE, _SIZE)

    # NSImage alloc/initWithSize:
    NSImage = _cls("NSImage")
    img = _msg(NSImage, _sel("alloc"))

    # initWithSize: takes NSSize (two doubles)
    objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_double, ctypes.c_double]
    objc.objc_msgSend.restype = ctypes.c_void_p
    img = objc.objc_msgSend(img, _sel("initWithSize:"), ctypes.c_double(_SIZE), ctypes.c_double(_SIZE))

    # lockFocus / unlockFocus
    objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    objc.objc_msgSend.restype = ctypes.c_void_p
    _msg(img, _sel("lockFocus"))

    # Get current CGContext
    NSGraphicsContext = _cls("NSGraphicsContext")
    objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    objc.objc_msgSend.restype = ctypes.c_void_p
    gctx = objc.objc_msgSend(NSGraphicsContext, _sel("currentContext"))

    # CGContext from NSGraphicsContext
    objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    objc.objc_msgSend.restype = ctypes.c_void_p
    cgctx = objc.objc_msgSend(gctx, _sel("CGContext"))

    _draw_gauge(cg, cgctx, fill_pct, state)

    objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    objc.objc_msgSend.restype = ctypes.c_void_p
    _msg(img, _sel("unlockFocus"))

    return img


def _draw_gauge(cg, ctx, fill_pct: float, state: GaugeState) -> None:
    """Draw background track + filled arc into ctx."""
    # Colours
    if state == GaugeState.NORMAL:
        fg = (1.0, 1.0, 1.0, 1.0)    # white (template)
        track = (1.0, 1.0, 1.0, 0.25)
    elif state == GaugeState.AMBER:
        fg = (1.0, 0.584, 0.0, 1.0)  # #FF9500 orange
        track = (1.0, 0.584, 0.0, 0.25)
    else:
        fg = (1.0, 0.231, 0.188, 1.0) # #FF3B30 red
        track = (1.0, 0.231, 0.188, 0.25)

    # CGContextSetLineWidth
    cg.CGContextSetLineWidth(ctx, ctypes.c_double(_STROKE))
    cg.CGContextSetLineCap(ctx, ctypes.c_int(1))  # kCGLineCapRound

    # Track arc (full 270°)
    _set_stroke_color(cg, ctx, *track)
    _add_arc(cg, ctx, _CX, _CY, _RADIUS, _START_DEG, _START_DEG - _SPAN_DEG, clockwise=True)
    cg.CGContextStrokePath(ctx)

    # Fill arc
    if fill_pct > 0.005:
        fill_deg = _SPAN_DEG * fill_pct
        _set_stroke_color(cg, ctx, *fg)
        _add_arc(cg, ctx, _CX, _CY, _RADIUS, _START_DEG, _START_DEG - fill_deg, clockwise=True)
        cg.CGContextStrokePath(ctx)

    # Centre dot
    _set_fill_color(cg, ctx, *fg)
    dot_r = 2.5
    cg.CGContextFillEllipseInRect(
        ctx,
        ctypes.c_double(_CX - dot_r), ctypes.c_double(_CY - dot_r),
        ctypes.c_double(dot_r * 2), ctypes.c_double(dot_r * 2),
    )


def _set_stroke_color(cg, ctx, r, g, b, a):
    cg.CGContextSetRGBStrokeColor(
        ctx,
        ctypes.c_double(r), ctypes.c_double(g),
        ctypes.c_double(b), ctypes.c_double(a),
    )


def _set_fill_color(cg, ctx, r, g, b, a):
    cg.CGContextSetRGBFillColor(
        ctx,
        ctypes.c_double(r), ctypes.c_double(g),
        ctypes.c_double(b), ctypes.c_double(a),
    )


def _deg_to_rad(deg: float) -> float:
    return deg * math.pi / 180.0


def _add_arc(cg, ctx, cx, cy, r, start_deg, end_deg, *, clockwise: bool) -> None:
    cg.CGContextAddArc(
        ctx,
        ctypes.c_double(cx), ctypes.c_double(cy),
        ctypes.c_double(r),
        ctypes.c_double(_deg_to_rad(start_deg)),
        ctypes.c_double(_deg_to_rad(end_deg)),
        ctypes.c_int(1 if clockwise else 0),
    )
