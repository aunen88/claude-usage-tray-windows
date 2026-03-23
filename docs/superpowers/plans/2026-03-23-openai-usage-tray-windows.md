# OpenAI Usage Tray — Windows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows system tray app (`openai_usage_tray_windows/`) that tracks OpenAI API usage and costs per model, today and this month — a Windows port of the macOS `openai_usage_tray`.

**Architecture:** `pystray` + hidden `tkinter` root for the Windows tray; all GUI mutations on the main thread via a `queue.Queue` drained by `root.after(50ms)`. A daemon polling thread calls `fetch_usage()` every `refresh_interval` seconds and posts results back to the GUI queue. A `_backoff_pending` guard (using `root.after()`, no lock) prevents duplicate backoff timers after PC sleep/wake.

**Tech Stack:** Python 3.10+, `pystray`, `Pillow`, `requests`, `tkinter` (stdlib), `PyInstaller`. No `pywin32` — `win32_ui.py` uses only `ctypes` and `winreg`.

---

## File Map

| File | Origin | Notes |
|------|--------|-------|
| `api.py` | Copied from `openai_usage_tray/` | Unchanged |
| `menu_builder.py` | Copied from `openai_usage_tray/` | Unchanged |
| `win32_ui.py` | Copied from `claude_tray/` | Unchanged; `taskbar_height()` unused |
| `config.py` | Adapted from `openai_usage_tray/config.py` | Windows path + clamp 3600 |
| `icon_renderer.py` | New | `render_icon(today_cost, *, warning, critical)` |
| `popup.py` | New | `SettingsWindow` only — no `DetailWindow` |
| `main.py` | New | `App` class — tray lifecycle, polling, backoff |
| `tests/test_api.py` | Copied from `openai_usage_tray/tests/` | Unchanged |
| `tests/test_menu_builder.py` | Copied from `openai_usage_tray/tests/` | Unchanged |
| `tests/test_config.py` | Adapted from `openai_usage_tray/tests/` | Windows path + clamp assertions |
| `tests/test_icon_renderer.py` | New | Size + no-crash tests |

---

## Task 1: Project Scaffold

**Files:**
- Create: `openai_usage_tray_windows/` (entire directory)
- Create: `openai_usage_tray_windows/requirements.txt`
- Create: `openai_usage_tray_windows/pyproject.toml`
- Create: `openai_usage_tray_windows/.gitignore`
- Create: `openai_usage_tray_windows/dpi_aware.manifest`

- [ ] **Step 1: Create project directory and scaffold files**

```bash
mkdir -p /f/Claude/openai_usage_tray_windows/tests
cd /f/Claude/openai_usage_tray_windows
```

`requirements.txt`:
```
pystray==0.19.5
Pillow==11.1.0
requests==2.32.3
pyinstaller==6.15.0
pytest==8.3.5
```

`pyproject.toml`:
```toml
[tool.ruff]
line-length = 120
extend-select = ["B", "I"]

[tool.ruff.lint]
extend-select = ["B", "I"]
```

`.gitignore`:
```
__pycache__/
*.py[cod]
dist/
build/
*.spec
*.egg-info/
.venv/
```

`dpi_aware.manifest`:
```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0" xmlns:asmv3="urn:schemas-microsoft-com:asm.v3">
  <asmv3:application>
    <asmv3:windowsSettings>
      <dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">PerMonitorV2</dpiAwareness>
    </asmv3:windowsSettings>
  </asmv3:application>
</assembly>
```

- [ ] **Step 2: Init git and make first commit**

```bash
cd /f/Claude/openai_usage_tray_windows
git init
git add requirements.txt pyproject.toml .gitignore dpi_aware.manifest
git commit -m "chore: project scaffold"
```

---

## Task 2: Copy Unchanged Modules

**Files:**
- Create: `openai_usage_tray_windows/api.py` (copy)
- Create: `openai_usage_tray_windows/menu_builder.py` (copy)
- Create: `openai_usage_tray_windows/win32_ui.py` (copy)
- Create: `openai_usage_tray_windows/tests/test_api.py` (copy)
- Create: `openai_usage_tray_windows/tests/test_menu_builder.py` (copy)

- [ ] **Step 1: Copy files**

