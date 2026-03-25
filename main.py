"""ClaudeUsageTray – Windows system tray app for Claude Code OAuth usage.

Architecture
------------
• main thread  : hidden tkinter root + event loop (GUI is only safe on this thread)
• pystray      : runs in its own background thread via icon.run_detached()
• polling      : daemon thread, fires every N seconds, posts results to GUI queue
• GUI queue    : queue.Queue drained by root.after() every 50 ms

All state mutations happen on the main thread; background threads only write
to the queue.
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
from PIL import Image

import api as api_module
from api import AuthError, RateLimitError, UsageData
from config import Settings, get_startup_enabled, load_settings, set_startup_enabled
from icon_renderer import render_icon
from popup import DetailWindow, SettingsWindow

# ── Logging ─────────────────────────────────────────────────────────────────

_LOG_DIR = Path(os.environ.get("APPDATA", "~")) / "ClaudeUsageTray"
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

# ── App ──────────────────────────────────────────────────────────────────────

class App:
    """Owns all state; all public methods must be called on the main thread."""

    def __init__(self) -> None:
        self.settings: Settings = load_settings()

        # Usage state (main-thread only after initialisation)
        self.usage: Optional[UsageData] = None
        self.last_updated: Optional[datetime] = None
        self.status: str = "no_token"   # ok | stale | error | no_token | relogin
        self.status_msg: str = ""

        # Cached credentials (main-thread only)
        self._token: Optional[str] = None
        self._refresh_token: Optional[str] = None

        # Window references
        self._detail_win: Optional[tk.Toplevel] = None
        self._settings_win: Optional[tk.Toplevel] = None

        # Cross-thread dispatch queue
        self._gui_q: queue.Queue = queue.Queue()

        # Exponential backoff state for rate-limiting
        self._backoff_s: int = 60   # current backoff duration in seconds
        self._backoff_pending: bool = False  # guard against duplicate backoff timers
        self._backoff_after_id: Optional[str] = None  # root.after() ID for cancellation

        # Hidden tkinter root
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("ClaudeUsageTray")

        # Pystray icon (placeholder until first fetch)
        placeholder = render_icon(None, None, status="no_token")
        try:
            self.icon = pystray.Icon(
                "ClaudeUsageTray",
                icon=placeholder,
                title="Claude Usage \u2013 loading\u2026",
                menu=self._make_menu(),
                on_click=self._on_tray_click,  # pystray >= 0.19 single-click
            )
        except TypeError:
            # Older pystray without on_click — double-click via default=True menu item
            self.icon = pystray.Icon(
                "ClaudeUsageTray",
                icon=placeholder,
                title="Claude Usage \u2013 loading\u2026",
                menu=self._make_menu(),
            )

    # ── Menu ─────────────────────────────────────────────────────────────────

    def _make_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(
                "Show Details",
                lambda _icon, _item: self._post(self._open_detail),
                default=True,
            ),
            pystray.MenuItem(
                "Refresh",
                lambda _icon, _item: self._post(self._do_refresh),
            ),
            pystray.MenuItem(
                "Settings",
                lambda _icon, _item: self._post(self._open_settings),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Start with Windows",
                self._toggle_startup,
                checked=lambda _item: get_startup_enabled(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Exit",
                lambda _icon, _item: self._post(self._do_exit),
            ),
        )

    def _toggle_startup(self, _icon, _item) -> None:  # called from pystray thread
        set_startup_enabled(not get_startup_enabled())

    # ── Cross-thread queue ────────────────────────────────────────────────────

    def _post(self, fn, *args) -> None:
        """Queue a callable to run on the main (tkinter) thread."""
        self._gui_q.put((fn, args))

    def _drain_queue(self) -> None:
        """Drain the GUI queue; rescheduled every 50 ms via root.after()."""
        try:
            while True:
                fn, args = self._gui_q.get_nowait()
                try:
                    fn(*args)
                except Exception:
                    log.exception("GUI queue callback raised an exception")
        except queue.Empty:
            pass
        self.root.after(50, self._drain_queue)

    # ── Polling ───────────────────────────────────────────────────────────────

    def _schedule_next_poll(self) -> None:
        self.root.after(self.settings.refresh_interval * 1000, self._poll_tick)

    def _poll_tick(self) -> None:
        """Main-thread timer callback – fires fetch in a daemon thread."""
        if not self._backoff_pending and self.status not in ("ratelimit", "relogin"):
            threading.Thread(target=self._fetch, daemon=True).start()
        self._schedule_next_poll()

    def _fetch(self) -> None:
        """Background worker – reads token and calls the API."""
        token = self._resolve_token()
        if not token:
            self._post(self._apply_state, None, "no_token", "Token not found in credential files.")
            return

        try:
            data = api_module.fetch_usage(token)
            log.info(
                "Usage: 5h=%.0f%%  7d=%.0f%%  sonnet=%s",
                data.five_hour, data.seven_day,
                f"{data.seven_day_sonnet:.0f}%" if data.seven_day_sonnet is not None else "n/a",
            )
            self._backoff_s = 60   # reset backoff on success
            self._post(self._clear_backoff_pending)
            self._post(self._apply_state, data, "ok", "")

        except AuthError as exc:
            log.warning("Auth error: %s", exc)
            # Clear cached token so next poll re-reads from disk (user may have re-logged in)
            if not self.settings.token_override:
                self._post(self._clear_cached_token)
            self._post(self._apply_state, self.usage, "relogin", str(exc))
            # Exponential backoff for auth errors (60s → 120s → ... → 600s cap)
            # Avoids rapid retries that trigger rate limits
            self._backoff_s = min(self._backoff_s * 2, 600)
            log.info("Auth retry in %ds", self._backoff_s)
            self._post(self._schedule_backoff_fetch, self._backoff_s * 1000)

        except RateLimitError as exc:
            # Use API hint if meaningful, otherwise use exponential backoff (cap 1 hour)
            if exc.retry_after > 0:
                self._backoff_s = min(exc.retry_after, 3600)
            else:
                self._backoff_s = min(self._backoff_s * 2, 3600)
            log.warning("Rate limited – backing off %ds", self._backoff_s)
            self._post(self._apply_state, self.usage, "ratelimit", str(exc))
            self._post(self._schedule_backoff_fetch, self._backoff_s * 1000)

        except Exception as exc:
            # Detect 429 that slipped past the RateLimitError handler (e.g.
            # unparseable retry-after header caused ValueError inside the
            # status-code-429 branch).
            is_429 = "429" in str(exc) or (
                hasattr(exc, "response")
                and getattr(exc.response, "status_code", None) == 429
            )
            if is_429:
                self._backoff_s = min(self._backoff_s * 2, 3600)
                log.warning("Rate limited (fallback) – backing off %ds", self._backoff_s)
                self._post(self._apply_state, self.usage, "ratelimit", str(exc))
                self._post(self._schedule_backoff_fetch, self._backoff_s * 1000)
            else:
                log.error("Fetch failed: %s", exc)
                new_status = "stale" if self.usage else "error"
                self._post(self._apply_state, self.usage, new_status, str(exc))
                # Back off on repeated errors to avoid hammering a failing API
                self._backoff_s = min(self._backoff_s * 2, 900)
                self._post(self._schedule_backoff_fetch, self._backoff_s * 1000)

    def _resolve_token(self) -> Optional[str]:
        """Token priority: override > cached > auto-discovered."""
        if self.settings.token_override:
            return self.settings.token_override
        if self._token:
            return self._token
        token, refresh = api_module.find_credentials()
        # Store on main thread later; this runs in background thread.
        # We can safely read these (GIL-protected attribute write is atomic),
        # but to avoid races we post the assignment.
        if token:
            self._post(self._store_credentials, token, refresh)
        return token

    def _store_credentials(self, token: str, refresh: Optional[str]) -> None:
        self._token = token
        self._refresh_token = refresh

    def _clear_cached_token(self) -> None:
        self._token = None
        self._refresh_token = None

    def _clear_backoff_pending(self) -> None:
        self._backoff_pending = False

    def _schedule_backoff_fetch(self, delay_ms: int) -> None:
        """Schedule a post-backoff fetch; silently drops duplicates (main thread)."""
        if self._backoff_pending:
            log.debug("Backoff fetch already scheduled – skipping duplicate")
            return
        self._backoff_pending = True
        self._backoff_after_id = self.root.after(delay_ms, self._run_backoff_fetch)

    def _cancel_backoff(self) -> None:
        """Cancel any pending backoff timer (main thread)."""
        if self._backoff_after_id is not None:
            self.root.after_cancel(self._backoff_after_id)
            self._backoff_after_id = None
        self._backoff_pending = False

    def _run_backoff_fetch(self) -> None:
        self._backoff_pending = False
        self._backoff_after_id = None
        threading.Thread(target=self._fetch, daemon=True).start()

    # ── State application (main thread) ──────────────────────────────────────

    def _apply_state(
        self,
        usage: Optional[UsageData],
        status: str,
        msg: str,
    ) -> None:
        self.usage = usage
        self.status = status
        self.status_msg = msg
        if status == "ok":
            self.last_updated = datetime.now()
        self._refresh_icon()
        self._refresh_tooltip()

    def _refresh_icon(self) -> None:
        fh = self.usage.five_hour if self.usage else None
        sd = self.usage.seven_day if self.usage else None
        img = render_icon(
            fh, sd,
            warning=self.settings.warning_threshold,
            critical=self.settings.critical_threshold,
            status=self.status,
        )
        self.icon.icon = img

    def _refresh_tooltip(self) -> None:
        if self.usage and self.status not in ("no_token", "relogin"):
            parts = [
                f"5h: {self.usage.five_hour:.0f}%",
                f"7d: {self.usage.seven_day:.0f}%",
            ]
            if self.usage.seven_day_sonnet is not None:
                parts.append(f"Sonnet: {self.usage.seven_day_sonnet:.0f}%")
            if self.status == "stale":
                parts.append("(stale)")
            self.icon.title = "Claude Usage – " + "  |  ".join(parts)
        elif self.status == "no_token":
            self.icon.title = "Claude Usage – token not found (click Settings)"
        elif self.status == "relogin":
            self.icon.title = "Claude Usage – re-login required"
        elif self.status == "ratelimit":
            self.icon.title = "Claude Usage – rate limited, backing off…"
        else:
            self.icon.title = f"Claude Usage – error: {self.status_msg[:60]}"

    # ── UI actions (main thread) ──────────────────────────────────────────────

    def _do_refresh(self) -> None:
        self._cancel_backoff()
        threading.Thread(target=self._fetch, daemon=True).start()

    def _on_tray_click(self, _icon, _button, _time=None) -> None:
        """Called from pystray thread on single left-click."""
        self._post(self._toggle_detail)

    def _toggle_detail(self) -> None:
        """Open flyout if closed; close it (with animation) if already open."""
        if self._detail_win and self._detail_win.winfo_exists():
            try:
                self._detail_win.close()   # DetailWindow.close() triggers fade-out
            except Exception:
                try:
                    self._detail_win.destroy()
                except Exception:
                    pass
            self._detail_win = None
            return
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

    def _open_detail(self) -> None:
        """Called from the 'Show Details' menu item (double-click fallback)."""
        self._toggle_detail()

    def _open_settings(self) -> None:
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.lift()
            self._settings_win.focus_force()
            return
        self._settings_win = SettingsWindow(
            self.root,
            self.settings,
            on_save=self._on_settings_saved,
        )

    def _on_settings_saved(self, new: Settings) -> None:
        self.settings = new
        # Force token re-read in case override changed
        self._token = None
        # Cancel any pending backoff so the stale timer doesn't fire after the
        # immediate fetch below.
        self._cancel_backoff()
        self._backoff_s = 60
        self._refresh_icon()
        # Restart polling with the new interval: cancel old schedule by
        # simply scheduling a new one; the old one will harmlessly re-fire once.
        self._schedule_next_poll()
        threading.Thread(target=self._fetch, daemon=True).start()

    def _do_exit(self) -> None:
        log.info("Exiting.")
        try:
            self.icon.stop()
        except Exception:
            pass
        self.root.quit()

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self) -> None:
        # Initial fetch (no delay)
        threading.Thread(target=self._fetch, daemon=True).start()

        # Start recurring poll after first interval
        self._schedule_next_poll()

        # Start draining the GUI queue
        self.root.after(50, self._drain_queue)

        # Start pystray in its own background thread
        self.icon.run_detached()

        log.info("ClaudeUsageTray started.")

        # Block on tkinter main loop
        try:
            self.root.mainloop()
        finally:
            try:
                self.icon.stop()
            except Exception:
                pass
        log.info("ClaudeUsageTray stopped.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    App().run()


if __name__ == "__main__":
    main()
