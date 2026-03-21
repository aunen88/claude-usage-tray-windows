"""Tkinter popup windows – macOS popover-style design.

DetailWindow   – borderless white popover anchored to the bottom-right corner
SettingsWindow – modal settings sheet
"""

from __future__ import annotations

import tkinter as tk
import tkinter.messagebox
from datetime import datetime, timezone
from typing import Callable, Optional

from api import UsageData
from config import Settings, get_startup_enabled, save_settings, set_startup_enabled

# ── Palette (matches macOS native popover) ────────────────────────────────────
BG       = "#FFFFFF"   # popover / card background
BG_SEC   = "#F2F2F7"   # section bg, hover highlight, entry bg
FG       = "#1C1C1E"   # primary text  (macOS label)
FG_DIM   = "#8E8E93"   # secondary text (macOS secondaryLabel)
DIVIDER  = "#E5E5EA"   # hairline rule
BORDER   = "#C6C6C8"   # 1-px window border
GREEN    = "#34C759"   # macOS systemGreen
ORANGE   = "#FF9500"   # macOS systemOrange
RED      = "#FF3B30"   # macOS systemRed
BLUE     = "#007AFF"   # macOS systemBlue  (Sonnet accent)
BLUE_DK  = "#0056CC"   # Save-button hover

# Typography
FONT     = ("Segoe UI", 10)
FONT_B   = ("Segoe UI Semibold", 10)
FONT_SM  = ("Segoe UI", 8)
FONT_T   = ("Segoe UI Semibold", 12)
FONT_IC  = ("Segoe UI", 11)   # icon label

_WIN_W = 260   # fixed popover width (px)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _color(v: float, w: int, c: int) -> str:
    return RED if v >= c else ORANGE if v >= w else GREEN


def _remaining(iso: Optional[str]) -> str:
    """'2h 14m' until the ISO-8601 reset timestamp, or empty string."""
    if not iso:
        return ""
    try:
        target = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        secs   = int((target - datetime.now(timezone.utc)).total_seconds())
        if secs <= 0:
            return ""
        h, r = divmod(secs, 3600)
        return f"{h}h {r // 60}m" if h else f"{r // 60}m"
    except Exception:
        return ""


def _rule(parent: tk.Widget) -> None:
    """1-px horizontal divider."""
    tk.Frame(parent, bg=DIVIDER, height=1).pack(fill="x")


def _action_row(parent: tk.Widget, icon: str, label: str, cmd: Callable) -> None:
    """Flat clickable row with icon + label; highlights on hover."""
    outer = tk.Frame(parent, bg=BG, cursor="hand2")
    outer.pack(fill="x")
    inner = tk.Frame(outer, bg=BG)
    inner.pack(fill="x", padx=14, pady=7)
    w_icon = tk.Label(inner, text=icon, bg=BG, fg=FG, font=FONT_IC)
    w_icon.pack(side="left")
    w_text = tk.Label(inner, text=f"  {label}", bg=BG, fg=FG, font=FONT)
    w_text.pack(side="left")

    all_widgets = (outer, inner, w_icon, w_text)

    def _enter(_e):
        for w in all_widgets:
            w.configure(bg=BG_SEC)

    def _leave(_e):
        for w in all_widgets:
            w.configure(bg=BG)

    for w in all_widgets:
        w.bind("<Enter>", _enter)
        w.bind("<Leave>", _leave)
        w.bind("<Button-1>", lambda _e, c=cmd: c())


# ── Detail window ─────────────────────────────────────────────────────────────