```bash
cp /f/Claude/openai_usage_tray/api.py /f/Claude/openai_usage_tray_windows/api.py
cp /f/Claude/openai_usage_tray/menu_builder.py /f/Claude/openai_usage_tray_windows/menu_builder.py
cp /f/Claude/claude_tray/win32_ui.py /f/Claude/openai_usage_tray_windows/win32_ui.py
cp /f/Claude/openai_usage_tray/tests/test_api.py /f/Claude/openai_usage_tray_windows/tests/test_api.py
cp /f/Claude/openai_usage_tray/tests/test_menu_builder.py /f/Claude/openai_usage_tray_windows/tests/test_menu_builder.py
touch /f/Claude/openai_usage_tray_windows/tests/__init__.py
```

- [ ] **Step 2: Run the copied tests to verify they pass**

```bash
cd /f/Claude/openai_usage_tray_windows
python -m pytest tests/test_api.py tests/test_menu_builder.py -v
```

Expected: all tests PASS (these run on any platform — no Windows-specific imports).

- [ ] **Step 3: Commit**

```bash
git add api.py menu_builder.py win32_ui.py tests/
git commit -m "feat: copy unchanged modules from macOS and claude_tray"
```

---

## Task 3: Adapt `config.py`

**Files:**
- Create: `openai_usage_tray_windows/config.py` (adapted)
- Create: `openai_usage_tray_windows/tests/test_config.py` (adapted)

The two Windows-specific changes from the macOS `config.py`:
1. Config path: `~/.openai_usage_tray/settings.json` → `%APPDATA%\OpenAIUsageTray\settings.json`
2. `refresh_interval` clamp: `max(60, min(..., 600))` → `max(60, min(..., 3600))`

- [ ] **Step 1: Write the failing tests**

Create `openai_usage_tray_windows/tests/test_config.py`:

