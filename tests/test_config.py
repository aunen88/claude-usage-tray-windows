"""Unit tests for config.load_settings()."""
import json, tempfile
from pathlib import Path
from unittest.mock import patch
import config


def _write_settings(tmp: Path, data: dict) -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "settings.json").write_text(json.dumps(data), encoding="utf-8")


def test_refresh_interval_clamped_above_300():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        _write_settings(p, {"refresh_interval": 9999})
        with patch.object(config, "CONFIG_FILE", p / "settings.json"):
            s = config.load_settings()
    assert s.refresh_interval == 300


def test_refresh_interval_below_300_unchanged():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        _write_settings(p, {"refresh_interval": 120})
        with patch.object(config, "CONFIG_FILE", p / "settings.json"):
            s = config.load_settings()
    assert s.refresh_interval == 120


def test_defaults_when_no_file():
    with patch.object(config, "CONFIG_FILE", Path("/nonexistent/settings.json")):
        s = config.load_settings()
    assert s.refresh_interval == 60
    assert s.warning_threshold == 80
