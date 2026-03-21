"""Load/save settings and manage the Windows startup registry entry."""

from __future__ import annotations

import json
import os
import sys
import winreg
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

_APPDATA = os.environ.get("APPDATA", os.path.expanduser("~"))
CONFIG_DIR = Path(_APPDATA) / "ClaudeUsageTray"
CONFIG_FILE = CONFIG_DIR / "settings.json"

_STARTUP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_NAME = "ClaudeUsageTray"


@dataclass
class Settings:
    warning_threshold: int = 80
    critical_threshold: int = 90
    refresh_interval: int = 60
    token_override: str = ""


def load_settings() -> Settings:
    if CONFIG_FILE.exists():
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            valid = {k: v for k, v in raw.items() if k in Settings.__dataclass_fields__}
            return Settings(**valid)
        except Exception:
            pass
    return Settings()


def save_settings(settings: Settings) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")


def _startup_cmd() -> str:
    """Return the command string to register for auto-start."""
    if getattr(sys, "frozen", False):
        # Running as a PyInstaller .exe
        return f'"{sys.executable}"'
    script = os.path.abspath(sys.argv[0])
    return f'"{sys.executable}" "{script}"'


def get_startup_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_KEY) as key:
            winreg.QueryValueEx(key, _APP_NAME)
            return True
    except OSError:
        return False


def set_startup_enabled(enabled: bool) -> None:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _STARTUP_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enabled:
                winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, _startup_cmd())
            else:
                try:
                    winreg.DeleteValue(key, _APP_NAME)
                except FileNotFoundError:
                    pass
    except OSError as exc:
        print(f"[config] Could not update startup registry: {exc}")
