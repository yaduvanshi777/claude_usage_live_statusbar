#!/usr/bin/env bash
# scripts/release.sh — Bump version, tag, push to trigger CI release pipeline
#
# Usage:
#   ./scripts/release.sh 0.2.0
#
# What it does:
#   1. Updates version in pyproject.toml and src/claude_usage_bar/__init__.py
#   2. Updates version in packaging/claude-usage-bar.spec and homebrew formula
#   3. Commits the version bump
#   4. Creates annotated git tag v<version>
#   5. Pushes commit + tag — GitHub Actions release.yml takes it from there

set -euo pipefail
cd "$(dirname "$0")/.."

NEW_VERSION="${1:?Usage: ./scripts/release.sh <version>  e.g. 0.2.0}"

# Validate semver format
if ! [[ "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "ERROR: version must be X.Y.Z (got: $NEW_VERSION)" >&2
    exit 1
fi

# Ensure clean working tree
if ! git diff --quiet HEAD; then
    echo "ERROR: working tree is dirty — commit or stash changes first" >&2
    exit 1
fi

echo "==> Bumping to v${NEW_VERSION}"

# ── pyproject.toml ────────────────────────────────────────────────────────────
sed -i '' "s/^version = \".*\"/version = \"${NEW_VERSION}\"/" pyproject.toml

# ── __init__.py ───────────────────────────────────────────────────────────────
sed -i '' "s/__version__ = \".*\"/__version__ = \"${NEW_VERSION}\"/" \
    src/claude_usage_bar/__init__.py

# ── PyInstaller spec ──────────────────────────────────────────────────────────
sed -i '' \
    "s/version=\"[0-9]*\.[0-9]*\.[0-9]*\"/version=\"${NEW_VERSION}\"/" \
    packaging/claude-usage-bar.spec
sed -i '' \
    "s/\"CFBundleShortVersionString\": \"[0-9]*\.[0-9]*\.[0-9]*\"/\"CFBundleShortVersionString\": \"${NEW_VERSION}\"/" \
    packaging/claude-usage-bar.spec

# ── Homebrew formula ──────────────────────────────────────────────────────────
sed -i '' "s/version \"[0-9]*\.[0-9]*\.[0-9]*\"/version \"${NEW_VERSION}\"/" \
    packaging/homebrew/formula.rb

echo "==> Files updated:"
git diff --stat

echo ""
read -r -p "Commit and tag v${NEW_VERSION}? [y/N] " confirm
[[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

git add pyproject.toml src/claude_usage_bar/__init__.py \
    packaging/claude-usage-bar.spec packaging/homebrew/formula.rb

git commit -m "chore: release v${NEW_VERSION}"
git tag -a "v${NEW_VERSION}" -m "Release v${NEW_VERSION}"

echo "==> Pushing..."
git push origin HEAD
git push origin "v${NEW_VERSION}"

echo ""
echo "Tag v${NEW_VERSION} pushed — GitHub Actions will build and publish the release."
echo "Monitor: https://github.com/$(git remote get-url origin | sed 's/.*github.com[:/]//' | sed 's/\.git$//')/actions"
