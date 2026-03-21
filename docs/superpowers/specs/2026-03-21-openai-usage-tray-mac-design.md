# OpenAI Usage Tray — macOS — Design Spec
**Date:** 2026-03-21
**Status:** Draft

---

## Overview

A macOS menu bar app that polls the OpenAI organization usage API and displays per-model token counts and dollar costs for today and the current billing month. Targeted at developers with paid OpenAI API access.

---

## Architecture

**Stack:** Python + `rumps` (macOS menu bar), PyInstaller `.app` bundle.

`rumps` owns the main thread and NSApplication run loop. A `@rumps.timer` decorator drives polling on a background thread. State updates are applied by directly mutating `rumps.App` title and menu items, which are thread-safe in rumps.

**File structure:**

| File | Responsibility |
|------|---------------|
| `main.py` | `App` class, rumps setup, polling timer, state application |
| `api.py` | OpenAI usage API calls, `UsageData` / `ModelUsage` dataclasses, pricing table |
| `config.py` | Load/save settings to `~/.openai_usage_tray/settings.json` |
| `menu_builder.py` | Builds the dynamic dropdown menu from usage data |
| `build.sh` | PyInstaller `.app` bundle script |
| `requirements.txt` | `rumps`, `requests`, `pyinstaller` (pinned versions) |
| `README.md` | User-facing docs (see README section below) |

---

## Data & API

### Completions endpoint (tokens)

```
GET https://api.openai.com/v1/organization/usage/completions
  ?start_time=<unix>
  &end_time=<unix>
  &group_by[]=model
  &limit=100
```

Returns paginated results. The app follows `next_page` tokens until exhausted. Response fields are `input_tokens` and `output_tokens` per model bucket.

Two calls per poll: one for today (local midnight → now) and one for the current billing month (1st of month 00:00 local → now). Pagination is handled for both.

### Costs endpoint (dollars)

```
GET https://api.openai.com/v1/organization/costs
  ?start_time=<UTC midnight on 1st of billing month, unix>
  &bucket_width=1d
  &limit=<days_elapsed_in_billing_month>
```

**One fetch per poll**, starting at UTC midnight on the 1st of the current billing month with `limit` set to the number of days elapsed so far. This returns one `1d` bucket per day. The app sums `amount.value` across all returned buckets for the **month total**, and extracts the bucket whose date matches today (UTC) for the **today total**. No separate "today-only" fetch is needed.

If no bucket matching today's UTC date is present (e.g., in the first minutes after UTC midnight before the API closes the previous day's bucket), `today_cost` is set to `0.0`.

Note: the completions endpoint uses **local midnight** for its "today" window while the costs endpoint uses **UTC midnight**. Today's token counts and today's cost total can therefore diverge near UTC midnight. This is a known limitation and is documented in the README.

`bucket_width=1d` buckets are aligned to **UTC midnight**, not local time. Users in non-UTC timezones may see today's cost bucket lag by up to 24 hours near midnight UTC. This is a known limitation and is not worth adding complexity to solve.

The costs endpoint does **not** support `end_time` or per-model grouping. Only org-level cost totals are available from this endpoint.

### Per-model cost derivation

Since the costs endpoint cannot break down by model, per-model cost is **computed** by multiplying token counts (from the completions endpoint) by a hardcoded pricing table in `api.py`. The table covers current OpenAI models (gpt-4o, gpt-4o-mini, o1, o3-mini, etc.) with input/output price per million tokens. Unknown models fall back to `None` cost (shown as `—`). The pricing table is a plain dict constant — easy to update when OpenAI changes prices.

### Auth

Both endpoints require `Authorization: Bearer <api_key>` with an Admin API key scoped to `usage.read`. Configured by the user in Settings.

### `UsageData` dataclass

