"""Secure API key storage via the OS keychain.

macOS: uses the system Keychain via the `security` CLI (no extra deps).
Linux: uses the `secretstorage` library (libsecret / GNOME Keyring).
Windows: uses the `keyring` library (Windows Credential Manager).

Falls back to plaintext config if the keychain is unavailable.

Public API:
    save_api_key(key: str) -> None
    load_api_key() -> str          # returns "" if not set
    delete_api_key() -> None
"""

from __future__ import annotations

import logging
import subprocess
import sys

logger = logging.getLogger(__name__)

_SERVICE = "claude-usage-bar"
_ACCOUNT = "anthropic-api-key"


# ------------------------------------------------------------------
# Public interface
# ------------------------------------------------------------------

def save_api_key(key: str) -> bool:
    """Store API key in the OS keychain. Returns True on success."""
    try:
        return _backend().save(key)
    except Exception as e:
        logger.warning("Keychain save failed: %s", e)
        return False


def load_api_key() -> str:
    """Load API key from the OS keychain. Returns '' if not found."""
    try:
        return _backend().load()
    except Exception as e:
        logger.debug("Keychain load failed: %s", e)
        return ""


def delete_api_key() -> None:
    """Remove the API key from the OS keychain."""
    try:
        _backend().delete()
    except Exception as e:
        logger.debug("Keychain delete failed: %s", e)


# ------------------------------------------------------------------
# Backend selection
# ------------------------------------------------------------------

def _backend() -> _KeychainBackend:
    if sys.platform == "darwin":
        return _MacOSKeychain()
    try:
        import keyring  # noqa: F401
        return _KeyringBackend()
    except ImportError:
        pass
    return _NullKeychain()


class _KeychainBackend:
    def save(self, key: str) -> bool: ...
    def load(self) -> str: ...
    def delete(self) -> None: ...


class _MacOSKeychain(_KeychainBackend):
    """Uses macOS `security` CLI — ships with every macOS, zero extra deps."""

    def save(self, key: str) -> bool:
        # Delete first to handle update case (security add-generic-password errors on duplicate)
        self.delete()
        result = subprocess.run(
            [
                "security", "add-generic-password",
                "-s", _SERVICE,
                "-a", _ACCOUNT,
                "-w", key,
                "-U",  # update if exists (belt-and-suspenders)
            ],
            capture_output=True,
        )
        return result.returncode == 0

    def load(self) -> str:
        result = subprocess.run(
            [
                "security", "find-generic-password",
                "-s", _SERVICE,
                "-a", _ACCOUNT,
                "-w",  # print password only
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return ""

    def delete(self) -> None:
        subprocess.run(
            [
                "security", "delete-generic-password",
                "-s", _SERVICE,
                "-a", _ACCOUNT,
            ],
            capture_output=True,
        )


class _KeyringBackend(_KeychainBackend):
    """Uses the `keyring` library — covers Linux (secretstorage) and Windows."""

    def save(self, key: str) -> bool:
        import keyring
        keyring.set_password(_SERVICE, _ACCOUNT, key)
        return True

    def load(self) -> str:
        import keyring
        return keyring.get_password(_SERVICE, _ACCOUNT) or ""

    def delete(self) -> None:
        import keyring
        try:
            keyring.delete_password(_SERVICE, _ACCOUNT)
        except keyring.errors.PasswordDeleteError:
            pass


class _NullKeychain(_KeychainBackend):
    """Graceful no-op when no keychain backend is available."""

    def save(self, key: str) -> bool:
        logger.warning(
            "No keychain backend available. "
            "Install `keyring` package or use macOS/Windows for secure storage."
        )
        return False

    def load(self) -> str:
        return ""

    def delete(self) -> None:
        pass
