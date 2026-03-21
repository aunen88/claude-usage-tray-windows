"""Unit tests for api.test_connection()."""
from unittest.mock import MagicMock, patch
import api


def _mock_resp(status: int, body: dict | None = None, headers: dict | None = None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body or {}
    r.headers = headers or {}
    r.raise_for_status.return_value = None
    return r


def test_test_connection_success():
    body = {
        "five_hour":  {"utilization": 35.0},
        "seven_day":  {"utilization": 71.0},
    }
    with patch("api.requests.get", return_value=_mock_resp(200, body)):
        ok, msg = api.test_connection("fake-token")
    assert ok is True
    assert "35%" in msg
    assert "71%" in msg


def test_test_connection_401():
    with patch("api.requests.get", return_value=_mock_resp(401)):
        ok, msg = api.test_connection("bad-token")
    assert ok is False
    assert "401" in msg


def test_test_connection_network_error():
    import requests as _req
    with patch("api.requests.get", side_effect=_req.ConnectionError("timeout")):
        ok, msg = api.test_connection("any-token")
    assert ok is False
    assert "reach" in msg.lower()
