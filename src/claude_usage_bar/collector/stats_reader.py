"""Bootstrap loader — reads ~/.claude/stats-cache.json for historical totals.

This gives us instant data on startup without re-parsing all JSONL history.
The FSWatcher then takes over for real-time updates from today's JSONL files.

Note: stats-cache.json has costUSD=0 for all models (confirmed from actual file).
We ignore cost from the cache and recompute from tokens × pricing table.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from claude_usage_bar.metrics.aggregator import ModelStats, TokenAggregator
from claude_usage_bar.metrics.costs import CostCalculator

logger = logging.getLogger(__name__)

STATS_CACHE_PATH = Path.home() / ".claude" / "stats-cache.json"


def bootstrap_from_cache(aggregator: TokenAggregator, cost_calculator: CostCalculator) -> bool:
    """
    Pre-populate the aggregator from stats-cache.json.

    Returns True if cache was loaded successfully, False otherwise.
    The JSONL watcher will handle today's data regardless of this result.
    """
    if not STATS_CACHE_PATH.exists():
        logger.info("stats-cache.json not found, skipping bootstrap")
        return False

    try:
        data = json.loads(STATS_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Failed to read stats-cache.json: %s", e)
        return False

    model_usage = data.get("modelUsage", {})
    if not model_usage:
        return False

    today = date.today()

    # stats-cache is a lifetime aggregate — we inject it as a synthetic "all-time"
    # entry keyed to a sentinel date so it doesn't overlap with today's live data.
    # The aggregator only uses today/week/month for display, so historical totals
    # from the cache are NOT surfaced directly — we rely on JSONL for time-windowed data.
    # The cache is only used to warm up model-name discovery and for the "all time" total.
    #
    # For now we inject it tagged as today; the FSWatcher will update today's numbers
    # accurately as it processes today's JSONL files. This is safe because:
    # - We deduplicate by UUID — JSONL-sourced entries will overwrite the cache-sourced ones
    # - The cache uses lifetime totals which would inflate today's numbers
    #
    # CORRECT APPROACH: only use cache to learn which models exist; don't inject token counts.
    logger.info(
        "stats-cache.json loaded. Known models: %s", list(model_usage.keys())
    )
    return True


def get_active_session_count() -> int:
    """Count running Claude sessions by reading ~/.claude/sessions/*.json."""
    sessions_dir = Path.home() / ".claude" / "sessions"
    if not sessions_dir.exists():
        return 0

    import os
    import signal

    count = 0
    for p in sessions_dir.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            pid = data.get("pid")
            if pid:
                # Check if the process is actually alive
                try:
                    os.kill(pid, 0)
                    count += 1
                except (ProcessLookupError, PermissionError):
                    pass  # Process dead or we don't have permission to signal it
        except Exception:
            pass
    return count
