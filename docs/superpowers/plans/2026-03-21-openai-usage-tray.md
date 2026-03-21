# OpenAI Usage Tray — macOS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a macOS menu bar app that polls the OpenAI organization usage API and shows per-model token counts and dollar costs for today and the current billing month.

**Architecture:** Python + `rumps` (NSApplication menu bar), polling via `@rumps.timer` on a background thread, state applied by mutating rumps title/menu items directly. Three concurrent API calls per poll (today tokens, month tokens, billing costs) merged into one `UsageData`. Per-model cost derived from a hardcoded pricing table.

**Tech Stack:** Python 3.11+, `rumps`, `requests`, `pytest`, PyInstaller

---

## File Map

| Path | Purpose |
|------|---------|
| `F:\Claude\openai_usage_tray\api.py` | Dataclasses, pricing table, completions + costs API calls, error types |
| `F:\Claude\openai_usage_tray\config.py` | `Settings` dataclass, load/save to `~/.openai_usage_tray/settings.json` |
| `F:\Claude\openai_usage_tray\menu_builder.py` | Pure functions that build rumps menu item strings from `UsageData` |
| `F:\Claude\openai_usage_tray\main.py` | `App(rumps.App)`, polling timer, state application, backoff guard, settings UI |
| `F:\Claude\openai_usage_tray\requirements.txt` | Pinned deps |
| `F:\Claude\openai_usage_tray\build.sh` | PyInstaller `.app` bundle script |
| `F:\Claude\openai_usage_tray\README.md` | User docs |
| `F:\Claude\openai_usage_tray\.gitignore` | Standard Python + PyInstaller ignores |
| `F:\Claude\openai_usage_tray\tests\__init__.py` | Empty |
| `F:\Claude\openai_usage_tray\tests\test_api.py` | Unit tests for parsing, pricing, pagination, error handling |
| `F:\Claude\openai_usage_tray\tests\test_config.py` | Unit tests for settings load/save |
| `F:\Claude\openai_usage_tray\tests\test_menu_builder.py` | Unit tests for display string formatting |

---

## Task 1: Project Scaffold

**Files:**
- Create: `F:\Claude\openai_usage_tray\` (new git repo)
- Create: `F:\Claude\openai_usage_tray\requirements.txt`
- Create: `F:\Claude\openai_usage_tray\.gitignore`
- Create: `F:\Claude\openai_usage_tray\tests\__init__.py`

- [ ] **Step 1: Create project folder and git repo**

```bash
mkdir F:/Claude/openai_usage_tray
cd F:/Claude/openai_usage_tray
git init
```

- [ ] **Step 2: Write `requirements.txt`**

```
rumps==0.4.0
requests==2.32.3
pyinstaller==6.11.1
pytest==8.3.5
```

- [ ] **Step 3: Write `.gitignore`**

```
__pycache__/
*.pyc
*.pyo
dist/
build/
*.spec
.pytest_cache/
*.egg-info/
.DS_Store
```

- [ ] **Step 4: Create tests package**

```bash
mkdir tests
touch tests/__init__.py
```

- [ ] **Step 5: Install dependencies**

```bash
pip install -r requirements.txt
```

- [ ] **Step 6: Initial commit**

```bash
git add .
git commit -m "chore: project scaffold"
```

---

## Task 2: Config Module

**Files:**
- Create: `F:\Claude\openai_usage_tray\config.py`
- Create: `F:\Claude\openai_usage_tray\tests\test_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_config.py
import json
import os
from pathlib import Path
import pytest
from unittest.mock import patch

def test_default_settings():
    from config import Settings
    s = Settings()
    assert s.api_key == ""
    assert s.refresh_interval == 300
    assert s.month_warning_usd == 50.0
    assert s.month_critical_usd == 100.0

def test_save_and_load_roundtrip(tmp_path):
    from config import Settings, save_settings, load_settings
    with patch("config.CONFIG_FILE", tmp_path / "settings.json"):
        with patch("config.CONFIG_DIR", tmp_path):
            s = Settings(api_key="sk-test", refresh_interval=120,
                         month_warning_usd=25.0, month_critical_usd=75.0)
            save_settings(s)
            loaded = load_settings()
            assert loaded.api_key == "sk-test"
            assert loaded.refresh_interval == 120
            assert loaded.month_warning_usd == 25.0
            assert loaded.month_critical_usd == 75.0

def test_load_missing_file_returns_defaults(tmp_path):
    from config import load_settings
    with patch("config.CONFIG_FILE", tmp_path / "nonexistent.json"):
        s = load_settings()
    assert s.api_key == ""
    assert s.refresh_interval == 300

def test_refresh_interval_clamped_to_600(tmp_path):
    from config import load_settings
    with patch("config.CONFIG_FILE", tmp_path / "settings.json"):
        with patch("config.CONFIG_DIR", tmp_path):
            raw = {"api_key": "", "refresh_interval": 9999,
                   "month_warning_usd": 50.0, "month_critical_usd": 100.0}
            (tmp_path / "settings.json").write_text(json.dumps(raw))
            s = load_settings()
            assert s.refresh_interval == 600