```python
import importlib
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest


def test_default_settings():
    from config import Settings
    s = Settings()
    assert s.api_key == ""
    assert s.refresh_interval == 300
    assert s.month_warning_usd == 50.0
    assert s.month_critical_usd == 100.0


def test_save_and_load_roundtrip(tmp_path):
    from config import Settings, load_settings, save_settings
    with patch("config.CONFIG_FILE", tmp_path / "settings.json"), \
         patch("config.CONFIG_DIR", tmp_path):
        s = Settings(api_key="sk-test", refresh_interval=120,
                     month_warning_usd=25.0, month_critical_usd=75.0)
        save_settings(s)
        loaded = load_settings()
    assert loaded.api_key == "sk-test"
    assert loaded.refresh_interval == 120


def test_load_missing_file_returns_defaults(tmp_path):
    from config import load_settings
    with patch("config.CONFIG_FILE", tmp_path / "nonexistent.json"):
        s = load_settings()
    assert s.api_key == ""
    assert s.refresh_interval == 300


def test_refresh_interval_clamped_to_3600(tmp_path):
    from config import load_settings
    raw = {"api_key": "", "refresh_interval": 9999,
           "month_warning_usd": 50.0, "month_critical_usd": 100.0}
    (tmp_path / "settings.json").write_text(json.dumps(raw))
    with patch("config.CONFIG_FILE", tmp_path / "settings.json"), \
         patch("config.CONFIG_DIR", tmp_path):
        s = load_settings()
    assert s.refresh_interval == 3600


def test_refresh_interval_clamped_to_60(tmp_path):
    from config import load_settings
    raw = {"api_key": "", "refresh_interval": 0,
           "month_warning_usd": 50.0, "month_critical_usd": 100.0}
    (tmp_path / "settings.json").write_text(json.dumps(raw))
    with patch("config.CONFIG_FILE", tmp_path / "settings.json"), \
         patch("config.CONFIG_DIR", tmp_path):
        s = load_settings()
    assert s.refresh_interval == 60


def test_config_path_uses_appdata(monkeypatch):
    monkeypatch.setenv("APPDATA", "C:\\Users\\test\\AppData\\Roaming")
    # Re-import to pick up fresh module-level constants
    import config
    importlib.reload(config)
    try:
        assert "OpenAIUsageTray" in str(config.CONFIG_DIR)
        assert "APPDATA" not in str(config.CONFIG_DIR)  # env var was expanded
    finally:
        importlib.reload(config)  # restore module state for subsequent tests
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /f/Claude/openai_usage_tray_windows
python -m pytest tests/test_config.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3: Implement `config.py`**

Create `config.py`:

```python
"""Load/save settings to %APPDATA%\OpenAIUsageTray\settings.json."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

CONFIG_DIR = Path(os.environ.get("APPDATA", os.path.expanduser("~"))) / "OpenAIUsageTray"
CONFIG_FILE = CONFIG_DIR / "settings.json"


@dataclass
class Settings:
    api_key: str = ""
    refresh_interval: int = 300       # seconds, 60–3600
    month_warning_usd: float = 50.0
    month_critical_usd: float = 100.0


def load_settings() -> Settings:
    if CONFIG_FILE.exists():
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            valid = {k: v for k, v in raw.items() if k in Settings.__dataclass_fields__}
            s = Settings(**valid)
            s.refresh_interval = max(60, min(s.refresh_interval, 3600))
            return s
        except Exception:
            log.warning("Could not load settings, using defaults.")
    return Settings()


def save_settings(settings: Settings) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_config.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: add config module with Windows path and 3600s clamp"
```

---

## Task 4: `icon_renderer.py`

**Files:**
- Create: `openai_usage_tray_windows/icon_renderer.py`
- Create: `openai_usage_tray_windows/tests/test_icon_renderer.py`

Renders a 64×64 RGBA `PIL.Image` showing today's spend. Background tint indicates cost level.

- [ ] **Step 1: Write the failing tests**

Create `openai_usage_tray_windows/tests/test_icon_renderer.py`:

```python
from PIL import Image


def test_render_icon_returns_64x64():
    from icon_renderer import render_icon
    img = render_icon(4.20, warning=50.0, critical=100.0)
    assert isinstance(img, Image.Image)
    assert img.size == (64, 64)


def test_render_icon_below_warning():
    from icon_renderer import render_icon
    img = render_icon(1.00, warning=50.0, critical=100.0)
    assert img.size == (64, 64)


def test_render_icon_at_warning():
    from icon_renderer import render_icon
    img = render_icon(50.0, warning=50.0, critical=100.0)
    assert img.size == (64, 64)


def test_render_icon_at_critical():
    from icon_renderer import render_icon
    img = render_icon(100.0, warning=50.0, critical=100.0)
    assert img.size == (64, 64)


def test_render_icon_zero_cost():
    from icon_renderer import render_icon
    img = render_icon(0.0, warning=50.0, critical=100.0)
    assert img.size == (64, 64)


def test_render_icon_large_cost():
    from icon_renderer import render_icon
    img = render_icon(999.99, warning=50.0, critical=100.0)
    assert img.size == (64, 64)
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_icon_renderer.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'icon_renderer'`

- [ ] **Step 3: Implement `icon_renderer.py`**

Create `icon_renderer.py`:

```python
"""Pillow-based tray icon for OpenAI Usage Tray — Windows.

Renders a 64×64 RGBA image showing today's spend in dollars.
Background tint reflects cost level against thresholds.

Render pipeline: draw at 128×128 → LANCZOS downsample to 64×64.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_RENDER = 128
_OUT = 64

_FONT_CANDIDATES = [
    "C:/Windows/Fonts/consolab.ttf",   # Consolas Bold
    "C:/Windows/Fonts/consola.ttf",    # Consolas Regular
    "C:/Windows/Fonts/courbd.ttf",     # Courier New Bold
    "C:/Windows/Fonts/cour.ttf",       # Courier New
    "C:/Windows/Fonts/lucon.ttf",      # Lucida Console
    "C:/Windows/Fonts/arialbd.ttf",    # Arial Bold (last resort)
]