class DetailWindow(tk.Toplevel):
    """Borderless white popover shown on left-click / Show Details."""

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
        self._on_refresh      = on_refresh
        self._on_open_settings = on_open_settings
        self._settings        = settings

        self._status = status

        self.overrideredirect(True)   # no title bar – popover look
        self.configure(bg=BORDER)     # 1-px border via surrounding bg colour
        self.attributes("-topmost", True)

        self._build(usage, last_updated)
        self.after(0, self._position)
        self.bind("<Escape>", lambda _e: self.destroy())

    # ------------------------------------------------------------------

    def _build(self, usage: Optional[UsageData], last_updated: Optional[datetime]) -> None:
        # Inner frame – 1-px inset gives the border effect
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=1, pady=1)

        # ── Stats section ───────────────────────────────────────────────
        stats = tk.Frame(wrap, bg=BG)
        stats.pack(fill="x", pady=(6, 2))

        if usage is None:
            msg = {
                "relogin":   "Auth error  —  re-login to Claude Code",
                "ratelimit": "Rate limited by API  —  backing off, will retry",
                "error":     "Could not reach the API  —  check your connection",
                "stale":     "Showing last known data  —  retrying…",
            }.get(self._status, "Fetching data…")
            tk.Label(
                stats, text=msg,
                bg=BG, fg=FG_DIM, font=FONT_SM,
            ).pack(padx=14, pady=10)
        else:
            w = self._settings.warning_threshold
            c = self._settings.critical_threshold
            self._stat_row(stats, "⏱", "5hr",    usage.five_hour,        w, c,
                           _remaining(usage.five_hour_resets_at))
            self._stat_row(stats, "📅", "Week",   usage.seven_day,        w, c,
                           _remaining(usage.seven_day_resets_at))
            if usage.seven_day_sonnet is not None:
                self._stat_row(stats, "◆", "Sonnet", usage.seven_day_sonnet, w, c,
                               icon_color=BLUE)

        # Last updated – subtle caption under the stats
        ts = last_updated.strftime("%H:%M:%S") if last_updated else "never"
        tk.Label(
            wrap, text=f"Last updated: {ts}",
            bg=BG, fg=FG_DIM, font=FONT_SM,
        ).pack(anchor="w", padx=14, pady=(0, 6))

        # ── Actions ─────────────────────────────────────────────────────
        _rule(wrap)
        _action_row(wrap, "↻", "Refresh",  self._do_refresh)
        _action_row(wrap, "⚙", "Settings", self._do_settings)

        # ── Quit ────────────────────────────────────────────────────────
        _rule(wrap)
        _action_row(wrap, "⏻", "Exit", self.destroy)

    def _stat_row(
        self,
        parent: tk.Widget,
        icon: str,
        label: str,
        value: float,
        w: int,
        c: int,
        rem: str = "",
        *,
        icon_color: Optional[str] = None,
    ) -> None:
        clr = _color(value, w, c)
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=14, pady=4)

        fg_icon = icon_color if icon_color else FG_DIM
        tk.Label(row, text=icon, bg=BG, fg=fg_icon, font=FONT_IC).pack(side="left")
        # Bold "Label: XX%"
        tk.Label(
            row,
            text=f"  {label}: ",
            bg=BG, fg=FG, font=FONT_B,
        ).pack(side="left")
        tk.Label(row, text=f"{value:.0f}%", bg=BG, fg=clr, font=FONT_B).pack(side="left")
        # Time remaining on the right
        if rem:
            tk.Label(row, text=rem, bg=BG, fg=FG_DIM, font=FONT_SM).pack(side="right")

    def _position(self) -> None:
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        # Enforce minimum width; height is driven by content
        w  = max(self.winfo_reqwidth(), self.winfo_width(), _WIN_W + 2)
        h  = max(self.winfo_reqheight(), self.winfo_height())
        # Set explicit geometry so the width is always consistent
        self.geometry(f"{w}x{h}+{max(0, sw - w - 12)}+{max(0, sh - h - 52)}")
        self.lift()
        self.after(50, self.focus_force)

    def _do_refresh(self) -> None:
        self.destroy()
        self._on_refresh()

    def _do_settings(self) -> None:
        self.destroy()
        self._on_open_settings()


# ── Settings window ───────────────────────────────────────────────────────────

