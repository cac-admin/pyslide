# -*- coding: utf-8 -*-
""" Protocol client behaviour against a fake server."""

from __future__ import annotations

import pytest

from conftest import BASE_URL, CAPABILITIES, FakeConnectionError, FakeResponse, FakeTimeout


def make_client(**kwargs):
    from pyslide.remote._client import RemoteClient

    kwargs.setdefault("token", "tok-test")
    return RemoteClient(BASE_URL, **kwargs)


def test_paths_are_versioned_under_the_base_url(remote_home, fake_requests):
    fake_requests.route(
        "GET", "/v1/capabilities", FakeResponse(json_data=CAPABILITIES)
    )

    payload = make_client().capabilities()

    assert payload == CAPABILITIES
    assert fake_requests.urls("GET") == [
        "https://example.test/api/remote/v1/capabilities"
    ]


def test_base_url_with_version_suffix_is_not_doubled(remote_home, fake_requests):
    from pyslide.remote._client import RemoteClient

    fake_requests.route(
        "GET", "/v1/capabilities", FakeResponse(json_data=CAPABILITIES)
    )

    RemoteClient(BASE_URL + "/v1", token="t").capabilities()

    assert fake_requests.urls("GET")[0].count("/v1") == 1


def test_capabilities_needs_no_token(remote_home, fake_requests):
    from pyslide.remote._client import RemoteClient

    fake_requests.route(
        "GET", "/v1/capabilities", FakeResponse(json_data=CAPABILITIES)
    )

    RemoteClient(BASE_URL).capabilities()

    _method, _url, kwargs = fake_requests.calls[0]
    assert kwargs["headers"] == {}


def test_authenticated_requests_send_a_bearer_token(remote_home, fake_requests):
    fake_requests.route(
        "GET", "/v1/jobs/7", FakeResponse(json_data={"status": "pending"})
    )

    make_client(token="tok-abc").get_job("7")

    _method, _url, kwargs = fake_requests.calls[0]
    assert kwargs["headers"]["Authorization"] == "Bearer tok-abc"


def test_missing_token_is_reported_before_the_request(remote_home, fake_requests):
    from pyslide.remote._client import RemoteClient
    from pyslide.remote._errors import RemoteAuthError

    with pytest.raises(RemoteAuthError, match="pyslide-remote login"):
        RemoteClient(BASE_URL).get_job("7")
    assert fake_requests.calls == []


def test_protocol_mismatch_is_rejected(remote_home, fake_requests):
    from pyslide.remote._errors import RemoteProtocolError

    fake_requests.route(
        "GET",
        "/v1/capabilities",
        FakeResponse(json_data={"protocol": "pyslide-remote/2"}),
    )

    with pytest.raises(RemoteProtocolError, match="pyslide-remote/2"):
        make_client().check_protocol()


def test_server_without_protocol_field_is_rejected(remote_home, fake_requests):
    from pyslide.remote._errors import RemoteProtocolError

    fake_requests.route("GET", "/v1/capabilities", FakeResponse(json_data={}))

    with pytest.raises(RemoteProtocolError, match="does not look like"):
        make_client().check_protocol()


def test_login_returns_a_token(remote_home, fake_requests):
    fake_requests.route(
        "POST",
        "/v1/auth/login",
        FakeResponse(json_data={"token": "tok-new", "username": "tester"}),
    )

    payload = make_client().login("tester", "secret")

    assert payload["token"] == "tok-new"
    _method, _url, kwargs = fake_requests.calls[0]
    assert kwargs["json"] == {"username": "tester", "password": "secret"}


def test_login_without_a_token_in_the_body_is_a_protocol_error(
    remote_home, fake_requests
):
    from pyslide.remote._errors import RemoteProtocolError

    fake_requests.route(
        "POST", "/v1/auth/login", FakeResponse(json_data={"ok": True})
    )

    with pytest.raises(RemoteProtocolError, match="no 'token'"):
        make_client().login("tester", "secret")