# Background colours (RGBA) — dark base with cost-level tint
_BG_NORMAL = (26, 26, 26, 235)   # neutral dark
_BG_WARN   = (60, 38, 0, 235)    # amber tint
_BG_CRIT   = (60, 0, 0, 235)     # red tint
_TEXT_COLOR = "#DDDDDD"


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    text: str,
    fill: str,
    font: ImageFont.FreeTypeFont,
) -> None:
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        draw.text((cx - w // 2 - bbox[0], cy - h // 2 - bbox[1]), text, fill=fill, font=font)
    except AttributeError:
        # Pillow < 9.2 fallback
        draw.text((cx - 16, cy - 8), text, fill=fill, font=font)


def render_icon(today_cost: float, *, warning: float, critical: float) -> Image.Image:
    """Return a 64×64 RGBA PIL.Image for the system tray.

    Args:
        today_cost: Today's spend in USD.
        warning:    Monthly warning threshold in USD (for background tint).
        critical:   Monthly critical threshold in USD (for background tint).

    Note: tint thresholds are compared against today_cost for a live
    per-day indicator. The title bar uses month totals; the icon uses today.
    """
    if today_cost >= critical:
        bg = _BG_CRIT
    elif today_cost >= warning:
        bg = _BG_WARN
    else:
        bg = _BG_NORMAL

    sz = _RENDER
    img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, sz - 1, sz - 1], fill=bg)

    # Format: "$4.20" for < $100, "$142" for >= $100
    if today_cost >= 100:
        text = f"${int(today_cost)}"
        font_size = 36
    elif today_cost >= 10:
        text = f"${today_cost:.1f}"
        font_size = 32
    else:
        text = f"${today_cost:.2f}"
        font_size = 28

    font = _load_font(font_size)
    _draw_centered(draw, sz // 2, sz // 2, text, _TEXT_COLOR, font)

    return img.resize((_OUT, _OUT), Image.LANCZOS)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_icon_renderer.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add icon_renderer.py tests/test_icon_renderer.py
git commit -m "feat: add icon_renderer with spend text and cost-level tint"
```

---

## Task 5: `popup.py` (SettingsWindow)

**Files:**
- Create: `openai_usage_tray_windows/popup.py`

`SettingsWindow` — a `tk.Toplevel` modal with:
- Masked API key `tk.Entry` + eye-toggle button
- Three `tk.Scale` sliders (refresh interval, warning $, critical $)
- Save (validates non-empty key, calls `save_settings` then `on_save` callback) / Cancel

No unit tests — tkinter GUI; verify by manual smoke test.

- [ ] **Step 1: Implement `popup.py`**

Create `popup.py`:

```python
"""Tkinter settings window for OpenAI Usage Tray — Windows."""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from config import Settings, save_settings
import win32_ui

# Typography
FONT    = ("Segoe UI", 10)
FONT_B  = ("Segoe UI Semibold", 10)
FONT_SM = ("Segoe UI", 8)


def _palette() -> dict:
    light = win32_ui.is_light_theme()
    return {
        "BG":      "#f3f3f3" if light else "#202020",
        "BG_SEC":  "#e8e8e8" if light else "#2c2c2c",
        "FG":      "#1c1c1c" if light else "#f0f0f0",
        "RED":     "#FF3B30",
        "BLUE":    "#007AFF",
    }


class SettingsWindow(tk.Toplevel):
    """Modal settings window. Calls on_save(new_settings) on successful save."""

    def __init__(
        self,
        master: tk.Tk,
        settings: Settings,
        on_save: Callable[[Settings], None],
    ) -> None:
        super().__init__(master)
        self.title("Settings — OpenAI Usage Tray")
        self.resizable(False, False)
        self._settings = settings
        self._on_save = on_save
        self._show_key = False
        self._p = _palette()
        self.configure(bg=self._p["BG"])
        self._build_ui()
        self.grab_set()
        self.focus_set()
        self.update_idletasks()
        self._center()
        try:
            win32_ui.apply_rounded_corners(self.winfo_id())
        except Exception:
            pass

    def _center(self) -> None:
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    def _build_ui(self) -> None:
        PAD = 16
        p = self._p

        # ── API Key ──────────────────────────────────────────────────────────
        tk.Label(self, text="OpenAI Admin API Key", bg=p["BG"], fg=p["FG"],
                 font=FONT_B).pack(anchor="w", padx=PAD, pady=(PAD, 2))

        key_frame = tk.Frame(self, bg=p["BG"])
        key_frame.pack(fill="x", padx=PAD, pady=(0, 2))

        self._key_var = tk.StringVar(value=self._settings.api_key)
        self._key_entry = tk.Entry(
            key_frame, textvariable=self._key_var, show="●", width=36,
            bg=p["BG_SEC"], fg=p["FG"], insertbackground=p["FG"],
            relief="flat", font=FONT,
        )
        self._key_entry.pack(side="left", ipady=4)

        tk.Button(
            key_frame, text="👁", bg=p["BG"], fg=p["FG"], relief="flat",
            cursor="hand2", command=self._toggle_key,
        ).pack(side="left", padx=(4, 0))

        self._key_error = tk.Label(self, text="", bg=p["BG"], fg=p["RED"], font=FONT_SM)
        self._key_error.pack(anchor="w", padx=PAD)

        # ── Sliders ───────────────────────────────────────────────────────────
        self._interval_var = tk.IntVar(value=self._settings.refresh_interval)
        self._warning_var  = tk.IntVar(value=int(self._settings.month_warning_usd))
        self._critical_var = tk.IntVar(value=int(self._settings.month_critical_usd))

        self._slider_row("Refresh interval (s)", self._interval_var, from_=60, to=3600)
        self._slider_row("Warning threshold ($)", self._warning_var,  from_=1,  to=500)
        self._slider_row("Critical threshold ($)", self._critical_var, from_=1,  to=1000)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_frame = tk.Frame(self, bg=p["BG"])
        btn_frame.pack(fill="x", padx=PAD, pady=PAD)

        tk.Button(
            btn_frame, text="Cancel", command=self.destroy,
            bg=p["BG_SEC"], fg=p["FG"], relief="flat", padx=12, pady=4,
        ).pack(side="right", padx=(4, 0))

        tk.Button(
            btn_frame, text="Save", command=self._save,
            bg=p["BLUE"], fg="#ffffff", relief="flat", padx=12, pady=4,
        ).pack(side="right")

    def _slider_row(self, label: str, var: tk.IntVar, from_: int, to: int) -> None:
        p = self._p
        frame = tk.Frame(self, bg=p["BG"])
        frame.pack(fill="x", padx=16, pady=4)
        tk.Label(frame, text=label, bg=p["BG"], fg=p["FG"],
                 font=FONT, width=24, anchor="w").pack(side="left")
        tk.Scale(
            frame, from_=from_, to=to, orient="horizontal", variable=var,
            bg=p["BG"], fg=p["FG"], highlightthickness=0, relief="flat",
        ).pack(side="left", fill="x", expand=True)

    def _toggle_key(self) -> None:
        self._show_key = not self._show_key
        self._key_entry.config(show="" if self._show_key else "●")

    def _save(self) -> None:
        key = self._key_var.get().strip()
        if not key:
            self._key_error.config(text="API key cannot be empty.")
            return
        self._key_error.config(text="")
        new_settings = Settings(
            api_key=key,
            refresh_interval=self._interval_var.get(),
            month_warning_usd=float(self._warning_var.get()),
            month_critical_usd=float(self._critical_var.get()),
        )
        save_settings(new_settings)
        self._on_save(new_settings)
        self.destroy()
```

- [ ] **Step 2: Smoke test (manual)**

```bash
cd /f/Claude/openai_usage_tray_windows
python -c "
import tkinter as tk
from config import Settings
from popup import SettingsWindow

root = tk.Tk()
root.withdraw()

def on_save(s):
    print('Saved:', s)
    root.destroy()

SettingsWindow(root, Settings(), on_save)
root.mainloop()
"
```

Expected: Settings window appears centered on screen. Manually verify:
1. Click Save with empty API key → inline red error label appears, window stays open
2. Type any key value → click Save → prints saved settings, window closes
3. Click Cancel → window closes with no output

- [ ] **Step 3: Commit**

```bash
git add popup.py
git commit -m "feat: add SettingsWindow with API key entry and sliders"
```

---

## Task 6: `main.py` (App)

**Files:**
- Create: `openai_usage_tray_windows/main.py`

The `App` class owns all state. Key points:
- All GUI mutations on main thread via `_gui_q` / `_post()`
- `_poll_tick()` runs on main thread via `root.after()`; spawns fetch daemon thread
- `_fetch()` runs on daemon thread; posts results back via `_post(_apply_state, ...)`
- `_schedule_backoff()` uses `root.after()` on main thread — no lock needed
- Manual Refresh bypasses `_backoff_pending` (calls `threading.Thread` directly)
- **Menu rebuild**: Use `self.icon.menu = self._make_menu()` — pystray's `menu` property setter automatically calls `update_menu()`. Do NOT call `icon.update_menu()` separately. `_make_menu()` must use static string values (not callables) and be called every time state changes to produce a fresh `pystray.Menu` object with the current data baked in.

- [ ] **Step 1: Implement `main.py`**

Create `main.py`:

```python
"""OpenAIUsageTray — Windows system tray app for OpenAI API usage tracking.

Architecture
------------
• main thread  : hidden tkinter root + event loop (all GUI mutations here)
• pystray      : runs detached via icon.run_detached()
• polling      : daemon thread, posts results to GUI queue
• GUI queue    : queue.Queue drained by root.after(50ms)
"""
from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from typing import Optional

import pystray

from api import AuthError, RateLimitError, UsageData, fetch_usage
from config import Settings, load_settings
from icon_renderer import render_icon
from menu_builder import (
    build_last_updated, build_model_line, build_summary_lines, build_title,
)
from popup import SettingsWindow

# ── Logging ──────────────────────────────────────────────────────────────────

_LOG_DIR = Path(os.environ.get("APPDATA", "~")) / "OpenAIUsageTray"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "app.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────


class App:
    """Owns all state. All public methods must be called on the main thread."""

    def __init__(self) -> None:
        self.settings: Settings = load_settings()
        self.usage: Optional[UsageData] = None
        self.status: str = "no_key" if not self.settings.api_key else "loading"

        # Backoff state (main-thread only after init)
        self._backoff_s: int = 60
        self._backoff_pending: bool = False

        # Settings window reference
        self._settings_win: Optional[tk.Toplevel] = None

        # Cross-thread dispatch queue
        self._gui_q: queue.Queue = queue.Queue()

        # Hidden tkinter root
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("OpenAIUsageTray")

        # Tray icon
        placeholder = render_icon(
            0.0,
            warning=self.settings.month_warning_usd,
            critical=self.settings.month_critical_usd,
        )
        self.icon = pystray.Icon(
            "OpenAIUsageTray",
            icon=placeholder,
            title="OpenAI Usage",
            menu=self._make_menu(),
        )

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self) -> None:
        self.root.after(50, self._drain_queue)
        self.root.after(100, self._initial_fetch)
        self.icon.run_detached()
        self.root.mainloop()

    # ── Queue ─────────────────────────────────────────────────────────────────

    def _post(self, fn, *args) -> None:
        self._gui_q.put((fn, args))

    def _drain_queue(self) -> None:
        try:
            while True:
                fn, args = self._gui_q.get_nowait()
                try:
                    fn(*args)
                except Exception:
                    log.exception("GUI queue callback raised")
        except queue.Empty:
            pass
        self.root.after(50, self._drain_queue)

    # ── Polling ───────────────────────────────────────────────────────────────

    def _initial_fetch(self) -> None:
        if self.settings.api_key:
            threading.Thread(target=self._fetch, daemon=True).start()
        self._schedule_next_poll()

    def _schedule_next_poll(self) -> None:
        self.root.after(self.settings.refresh_interval * 1000, self._poll_tick)

    def _poll_tick(self) -> None:
        """Main-thread timer — spawns fetch if not in backoff and interval elapsed."""
        if not self._backoff_pending and self.status != "ratelimit":
            if self.usage is None or (
                (datetime.now() - self.usage.fetched_at).total_seconds()
                >= self.settings.refresh_interval
            ):
                threading.Thread(target=self._fetch, daemon=True).start()
        self._schedule_next_poll()

    # ── Fetch (background thread) ─────────────────────────────────────────────

    def _fetch(self) -> None:
        if not self.settings.api_key:
            self._post(self._apply_state, "no_key", None)
            return
        try:
            data = fetch_usage(self.settings.api_key)
            self._backoff_s = 60
            log.info("Fetched: today=$%.2f month=$%.2f", data.today_cost, data.month_cost)
            self._post(self._apply_state, "ok", data)
        except AuthError as exc:
            log.warning("Auth error: %s", exc)
            self._post(self._apply_state, "error", None)
        except RateLimitError as exc:
            self._backoff_s = (
                min(exc.retry_after, 900) if exc.retry_after > 0
                else min(self._backoff_s * 2, 900)
            )
            log.warning("Rate limited — backing off %ds", self._backoff_s)
            self._post(self._apply_state, "ratelimit", None)
        except Exception as exc:
            log.error("Fetch failed: %s", exc)
            self._post(self._apply_state, "stale" if self.usage else "error", None)

    # ── State application (main thread) ──────────────────────────────────────

    def _apply_state(self, status: str, data: Optional[UsageData]) -> None:
        self.status = status
        if data is not None:
            self.usage = data
        if status == "ratelimit":
            self._schedule_backoff()
        elif status == "ok":
            self._backoff_pending = False
        self._refresh_icon()
        self.icon.menu = self._make_menu()

    def _schedule_backoff(self) -> None:
        """Schedule a post-backoff retry. Silently drops duplicates (main thread)."""
        if self._backoff_pending:
            log.debug("Backoff already scheduled — skipping duplicate")
            return
        self._backoff_pending = True
        self.root.after(self._backoff_s * 1000, self._run_backoff)

    def _run_backoff(self) -> None:
        self._backoff_pending = False
        threading.Thread(target=self._fetch, daemon=True).start()

    # ── Icon + menu ───────────────────────────────────────────────────────────

    def _refresh_icon(self) -> None:
        today_cost = self.usage.today_cost if self.usage else 0.0
        img = render_icon(
            today_cost,
            warning=self.settings.month_warning_usd,
            critical=self.settings.month_critical_usd,
        )
        self.icon.icon = img
        # Update tray tooltip / title
        if self.usage:
            self.icon.title = build_title(
                self.usage,
                warning=self.settings.month_warning_usd,
                critical=self.settings.month_critical_usd,
                month_cost=self.usage.month_cost,
            )
        elif self.status == "no_key":
            self.icon.title = "OpenAI Usage — no key"
        elif self.status == "loading":
            self.icon.title = "OpenAI Usage — loading…"
        else:
            self.icon.title = "OpenAI Usage — error"

    def _make_menu(self) -> pystray.Menu:
        items: list = []

        if self.usage and self.status in ("ok", "stale", "ratelimit"):
            today_line, month_line = build_summary_lines(self.usage)
            items += [
                pystray.MenuItem(today_line, None, enabled=False),
                pystray.MenuItem(month_line, None, enabled=False),
                pystray.Menu.SEPARATOR,
            ]
            for m in self.usage.models:
                items.append(pystray.MenuItem(build_model_line(m), None, enabled=False))
            items.append(pystray.Menu.SEPARATOR)
            if self.status == "stale":
                items.append(pystray.MenuItem("Network error — retrying…", None, enabled=False))
            elif self.status == "ratelimit":
                items.append(pystray.MenuItem(
                    f"Rate limited, retrying in {self._backoff_s}s…", None, enabled=False,
                ))
            else:
                items.append(pystray.MenuItem(build_last_updated(self.usage), None, enabled=False))
        elif self.status == "no_key":
            items.append(pystray.MenuItem("No API key — open Settings", None, enabled=False))
        elif self.status == "error":
            items.append(pystray.MenuItem("API error — check Settings", None, enabled=False))
        else:
            items.append(pystray.MenuItem("Loading…", None, enabled=False))

        items += [
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Refresh", lambda _i, _it: self._post(self._do_refresh)),
            pystray.MenuItem("Settings…", lambda _i, _it: self._post(self._open_settings)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda _i, _it: self._post(self._do_quit)),
        ]
        return pystray.Menu(*items)

    # ── UI actions (main thread) ──────────────────────────────────────────────

    def _do_refresh(self) -> None:
        """Bypass _backoff_pending — spawns fetch immediately (claude_tray pattern)."""
        threading.Thread(target=self._fetch, daemon=True).start()

    def _open_settings(self) -> None:
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.lift()
            return
        self._settings_win = SettingsWindow(self.root, self.settings, self._on_settings_saved)

    def _on_settings_saved(self, new_settings: Settings) -> None:
        self.settings = new_settings
        if new_settings.api_key:
            self.status = "loading"
            self._refresh_icon()
            self.icon.menu = self._make_menu()
            threading.Thread(target=self._fetch, daemon=True).start()

    def _do_quit(self) -> None:
        self.icon.stop()
        self.root.destroy()