class SettingsWindow(tk.Toplevel):
    """Clean settings sheet matching the macOS aesthetics."""

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

        self.title("Claude Usage – Settings")
        self.resizable(False, False)
        self.configure(bg=BG_SEC)
        self.attributes("-topmost", True)

        self._build()
        self.after(0, self._center)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # ------------------------------------------------------------------

    def _build(self) -> None:
        # ── Header ──────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=BG)
        hdr.pack(fill="x")
        tk.Label(
            hdr, text="◑  Claude Usage  –  Settings",
            bg=BG, fg=FG, font=FONT_T,
        ).pack(side="left", padx=16, pady=14)
        _rule(self)

        # ── Body ────────────────────────────────────────────────────────
        body = tk.Frame(self, bg=BG_SEC)
        body.pack(fill="both", expand=True)

        # Thresholds
        self._section_label(body, "THRESHOLDS")
        card = self._card(body)
        self._slider_row(card, "Warning (%)",  "warning_threshold",
                         50,  95, self._settings.warning_threshold)
        _rule(card)
        self._slider_row(card, "Critical (%)", "critical_threshold",
                         60, 100, self._settings.critical_threshold)

        # Polling
        self._section_label(body, "POLLING")
        card2 = self._card(body)
        self._entry_row(card2, "Refresh interval (s)", "refresh_interval",
                        str(self._settings.refresh_interval))

        # Token override
        self._section_label(body, "TOKEN OVERRIDE")
        card3 = self._card(body)
        self._token_rows(card3)

        # Startup
        self._section_label(body, "SYSTEM")
        card4 = self._card(body)
        self._startup_row(card4)

        # ── Footer ──────────────────────────────────────────────────────
        _rule(self)
        ftr = tk.Frame(self, bg=BG)
        ftr.pack(fill="x")

        rst = tk.Label(
            ftr, text="Reset to Defaults",
            bg=BG, fg=RED, font=FONT, cursor="hand2",
        )
        rst.pack(side="left", padx=16, pady=10)
        rst.bind("<Button-1>", lambda _e: self._reset())

        tk.Button(
            ftr, text="Save", command=self._save,
            bg=BLUE, fg="white", font=FONT_B,
            relief="flat", padx=16, pady=5,
            activebackground=BLUE_DK, activeforeground="white",
            cursor="hand2", bd=0,
        ).pack(side="right", padx=16, pady=10)

    # ------------------------------------------------------------------

    def _section_label(self, parent: tk.Widget, text: str) -> None:
        tk.Label(
            parent, text=text,
            bg=BG_SEC, fg=FG_DIM, font=FONT_SM,
        ).pack(anchor="w", padx=20, pady=(10, 2))

    def _card(self, parent: tk.Widget) -> tk.Frame:
        f = tk.Frame(parent, bg=BG)
        f.pack(fill="x", padx=16, pady=(0, 4))
        return f

    def _slider_row(
        self, parent: tk.Widget,
        label: str, key: str,
        from_: int, to: int, default: int,
    ) -> None:
        var = tk.IntVar(value=default)
        self._vars[key] = var

        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=14, pady=8)

        # Label row with live value on the right
        hdr = tk.Frame(row, bg=BG)
        hdr.pack(fill="x")
        tk.Label(hdr, text=label, bg=BG, fg=FG, font=FONT).pack(side="left")
        val_str = tk.StringVar(value=f"{default}%")
        tk.Label(hdr, textvariable=val_str, bg=BG, fg=FG_DIM, font=FONT).pack(side="right")

        def _on_move(v: str) -> None:
            val_str.set(f"{int(float(v))}%")

        tk.Scale(
            row, from_=from_, to=to,
            orient="horizontal", variable=var, command=_on_move,
            bg=BG, fg=FG, troughcolor=BG_SEC,
            highlightthickness=0, showvalue=False,
            relief="flat", sliderlength=18, bd=0,
        ).pack(fill="x", pady=(4, 0))

    def _entry_row(
        self, parent: tk.Widget,
        label: str, key: str, default: str,
    ) -> None:
        var = tk.StringVar(value=default)
        self._vars[key] = var
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=14, pady=10)
        tk.Label(row, text=label, bg=BG, fg=FG, font=FONT).pack(side="left")
        tk.Entry(
            row, textvariable=var,
            bg=BG_SEC, fg=FG, insertbackground=FG,
            relief="flat", width=6, font=FONT,
        ).pack(side="right")

    def _token_rows(self, parent: tk.Widget) -> None:
        var = tk.StringVar(value=self._settings.token_override)
        self._vars["token_override"] = var

        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=14, pady=(10, 0))

        entry = tk.Entry(
            row, textvariable=var,
            bg=BG_SEC, fg=FG, insertbackground=FG,
            relief="flat", width=26, show="●", font=FONT,
        )
        entry.pack(side="left")

        def _toggle():
            entry.config(show="" if entry.cget("show") else "●")

        eye = tk.Label(row, text="👁", bg=BG, fg=FG_DIM,
                       font=("Segoe UI", 11), cursor="hand2")
        eye.pack(side="left", padx=(6, 0))
        eye.bind("<Button-1>", lambda _e: _toggle())

        tk.Label(
            parent,
            text="Leave blank to auto-detect from credentials file.",
            bg=BG, fg=FG_DIM, font=FONT_SM,
        ).pack(anchor="w", padx=14, pady=(4, 8))

    def _startup_row(self, parent: tk.Widget) -> None:
        var = tk.BooleanVar(value=get_startup_enabled())
        self._vars["startup"] = var
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=14, pady=10)
        tk.Label(row, text="Start with Windows", bg=BG, fg=FG, font=FONT).pack(side="left")
        tk.Checkbutton(
            row, variable=var,
            bg=BG, activebackground=BG, selectcolor=BG_SEC,
        ).pack(side="right")

    def _center(self) -> None:
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w  = max(self.winfo_reqwidth(),  self.winfo_width())
        h  = max(self.winfo_reqheight(), self.winfo_height())
        self.geometry(f"+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2)}")
        self.lift()
        self.after(50, self.focus_force)

    # ------------------------------------------------------------------

    def _reset(self) -> None:
        d = Settings()
        self._vars["warning_threshold"].set(d.warning_threshold)
        self._vars["critical_threshold"].set(d.critical_threshold)
        self._vars["refresh_interval"].set(str(d.refresh_interval))
        self._vars["token_override"].set("")

    def _save(self) -> None:
        try:
            new = Settings(
                warning_threshold=int(self._vars["warning_threshold"].get()),
                critical_threshold=int(self._vars["critical_threshold"].get()),
                refresh_interval=max(10, int(self._vars["refresh_interval"].get())),
                token_override=self._vars["token_override"].get().strip(),
            )
        except ValueError as exc:
            tk.messagebox.showerror("Invalid input", str(exc), parent=self)
            return

        if new.warning_threshold >= new.critical_threshold:
            tk.messagebox.showerror(
                "Invalid thresholds",
                "Warning threshold must be less than critical threshold.",
                parent=self,
            )
            return

        set_startup_enabled(bool(self._vars["startup"].get()))
        save_settings(new)
        self._on_save(new)
        self.destroy()
