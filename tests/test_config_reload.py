"""Tests for config hot-reload and keychain migration in load_config."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from claude_usage_bar.config import load_config, _migrate_key_to_keychain, AppConfig  # noqa: F401


class TestMigrateKeyToKeychain:
    def test_clears_plaintext_key_in_config_file(self):
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False, mode="w") as f:
            f.write('[api]\nanthropic_api_key = "sk-live-secret"\n')
            path = Path(f.name)

        with patch("claude_usage_bar.config.CONFIG_PATH", path):
            _migrate_key_to_keychain("sk-live-secret")

        content = path.read_text()
        assert "sk-live-secret" not in content
        assert "anthropic_api_key" in content  # line still present, key cleared

    def test_does_not_raise_on_missing_file(self):
        from claude_usage_bar.config import _migrate_key_to_keychain
        with patch("claude_usage_bar.config.CONFIG_PATH", Path("/tmp/no-such-file.toml")):
            _migrate_key_to_keychain("key")  # must not raise


class TestLoadConfigKeychainIntegration:
    def test_loads_key_from_keychain_when_config_empty(self):
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False, mode="w") as f:
            f.write('[api]\nanthropic_api_key = ""\n')
            path = Path(f.name)

        with patch("claude_usage_bar.config.CONFIG_PATH", path), \
             patch("claude_usage_bar.keychain.load_api_key", return_value="sk-from-keychain"):
            cfg = load_config()

        assert cfg.api.anthropic_api_key == "sk-from-keychain"

    def test_migrates_plaintext_key_to_keychain(self):
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False, mode="w") as f:
            f.write('[api]\nanthropic_api_key = "sk-plaintext"\n')
            path = Path(f.name)

        saved_keys = []

        def mock_save(key):
            saved_keys.append(key)
            return True

        with patch("claude_usage_bar.config.CONFIG_PATH", path), \
             patch("claude_usage_bar.keychain.save_api_key", side_effect=mock_save):
            cfg = load_config()

        assert "sk-plaintext" in saved_keys
        assert cfg.api.anthropic_api_key == "sk-plaintext"


class TestAppConfigReload:
    def test_reload_config_updates_display_format(self):
        """AppConfig.reload_config() picks up changed display.format."""
        from claude_usage_bar.app import UsageBarApp

        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False, mode="w") as f:
            f.write('[display]\nformat = "cost"\n')
            path = Path(f.name)

        with patch("claude_usage_bar.config.CONFIG_PATH", path), \
             patch("claude_usage_bar.keychain.load_api_key", return_value=""), \
             patch("claude_usage_bar.collector.stats_reader.STATS_CACHE_PATH", Path("/tmp/no-cache.json")), \
             patch("claude_usage_bar.collector.fs_watcher.PROJECTS_DIR", Path("/tmp/no-projects")):
            app = UsageBarApp()
            assert app.config.display.format == "cost"

            # Update config on disk
            path.write_text('[display]\nformat = "tokens"\n')
            app.reload_config()
            assert app.config.display.format == "tokens"