def main() -> None:
    App().run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test (manual)**

```bash
cd /f/Claude/openai_usage_tray_windows
pip install pystray Pillow requests
python main.py
```

Verify:
1. Tray icon appears in system tray (bottom-right)
2. Right-click shows menu — "Loading…" then data or "API error — check Settings"
3. Right-click → Settings… → window opens with sliders and key field
4. Enter a valid API key → Save → icon updates, menu shows data within a few seconds
5. Right-click → Refresh → data refreshes immediately
6. Right-click → Quit → app exits cleanly

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: add main App with pystray polling, backoff guard, and settings"
```

---

## Task 7: Build Script and README

**Files:**
- Create: `openai_usage_tray_windows/build.bat`
- Create: `openai_usage_tray_windows/README.md`

- [ ] **Step 1: Create `build.bat`**

```bat
@echo off
echo Installing dependencies...
pip install -r requirements.txt

echo Building OpenAIUsageTray.exe...
python -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name OpenAIUsageTray ^
    --manifest dpi_aware.manifest ^
    main.py

echo.
echo Done! Executable: dist\OpenAIUsageTray.exe
```

- [ ] **Step 2: Create `README.md`**

```markdown
# OpenAI Usage Tray — Windows

A Windows system tray app that tracks your OpenAI API usage and costs per model, today and this month.

