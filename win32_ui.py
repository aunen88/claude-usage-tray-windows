"""Windows 11 UI helpers — DWM rounded corners, acrylic blur, theme detection.

All public functions are safe to call on any Windows version and return
sensible defaults on failure. Import this module anywhere; it never raises.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import sys
import winreg

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# DwmSetWindowAttribute
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2

# SetWindowCompositionAttribute / accent policy
WCA_ACCENT_POLICY = 19
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4

# Windows build number where acrylic blur was introduced (1803)
_ACRYLIC_MIN_BUILD = 17134

# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------

class _ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState",   ctypes.c_uint),
        ("AccentFlags",   ctypes.c_uint),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId",   ctypes.c_uint),
    ]


class _WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute",  ctypes.c_int),
        ("pData",      ctypes.c_void_p),
        ("SizeOfData", ctypes.c_size_t),
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_light_theme() -> bool:
    """Return True if Windows is in light app theme mode, False for dark.

    Defaults to False (dark) if the registry key is absent (e.g. LTSC).
    """
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return bool(value)
    except OSError:
        return False  # default to dark theme


def apply_rounded_corners(hwnd: int) -> None:
    """Apply DWM rounded corners to a window.

    Must be called after the window is mapped (HWND is valid).
    No-op on Windows 10 or if DWM is unavailable.
    """
    try:
        pref = ctypes.c_int(DWMWCP_ROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(pref),
            ctypes.sizeof(pref),
        )
    except Exception:
        pass  # DWM not available or Windows 10 — corners stay square


def apply_acrylic(hwnd: int, tint_color: int = 0x80000000) -> bool:
    """Apply acrylic blur-behind to a window.  Returns True on success.

    tint_color is ABGR (alpha in high byte).  Default is 50% black.
    Only applied on Windows 10 build 17134+ (1803).
    """
    if sys.getwindowsversion().build < _ACRYLIC_MIN_BUILD:
        return False
    try:
        accent = _ACCENT_POLICY()
        accent.AccentState   = ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.GradientColor = tint_color

        data = _WINDOWCOMPOSITIONATTRIBDATA()
        data.Attribute  = WCA_ACCENT_POLICY
        data.pData      = ctypes.cast(ctypes.byref(accent), ctypes.c_void_p)
        data.SizeOfData = ctypes.sizeof(accent)

        ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
        return True
    except Exception:
        return False


def taskbar_height() -> int:
    """Return the taskbar height in pixels, or 52 if detection fails."""
    try:
        class _APPBARDATA(ctypes.Structure):
            _fields_ = [
                ("cbSize",           ctypes.wintypes.DWORD),
                ("hWnd",             ctypes.wintypes.HWND),
                ("uCallbackMessage", ctypes.wintypes.UINT),
                ("uEdge",            ctypes.wintypes.UINT),
                ("rc",               ctypes.wintypes.RECT),
                ("lParam",           ctypes.wintypes.LPARAM),
            ]

        ABM_GETTASKBARPOS = 0x00000005
        data = _APPBARDATA()
        data.cbSize = ctypes.sizeof(data)
        ctypes.windll.shell32.SHAppBarMessage(ABM_GETTASKBARPOS, ctypes.byref(data))
        rc = data.rc
        # Height = screen_height - rc.top (for bottom-docked taskbar)
        sh = ctypes.windll.user32.GetSystemMetrics(1)  # SM_CYSCREEN
        return sh - rc.top
    except Exception:
        return 52
