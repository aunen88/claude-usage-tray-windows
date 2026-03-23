# Design: OpenAI Usage Tray — Windows

**Date:** 2026-03-23
**Project location:** `F:\Claude\openai_usage_tray_windows\`
**GitHub repo:** `openai-usage-tray-windows` (separate from macOS repo)
**Reference:** macOS counterpart at `F:\Claude\openai_usage_tray\`

---

## Overview

A Windows system tray app that tracks OpenAI/ChatGPT API usage and costs per model, today and this month. Feature-identical to the macOS `openai_usage_tray`, ported to Windows using `pystray` + `tkinter`.

---

## Architecture

### Thread Model (mirrors `claude_tray`)

| Thread | Role |
|--------|------|
| Main thread | Hidden `tkinter` root + event loop — all GUI operations here |
| `pystray` thread | Runs detached via `icon.run_detached()`; menu rebuild posts to GUI queue |
| Polling daemon thread | Fires every N seconds, enqueues results |
| GUI queue | `queue.Queue` drained by `root.after(50ms)` |

### Key Design Decisions

- **`_backoff_pending` guard (Windows-specific divergence from macOS)**: The macOS source uses `threading.Lock` + `threading.Timer`. The Windows port adopts the `claude_tray` pattern: `root.after()` on the main thread only — no `threading.Timer`, no lock needed. `_backoff_s` is written on the fetch thread (CPython GIL makes the integer write safe) and read on the main thread inside the `root.after()` callback, sequenced after the fetch thread posts its result to the queue.
- **Manual Refresh and backoff**: The `Refresh` menu item triggers an immediate poll and **bypasses** `_backoff_pending` (adopts `claude_tray` pattern, which has no guard on manual refresh). This differs from the macOS source, which blocks Refresh during active backoff.
- **Menu rebuild**: `pystray` menus are immutable — the entire `pystray.Menu` is reconstructed and reapplied via `icon.menu = ...` on each state change. Executes on the main thread via GUI queue.
- **Settings window**: `tk.Entry` with show/hide eye-toggle button for the API key; `tk.Scale` sliders for all numeric fields — same style as `claude_tray`'s `SettingsWindow`. **Note:** `claude_tray`'s `SettingsWindow` uses `to=600` for the refresh interval slider — the Windows OpenAI port must use `to=3600` instead.
- **Tray icon**: Pillow-rendered 64×64. Normal state renders today's spend as text (e.g. `$4.20`). Warning = amber tint; critical = red tint. Rendered at 128×128, downsampled to 64×64.
- **No auto-start registry**: The Windows auto-start registry toggle present in `claude_tray` is intentionally excluded — the macOS app has no equivalent feature and this port matches the macOS feature set.

---

## Modules

### Reused unchanged from `openai_usage_tray`
- `api.py` — `fetch_usage()`, `ModelUsage`, `UsageData`, `PRICING`, `AuthError`, `RateLimitError`
- `menu_builder.py` — `build_title()`, `build_summary_lines()`, `build_model_line()`, `format_tokens()`, `build_last_updated()`

### Adapted from `openai_usage_tray` (Windows changes)
- `config.py` — Config path changed from `~/.openai_usage_tray/settings.json` to `%APPDATA%\OpenAIUsageTray\settings.json`. `refresh_interval` clamp raised from 600s to 3600s. Fields unchanged: `api_key`, `refresh_interval`, `month_warning_usd`, `month_critical_usd`.

### Copied from `claude_tray`
- `win32_ui.py` — DWM rounded corners, acrylic blur, system theme detection, taskbar height. Uses only `ctypes` and `winreg` (stdlib) — no `pywin32` needed. `taskbar_height()` is present but unused (no `DetailWindow`).

### New (Windows-specific)
- `main.py` — `App` class: tray lifecycle, polling loop, GUI queue drain, backoff guard
- `icon_renderer.py` — Pillow tray icon, today's spend text, cost-level tint. Public interface: `render_icon(today_cost: float, *, warning: float, critical: float) -> PIL.Image.Image`
- `popup.py` — `SettingsWindow(tk.Toplevel)` only. No `DetailWindow` — all usage data displayed in the tray menu.

### Build
- `build.bat` — `PyInstaller --onefile --windowed --icon=icon.ico --manifest=dpi_aware.manifest main.py`
- `requirements.txt` — `pystray`, `Pillow`, `requests`, `pyinstaller`

---

## Tray Menu Layout

The menu content changes based on status. The bottom items (Refresh, Settings, Quit) are always present.

**Status: `ok`**
```
OpenAI Usage
─────────────────────────
Today:      $4.20  |  120k in / 45k out
This month: $38.50 |  890k in / 210k out
─────────────────────────
gpt-4o:  $1.20  |  120k / 45k
gpt-4o-mini:  $0.03  |  45k / 8k
o1-mini:  $0.18  |  12k / 3k
─────────────────────────
Last updated: 14:32 (local time)
─────────────────────────
Refresh
Settings…
Quit
```

**Status: `stale`** — replace last-updated line with:
```
Network error — retrying…
```

**Status: `ratelimit`** — replace last-updated line with:
```
Rate limited, retrying in 120s…
```

**Status: `loading`** — replace data block with:
```
Loading…
```

**Status: `no_key`** — replace data block with:
```
No API key — open Settings
```

**Status: `error`** — replace data block with:
```
API error — check Settings
```

Notes:
- Title indicator: `⚠ OpenAI Usage` when `month_cost >= month_warning_usd`; `🔴 OpenAI Usage` when `month_cost >= month_critical_usd`; from `build_title(data, warning=settings.month_warning_usd, critical=settings.month_critical_usd, month_cost=usage.month_cost)`
- Today/Month lines from `build_summary_lines(data)` two-tuple as-is
- Model lines from `build_model_line(m)` as-is — format: `"{model}:  {cost}  |  {in} / {out}"`; unknown cost shows `—`
- Last-updated line from `build_last_updated(data)` as-is — includes `" (local time)"`

---

## Settings Window

| Field | Type | Default | Range |
|-------|------|---------|-------|
| API Key | `tk.Entry` + eye-toggle (show/hide) | `""` | non-empty string |
| Refresh interval (s) | `tk.Scale` (`to=3600`) | `300` | 60–3600 |
| Warning threshold ($) | `tk.Scale` | `50` | 1–500 |
| Critical threshold ($) | `tk.Scale` | `100` | 1–1000 |

Save → `save_settings()` (writes `%APPDATA%\OpenAIUsageTray\settings.json`) → trigger immediate poll.
Cancel → close with no changes.
Empty API key on Save: inline `tk.Label` error message shown; window stays open.
No auto-start registry toggle.

---

## Polling & Error States

- Daemon thread calls `fetch_usage()` every `refresh_interval` seconds
- Results enqueued; GUI thread drains queue, rebuilds menu
- Exponential backoff on rate-limit: 60s → 120s → 900s cap
- `_backoff_pending` guard: `root.after()` only, main thread, no lock
- Manual Refresh bypasses `_backoff_pending` (spawns fetch thread immediately)

Status strings: `no_key`, `loading`, `ok`, `stale`, `ratelimit`, `error`

`stale` set immediately on non-ratelimit exception when prior data exists. `error` used for both `AuthError` (401) and network errors (no prior data) — both show "API error — check Settings". Tray tooltip reflects current status.

---

## Error Handling

| Condition | Behaviour |
|-----------|-----------|
| No API key | `no_key` status; menu shows "No API key — open Settings" |
| `AuthError` (401) | `error` status; menu shows "API error — check Settings" |
| Network error, no prior data | `error` status; menu shows "API error — check Settings" |
| Network error, prior data exists | `stale` status; last good data shown; menu shows "Network error — retrying…" |
| 429 Rate Limited | `ratelimit` status; backoff with `_backoff_pending` guard; `retry-after` header respected |
| Malformed response | Logged; treated as `error` or `stale`; no crash |

---

## Testing

- `api.py` tests: reused verbatim from `openai_usage_tray/tests/test_api.py`
- `config.py` tests: adapted from `openai_usage_tray/tests/test_config.py` — update config path assertions to `%APPDATA%\OpenAIUsageTray` and update clamp test to assert 3600 upper bound (not 600)
- `menu_builder.py` tests: reused verbatim from `openai_usage_tray/tests/test_menu_builder.py`
- `icon_renderer.py`: unit tests — `render_icon(today_cost, warning=w, critical=c)` returns `PIL.Image.Image` of size 64×64; test for `today_cost` below warning, at warning, and at critical
- `popup.py`: not unit-tested (tkinter GUI); manual smoke test
- `main.py`: not unit-tested (pystray GUI); manual smoke test — including verifying that `_backoff_pending` prevents duplicate backoff callbacks after simulated rapid poll failures

---

## File Structure

```
openai_usage_tray_windows/
├── main.py
├── api.py               # copied from openai_usage_tray
├── config.py            # adapted from openai_usage_tray (path + clamp)
├── menu_builder.py      # copied from openai_usage_tray
├── icon_renderer.py     # new
├── popup.py             # new (SettingsWindow only, no DetailWindow)
├── win32_ui.py          # copied from claude_tray (taskbar_height unused)
├── requirements.txt
├── build.bat
├── dpi_aware.manifest
├── README.md
├── pyproject.toml       # Ruff config (line-length 120, extends B+I) — mirrors claude_tray
└── tests/
    ├── test_api.py
    ├── test_config.py
    ├── test_menu_builder.py
    └── test_icon_renderer.py
```

---

## Known Limitations

- Per-model cost uses hardcoded `PRICING` table — new models show `—` until table is updated
- Costs API is UTC-aligned; "today" boundary may differ from local midnight by up to ±14h (same as macOS)
- `pystray` menus require full rebuild on every state change (acceptable at ≤60 min poll interval)
- `AuthError` (bad key) and general network errors both show "API error — check Settings"; distinguish via `app.log`
- Manual Refresh bypasses active backoff (matches `claude_tray` behavior, not macOS behavior)
- DPI: `dpi_aware.manifest` sets Per-Monitor DPI awareness; extreme scales (300%+) may show minor icon aliasing
