# UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign ClaudeUsageTray to use a Windows 11 flyout with rounded corners, acrylic blur, system theme awareness, slide/fade animations, and a cleaner settings sheet.

**Architecture:** The existing multi-threaded architecture (tkinter main thread + pystray thread + daemon fetch thread + GUI queue) is unchanged. Only UI rendering code in `popup.py`, `icon_renderer.py`, and the tray-click wiring in `main.py` are modified. New Windows API calls (DWM, acrylic) are isolated in a `win32_ui.py` helper so the rest of the code stays pure Python.

**Tech Stack:** Python 3.11+, tkinter, Pillow, pystray, ctypes (Windows API), winreg

---

## File Map

| File | Role | Change |
|---|---|---|
| `api.py` | Token discovery + API calls | Add `test_connection(token)` |
| `config.py` | Settings load/save | Clamp `refresh_interval` ≤ 300 on load |
| `icon_renderer.py` | Tray icon rendering | 2× supersampling, text-colored, Consolas Bold |
| `win32_ui.py` | **New** – Windows API helpers | DWM rounding, acrylic blur, theme detection, taskbar height |
| `popup.py` | Flyout windows | Full rewrite of `DetailWindow` + `SettingsWindow` |
| `main.py` | App entry point + state | Add `on_click` toggle; rename `_open_detail` → `_toggle_detail` |
| `tests/test_api.py` | **New** – API unit tests | `test_connection` coverage |
| `tests/test_config.py` | **New** – Config unit tests | Clamp coverage |
| `tests/test_icon.py` | **New** – Icon unit tests | Render size + color coverage |

---

## Task 1: `api.py` — Add `test_connection()`

**Files:**
- Modify: `api.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: Create `tests/` scaffolding**

Create these files first so pytest can find the project modules:

`tests/__init__.py` — empty file.

`tests/conftest.py`:
```python
import sys
import pathlib
# Add project root to sys.path so bare `import api` etc. work from any cwd
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
```

Then create `tests/test_api.py`:

```python
"""Unit tests for api.test_connection()."""
from unittest.mock import MagicMock, patch
import api


def _mock_resp(status: int, body: dict | None = None, headers: dict | None = None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body or {}
    r.headers = headers or {}
    r.raise_for_status.return_value = None
    return r


def test_test_connection_success():
    body = {
        "five_hour":  {"utilization": 35.0},
        "seven_day":  {"utilization": 71.0},
    }
    with patch("api.requests.get", return_value=_mock_resp(200, body)):
        ok, msg = api.test_connection("fake-token")
    assert ok is True
    assert "35%" in msg
    assert "71%" in msg


def test_test_connection_401():
    with patch("api.requests.get", return_value=_mock_resp(401)):
        ok, msg = api.test_connection("bad-token")
    assert ok is False
    assert "401" in msg


def test_test_connection_network_error():
    import requests as _req
    with patch("api.requests.get", side_effect=_req.ConnectionError("timeout")):
        ok, msg = api.test_connection("any-token")
    assert ok is False
    assert "reach" in msg.lower()
```

- [ ] **Step 2: Run tests — expect failure (function not defined)**

```
python -m pytest tests/test_api.py -v
```
Expected: `AttributeError: module 'api' has no attribute 'test_connection'`

- [ ] **Step 3: Add `test_connection()` to `api.py`**

Add after the `fetch_usage` function (before the `if __name__ == "__main__":` block):

```python
def test_connection(token: str) -> tuple[bool, str]:
    """One-shot connectivity check.  Returns (success, human-readable message).

    Never raises — all errors are caught and returned as (False, message).
    """
    try:
        resp = requests.get(
            API_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": _BETA,
            },
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        return False, f"Could not reach API — {exc}"

    if resp.status_code == 401:
        return False, "401 — token rejected"
    if resp.status_code == 429:
        return False, "429 — rate limited, try again shortly"

    try:
        resp.raise_for_status()
    except Exception as exc:
        return False, f"HTTP error — {exc}"

    body = resp.json()
    fh = float((body.get("five_hour") or {}).get("utilization", 0))
    sd = float((body.get("seven_day") or {}).get("utilization", 0))
    return True, f"Connected — {fh:.0f}% / {sd:.0f}%"
```

- [ ] **Step 4: Run tests — expect all pass**

```
python -m pytest tests/test_api.py -v
```
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add api.py tests/__init__.py tests/test_api.py
git commit -m "feat: add api.test_connection() for settings UI"
```

---

## Task 2: `config.py` — Clamp `refresh_interval` on Load

**Files:**
- Modify: `config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

```python
"""Unit tests for config.load_settings()."""
import json, tempfile, os
from pathlib import Path
from unittest.mock import patch
import config


def _write_settings(tmp: Path, data: dict) -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "settings.json").write_text(json.dumps(data), encoding="utf-8")


def test_refresh_interval_clamped_above_300():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        _write_settings(p, {"refresh_interval": 9999})
        with patch.object(config, "CONFIG_FILE", p / "settings.json"):
            s = config.load_settings()
    assert s.refresh_interval == 300


def test_refresh_interval_below_300_unchanged():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        _write_settings(p, {"refresh_interval": 120})
        with patch.object(config, "CONFIG_FILE", p / "settings.json"):
            s = config.load_settings()
    assert s.refresh_interval == 120


