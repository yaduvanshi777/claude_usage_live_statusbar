#!/usr/bin/env bash
# scripts/build.sh — Build Claude Usage Bar.app locally
#
# Usage:
#   ./scripts/build.sh                    # ad-hoc sign (no Developer ID needed)
#   CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" ./scripts/build.sh
#   NOTARIZE=1 APPLE_ID="you@example.com" APPLE_TEAM_ID="TEAMID" APPLE_APP_PASSWORD="xxxx" ./scripts/build.sh
#
# Output: dist/Claude Usage Bar.app  and  dist/claude-usage-bar-<version>.dmg

set -euo pipefail
cd "$(dirname "$0")/.."

# ── 0. Determine version ──────────────────────────────────────────────────────
VERSION=$(python3 -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); print(d['project']['version'])")
echo "==> Building claude-usage-bar v${VERSION}"

# ── 1. Generate icon if not present ───────────────────────────────────────────
if [[ ! -f packaging/assets/icon.icns ]]; then
    echo "==> Generating icon..."
    python3 packaging/assets/make_icns.py
fi

# ── 2. Install build deps into current venv ───────────────────────────────────
echo "==> Installing build dependencies..."
pip install -q pyinstaller pillow

# ── 3. Clean previous build ───────────────────────────────────────────────────
rm -rf dist/claude-usage-bar dist/"Claude Usage Bar.app" build/claude-usage-bar

# ── 4. PyInstaller ────────────────────────────────────────────────────────────
# Set CLAUDE_BAR_UNIVERSAL2=1 only when using a fat python.org Python install.
# Homebrew Python is arm64-only and will fail if universal2 is forced.
echo "==> Running PyInstaller (arch: ${CLAUDE_BAR_UNIVERSAL2:+universal2}${CLAUDE_BAR_UNIVERSAL2:-native})..."
pyinstaller packaging/claude-usage-bar.spec \
    --distpath dist \
    --workpath build \
    --noconfirm

APP="dist/Claude Usage Bar.app"

if [[ ! -d "$APP" ]]; then
    echo "ERROR: PyInstaller did not produce $APP" >&2
    exit 1
fi

# ── 5. Codesign ───────────────────────────────────────────────────────────────
IDENTITY="${CODESIGN_IDENTITY:--}"   # default: ad-hoc sign
ENTITLEMENTS="packaging/entitlements.plist"

echo "==> Codesigning with identity: ${IDENTITY}"
codesign \
    --force \
    --deep \
    --options runtime \
    --entitlements "$ENTITLEMENTS" \
    --sign "$IDENTITY" \
    "$APP"

echo "==> Verifying signature..."
codesign --verify --deep --strict "$APP"
spctl --assess --type execute "$APP" 2>/dev/null \
    && echo "    Gatekeeper: accepted" \
    || echo "    Gatekeeper: rejected (expected for ad-hoc sign — use Developer ID for distribution)"

# ── 6. DMG ────────────────────────────────────────────────────────────────────
DMG="dist/claude-usage-bar-${VERSION}.dmg"

if command -v create-dmg &>/dev/null; then
    echo "==> Creating DMG..."
    create-dmg \
        --volname "Claude Usage Bar ${VERSION}" \
        --window-size 540 380 \
        --icon-size 128 \
        --icon "Claude Usage Bar.app" 135 190 \
        --hide-extension "Claude Usage Bar.app" \
        --app-drop-link 405 190 \
        --background packaging/assets/dmg_background.png 2>/dev/null \
        "$DMG" \
        "$APP" \
    || create-dmg \
        --volname "Claude Usage Bar ${VERSION}" \
        --window-size 540 380 \
        --icon-size 128 \
        --icon "Claude Usage Bar.app" 135 190 \
        --hide-extension "Claude Usage Bar.app" \
        --app-drop-link 405 190 \
        "$DMG" \
        "$APP"
else
    echo "==> create-dmg not found, building plain DMG with hdiutil..."
    STAGING=$(mktemp -d)
    cp -R "$APP" "$STAGING/"
    ln -s /Applications "$STAGING/Applications"
    hdiutil create \
        -volname "Claude Usage Bar ${VERSION}" \
        -srcfolder "$STAGING" \
        -ov -format UDZO \
        "$DMG"
    rm -rf "$STAGING"
fi

# ── 7. Notarize (optional) ────────────────────────────────────────────────────
if [[ "${NOTARIZE:-0}" == "1" ]]; then
    echo "==> Submitting for notarization..."
    xcrun notarytool submit "$DMG" \
        --apple-id "${APPLE_ID:?set APPLE_ID}" \
        --team-id "${APPLE_TEAM_ID:?set APPLE_TEAM_ID}" \
        --password "${APPLE_APP_PASSWORD:?set APPLE_APP_PASSWORD}" \
        --wait

    echo "==> Stapling notarization ticket..."
    xcrun stapler staple "$DMG"
    xcrun stapler staple "$APP"
fi

# ── 8. Summary ────────────────────────────────────────────────────────────────
echo ""
echo "Build complete:"
echo "  App:  $APP"
echo "  DMG:  $DMG  ($(du -sh "$DMG" | cut -f1))"
SHA=$(shasum -a 256 "$DMG" | awk '{print $1}')
echo "  SHA256: $SHA"
echo ""
echo "Update packaging/homebrew/formula.rb with:"
echo "  sha256 \"${SHA}\""
