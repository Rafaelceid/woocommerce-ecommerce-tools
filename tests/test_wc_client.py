"""Tests for shared/wc_client.py.

Run with:  pytest tests/test_wc_client.py -v
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
import time
import unittest
import unittest.mock as mock
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

import pytest

from shared.wc_client import WCClient, load_env


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(body: object, status: int = 200, headers: dict | None = None) -> mock.MagicMock:
    """Build a mock response for urllib.request.urlopen."""
    raw = json.dumps(body).encode()
    resp = mock.MagicMock()
    resp.read.return_value = raw
    resp.status = status
    h = {
        "X-WP-Total": str(len(body) if isinstance(body, list) else 1),
        "X-WP-TotalPages": "1",
        **(headers or {}),
    }
    resp.headers = h
    resp.__enter__ = lambda s: s
    resp.__exit__ = mock.MagicMock(return_value=False)
    return resp


# ---------------------------------------------------------------------------
# load_env
# ---------------------------------------------------------------------------

class TestLoadEnv:
    def test_reads_from_os_env(self, monkeypatch):
        monkeypatch.setenv("WC_CONSUMER_KEY", "ck_test")
        monkeypatch.setenv("WC_CONSUMER_SECRET", "cs_test")
        ck, cs = load_env()
        assert ck == "ck_test"
        assert cs == "cs_test"

    def test_reads_from_dotenv_file(self, monkeypatch, tmp_path):
        monkeypatch.delenv("WC_CONSUMER_KEY", raising=False)
        monkeypatch.delenv("WC_CONSUMER_SECRET", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text("WC_CONSUMER_KEY=ck_file\nWC_CONSUMER_SECRET=cs_file\n")
        ck, cs = load_env(env_path=env_file)
        assert ck == "ck_file"
        assert cs == "cs_file"

    def test_raises_when_missing(self, monkeypatch, tmp_path):
        monkeypatch.delenv("WC_CONSUMER_KEY", raising=False)
        monkeypatch.delenv("WC_CONSUMER_SECRET", raising=False)
        # Prevent walk-up from finding any real .env on the filesystem
        monkeypatch.setattr(Path, "exists", lambda self: False)
        with pytest.raises(SystemExit, match="Missing"):
            load_env(env_path=tmp_path / "nonexistent.env")


# ---------------------------------------------------------------------------
# WCClient._request
# ---------------------------------------------------------------------------

class TestWCClientRequest:
    def _client(self) -> WCClient:
        return WCClient("ck_x", "cs_x", base_url="https://example.com/wp-json")

    def test_happy_path_get(self):
        client = self._client()
        payload = {"id": 1, "name": "Test"}
        with mock.patch("urllib.request.urlopen", return_value=_make_response(payload)):
            result, headers = client._request("GET", "/wc/v3/products/1")
        assert result == payload

    def test_authorization_header(self):
        client = self._client()
        expected_token = base64.b64encode(b"ck_x:cs_x").decode()
        captured = {}

        def fake_open(req, timeout=None):
            captured["auth"] = req.get_header("Authorization")
            return _make_response({})

        with mock.patch("urllib.request.urlopen", side_effect=fake_open):
            client._request("GET", "/wc/v3/test")

        assert captured["auth"] == f"Basic {expected_token}"

    def test_retries_on_429(self):
        client = self._client()
        call_count = 0

        def fake_open(req, timeout=None):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                exc = urllib.error.HTTPError(url="", code=429, msg="Too Many Requests", hdrs={}, fp=BytesIO(b""))
                raise exc
            return _make_response({"ok": True})

        with mock.patch("urllib.request.urlopen", side_effect=fake_open), \
             mock.patch("time.sleep"):
            data, _ = client._request("GET", "/wc/v3/products")

        assert call_count == 3
        assert data["ok"] is True

    def test_raises_on_404(self):
        client = self._client()

        def fake_open(req, timeout=None):
            raise urllib.error.HTTPError(url="", code=404, msg="Not Found", hdrs={}, fp=BytesIO(b"not found"))

        with mock.patch("urllib.request.urlopen", side_effect=fake_open):
            with pytest.raises(RuntimeError, match="HTTP 404"):
                client._request("GET", "/wc/v3/products/999")


# ---------------------------------------------------------------------------
# WCClient.paginate
# ---------------------------------------------------------------------------

class TestPaginate:
    def _client(self) -> WCClient:
        return WCClient("ck_x", "cs_x", base_url="https://example.com/wp-json")

    def test_single_page(self):
        client = self._client()
        items = [{"id": i} for i in range(5)]
        resp = _make_response(items)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            pages = list(client.paginate("/wc/v3/products"))
        assert len(pages) == 1
        assert pages[0] == items

    def test_multiple_pages(self):
        client = self._client()
        page_data = [[{"id": i} for i in range(100)], [{"id": i} for i in range(100, 120)]]
        call_index = [0]

        def fake_open(req, timeout=None):
            idx = call_index[0]
            call_index[0] += 1
            body = page_data[idx]
            resp = _make_response(
                body,
                headers={"X-WP-TotalPages": "2", "X-WP-Total": "120"},
            )
            return resp

        with mock.patch("urllib.request.urlopen", side_effect=fake_open):
            pages = list(client.paginate("/wc/v3/products"))

        assert len(pages) == 2
        assert len(pages[0]) == 100
        assert len(pages[1]) == 20


# ---------------------------------------------------------------------------
# WCClient.put dry_run
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_put_dry_run_does_not_call_api(self):
        client = WCClient("ck_x", "cs_x")
        with mock.patch("urllib.request.urlopen") as mock_open:
            result = client.put("/wc/v3/products/1", {"name": "X"}, dry_run=True)
        mock_open.assert_not_called()
        assert result is None

    def test_put_live_calls_api(self):
        client = WCClient("ck_x", "cs_x", base_url="https://example.com/wp-json")
        payload = {"id": 1, "name": "X"}
        with mock.patch("urllib.request.urlopen", return_value=_make_response(payload)):
            result = client.put("/wc/v3/products/1", {"name": "X"}, dry_run=False)
        assert result == payload


# ---------------------------------------------------------------------------
# Category validation
# ---------------------------------------------------------------------------

class TestCategoryValidation:
    def test_validate_raises_on_bad_id(self):
        client = WCClient("ck_x", "cs_x", base_url="https://example.com/wp-json")
        cats = [{"id": 651}, {"id": 652}]
        with mock.patch("urllib.request.urlopen", return_value=_make_response(cats)):
            with pytest.raises(ValueError, match="999"):
                client.validate_category_ids([651, 999])

    def test_validate_passes_on_good_ids(self):
        client = WCClient("ck_x", "cs_x", base_url="https://example.com/wp-json")
        cats = [{"id": 651}, {"id": 652}]
        with mock.patch("urllib.request.urlopen", return_value=_make_response(cats)):
            client.validate_category_ids([651, 652])  # must not raise


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class TestRateLimit:
    def test_rate_limit_enforced(self):
        client = WCClient("ck_x", "cs_x", base_url="https://example.com/wp-json", rate_limit=0.1)
        slept = []

        def fake_sleep(secs):
            slept.append(secs)

        with mock.patch("time.sleep", side_effect=fake_sleep), \
             mock.patch("urllib.request.urlopen", return_value=_make_response({})):
            # First call – no prior call, so no sleep needed (monotonic will handle it)
            client._last_call = time.monotonic() - 0.0  # simulate just called
            client._request("GET", "/wc/v3/test")

        # At least one sleep was requested at some point (depends on timing)
        # What we really test is that sleep is called if not enough time passed
        client2 = WCClient("ck_x", "cs_x", base_url="https://example.com/wp-json", rate_limit=10.0)
        client2._last_call = time.monotonic()  # just called
        with mock.patch("time.sleep", side_effect=fake_sleep), \
             mock.patch("urllib.request.urlopen", return_value=_make_response({})):
            client2._request("GET", "/wc/v3/test")

        assert any(s > 0 for s in slept)