def test_bad_credentials_raise_an_auth_error(remote_home, fake_requests):
    from pyslide.remote._errors import RemoteAuthError

    fake_requests.route(
        "POST",
        "/v1/auth/login",
        FakeResponse(
            status_code=401,
            json_data={"error": "invalid_credentials", "message": "Wrong password."},
        ),
    )

    with pytest.raises(RemoteAuthError) as excinfo:
        make_client().login("tester", "nope")

    assert str(excinfo.value) == "Wrong password."
    assert excinfo.value.error == "invalid_credentials"
    assert excinfo.value.status_code == 401


def test_submit_uploads_a_single_file_field(remote_home, fake_requests, tiny_slide):
    fake_requests.route(
        "POST", "/v1/jobs", FakeResponse(status_code=201, json_data={"id": "job-1"})
    )

    created = make_client().submit_job(tiny_slide)

    assert created["id"] == "job-1"
    _method, url, kwargs = fake_requests.calls[0]
    assert url.endswith("/v1/jobs")
    filename, _handle, content_type = kwargs["files"]["file"]
    assert filename == "slide.tif"
    assert content_type == "application/octet-stream"


def test_submit_without_a_job_id_is_a_protocol_error(
    remote_home, fake_requests, tiny_slide
):
    from pyslide.remote._errors import RemoteProtocolError

    fake_requests.route(
        "POST", "/v1/jobs", FakeResponse(status_code=201, json_data={})
    )

    with pytest.raises(RemoteProtocolError, match="no job 'id'"):
        make_client().submit_job(tiny_slide)


def test_unknown_job_status_is_a_protocol_error(remote_home, fake_requests):
    from pyslide.remote._errors import RemoteProtocolError

    fake_requests.route(
        "GET", "/v1/jobs/7", FakeResponse(json_data={"status": "almost-done"})
    )

    with pytest.raises(RemoteProtocolError, match="almost-done"):
        make_client().get_job("7")


def test_unknown_job_id_raises_job_not_found(remote_home, fake_requests):
    from pyslide.remote._errors import RemoteJobNotFound

    fake_requests.route(
        "GET",
        "/v1/jobs/7",
        FakeResponse(
            status_code=404, json_data={"error": "not_found", "message": "No job 7."}
        ),
    )

    with pytest.raises(RemoteJobNotFound, match="No job 7."):
        make_client().get_job("7")


def test_artifacts_skips_malformed_entries(remote_home, fake_requests):
    fake_requests.route(
        "GET",
        "/v1/jobs/7/artifacts",
        FakeResponse(
            json_data={
                "artifacts": [
                    {"name": "mask.png", "url": "/files/mask.png"},
                    {"name": "no-url"},
                    "not-an-object",
                    {"url": "/files/no-name"},
                ]
            }
        ),
    )

    artifacts = make_client().artifacts("7")

    assert artifacts == [{"name": "mask.png", "url": "/files/mask.png"}]


def test_submit_uses_a_long_read_timeout_by_default(
    remote_home, fake_requests, tiny_slide
):
    from pyslide.remote._config import DEFAULT_TIMEOUT, DEFAULT_UPLOAD_TIMEOUT

    fake_requests.route(
        "POST", "/v1/jobs", FakeResponse(status_code=201, json_data={"id": "job-1"})
    )

    make_client().submit_job(tiny_slide)

    _method, _url, kwargs = fake_requests.calls[0]
    assert kwargs["timeout"] == (DEFAULT_TIMEOUT, DEFAULT_UPLOAD_TIMEOUT)


def test_submit_does_not_retry_a_timeout(remote_home, fake_requests, tiny_slide):
    from pyslide.remote._errors import RemoteAPIError

    fake_requests.route("POST", "/v1/jobs", FakeTimeout("read timed out"))

    with pytest.raises(RemoteAPIError, match="upload failed after 1 attempt"):
        make_client().submit_job(tiny_slide)

    assert fake_requests.count("POST", "/v1/jobs") == 1


