"""Run Seshat at login (Windows).

Uses the per-user Run key, which needs no admin rights and is trivially
reversible. The registry access goes through a small backend Protocol so the
logic is testable with an in-memory fake; the real backend is winreg.
"""

from __future__ import annotations

import sys
from typing import Protocol

APP_NAME = "Seshat"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class RegistryBackend(Protocol):
    def get(self, key: str, name: str) -> str | None: ...
    def set(self, key: str, name: str, value: str) -> None: ...
    def delete(self, key: str, name: str) -> None: ...


class WinregBackend:
    def _hkcu(self):
        import winreg

        return winreg

    def get(self, key: str, name: str) -> str | None:
        winreg = self._hkcu()
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
                value, _ = winreg.QueryValueEx(handle, name)
                return value
        except FileNotFoundError:
            return None

    def set(self, key: str, name: str, value: str) -> None:
        winreg = self._hkcu()
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
            winreg.SetValueEx(handle, name, 0, winreg.REG_SZ, value)

    def delete(self, key: str, name: str) -> None:
        winreg = self._hkcu()
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE
            ) as handle:
                winreg.DeleteValue(handle, name)
        except FileNotFoundError:
            pass


def _default_backend() -> RegistryBackend:
    if sys.platform != "win32":
        raise RuntimeError("Run-on-login is currently Windows-only.")
    return WinregBackend()


def launch_command() -> str:
    """The command the Run key executes at login."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" -m seshat.cli app'


def enable(command: str | None = None, backend: RegistryBackend | None = None) -> None:
    backend = backend or _default_backend()
    backend.set(RUN_KEY, APP_NAME, command or launch_command())


def disable(backend: RegistryBackend | None = None) -> None:
    backend = backend or _default_backend()
    backend.delete(RUN_KEY, APP_NAME)


def is_enabled(backend: RegistryBackend | None = None) -> bool:
    backend = backend or _default_backend()
    return backend.get(RUN_KEY, APP_NAME) is not None
