# UI Redesign — ClaudeUsageTray
**Date:** 2026-03-21
**Status:** Approved
**Approach:** Option A — Full Windows 11 Flyout

---

## Overview

Redesign the ClaudeUsageTray tray icon and popup window to match a modern Windows 11 aesthetic, inspired by the macOS original. The detail popup becomes a native-feeling flyout anchored to the taskbar with rounded corners, acrylic blur, and system theme awareness. The tray icon gets anti-aliased text via 2× supersampling.

---

## 1. Tray Icon (`icon_renderer.py`)

### What is changing
- **Anti-aliasing:** Currently draws directly at 64×64. Change to render internally at 128×128 then downscale to 64×64 with `Image.LANCZOS`. All coordinate constants (`_SIZE`, text anchor y=17/47, separator y=32, separator endpoints x=8/55) must be doubled for the internal canvas and the final image resized at return.
- **Color scheme:** Remove the solid colored background fill (current dark green/orange/red RGBA). Replace with a transparent or neutral dark background (`#1a1a1a`) and color the **text** instead of the background. This makes the icon look less like a colored rectangle and more like a status indicator.
- **Font:** Change from Consolas Regular (`consola.ttf`) to Consolas Bold (`consolab.ttf`). Add `consolab.ttf` to the font candidate list before `consola.ttf`. Fall back to `consola.ttf` if bold is not present.

### What is unchanged
- Two-line stacked layout (session % top, weekly % bottom) — already implemented
- Threshold-based color logic (green/orange/red) — already implemented, just moves from background to text
- White `?` for error states — unchanged

---

## 2. Flyout Window (`popup.py` — `DetailWindow`)

### Trigger & Positioning
- **Open/close trigger:** `pystray` on Windows maps `default=True` menu items to double-click, not single left-click. Use `pystray`'s `on_click` parameter (available in pystray ≥ 0.19) to bind a single left-click handler. Wire it in `main.py` by passing `on_click=self._on_tray_click` to `pystray.Icon(name, image, menu=..., on_click=self._on_tray_click)`. The `_on_tray_click(icon, button, time)` method posts `_toggle_detail` to the GUI queue. If `on_click` is unavailable (older pystray), fall back to the existing `default=True` double-click behaviour and document the limitation in a comment.
- **Toggle behaviour:** `_toggle_detail` checks `self._detail_win and self._detail_win.winfo_exists()`. If the flyout is open, trigger its fade-out close animation and destroy it. If closed, open it with the slide-up animation. A second tray click closes rather than lifts/refocuses.
- **Position:** Bottom-right of screen, with taskbar clearance determined via `ctypes.windll.shell32.SHAppBarMessage` (`ABM_GETTASKBARPOS`) to get the actual taskbar rect. Fall back to 52px if the call fails. 12px gap between flyout bottom and taskbar top.
- **Width:** 280px (up from current 260px — explicit change).

### Animation (implemented in `popup.py`, not `main.py`)
- **Open:** Slide up from taskbar by 160px over 150ms using a tkinter `after`-loop stepping `y` position. Ease-out: step size decreases each frame.
- **Close:** Fade out (alpha 1.0 → 0.0) over 100ms, then destroy. Triggered by `<Escape>`, `<FocusOut>`, or clicking outside the window.
- **Focus-loss dismiss:** Bind `<FocusOut>` on the `Toplevel`. Add a short `after(50, ...)` delay before dismissing to avoid false triggers from child widget focus transitions.

### Shape & Background
- Borderless: `overrideredirect(True)`
- Rounded corners: call `ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)` inside an `after(0, ...)` callback (after `update_idletasks()`) to ensure the HWND is valid before the call.
- Acrylic blur: call `SetWindowCompositionAttribute` with `ACCENT_ENABLE_ACRYLICBLURBEHIND`. Wrap in `try/except OSError` — if it fails (Windows 10 LTSC, sandboxed environments), fall back to solid background. Detect Windows version via `sys.getwindowsversion().build` — apply acrylic only on build ≥ 17134 (Windows 10 1803+). On builds below 17134 or on failure, use solid fallback immediately.
- **Dark theme fallback:** `#202020` background, light text
- **Light theme fallback:** `#f3f3f3` background, dark text

