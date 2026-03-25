"""Tkinter popup windows — modern dark-glass design.

DetailWindow   – borderless flyout anchored to bottom-right, slides up from taskbar
SettingsWindow – modal settings sheet, centered on screen
"""
from __future__ import annotations

import os
import sys
import threading as _threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PIL import Image as _PILImage, ImageTk as _ImageTk

import win32_ui
import api as api_module
from api import UsageData
from config import Settings, get_startup_enabled, save_settings, set_startup_enabled

# ── Brand icon ───────────────────────────────────────────────────────────────

def _brand_icon_path() -> Path:
    """Locate claude_icon.png — handles both source and PyInstaller builds."""
    # PyInstaller extracts --add-data files to sys._MEIPASS
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "claude_icon.png"
    return Path(__file__).parent / "claude_icon.png"


def _load_brand_icon(size: int = 28) -> Optional[_ImageTk.PhotoImage]:
    """Load and resize the Claude brand icon. Returns None on failure."""
    try:
        img = _PILImage.open(_brand_icon_path())
        img = img.resize((size, size), _PILImage.LANCZOS)
        return _ImageTk.PhotoImage(img)
    except Exception:
        return None

# ── Palette ───────────────────────────────────────────────────────────────────

def _palette() -> dict:
    """Return color tokens for the current Windows theme.

    Dark palette inspired by "Developer Tool / IDE" color system:
      BG deep slate, elevated cards, amber (Claude brand) accent,
      green/orange/red semantic thresholds.
    Light palette: warm neutral tones with the same accent hierarchy.
    """
    light = win32_ui.is_light_theme()
    if light:
        return {
            "BG":          "#f8fafc",
            "BG_CARD":     "#ffffff",
            "BG_HOVER":    "#f1f5f9",
            "FG":          "#0f172a",
            "FG_DIM":      "#475569",
            "FG_MUTED":    "#94a3b8",
            "DIVIDER":     "#e2e8f0",
            "AMBER":       "#d97706",
            "GREEN":       "#16a34a",
            "ORANGE":      "#ea580c",
            "RED":         "#dc2626",
            "BTN_BG":      "#f1f5f9",
            "BTN_FG":      "#0f172a",
            "ACRYLIC":     0xF0F8FAFC,
            "BANNER_WARN": "#fffbeb",
            "BAR_BG":      "#e2e8f0",
            "CARD_BORDER": "#e2e8f0",
        }
    return {
        "BG":          "#0f172a",
        "BG_CARD":     "#1b2336",
        "BG_HOVER":    "#1e293b",
        "FG":          "#f8fafc",
        "FG_DIM":      "#94a3b8",
        "FG_MUTED":    "#64748b",
        "DIVIDER":     "#1e293b",
        "AMBER":       "#f59e0b",
        "GREEN":       "#4ade80",
        "ORANGE":      "#fb923c",
        "RED":         "#f87171",
        "BTN_BG":      "#1e293b",
        "BTN_FG":      "#cbd5e1",
        "ACRYLIC":     0xF00F172A,
        "BANNER_WARN": "#1c1306",
        "BAR_BG":      "#1e293b",
        "CARD_BORDER": "#272f42",
    }

# ── Typography ────────────────────────────────────────────────────────────────

_FONT_BODY     = ("Segoe UI Variable", 10)
_FONT_BODY_B   = ("Segoe UI Variable", 10, "bold")
_FONT_LABEL    = ("Segoe UI Variable", 9)
_FONT_SMALL    = ("Segoe UI Variable", 8)   # reset-time / helper
_FONT_NUM      = ("Consolas", 22, "bold")   # large metric value
_FONT_TS       = ("Consolas", 9)            # timestamp

# ── Constants ─────────────────────────────────────────────────────────────────

_WIN_W       = 320
_SLIDE_PX    = 140
_SLIDE_MS    = 180
_SLIDE_STEPS = 14
_FADE_MS     = 100
_FADE_STEPS  = 8
_BAR_H       = 6      # progress bar height px
_BAR_ANIM_MS = 400    # bar fill animation duration ms
_BAR_STEPS   = 20

# ── Helpers ───────────────────────────────────────────────────────────────────

