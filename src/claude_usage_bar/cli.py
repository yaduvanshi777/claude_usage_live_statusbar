"""CLI entry point.

Usage:
    claude-usage-bar              # launch menu bar app (macOS)
    claude-usage-bar --print      # print current stats as JSON and exit
    claude-usage-bar install      # create LaunchAgent for auto-start on login
    claude-usage-bar uninstall    # remove LaunchAgent
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> None:
    from claude_usage_bar import __version__

    parser = argparse.ArgumentParser(
        prog="claude-usage-bar",
        description="Claude usage in your menu bar",
    )
    parser.add_argument(
        "--version", action="version", version=f"claude-usage-bar {__version__}"
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("install", help="Install LaunchAgent (auto-start on login)")
    sub.add_parser("uninstall", help="Remove LaunchAgent")

    parser.add_argument(
        "--print",
        action="store_true",
        help="Print current stats as JSON to stdout and exit",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    if args.debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    if args.command == "install":
        _install_launch_agent()
        return

    if args.command == "uninstall":
        _uninstall_launch_agent()
        return

    if args.print:
        _print_stats()
        return

    # Default: launch the menu bar app
    from claude_usage_bar.app import run
    run()


def _print_stats() -> None:
    """Scan JSONL files and print current stats as JSON. Useful for scripting."""
    from claude_usage_bar.collector.fs_watcher import FSWatcher
    from claude_usage_bar.collector.stats_reader import get_active_session_count
    from claude_usage_bar.config import load_config
    from claude_usage_bar.metrics.aggregator import TokenAggregator
    from claude_usage_bar.metrics.costs import CostCalculator

    config = load_config()
    aggregator = TokenAggregator()
    calculator = CostCalculator(config)
    watcher = FSWatcher(aggregator, calculator)
    watcher._handler.initial_scan()

    snap = aggregator.snapshot()
    active = get_active_session_count()

    output = {
        "today": {
            "total_tokens": snap.today.total_tokens,
            "input_tokens": snap.today.input_tokens,
            "output_tokens": snap.today.output_tokens,
            "cache_read_tokens": snap.today.cache_read_tokens,
            "cache_write_1h_tokens": snap.today.cache_write_1h_tokens,
            "cache_write_5m_tokens": snap.today.cache_write_5m_tokens,
            "cost_usd": round(snap.today.cost_usd, 6),
            "requests": snap.today.requests,
        },
        "week": {
            "total_tokens": snap.week.total_tokens,
            "cost_usd": round(snap.week.cost_usd, 6),
            "requests": snap.week.requests,
        },
        "month": {
            "total_tokens": snap.month.total_tokens,
            "cost_usd": round(snap.month.cost_usd, 6),
            "requests": snap.month.requests,
        },
        "by_model": {
            model: {
                "total_tokens": ms.total_tokens,
                "cost_usd": round(ms.cost_usd, 6),
                "requests": ms.requests,
            }
            for model, ms in snap.today_by_model.items()
        },
        "active_sessions": active,
    }
    print(json.dumps(output, indent=2))


def _install_launch_agent() -> None:
    import shutil
    import subprocess
    from pathlib import Path

    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_path = plist_dir / "com.claude-usage-bar.plist"

    # shutil.which searches PATH — may miss pipx installs if PATH isn't updated yet.
    # Fall back to finding the script next to sys.executable (same venv/pipx env).
    executable = shutil.which("claude-usage-bar")
    if not executable:
        candidate = Path(sys.executable).parent / "claude-usage-bar"
        if candidate.exists():
            executable = str(candidate)
    if not executable:
        print("ERROR: claude-usage-bar not found. Install with: pipx install claude-usage-bar", file=sys.stderr)
        sys.exit(1)

    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(
        f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.claude-usage-bar</string>
    <key>ProgramArguments</key>
    <array>
        <string>{executable}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <!-- Only restart on crash (non-zero exit). Clean quit (exit 0) stays quit. -->
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>{Path.home()}/.claude-usage-bar/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{Path.home()}/.claude-usage-bar/stderr.log</string>
</dict>
</plist>
""",
        encoding="utf-8",
    )
    subprocess.run(["launchctl", "load", str(plist_path)], check=True)
    print(f"Installed LaunchAgent: {plist_path}")
    print("Claude Usage Bar will now start automatically on login.")


def _uninstall_launch_agent() -> None:
    import subprocess
    from pathlib import Path

    plist_path = Path.home() / "Library" / "LaunchAgents" / "com.claude-usage-bar.plist"
    if not plist_path.exists():
        print("LaunchAgent not installed.")
        return

    subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
    plist_path.unlink()
    print("LaunchAgent removed.")
