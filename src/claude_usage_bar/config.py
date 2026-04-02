"""Configuration loader — reads ~/.claude-usage-bar/config.toml with sane defaults."""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

CONFIG_PATH = Path.home() / ".claude-usage-bar" / "config.toml"

# Pricing as of 2026-04 — override in config.toml as models change.
DEFAULT_PRICING: dict[str, dict[str, float]] = {
    # Sonnet 4.6
    "claude-sonnet-4-6": {
        "input_per_mtok": 3.00,
        "output_per_mtok": 15.00,
        "cache_read_per_mtok": 0.30,
        "cache_write_per_mtok": 3.75,
    },
    # Sonnet 4.5 (observed in your JSONL files)
    "claude-sonnet-4-5-20250929": {
        "input_per_mtok": 3.00,
        "output_per_mtok": 15.00,
        "cache_read_per_mtok": 0.30,
        "cache_write_per_mtok": 3.75,
    },
    # Haiku 4.5
    "claude-haiku-4-5-20251001": {
        "input_per_mtok": 0.80,
        "output_per_mtok": 4.00,
        "cache_read_per_mtok": 0.08,
        "cache_write_per_mtok": 1.00,
    },
    # Opus 4.6
    "claude-opus-4-6": {
        "input_per_mtok": 15.00,
        "output_per_mtok": 75.00,
        "cache_read_per_mtok": 1.50,
        "cache_write_per_mtok": 18.75,
    },
    # Fallback for unknown models — use Sonnet pricing
    "_default": {
        "input_per_mtok": 3.00,
        "output_per_mtok": 15.00,
        "cache_read_per_mtok": 0.30,
        "cache_write_per_mtok": 3.75,
    },
}


@dataclass
class DisplayConfig:
    format: Literal["cost", "tokens", "both"] = "both"
    show_rate_limits: bool = True
    refresh_interval_seconds: int = 2


@dataclass
class ApiConfig:
    anthropic_api_key: str = ""


@dataclass
class AppConfig:
    display: DisplayConfig = field(default_factory=DisplayConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    pricing: dict[str, dict[str, float]] = field(default_factory=lambda: dict(DEFAULT_PRICING))

    def get_pricing(self, model: str) -> dict[str, float]:
        """Return pricing for model, with prefix-match fallback, then _default."""
        if model in self.pricing:
            return self.pricing[model]
        # Prefix match: "claude-sonnet-4-6-20260401" → "claude-sonnet-4-6"
        for key in self.pricing:
            if key != "_default" and model.startswith(key):
                return self.pricing[key]
        return self.pricing.get("_default", DEFAULT_PRICING["_default"])


def load_config() -> AppConfig:
    """Load config from disk, falling back to defaults on any error."""
    if not CONFIG_PATH.exists():
        return AppConfig()

    try:
        with open(CONFIG_PATH, "rb") as f:
            raw = tomllib.load(f)
    except Exception:
        # Corrupted config — use defaults, don't crash the app.
        return AppConfig()

    cfg = AppConfig()

    if display := raw.get("display"):
        cfg.display.format = display.get("format", cfg.display.format)
        cfg.display.show_rate_limits = display.get("show_rate_limits", cfg.display.show_rate_limits)
        cfg.display.refresh_interval_seconds = display.get(
            "refresh_interval_seconds", cfg.display.refresh_interval_seconds
        )

    if api := raw.get("api"):
        plaintext_key = api.get("anthropic_api_key", "")
        if plaintext_key:
            # Plaintext key present — migrate it to keychain and clear from config
            from claude_usage_bar.keychain import save_api_key
            if save_api_key(plaintext_key):
                cfg.api.anthropic_api_key = plaintext_key
                _migrate_key_to_keychain(plaintext_key)
            else:
                cfg.api.anthropic_api_key = plaintext_key
        else:
            # Load from keychain
            from claude_usage_bar.keychain import load_api_key
            cfg.api.anthropic_api_key = load_api_key()

    # Merge user pricing on top of defaults
    if pricing := raw.get("pricing"):
        for model, rates in pricing.items():
            cfg.pricing[model] = rates

    return cfg


def _migrate_key_to_keychain(key: str) -> None:
    """
    Rewrite config.toml clearing the plaintext key after migrating to keychain.
    Safe to fail — the key is already in the keychain at this point.
    """
    if not CONFIG_PATH.exists():
        return
    try:
        lines = CONFIG_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("anthropic_api_key") and "=" in stripped:
                new_lines.append('anthropic_api_key = ""  # stored in OS keychain\n')
            else:
                new_lines.append(line)
        CONFIG_PATH.write_text("".join(new_lines), encoding="utf-8")
    except Exception:
        pass  # Non-fatal — key is safe in keychain already


def write_default_config() -> None:
    """Write a commented default config file for new users."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        """\
[display]
# "cost" | "tokens" | "both"
format = "both"
show_rate_limits = true
refresh_interval_seconds = 2

[api]
# Optional — enables rate-limit header enrichment
anthropic_api_key = ""

[pricing."claude-sonnet-4-6"]
input_per_mtok = 3.00
output_per_mtok = 15.00
cache_read_per_mtok = 0.30
cache_write_per_mtok = 3.75

[pricing."claude-haiku-4-5-20251001"]
input_per_mtok = 0.80
output_per_mtok = 4.00
cache_read_per_mtok = 0.08
cache_write_per_mtok = 1.00
""",
        encoding="utf-8",
    )
