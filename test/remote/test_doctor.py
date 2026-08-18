# -*- coding: utf-8 -*-
""" Diagnostics for configuration, transport, protocol, and login."""

from __future__ import annotations

from conftest import CAPABILITIES, FakeConnectionError, FakeResponse


def check(checks, name):
    """ Return the check called ``name``."""
    for item in checks:
        if item.name == name:
            return item
    raise AssertionError(f"no check named {name!r} in {[c.name for c in checks]}")


def test_missing_configuration_stops_early(remote_home):
    from pyslide.remote._doctor import run_checks

    checks = run_checks()

    assert [item.name for item in checks] == ["config"]
    assert check(checks, "config").ok is False


def test_non_http_url_is_rejected(remote_home):
    from pyslide.remote import _config as config
    from pyslide.remote._doctor import run_checks

    config.save_profile("default", {"base_url": "example.test/api"})

    assert check(run_checks(), "config").ok is False


def test_healthy_server_passes_everything(profile, fake_requests):
    from pyslide.remote._doctor import run_checks

    fake_requests.route(
        "GET", "/v1/capabilities", FakeResponse(json_data=CAPABILITIES)
    )
    fake_requests.route(
        "GET", "/v1/auth/whoami", FakeResponse(json_data={"username": "tester"})
    )

    checks = run_checks()

    assert check(checks, "reachable").ok is True
    assert check(checks, "protocol").ok is True
    assert check(checks, "auth").ok is True
    assert "2.0 GiB" in check(checks, "limits").detail


def test_unreachable_server_skips_later_checks(profile, fake_requests):
    from pyslide.remote._doctor import run_checks

    fake_requests.route(
        "GET", "/v1/capabilities", FakeConnectionError("connection refused")
    )

    checks = run_checks()

    assert check(checks, "reachable").ok is False
    assert [item.name for item in checks] == ["config", "tls", "reachable"]


def test_disabled_certificate_check_is_called_out(remote_home, fake_requests):
    from pyslide.remote import _config as config
    from pyslide.remote._doctor import run_checks

    config.save_profile(
        "default", {"base_url": "https://example.test/api/remote", "verify": False}
    )
    fake_requests.route(
        "GET", "/v1/capabilities", FakeResponse(json_data=CAPABILITIES)
    )

    tls = check(run_checks(), "tls")

    assert tls.ok is None
    assert "verification is disabled" in tls.detail


def test_plain_http_is_called_out(remote_home, fake_requests):
    from pyslide.remote import _config as config
    from pyslide.remote._doctor import run_checks

    config.save_profile("default", {"base_url": "http://example.test/api/remote"})
    fake_requests.route(
        "GET", "/v1/capabilities", FakeResponse(json_data=CAPABILITIES)
    )

    tls = check(run_checks(), "tls")

    assert tls.ok is None
    assert "unencrypted" in tls.detail


def test_missing_token_is_flagged(remote_home, fake_requests):
    from pyslide.remote import _config as config
    from pyslide.remote._doctor import run_checks

    config.save_profile("default", {"base_url": "https://example.test/api/remote"})
    fake_requests.route(
        "GET", "/v1/capabilities", FakeResponse(json_data=CAPABILITIES)
    )

    auth = check(run_checks(), "auth")

    assert auth.ok is False
    assert "pyslide-remote login" in auth.detail


def test_rejected_token_tells_the_user_to_log_in_again(profile, fake_requests):
    from pyslide.remote._doctor import run_checks

    fake_requests.route(
        "GET", "/v1/capabilities", FakeResponse(json_data=CAPABILITIES)
    )
    fake_requests.route(
        "GET",
        "/v1/auth/whoami",
        FakeResponse(status_code=401, json_data={"message": "Expired."}),
    )

    auth = check(run_checks(), "auth")

    assert auth.ok is False
    assert "pyslide-remote login" in auth.detail


def test_server_without_whoami_leaves_auth_unverified(profile, fake_requests):
    from pyslide.remote._doctor import run_checks

    fake_requests.route(
        "GET", "/v1/capabilities", FakeResponse(json_data=CAPABILITIES)
    )
    fake_requests.route("GET", "/v1/auth/whoami", FakeResponse(status_code=404))

    auth = check(run_checks(), "auth")

    assert auth.ok is None
    assert "could not be verified" in auth.detail


def test_report_lines_are_aligned(profile, fake_requests):
    from pyslide.remote._doctor import format_report, run_checks

    fake_requests.route(
        "GET", "/v1/capabilities", FakeResponse(json_data=CAPABILITIES)
    )
    fake_requests.route(
        "GET", "/v1/auth/whoami", FakeResponse(json_data={"username": "tester"})
    )

    report = format_report(run_checks())

    assert all(line.startswith("[") for line in report.splitlines())