def test_refresh_interval_clamped_to_60(tmp_path):
    from config import load_settings
    with patch("config.CONFIG_FILE", tmp_path / "settings.json"):
        with patch("config.CONFIG_DIR", tmp_path):
            raw = {"api_key": "", "refresh_interval": 0,
                   "month_warning_usd": 50.0, "month_critical_usd": 100.0}
            (tmp_path / "settings.json").write_text(json.dumps(raw))
            s = load_settings()
            assert s.refresh_interval == 60
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd F:/Claude/openai_usage_tray
pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3: Write `config.py`**

```python
"""Load/save settings to ~/.openai_usage_tray/settings.json."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

CONFIG_DIR = Path(os.path.expanduser("~")) / ".openai_usage_tray"
CONFIG_FILE = CONFIG_DIR / "settings.json"


@dataclass
class Settings:
    api_key: str = ""
    refresh_interval: int = 300       # seconds, 60-600
    month_warning_usd: float = 50.0
    month_critical_usd: float = 100.0


def load_settings() -> Settings:
    if CONFIG_FILE.exists():
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            valid = {k: v for k, v in raw.items() if k in Settings.__dataclass_fields__}
            s = Settings(**valid)
            s.refresh_interval = max(60, min(s.refresh_interval, 600))
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
pytest tests/test_config.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: add config module with settings load/save"
```

---

## Task 3: API — Dataclasses and Pricing Table

**Files:**
- Create: `F:\Claude\openai_usage_tray\api.py`
- Create: `F:\Claude\openai_usage_tray\tests\test_api.py`

- [ ] **Step 1: Write failing tests for pricing**

```python
# tests/test_api.py
import pytest

def test_model_usage_defaults():
    from api import ModelUsage
    m = ModelUsage(model="gpt-4o", input_tokens=1_000_000, output_tokens=500_000,
                   month_input_tokens=5_000_000, month_output_tokens=2_000_000,
                   today_cost=None, month_cost=None)
    assert m.model == "gpt-4o"
    assert m.input_tokens == 1_000_000

def test_known_model_cost():
    from api import compute_model_cost, PRICING
    assert "gpt-4o" in PRICING
    cost = compute_model_cost("gpt-4o", input_tokens=1_000_000, output_tokens=500_000)
    # gpt-4o: $2.50/M in, $10.00/M out → $2.50 + $5.00 = $7.50
    assert abs(cost - 7.50) < 0.01

def test_unknown_model_cost_returns_none():
    from api import compute_model_cost
    assert compute_model_cost("gpt-unknown-9000", 100, 100) is None

def test_pricing_table_has_required_models():
    from api import PRICING
    for model in ["gpt-4o", "gpt-4o-mini", "o1", "o3-mini"]:
        assert model in PRICING, f"{model} missing from PRICING table"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_api.py -v
```

Expected: `ModuleNotFoundError: No module named 'api'`

- [ ] **Step 3: Write dataclasses and pricing table in `api.py`**

```python
"""OpenAI organization usage API — dataclasses, pricing, and HTTP calls."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests

log = logging.getLogger(__name__)

_TIMEOUT = 10
_COMPLETIONS_URL = "https://api.openai.com/v1/organization/usage/completions"
_COSTS_URL = "https://api.openai.com/v1/organization/costs"

# ---------------------------------------------------------------------------
# Pricing table — USD per 1M tokens (input, output)
# Update this dict when OpenAI changes prices.
# ---------------------------------------------------------------------------
PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o":               (2.50,  10.00),
    "gpt-4o-2024-11-20":    (2.50,  10.00),
    "gpt-4o-2024-08-06":    (2.50,  10.00),
    "gpt-4o-mini":          (0.15,   0.60),
    "gpt-4o-mini-2024-07-18": (0.15, 0.60),
    "o1":                   (15.00, 60.00),
    "o1-2024-12-17":        (15.00, 60.00),
    "o1-mini":              (1.10,   4.40),
    "o3-mini":              (1.10,   4.40),
    "gpt-4-turbo":          (10.00, 30.00),
    "gpt-4-turbo-2024-04-09": (10.00, 30.00),
    "gpt-4":                (30.00, 60.00),
    "gpt-3.5-turbo":        (0.50,   1.50),
    "gpt-3.5-turbo-0125":   (0.50,   1.50),
}


def compute_model_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> Optional[float]:
    """Return dollar cost for the given token counts, or None if model unknown."""
    pricing = PRICING.get(model)
    if pricing is None:
        return None
    price_in, price_out = pricing
    return (input_tokens / 1_000_000) * price_in + (output_tokens / 1_000_000) * price_out


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ModelUsage:
    model: str
    input_tokens: int               # today
    output_tokens: int              # today
    month_input_tokens: int
    month_output_tokens: int
    today_cost: Optional[float]     # None if model not in PRICING
    month_cost: Optional[float]


@dataclass
class UsageData:
    models: list[ModelUsage]        # sorted by month_cost desc, then name
    today_cost: float               # org-level USD from costs endpoint
    month_cost: float               # org-level USD from costs endpoint
    today_input_tokens: int
    today_output_tokens: int
    month_input_tokens: int
    month_output_tokens: int
    fetched_at: datetime            # local time


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class AuthError(Exception):
    """401 — API key rejected."""


class RateLimitError(Exception):
    """429 — rate limited."""
    def __init__(self, msg: str, retry_after: int = 300):
        super().__init__(msg)
        self.retry_after = retry_after
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_api.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add api.py tests/test_api.py
git commit -m "feat: add api dataclasses and pricing table"
```

