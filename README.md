<div align="center">

# Claude Usage Bar

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![macOS](https://img.shields.io/badge/macOS-13%2B-black?logo=apple&logoColor=white)](https://www.apple.com/macos/)
[![Tests](https://img.shields.io/badge/tests-48%20passed-brightgreen?logo=pytest&logoColor=white)]()
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)]()
[![Made with ❤️](https://img.shields.io/badge/made%20with-%E2%9D%A4%EF%B8%8F-red)]()

**Real-time Claude token usage & cost in your menu bar.**  
Reads directly from `~/.claude/` session files — no API key required.

[Installation](#installation) • [Usage](#usage) • [Configuration](#configuration) • [Development](#️-development) • [Contributing](#contributing)

---

<img width="320" alt="Claude Usage Bar screenshot" src="https://img.shields.io/badge/today-%2426.38%20%7C%2024.4M%20tok-orange?style=for-the-badge&logo=anthropic&logoColor=white"/>

</div>

---

## ✨ Features

| Feature | Details |
|---|---|
| 🔴 **Real-time** | FSEvents watcher on `~/.claude/projects/**/*.jsonl` — updates in ~100ms |
| 💰 **Accurate cost tracking** | Per-model cost with correct TTL-tier cache pricing (5-min vs 1-hour cache write rates) |
| 📊 **Time windows** | Today / This Week / This Month |
| 🔒 **Secure** | API key stored in macOS Keychain — never plaintext |
| 🔄 **Hot reload** | Config changes apply live — no restart needed |
| 🖥️ **Cross-platform** | macOS (rumps) + Linux/Windows (pystray) |
| ⚡ **Zero API calls** | Works entirely from local files — no network required |
| 🔁 **Deduplication** | UUID-based dedup prevents double-counting entries shared across JSONL files |

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

## ⬆️ Updating

```bash
# pipx
pipx install --force git+https://github.com/yaduvanshi777/claude_usage_live_statusbar.git

# pip
pip install --upgrade git+https://github.com/yaduvanshi777/claude_usage_live_statusbar.git
```

Then restart the app:
```bash
pkill -f claude_usage_bar; claude-usage-bar
```

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

The app shows a live gauge icon alongside cost and token totals:

```
◕ $26.38 | 24.4M tok
├── ── Today ──────────────────────────────
│   Tokens:     24,707,218  (in: 8k  out: 160k  cache: 24.5M)
│   Cost:       $26.38
│   Requests:   318
│   Active now: 3 sessions
│
├── This week:   145.1M tok  $139.20
├── This month:  530.1M tok  $346.33
│
├── ── By Model (today) ───────────────────
│   opus-4-6       $14.37 | 3.2M tok
│   sonnet-4-6     $12.09 | 21.5M tok
│
├── ── Rate Limits ────────────────────────
│   Tokens/min:  ████████░░  78%
│   Reqs/min:    ████░░░░░░  42%
│
├── Refresh Now
├── Open Config…
└── Quit
```

### `--print` JSON output

```bash
claude-usage-bar --print
```

```json
{
  "today": {
    "total_tokens": 24707218,
    "input_tokens": 7988,
    "output_tokens": 159506,
    "cache_read_tokens": 22907617,
    "cache_write_1h_tokens": 1039300,
    "cache_write_5m_tokens": 592807,
    "cost_usd": 26.464197,
    "requests": 318
  },
  "week":  { "total_tokens": 145113941, "cost_usd": 139.20, "requests": 1761 },
  "month": { "total_tokens": 530103567, "cost_usd": 346.33, "requests": 6562 },
  "by_model": { "...": {} },
  "active_sessions": 3
}
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
cache_write_1h_per_mtok = 3.75   # 1-hour extended cache (input × 1.25)
cache_write_5m_per_mtok = 3.00   # 5-minute ephemeral cache (= input rate)

[pricing."claude-haiku-4-5-20251001"]
input_per_mtok = 0.80
output_per_mtok = 4.00
cache_read_per_mtok = 0.08
cache_write_1h_per_mtok = 1.00
cache_write_5m_per_mtok = 0.80
```

> **Migrating from v0.1.0?** The old `cache_write_per_mtok` key is automatically promoted to
> `cache_write_1h_per_mtok` on first load — no manual config changes needed.

### Cache Write Pricing

Anthropic charges different rates depending on the cache TTL selected by the client:

| Tier | TTL | Price |
|---|---|---|
| Ephemeral | 5 minutes | Same as `input_per_mtok` (no premium) |
| Extended | 1 hour | `input_per_mtok × 1.25` |

The app reads `usage.cache_creation.ephemeral_5m_input_tokens` and
`ephemeral_1h_input_tokens` directly from JSONL and applies the correct rate to each.

---

## 🏗️ Architecture

```
FSWatcher (watchdog/FSEvents)
    │ file modified event (~100ms latency)
    ▼
TokenAggregator (thread-safe, UUID dedup)
    │ splits cache writes into 5m / 1h TTL buckets
    ▼
CostCalculator (TOML pricing table, per-TTL rates)
    │
    ▼
rumps StatusBarRenderer (macOS) — gauge icon + live text
pystray SystemTrayRenderer (Linux/Windows)
```

**Data sources** — all local, no network required:

| Source | What It Provides |
|---|---|
| `~/.claude/projects/**/*.jsonl` | Live per-request token & cache-tier data |
| `~/.claude/stats-cache.json` | Historical model-name bootstrap |
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

### Fast development loop

```bash
./scripts/dev.sh           # kill any running instance, start from source (instant)
./scripts/dev.sh --watch   # auto-restart on every src/ file save
                           # requires: brew install fswatch
```

Running from source reads live `.py` files — no PyInstaller rebuild needed during iteration.

### Build `.app` bundle

```bash
# Build only
./scripts/build.sh

# Build + deploy to /Applications + flush icon cache
DEPLOY=1 ./scripts/build.sh

# Output: dist/Claude Usage Bar.app  +  dist/claude-usage-bar-<version>.dmg
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
│   │   ├── aggregator.py       # Thread-safe token accumulation (5m/1h TTL split)
│   │   └── costs.py            # Per-TTL-tier pricing math
│   └── renderer/
│       ├── macos.py            # rumps menu bar + gauge icon
│       └── linux.py            # pystray fallback
├── packaging/
│   ├── assets/
│   │   ├── icon.icns           # App icon (Usage Radar design, all sizes)
│   │   ├── menubar.png         # Menu bar template icon (22pt @2x)
│   │   └── make_icns.py        # Icon generator (requires pillow)
│   ├── claude-usage-bar.spec   # PyInstaller
│   ├── homebrew/formula.rb     # brew install
│   └── launchd/plist           # Auto-start on login
├── scripts/
│   ├── build.sh                # Local .app build (uses project .venv)
│   ├── dev.sh                  # Fast dev loop — kill + restart from source
│   └── release.sh              # Version bump + tag + push
└── tests/                      # 48 tests
```

---

## 🤝 Contributing

1. Fork the repo
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Use `./scripts/dev.sh` for rapid iteration
4. Run tests: `pytest tests/ -v`
5. Push and open a PR

---

## 📄 License

[MIT](LICENSE) — Made with ❤️
