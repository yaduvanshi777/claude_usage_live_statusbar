# PyInstaller spec for claude-usage-bar
#
# Build locally:
#   ./scripts/build.sh
#
# Or manually:
#   pyinstaller packaging/claude-usage-bar.spec
#
# Produces: dist/Claude Usage Bar.app

from pathlib import Path

# Spec lives in packaging/ — project root is one level up
_ROOT = Path(SPECPATH).parent
SRC = _ROOT / "src"
ASSETS = _ROOT / "packaging" / "assets"

# All watchdog observers must be listed — PyInstaller misses dynamic imports.
# On macOS we primarily use FSEvents, but include polling as fallback.
WATCHDOG_HIDDEN = [
    "watchdog.observers.fsevents",
    "watchdog.observers.kqueue",
    "watchdog.observers.polling",
    "watchdog.events",
    "watchdog.utils",
    "watchdog.utils.delayed_queue",
    "watchdog.utils.dirsnapshot",
    "watchdog.utils.event_debouncer",
    "watchdog.utils.platform",
]

a = Analysis(
    [str(SRC / "claude_usage_bar" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[
        # Ship the default config template so first-run write works offline
        (str(ASSETS / "icon.icns"), "."),
    ],
    hiddenimports=[
        "rumps",
        "watchdog",
        *WATCHDOG_HIDDEN,
        # tomllib is stdlib in 3.11+ but PyInstaller sometimes misses it
        "tomllib",
        # keychain uses subprocess only — no hidden imports needed
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "test",
        "unittest",
        "email",
        "html",
        "http",
        "xmlrpc",
        "pydoc",
        "doctest",
        "difflib",
        "pdb",
        "profile",
        "cProfile",
        "timeit",
        "trace",
    ],
    noarchive=False,
    optimize=2,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="claude-usage-bar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=False,          # UPX breaks macOS codesign — never use for .app bundles
    console=False,      # LSUIElement app — no terminal window
    disable_windowed_traceback=False,
    # universal2 requires a fat Python install (python.org installer, not Homebrew).
    # Set CLAUDE_BAR_UNIVERSAL2=1 in CI to produce arm64+x86_64 fat binary.
    # Local Homebrew Python builds native arch only.
    target_arch="universal2" if __import__("os").environ.get("CLAUDE_BAR_UNIVERSAL2") else None,
    codesign_identity=None,         # Done post-build via scripts/build.sh
    entitlements_file=None,         # Applied via codesign in scripts/build.sh
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=True,
    upx=False,
    name="claude-usage-bar",
)

app = BUNDLE(
    coll,
    name="Claude Usage Bar.app",
    icon=str(ASSETS / "icon.icns"),
    bundle_identifier="com.claude-usage-bar",
    version="0.1.0",
    info_plist={
        # Menu bar app — no Dock icon
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
        "CFBundleName": "Claude Usage Bar",
        "CFBundleDisplayName": "Claude Usage Bar",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "1",
        "NSHumanReadableCopyright": "MIT License",
        # Allow reading ~/.claude/ without triggering Privacy prompts
        # (no sandbox = no prompt needed for home dir reads)
        "NSAppleEventsUsageDescription": "Claude Usage Bar reads local Claude session files.",
    },
)
