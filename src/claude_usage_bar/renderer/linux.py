"""Linux/Windows system tray renderer using pystray.

pystray works on Linux (via AppIndicator/GTK) and Windows (via win32api).
It does not require a persistent main-thread event loop like rumps does,
so we drive updates from a background polling thread.

Install: pip install pystray pillow
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from datetime import date, datetime
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

try:
    import pystray
    from PIL import Image, ImageDraw
    _PYSTRAY_AVAILABLE = True
except ImportError:
    _PYSTRAY_AVAILABLE = False

from claude_usage_bar.config import AppConfig, CONFIG_PATH, write_default_config

if TYPE_CHECKING:
    from claude_usage_bar.app import UsageBarApp


def _require_pystray() -> None:
    if not _PYSTRAY_AVAILABLE:
        logger.error(
            "pystray and Pillow are required for Linux/Windows: "
            "pip install pystray pillow"
        )
        sys.exit(1)


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def _fmt_cost(usd: float) -> str:
    return f"${usd:.2f}"


def _compute_burn_rate_label(cost_usd: float, cfg) -> str:
    now = datetime.now()
    elapsed_minutes = now.hour * 60 + now.minute
    if elapsed_minutes < cfg.display.min_burn_rate_minutes:
        return "Burn rate: (collecting data…)"
    hourly = cost_usd / (elapsed_minutes / 60.0)
    daily = cost_usd / (elapsed_minutes / (60.0 * 24))
    label = f"Burn rate: {_fmt_cost(hourly)}/hr → {_fmt_cost(daily)}/day"
    if cfg.display.budget_daily_usd > 0:
        pct = (daily / cfg.display.budget_daily_usd) * 100
        label += f"  ({pct:.0f}% of budget)"
    return label


def _make_icon_image(color: str = "#4A90D9") -> "Image.Image":
    """Generate a simple 64×64 status icon. Replace with a proper .png for production."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Draw a simple "C" shape to represent Claude
    draw.ellipse([4, 4, 60, 60], outline=color, width=8)
    draw.rectangle([32, 4, 64, 60], fill=(0, 0, 0, 0))  # cut right half
    return img