def test_defaults_when_no_file():
    with patch.object(config, "CONFIG_FILE", Path("/nonexistent/settings.json")):
        s = config.load_settings()
    assert s.refresh_interval == 60
    assert s.warning_threshold == 80
```

- [ ] **Step 2: Run — expect failure**

```
python -m pytest tests/test_config.py -v
```
Expected: `FAILED test_refresh_interval_clamped_above_300`

- [ ] **Step 3: Update `load_settings()` in `config.py`**

Replace the `load_settings` function:

```python
def load_settings() -> Settings:
    if CONFIG_FILE.exists():
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            valid = {k: v for k, v in raw.items() if k in Settings.__dataclass_fields__}
            s = Settings(**valid)
            # Clamp refresh_interval to slider's max (300 s) in case an older
            # settings.json contains a larger value.
            s.refresh_interval = min(s.refresh_interval, 300)
            return s
        except Exception:
            pass
    return Settings()
```

- [ ] **Step 4: Run — expect all pass**

```
python -m pytest tests/test_config.py -v
```
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: clamp refresh_interval to 300s on settings load"
```

---

## Task 3: `icon_renderer.py` — 2× Supersampling + Text Color + Bold Font

**Files:**
- Modify: `icon_renderer.py`
- Create: `tests/test_icon.py`

- [ ] **Step 1: Write failing tests**

```python
"""Unit tests for icon_renderer.render_icon()."""
from PIL import Image
import icon_renderer


def test_output_is_64x64():
    img = icon_renderer.render_icon(20.0, 50.0, status="ok")
    assert img.size == (64, 64)


def test_output_is_rgba():
    img = icon_renderer.render_icon(20.0, 50.0, status="ok")
    assert img.mode == "RGBA"


def test_error_state_returns_image():
    img = icon_renderer.render_icon(None, None, status="error")
    assert img.size == (64, 64)


def test_ok_background_is_dark():
    """Normal state: background should be near #1a1a1a (dark, not colored)."""
    img = icon_renderer.render_icon(20.0, 50.0, status="ok")
    # Sample center pixel — should not be brightly colored
    r, g, b, a = img.getpixel((32, 32))
    # Text pixel may be colored; sample a corner which should be background
    r, g, b, a = img.getpixel((2, 2))
    assert r < 60 and g < 60 and b < 60, f"Expected dark bg, got ({r},{g},{b})"
```

- [ ] **Step 2: Run — record current behavior (some tests may pass, some fail)**

```
python -m pytest tests/test_icon.py -v
```

- [ ] **Step 3: Rewrite `icon_renderer.py`**

Replace the entire file:

```python
"""Pillow-based dynamic tray icon — Windows 11 style.

Renders a 64×64 RGBA image by drawing at 128×128 then downscaling with
LANCZOS for clean anti-aliased text.

Color scheme: dark neutral background (#1a1a1a), text colored by value:
  green  (#55EE55) – below warning
  orange (#FFAA00) – warning ≤ value < critical
  red    (#FF5555) – critical and above

Status variants
---------------
ok       normal two-line rendering
stale    same layout, grey text
error    grey background, "?" label
no_token grey background, "?" label
ratelimit grey background, "?" label
relogin  dark-red background, "!!" label
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

# Internal render size (2× for anti-aliasing); downscaled to _OUT at return
_RENDER = 128
_OUT    = 64

# Bold Consolas preferred; fall back to regular, then other monospace fonts
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/consolab.ttf",  # Consolas Bold
    "C:/Windows/Fonts/consola.ttf",   # Consolas Regular
    "C:/Windows/Fonts/courbd.ttf",    # Courier New Bold
    "C:/Windows/Fonts/cour.ttf",      # Courier New
    "C:/Windows/Fonts/lucon.ttf",     # Lucida Console
    "C:/Windows/Fonts/arialbd.ttf",   # Arial Bold (last resort)
]

_BG_DARK    = (26, 26, 26, 235)     # #1a1a1a – normal background
_BG_GREY    = (75, 75, 75, 225)     # error/unknown background
_BG_RELOGIN = (80, 0, 0, 235)       # dark-red relogin background

_GREEN  = "#55EE55"
_ORANGE = "#FFAA00"
_RED    = "#FF5555"
_GREY   = "#999999"
_WHITE  = "#CCCCCC"


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _text_color(value: float, warning: int, critical: int) -> str:
    if value >= critical:
        return _RED
    if value >= warning:
        return _ORANGE
    return _GREEN


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
        draw.text((cx - w // 2, cy - h // 2), text, fill=fill, font=font)
    except AttributeError:
        try:
            w, h = draw.textsize(text, font=font)  # type: ignore[attr-defined]
            draw.text((cx - w // 2, cy - h // 2), text, fill=fill, font=font)
        except Exception:
            draw.text((cx - 8, cy - 8), text, fill=fill, font=font)


def render_icon(
    five_hour: Optional[float],
    seven_day: Optional[float],
    *,
    warning: int = 80,
    critical: int = 90,
    status: str = "ok",
) -> Image.Image:
    """Return a 64×64 RGBA PIL.Image for the system tray."""
    sz = _RENDER
    img  = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ── Error / unknown states ──────────────────────────────────────────
    if status in ("no_token", "error", "ratelimit") or five_hour is None:
        draw.rectangle([0, 0, sz - 1, sz - 1], fill=_BG_GREY)
        font = _load_font(64)
        _draw_centered(draw, sz // 2, sz // 2, "?", _WHITE, font)
        return img.resize((_OUT, _OUT), Image.LANCZOS)

    if status == "relogin":
        draw.rectangle([0, 0, sz - 1, sz - 1], fill=_BG_RELOGIN)
        font = _load_font(52)
        _draw_centered(draw, sz // 2, sz // 2, "!!", "#FF8888", font)
        return img.resize((_OUT, _OUT), Image.LANCZOS)

    # ── Normal / stale rendering ────────────────────────────────────────
    draw.rectangle([0, 0, sz - 1, sz - 1], fill=_BG_DARK)

    max_val = max(five_hour, seven_day or 0.0)
    if status == "stale":
        line1_color = _GREY
        line2_color = _GREY
    else:
        line1_color = _text_color(five_hour, warning, critical)
        line2_color = _text_color(seven_day or 0.0, warning, critical)

    font = _load_font(40)
    line1 = f"{int(round(five_hour))}%"
    line2 = f"{int(round(seven_day or 0))}%"

    # Text anchors at 2× scale: y=34 (top line), y=94 (bottom line)
    _draw_centered(draw, sz // 2, 34,  line1, line1_color, font)

    # Separator at y=64 (midpoint)
    sep_color = "#444444"
    draw.line([(16, 64), (sz - 17, 64)], fill=sep_color, width=2)

    _draw_centered(draw, sz // 2, 94, line2, line2_color, font)

    return img.resize((_OUT, _OUT), Image.LANCZOS)
```

