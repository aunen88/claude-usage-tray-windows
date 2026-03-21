"""Tkinter popup windows – macOS popover-style design.

DetailWindow   – borderless white popover anchored to the bottom-right corner
SettingsWindow – modal settings sheet
"""

from __future__ import annotations

import tkinter as tk
import tkinter.messagebox
from datetime import datetime, timezone
from typing import Callable, Optional

import win32_ui
from api import UsageData
from config import Settings, get_startup_enabled, save_settings, set_startup_enabled

# ── Theme-aware palette ───────────────────────────────────────────────────────

def _palette() -> dict:
    """Return color tokens based on current Windows theme. Re-read on each call."""
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

# Static palette still used by SettingsWindow (unchanged in this task)
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
FONT    = ("Segoe UI", 10)
FONT_B  = ("Segoe UI Semibold", 10)
FONT_SM = ("Segoe UI", 8)
FONT_T  = ("Segoe UI Semibold", 12)
FONT_IC = ("Segoe UI", 11)

_WIN_W = 280   # flyout width (px) — changed from 260

# Animation timings
_SLIDE_PX    = 160   # total slide distance (px)
_SLIDE_MS    = 150   # slide duration (ms)
_SLIDE_STEPS = 12    # number of animation frames
_FADE_MS     = 100   # fade-out duration (ms)
_FADE_STEPS  = 8


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
    """Windows 11 flyout — slides up from taskbar, acrylic/DWM background."""

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
        self._closing          = False

        # Read theme once per open
        self._pal = _palette()

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.0)   # start invisible for slide-in

        self._build(usage, last_updated)
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

        # Stats section
        stats = tk.Frame(outer, bg=p["BG"])
        stats.pack(fill="x", pady=(8, 4))

        if usage is None:
            msg = {
                "relogin":   "Auth error — re-login to Claude Code",
                "ratelimit": "Rate limited — backing off, will retry",
                "error":     "Could not reach API — check connection",
                "stale":     "Showing last known data — retrying\u2026",
            }.get(self._status, "Fetching data\u2026")
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
        # Track (background)
        canvas.create_oval(0, 0, bar_h, bar_h, fill=p["BG_SEC"], outline="")
        canvas.create_rectangle(r, 0, bar_w - r, bar_h, fill=p["BG_SEC"], outline="")
        canvas.create_oval(bar_w - bar_h, 0, bar_w, bar_h, fill=p["BG_SEC"], outline="")
        # Fill
        fill_w = max(bar_h, int(bar_w * min(value, 100) / 100))
        canvas.create_oval(0, 0, bar_h, bar_h, fill=clr, outline="")
        canvas.create_rectangle(r, 0, fill_w - r, bar_h, fill=clr, outline="")
        if fill_w - bar_h >= 0:
            canvas.create_oval(fill_w - bar_h, 0, fill_w, bar_h, fill=clr, outline="")

    # ── Position + animation ─────────────────────────────────────────────

    def _position_and_animate(self) -> None:
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        tb = win32_ui.taskbar_height()
        w  = max(self.winfo_reqwidth(), _WIN_W)
        h  = max(self.winfo_reqheight(), self.winfo_height())

        x      = sw - w - 12
        y_end  = sh - h - tb - 12
        y_start = y_end + _SLIDE_PX

        self.geometry(f"{w}x{h}+{x}+{y_start}")
        self.attributes("-alpha", 1.0)
        self.lift()
        self.after(50, self.focus_force)
        self._animate_slide(x, y_start, y_end, step=0)

    def _animate_slide(self, x: int, y_from: int, y_to: int, step: int) -> None:
        if step >= _SLIDE_STEPS:
            try:
                self.geometry(f"+{x}+{y_to}")
            except tk.TclError:
                pass
            return
        t = (step + 1) / _SLIDE_STEPS
        ease = 1 - (1 - t) ** 2   # ease-out quadratic
        y = int(y_from + (y_to - y_from) * ease)
        try:
            self.geometry(f"+{x}+{y}")
        except tk.TclError:
            return
        delay = max(1, _SLIDE_MS // _SLIDE_STEPS)
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
            try:
                self.destroy()
            except tk.TclError:
                pass
            return
        alpha = 1.0 - (step + 1) / _FADE_STEPS
        try:
            self.attributes("-alpha", alpha)
        except tk.TclError:
            return
        self.after(max(1, _FADE_MS // _FADE_STEPS), lambda: self._animate_fade(step + 1))

    # ── Focus-loss dismiss ───────────────────────────────────────────────

    def _on_focus_out(self, _event) -> None:
        self.after(50, self._check_focus)

    def _check_focus(self) -> None:
        if self._closing:
            return
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
