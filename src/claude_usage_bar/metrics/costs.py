"""Cost calculator — stateless, pricing-table-driven."""

from __future__ import annotations

from claude_usage_bar.config import AppConfig
from claude_usage_bar.metrics.aggregator import ModelStats


class CostCalculator:
    """Computes USD cost for a ModelStats object using the config pricing table."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def compute(self, model: str, stats: ModelStats) -> float:
        rates = self._config.get_pricing(model)
        cost = (
            stats.input_tokens       * rates["input_per_mtok"]          / 1_000_000
            + stats.output_tokens    * rates["output_per_mtok"]         / 1_000_000
            + stats.cache_read_tokens * rates["cache_read_per_mtok"]    / 1_000_000
            + stats.cache_write_1h_tokens * rates["cache_write_1h_per_mtok"] / 1_000_000
            + stats.cache_write_5m_tokens * rates["cache_write_5m_per_mtok"] / 1_000_000
        )
        return cost
