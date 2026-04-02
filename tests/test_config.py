"""Tests for config loading — uses temp files."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_usage_bar.config import AppConfig, load_config, DEFAULT_PRICING


class TestAppConfig:
    def test_defaults_are_sane(self):
        cfg = AppConfig()
        assert cfg.display.format == "both"
        assert cfg.display.show_rate_limits is True
        assert cfg.api.anthropic_api_key == ""

    def test_exact_model_match(self):
        cfg = AppConfig()
        rates = cfg.get_pricing("claude-sonnet-4-6")
        assert rates["input_per_mtok"] == 3.00

    def test_prefix_match_fallback(self):
        cfg = AppConfig()
        rates = cfg.get_pricing("claude-sonnet-4-6-20260401")
        assert rates["input_per_mtok"] == 3.00

    def test_default_fallback_for_unknown_model(self):
        cfg = AppConfig()
        rates = cfg.get_pricing("claude-future-unknown-model")
        assert rates == DEFAULT_PRICING["_default"]

    def test_load_config_returns_defaults_when_no_file(self):
        with patch("claude_usage_bar.config.CONFIG_PATH", Path("/tmp/does-not-exist.toml")):
            cfg = load_config()
        assert cfg.display.format == "both"

    def test_load_config_returns_defaults_on_parse_error(self):
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False, mode="w") as f:
            f.write("this is not valid toml ][}{")
            path = Path(f.name)
        with patch("claude_usage_bar.config.CONFIG_PATH", path):
            cfg = load_config()
        assert cfg.display.format == "both"

    def test_load_config_reads_display_format(self):
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False, mode="w") as f:
            f.write('[display]\nformat = "cost"\n')
            path = Path(f.name)
        with patch("claude_usage_bar.config.CONFIG_PATH", path):
            cfg = load_config()
        assert cfg.display.format == "cost"

    def test_load_config_merges_custom_pricing(self):
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False, mode="w") as f:
            f.write(
                '[pricing."my-custom-model"]\n'
                "input_per_mtok = 1.00\n"
                "output_per_mtok = 5.00\n"
                "cache_read_per_mtok = 0.10\n"
                "cache_write_per_mtok = 1.25\n"
            )
            path = Path(f.name)
        with patch("claude_usage_bar.config.CONFIG_PATH", path):
            cfg = load_config()
        assert cfg.get_pricing("my-custom-model")["input_per_mtok"] == 1.00
        # Default models should still be present
        assert cfg.get_pricing("claude-sonnet-4-6")["input_per_mtok"] == 3.00
