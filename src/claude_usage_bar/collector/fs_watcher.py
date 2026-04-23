"""FSEvents-backed JSONL watcher.

Watches ~/.claude/projects/**/*.jsonl for modifications and feeds new lines
into the TokenAggregator. Uses per-file byte-offset tracking so we never
re-process lines already ingested, even across multiple FSEvents for the
same file.

Thread model:
    watchdog dispatches events on a background thread.
    TokenAggregator.ingest_entry() is thread-safe.
    No locks needed here — offset dict is only written from this thread.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from claude_usage_bar.metrics.aggregator import TokenAggregator
from claude_usage_bar.metrics.costs import CostCalculator

logger = logging.getLogger(__name__)

PROJECTS_DIR = Path.home() / ".claude" / "projects"


class _JSOLHandler(FileSystemEventHandler):
    def __init__(self, aggregator: TokenAggregator, cost_calculator: CostCalculator) -> None:
        super().__init__()
        self._aggregator = aggregator
        self._cost_calculator = cost_calculator
        # file_path (str) → bytes read so far
        self._offsets: dict[str, int] = {}

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = str(event.src_path)
        if path.endswith(".jsonl"):
            self._process_file(Path(path))

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = str(event.src_path)
        if path.endswith(".jsonl"):
            self._process_file(Path(path))

    def _process_file(self, path: Path) -> None:
        offset = self._offsets.get(str(path), 0)
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return

        if size <= offset:
            return  # File shrunk (truncated) or no new data

        try:
            with open(path, "rb") as f:
                f.seek(offset)
                new_bytes = f.read(size - offset)
        except OSError as e:
            logger.warning("Cannot read %s: %s", path, e)
            return

        self._offsets[str(path)] = size

        # Parse complete lines only — a partial last line is fine to skip;
        # the next FSEvent will pick it up.
        for raw_line in new_bytes.split(b"\n"):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            self._aggregator.ingest_entry(entry, self._cost_calculator, project_name=path.parent.name)

    def initial_scan(self) -> None:
        """Process all existing JSONL files on startup."""
        if not PROJECTS_DIR.exists():
            logger.info("~/.claude/projects not found — no history to scan")
            return

        jsonl_files = sorted(PROJECTS_DIR.rglob("*.jsonl"))
        logger.info("Initial scan: %d JSONL files", len(jsonl_files))
        for path in jsonl_files:
            self._process_file(path)


class FSWatcher:
    """Manages the watchdog Observer lifecycle."""

    def __init__(self, aggregator: TokenAggregator, cost_calculator: CostCalculator) -> None:
        self._handler = _JSOLHandler(aggregator, cost_calculator)
        self._observer: Observer | None = None

    def start(self) -> None:
        """Do initial scan then start watching for live changes."""
        self._handler.initial_scan()

        if not PROJECTS_DIR.exists():
            logger.warning("~/.claude/projects not found — live watching disabled")
            return

        self._observer = Observer()
        self._observer.schedule(self._handler, str(PROJECTS_DIR), recursive=True)
        self._observer.start()
        logger.info("FSWatcher started on %s", PROJECTS_DIR)

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