---

## Task 4: API — Completions Endpoint

**Files:**
- Modify: `F:\Claude\openai_usage_tray\api.py`
- Modify: `F:\Claude\openai_usage_tray\tests\test_api.py`

- [ ] **Step 1: Add failing tests for completions parsing**

Add to `tests/test_api.py`:

```python
from unittest.mock import MagicMock, patch

def _mock_response(body: dict, status: int = 200, headers: dict | None = None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    r.headers = headers or {}
    r.raise_for_status = MagicMock()
    return r

def test_fetch_completions_single_page():
    from api import fetch_completions
    page = {
        "data": [
            {"model": "gpt-4o",      "input_tokens": 1000, "output_tokens": 500,  "results": []},
            {"model": "gpt-4o-mini", "input_tokens": 2000, "output_tokens": 1000, "results": []},
        ],
        "has_more": False,
        "next_page": None,
    }
    with patch("api.requests.get", return_value=_mock_response(page)):
        result = fetch_completions("sk-test", start_time=0, end_time=1)
    assert result["gpt-4o"] == (1000, 500)
    assert result["gpt-4o-mini"] == (2000, 1000)

def test_fetch_completions_pagination():
    from api import fetch_completions
    page1 = {
        "data": [{"model": "gpt-4o", "input_tokens": 100, "output_tokens": 50, "results": []}],
        "has_more": True,
        "next_page": "tok123",
    }
    page2 = {
        "data": [{"model": "gpt-4o", "input_tokens": 200, "output_tokens": 100, "results": []}],
        "has_more": False,
        "next_page": None,
    }
    responses = [_mock_response(page1), _mock_response(page2)]
    with patch("api.requests.get", side_effect=responses):
        result = fetch_completions("sk-test", start_time=0, end_time=1)
    # tokens should be summed across pages
    assert result["gpt-4o"] == (300, 150)

def test_fetch_completions_401_raises_auth_error():
    from api import fetch_completions, AuthError
    with patch("api.requests.get", return_value=_mock_response({}, status=401)):
        with pytest.raises(AuthError):
            fetch_completions("bad-key", start_time=0, end_time=1)

def test_fetch_completions_429_raises_rate_limit():
    from api import fetch_completions, RateLimitError
    r = _mock_response({}, status=429, headers={"retry-after": "60"})
    with patch("api.requests.get", return_value=r):
        with pytest.raises(RateLimitError) as exc_info:
            fetch_completions("sk-test", start_time=0, end_time=1)
    assert exc_info.value.retry_after == 60
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_api.py::test_fetch_completions_single_page -v
```

Expected: `AttributeError: module 'api' has no attribute 'fetch_completions'`

- [ ] **Step 3: Add `fetch_completions` to `api.py`**

Add after the exceptions section:

```python
def fetch_completions(
    api_key: str,
    start_time: int,
    end_time: int,
) -> dict[str, tuple[int, int]]:
    """Return {model: (input_tokens, output_tokens)} summed across all pages.

    start_time / end_time are Unix timestamps.
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    totals: dict[str, list[int]] = {}
    params: dict = {
        "start_time": start_time,
        "end_time": end_time,
        "group_by[]": "model",
        "limit": 100,
    }

    while True:
        resp = requests.get(_COMPLETIONS_URL, headers=headers, params=params, timeout=_TIMEOUT)
        if resp.status_code == 401:
            raise AuthError("HTTP 401 — API key rejected.")
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("retry-after", 300))
            raise RateLimitError(f"Rate limited — retry in {retry_after}s.", retry_after)
        resp.raise_for_status()

        body = resp.json()
        for bucket in body.get("data", []):
            model = bucket["model"]
            inp = bucket.get("input_tokens", 0)
            out = bucket.get("output_tokens", 0)
            if model not in totals:
                totals[model] = [0, 0]
            totals[model][0] += inp
            totals[model][1] += out

        if not body.get("has_more"):
            break
        params["page"] = body["next_page"]

    return {m: (v[0], v[1]) for m, v in totals.items()}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_api.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add api.py tests/test_api.py
git commit -m "feat: add fetch_completions with pagination and error handling"
```

---

## Task 5: API — Costs Endpoint

**Files:**
- Modify: `F:\Claude\openai_usage_tray\api.py`
- Modify: `F:\Claude\openai_usage_tray\tests\test_api.py`

- [ ] **Step 1: Add failing tests for costs parsing**