def _threshold_color(value: float, warn: int, crit: int, pal: dict) -> str:
    return pal["RED"] if value >= crit else pal["ORANGE"] if value >= warn else pal["GREEN"]


def _rounded_rect(canvas: tk.Canvas, x1: int, y1: int, x2: int, y2: int,
                  r: int, **kw) -> None:
    """Draw a rounded rectangle on canvas."""
    canvas.create_arc(x1, y1, x1+2*r, y1+2*r, start=90,  extent=90,  style="pieslice", **kw)
    canvas.create_arc(x2-2*r, y1, x2, y1+2*r, start=0,   extent=90,  style="pieslice", **kw)
    canvas.create_arc(x1, y2-2*r, x1+2*r, y2, start=180, extent=90,  style="pieslice", **kw)
    canvas.create_arc(x2-2*r, y2-2*r, x2, y2, start=270, extent=90,  style="pieslice", **kw)
    canvas.create_rectangle(x1+r, y1, x2-r, y2, **kw)
    canvas.create_rectangle(x1, y1+r, x2, y2-r, **kw)


def _draw_brand_icon(canvas: tk.Canvas, size: int, color: str) -> None:
    """Draw an amber rounded-square with a simple circle-mark inside."""
    r = size // 5
    _rounded_rect(canvas, 0, 0, size, size, r, fill=color, outline="")
    m = size // 5
    canvas.create_oval(m, m, size-m, size-m, outline="white", width=1.5)
    canvas.create_arc(m, m, size-m, size-m, start=45, extent=180,
                      fill=color, outline=color, style="pieslice")


def _draw_status_dot(canvas: tk.Canvas, size: int, color: str) -> None:
    """Draw a filled circle status indicator."""
    canvas.create_oval(1, 1, size-1, size-1, fill=color, outline="")


def _format_reset(iso_str: Optional[str]) -> str:
    """Convert an ISO-8601 reset timestamp to a human-friendly relative string."""
    if not iso_str:
        return ""
    try:
        # Handle ISO-8601 with or without trailing Z / timezone
        cleaned = iso_str.replace("Z", "+00:00")
        reset_dt = datetime.fromisoformat(cleaned)
        now = datetime.now(reset_dt.tzinfo)
        delta = reset_dt - now
        total_s = int(delta.total_seconds())
        if total_s <= 0:
            return "Resets soon"
        hours, rem = divmod(total_s, 3600)
        mins = rem // 60
        if hours > 0:
            return f"Resets in {hours}h {mins}m"
        return f"Resets in {mins}m"
    except (ValueError, TypeError):
        return ""


# ── Detail window ─────────────────────────────────────────────────────────────

