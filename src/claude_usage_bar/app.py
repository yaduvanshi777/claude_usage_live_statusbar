"""UsageBarApp — wires together all components and owns the application lifecycle.

Startup sequence:
    1. Load config
    2. Bootstrap from stats-cache.json (fast, historical warmup)
    3. FSWatcher initial scan (all existing JSONL files)
    4. FSWatcher starts watching for live changes
    5. Optional ApiPoller starts (if API key configured)
    6. Session counter starts polling
    7. rumps.App.run() takes over the main thread (required by AppKit)
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from typing import TYPE_CHECKING

from claude_usage_bar.collector.api_poller import ApiPoller, RateLimitStats
from claude_usage_bar.collector.fs_watcher import FSWatcher
from claude_usage_bar.collector.stats_reader import bootstrap_from_cache, get_active_session_count
from claude_usage_bar.config import AppConfig, CONFIG_PATH, load_config
from claude_usage_bar.metrics.aggregator import AggregatorSnapshot, TokenAggregator
from claude_usage_bar.metrics.costs import CostCalculator

logger = logging.getLogger(__name__)


class UsageBarApp:
    """
    Application root. Owns all component lifetimes.
    The UI renderer holds a reference to this object and calls
    get_snapshot() / get_rate_limits() on each timer tick.
    """

    def __init__(self) -> None:
        self.config: AppConfig = load_config()
        self._config_lock = threading.RLock()
        self._cost_calculator = CostCalculator(self.config)
        self._aggregator = TokenAggregator()
        self._watcher = FSWatcher(self._aggregator, self._cost_calculator)
        self._api_poller = ApiPoller(self.config.api.anthropic_api_key)
        self._session_timer: threading.Thread | None = None
        self._config_watcher: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._config_mtime: float = CONFIG_PATH.stat().st_mtime if CONFIG_PATH.exists() else 0.0

    def start(self) -> None:
        """Initialize all background services. Call before running the UI."""
        # 1. Bootstrap historical data from stats-cache (non-blocking, fast)
        bootstrap_from_cache(self._aggregator, self._cost_calculator)

        # 2. Full initial JSONL scan + start FSEvents watcher
        self._watcher.start()

        # 3. Seed active session count
        self._aggregator.set_active_sessions(get_active_session_count())

        # 4. Start session count polling (every 10s — cheap stat() calls)
        self._session_timer = threading.Thread(
            target=self._session_poll_loop, daemon=True, name="session-poller"
        )
        self._session_timer.start()

        # 5. Optional API rate-limit poller
        self._api_poller.start()

        # 6. Config hot-reload watcher (polls mtime every 5s — cheap)
        self._config_watcher = threading.Thread(
            target=self._config_watch_loop, daemon=True, name="config-watcher"
        )
        self._config_watcher.start()

    def reload_config(self) -> None:
        """Reload config from disk and apply changes live (no restart needed)."""
        new_config = load_config()
        with self._config_lock:
            old_key = self.config.api.anthropic_api_key
            self.config = new_config
            self._cost_calculator = CostCalculator(new_config)
            # Restart API poller only if key changed
            if new_config.api.anthropic_api_key != old_key:
                self._api_poller.stop()
                self._api_poller = ApiPoller(new_config.api.anthropic_api_key)
                self._api_poller.start()
        logger.info("Config reloaded")

    def get_snapshot(self) -> AggregatorSnapshot:
        """Called from the UI timer thread — must return quickly."""
        return self._aggregator.snapshot()

    def get_rate_limits(self) -> RateLimitStats | None:
        with self._config_lock:
            has_key = bool(self.config.api.anthropic_api_key)
            poller = self._api_poller
        if has_key:
            return poller.get_stats()
        return None

    def force_rescan(self) -> None:
        """Triggered by 'Refresh Now' menu item — re-runs initial scan."""
        threading.Thread(
            target=self._watcher._handler.initial_scan,
            daemon=True,
            name="force-rescan",
        ).start()

    def shutdown(self) -> None:
        self._stop_event.set()
        self._watcher.stop()
        self._api_poller.stop()

    def _session_poll_loop(self) -> None:
        while not self._stop_event.wait(timeout=10):
            try:
                count = get_active_session_count()
                self._aggregator.set_active_sessions(count)
            except Exception as e:
                logger.debug("Session poll error: %s", e)

    def _config_watch_loop(self) -> None:
        while not self._stop_event.wait(timeout=5):
            try:
                if not CONFIG_PATH.exists():
                    continue
                mtime = CONFIG_PATH.stat().st_mtime
                if mtime != self._config_mtime:
                    self._config_mtime = mtime
                    self.reload_config()
            except Exception as e:
                logger.debug("Config watch error: %s", e)


def run() -> None:
    """Entry point — called from cli.py and __main__.py."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    app_core = UsageBarApp()
    app_core.start()

    if sys.platform == "darwin":
        from claude_usage_bar.renderer.macos import MenuBarRenderer
        # rumps.App.run() must be called from the main thread (AppKit requirement)
        renderer = MenuBarRenderer(app_core)
        renderer.run()
    else:
        from claude_usage_bar.renderer.linux import SystemTrayRenderer
        renderer = SystemTrayRenderer(app_core)
        renderer.run()
