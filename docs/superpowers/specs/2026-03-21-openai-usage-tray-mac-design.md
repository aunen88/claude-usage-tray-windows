# OpenAI Usage Tray — macOS — Design Spec
**Date:** 2026-03-21
**Status:** Draft

---

## Overview

A macOS menu bar app that polls the OpenAI organization usage API and displays per-model token counts and dollar costs for today and the current billing month. Targeted at developers with paid OpenAI API access.

---

## Architecture

**Stack:** Python + `rumps` (macOS menu bar), PyInstaller `.app` bundle.

`rumps` owns the main thread and NSApplication run loop. A `@rumps.timer` decorator drives polling on a background thread. No separate GUI queue or tkinter root is needed — `rumps` provides thread-safe title/menu update methods.

**File structure:**

| File | Responsibility |
|------|---------------|
| `main.py` | `App` class, rumps setup, polling timer, state application |
| `api.py` | OpenAI usage API calls, `UsageData` dataclass |
| `config.py` | Load/save settings to `~/.openai_usage_tray/settings.json` |
| `menu_builder.py` | Builds the dynamic dropdown menu from usage data |
| `build.sh` | PyInstaller `.app` bundle script |
| `requirements.txt` | Python dependencies |
| `README.md` | User-facing docs (see README section below) |

---

## Data & API

**Endpoints:**
- `GET https://api.openai.com/v1/organization/usage/completions?start_time=<unix>&end_time=<unix>&group_by[]=model`
- `GET https://api.openai.com/v1/organization/usage/costs?start_time=<unix>&end_time=<unix>&group_by[]=line_item`

Both endpoints require an **Admin API key** with `usage.read` permission, set by the user in Settings. Auth is `Authorization: Bearer <api_key>`.

**`UsageData` dataclass:**
```python
@dataclass
class UsageData:
    models: list[ModelUsage]        # per-model breakdown
    today_cost: float               # USD
    month_cost: float               # USD
    today_tokens_in: int
    today_tokens_out: int
    month_tokens_in: int
    month_tokens_out: int
    fetched_at: datetime

@dataclass
class ModelUsage:
    model: str
    cost: float                     # USD, today + month combined
    tokens_in: int
    tokens_out: int
```

Two API calls are made per poll: one for today (midnight → now) and one for the current billing month (1st → now). Results are merged into a single `UsageData`.

---

## Display

**Menu bar title:** Today's total cost, e.g. `$4.20`. Shows `?` when no API key is configured or on error.

**Dropdown menu:**
```
Today:       $4.20  |  2.1M in / 0.8M out
This month:  $31.50 |  18M in / 6M out
─────────────────────────────────────────
gpt-4o:        $3.10
gpt-4o-mini:   $1.10
o3-mini:       $0.00
─────────────────────────────────────────
Last updated: 22:34
Refresh
Settings
─────────────────────────────────────────
Quit
```

Models with zero cost are shown but greyed out. Models are sorted by cost descending.

---

## Settings

Stored in `~/.openai_usage_tray/settings.json`:

| Setting | Default | Description |
|---------|---------|-------------|
| `api_key` | `""` | OpenAI Admin API key |
| `refresh_interval` | `300` | Poll interval in seconds (60–600) |
| `warning_threshold` | `50.00` | Monthly spend warning (USD) — turns title orange |
| `critical_threshold` | `100.00` | Monthly spend critical (USD) — turns title red |

Settings window: text field for API key, slider for refresh interval, number fields for thresholds. Includes a "Test connection" button that makes a live API call and shows the result.

---

## Error Handling

| Condition | Menu bar | Menu item |
|-----------|----------|-----------|
| No API key | `?` | "Add API key in Settings" |
| 401 invalid key | `!` | "Invalid API key — check Settings" |
| 429 rate limited | last value (stale) | "Rate limited, retrying in Xs…" |
| Network failure | last value (stale) | "Network error — retrying…" |
| First load / no data yet | `…` | "Loading…" |

**Rate limit handling:** Identical to the Claude tray fix — a `_backoff_pending` guard ensures only one backoff timer is ever queued, preventing a retry storm after sleep/wake. Backoff uses `retry-after` header if present, otherwise exponential up to 15 min cap.

---

## README

The README will cover:
1. What the app shows (per-model tokens + cost, today and this month)
2. **How to get an Admin API key** — OpenAI dashboard → API keys → Create new secret key → Permissions → Usage: Read
3. How to install the `.app` bundle (drag to Applications, allow in Security & Privacy if needed)
4. How to configure (first launch opens Settings, paste API key, click Test)
5. Settings reference (refresh interval, spend thresholds)
6. How to build from source (`pip install -r requirements.txt && sh build.sh`)

---

## Out of Scope

- Windows support (macOS only; `rumps` is macOS-specific)
- ChatGPT Plus subscription usage (consumer accounts have no public usage API)
- Per-project or per-user breakdowns (org-level totals only)
- Historical charts or export
