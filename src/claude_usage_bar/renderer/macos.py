"""macOS menu bar renderer using rumps.

Layout:
    Title:  ◕ $1.24 | 1.2M tok

    ── Today ──────────────────────────────
    Tokens:      1,247,891  (in: 42k  out: 89k  cache: 1.1M)
    Cost:        $1.24
    Requests:    847
    Active now:  3 sessions
    Cache saved: $0.84
    Burn rate:   $2.40/hr  → $57.60/day

    ── This Week ──────────────────────────
    Tokens:      8.4M   Cost: $9.12
    ▁▂▃█░░░  (sparkline)

    ── This Month ─────────────────────────
    Tokens:      24.1M  Cost: $31.44

    ── By Project (today) ─────────────────
    my-project         $0.98 | 712k tok
    other-project      $0.26 | 181k tok

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
import sys
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import rumps

from claude_usage_bar.config import AppConfig, write_default_config, CONFIG_PATH
from claude_usage_bar.metrics.aggregator import AggregatorSnapshot, ModelStats

if TYPE_CHECKING:
    from claude_usage_bar.app import UsageBarApp

logger = logging.getLogger(__name__)


def _menubar_icon_path() -> str | None:
    """
    Locate menubar.png in both PyInstaller bundle and source-tree contexts.
    Returns an absolute path string, or None if the file can't be found.
    """
    if getattr(sys, "frozen", False):
        p = Path(sys._MEIPASS) / "menubar.png"  # type: ignore[attr-defined]
    else:
        p = Path(__file__).parent.parent.parent.parent / "packaging" / "assets" / "menubar.png"
    return str(p) if p.exists() else None


_BAR_FILL = "█"
_BAR_EMPTY = "░"
_BAR_WIDTH = 10
_SPARK_CHARS = " ▁▂▃▄▅▆▇█"


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


def _sparkline(week_by_day: dict[date, float]) -> str:
    """Build a 7-character sparkline for the last 7 days (oldest→today)."""
    today = date.today()
    days = [(today.toordinal() - i) for i in range(6, -1, -1)]
    values = [week_by_day.get(date.fromordinal(d), 0.0) for d in days]
    max_v = max(values) if values else 0.0
    if max_v == 0:
        return "░░░░░░░"
    chars = []
    for v in values:
        idx = round((v / max_v) * (len(_SPARK_CHARS) - 1))
        chars.append(_SPARK_CHARS[idx])
    return "".join(chars)


class MenuBarRenderer(rumps.App):
    """
    rumps.App subclass that owns the menu bar lifecycle.
    Refreshes the title and menu items on a timer.
    """

    def __init__(self, app: UsageBarApp) -> None:
        icon_path = _menubar_icon_path()
        super().__init__(
            name="Claude Usage",
            title="loading…",
            icon=icon_path,
            template=True,
            quit_button=None,
        )
        self._app = app
        self._alert_fired_80 = False
        self._alert_fired_100 = False
        self._alert_reset_date: date | None = None
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
        self._today_savings = rumps.MenuItem("Cache saved: —")
        self._burn_rate_line = rumps.MenuItem("Burn rate: —")

        # Week / Month
        self._week_line = rumps.MenuItem("This week: —")
        self._sparkline_line = rumps.MenuItem("         ")
        self._month_line = rumps.MenuItem("This month: —")

        # Project breakdown (dynamic)
        self._project_items: list[rumps.MenuItem] = []

        # Model breakdown (dynamic)
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
            self._today_savings,
            self._burn_rate_line,
            None,
            self._week_line,
            self._sparkline_line,
            self._month_line,
            None,
            rumps.MenuItem("── By Project (today) ─────────────────"),
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

        # ── Live gauge icon ──────────────────────────────────────────────
        self._update_gauge_icon(today.cost_usd, cfg)

        # ── Title bar ───────────────────────────────────────────────────
        if cfg.display.format == "cost":
            self.title = _fmt_cost(today.cost_usd)
        elif cfg.display.format == "tokens":
            self.title = f"{_fmt_tokens(today.total_tokens)} tok"
        else:
            self.title = f"{_fmt_cost(today.cost_usd)} | {_fmt_tokens(today.total_tokens)} tok"

        # ── Today section ───────────────────────────────────────────────
        self._today_tokens.title = (
            f"Tokens:     {today.total_tokens:,}"
            f"  (in: {_fmt_tokens(today.input_tokens)}"
            f"  out: {_fmt_tokens(today.output_tokens)}"
            f"  cache: {_fmt_tokens(today.cache_read_tokens + today.cache_write_tokens)})"
        )
        self._today_cost.title = f"Cost:       {_fmt_cost(today.cost_usd)}"
        self._today_requests.title = f"Requests:   {today.requests:,}"
        self._today_sessions.title = f"Active now: {snap.active_sessions} session{'s' if snap.active_sessions != 1 else ''}"

        # Cache savings
        calc = self._app.get_cost_calculator()
        savings = sum(
            calc.compute_savings(model, ms)
            for model, ms in snap.today_by_model.items()
        )
        self._today_savings.title = f"Cache saved: {_fmt_cost(savings)}"

        # Burn rate + projection
        self._burn_rate_line.title = _compute_burn_rate_label(today.cost_usd, cfg)

        # ── Week / Month ─────────────────────────────────────────────────
        w = snap.week
        self._week_line.title = (
            f"This week:   {_fmt_tokens(w.total_tokens)} tok  {_fmt_cost(w.cost_usd)}"
        )
        self._sparkline_line.title = f"  {_sparkline(snap.week_by_day)}"
        m = snap.month
        self._month_line.title = (
            f"This month:  {_fmt_tokens(m.total_tokens)} tok  {_fmt_cost(m.cost_usd)}"
        )

        # ── By Project ───────────────────────────────────────────────────
        for item in self._project_items:
            try:
                del self.menu[item.title]
            except KeyError:
                pass
        self._project_items = []

        project_section_key = "── By Project (today) ─────────────────"
        sorted_projects = sorted(
            snap.today_by_project.items(),
            key=lambda kv: kv[1].cost_usd,
            reverse=True,
        )
        insert_after = project_section_key
        for proj_name, ms in sorted_projects[:5]:  # cap at 5 projects
            display = proj_name[:36] if len(proj_name) > 36 else proj_name
            label = f"  {display:<36} {_fmt_cost(ms.cost_usd)} | {_fmt_tokens(ms.total_tokens)} tok"
            item = rumps.MenuItem(label)
            self.menu.insert_after(insert_after, item)
            self._project_items.append(item)
            insert_after = label

        # ── By Model ─────────────────────────────────────────────────────
        for item in self._model_items:
            try:
                del self.menu[item.title]
            except KeyError:
                pass
        self._model_items = []

        model_section_key = "── By Model (today) ───────────────────"
        sorted_models = sorted(
            snap.today_by_model.items(),
            key=lambda kv: kv[1].cost_usd,
            reverse=True,
        )
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

        # ── Rate Limits ──────────────────────────────────────────────────
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

        # ── Budget alerts ─────────────────────────────────────────────────
        self._check_budget_alerts(today.cost_usd, cfg)

    # ------------------------------------------------------------------
    # Gauge icon
    # ------------------------------------------------------------------

    _DEFAULT_DAILY_REF = 50.0   # $ soft-scale when no budget_daily_usd configured

    def _update_gauge_icon(self, cost_usd: float, cfg: AppConfig) -> None:
        budget        = cfg.display.budget_daily_usd
        budget_active = budget > 0
        ref           = budget if budget_active else self._DEFAULT_DAILY_REF
        fill_pct      = cost_usd / ref
        try:
            from claude_usage_bar.renderer.gauge_icon import render_gauge, GaugeState
            path, state = render_gauge(fill_pct, budget_active=budget_active)
            # Only switch template mode when budget is active and state requires it.
            # Toggling template on every tick causes a visual duplicate-icon artefact
            # in rumps — set it once and keep it stable.
            want_template = (state == GaugeState.NORMAL)
            if self.template != want_template:
                self.template = want_template
            self.icon = path
        except Exception as e:
            logger.debug("Gauge icon render failed: %s", e)

    # ------------------------------------------------------------------
    # Budget alerts
    # ------------------------------------------------------------------

    def _check_budget_alerts(self, cost_usd: float, cfg: AppConfig) -> None:
        budget = cfg.display.budget_daily_usd
        if budget <= 0:
            return

        today = date.today()
        # Reset alert flags at midnight
        if self._alert_reset_date != today:
            self._alert_reset_date = today
            self._alert_fired_80 = False
            self._alert_fired_100 = False

        pct = cost_usd / budget
        if pct >= 1.0 and not self._alert_fired_100:
            self._alert_fired_100 = True
            rumps.notification(
                title="Claude Usage Bar — Budget Exceeded",
                subtitle=f"Today's spend: {_fmt_cost(cost_usd)}",
                message=f"Daily budget of {_fmt_cost(budget)} has been exceeded.",
            )
        elif pct >= 0.8 and not self._alert_fired_80:
            self._alert_fired_80 = True
            rumps.notification(
                title="Claude Usage Bar — 80% Budget",
                subtitle=f"Today's spend: {_fmt_cost(cost_usd)}",
                message=f"{pct * 100:.0f}% of your {_fmt_cost(budget)} daily budget used.",
            )

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
        _unload_launch_agent()
        rumps.quit_application()


def _unload_launch_agent() -> None:
    plist = Path.home() / "Library" / "LaunchAgents" / "com.claude-usage-bar.plist"
    if plist.exists():
        try:
            subprocess.run(
                ["launchctl", "unload", str(plist)],
                capture_output=True,
                timeout=3,
            )
        except Exception:
            pass


def _compute_burn_rate_label(cost_usd: float, cfg: AppConfig) -> str:
    """
    Estimate hourly burn rate from elapsed time since midnight (local).
    Suppressed until min_burn_rate_minutes of data are available.
    """
    now = datetime.now()
    elapsed_minutes = now.hour * 60 + now.minute
    if elapsed_minutes < cfg.display.min_burn_rate_minutes:
        return "Burn rate: (collecting data…)"

    hourly = cost_usd / (elapsed_minutes / 60.0)
    daily = cost_usd / (elapsed_minutes / (60.0 * 24))

    label = f"Burn rate:   {_fmt_cost(hourly)}/hr  → {_fmt_cost(daily)}/day"
    if cfg.display.budget_daily_usd > 0:
        budget = cfg.display.budget_daily_usd
        pct = (daily / budget) * 100
        label += f"  ({pct:.0f}% of budget)"
    return label


def _shorten_model(name: str) -> str:
    name = name.removeprefix("claude-")
    parts = name.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 8:
        name = parts[0]
    return name
