"""Tests for the token aggregator — no I/O, pure in-memory logic."""

from __future__ import annotations

import pytest
from datetime import date, timezone
from unittest.mock import MagicMock

from claude_usage_bar.metrics.aggregator import TokenAggregator, ModelStats


def _make_cost_calc(cost: float = 0.01):
    calc = MagicMock()
    calc.compute.return_value = cost
    return calc


def _assistant_entry(
    uuid: str = "uuid-1",
    model: str = "claude-sonnet-4-6",
    timestamp: str = "2026-04-02T10:00:00Z",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_read: int = 200,
    cache_write: int = 300,
) -> dict:
    return {
        "type": "assistant",
        "uuid": uuid,
        "timestamp": timestamp,
        "message": {
            "model": model,
            "role": "assistant",
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_write,
            },
        },
    }


class TestTokenAggregator:
    def test_ignores_non_assistant_entries(self):
        agg = TokenAggregator()
        calc = _make_cost_calc()
        agg.ingest_entry({"type": "user", "uuid": "u1", "timestamp": "2026-04-02T10:00:00Z"}, calc)
        agg.ingest_entry({"type": "summary", "uuid": "u2"}, calc)
        snap = agg.snapshot()
        assert snap.today.requests == 0

    def test_ignores_entries_without_usage(self):
        agg = TokenAggregator()
        calc = _make_cost_calc()
        entry = {
            "type": "assistant",
            "uuid": "u1",
            "timestamp": "2026-04-02T10:00:00Z",
            "message": {"model": "claude-sonnet-4-6", "role": "assistant"},
        }
        agg.ingest_entry(entry, calc)
        snap = agg.snapshot()
        assert snap.today.requests == 0

    def test_deduplicates_by_uuid(self):
        agg = TokenAggregator()
        calc = _make_cost_calc(0.01)
        entry = _assistant_entry(uuid="same-uuid", input_tokens=100)
        agg.ingest_entry(entry, calc)
        agg.ingest_entry(entry, calc)  # second ingest — must be ignored
        snap = agg.snapshot()
        assert snap.today.requests == 1

    def test_accumulates_tokens(self):
        agg = TokenAggregator()
        calc = _make_cost_calc(0.01)
        agg.ingest_entry(_assistant_entry(uuid="u1", input_tokens=100, output_tokens=50), calc)
        agg.ingest_entry(_assistant_entry(uuid="u2", input_tokens=200, output_tokens=75), calc)
        snap = agg.snapshot()
        assert snap.today.input_tokens == 300
        assert snap.today.output_tokens == 125
        assert snap.today.requests == 2

    def test_separates_by_model(self):
        agg = TokenAggregator()
        calc = _make_cost_calc(0.01)
        agg.ingest_entry(_assistant_entry(uuid="u1", model="claude-sonnet-4-6", input_tokens=100), calc)
        agg.ingest_entry(_assistant_entry(uuid="u2", model="claude-haiku-4-5-20251001", input_tokens=50), calc)
        snap = agg.snapshot()
        assert "claude-sonnet-4-6" in snap.today_by_model
        assert "claude-haiku-4-5-20251001" in snap.today_by_model
        assert snap.today_by_model["claude-sonnet-4-6"].input_tokens == 100
        assert snap.today_by_model["claude-haiku-4-5-20251001"].input_tokens == 50

    def test_cost_is_summed(self):
        agg = TokenAggregator()
        calc = _make_cost_calc(0.05)
        agg.ingest_entry(_assistant_entry(uuid="u1"), calc)
        agg.ingest_entry(_assistant_entry(uuid="u2"), calc)
        snap = agg.snapshot()
        assert abs(snap.today.cost_usd - 0.10) < 1e-9

    def test_active_sessions(self):
        agg = TokenAggregator()
        agg.set_active_sessions(3)
        assert agg.snapshot().active_sessions == 3

    def test_week_includes_today(self):
        agg = TokenAggregator()
        calc = _make_cost_calc(0.01)
        agg.ingest_entry(_assistant_entry(uuid="u1", input_tokens=500), calc)
        snap = agg.snapshot()
        assert snap.week.input_tokens >= 500

    def test_total_tokens_property(self):
        ms = ModelStats(
            input_tokens=100, output_tokens=50, cache_read_tokens=200, cache_write_tokens=300
        )
        assert ms.total_tokens == 650