class SystemTrayRenderer:
    """
    pystray-based system tray renderer for Linux and Windows.

    pystray menus are rebuilt on each update — pystray doesn't support
    mutating menu items in place. We rebuild the full menu every
    `refresh_interval_seconds` seconds on a background thread.
    """

    def __init__(self, app: "UsageBarApp") -> None:
        _require_pystray()
        self._app = app
        self._icon: "pystray.Icon | None" = None
        self._stop_event = threading.Event()

    def run(self) -> None:
        """Start the tray icon. Blocks until quit."""
        icon_image = _make_icon_image()
        self._icon = pystray.Icon(
            name="claude-usage-bar",
            icon=icon_image,
            title="Claude Usage",
            menu=self._build_menu(),
        )

        # Background thread drives periodic menu/title refresh
        updater = threading.Thread(target=self._update_loop, daemon=True, name="tray-updater")
        updater.start()

        self._icon.run()

    def _update_loop(self) -> None:
        while not self._stop_event.wait(
            timeout=self._app.config.display.refresh_interval_seconds
        ):
            if self._icon is None:
                continue
            try:
                snap = self._app.get_snapshot()
                rl = self._app.get_rate_limits()
                cfg = self._app.config

                today = snap.today
                # Update title (tooltip on Linux/Windows)
                if cfg.display.format == "cost":
                    title = f"Claude: {_fmt_cost(today.cost_usd)}"
                elif cfg.display.format == "tokens":
                    title = f"Claude: {_fmt_tokens(today.total_tokens)} tok"
                else:
                    title = f"Claude: {_fmt_cost(today.cost_usd)} | {_fmt_tokens(today.total_tokens)} tok"

                self._icon.title = title
                self._icon.menu = self._build_menu()
            except Exception as e:
                logger.debug("Tray update error: %s", e)

    def _build_menu(self) -> "pystray.Menu":
        snap = self._app.get_snapshot()
        rl = self._app.get_rate_limits()
        cfg = self._app.config
        today = snap.today

        items: list[pystray.MenuItem] = []

        # ── Today ──────────────────────────────────────────────────
        items.append(pystray.MenuItem("── Today ──", None, enabled=False))
        items.append(pystray.MenuItem(
            f"Tokens:    {today.total_tokens:,}"
            f"  (in: {_fmt_tokens(today.input_tokens)}"
            f"  out: {_fmt_tokens(today.output_tokens)}"
            f"  cache: {_fmt_tokens(today.cache_read_tokens + today.cache_write_tokens)})",
            None, enabled=False,
        ))
        items.append(pystray.MenuItem(
            f"Cost:      {_fmt_cost(today.cost_usd)}", None, enabled=False
        ))
        items.append(pystray.MenuItem(
            f"Requests:  {today.requests:,}", None, enabled=False
        ))
        items.append(pystray.MenuItem(
            f"Active:    {snap.active_sessions} session{'s' if snap.active_sessions != 1 else ''}",
            None, enabled=False,
        ))

        # Cache savings
        calc = self._app.get_cost_calculator()
        savings = sum(
            calc.compute_savings(model, ms)
            for model, ms in snap.today_by_model.items()
        )
        items.append(pystray.MenuItem(
            f"Cache saved: {_fmt_cost(savings)}", None, enabled=False
        ))

        # Burn rate
        items.append(pystray.MenuItem(
            _compute_burn_rate_label(today.cost_usd, cfg), None, enabled=False
        ))
        items.append(pystray.Menu.SEPARATOR)

        # ── Week / Month ────────────────────────────────────────────
        w = snap.week
        items.append(pystray.MenuItem(
            f"This week:  {_fmt_tokens(w.total_tokens)} tok  {_fmt_cost(w.cost_usd)}",
            None, enabled=False,
        ))
        m = snap.month
        items.append(pystray.MenuItem(
            f"This month: {_fmt_tokens(m.total_tokens)} tok  {_fmt_cost(m.cost_usd)}",
            None, enabled=False,
        ))
        items.append(pystray.Menu.SEPARATOR)

        # ── By Project ──────────────────────────────────────────────
        items.append(pystray.MenuItem("── By Project (today) ──", None, enabled=False))
        sorted_projects = sorted(
            snap.today_by_project.items(),
            key=lambda kv: kv[1].cost_usd,
            reverse=True,
        )
        for proj_name, ms in sorted_projects[:5]:
            items.append(pystray.MenuItem(
                f"  {proj_name[:28]:<28} {_fmt_cost(ms.cost_usd)} | {_fmt_tokens(ms.total_tokens)} tok",
                None, enabled=False,
            ))
        items.append(pystray.Menu.SEPARATOR)

        # ── By Model ────────────────────────────────────────────────
        items.append(pystray.MenuItem("── By Model (today) ──", None, enabled=False))
        sorted_models = sorted(
            snap.today_by_model.items(),
            key=lambda kv: kv[1].cost_usd,
            reverse=True,
        )
        for model_name, ms in sorted_models:
            if model_name in ("<synthetic>", "_unknown"):
                continue
            display_name = model_name.removeprefix("claude-")
            # Strip date suffix
            parts = display_name.rsplit("-", 1)
            if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 8:
                display_name = parts[0]
            items.append(pystray.MenuItem(
                f"  {display_name:<28} {_fmt_cost(ms.cost_usd)} | {_fmt_tokens(ms.total_tokens)} tok",
                None, enabled=False,
            ))
        items.append(pystray.Menu.SEPARATOR)

        # ── Rate Limits ─────────────────────────────────────────────
        if rl and cfg.display.show_rate_limits:
            items.append(pystray.MenuItem("── Rate Limits ──", None, enabled=False))
            items.append(pystray.MenuItem(
                f"Tokens/min: {rl.tokens_pct_used * 100:.0f}% used", None, enabled=False
            ))
            items.append(pystray.MenuItem(
                f"Reqs/min:   {rl.requests_pct_used * 100:.0f}% used", None, enabled=False
            ))
            items.append(pystray.Menu.SEPARATOR)

        # ── Actions ─────────────────────────────────────────────────
        items.append(pystray.MenuItem("Refresh Now", self._on_refresh))
        items.append(pystray.MenuItem("Open Config…", self._on_open_config))
        items.append(pystray.MenuItem("Quit", self._on_quit))

        return pystray.Menu(*items)

    def _on_refresh(self, icon, item) -> None:
        self._app.force_rescan()

    def _on_open_config(self, icon, item) -> None:
        if not CONFIG_PATH.exists():
            write_default_config()
        if sys.platform == "win32":
            subprocess.Popen(["notepad", str(CONFIG_PATH)])
        else:
            # Linux: try xdg-open, fall back to $EDITOR
            subprocess.Popen(["xdg-open", str(CONFIG_PATH)])

    def _on_quit(self, icon, item) -> None:
        self._stop_event.set()
        self._app.shutdown()
        icon.stop()
