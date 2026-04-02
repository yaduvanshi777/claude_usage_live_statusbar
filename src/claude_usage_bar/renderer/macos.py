"""macOS menu bar renderer using rumps.

Layout:
    Title:  ⬛ $1.24 | 1.2M tok

    ── Today ──────────────────────────────
    Tokens:      1,247,891  (in: 42k  out: 89k  cache: 1.1M)
    Cost:        $1.24
    Requests:    847
    Active now:  3 sessions

    ── This Week ──────────────────────────
    Tokens:      8.4M   Cost: $9.12

    ── This Month ─────────────────────────
    Tokens:      24.1M  Cost: $31.44

    ── By Model (today) ───────────────────
    claude-sonnet-4-6       $1.01 | 893k tok
    claude-haiku-4-5        $0.23 | 354k tok

    ── Rate Limits ────────────────────────
    Tokens/min:  ████████░░  78%
    Reqs/min:    ████░░░░░░  42%
    ───────────────────────────────────────
    Refresh Now
    Open Config...
    Quit
"""

from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import rumps

from claude_usage_bar.config import AppConfig, write_default_config, CONFIG_PATH
from claude_usage_bar.metrics.aggregator import AggregatorSnapshot, ModelStats

if TYPE_CHECKING:
    from claude_usage_bar.app import UsageBarApp

logger = logging.getLogger(__name__)

_BAR_FILL = "█"
_BAR_EMPTY = "░"
_BAR_WIDTH = 10


def _bar(pct: float) -> str:
    filled = round(pct * _BAR_WIDTH)
    return _BAR_FILL * filled + _BAR_EMPTY * (_BAR_WIDTH - filled)


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def _fmt_cost(usd: float) -> str:
    return f"${usd:.2f}"


