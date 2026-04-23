"""Configuration loader — reads ~/.claude-usage-bar/config.toml with sane defaults."""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

CONFIG_PATH = Path.home() / ".claude-usage-bar" / "config.toml"

# Pricing as of 2026-04 — override in config.toml as models change.
#
# Cache write tiers (Anthropic prices these differently):
#   cache_write_1h_per_mtok  — 1-hour extended cache, input rate + 25% premium
#   cache_write_5m_per_mtok  — 5-minute ephemeral cache, same as input rate (no premium)
DEFAULT_PRICING: dict[str, dict[str, float]] = {
    # Sonnet 4.6
    "claude-sonnet-4-6": {
        "input_per_mtok":          3.00,
        "output_per_mtok":        15.00,
        "cache_read_per_mtok":     0.30,
        "cache_write_1h_per_mtok": 3.75,   # input × 1.25
        "cache_write_5m_per_mtok": 3.00,   # same as input
    },
    # Sonnet 4.5 (observed in JSONL files)
    "claude-sonnet-4-5-20250929": {
        "input_per_mtok":          3.00,
        "output_per_mtok":        15.00,
        "cache_read_per_mtok":     0.30,
        "cache_write_1h_per_mtok": 3.75,
        "cache_write_5m_per_mtok": 3.00,
    },
    # Haiku 4.5
    "claude-haiku-4-5-20251001": {
        "input_per_mtok":          0.80,
        "output_per_mtok":         4.00,
        "cache_read_per_mtok":     0.08,
        "cache_write_1h_per_mtok": 1.00,   # input × 1.25
        "cache_write_5m_per_mtok": 0.80,   # same as input
    },
    # Opus 4.6
    "claude-opus-4-6": {
        "input_per_mtok":           15.00,
        "output_per_mtok":          75.00,
        "cache_read_per_mtok":       1.50,
        "cache_write_1h_per_mtok":  18.75,  # input × 1.25
        "cache_write_5m_per_mtok":  15.00,  # same as input
    },
    # Fallback for unknown models — Sonnet pricing
    "_default": {
        "input_per_mtok":          3.00,
        "output_per_mtok":        15.00,
        "cache_read_per_mtok":     0.30,
        "cache_write_1h_per_mtok": 3.75,
        "cache_write_5m_per_mtok": 3.00,
    },
}


@dataclass
class DisplayConfig:
    format: Literal["cost", "tokens", "both"] = "both"
    show_rate_limits: bool = True
    refresh_interval_seconds: int = 2
    budget_daily_usd: float = 0.0          # 0 = disabled; enables budget alerts + burn projection
    min_burn_rate_minutes: int = 30        # suppress burn projection before this many minutes of data


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
        cfg.display.budget_daily_usd = float(display.get("budget_daily_usd", cfg.display.budget_daily_usd))
        cfg.display.min_burn_rate_minutes = int(display.get("min_burn_rate_minutes", cfg.display.min_burn_rate_minutes))

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

    # Merge user pricing on top of defaults.
    # Migration: if user's config still has the old single `cache_write_per_mtok`
    # key (pre-TTL-split), promote it to both new keys so the app doesn't crash.
    if pricing := raw.get("pricing"):
        for model, user_rates in pricing.items():
            merged = dict(cfg.pricing.get(model, DEFAULT_PRICING["_default"]))
            merged.update(user_rates)
            if ("cache_write_per_mtok" in merged
                    and "cache_write_1h_per_mtok" not in merged
                    and "cache_write_5m_per_mtok" not in merged):
                old_rate = merged.pop("cache_write_per_mtok")
                merged["cache_write_1h_per_mtok"] = old_rate
                merged["cache_write_5m_per_mtok"] = merged.get("input_per_mtok", old_rate)
            cfg.pricing[model] = merged

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
# budget_daily_usd = 30.0        # optional: enables budget alerts + burn projection
# min_burn_rate_minutes = 30     # suppress projection until this many minutes of data

[api]
# Optional — enables rate-limit header enrichment
anthropic_api_key = ""

[pricing."claude-sonnet-4-6"]
input_per_mtok = 3.00
output_per_mtok = 15.00
cache_read_per_mtok = 0.30
cache_write_1h_per_mtok = 3.75
cache_write_5m_per_mtok = 3.00

[pricing."claude-haiku-4-5-20251001"]
input_per_mtok = 0.80
output_per_mtok = 4.00
cache_read_per_mtok = 0.08
cache_write_1h_per_mtok = 1.00
cache_write_5m_per_mtok = 0.80
""",
        encoding="utf-8",
    )