def test_artifact_listing_must_contain_the_array(remote_home, fake_requests):
    from pyslide.remote._errors import RemoteProtocolError

    fake_requests.route(
        "GET", "/v1/jobs/7/artifacts", FakeResponse(json_data={"files": []})
    )

    with pytest.raises(RemoteProtocolError, match="artifacts"):
        make_client().artifacts("7")


def test_relative_artifact_urls_resolve_against_the_server(remote_home):
    client = make_client()

    assert client.artifact_url("/files/a.png") == (
        "https://example.test/api/remote/files/a.png"
    )
    assert client.artifact_url("https://cdn.test/a.png") == "https://cdn.test/a.png"


def test_download_writes_the_file_and_leaves_no_partial(
    remote_home, fake_requests, tmp_path
):
    payload = b"x" * 4096
    fake_requests.route(
        "GET",
        "/files/mask.png",
        FakeResponse(content=payload, headers={"Content-Length": str(len(payload))}),
    )

    dest = tmp_path / "out" / "mask.png"
    written = make_client().download_artifact(
        {"name": "mask.png", "url": "/files/mask.png"}, dest
    )

    assert dest.read_bytes() == payload
    assert written == str(dest)
    assert not (tmp_path / "out" / "mask.png.part").exists()


def test_failed_download_does_not_leave_a_file_behind(
    remote_home, fake_requests, tmp_path
):
    from pyslide.remote._errors import RemoteAPIError

    fake_requests.route(
        "GET",
        "/files/mask.png",
        FakeResponse(status_code=403, json_data={"message": "Not yours."}),
    )

    dest = tmp_path / "mask.png"
    with pytest.raises(RemoteAPIError):
        make_client().download_artifact({"name": "m", "url": "/files/mask.png"}, dest)

    assert not dest.exists()
    assert not dest.with_suffix(".png.part").exists()


def test_transient_server_errors_are_retried(remote_home, fake_requests):
    fake_requests.route(
        "GET",
        "/v1/jobs/7",
        FakeResponse(status_code=503, text="upstream busy"),
        FakeResponse(json_data={"status": "processing"}),
    )

    payload = make_client().get_job("7")

    assert payload["status"] == "processing"
    assert fake_requests.count("GET", "/v1/jobs/7") == 2


def test_network_errors_are_retried_then_reported(remote_home, fake_requests):
    from pyslide.remote._errors import RemoteAPIError

    fake_requests.route(
        "GET",
        "/v1/jobs/7",
        FakeConnectionError("connection reset"),
        FakeConnectionError("connection reset"),
        FakeConnectionError("connection reset"),
    )

    with pytest.raises(RemoteAPIError, match="status failed after 3 attempt"):
        make_client().get_job("7")


def test_auth_failures_are_not_retried(remote_home, fake_requests):
    from pyslide.remote._errors import RemoteAuthError

    fake_requests.route(
        "GET", "/v1/jobs/7", FakeResponse(status_code=401, json_data={})
    )

    with pytest.raises(RemoteAuthError):
        make_client().get_job("7")
    assert fake_requests.count("GET", "/v1/jobs/7") == 1


def test_non_json_error_bodies_still_produce_a_message(remote_home, fake_requests):
    from pyslide.remote._errors import RemoteAPIError

    fake_requests.route(
        "GET", "/v1/jobs/7", FakeResponse(status_code=500, text="Server Error")
    )

    with pytest.raises(RemoteAPIError, match="Server Error"):
        make_client().get_job("7")


def test_a_detail_only_error_body_is_read_as_the_message(remote_home, fake_requests):
    from pyslide.remote._errors import RemoteAPIError

    fake_requests.route(
        "GET",
        "/v1/jobs/7",
        FakeResponse(status_code=409, json_data={"detail": "Slide is locked."}),
    )

    with pytest.raises(RemoteAPIError) as excinfo:
        make_client().get_job("7")

    assert str(excinfo.value) == "Slide is locked."
