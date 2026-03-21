"""Unit tests for icon_renderer.render_icon()."""
from PIL import Image
import icon_renderer


def test_output_is_64x64():
    img = icon_renderer.render_icon(20.0, 50.0, status="ok")
    assert img.size == (64, 64)


def test_output_is_rgba():
    img = icon_renderer.render_icon(20.0, 50.0, status="ok")
    assert img.mode == "RGBA"


def test_error_state_returns_image():
    img = icon_renderer.render_icon(None, None, status="error")
    assert img.size == (64, 64)


def test_relogin_state_returns_image():
    img = icon_renderer.render_icon(None, None, status="relogin")
    assert img.size == (64, 64)
    assert img.mode == "RGBA"


def test_ok_background_is_dark():
    """Normal state: background should be near #1a1a1a (dark, not colored)."""
    img = icon_renderer.render_icon(20.0, 50.0, status="ok")
    # Sample a non-corner edge pixel that should be background
    r, g, b, a = img.getpixel((4, 4))
    assert r < 60 and g < 60 and b < 60 and a > 100, f"Expected dark bg, got ({r},{g},{b},{a})"
