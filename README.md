# Claude Usage Bar

macOS menu bar app showing real-time Claude token usage and cost by reading local `~/.claude/` session files. No API key required.

## Install

```bash
pipx install claude-usage-bar
claude-usage-bar install   # creates LaunchAgent for auto-start on login
```

## Usage

```bash
claude-usage-bar           # launch menu bar app
claude-usage-bar --print   # print current stats as JSON
```

## Config

`~/.claude-usage-bar/config.toml` is created automatically on first run via **Open Config…** in the menu.