Add to `tests/test_api.py`:

```python
def test_fetch_costs_sums_buckets():
    from api import fetch_costs
    body = {
        "data": [
            {"start_time": 1700000000, "results": [{"amount": {"value": 3.10, "currency": "usd"}}]},
            {"start_time": 1700086400, "results": [{"amount": {"value": 1.10, "currency": "usd"}}]},
        ],
        "has_more": False,
    }
    with patch("api.requests.get", return_value=_mock_response(body)):
        month_total, today_cost = fetch_costs("sk-test", month_start=0, today_utc_start=1700086400)
    assert abs(month_total - 4.20) < 0.001
    assert abs(today_cost - 1.10) < 0.001

def test_fetch_costs_today_bucket_absent_returns_zero():
    from api import fetch_costs
    body = {
        "data": [
            {"start_time": 1700000000, "results": [{"amount": {"value": 3.10, "currency": "usd"}}]},
        ],
        "has_more": False,
    }
    with patch("api.requests.get", return_value=_mock_response(body)):
        month_total, today_cost = fetch_costs("sk-test", month_start=0, today_utc_start=1700086400)
    assert abs(month_total - 3.10) < 0.001
    assert today_cost == 0.0

def test_fetch_costs_401_raises_auth_error():
    from api import fetch_costs, AuthError
    with patch("api.requests.get", return_value=_mock_response({}, status=401)):
        with pytest.raises(AuthError):
            fetch_costs("bad-key", month_start=0, today_utc_start=0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_api.py::test_fetch_costs_sums_buckets -v
```

Expected: `AttributeError: module 'api' has no attribute 'fetch_costs'`

- [ ] **Step 3: Add `fetch_costs` to `api.py`**

```python
def fetch_costs(
    api_key: str,
    month_start: int,
    today_utc_start: int,
) -> tuple[float, float]:
    """Return (month_total_usd, today_usd).

    month_start: Unix timestamp of UTC midnight on the 1st of the billing month.
    today_utc_start: Unix timestamp of UTC midnight today.
    """
    from datetime import date, timezone

    headers = {"Authorization": f"Bearer {api_key}"}
    today_utc = date.fromtimestamp(today_utc_start, tz=timezone.utc)

    # Number of days elapsed in the billing month (minimum 1)
    days_elapsed = max(1, (today_utc - date.fromtimestamp(month_start, tz=timezone.utc)).days + 1)

    params = {
        "start_time": month_start,
        "bucket_width": "1d",
        "limit": days_elapsed,
    }

    resp = requests.get(_COSTS_URL, headers=headers, params=params, timeout=_TIMEOUT)
    if resp.status_code == 401:
        raise AuthError("HTTP 401 — API key rejected.")
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("retry-after", 300))
        raise RateLimitError(f"Rate limited — retry in {retry_after}s.", retry_after)
    resp.raise_for_status()

    body = resp.json()
    month_total = 0.0
    today_cost = 0.0

    for bucket in body.get("data", []):
        for result in bucket.get("results", []):
            value = float(result.get("amount", {}).get("value", 0.0))
            month_total += value
            bucket_date = date.fromtimestamp(bucket["start_time"], tz=timezone.utc)
            if bucket_date == today_utc:
                today_cost += value

    return month_total, today_cost
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_api.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add api.py tests/test_api.py
git commit -m "feat: add fetch_costs with bucket parsing and today extraction"
```

---

## Task 6: API — Concurrent Fetch and Merge

**Files:**
- Modify: `F:\Claude\openai_usage_tray\api.py`
- Modify: `F:\Claude\openai_usage_tray\tests\test_api.py`

- [ ] **Step 1: Add failing test for full fetch**

Add to `tests/test_api.py`:

```python
def test_fetch_usage_merges_into_usage_data():
    from api import fetch_usage, UsageData

    completions_today = {"gpt-4o": (1_000_000, 500_000)}
    completions_month = {"gpt-4o": (5_000_000, 2_000_000)}
    costs = (31.50, 4.20)

    with patch("api.fetch_completions", side_effect=[completions_today, completions_month]), \
         patch("api.fetch_costs", return_value=costs):
        data = fetch_usage("sk-test")

    assert isinstance(data, UsageData)
    assert abs(data.today_cost - 4.20) < 0.001
    assert abs(data.month_cost - 31.50) < 0.001
    assert data.today_input_tokens == 1_000_000
    assert data.today_output_tokens == 500_000
    assert data.month_input_tokens == 5_000_000
    assert data.month_output_tokens == 2_000_000
    assert len(data.models) == 1
    m = data.models[0]
    assert m.model == "gpt-4o"
    assert m.input_tokens == 1_000_000
    assert m.month_input_tokens == 5_000_000
    # gpt-4o today cost: 1M * $2.50/M + 0.5M * $10/M = $2.50 + $5.00 = $7.50
    assert abs(m.today_cost - 7.50) < 0.01
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_api.py::test_fetch_usage_merges_into_usage_data -v
```