class MenuBarRenderer(rumps.App):
    """
    rumps.App subclass that owns the menu bar lifecycle.
    Refreshes the title and menu items on a timer.
    """

    def __init__(self, app: UsageBarApp) -> None:
        super().__init__(
            name="Claude Usage",
            title="⬛ loading…",
            quit_button=None,  # We add our own Quit item
        )
        self._app = app
        self._build_menu()

    # ------------------------------------------------------------------
    # Menu structure
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        self.menu.clear()

        # Today section
        self._today_tokens = rumps.MenuItem("Tokens: —")
        self._today_cost = rumps.MenuItem("Cost: —")
        self._today_requests = rumps.MenuItem("Requests: —")
        self._today_sessions = rumps.MenuItem("Active now: —")

        # Week / Month
        self._week_line = rumps.MenuItem("This week: —")
        self._month_line = rumps.MenuItem("This month: —")

        # Model breakdown (dynamic — rebuilt on each refresh)
        self._model_items: list[rumps.MenuItem] = []

        # Rate limits
        self._rl_tokens = rumps.MenuItem("Tokens/min: —")
        self._rl_requests = rumps.MenuItem("Reqs/min: —")

        self.menu = [
            rumps.MenuItem("── Today ──────────────────────────────"),
            self._today_tokens,
            self._today_cost,
            self._today_requests,
            self._today_sessions,
            None,  # separator
            self._week_line,
            self._month_line,
            None,
            rumps.MenuItem("── By Model (today) ───────────────────"),
            None,
            rumps.MenuItem("── Rate Limits ────────────────────────"),
            self._rl_tokens,
            self._rl_requests,
            None,
            rumps.MenuItem("Refresh Now", callback=self._on_refresh),
            rumps.MenuItem("Open Config…", callback=self._on_open_config),
            rumps.MenuItem("Quit", callback=self._on_quit),
        ]

    # ------------------------------------------------------------------
    # Timer-driven refresh
    # ------------------------------------------------------------------

    @rumps.timer(2)
    def _tick(self, _sender) -> None:
        snapshot = self._app.get_snapshot()
        rl = self._app.get_rate_limits()
        self._render(snapshot, rl)

    def _render(self, snap: AggregatorSnapshot, rl) -> None:
        cfg: AppConfig = self._app.config
        today = snap.today

        # ── Title bar ───────────────────────────────────────────────
        if cfg.display.format == "cost":
            self.title = f"⬛ {_fmt_cost(today.cost_usd)}"
        elif cfg.display.format == "tokens":
            self.title = f"⬛ {_fmt_tokens(today.total_tokens)} tok"
        else:
            self.title = f"⬛ {_fmt_cost(today.cost_usd)} | {_fmt_tokens(today.total_tokens)} tok"

        # ── Today section ───────────────────────────────────────────
        self._today_tokens.title = (
            f"Tokens:     {today.total_tokens:,}"
            f"  (in: {_fmt_tokens(today.input_tokens)}"
            f"  out: {_fmt_tokens(today.output_tokens)}"
            f"  cache: {_fmt_tokens(today.cache_read_tokens + today.cache_write_tokens)})"
        )
        self._today_cost.title = f"Cost:       {_fmt_cost(today.cost_usd)}"
        self._today_requests.title = f"Requests:   {today.requests:,}"
        self._today_sessions.title = f"Active now: {snap.active_sessions} session{'s' if snap.active_sessions != 1 else ''}"

        # ── Week / Month ─────────────────────────────────────────────
        w = snap.week
        self._week_line.title = (
            f"This week:   {_fmt_tokens(w.total_tokens)} tok  {_fmt_cost(w.cost_usd)}"
        )
        m = snap.month
        self._month_line.title = (
            f"This month:  {_fmt_tokens(m.total_tokens)} tok  {_fmt_cost(m.cost_usd)}"
        )

        # ── By Model ─────────────────────────────────────────────────
        # Rebuild model section — insert after the section header.
        # We rely on the fact that rumps menus are ordered dicts.
        # Remove old model items, insert fresh ones.
        for item in self._model_items:
            del self.menu[item.title]
        self._model_items = []

        model_section_key = "── By Model (today) ───────────────────"
        sorted_models = sorted(
            snap.today_by_model.items(),
            key=lambda kv: kv[1].cost_usd,
            reverse=True,
        )
        # Insert items after the section header
        insert_after = model_section_key
        for model_name, ms in sorted_models:
            if model_name in ("<synthetic>", "_unknown"):
                continue
            display_name = _shorten_model(model_name)
            label = f"  {display_name:<32} {_fmt_cost(ms.cost_usd)} | {_fmt_tokens(ms.total_tokens)} tok"
            item = rumps.MenuItem(label)
            self.menu.insert_after(insert_after, item)
            self._model_items.append(item)
            insert_after = label

        # ── Rate Limits ──────────────────────────────────────────────
        if rl and cfg.display.show_rate_limits:
            tok_pct = rl.tokens_pct_used
            req_pct = rl.requests_pct_used
            self._rl_tokens.title = (
                f"Tokens/min:  {_bar(tok_pct)}  {tok_pct * 100:.0f}%"
            )
            self._rl_requests.title = (
                f"Reqs/min:    {_bar(req_pct)}  {req_pct * 100:.0f}%"
            )
        else:
            self._rl_tokens.title = "Rate limits: (set API key in config)"
            self._rl_requests.title = ""

    # ------------------------------------------------------------------
    # Menu callbacks
    # ------------------------------------------------------------------

    def _on_refresh(self, _sender) -> None:
        self._app.force_rescan()

    def _on_open_config(self, _sender) -> None:
        if not CONFIG_PATH.exists():
            write_default_config()
        subprocess.Popen(["open", str(CONFIG_PATH)])

    def _on_quit(self, _sender) -> None:
        self._app.shutdown()
        # Disable the LaunchAgent before exiting so launchd doesn't respawn us.
        # KeepAlive=true means launchd restarts on any exit — unloading prevents that.
        _unload_launch_agent()
        rumps.quit_application()


def _unload_launch_agent() -> None:
    """Unload the LaunchAgent so launchd stops respawning after Quit."""
    plist = Path.home() / "Library" / "LaunchAgents" / "com.claude-usage-bar.plist"
    if plist.exists():
        try:
            subprocess.run(
                ["launchctl", "unload", str(plist)],
                capture_output=True,
                timeout=3,
            )
        except Exception:
            pass  # Non-fatal — process is exiting anyway


def _shorten_model(name: str) -> str:
    """Shorten model names for display: 'claude-sonnet-4-6-20260401' → 'sonnet-4-6'."""
    name = name.removeprefix("claude-")
    # Strip trailing date suffix like -20260401
    parts = name.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 8:
        name = parts[0]
    return name