```python
@dataclass
class ModelUsage:
    model: str
    input_tokens: int           # today
    output_tokens: int          # today
    month_input_tokens: int
    month_output_tokens: int
    today_cost: Optional[float]   # derived from pricing table; None if model unknown
    month_cost: Optional[float]

@dataclass
class UsageData:
    models: list[ModelUsage]      # sorted by month_cost desc, then name
    today_cost: float             # org-level total from costs endpoint (USD)
    month_cost: float             # org-level total from costs endpoint (USD)
    today_input_tokens: int       # sum across all models
    today_output_tokens: int
    month_input_tokens: int
    month_output_tokens: int
    fetched_at: datetime          # local time
```

All three API calls (today tokens, month tokens, costs for the full billing month) are made concurrently using `concurrent.futures.ThreadPoolExecutor` and merged into one `UsageData`.

---

## Display

**Menu bar title:** Today's org-level cost, e.g. `$4.20`. Shows `?` when no API key is configured or on unrecoverable error. Shows `…` on first load.

**Dropdown menu:**
```
Today:       $4.20  |  2.1M in / 0.8M out
This month:  $31.50 |  18M in / 6M out
─────────────────────────────────────────
gpt-4o:        $3.10  |  1.8M / 0.6M
gpt-4o-mini:   $1.10  |  0.3M / 0.2M
o3-mini:          —   |  12k  / 4k
─────────────────────────────────────────
Last updated: 22:34 (local time)
Refresh
Settings
─────────────────────────────────────────
Quit
```

Models are sorted by month cost descending. Models with unknown pricing show `—` for cost. Token counts are humanised (k / M).

---

## Settings

Stored in `~/.openai_usage_tray/settings.json`:

| Setting | Default | Description |
|---------|---------|-------------|
| `api_key` | `""` | OpenAI Admin API key (`usage.read` scope) |
| `refresh_interval` | `300` | Poll interval in seconds (60–600) |
| `month_warning_usd` | `50.0` | Monthly spend warning threshold (USD) |
| `month_critical_usd` | `100.0` | Monthly spend critical threshold (USD) |

**Settings UI:** Implemented as a sequential series of `rumps.Window` prompts (no PyObjC or tkinter required). Each field gets its own prompt dialog. A "Test connection" step fires a live API call and shows the result in a final `rumps.alert`. This avoids any native window dependency.

**Spend thresholds:** At warning/critical levels the menu bar title gains a Unicode prefix (`⚠ $4.20` / `🔴 $4.20`) since `rumps` does not support colored NSAttributedString titles without PyObjC.

---

## Error Handling

| Condition | Menu bar | Status menu item |
|-----------|----------|-----------------|
| No API key | `?` | "Add API key in Settings" |
| 401 invalid key | `!` | "Invalid API key — check Settings" |
| 429 rate limited | last value (stale label) | "Rate limited, retrying in Xs…" |
| Network failure | last value (stale label) | "Network error — retrying…" |
| First load | `…` | "Loading…" |

**Rate limit / sleep-wake guard:** Identical to the Claude tray fix — a `_backoff_pending` boolean ensures only one backoff timer is ever queued. It is mutated exclusively within the `@rumps.timer` callback. Because `rumps` serialises all timer callbacks onto a single background thread, only one callback runs at a time and no lock is needed. Prevents retry storm after sleep/wake. Backoff uses `retry-after` header if present, exponential otherwise, capped at 15 min.

**Request timeout:** 10 seconds on all `requests.get` calls.

---

## README

The README will cover:

1. What the app shows (per-model tokens + cost, today and this month)
2. **How to get an Admin API key** — OpenAI dashboard → API keys → Create new secret key → Permissions → Usage: Read
3. How to install the `.app` bundle (drag to Applications, allow in Security & Privacy if Gatekeeper blocks it)
4. How to configure (first launch opens Settings via sequential prompts, paste API key, test connection)
5. Settings reference (refresh interval, spend thresholds, pricing table note)
6. How to build from source (`pip install -r requirements.txt && sh build.sh`)
7. Note on pricing table: costs shown for unknown models display `—`; users can update the table in `api.py`

---

## Out of Scope

- Windows support (`rumps` is macOS-only)
- ChatGPT Plus subscription usage (no public API)
- Per-project or per-user breakdowns (org-level only)
- Historical charts or export
- Automatic pricing table updates (hardcoded table, manual updates only)