Expected: `AttributeError: module 'api' has no attribute 'fetch_usage'`

- [ ] **Step 3: Add `fetch_usage` to `api.py`**

Add at the bottom of `api.py`:

```python
def fetch_usage(api_key: str) -> UsageData:
    """Fire all three API calls concurrently and return merged UsageData."""
    import concurrent.futures
    from datetime import date, timezone, timedelta
    import time

    now = datetime.now()
    local_midnight = datetime(now.year, now.month, now.day)
    month_start_local = datetime(now.year, now.month, 1)

    today_utc = date.today()
    month_start_utc = date(today_utc.year, today_utc.month, 1)
    month_start_unix = int(datetime(
        month_start_utc.year, month_start_utc.month, 1,
        tzinfo=timezone.utc
    ).timestamp())
    today_utc_start = int(datetime(
        today_utc.year, today_utc.month, today_utc.day,
        tzinfo=timezone.utc
    ).timestamp())

    now_unix = int(time.time())
    local_midnight_unix = int(local_midnight.timestamp())
    month_start_local_unix = int(month_start_local.timestamp())

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        f_today   = ex.submit(fetch_completions, api_key, local_midnight_unix, now_unix)
        f_month   = ex.submit(fetch_completions, api_key, month_start_local_unix, now_unix)
        f_costs   = ex.submit(fetch_costs, api_key, month_start_unix, today_utc_start)

        today_tokens = f_today.result()    # dict[model, (in, out)]
        month_tokens = f_month.result()
        month_cost, today_cost_val = f_costs.result()

    # Union of all models seen in either window
    all_models = set(today_tokens) | set(month_tokens)

    model_list: list[ModelUsage] = []
    for model in all_models:
        ti, to = today_tokens.get(model, (0, 0))
        mi, mo = month_tokens.get(model, (0, 0))
        model_list.append(ModelUsage(
            model=model,
            input_tokens=ti,
            output_tokens=to,
            month_input_tokens=mi,
            month_output_tokens=mo,
            today_cost=compute_model_cost(model, ti, to),
            month_cost=compute_model_cost(model, mi, mo),
        ))

    # Sort by month_cost desc (None → 0 for sort key), then name
    model_list.sort(key=lambda m: (-(m.month_cost or 0.0), m.model))

    return UsageData(
        models=model_list,
        today_cost=today_cost_val,
        month_cost=month_cost,
        today_input_tokens=sum(t[0] for t in today_tokens.values()),
        today_output_tokens=sum(t[1] for t in today_tokens.values()),
        month_input_tokens=sum(t[0] for t in month_tokens.values()),
        month_output_tokens=sum(t[1] for t in month_tokens.values()),
        fetched_at=datetime.now(),
    )
```

- [ ] **Step 4: Run all tests**

```bash
pytest tests/test_api.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add api.py tests/test_api.py
git commit -m "feat: add fetch_usage concurrent merge"
```

---

## Task 7: Menu Builder

**Files:**
- Create: `F:\Claude\openai_usage_tray\menu_builder.py`
- Create: `F:\Claude\openai_usage_tray\tests\test_menu_builder.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_menu_builder.py
import pytest
from datetime import datetime

def _make_data(today_cost=4.20, month_cost=31.50,
               today_in=2_100_000, today_out=800_000,
               month_in=18_000_000, month_out=6_000_000):
    from api import UsageData, ModelUsage
    models = [
        ModelUsage("gpt-4o", 1_800_000, 600_000, 15_000_000, 5_000_000,
                   today_cost=3.10, month_cost=27.50),
        ModelUsage("gpt-4o-mini", 300_000, 200_000, 3_000_000, 1_000_000,
                   today_cost=1.10, month_cost=4.00),
        ModelUsage("o3-mini", 12_000, 4_000, 100_000, 40_000,
                   today_cost=None, month_cost=None),
    ]
    return UsageData(
        models=models,
        today_cost=today_cost, month_cost=month_cost,
        today_input_tokens=today_in, today_output_tokens=today_out,
        month_input_tokens=month_in, month_output_tokens=month_out,
        fetched_at=datetime(2026, 3, 21, 22, 34, 0),
    )

def test_format_tokens_k():
    from menu_builder import format_tokens
    assert format_tokens(12_000) == "12k"

def test_format_tokens_m():
    from menu_builder import format_tokens
    assert format_tokens(2_100_000) == "2.1M"

def test_format_tokens_m_round():
    from menu_builder import format_tokens
    assert format_tokens(2_000_000) == "2M"

def test_format_tokens_zero():
    from menu_builder import format_tokens
    assert format_tokens(0) == "0"

def test_title_normal():
    from menu_builder import build_title
    data = _make_data(today_cost=4.20)
    assert build_title(data, warning=50.0, critical=100.0, month_cost=31.50) == "$4.20"

def test_title_warning():
    from menu_builder import build_title
    data = _make_data(today_cost=4.20)
    assert build_title(data, warning=50.0, critical=100.0, month_cost=55.0).startswith("⚠")

def test_title_critical():
    from menu_builder import build_title
    data = _make_data(today_cost=4.20)
    assert build_title(data, warning=50.0, critical=100.0, month_cost=105.0).startswith("🔴")

def test_summary_lines():
    from menu_builder import build_summary_lines
    data = _make_data()
    today_line, month_line = build_summary_lines(data)
    assert "$4.20" in today_line
    assert "2.1M" in today_line
    assert "$31.50" in month_line

def test_model_line_known_cost():
    from menu_builder import build_model_line
    from api import ModelUsage
    m = ModelUsage("gpt-4o", 1_800_000, 600_000, 15_000_000, 5_000_000,
                   today_cost=3.10, month_cost=27.50)
    line = build_model_line(m)
    assert "gpt-4o" in line
    assert "$27.50" in line

def test_model_line_unknown_cost():
    from menu_builder import build_model_line
    from api import ModelUsage
    m = ModelUsage("o3-mini", 12_000, 4_000, 100_000, 40_000,
                   today_cost=None, month_cost=None)
    line = build_model_line(m)
    assert "—" in line

def test_last_updated_line():
    from menu_builder import build_last_updated
    data = _make_data()
    line = build_last_updated(data)
    assert "22:34" in line
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_menu_builder.py -v
```

