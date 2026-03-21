"""Token discovery and Anthropic OAuth usage API calls.

Token search order
------------------
1. settings.token_override (if set)
2. %APPDATA%\\Claude\\claude_credentials
3. %USERPROFILE%\\.claude\\claude_credentials

The JSON credential file may use any of several field layouts emitted by
different Claude Code versions:
  {"accessToken": "..."}
  {"access_token": "..."}
  {"claudeAiOauth": {"accessToken": "..."}}   ← macOS-style migrated file
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import requests

log = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/api/oauth/usage"
_BETA = "oauth-2025-04-20"
_TIMEOUT = 10


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class UsageData:
    five_hour: float             # utilisation 0–100
    seven_day: float             # utilisation 0–100
    seven_day_sonnet: Optional[float]   # utilisation 0–100, or None
    five_hour_resets_at: Optional[str]  # ISO-8601 string
    seven_day_resets_at: Optional[str]


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class TokenNotFoundError(Exception):
    """No OAuth token could be discovered on disk."""


class AuthError(Exception):
    """API returned 401 – token invalid or expired."""


class RateLimitError(Exception):
    """API returned 429 – too many requests.  retry_after is in seconds."""
    def __init__(self, msg: str, retry_after: int = 300):
        super().__init__(msg)
        self.retry_after = retry_after


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def _candidate_paths() -> list[Path]:
    appdata = os.environ.get("APPDATA", "")
    home = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    return [
        # Most common on Windows – Claude Code stores credentials here
        Path(home) / ".claude" / ".credentials.json",
        # Legacy / alternative names
        Path(appdata) / "Claude" / "claude_credentials",
        Path(home) / ".claude" / "claude_credentials",
    ]


def _extract(data: dict, *keys: str) -> Optional[str]:
    """Return first non-empty string value matching any of *keys* in *data*."""
    for k in keys:
        v = data.get(k)
        if v and isinstance(v, str):
            return v
    return None


def _parse_access(data: dict) -> Optional[str]:
    direct = _extract(data, "accessToken", "access_token", "oauth_token", "token")
    if direct:
        return direct
    # Nested namespaces used by some Claude Code versions
    for ns in ("claudeAiOauth", "oauth", "credentials"):
        nested = data.get(ns)
        if isinstance(nested, dict):
            found = _extract(nested, "accessToken", "access_token")
            if found:
                return found
    return None


def _parse_refresh(data: dict) -> Optional[str]:
    direct = _extract(data, "refreshToken", "refresh_token")
    if direct:
        return direct
    for ns in ("claudeAiOauth", "oauth", "credentials"):
        nested = data.get(ns)
        if isinstance(nested, dict):
            found = _extract(nested, "refreshToken", "refresh_token")
            if found:
                return found
    return None


def find_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Return *(access_token, refresh_token)*.

    Both may be ``None`` if no credential file is found or parseable.
    """
    for path in _candidate_paths():
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            access = _parse_access(data)
            if access:
                refresh = _parse_refresh(data)
                log.info("Token loaded from %s", path)
                return access, refresh
        except Exception as exc:
            log.warning("Could not parse %s: %s", path, exc)
    return None, None


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------

def fetch_usage(token: str) -> UsageData:
    """Call ``GET /api/oauth/usage`` and return structured usage data.

    Raises
    ------
    AuthError
        HTTP 401 – token rejected.
    requests.HTTPError
        Any other non-2xx response.
    requests.RequestException
        Network-level failure.
    """
    import time

    for attempt in range(2):
        resp = requests.get(
            API_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": _BETA,
            },
            timeout=_TIMEOUT,
        )
        if resp.status_code == 401 and attempt == 0:
            log.warning("Got 401 on first attempt, retrying in 3 s…")
            time.sleep(3)
            continue
        break

    if resp.status_code == 401:
        raise AuthError("HTTP 401 – token rejected. Re-login to Claude Code.")

    if resp.status_code == 429:
        retry_after = int(resp.headers.get("retry-after", 300))
        raise RateLimitError(
            f"Rate limited by API – retry in {retry_after}s.", retry_after
        )

    resp.raise_for_status()

    body = resp.json()
    fh = body.get("five_hour") or {}
    sd = body.get("seven_day") or {}
    sds = body.get("seven_day_sonnet")

    return UsageData(
        five_hour=float(fh.get("utilization", 0)),
        seven_day=float(sd.get("utilization", 0)),
        seven_day_sonnet=float(sds["utilization"]) if sds else None,
        five_hour_resets_at=fh.get("resets_at"),
        seven_day_resets_at=sd.get("resets_at"),
    )


def test_connection(token: str) -> Tuple[bool, str]:
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
        body = resp.json()
        fh = float((body.get("five_hour") or {}).get("utilization", 0))
        sd = float((body.get("seven_day") or {}).get("utilization", 0))
    except Exception as exc:
        return False, f"HTTP error — {exc}"

    return True, f"Connected — {fh:.0f}% / {sd:.0f}%"


# ---------------------------------------------------------------------------
# Quick smoke-test (run this file directly to verify token + API)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.DEBUG)

    token_arg = sys.argv[1] if len(sys.argv) > 1 else None

    if token_arg:
        token = token_arg
        print(f"Using token from command line (first 8 chars): {token[:8]}…")
    else:
        token, refresh = find_credentials()
        if not token:
            print("ERROR: No token found. Check credential file locations or pass token as argument.")
            sys.exit(1)
        print(f"Token found (first 8 chars): {token[:8]}…")
        if refresh:
            print(f"Refresh token present (first 8 chars): {refresh[:8]}…")

    print("Calling API…")
    try:
        data = fetch_usage(token)
        print(f"  five_hour utilization : {data.five_hour:.1f}%  (resets {data.five_hour_resets_at})")
        print(f"  seven_day utilization : {data.seven_day:.1f}%  (resets {data.seven_day_resets_at})")
        if data.seven_day_sonnet is not None:
            print(f"  seven_day_sonnet      : {data.seven_day_sonnet:.1f}%")
        print("OK")
    except AuthError as e:
        print(f"Auth error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
