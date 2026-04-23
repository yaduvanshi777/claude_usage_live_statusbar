"""Tests for FSWatcher file parsing — uses temp files, no real FSEvents."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from claude_usage_bar.collector.fs_watcher import _JSOLHandler
from claude_usage_bar.metrics.aggregator import TokenAggregator
from claude_usage_bar.metrics.costs import CostCalculator
from claude_usage_bar.config import AppConfig


def _make_handler() -> tuple[_JSOLHandler, TokenAggregator]:
    agg = TokenAggregator()
    calc = CostCalculator(AppConfig())
    handler = _JSOLHandler(agg, calc)
    return handler, agg


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def _today_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _assistant_entry(uuid: str = "u1", input_tokens: int = 100) -> dict:
    return {
        "type": "assistant",
        "uuid": uuid,
        "timestamp": _today_ts(),
        "message": {
            "model": "claude-sonnet-4-6",
            "role": "assistant",
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": 50,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        },
    }


class TestJSONLHandler:
    def test_processes_assistant_entries(self):
        handler, agg = _make_handler()
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)

        _write_jsonl(path, [_assistant_entry("u1", 100), _assistant_entry("u2", 200)])
        handler._process_file(path)
        snap = agg.snapshot()
        assert snap.today.requests == 2
        assert snap.today.input_tokens == 300

    def test_incremental_reads(self):
        """Second call to _process_file should only read new lines."""
        handler, agg = _make_handler()
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            path = Path(f.name)
            f.write(json.dumps(_assistant_entry("u1", 100)) + "\n")

        handler._process_file(path)
        assert agg.snapshot().today.requests == 1

        # Append a new line
        with open(path, "a") as f:
            f.write(json.dumps(_assistant_entry("u2", 200)) + "\n")

        handler._process_file(path)
        snap = agg.snapshot()
        assert snap.today.requests == 2
        assert snap.today.input_tokens == 300

    def test_deduplication_across_multiple_scans(self):
        """Re-scanning from offset=0 (e.g., after restart) must not double-count."""
        handler, agg = _make_handler()
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)

        _write_jsonl(path, [_assistant_entry("u1", 100)])

        # Simulate two full scans (e.g., two force-rescans)
        # Reset offset to force re-read
        handler._offsets.clear()
        handler._process_file(path)
        handler._offsets.clear()
        handler._process_file(path)

        snap = agg.snapshot()
        # UUID dedup in aggregator must prevent double-counting
        assert snap.today.requests == 1

    def test_skips_malformed_json_lines(self):
        handler, agg = _make_handler()
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            path = Path(f.name)
            f.write("not json\n")
            f.write(json.dumps(_assistant_entry("u1", 100)) + "\n")
            f.write("{broken\n")

        handler._process_file(path)
        assert agg.snapshot().today.requests == 1

    def test_nonexistent_file_is_ignored(self):
        handler, agg = _make_handler()
        handler._process_file(Path("/tmp/does-not-exist.jsonl"))
        # Should not raise

    def test_empty_file_is_ignored(self):
        handler, agg = _make_handler()
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        handler._process_file(path)
        assert agg.snapshot().today.requests == 0