Expected: `ModuleNotFoundError: No module named 'menu_builder'`

- [ ] **Step 3: Write `menu_builder.py`**

```python
"""Pure functions that build menu item strings from UsageData."""
from __future__ import annotations

from typing import Optional
from api import ModelUsage, UsageData


def format_tokens(n: int) -> str:
    if n == 0:
        return "0"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    if n >= 1_000:
        return f"{n // 1_000}k"
    return str(n)


def build_title(
    data: UsageData,
    warning: float,
    critical: float,
    month_cost: float,
) -> str:
    cost_str = f"${data.today_cost:.2f}"
    if month_cost >= critical:
        return f"🔴 {cost_str}"
    if month_cost >= warning:
        return f"⚠ {cost_str}"
    return cost_str


def build_summary_lines(data: UsageData) -> tuple[str, str]:
    today_line = (
        f"Today:      ${data.today_cost:.2f}  |  "
        f"{format_tokens(data.today_input_tokens)} in / "
        f"{format_tokens(data.today_output_tokens)} out"
    )
    month_line = (
        f"This month: ${data.month_cost:.2f}  |  "
        f"{format_tokens(data.month_input_tokens)} in / "
        f"{format_tokens(data.month_output_tokens)} out"
    )
    return today_line, month_line


def build_model_line(m: ModelUsage) -> str:
    cost = f"${m.month_cost:.2f}" if m.month_cost is not None else "—"
    tokens = (
        f"{format_tokens(m.month_input_tokens)} / "
        f"{format_tokens(m.month_output_tokens)}"
    )
    return f"{m.model}:  {cost}  |  {tokens}"


def build_last_updated(data: UsageData) -> str:
    return f"Last updated: {data.fetched_at.strftime('%H:%M')} (local time)"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_menu_builder.py -v
```

Expected: all pass

- [ ] **Step 5: Run full test suite**

```bash
pytest -v
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add menu_builder.py tests/test_menu_builder.py
git commit -m "feat: add menu_builder with display formatting"
```

---

## Task 8: Main App

**Files:**
- Create: `F:\Claude\openai_usage_tray\main.py`

Note: `rumps` only works on macOS and cannot be imported on Windows. TDD is skipped for this file — all testable logic lives in `api.py`, `config.py`, and `menu_builder.py`. Verify `main.py` manually on macOS in Task 10.

- [ ] **Step 1: Write `main.py`**

