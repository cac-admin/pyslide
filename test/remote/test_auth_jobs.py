# -*- coding: utf-8 -*-
""" Token storage and the local job registry."""

from __future__ import annotations

import json

import pytest

from conftest import BASE_URL, FakeResponse


def test_tokens_are_stored_per_profile(remote_home):
    from pyslide.remote import _auth as auth

    auth.save_token("tok-a", profile="a", username="alice")
    auth.save_token("tok-b", profile="b")

    assert auth.load_token("a") == "tok-a"
    assert auth.load_token("b") == "tok-b"
    assert auth.load_token("c") is None


def test_env_token_wins_over_stored_one(remote_home, monkeypatch):
    from pyslide.remote import _auth as auth

    auth.save_token("tok-stored", profile="default")
    monkeypatch.setenv("PYSLIDE_REMOTE_TOKEN", "tok-env")

    assert auth.load_token("default") == "tok-env"


def test_clearing_one_profile_keeps_the_others(remote_home):
    from pyslide.remote import _auth as auth

    auth.save_token("tok-a", profile="a")
    auth.save_token("tok-b", profile="b")

    assert auth.clear_token("a") is True
    assert auth.load_token("a") is None
    assert auth.load_token("b") == "tok-b"
    assert auth.clear_token("a") is False


def test_clearing_the_last_profile_removes_the_file(remote_home):
    from pyslide.remote import _auth as auth

    auth.save_token("tok-a", profile="a")
    auth.clear_token("a")

    assert not auth.credentials_path().exists()


def test_stored_token_is_not_written_into_the_config_file(remote_home):
    from pyslide.remote import _auth as auth, _config as config

    config.save_profile("default", {"base_url": BASE_URL})
    auth.save_token("tok-secret", profile="default")

    assert "tok-secret" not in config.config_path().read_text(encoding="utf-8")
    saved = json.loads(auth.credentials_path().read_text(encoding="utf-8"))
    assert saved["profiles"]["default"]["token"] == "tok-secret"


def test_ensure_token_prefers_the_stored_token(remote_home, fake_requests):
    from pyslide.remote import _auth as auth
    from pyslide.remote._client import RemoteClient

    auth.save_token("tok-stored", profile="default")
    client = RemoteClient(BASE_URL)

    assert auth.ensure_token(client, profile="default") == "tok-stored"
    assert fake_requests.calls == []


def test_ensure_token_logs_in_when_forced(remote_home, fake_requests, monkeypatch):
    from pyslide.remote import _auth as auth
    from pyslide.remote._client import RemoteClient

    auth.save_token("tok-old", profile="default")
    monkeypatch.setenv("PYSLIDE_REMOTE_USER", "tester")
    monkeypatch.setenv("PYSLIDE_REMOTE_PASSWORD", "secret")
    fake_requests.route(
        "POST",
        "/v1/auth/login",
        FakeResponse(json_data={"token": "tok-new", "username": "tester"}),
    )

    token = auth.ensure_token(
        RemoteClient(BASE_URL), profile="default", force_login=True
    )

    assert token == "tok-new"
    assert auth.load_token("default") == "tok-new"


def test_login_prompts_when_nothing_is_supplied(remote_home, fake_requests, monkeypatch):
    from pyslide.remote import _auth as auth
    from pyslide.remote._client import RemoteClient

    prompts = []

    def fake_prompt(text, *, secret=False):
        prompts.append((text, secret))
        return "typed-secret" if secret else "typed-user"

    monkeypatch.setattr(auth, "_prompt", fake_prompt)
    fake_requests.route(
        "POST", "/v1/auth/login", FakeResponse(json_data={"token": "tok-typed"})
    )

    token = auth.ensure_token(RemoteClient(BASE_URL), profile="default")

    assert token == "tok-typed"
    assert [secret for _text, secret in prompts] == [False, True]


def test_image_key_tracks_file_content(remote_home, tiny_slide):
    from pyslide.remote import _jobs as jobs

    first = jobs.image_key(tiny_slide)
    tiny_slide.write_bytes(b"a longer set of slide bytes than before")

    assert jobs.image_key(tiny_slide) != first


def test_image_key_requires_the_file_to_exist(remote_home, tmp_path):
    from pyslide.remote import _jobs as jobs

    with pytest.raises(FileNotFoundError):
        jobs.image_key(tmp_path / "absent.tif")


def test_job_records_are_scoped_to_a_profile(remote_home, tiny_slide):
    from pyslide.remote import _jobs as jobs

    key = jobs.image_key(tiny_slide)
    jobs.set_job_id(key, "job-a", profile="a")
    jobs.set_job_id(key, "job-b", profile="b")

    assert jobs.get_job_id(key, profile="a") == "job-a"
    assert jobs.get_job_id(key, profile="b") == "job-b"

    assert jobs.clear_job_id(key, profile="a") is True
    assert jobs.get_job_id(key, profile="a") is None
    assert jobs.get_job_id(key, profile="b") == "job-b"


def test_job_id_must_not_be_empty(remote_home, tiny_slide):
    from pyslide.remote import _jobs as jobs

    with pytest.raises(ValueError):
        jobs.set_job_id(jobs.image_key(tiny_slide), None)