class DetailWindow(tk.Toplevel):
    """Modern dark-glass flyout — slides up from taskbar corner."""

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
        self._tk_root          = root
        self._on_refresh       = on_refresh
        self._on_open_settings = on_open_settings
        self._settings         = settings
        self._status           = status
        self._closing          = False
        self._bar_canvases: list[tuple[tk.Canvas, float]] = []  # (canvas, fill_ratio)

        self._pal = _palette()

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.0)
        self.configure(bg=self._pal["BG"])

        self._build(usage, last_updated)
        self.after(0, self._init_win32)

        self.bind("<Escape>", lambda _e: self.close())
        self.bind("<FocusOut>", self._on_focus_out)

    # ── Win32 ─────────────────────────────────────────────────────────────

    def _init_win32(self) -> None:
        self.update_idletasks()
        hwnd = self.winfo_id()
        win32_ui.apply_rounded_corners(hwnd)
        ok = win32_ui.apply_acrylic(hwnd, tint_color=self._pal["ACRYLIC"])
        if not ok:
            self.configure(bg=self._pal["BG"])
        self._position_and_animate()

    # ── Layout ────────────────────────────────────────────────────────────

    def _build(self, usage: Optional[UsageData], last_updated: Optional[datetime]) -> None:
        p = self._pal
        outer = tk.Frame(self, bg=p["BG"], bd=0)
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        self._build_header(outer)
        tk.Frame(outer, bg=p["DIVIDER"], height=1).pack(fill="x")
        self._build_body(outer, usage)
        tk.Frame(outer, bg=p["DIVIDER"], height=1).pack(fill="x")
        self._build_footer(outer, last_updated)

    def _build_header(self, parent: tk.Widget) -> None:
        p = self._pal
        row = tk.Frame(parent, bg=p["BG"])
        row.pack(fill="x", padx=14, pady=(13, 11))

        # Claude brand icon
        self._brand_img = _load_brand_icon(28)
        if self._brand_img:
            ic = tk.Label(row, image=self._brand_img, bg=p["BG"])
        else:
            ic = tk.Canvas(row, width=28, height=28, bg=p["BG"],
                           highlightthickness=0)
            _draw_brand_icon(ic, 28, p["AMBER"])
        ic.pack(side="left")

        # Title + subtitle
        txt = tk.Frame(row, bg=p["BG"])
        txt.pack(side="left", padx=(9, 0))
        tk.Label(txt, text="Claude Usage", bg=p["BG"], fg=p["FG"],
                 font=_FONT_BODY_B).pack(anchor="w")
        tk.Label(txt, text="claude.ai/code", bg=p["BG"], fg=p["FG_DIM"],
                 font=_FONT_LABEL).pack(anchor="w")

        # Status dot
        dot_color = {
            "ok":        p["GREEN"],
            "stale":     p["ORANGE"],
            "ratelimit": p["ORANGE"],
            "relogin":   p["RED"],
            "error":     p["RED"],
        }.get(self._status, p["FG_MUTED"])
        dot = tk.Canvas(row, width=9, height=9, bg=p["BG"],
                        highlightthickness=0)
        dot.pack(side="right", padx=(0, 2))
        _draw_status_dot(dot, 9, dot_color)

    def _build_body(self, parent: tk.Widget, usage: Optional[UsageData]) -> None:
        p = self._pal
        w = self._settings.warning_threshold
        c = self._settings.critical_threshold

        wrap = tk.Frame(parent, bg=p["BG"])
        wrap.pack(fill="x", padx=12, pady=10)

        if usage is None:
            msg = {
                "relogin":   "Auth error — re-login to Claude Code",
                "ratelimit": "Rate limited — will retry shortly",
                "error":     "Could not reach API — check connection",
                "stale":     "Showing cached data — retrying…",
            }.get(self._status, "Fetching data…")
            tk.Label(wrap, text=msg, bg=p["BG"], fg=p["FG_DIM"],
                     font=_FONT_LABEL, wraplength=280, justify="left",
                     ).pack(padx=4, pady=8, anchor="w")
        else:
            self._metric_card(wrap, "Session", "5 hour window",
                              usage.five_hour, w, c,
                              reset_at=usage.five_hour_resets_at)
            self._metric_card(wrap, "Weekly", "7 day window",
                              usage.seven_day, w, c,
                              reset_at=usage.seven_day_resets_at)
            if usage.seven_day_sonnet is not None:
                self._metric_card(wrap, "Sonnet", "7 day window",
                                  usage.seven_day_sonnet, w, c)

        # Rate-limit banner
        if self._status == "ratelimit":
            banner_bg = p["BANNER_WARN"]
            banner = tk.Frame(wrap, bg=banner_bg)
            banner.pack(fill="x", pady=(6, 0))
            tk.Frame(banner, bg=p["ORANGE"], height=1).pack(fill="x")
            inner = tk.Frame(banner, bg=banner_bg)
            inner.pack(fill="x")
            tk.Label(inner,
                     text="Rate limited — retrying shortly",
                     bg=banner_bg, fg=p["ORANGE"],
                     font=_FONT_LABEL, anchor="w",
                     ).pack(fill="x", padx=10, pady=7)

    def _metric_card(self, parent: tk.Widget, title: str, subtitle: str,
                     value: float, warn: int, crit: int,
                     reset_at: Optional[str] = None) -> None:
        p   = self._pal
        clr = _threshold_color(value, warn, crit, p)

        card = tk.Frame(parent, bg=p["BG_CARD"],
                        highlightthickness=1,
                        highlightbackground=p["CARD_BORDER"])
        card.pack(fill="x", pady=4)

        # Top row: label left, value right
        top = tk.Frame(card, bg=p["BG_CARD"])
        top.pack(fill="x", padx=14, pady=(10, 0))

        lbl_frame = tk.Frame(top, bg=p["BG_CARD"])
        lbl_frame.pack(side="left", anchor="sw")
        tk.Label(lbl_frame, text=title, bg=p["BG_CARD"], fg=p["FG"],
                 font=_FONT_BODY_B).pack(anchor="w")
        tk.Label(lbl_frame, text=subtitle, bg=p["BG_CARD"], fg=p["FG_MUTED"],
                 font=_FONT_SMALL).pack(anchor="w")

        tk.Label(top, text=f"{value:.0f}%", bg=p["BG_CARD"], fg=clr,
                 font=_FONT_NUM).pack(side="right", anchor="ne")

        # Progress bar canvas — animated on open
        bar_frame = tk.Frame(card, bg=p["BG_CARD"])
        bar_frame.pack(fill="x", padx=14, pady=(6, 0))

        canvas = tk.Canvas(bar_frame, height=_BAR_H, bg=p["BG_CARD"],
                           highlightthickness=0)
        canvas.pack(fill="x")

        fill_ratio = min(max(value / 100.0, 0.0), 1.0)

        def _on_configure(event, cv=canvas, ratio=fill_ratio, color=clr):
            tw = event.width
            cv.delete("all")
            _rounded_rect(cv, 0, 0, tw, _BAR_H, _BAR_H // 2,
                          fill=p["BAR_BG"], outline="")
            cv._target_fill = int(tw * ratio)
            cv._fill_color  = color
            cv._track_w     = tw

        canvas.bind("<Configure>", _on_configure)
        self._bar_canvases.append((canvas, fill_ratio))

        # Reset time (if available)
        reset_text = _format_reset(reset_at)
        if reset_text:
            tk.Label(card, text=reset_text, bg=p["BG_CARD"],
                     fg=p["FG_MUTED"], font=_FONT_SMALL,
                     anchor="w").pack(fill="x", padx=14, pady=(4, 8))
        else:
            tk.Frame(card, bg=p["BG_CARD"], height=8).pack()

    # ── Bar fill animation ────────────────────────────────────────────────

    def _start_bar_animations(self) -> None:
        for canvas, fill_ratio in self._bar_canvases:
            self._anim_bar(canvas, fill_ratio, step=0)

    def _anim_bar(self, canvas: tk.Canvas, fill_ratio: float, step: int) -> None:
        if step > _BAR_STEPS:
            return
        p = self._pal
        try:
            tw = getattr(canvas, "_track_w", canvas.winfo_width())
            if tw < 2:
                self.after(20, lambda: self._anim_bar(canvas, fill_ratio, step))
                return
            color = getattr(canvas, "_fill_color", p["GREEN"])
            t     = step / _BAR_STEPS
            ease  = 1 - (1 - t) ** 3   # ease-out cubic
            fw    = int(tw * fill_ratio * ease)
            canvas.delete("fill")
            if fw > 0:
                _rounded_rect(canvas, 0, 0, fw, _BAR_H, _BAR_H // 2,
                              fill=color, outline="", tags="fill")
        except tk.TclError:
            return
        delay = max(1, _BAR_ANIM_MS // _BAR_STEPS)
        self.after(delay, lambda: self._anim_bar(canvas, fill_ratio, step + 1))

    # ── Footer ────────────────────────────────────────────────────────────

    def _build_footer(self, parent: tk.Widget, last_updated: Optional[datetime]) -> None:
        p  = self._pal
        ts = last_updated.strftime("%H:%M:%S") if last_updated else "never"

        row = tk.Frame(parent, bg=p["BG"])
        row.pack(fill="x", padx=14, pady=9)

        tk.Label(row, text=f"Updated {ts}", bg=p["BG"], fg=p["FG_MUTED"],
                 font=_FONT_TS).pack(side="left")

        btn_kw = dict(
            font=_FONT_LABEL, relief="flat", bd=0,
            padx=10, pady=4, cursor="hand2",
            bg=p["BTN_BG"], fg=p["BTN_FG"],
            activebackground=p["BG_HOVER"],
            activeforeground=p["FG"],
        )
        tk.Button(row, text="Settings", command=self._do_settings, **btn_kw
                  ).pack(side="right")
        tk.Button(row, text="Refresh", command=self._do_refresh,
                  bg=p["BTN_BG"],
                  activebackground=p["BG_HOVER"],
                  fg=p["AMBER"],
                  activeforeground=p["AMBER"],
                  font=_FONT_LABEL, relief="flat", bd=0,
                  padx=10, pady=4, cursor="hand2",
                  ).pack(side="right", padx=(0, 6))

    # ── Position + animation ──────────────────────────────────────────────

    def _position_and_animate(self) -> None:
        self.update_idletasks()
        sw  = self.winfo_screenwidth()
        sh  = self.winfo_screenheight()
        tb  = win32_ui.taskbar_height()
        w   = max(self.winfo_reqwidth(), _WIN_W)
        h   = max(self.winfo_reqheight(), self.winfo_height())
        x       = sw - w - 12
        y_end   = sh - h - tb - 12
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
                self._start_bar_animations()
            except tk.TclError:
                pass
            return
        t    = (step + 1) / _SLIDE_STEPS
        ease = 1 - (1 - t) ** 2
        y    = int(y_from + (y_to - y_from) * ease)
        try:
            self.geometry(f"+{x}+{y}")
        except tk.TclError:
            return
        self.after(max(1, _SLIDE_MS // _SLIDE_STEPS),
                   lambda: self._animate_slide(x, y_from, y_to, step + 1))

    # ── Close (fade-out) ──────────────────────────────────────────────────

    def close(self) -> None:
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
        self.after(max(1, _FADE_MS // _FADE_STEPS),
                   lambda: self._animate_fade(step + 1))

    # ── Focus-loss dismiss ────────────────────────────────────────────────

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

    # ── Actions ───────────────────────────────────────────────────────────

    def _do_refresh(self) -> None:
        self.close()
        self._tk_root.after(_FADE_MS + 20, self._on_refresh)

    def _do_settings(self) -> None:
        self.close()
        self._tk_root.after(_FADE_MS + 20, self._on_open_settings)


# ── Settings window ───────────────────────────────────────────────────────────

class SettingsWindow(tk.Toplevel):
    """Settings flyout — same dark-glass design, centered on screen."""

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
        self._closing  = False
        self._pal      = _palette()
        self._drag_x   = 0
        self._drag_y   = 0

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.0)
        self.configure(bg=self._pal["BG"])

        self._build()
        self.after(0, self._init_win32)
        self.bind("<Escape>", lambda _e: self.close())

    def _init_win32(self) -> None:
        try:
            self.update_idletasks()
            hwnd = self.winfo_id()
            win32_ui.apply_rounded_corners(hwnd)
            ok = win32_ui.apply_acrylic(hwnd, tint_color=self._pal["ACRYLIC"])
            if not ok:
                self.configure(bg=self._pal["BG"])
            self._center_and_show()
        except tk.TclError:
            pass

    def _build(self) -> None:
        p = self._pal
        outer = tk.Frame(self, bg=p["BG"])
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        # Header (draggable)
        hdr = tk.Frame(outer, bg=p["BG"], cursor="fleur")
        hdr.pack(fill="x", padx=14, pady=(13, 11))
        self._brand_img = _load_brand_icon(28)
        if self._brand_img:
            ic = tk.Label(hdr, image=self._brand_img, bg=p["BG"])
        else:
            ic = tk.Canvas(hdr, width=28, height=28, bg=p["BG"], highlightthickness=0)
            _draw_brand_icon(ic, 28, p["AMBER"])
        ic.pack(side="left")
        txt = tk.Frame(hdr, bg=p["BG"])
        txt.pack(side="left", padx=(9, 0))
        tk.Label(txt, text="Settings", bg=p["BG"], fg=p["FG"],
                 font=_FONT_BODY_B).pack(anchor="w")
        tk.Label(txt, text="Claude Usage Tray", bg=p["BG"], fg=p["FG_DIM"],
                 font=_FONT_LABEL).pack(anchor="w")

        # Bind drag on header and all its children
        for widget in [hdr, ic, txt] + list(txt.winfo_children()):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)

        tk.Frame(outer, bg=p["DIVIDER"], height=1).pack(fill="x")

        body = tk.Frame(outer, bg=p["BG"])
        body.pack(fill="both", expand=True, padx=14, pady=10)

        self._slider_row(body, "Warning threshold",  "warning_threshold",
                         50, 95,  self._settings.warning_threshold,  "%",
                         accent=p["ORANGE"])
        self._slider_row(body, "Critical threshold", "critical_threshold",
                         60, 100, self._settings.critical_threshold, "%",
                         accent=p["RED"])
        self._slider_row(body, "Refresh interval",   "refresh_interval",
                         120, 600, self._settings.refresh_interval,  "s",
                         accent=p["AMBER"])

        tk.Frame(body, bg=p["DIVIDER"], height=1).pack(fill="x", pady=8)

        tk.Label(body, text="Token override", bg=p["BG"], fg=p["FG"],
                 font=_FONT_BODY).pack(anchor="w")
        self._token_rows(body)

        tk.Frame(body, bg=p["DIVIDER"], height=1).pack(fill="x", pady=8)

        self._startup_row(body)

        tk.Frame(outer, bg=p["DIVIDER"], height=1).pack(fill="x")
        ftr = tk.Frame(outer, bg=p["BG"])
        ftr.pack(fill="x", padx=14, pady=10)

        btn_kw = dict(font=_FONT_LABEL, relief="flat", bd=0,
                      padx=14, pady=5, cursor="hand2")
        tk.Button(ftr, text="Save", command=self._save,
                  bg=p["AMBER"], fg="#ffffff",
                  activebackground=p["ORANGE"], activeforeground="#ffffff",
                  **btn_kw).pack(side="right")
        tk.Button(ftr, text="Cancel", command=self.close,
                  bg=p["BTN_BG"], fg=p["BTN_FG"],
                  activebackground=p["BG_HOVER"], activeforeground=p["FG"],
                  **btn_kw).pack(side="right", padx=(0, 8))

    def _slider_row(
        self, parent: tk.Widget, label: str, key: str,
        from_: int, to: int, default: int, unit: str, accent: str = "",
    ) -> None:
        p   = self._pal
        var = tk.IntVar(value=default)
        self._vars[key] = var

        row = tk.Frame(parent, bg=p["BG"])
        row.pack(fill="x", pady=4)

        hdr = tk.Frame(row, bg=p["BG"])
        hdr.pack(fill="x")
        tk.Label(hdr, text=label, bg=p["BG"], fg=p["FG"],
                 font=_FONT_BODY).pack(side="left")
        val_lbl = tk.Label(hdr, text=f"{default}{unit}", bg=p["BG"],
                           fg=accent or p["AMBER"], font=_FONT_BODY)
        val_lbl.pack(side="right")

        def _on_move(v: str) -> None:
            val_lbl.config(text=f"{int(float(v))}{unit}")

        tk.Scale(
            row, from_=from_, to=to, orient="horizontal",
            variable=var, command=_on_move,
            bg=p["BG"], fg=p["FG"], troughcolor=p["BG_CARD"],
            highlightthickness=0, showvalue=False,
            relief="flat", sliderlength=16, bd=0,
        ).pack(fill="x")

    def _token_rows(self, parent: tk.Widget) -> None:
        p   = self._pal
        var = tk.StringVar(value=self._settings.token_override)
        self._vars["token_override"] = var

        row = tk.Frame(parent, bg=p["BG"])
        row.pack(fill="x", pady=(4, 0))

        entry = tk.Entry(
            row, textvariable=var, show="●",
            bg=p["BG_CARD"], fg=p["FG"], insertbackground=p["FG"],
            relief="flat", width=28, font=_FONT_LABEL,
            highlightthickness=1, highlightbackground=p["DIVIDER"],
        )
        entry.pack(side="left", ipady=5)

        def _toggle():
            entry.config(show="" if entry.cget("show") else "●")

        eye = tk.Label(row, text="👁", bg=p["BG"], fg=p["FG_DIM"],
                       font=("Segoe UI", 11), cursor="hand2")
        eye.pack(side="left", padx=(6, 0))
        eye.bind("<Button-1>", lambda _e: _toggle())

        test_row = tk.Frame(parent, bg=p["BG"])
        test_row.pack(fill="x", pady=(6, 0))

        self._test_result_var = tk.StringVar(value="")
        self._test_btn = tk.Button(
            test_row, text="Test connection",
            bg=p["BTN_BG"], fg=p["BTN_FG"],
            activebackground=p["BG_HOVER"],
            font=_FONT_LABEL, relief="flat", padx=10, pady=3,
            cursor="hand2", bd=0,
        )
        self._test_btn.pack(side="left")
        tk.Label(test_row, textvariable=self._test_result_var,
                 bg=p["BG"], fg=p["FG_DIM"], font=_FONT_LABEL,
                 ).pack(side="left", padx=(8, 0))

        def _run_test():
            token = var.get().strip()
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
                try:
                    self.after(0, lambda: _show(ok, msg))
                except tk.TclError:
                    pass

            def _show(ok: bool, msg: str) -> None:
                try:
                    self._test_btn.config(state="normal")
                    self._test_result_var.set(f"{'✓' if ok else '✗'} {msg}")
                except tk.TclError:
                    pass

            _threading.Thread(target=_work, daemon=True).start()

        self._test_btn.config(command=_run_test)

        tk.Label(parent, text="Leave blank to auto-detect from credentials file.",
                 bg=p["BG"], fg=p["FG_MUTED"], font=("Segoe UI Variable", 8),
                 ).pack(anchor="w", pady=(2, 0))

    def _startup_row(self, parent: tk.Widget) -> None:
        p   = self._pal
        var = tk.BooleanVar(value=get_startup_enabled())
        self._vars["startup"] = var

        row = tk.Frame(parent, bg=p["BG_CARD"],
                       highlightthickness=1,
                       highlightbackground=p["DIVIDER"])
        row.pack(fill="x")

        inner = tk.Frame(row, bg=p["BG_CARD"])
        inner.pack(fill="x", padx=12, pady=9)

        lbl_frame = tk.Frame(inner, bg=p["BG_CARD"])
        lbl_frame.pack(side="left")
        tk.Label(lbl_frame, text="Start with Windows", bg=p["BG_CARD"],
                 fg=p["FG"], font=_FONT_BODY).pack(anchor="w")
        tk.Label(lbl_frame, text="Launch tray on login", bg=p["BG_CARD"],
                 fg=p["FG_MUTED"], font=_FONT_LABEL).pack(anchor="w")

        # Canvas toggle switch
        TW, TH = 36, 20
        toggle_cv = tk.Canvas(inner, width=TW, height=TH,
                               bg=p["BG_CARD"], highlightthickness=0,
                               cursor="hand2")
        toggle_cv.pack(side="right")

        def _draw_toggle():
            toggle_cv.delete("all")
            on = var.get()
            track = p["AMBER"] if on else p["FG_MUTED"]
            _rounded_rect(toggle_cv, 0, 0, TW, TH, TH // 2,
                          fill=track, outline="")
            tx = TW - TH // 2 - 3 if on else TH // 2 + 3
            toggle_cv.create_oval(tx - TH // 2 + 3, 2,
                                   tx + TH // 2 - 3, TH - 2,
                                   fill="white", outline="")

        def _toggle(_e=None):
            var.set(not var.get())
            _draw_toggle()

        toggle_cv.bind("<Button-1>", _toggle)
        row.bind("<Button-1>", _toggle)
        inner.bind("<Button-1>", _toggle)
        lbl_frame.bind("<Button-1>", _toggle)
        for child in lbl_frame.winfo_children():
            child.bind("<Button-1>", _toggle)
        _draw_toggle()

    def _drag_start(self, event) -> None:
        self._drag_x = event.x_root - self.winfo_x()
        self._drag_y = event.y_root - self.winfo_y()

    def _drag_move(self, event) -> None:
        self.geometry(f"+{event.x_root - self._drag_x}+{event.y_root - self._drag_y}")

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

    def _save(self) -> None:
        try:
            new = Settings(
                warning_threshold  = int(self._vars["warning_threshold"].get()),
                critical_threshold = int(self._vars["critical_threshold"].get()),
                refresh_interval   = int(self._vars["refresh_interval"].get()),
                token_override     = self._vars["token_override"].get().strip(),
            )
        except (ValueError, KeyError):
            return
        if new.warning_threshold >= new.critical_threshold:
            return
        set_startup_enabled(bool(self._vars["startup"].get()))
        save_settings(new)
        self._on_save(new)
        self.close()
