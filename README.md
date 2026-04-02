<div align="center">

# ⬛ Claude Usage Bar

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![macOS](https://img.shields.io/badge/macOS-13%2B-black?logo=apple&logoColor=white)](https://www.apple.com/macos/)
[![Tests](https://img.shields.io/badge/tests-48%20passed-brightgreen?logo=pytest&logoColor=white)]()
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)]()
[![Made with ❤️](https://img.shields.io/badge/made%20with-%E2%9D%A4%EF%B8%8F-red)]()

**Real-time Claude token usage & cost in your menu bar.**
Reads directly from `~/.claude/` session files — no API key required.

[Installation](#installation) • [Usage](#usage) • [Configuration](#configuration) • [Contributing](#contributing)

---

<img width="320" alt="Claude Usage Bar screenshot" src="https://img.shields.io/badge/today-%2442.17%20%7C%201044%20reqs-orange?style=for-the-badge&logo=anthropic&logoColor=white"/>

</div>

---

## ✨ Features

| Feature | Details |
|---|---|
| 🔴 **Real-time** | FSEvents watcher on `~/.claude/projects/**/*.jsonl` — updates in ~100ms |
| 💰 **Cost tracking** | Per-model cost breakdown with configurable pricing table |
| 📊 **Time windows** | Today / This Week / This Month |
| 🔒 **Secure** | API key stored in macOS Keychain — never plaintext |
| 🔄 **Hot reload** | Config changes apply live — no restart needed |
| 🖥️ **Cross-platform** | macOS (rumps) + Linux/Windows (pystray) |
| ⚡ **Zero API calls** | Works entirely from local files — no network required |

---

## 📦 Installation

### Option 1 — pipx (recommended)

```bash
pipx install git+https://github.com/yaduvanshi777/claude_usage_live_statusbar.git
claude-usage-bar install   # sets up auto-start on login
```

### Option 2 — pip

```bash
pip install git+https://github.com/yaduvanshi777/claude_usage_live_statusbar.git
claude-usage-bar install
```

### Requirements

- Python 3.11+
- macOS 13+ (Ventura or later)
- [`pipx`](https://pipx.pypa.io/) — `brew install pipx`

---

## 🚀 Usage

```bash
claude-usage-bar              # launch menu bar app
claude-usage-bar --print      # print current stats as JSON and exit
claude-usage-bar install      # install LaunchAgent (auto-start on login)
claude-usage-bar uninstall    # remove LaunchAgent
claude-usage-bar --version    # show version
```

### Menu Bar Display

```
⬛ $42.17 | 68.4M tok
├── ── Today ──────────────────────────────
│   Tokens:     68,357,248  (in: 7k  out: 230k  cache: 68M)
│   Cost:       $42.17
│   Requests:   1,044
│   Active now: 4 sessions
│
├── This week:   285.9M tok  $214.42
├── This month:  116.7M tok  $75.92
│
├── ── By Model (today) ───────────────────
│   sonnet-4-6            $6.45 | 9.3M tok
│   sonnet-4-5-20250929   $30.54 | 56.3M tok
│   haiku-4-5-20251001    $0.46 | 1.5M tok
│
├── ── Rate Limits ────────────────────────
│   Tokens/min:  ████████░░  78%
│   Reqs/min:    ████░░░░░░  42%
│
├── Refresh Now
├── Open Config…
└── Quit
```

---

## ⚙️ Configuration

Config file is created automatically at `~/.claude-usage-bar/config.toml` when you click **Open Config…**

```toml
[display]
# "cost" | "tokens" | "both"
format = "both"
show_rate_limits = true
refresh_interval_seconds = 2

[api]
# Optional — enables rate-limit header enrichment
# Key is stored in macOS Keychain, not here
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
```

---

## 🏗️ Architecture

```
FSWatcher (watchdog/FSEvents)
    │ file modified event (~100ms latency)
    ▼
TokenAggregator (thread-safe, UUID dedup)
    │ updates in-memory metrics
    ▼
CostCalculator (TOML pricing table)
    │
    ▼
rumps StatusBarRenderer (macOS)
pystray SystemTrayRenderer (Linux/Windows)
```

**Data sources** — all local, no network required:

| Source | What It Provides |
|---|---|
| `~/.claude/projects/**/*.jsonl` | Live per-request token data |
| `~/.claude/stats-cache.json` | Historical totals bootstrap |
| `~/.claude/sessions/*.json` | Active session count |
| Anthropic API headers *(optional)* | Rate limit % remaining |

---

## 🛠️ Development

```bash
git clone https://github.com/yaduvanshi777/claude_usage_live_statusbar.git
cd claude_usage_live_statusbar

python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Print live stats (no UI)
python -m claude_usage_bar --print
```

### Build `.app` bundle

```bash
./scripts/build.sh
# Output: dist/Claude Usage Bar.app
```

---

## 📁 Project Structure

```
claude-usage-bar/
├── src/claude_usage_bar/
│   ├── app.py                  # Application lifecycle
│   ├── config.py               # TOML config + hot-reload
│   ├── keychain.py             # OS keychain (macOS/Linux/Windows)
│   ├── collector/
│   │   ├── fs_watcher.py       # FSEvents JSONL watcher
│   │   ├── stats_reader.py     # stats-cache.json parser
│   │   └── api_poller.py       # Optional rate-limit poller
│   ├── metrics/
│   │   ├── aggregator.py       # Thread-safe token accumulation
│   │   └── costs.py            # Pricing table math
│   └── renderer/
│       ├── macos.py            # rumps menu bar
│       └── linux.py            # pystray fallback
├── packaging/
│   ├── claude-usage-bar.spec   # PyInstaller
│   ├── homebrew/formula.rb     # brew install
│   └── launchd/plist           # Auto-start on login
├── scripts/
│   ├── build.sh                # Local .app build
│   └── release.sh              # Version bump + tag + push
└── tests/                      # 48 tests
```

---

## 🤝 Contributing

1. Fork the repo
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Run tests: `pytest tests/ -v`
4. Push and open a PR

---

## 📄 License

[MIT](LICENSE) — Made with ❤️