```python
"""OpenAIUsageTray — macOS menu bar app for OpenAI API usage tracking."""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Optional

import rumps

from api import AuthError, RateLimitError, UsageData, fetch_usage
from config import Settings, load_settings, save_settings
from menu_builder import (
    build_last_updated, build_model_line, build_summary_lines, build_title,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-8s %(message)s")
log = logging.getLogger(__name__)


class OpenAIUsageTrayApp(rumps.App):
    def __init__(self):
        super().__init__("…", quit_button=None)
        self.settings: Settings = load_settings()
        self.usage: Optional[UsageData] = None
        self.status: str = "no_key" if not self.settings.api_key else "loading"
        self._backoff_s: int = 60
        self._backoff_pending: bool = False

        self._build_menu()

        if self.settings.api_key:
            threading.Thread(target=self._fetch, daemon=True).start()

    # ── Menu construction ──────────────────────────────────────────────────

    def _build_menu(self) -> None:
        self.menu.clear()
        if self.usage:
            today_line, month_line = build_summary_lines(self.usage)
            self.menu.add(rumps.MenuItem(today_line))
            self.menu.add(rumps.MenuItem(month_line))
            self.menu.add(rumps.separator)
            for m in self.usage.models:
                self.menu.add(rumps.MenuItem(build_model_line(m)))
            self.menu.add(rumps.separator)
            if self.status == "stale":
                self.menu.add(rumps.MenuItem("Network error — retrying…"))
            elif self.status == "ratelimit":
                self.menu.add(rumps.MenuItem(f"Rate limited, retrying in {self._backoff_s}s…"))
            else:
                self.menu.add(rumps.MenuItem(build_last_updated(self.usage)))
        elif self.status == "no_key":
            self.menu.add(rumps.MenuItem("Add API key in Settings"))
        elif self.status in ("error", "auth_error"):
            self.menu.add(rumps.MenuItem("Invalid API key — check Settings"))
        else:
            self.menu.add(rumps.MenuItem("Loading…"))
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Refresh", callback=self._on_refresh))
        self.menu.add(rumps.MenuItem("Settings", callback=self._on_settings))
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Quit", callback=rumps.quit_application))

    def _update_title(self) -> None:
        if self.status == "no_key":
            self.title = "?"
        elif self.status in ("error", "auth_error"):
            self.title = "!"
        elif self.status == "loading":
            self.title = "…"
        elif self.usage:  # ok, stale, ratelimit — show last known value
            self.title = build_title(
                self.usage,
                warning=self.settings.month_warning_usd,
                critical=self.settings.month_critical_usd,
                month_cost=self.usage.month_cost,
            )

    # ── Polling ────────────────────────────────────────────────────────────

    @rumps.timer(60)
    def _poll(self, _sender) -> None:
        """Fires every 60s; skips if not enough time has elapsed per refresh_interval.

        Note: rumps does not support cancelling a @rumps.timer after creation without
        PyObjC. The timer fires every 60s and checks elapsed time instead. This means
        refresh_interval changes take effect within 60s without a restart.
        """
        if self.status in ("ratelimit",) or self._backoff_pending:
            return
        if self.usage:
            elapsed = (datetime.now() - self.usage.fetched_at).total_seconds()
            if elapsed < self.settings.refresh_interval:
                return
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self) -> None:
        if not self.settings.api_key:
            self.status = "no_key"
            self._update_title()
            self._build_menu()
            return
        try:
            data = fetch_usage(self.settings.api_key)
            self._backoff_s = 60
            self._backoff_pending = False
            self.usage = data
            self.status = "ok"
            log.info("Fetched: today=$%.2f month=$%.2f", data.today_cost, data.month_cost)
        except AuthError as exc:
            log.warning("Auth error: %s", exc)
            self.status = "error"
        except RateLimitError as exc:
            if exc.retry_after > 0:
                self._backoff_s = min(exc.retry_after, 900)
            else:
                self._backoff_s = min(self._backoff_s * 2, 900)
            log.warning("Rate limited — backing off %ds", self._backoff_s)
            self.status = "ratelimit"
            self._schedule_backoff()
        except Exception as exc:
            log.error("Fetch failed: %s", exc)
            self.status = "error" if not self.usage else "stale"
        self._update_title()
        self._build_menu()

    def _schedule_backoff(self) -> None:
        if self._backoff_pending:
            return
        self._backoff_pending = True
        threading.Timer(self._backoff_s, self._backoff_retry).start()

    def _backoff_retry(self) -> None:
        self._backoff_pending = False
        self.status = "loading"
        threading.Thread(target=self._fetch, daemon=True).start()

    # ── UI actions ─────────────────────────────────────────────────────────

    def _on_refresh(self, _sender) -> None:
        threading.Thread(target=self._fetch, daemon=True).start()

    def _on_settings(self, _sender) -> None:
        w = rumps.Window(
            message="Enter your OpenAI Admin API key\n(usage.read permission required):",
            title="Settings — API Key",
            default_text=self.settings.api_key,
            ok="Next", cancel="Cancel",
            dimensions=(400, 24),
        )
        resp = w.run()
        if not resp.clicked:
            return
        new_key = resp.text.strip()

        w2 = rumps.Window(
            message=f"Refresh interval in seconds (60–600):",
            title="Settings — Refresh Interval",
            default_text=str(self.settings.refresh_interval),
            ok="Next", cancel="Cancel",
            dimensions=(200, 24),
        )
        resp2 = w2.run()
        if not resp2.clicked:
            return
        try:
            new_interval = max(60, min(int(resp2.text.strip()), 600))
        except ValueError:
            new_interval = self.settings.refresh_interval

        w3 = rumps.Window(
            message="Monthly spend warning threshold (USD):",
            title="Settings — Warning Threshold",
            default_text=str(self.settings.month_warning_usd),
            ok="Next", cancel="Cancel",
            dimensions=(200, 24),
        )
        resp3 = w3.run()
        if not resp3.clicked:
            return
        try:
            new_warning = float(resp3.text.strip())
        except ValueError:
            new_warning = self.settings.month_warning_usd

        w4 = rumps.Window(
            message="Monthly spend critical threshold (USD):",
            title="Settings — Critical Threshold",
            default_text=str(self.settings.month_critical_usd),
            ok="Save", cancel="Cancel",
            dimensions=(200, 24),
        )
        resp4 = w4.run()
        if not resp4.clicked:
            return
        try:
            new_critical = float(resp4.text.strip())
        except ValueError:
            new_critical = self.settings.month_critical_usd

        self.settings = Settings(
            api_key=new_key,
            refresh_interval=new_interval,
            month_warning_usd=new_warning,
            month_critical_usd=new_critical,
        )
        save_settings(self.settings)

        # Test connection
        if new_key:
            rumps.alert("Testing connection…")
            threading.Thread(target=self._fetch, daemon=True).start()


def main() -> None:
    OpenAIUsageTrayApp().run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add main.py
git commit -m "feat: add main app with rumps polling and settings UI"
```