- [ ] **Step 4: Run tests — expect all pass**

```
python -m pytest tests/test_icon.py -v
```
Expected: `4 passed`

- [ ] **Step 5: Smoke-test visually — launch the app and check the tray icon looks clean**

```
python main.py
```
Check: icon shows two percentage lines with dark background and colored text.

- [ ] **Step 6: Commit**

```bash
git add icon_renderer.py tests/test_icon.py
git commit -m "feat: 2x supersampled tray icon with text-colored theme"
```

---

## Task 4: `win32_ui.py` — Windows API Helpers (New File)

**Files:**
- Create: `win32_ui.py`

This module isolates all ctypes/winreg calls. Every function is safe to call and returns a sensible default on failure.

- [ ] **Step 1: Create `win32_ui.py`**

```python
"""Windows 11 UI helpers — DWM rounded corners, acrylic blur, theme detection.

All public functions are safe to call on any Windows version and return
sensible defaults on failure. Import this module anywhere; it never raises.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import sys
import winreg
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# DwmSetWindowAttribute
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_DEFAULT = 0
DWMWCP_ROUND   = 2

# SetWindowCompositionAttribute / accent policy
WCA_ACCENT_POLICY           = 19
ACCENT_DISABLED             = 0
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4

# Windows build number where acrylic blur was introduced (1803)
_ACRYLIC_MIN_BUILD = 17134

# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------

class _ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState",   ctypes.c_uint),
        ("AccentFlags",   ctypes.c_uint),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId",   ctypes.c_uint),
    ]


class _WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute",  ctypes.c_int),
        ("pData",      ctypes.c_void_p),
        ("SizeOfData", ctypes.c_size_t),
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_light_theme() -> bool:
    """Return True if Windows is in light app theme mode, False for dark.

    Defaults to False (dark) if the registry key is absent (e.g. LTSC).
    """
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return bool(value)
    except OSError:
        return False  # default to dark theme


def apply_rounded_corners(hwnd: int) -> None:
    """Apply DWM rounded corners to a window.

    Must be called after the window is mapped (HWND is valid).
    No-op on Windows 10 or if DWM is unavailable.
    """
    try:
        pref = ctypes.c_int(DWMWCP_ROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(pref),
            ctypes.sizeof(pref),
        )
    except Exception:
        pass  # DWM not available or Windows 10 — corners stay square


def apply_acrylic(hwnd: int, tint_color: int = 0x80000000) -> bool:
    """Apply acrylic blur-behind to a window.  Returns True on success.

    tint_color is ABGR (alpha in high byte).  Default is 50% black.
    Only applied on Windows 10 build 17134+ (1803).
    """
    if sys.getwindowsversion().build < _ACRYLIC_MIN_BUILD:
        return False
    try:
        accent = _ACCENT_POLICY()
        accent.AccentState   = ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.GradientColor = tint_color

        data = _WINDOWCOMPOSITIONATTRIBDATA()
        data.Attribute  = WCA_ACCENT_POLICY
        data.pData      = ctypes.cast(ctypes.byref(accent), ctypes.c_void_p)
        data.SizeOfData = ctypes.sizeof(accent)

        ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
        return True
    except Exception:
        return False


def taskbar_height() -> int:
    """Return the taskbar height in pixels, or 52 if detection fails."""
    try:
        class _APPBARDATA(ctypes.Structure):
            _fields_ = [
                ("cbSize",           ctypes.wintypes.DWORD),
                ("hWnd",             ctypes.wintypes.HWND),
                ("uCallbackMessage", ctypes.wintypes.UINT),
                ("uEdge",            ctypes.wintypes.UINT),
                ("rc",               ctypes.wintypes.RECT),
                ("lParam",           ctypes.wintypes.LPARAM),
            ]

        ABM_GETTASKBARPOS = 0x00000005
        data = _APPBARDATA()
        data.cbSize = ctypes.sizeof(data)
        ctypes.windll.shell32.SHAppBarMessage(ABM_GETTASKBARPOS, ctypes.byref(data))
        rc = data.rc
        # Height = screen_height - rc.top (for bottom-docked taskbar)
        sh = ctypes.windll.user32.GetSystemMetrics(1)  # SM_CYSCREEN
        return sh - rc.top
    except Exception:
        return 52
```

