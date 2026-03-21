"""Pillow-based dynamic tray icon.

Renders a 64×64 RGBA image showing session (5h) and weekly (7d) utilisation
percentages on two lines, with a colour-coded background:

  green  (#55EE55)  – both values below warning threshold
  orange (#FFAA00)  – max value ≥ warning
  red    (#FF5555)  – max value ≥ critical

Status variants
---------------
ok       normal rendering
stale    same percentages but greyed out (network error, showing cached data)
error    grey background, "?" label
no_token grey background, "?" label
relogin  dark-red background, "!!" label
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

_SIZE = 64

# Candidate monospace / bold fonts available on virtually every Windows install
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/consola.ttf",   # Consolas
    "C:/Windows/Fonts/cour.ttf",      # Courier New
    "C:/Windows/Fonts/lucon.ttf",     # Lucida Console
    "C:/Windows/Fonts/arialbd.ttf",   # Arial Bold (fallback)
    "C:/Windows/Fonts/arial.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    # Last resort: PIL built-in bitmap font (no size control)
    return ImageFont.load_default()


def _colors(value: float, warning: int, critical: int) -> tuple[str, tuple]:
    """Return (text_hex, bg_rgba) for a given utilisation value."""
    if value >= critical:
        return "#FF5555", (75, 0, 0, 235)
    if value >= warning:
        return "#FFAA00", (70, 42, 0, 235)
    return "#55EE55", (0, 58, 0, 235)


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    text: str,
    fill: str,
    font: ImageFont.FreeTypeFont,
) -> None:
    """Draw *text* centred at *(cx, cy)*, compatible with Pillow 8+ and older."""
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        draw.text((cx - w // 2, cy - h // 2), text, fill=fill, font=font)
    except AttributeError:
        # Pillow < 8 – use deprecated textsize
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
    """Return a 64×64 RGBA ``PIL.Image`` for the system tray."""
    sz = _SIZE
    img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ── Error / unknown states ──────────────────────────────────────────────
    if status in ("no_token", "error", "ratelimit") or five_hour is None:
        draw.rectangle([0, 0, sz - 1, sz - 1], fill=(75, 75, 75, 225))
        font = _load_font(32)
        _draw_centered(draw, sz // 2, sz // 2, "?", "#CCCCCC", font)
        return img

    if status == "relogin":
        draw.rectangle([0, 0, sz - 1, sz - 1], fill=(80, 0, 0, 235))
        font = _load_font(26)
        _draw_centered(draw, sz // 2, sz // 2, "!!", "#FF8888", font)
        return img

    # ── Normal / stale rendering ────────────────────────────────────────────
    max_val = max(five_hour, seven_day or 0.0)

    if status == "stale":
        text_color = "#999999"
        bg_color: tuple = (45, 45, 45, 225)
    else:
        text_color, bg_color = _colors(max_val, warning, critical)

    draw.rectangle([0, 0, sz - 1, sz - 1], fill=bg_color)

    font = _load_font(20)
    line1 = f"{int(round(five_hour))}%"
    line2 = f"{int(round(seven_day or 0))}%"

    _draw_centered(draw, sz // 2, 17, line1, text_color, font)

    # Thin separator
    sep_color = text_color
    draw.line([(8, 32), (sz - 9, 32)], fill=sep_color, width=1)

    _draw_centered(draw, sz // 2, 47, line2, text_color, font)

    return img
