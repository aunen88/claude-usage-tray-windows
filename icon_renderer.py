"""Pillow-based dynamic tray icon — Windows 11 style.

Renders a 64×64 RGBA image by drawing at 128×128 then downscaling with
LANCZOS for clean anti-aliased text.

Color scheme: dark neutral background (#1a1a1a), text colored by value:
  green  (#55EE55) – below warning
  orange (#FFAA00) – warning <= value < critical
  red    (#FF5555) – critical and above

Status variants
---------------
ok       normal two-line rendering
stale    same layout, grey text
error    grey background, "?" label
no_token grey background, "?" label
ratelimit grey background, "?" label
relogin  dark-red background, "!!" label
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

# Internal render size (2x for anti-aliasing); downscaled to _OUT at return
_RENDER = 128
_OUT    = 64

# Bold Consolas preferred; fall back to regular, then other monospace fonts
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/consolab.ttf",  # Consolas Bold
    "C:/Windows/Fonts/consola.ttf",   # Consolas Regular
    "C:/Windows/Fonts/courbd.ttf",    # Courier New Bold
    "C:/Windows/Fonts/cour.ttf",      # Courier New
    "C:/Windows/Fonts/lucon.ttf",     # Lucida Console
    "C:/Windows/Fonts/arialbd.ttf",   # Arial Bold (last resort)
]

_BG_DARK    = (26, 26, 26, 235)     # #1a1a1a - normal background
_BG_GREY    = (75, 75, 75, 225)     # error/unknown background
_BG_RELOGIN = (80, 0, 0, 235)       # dark-red relogin background

_GREEN  = "#55EE55"
_ORANGE = "#FFAA00"
_RED    = "#FF5555"
_GREY   = "#999999"
_WHITE  = "#CCCCCC"


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _text_color(value: float, warning: int, critical: int) -> str:
    if value >= critical:
        return _RED
    if value >= warning:
        return _ORANGE
    return _GREEN


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    text: str,
    fill: str,
    font: ImageFont.FreeTypeFont,
) -> None:
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        draw.text((cx - w // 2, cy - h // 2), text, fill=fill, font=font)
    except AttributeError:
        try:
            w, h = draw.textsize(text, font=font)  # type: ignore[attr-defined]
            draw.text((cx - w // 2, cy - h // 2), text, fill=fill, font=font)
        except Exception:
            draw.text((cx - 8, cy - 8), text, fill=fill, font=font)


def render_icon(
    five_hour: Optional[float],
    seven_day: Optional[float],
    *,
    warning: int = 80,
    critical: int = 90,
    status: str = "ok",
) -> Image.Image:
    """Return a 64x64 RGBA PIL.Image for the system tray."""
    sz = _RENDER
    img  = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # -- Error / unknown states --
    if status in ("no_token", "error", "ratelimit") or five_hour is None:
        draw.rectangle([0, 0, sz - 1, sz - 1], fill=_BG_GREY)
        font = _load_font(64)
        _draw_centered(draw, sz // 2, sz // 2, "?", _WHITE, font)
        return img.resize((_OUT, _OUT), Image.LANCZOS)

    if status == "relogin":
        draw.rectangle([0, 0, sz - 1, sz - 1], fill=_BG_RELOGIN)
        font = _load_font(52)
        _draw_centered(draw, sz // 2, sz // 2, "!!", "#FF8888", font)
        return img.resize((_OUT, _OUT), Image.LANCZOS)

    # -- Normal / stale rendering --
    draw.rectangle([0, 0, sz - 1, sz - 1], fill=_BG_DARK)

    if status == "stale":
        line1_color = _GREY
        line2_color = _GREY
    else:
        line1_color = _text_color(five_hour, warning, critical)
        line2_color = _text_color(seven_day or 0.0, warning, critical)

    font = _load_font(40)
    line1 = f"{int(round(five_hour))}%"
    line2 = f"{int(round(seven_day or 0))}%"

    # Text anchors at 2x scale: y=34 (top line), y=94 (bottom line)
    _draw_centered(draw, sz // 2, 34,  line1, line1_color, font)

    # Separator at y=64 (midpoint)
    draw.line([(16, 64), (sz - 17, 64)], fill="#444444", width=2)

    _draw_centered(draw, sz // 2, 94, line2, line2_color, font)

    return img.resize((_OUT, _OUT), Image.LANCZOS)
