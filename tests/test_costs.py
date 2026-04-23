"""Tests for CostCalculator — pricing math."""

from __future__ import annotations

import pytest
from claude_usage_bar.config import AppConfig
from claude_usage_bar.metrics.aggregator import ModelStats
from claude_usage_bar.metrics.costs import CostCalculator


def _calc() -> CostCalculator:
    return CostCalculator(AppConfig())


class TestCostCalculator:
    def test_sonnet_input_cost(self):
        calc = _calc()
        stats = ModelStats(input_tokens=1_000_000)
        cost = calc.compute("claude-sonnet-4-6", stats)
        assert abs(cost - 3.00) < 1e-6

    def test_sonnet_output_cost(self):
        calc = _calc()
        stats = ModelStats(output_tokens=1_000_000)
        cost = calc.compute("claude-sonnet-4-6", stats)
        assert abs(cost - 15.00) < 1e-6

    def test_haiku_is_cheaper_than_sonnet(self):
        calc = _calc()
        stats = ModelStats(input_tokens=1_000_000, output_tokens=1_000_000)
        haiku_cost = calc.compute("claude-haiku-4-5-20251001", stats)
        sonnet_cost = calc.compute("claude-sonnet-4-6", stats)
        assert haiku_cost < sonnet_cost

    def test_cache_read_cost(self):
        calc = _calc()
        # Sonnet cache read: $0.30 / MTok
        stats = ModelStats(cache_read_tokens=1_000_000)
        cost = calc.compute("claude-sonnet-4-6", stats)
        assert abs(cost - 0.30) < 1e-6

    def test_cache_write_cost(self):
        calc = _calc()
        # Sonnet 1h cache write: $3.75 / MTok
        stats = ModelStats(cache_write_1h_tokens=1_000_000)
        cost = calc.compute("claude-sonnet-4-6", stats)
        assert abs(cost - 3.75) < 1e-6

    def test_cache_write_5m_cost(self):
        calc = _calc()
        # Sonnet 5m cache write: $3.00 / MTok (same as input)
        stats = ModelStats(cache_write_5m_tokens=1_000_000)
        cost = calc.compute("claude-sonnet-4-6", stats)
        assert abs(cost - 3.00) < 1e-6

    def test_compute_savings(self):
        calc = _calc()
        # Savings = cache_read_tokens × (input_rate - cache_read_rate) / 1M
        # = 1M × (3.00 - 0.30) / 1M = $2.70
        stats = ModelStats(cache_read_tokens=1_000_000)
        savings = calc.compute_savings("claude-sonnet-4-6", stats)
        assert abs(savings - 2.70) < 1e-6

    def test_unknown_model_uses_default(self):
        calc = _calc()
        stats = ModelStats(input_tokens=1_000_000)
        cost = calc.compute("claude-unknown-future-model", stats)
        # Should use _default pricing (Sonnet rates)
        assert cost > 0

    def test_prefix_match(self):
        """claude-sonnet-4-6-20260401 should match claude-sonnet-4-6 pricing."""
        calc = _calc()
        stats = ModelStats(input_tokens=1_000_000)
        cost_exact = calc.compute("claude-sonnet-4-6", stats)
        cost_versioned = calc.compute("claude-sonnet-4-6-20260401", stats)
        assert abs(cost_exact - cost_versioned) < 1e-6

    def test_zero_tokens_zero_cost(self):
        calc = _calc()
        stats = ModelStats()
        cost = calc.compute("claude-sonnet-4-6", stats)
        assert cost == 0.0
