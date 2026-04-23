"""Thread-safe token/cost aggregator.

Maintains per-day, per-model counters built from JSONL assistant entries.
All public methods are safe to call from the FSWatcher thread or the UI thread.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone


@dataclass
class ModelStats:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    # Cache writes split by TTL tier — Anthropic prices these differently:
    #   5-minute ephemeral: same rate as input (no premium)
    #   1-hour extended:    input rate + 25% premium
    cache_write_1h_tokens: int = 0
    cache_write_5m_tokens: int = 0
    requests: int = 0
    cost_usd: float = 0.0

    def add(self, other: ModelStats) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_1h_tokens += other.cache_write_1h_tokens
        self.cache_write_5m_tokens += other.cache_write_5m_tokens
        self.requests += other.requests
        self.cost_usd += other.cost_usd

    @property
    def cache_write_tokens(self) -> int:
        """Total cache writes across both TTL tiers."""
        return self.cache_write_1h_tokens + self.cache_write_5m_tokens

    @property
    def total_tokens(self) -> int:
        return (self.input_tokens + self.output_tokens
                + self.cache_read_tokens + self.cache_write_tokens)


@dataclass
class DayStats:
    """Aggregated stats for a single calendar day (local time)."""
    date: date
    by_model: dict[str, ModelStats] = field(default_factory=lambda: defaultdict(ModelStats))

    @property
    def totals(self) -> ModelStats:
        combined = ModelStats()
        for ms in self.by_model.values():
            combined.add(ms)
        return combined


class TokenAggregator:
    """
    Accumulates assistant entries from JSONL files into a queryable stats store.

    Data flow:
        FSWatcher reads new lines → calls ingest_entry() → UI thread calls snapshot()

    Internally we keep a dict[date, DayStats] keyed on local calendar date.
    We also track which (file_path, byte_offset) we've already processed so
    re-scanning a file on FSEvent doesn't double-count.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # date → DayStats
        self._days: dict[date, DayStats] = {}
        # session_id → set of message uuids already ingested
        self._seen_uuids: set[str] = set()
        # active session count (injected from sessions/ directory reader)
        self._active_sessions: int = 0

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest_entry(self, entry: dict, cost_calculator) -> None:
        """
        Process one parsed JSONL line.

        Only `type == "assistant"` lines with a `.message.usage` block are
        relevant — everything else is silently ignored.
        """
        if entry.get("type") != "assistant":
            return

        uuid = entry.get("uuid")
        if not uuid or uuid in self._seen_uuids:
            return  # already counted

        message = entry.get("message", {})
        usage = message.get("usage")
        if not usage:
            return

        model = message.get("model", "_unknown")
        ts = entry.get("timestamp", "")
        entry_date = _parse_date(ts)

        stats = ModelStats(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
            cache_write_1h_tokens=_extract_cache_1h(usage),
            cache_write_5m_tokens=_extract_cache_5m(usage),
            requests=1,
        )
        stats.cost_usd = cost_calculator.compute(model, stats)

        with self._lock:
            self._seen_uuids.add(uuid)
            if entry_date not in self._days:
                self._days[entry_date] = DayStats(date=entry_date)
            day = self._days[entry_date]
            if model not in day.by_model:
                day.by_model[model] = ModelStats()
            day.by_model[model].add(stats)

    def set_active_sessions(self, count: int) -> None:
        with self._lock:
            self._active_sessions = count

    # ------------------------------------------------------------------
    # Queries (called from UI thread — must be fast)
    # ------------------------------------------------------------------

    def snapshot(self) -> AggregatorSnapshot:
        """Return a point-in-time immutable snapshot for the UI to render."""
        with self._lock:
            today = date.today()
            today_stats = self._days.get(today, DayStats(date=today))

            # Week: last 7 days including today
            week_combined = ModelStats()
            month_combined = ModelStats()
            for d, ds in self._days.items():
                delta = (today - d).days
                if delta < 7:
                    week_combined.add(ds.totals)
                if d.year == today.year and d.month == today.month:
                    month_combined.add(ds.totals)

            return AggregatorSnapshot(
                today=today_stats.totals,
                today_by_model=dict(today_stats.by_model),
                week=week_combined,
                month=month_combined,
                active_sessions=self._active_sessions,
            )


@dataclass
class AggregatorSnapshot:
    today: ModelStats
    today_by_model: dict[str, ModelStats]
    week: ModelStats
    month: ModelStats
    active_sessions: int


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _extract_cache_1h(usage: dict) -> int:
    """
    Extract 1-hour extended cache write tokens.

    Prefers the nested `cache_creation` object introduced in Claude 4.x.
    Falls back to the flat `cache_creation_input_tokens` total (treating the
    entire amount as 1-hour) for any older-format entries that lack the nested
    object — this preserves pre-fix behaviour and avoids undercounting.
    """
    cc = usage.get("cache_creation")
    if isinstance(cc, dict):
        return cc.get("ephemeral_1h_input_tokens", 0)
    return usage.get("cache_creation_input_tokens", 0)


def _extract_cache_5m(usage: dict) -> int:
    """
    Extract 5-minute ephemeral cache write tokens.

    Returns 0 if the nested `cache_creation` object is absent (old format).
    """
    cc = usage.get("cache_creation")
    if isinstance(cc, dict):
        return cc.get("ephemeral_5m_input_tokens", 0)
    return 0


def _parse_date(ts: str) -> date:
    """Parse ISO 8601 timestamp to local date. Falls back to today on parse error."""
    try:
        dt = datetime.fromisoformat(ts.rstrip("Z")).replace(tzinfo=timezone.utc)
        return dt.astimezone().date()
    except Exception:
        return date.today()