## Features

- Per-model token counts and dollar costs
- Today and this month totals (org-level)
- ⚠ / 🔴 warning and critical monthly spend indicators
- Configurable refresh interval, warning, and critical thresholds
- Exponential backoff on rate limits with sleep/wake guard

## Requirements

- Windows 10 / 11
- Python 3.10+ (or use the pre-built exe)
- An OpenAI [Admin API key](https://platform.openai.com/api-keys) with `usage.read` permission

## Running from source

```bash
pip install -r requirements.txt
python main.py
```

## Building the exe

```bash
build.bat
# Output: dist\OpenAIUsageTray.exe
```

## Settings

Right-click the tray icon → **Settings…**

| Field | Default | Notes |
|-------|---------|-------|
| API Key | — | OpenAI Admin API key (`sk-admin-...`) |
| Refresh interval | 300s | How often to poll (60–3600s) |
| Warning threshold | $50 | Monthly spend warning |
| Critical threshold | $100 | Monthly spend critical alert |

Settings saved to `%APPDATA%\OpenAIUsageTray\settings.json`.
Logs at `%APPDATA%\OpenAIUsageTray\app.log`.

## Architecture

- Main thread: hidden `tkinter` root + GUI queue (all state mutations here)
- `pystray` thread: runs detached, posts callbacks to GUI queue
- Polling thread: daemon thread calling OpenAI API, posts results to GUI queue
- Backoff guard: `_backoff_pending` prevents duplicate retry timers after PC sleep/wake
```

- [ ] **Step 3: Commit**

```bash
git add build.bat README.md
git commit -m "feat: add build script and README"
```

---

## Task 8: Final Check

- [ ] **Step 1: Run all tests**

```bash
cd /f/Claude/openai_usage_tray_windows
python -m pytest tests/ -v
```

Expected: all tests PASS. Verify test count covers `test_api.py`, `test_config.py`, `test_menu_builder.py`, `test_icon_renderer.py`.

- [ ] **Step 2: Verify file structure**

```bash
ls /f/Claude/openai_usage_tray_windows/
ls /f/Claude/openai_usage_tray_windows/tests/
```

Expected files present:
```
main.py  api.py  config.py  menu_builder.py  icon_renderer.py
popup.py  win32_ui.py  requirements.txt  build.bat  dpi_aware.manifest
README.md  pyproject.toml  .gitignore
tests/test_api.py  tests/test_config.py  tests/test_menu_builder.py  tests/test_icon_renderer.py
```

- [ ] **Step 3: Verify git log**

```bash
git log --oneline
```

Expected (newest first):
```
feat: add build script and README
feat: add main App with pystray polling, backoff guard, and settings
feat: add SettingsWindow with API key entry and sliders
feat: add icon_renderer with spend text and cost-level tint
feat: add config module with Windows path and 3600s clamp
feat: copy unchanged modules from macOS and claude_tray
chore: project scaffold
```

- [ ] **Step 4: Push to new GitHub repo**

```bash
cd /f/Claude/openai_usage_tray_windows
gh repo create openai-usage-tray-windows --public --source=. --remote=origin --push
```
