# -*- coding: utf-8 -*-
""" Fixtures for the remote annotation client tests."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

PRJ_PATH = Path(__file__).resolve().parents[2]

# Bind the package directory without executing pyslide/__init__.py, which
# imports the whole imaging stack. The remote client needs nothing but an HTTP
# library, and importing it this way keeps that true.
if "pyslide" not in sys.modules:
    _package = types.ModuleType("pyslide")
    _package.__path__ = [str(PRJ_PATH / "pyslide")]
    sys.modules["pyslide"] = _package

BASE_URL = "https://example.test/api/remote"
CAPABILITIES = {
    "protocol": "pyslide-remote/1",
    "auth_methods": ["login", "token"],
    "max_upload_bytes": 2 * 1024 ** 3,
}


class FakeResponse:
    """ Stand-in for a ``requests`` response."""

    def __init__(
        self,
        status_code=200,
        json_data=None,
        text="",
        content=b"",
        headers=None,
    ):
        self.status_code = status_code
        self._json = json_data
        self.text = text or ""
        self.content = content
        self.headers = headers or {}

    def json(self):
        if self._json is None:
            raise ValueError("response body is not JSON")
        return self._json

    def iter_content(self, chunk_size=1):
        for start in range(0, len(self.content), max(chunk_size, 1)):
            yield self.content[start : start + max(chunk_size, 1)]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeRequests:
    """ Minimal ``requests`` replacement that replays queued responses.

    Responses are registered per ``(method, url-suffix)`` so tests read as a
    description of the server rather than a call order.
    """

    def __init__(self):
        self.calls = []
        self._routes = {}
        self.exceptions = types.SimpleNamespace(
            ConnectionError=FakeConnectionError,
            Timeout=FakeTimeout,
            ChunkedEncodingError=FakeChunkedEncodingError,
            RequestException=Exception,
        )

    def route(self, method, suffix, *responses):
        """ Queue one or more responses for URLs ending with ``suffix``."""
        self._routes.setdefault((method.upper(), suffix), []).extend(responses)
        return self

    def _resolve(self, method, url):
        matches = [
            key
            for key in self._routes
            if key[0] == method and url.endswith(key[1])
        ]
        if not matches:
            raise AssertionError(f"unexpected {method} {url}")
        # Prefer the most specific registered suffix.
        key = max(matches, key=lambda item: len(item[1]))
        queued = self._routes[key]
        if not queued:
            raise AssertionError(f"no responses left for {method} {key[1]}")
        response = queued[0] if len(queued) == 1 else queued.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self._resolve("GET", url)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self._resolve("POST", url)

    def urls(self, method=None):
        """ URLs requested so far, optionally filtered by method."""
        return [
            url
            for call_method, url, _kwargs in self.calls
            if method is None or call_method == method
        ]

    def count(self, method, suffix):
        """ How many times a matching request was made."""
        return sum(
            1
            for call_method, url, _kwargs in self.calls
            if call_method == method and url.endswith(suffix)
        )


class FakeConnectionError(Exception):
    """ Network-level failure, treated as transient by the client."""


class FakeTimeout(Exception):
    """ Timeout failure, treated as transient by the client."""


class FakeChunkedEncodingError(Exception):
    """ Truncated response, treated as transient by the client."""


@pytest.fixture
def remote_home(tmp_path, monkeypatch):
    """ Redirect config, credentials, and job records into a temp directory."""
    home = tmp_path / "remote-home"
    monkeypatch.setenv("PYSLIDE_REMOTE_HOME", str(home))
    for name in (
        "PYSLIDE_REMOTE_URL",
        "PYSLIDE_REMOTE_PROFILE",
        "PYSLIDE_REMOTE_TOKEN",
        "PYSLIDE_REMOTE_VERIFY",
        "PYSLIDE_REMOTE_TIMEOUT",
        "PYSLIDE_REMOTE_USER",
        "PYSLIDE_REMOTE_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    return home


@pytest.fixture
def profile(remote_home):
    """ A saved profile with a stored token, as after a successful init."""
    from pyslide.remote import _auth as auth, _config as config

    config.save_profile("default", {"base_url": BASE_URL})
    auth.save_token("tok-saved", profile="default", username="tester")
    return "default"


@pytest.fixture
def fake_requests(monkeypatch):
    """ Install a fake ``requests`` module and hand it to the test."""
    fake = FakeRequests()
    monkeypatch.setitem(sys.modules, "requests", fake)
    return fake


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """ Keep retry and poll backoff from actually sleeping."""
    monkeypatch.setattr("time.sleep", lambda seconds: None)


@pytest.fixture
def tiny_slide(tmp_path):
    """ A small file that stands in for a slide upload."""
    path = tmp_path / "slide.tif"
    path.write_bytes(b"not-a-real-slide")
    return path