### Theme Detection
- Read `HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize\AppsUseLightTheme` via `winreg`.
- If the key is absent (e.g. Windows 10 LTSC): **default to dark theme**.
- Read at startup and each time the flyout opens (no restart required).

### Content Layout
```
┌─────────────────────────────┐
│  Claude Usage          ↗    │  ← title (Segoe UI 11pt bold) + link icon
│                             │
│  Session (5h)    35%  ████░ │  ← label strings change from "5hr"/"Week"
│  Weekly  (7d)    71%  █████ │
│  Sonnet  (7d)    --         │  ← hidden (row not rendered) if API returns no data
│                             │
│  Updated 09:54:01           │  ← dim secondary colour
│  [Refresh]      [Settings]  │
└─────────────────────────────┘
```

**Label string changes:** "5hr" → "Session (5h)", "Week" → "Weekly (7d)". Sonnet row hidden entirely (not shown as "--") when `usage.seven_day_sonnet is None`.

### Progress Bars
- Height: 6px, drawn on a `Canvas` widget with rounded ends (`arc` + `rectangle`)
- Colour per row: green/orange/red based on that row's value vs thresholds

### Typography
- Segoe UI 10pt for rows and timestamp
- Segoe UI 11pt Bold for the title

### Dismiss Triggers
- `<Escape>` key
- `<FocusOut>` event (with 50ms debounce)
- Clicking the tray icon again (toggle)

---

## 3. Settings Window (`popup.py` — `SettingsWindow`)

### Style
- Same flyout treatment: borderless, rounded corners, acrylic, theme-aware
- Opens centered on screen

### Layout
```
┌─────────────────────────────┐
│  Settings                   │
│                             │
│  Warning threshold    80%   │  ← slider (0–100)
│  Critical threshold   90%   │  ← slider (0–100)
│  Refresh interval     60s   │  ← slider (10s–300s); values above 300 clamped on load
│                             │
│  Token override             │
│  [________________________] │  ← masked, eye toggle
│  [Test connection]          │  ← async, see below
│  result label (inline)      │
│                             │
│  ☑ Start with Windows       │  ← flat checkbox row (no card grouping)
│                             │
│  [Save]          [Cancel]   │
└─────────────────────────────┘
```

### Changes from current `SettingsWindow`
- **Sliders replace text entries** for all three numeric fields
- **Cancel button replaces "Reset to Defaults"** — Cancel closes without saving
- **Card grouping removed** — flat layout throughout
- **Refresh interval clamped on load:** values > 300 in `settings.json` are clamped to 300 when loaded

### Test Connection Button
- On click: disable button, show "Testing…" in result label, spawn daemon thread calling `api.test_connection(token)`
- `api.test_connection(token)` returns `(success: bool, message: str)` — posts result back to GUI queue
- On result: re-enable button, show ✓ or ✗ + message inline below the token field
- Result label cleared (hidden) each time the Settings window opens

### `api.py` addition
Add `test_connection(token: str) -> tuple[bool, str]`:
- Calls the same `/api/oauth/usage` endpoint
- Returns `(True, "Connected — 35% / 71%")` on success
- Returns `(False, "401 — token rejected")` on 401
- Returns `(False, "Could not reach API")` on network error

---

## 4. Files Affected

| File | Change |
|---|---|
| `icon_renderer.py` | 2× supersampling + LANCZOS downscale; text-colored instead of background-colored; Consolas Bold |
| `popup.py` | Full rewrite of `DetailWindow` (flyout animation, DWM rounding, acrylic, theme); full rewrite of `SettingsWindow` (sliders, Cancel, flat layout, test button) |
| `main.py` | Add `on_click` handler for pystray single-click; no animation logic here |
| `api.py` | Add `test_connection(token)` function |
| `config.py` | Clamp `refresh_interval` to 300 in `load_settings()` after deserialising JSON, before returning the `Settings` object. The slider's 10–300 range prevents new out-of-range values; the load-time clamp fixes existing `settings.json` files. |

---

## 5. Out of Scope

- Notification/toast alerts on threshold crossing
- Usage history or trend graphs
- Multiple account support
- Dark mode tray icon variants