- [ ] **Step 2: Verify import works**

```
python -c "import win32_ui; print('light:', win32_ui.is_light_theme()); print('taskbar:', win32_ui.taskbar_height())"
```
Expected: prints theme and taskbar height without error.

- [ ] **Step 3: Commit**

```bash
git add win32_ui.py
git commit -m "feat: Windows 11 UI helpers (DWM, acrylic, theme, taskbar)"
```

---

## Task 5: `popup.py` — Rewrite `DetailWindow` as Windows 11 Flyout

**Files:**
- Modify: `popup.py`

This is the largest task. Replace the current `DetailWindow` class while keeping `SettingsWindow` temporarily intact (it's rewritten in Task 6).

- [ ] **Step 1: Add palette + animation constants at the top of `popup.py`**

Replace the existing palette block (lines 17–37) with:

```python
import sys
import win32_ui

# ── Theme-aware palette ───────────────────────────────────────────────────────

def _palette() -> dict:
    """Return color tokens based on current Windows theme."""
    light = win32_ui.is_light_theme()
    return {
        "BG":      "#f3f3f3" if light else "#202020",
        "BG_SEC":  "#e8e8e8" if light else "#2c2c2c",
        "FG":      "#1c1c1c" if light else "#f0f0f0",
        "FG_DIM":  "#767676" if light else "#888888",
        "DIVIDER": "#d0d0d0" if light else "#383838",
        "BORDER":  "#c0c0c0" if light else "#404040",
        "GREEN":   "#34C759",
        "ORANGE":  "#FF9500",
        "RED":     "#FF3B30",
        "BLUE":    "#007AFF",
    }

# Static palette used by SettingsWindow (updated in Task 6)
BG      = "#FFFFFF"
BG_SEC  = "#F2F2F7"
FG      = "#1C1C1E"
FG_DIM  = "#8E8E93"
DIVIDER = "#E5E5EA"
BORDER  = "#C6C6C8"
GREEN   = "#34C759"
ORANGE  = "#FF9500"
RED     = "#FF3B30"
BLUE    = "#007AFF"
BLUE_DK = "#0056CC"

# Typography
FONT   = ("Segoe UI", 10)
FONT_B = ("Segoe UI Semibold", 10)
FONT_SM = ("Segoe UI", 8)
FONT_T  = ("Segoe UI Semibold", 12)
FONT_IC = ("Segoe UI", 11)

_WIN_W = 280   # flyout width (px) — changed from 260

# Animation
_SLIDE_PX    = 160   # total slide distance (px)
_SLIDE_MS    = 150   # slide duration (ms)
_SLIDE_STEPS = 12    # number of animation frames
_FADE_MS     = 100   # fade-out duration (ms)
_FADE_STEPS  = 8
```

- [ ] **Step 2: Replace the `DetailWindow` class**

Remove the existing `DetailWindow` class (lines 95–220) and replace with:

```python
class DetailWindow(tk.Toplevel):
    """Windows 11 flyout — slides up from taskbar, acrylic background."""

    def __init__(
        self,
        root: tk.Tk,
        usage: Optional[UsageData],
        last_updated: Optional[datetime],
        settings: Settings,
        *,
        status: str = "ok",
        on_refresh: Callable,
        on_open_settings: Callable,
    ):
        super().__init__(root)
        self._on_refresh       = on_refresh
        self._on_open_settings = on_open_settings
        self._settings         = settings
        self._status           = status
        self._closing          = False   # guard against double-close

        # Read theme once; re-reads on each open via App._toggle_detail
        self._pal = _palette()

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.0)   # start invisible for slide-in

        self._build(usage, last_updated)

        # After widgets exist, apply Windows 11 styling + position + animate
        self.after(0, self._init_win32)

        self.bind("<Escape>", lambda _e: self.close())
        self.bind("<FocusOut>", self._on_focus_out)

    # ── Win32 setup ──────────────────────────────────────────────────────

    def _init_win32(self) -> None:
        self.update_idletasks()
        hwnd = self.winfo_id()
        win32_ui.apply_rounded_corners(hwnd)
        acrylic_ok = win32_ui.apply_acrylic(hwnd, tint_color=0xCC202020)
        if not acrylic_ok:
            # Solid fallback
            self.configure(bg=self._pal["BG"])
        self._position_and_animate()

    # ── Layout ───────────────────────────────────────────────────────────

    def _build(self, usage: Optional[UsageData], last_updated: Optional[datetime]) -> None:
        p = self._pal
        outer = tk.Frame(self, bg=p["BG"], bd=0)
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        # Title bar
        title_row = tk.Frame(outer, bg=p["BG"])
        title_row.pack(fill="x", padx=14, pady=(12, 6))
        tk.Label(
            title_row, text="Claude Usage",
            bg=p["BG"], fg=p["FG"], font=("Segoe UI Semibold", 11),
        ).pack(side="left")

        # Divider
        tk.Frame(outer, bg=p["DIVIDER"], height=1).pack(fill="x")

        # Stats
        stats = tk.Frame(outer, bg=p["BG"])
        stats.pack(fill="x", pady=(8, 4))

        if usage is None:
            msg = {
                "relogin":   "Auth error — re-login to Claude Code",
                "ratelimit": "Rate limited — backing off, will retry",
                "error":     "Could not reach API — check connection",
                "stale":     "Showing last known data — retrying…",
            }.get(self._status, "Fetching data…")
            tk.Label(
                stats, text=msg,
                bg=p["BG"], fg=p["FG_DIM"], font=("Segoe UI", 9),
                wraplength=240, justify="left",
            ).pack(padx=14, pady=8, anchor="w")
        else:
            w = self._settings.warning_threshold
            c = self._settings.critical_threshold
            self._stat_row(stats, "Session (5h)", usage.five_hour, w, c)
            self._stat_row(stats, "Weekly  (7d)", usage.seven_day, w, c)
            if usage.seven_day_sonnet is not None:
                self._stat_row(stats, "Sonnet  (7d)", usage.seven_day_sonnet, w, c)

        # Timestamp
        ts = last_updated.strftime("%H:%M:%S") if last_updated else "never"
        tk.Label(
            outer, text=f"Updated {ts}",
            bg=p["BG"], fg=p["FG_DIM"], font=("Segoe UI", 8),
        ).pack(anchor="w", padx=14, pady=(0, 8))

        # Button row
        tk.Frame(outer, bg=p["DIVIDER"], height=1).pack(fill="x")
        btn_row = tk.Frame(outer, bg=p["BG"])
        btn_row.pack(fill="x", padx=14, pady=10)

        btn_cfg = dict(
            bg=p["BG_SEC"], fg=p["FG"], font=("Segoe UI", 9),
            relief="flat", padx=12, pady=4, cursor="hand2", bd=0,
            activebackground=p["DIVIDER"], activeforeground=p["FG"],
        )
        tk.Button(btn_row, text="Refresh",  command=self._do_refresh,  **btn_cfg).pack(side="left")
        tk.Button(btn_row, text="Settings", command=self._do_settings, **btn_cfg).pack(side="right")

    def _stat_row(
        self, parent: tk.Widget, label: str, value: float, warn: int, crit: int,
    ) -> None:
        p = self._pal
        clr = p["RED"] if value >= crit else p["ORANGE"] if value >= warn else p["GREEN"]

        row = tk.Frame(parent, bg=p["BG"])
        row.pack(fill="x", padx=14, pady=3)

        tk.Label(row, text=label, bg=p["BG"], fg=p["FG"],
                 font=("Segoe UI", 10), width=13, anchor="w").pack(side="left")
        tk.Label(row, text=f"{value:.0f}%", bg=p["BG"], fg=clr,
                 font=("Segoe UI Semibold", 10), width=4, anchor="e").pack(side="left", padx=(0, 8))

        # Rounded progress bar via Canvas
        bar_w, bar_h = 100, 6
        canvas = tk.Canvas(row, width=bar_w, height=bar_h,
                            bg=p["BG"], highlightthickness=0, bd=0)
        canvas.pack(side="left")
        r = bar_h // 2
        # Track
        canvas.create_oval(0, 0, bar_h, bar_h, fill=p["BG_SEC"], outline="")
        canvas.create_rectangle(r, 0, bar_w - r, bar_h, fill=p["BG_SEC"], outline="")
        canvas.create_oval(bar_w - bar_h, 0, bar_w, bar_h, fill=p["BG_SEC"], outline="")
        # Fill
        fill_w = max(bar_h, int(bar_w * min(value, 100) / 100))
        canvas.create_oval(0, 0, bar_h, bar_h, fill=clr, outline="")
        canvas.create_rectangle(r, 0, fill_w - r, bar_h, fill=clr, outline="")
        canvas.create_oval(fill_w - bar_h, 0, fill_w, bar_h, fill=clr, outline="")

    # ── Position + animation ─────────────────────────────────────────────

    def _position_and_animate(self) -> None:
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        tb = win32_ui.taskbar_height()
        w  = max(self.winfo_reqwidth(), _WIN_W)
        h  = max(self.winfo_reqheight(), self.winfo_height())

        x = sw - w - 12
        y_end   = sh - h - tb - 12
        y_start = y_end + _SLIDE_PX

        self.geometry(f"{w}x{h}+{x}+{y_start}")
        self.attributes("-alpha", 1.0)
        self.lift()
        self.after(50, self.focus_force)

        self._animate_slide(x, y_start, y_end, step=0)

    def _animate_slide(self, x: int, y_from: int, y_to: int, step: int) -> None:
        if step >= _SLIDE_STEPS:
            self.geometry(f"+{x}+{y_to}")
            return
        # Ease-out: progress² gives fast start, slow finish
        t = (step + 1) / _SLIDE_STEPS
        ease = 1 - (1 - t) ** 2
        y = int(y_from + (y_to - y_from) * ease)
        self.geometry(f"+{x}+{y}")
        delay = _SLIDE_MS // _SLIDE_STEPS
        self.after(delay, lambda: self._animate_slide(x, y_from, y_to, step + 1))

    # ── Close (fade-out) ─────────────────────────────────────────────────

    def close(self) -> None:
        """Trigger fade-out animation then destroy."""
        if self._closing:
            return
        self._closing = True
        self._animate_fade(step=0)

    def _animate_fade(self, step: int) -> None:
        if step >= _FADE_STEPS:
            self.destroy()
            return
        alpha = 1.0 - (step + 1) / _FADE_STEPS
        try:
            self.attributes("-alpha", alpha)
        except tk.TclError:
            return  # already destroyed
        self.after(_FADE_MS // _FADE_STEPS, lambda: self._animate_fade(step + 1))

    # ── Focus-loss dismiss ───────────────────────────────────────────────

    def _on_focus_out(self, _event) -> None:
        # Debounce: child widget focus transitions fire FocusOut briefly
        self.after(50, self._check_focus)

    def _check_focus(self) -> None:
        try:
            focused = self.focus_displayof()
        except tk.TclError:
            return
        if focused is None or not str(focused).startswith(str(self)):
            self.close()

    # ── Actions ──────────────────────────────────────────────────────────

    def _do_refresh(self) -> None:
        self.close()
        self.after(_FADE_MS + 20, self._on_refresh)

    def _do_settings(self) -> None:
        self.close()
        self.after(_FADE_MS + 20, self._on_open_settings)
```

- [ ] **Step 3: Update `main.py` to call `close()` instead of `destroy()` on `_detail_win`**

In `main.py`, find `_open_detail` and update the lift/focus branch — this is replaced in Task 7, so leave it for now. Just verify the app starts.

- [ ] **Step 4: Run the app and test the flyout manually**

```
python main.py
```
Check:
- Double-clicking tray icon opens flyout
- Flyout slides up from taskbar with animation
- Rounded corners visible
- Background matches system theme (dark/light)
- Escape closes with fade animation
- Clicking elsewhere closes flyout (FocusOut)
- Refresh and Settings buttons work

- [ ] **Step 5: Commit**

```bash
git add popup.py win32_ui.py
git commit -m "feat: Windows 11 flyout DetailWindow with DWM, acrylic, slide/fade"
```

---

## Task 6: `popup.py` — Rewrite `SettingsWindow`

**Files:**
- Modify: `popup.py`

- [ ] **Step 1: Replace the `SettingsWindow` class**

Remove the existing `SettingsWindow` class (lines 225–448 in the original) and replace with:

```python
class SettingsWindow(tk.Toplevel):
    """Settings flyout — same Windows 11 style as DetailWindow."""

    def __init__(
        self,
        root: tk.Tk,
        settings: Settings,
        on_save: Callable[[Settings], None],
    ):
        super().__init__(root)
        self._settings = settings
        self._on_save  = on_save
        self._vars: dict[str, tk.Variable] = {}
        self._closing = False

        self._pal = _palette()
        p = self._pal

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.0)

        self._build()
        self.after(0, self._init_win32)
        self.bind("<Escape>", lambda _e: self.close())
        self.bind("<FocusOut>", self._on_focus_out)

    def _init_win32(self) -> None:
        self.update_idletasks()
        hwnd = self.winfo_id()
        win32_ui.apply_rounded_corners(hwnd)
        acrylic_ok = win32_ui.apply_acrylic(hwnd, tint_color=0xCC202020)
        if not acrylic_ok:
            self.configure(bg=self._pal["BG"])
        self._center_and_show()

    def _build(self) -> None:
        p = self._pal
        outer = tk.Frame(self, bg=p["BG"])
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        # Title
        tk.Label(
            outer, text="Settings",
            bg=p["BG"], fg=p["FG"], font=("Segoe UI Semibold", 11),
        ).pack(anchor="w", padx=14, pady=(14, 8))
        tk.Frame(outer, bg=p["DIVIDER"], height=1).pack(fill="x")

        body = tk.Frame(outer, bg=p["BG"])
        body.pack(fill="both", expand=True, padx=14, pady=8)

        # Threshold sliders
        self._slider_row(body, "Warning threshold",  "warning_threshold",
                         50, 95, self._settings.warning_threshold, "%")
        self._slider_row(body, "Critical threshold", "critical_threshold",
                         60, 100, self._settings.critical_threshold, "%")
        self._slider_row(body, "Refresh interval",   "refresh_interval",
                         10, 300, self._settings.refresh_interval, "s")

        tk.Frame(body, bg=p["DIVIDER"], height=1).pack(fill="x", pady=8)

        # Token override
        tk.Label(body, text="Token override", bg=p["BG"], fg=p["FG"],
                 font=("Segoe UI", 10)).pack(anchor="w")
        self._token_rows(body)

        tk.Frame(body, bg=p["DIVIDER"], height=1).pack(fill="x", pady=8)

        # Startup checkbox
        self._startup_row(body)

        # Footer
        tk.Frame(outer, bg=p["DIVIDER"], height=1).pack(fill="x")
        ftr = tk.Frame(outer, bg=p["BG"])
        ftr.pack(fill="x", padx=14, pady=10)

        btn_cfg = dict(
            font=("Segoe UI", 9), relief="flat", padx=14, pady=5,
            cursor="hand2", bd=0,
        )
        tk.Button(
            ftr, text="Save", command=self._save,
            bg="#007AFF", fg="white",
            activebackground="#0056CC", activeforeground="white",
            **btn_cfg,
        ).pack(side="right")
        tk.Button(
            ftr, text="Cancel", command=self.close,
            bg=p["BG_SEC"], fg=p["FG"],
            activebackground=p["DIVIDER"], activeforeground=p["FG"],
            **btn_cfg,
        ).pack(side="right", padx=(0, 8))

    def _slider_row(
        self, parent: tk.Widget, label: str, key: str,
        from_: int, to: int, default: int, unit: str,
    ) -> None:
        p = self._pal
        var = tk.IntVar(value=default)
        self._vars[key] = var

        row = tk.Frame(parent, bg=p["BG"])
        row.pack(fill="x", pady=4)

        hdr = tk.Frame(row, bg=p["BG"])
        hdr.pack(fill="x")
        tk.Label(hdr, text=label, bg=p["BG"], fg=p["FG"],
                 font=("Segoe UI", 10)).pack(side="left")
        val_str = tk.StringVar(value=f"{default}{unit}")
        tk.Label(hdr, textvariable=val_str, bg=p["BG"], fg=p["FG_DIM"],
                 font=("Segoe UI", 10)).pack(side="right")

        def _on_move(v: str) -> None:
            val_str.set(f"{int(float(v))}{unit}")

        tk.Scale(
            row, from_=from_, to=to,
            orient="horizontal", variable=var, command=_on_move,
            bg=p["BG"], fg=p["FG"], troughcolor=p["BG_SEC"],
            highlightthickness=0, showvalue=False,
            relief="flat", sliderlength=18, bd=0,
        ).pack(fill="x")

    def _token_rows(self, parent: tk.Widget) -> None:
        p = self._pal
        var = tk.StringVar(value=self._settings.token_override)
        self._vars["token_override"] = var

        row = tk.Frame(parent, bg=p["BG"])
        row.pack(fill="x", pady=(4, 0))

        entry = tk.Entry(
            row, textvariable=var,
            bg=p["BG_SEC"], fg=p["FG"], insertbackground=p["FG"],
            relief="flat", width=28, show="●", font=("Segoe UI", 9),
        )
        entry.pack(side="left")

        def _toggle():
            entry.config(show="" if entry.cget("show") else "●")

        eye = tk.Label(row, text="👁", bg=p["BG"], fg=p["FG_DIM"],
                       font=("Segoe UI", 11), cursor="hand2")
        eye.pack(side="left", padx=(6, 0))
        eye.bind("<Button-1>", lambda _e: _toggle())

        # Test connection button + result label
        test_row = tk.Frame(parent, bg=p["BG"])
        test_row.pack(fill="x", pady=(4, 0))

        self._test_result_var = tk.StringVar(value="")
        self._test_btn = tk.Button(
            test_row, text="Test connection",
            bg=p["BG_SEC"], fg=p["FG"], font=("Segoe UI", 9),
            relief="flat", padx=10, pady=3, cursor="hand2", bd=0,
            activebackground=p["DIVIDER"],
            command=self._run_test,
        )
        self._test_btn.pack(side="left")

        tk.Label(
            test_row, textvariable=self._test_result_var,
            bg=p["BG"], fg=p["FG_DIM"], font=("Segoe UI", 9),
        ).pack(side="left", padx=(8, 0))

        tk.Label(
            parent,
            text="Leave blank to auto-detect from credentials file.",
            bg=p["BG"], fg=p["FG_DIM"], font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(2, 0))

    def _run_test(self) -> None:
        import threading
        import api as api_module
        token = self._vars["token_override"].get().strip()
        if not token:
            t, _ = api_module.find_credentials()
            token = t or ""
        if not token:
            self._test_result_var.set("✗ No token found")
            return
        self._test_btn.config(state="disabled")
        self._test_result_var.set("Testing…")

        def _work():
            ok, msg = api_module.test_connection(token)
            self.after(0, lambda: self._show_test_result(ok, msg))

        threading.Thread(target=_work, daemon=True).start()

    def _show_test_result(self, ok: bool, msg: str) -> None:
        try:
            self._test_btn.config(state="normal")
            prefix = "✓" if ok else "✗"
            self._test_result_var.set(f"{prefix} {msg}")
        except tk.TclError:
            pass  # window closed during test

    def _startup_row(self, parent: tk.Widget) -> None:
        p = self._pal
        var = tk.BooleanVar(value=get_startup_enabled())
        self._vars["startup"] = var
        row = tk.Frame(parent, bg=p["BG"])
        row.pack(fill="x")
        tk.Label(row, text="Start with Windows", bg=p["BG"], fg=p["FG"],
                 font=("Segoe UI", 10)).pack(side="left")
        tk.Checkbutton(
            row, variable=var,
            bg=p["BG"], activebackground=p["BG"], selectcolor=p["BG_SEC"],
        ).pack(side="right")

    def _center_and_show(self) -> None:
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w  = max(self.winfo_reqwidth(), 320)
        h  = max(self.winfo_reqheight(), self.winfo_height())
        self.geometry(f"{w}x{h}+{max(0,(sw-w)//2)}+{max(0,(sh-h)//2)}")
        self.attributes("-alpha", 1.0)
        self.lift()
        self.after(50, self.focus_force)

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.destroy()

    def _on_focus_out(self, _event) -> None:
        self.after(50, self._check_focus)

    def _check_focus(self) -> None:
        try:
            focused = self.focus_displayof()
        except tk.TclError:
            return
        if focused is None or not str(focused).startswith(str(self)):
            self.close()

    def _save(self) -> None:
        try:
            new = Settings(
                warning_threshold  = int(self._vars["warning_threshold"].get()),
                critical_threshold = int(self._vars["critical_threshold"].get()),
                refresh_interval   = int(self._vars["refresh_interval"].get()),
                token_override     = self._vars["token_override"].get().strip(),
            )
        except (ValueError, KeyError) as exc:
            return  # shouldn't happen with sliders

        if new.warning_threshold >= new.critical_threshold:
            return  # sliders should prevent this, but guard anyway

        set_startup_enabled(bool(self._vars["startup"].get()))
        save_settings(new)
        self._on_save(new)
        self.close()
```

- [ ] **Step 2: Remove unused imports from the old `SettingsWindow` (`tkinter.messagebox`)**

At the top of `popup.py`, remove:
```python
import tkinter.messagebox
```

- [ ] **Step 3: Run the app and test settings manually**

```
python main.py
```
Check:
- Settings window opens centered, styled like flyout
- Sliders update live values on the right
- Test connection button: disabled during test, shows ✓/✗ result
- Cancel closes without saving
- Save closes and applies settings
- Start with Windows checkbox works

- [ ] **Step 4: Commit**

```bash
git add popup.py
git commit -m "feat: Windows 11 SettingsWindow with sliders, Cancel, test connection"
```

---

## Task 7: `main.py` — Add `on_click` Toggle Handler

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add `_on_tray_click` and `_toggle_detail` methods**

In `main.py`, after `_do_refresh`:

```python
def _on_tray_click(self, _icon, _button, _time=None) -> None:
    """Called from pystray thread on single left-click."""
    self._post(self._toggle_detail)

def _toggle_detail(self) -> None:
    """Open flyout if closed; close it (with animation) if open."""
    if self._detail_win and self._detail_win.winfo_exists():
        try:
            self._detail_win.close()   # DetailWindow.close() triggers fade
        except Exception:
            self._detail_win.destroy()
        self._detail_win = None
        return
    # Re-read theme on each open
    if self.status == "no_token":
        self._open_settings()
        return
    self._detail_win = DetailWindow(
        self.root,
        self.usage,
        self.last_updated,
        self.settings,
        status=self.status,
        on_refresh=self._do_refresh,
        on_open_settings=self._open_settings,
    )
```

- [ ] **Step 2: Wire `on_click` in `pystray.Icon` construction**

In `__init__`, replace:
```python
self.icon = pystray.Icon(
    "ClaudeUsageTray",
    icon=placeholder,
    title="Claude Usage – loading…",
    menu=self._make_menu(),
)
```
With:
```python
try:
    self.icon = pystray.Icon(
        "ClaudeUsageTray",
        icon=placeholder,
        title="Claude Usage – loading…",
        menu=self._make_menu(),
        on_click=self._on_tray_click,  # pystray >= 0.19 single-click
    )
except TypeError:
    # Older pystray without on_click — double-click via default=True menu item
    self.icon = pystray.Icon(
        "ClaudeUsageTray",
        icon=placeholder,
        title="Claude Usage – loading…",
        menu=self._make_menu(),
    )
```

- [ ] **Step 3: Update `_open_detail` to delegate to `_toggle_detail`**

Replace the `_open_detail` method body with:
```python
def _open_detail(self) -> None:
    """Called from the 'Show Details' menu item (double-click fallback)."""
    self._toggle_detail()
```

- [ ] **Step 4: Run full end-to-end test**

```
python main.py
```
Check:
- Single left-click opens flyout (if pystray supports `on_click`)
- Second single left-click closes it with fade animation
- Right-click still shows menu
- "Show Details" in menu still works
- Refresh, Settings, Exit all work correctly

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat: single-click toggle flyout via pystray on_click"
```

---

## Task 8: Final Polish + Build

- [ ] **Step 1: Run all unit tests**

```
python -m pytest tests/ -v
```
Expected: all tests pass.

- [ ] **Step 2: Build the exe**

```
build.bat
```
Expected: `dist\ClaudeUsageTray.exe` created.

- [ ] **Step 3: Smoke-test the exe**

Run `dist\ClaudeUsageTray.exe`. Verify:
- Tray icon appears with dark background and colored percentage text
- Single-click opens flyout (if on pystray >= 0.19)
- Flyout shows correct usage data or status message
- Flyout has rounded corners and acrylic/dark background
- Settings window opens centered with slider controls
- Test connection button works in Settings
- Exit from menu closes the app cleanly

- [ ] **Step 4: Final commit**

```bash
git add .
git commit -m "chore: final Windows 11 UI redesign — all tasks complete"
```
