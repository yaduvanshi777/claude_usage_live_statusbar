"""Tests for keychain module — mocks the OS backend so no real keychain is touched."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from claude_usage_bar import keychain as kc


class TestMacOSKeychain:
    def _make(self):
        return kc._MacOSKeychain()

    def test_save_calls_security_add(self):
        chain = self._make()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = chain.save("sk-test-key")
        assert result is True
        calls = [str(c) for c in mock_run.call_args_list]
        # Should have called delete then add
        assert any("add-generic-password" in c for c in calls)

    def test_save_returns_false_on_nonzero_exit(self):
        chain = self._make()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = chain.save("key")
        assert result is False

    def test_load_returns_stripped_stdout(self):
        chain = self._make()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="sk-abc123\n")
            key = chain.load()
        assert key == "sk-abc123"

    def test_load_returns_empty_on_failure(self):
        chain = self._make()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=44, stdout="")
            key = chain.load()
        assert key == ""

    def test_delete_does_not_raise(self):
        chain = self._make()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            chain.delete()  # must not raise


class TestNullKeychain:
    def test_save_returns_false(self):
        assert kc._NullKeychain().save("key") is False

    def test_load_returns_empty(self):
        assert kc._NullKeychain().load() == ""

    def test_delete_does_not_raise(self):
        kc._NullKeychain().delete()


class TestPublicInterface:
    def test_save_api_key_returns_bool(self):
        with patch.object(kc, "_backend") as mock_backend:
            mock_backend.return_value = kc._NullKeychain()
            result = kc.save_api_key("key")
        assert isinstance(result, bool)

    def test_load_api_key_returns_str(self):
        with patch.object(kc, "_backend") as mock_backend:
            b = MagicMock()
            b.load.return_value = "sk-test"
            mock_backend.return_value = b
            result = kc.load_api_key()
        assert result == "sk-test"

    def test_load_api_key_returns_empty_on_exception(self):
        with patch.object(kc, "_backend") as mock_backend:
            b = MagicMock()
            b.load.side_effect = RuntimeError("keychain locked")
            mock_backend.return_value = b
            result = kc.load_api_key()
        assert result == ""

    def test_delete_does_not_raise_on_exception(self):
        with patch.object(kc, "_backend") as mock_backend:
            b = MagicMock()
            b.delete.side_effect = RuntimeError("keychain error")
            mock_backend.return_value = b
            kc.delete_api_key()  # must not raise