---

## Task 9: Build Script and README

**Files:**
- Create: `F:\Claude\openai_usage_tray\build.sh`
- Create: `F:\Claude\openai_usage_tray\README.md`

- [ ] **Step 1: Write `build.sh`**

```bash
#!/usr/bin/env bash
set -e

echo "Installing / upgrading build dependencies..."
pip install --upgrade pyinstaller rumps requests

echo ""
echo "Building OpenAIUsageTray.app..."
python -m PyInstaller \
    --windowed \
    --name OpenAIUsageTray \
    --hidden-import rumps \
    --hidden-import requests \
    --collect-all rumps \
    main.py

echo ""
if [ -d "dist/OpenAIUsageTray.app" ]; then
    echo "Build succeeded: dist/OpenAIUsageTray.app"
else
    echo "Build FAILED — check output above."
    exit 1
fi
```

- [ ] **Step 2: Make build script executable**

```bash
chmod +x build.sh
```

- [ ] **Step 3: Write `README.md`**

```markdown
# OpenAI Usage Tray

A macOS menu bar app that shows your OpenAI API token usage and costs at a glance — per model, for today and the current billing month.

![Menu bar showing $4.20 with dropdown](screenshot.png)

## What it shows

- **Today** and **this month** total cost (USD) and token counts (input / output)
- **Per-model breakdown**: cost and tokens for each model you've used
- Spend warning (⚠) and critical (🔴) indicators when monthly spend exceeds your thresholds
- Updates every 5 minutes (configurable)

> **Note:** Per-model costs are derived by multiplying your token counts by a hardcoded pricing table in `api.py`. Costs for models not in the table show `—`. Update the `PRICING` dict in `api.py` if OpenAI changes prices.

> **Timezone note:** Token counts use local midnight for the "today" window. Cost totals use UTC midnight (API limitation). Near UTC midnight, today's tokens and cost may briefly show different periods.

## Requirements

- macOS 12+
- An [OpenAI Admin API key](https://platform.openai.com/api-keys) with **Usage: Read** permission

## Getting an Admin API key

1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Click **Create new secret key**
3. Under **Permissions**, select **Usage: Read**
4. Copy the key — you'll only see it once

## Installation

1. Download `OpenAIUsageTray.app` from the [Releases](../../releases) page
2. Drag it to your **Applications** folder
3. Double-click to open — if macOS blocks it, go to **System Settings → Privacy & Security** and click **Open Anyway**
4. A `?` icon appears in your menu bar — click it, then choose **Settings**
5. Paste your Admin API key and click through the prompts

## Settings

| Setting | Default | Description |
|---------|---------|-------------|
| API Key | — | Your OpenAI Admin API key (`usage.read` scope) |
| Refresh interval | 300s | How often to poll (60–600 seconds) |
| Warning threshold | $50 | Monthly spend that turns the icon ⚠ |
| Critical threshold | $100 | Monthly spend that turns the icon 🔴 |

## Building from source

```bash
git clone https://github.com/aunen88/openai-usage-tray-mac.git
cd openai-usage-tray-mac
pip install -r requirements.txt
sh build.sh
```

The built app will be at `dist/OpenAIUsageTray.app`.

## Running tests

```bash
pytest -v
```

Note: `rumps` is macOS-only. Tests for `api.py`, `config.py`, and `menu_builder.py` run on any platform using mocks. `main.py` requires macOS.
```

- [ ] **Step 4: Commit**

```bash
git add build.sh README.md
git commit -m "feat: add build script and README"
```

---

## Task 10: Final Check and Push

- [ ] **Step 1: Run full test suite**

```bash
pytest -v
```

Expected: all pass

- [ ] **Step 2: Verify project structure**

```bash
ls -1
```

Expected:
```
README.md
api.py
build.sh
config.py
main.py
menu_builder.py
requirements.txt
tests/
```

- [ ] **Step 3: Create GitHub repo and push**

```bash
gh repo create openai-usage-tray-mac --public --source=. --remote=origin --push
```

Or manually:
```bash
git remote add origin https://github.com/aunen88/openai-usage-tray-mac.git
git push -u origin master
```

- [ ] **Step 4: Smoke test on macOS**

On a Mac with Python 3.11+:
```bash
pip install -r requirements.txt
python main.py
```

Expected: `?` appears in the menu bar. Click it → Settings → paste Admin API key → after ~5 seconds the icon updates to `$X.XX`.
