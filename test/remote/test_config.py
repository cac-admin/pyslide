# -*- coding: utf-8 -*-
""" Profile storage and setting resolution."""

from __future__ import annotations

import json

import pytest

from conftest import BASE_URL


def test_save_and_read_profile(remote_home):
    from pyslide.remote import _config as config

    config.save_profile("lab", {"base_url": BASE_URL, "timeout": 15})

    assert config.current_profile_name() == "lab"
    assert config.get_profile()["base_url"] == BASE_URL
    assert config.resolve_timeout() == 15.0
    assert config.config_path().is_file()


def test_saved_url_drops_version_suffix_and_slash(remote_home):
    from pyslide.remote import _config as config

    config.save_profile("lab", {"base_url": "https://host/api/remote/v1/"})

    assert config.get_profile("lab")["base_url"] == "https://host/api/remote"


def test_second_profile_can_be_added_without_becoming_active(remote_home):
    from pyslide.remote import _config as config

    config.save_profile("first", {"base_url": BASE_URL})
    config.save_profile(
        "second", {"base_url": "https://other.test"}, make_current=False
    )

    assert config.current_profile_name() == "first"
    assert sorted(config.list_profiles()) == ["first", "second"]

    config.use_profile("second")
    assert config.resolve_base_url() == "https://other.test"


def test_use_unknown_profile_reports_known_ones(remote_home):
    from pyslide.remote import _config as config
    from pyslide.remote._errors import RemoteConfigError

    config.save_profile("lab", {"base_url": BASE_URL})

    with pytest.raises(RemoteConfigError) as excinfo:
        config.use_profile("nope")
    assert "lab" in str(excinfo.value)


def test_delete_profile_moves_active_pointer(remote_home):
    from pyslide.remote import _config as config

    config.save_profile("a", {"base_url": BASE_URL})
    config.save_profile("b", {"base_url": "https://b.test"})

    assert config.delete_profile("b") is True
    assert config.current_profile_name() == "a"
    assert config.delete_profile("b") is False


def test_env_overrides_beat_saved_profile(remote_home, monkeypatch):
    from pyslide.remote import _config as config

    config.save_profile("lab", {"base_url": BASE_URL, "timeout": 5})
    monkeypatch.setenv("PYSLIDE_REMOTE_URL", "https://env.test/api/remote/v1")
    monkeypatch.setenv("PYSLIDE_REMOTE_TIMEOUT", "90")
    monkeypatch.setenv("PYSLIDE_REMOTE_VERIFY", "off")

    assert config.resolve_base_url() == "https://env.test/api/remote"
    assert config.resolve_timeout() == 90.0
    assert config.resolve_verify() is False


def test_explicit_arguments_beat_env(remote_home, monkeypatch):
    from pyslide.remote import _config as config

    monkeypatch.setenv("PYSLIDE_REMOTE_URL", "https://env.test")

    assert config.resolve_base_url("https://arg.test") == "https://arg.test"


def test_verify_accepts_ca_bundle_path(remote_home):
    from pyslide.remote import _config as config

    config.save_profile("lab", {"base_url": BASE_URL, "verify": "/ca.pem"})

    assert config.resolve_verify() == "/ca.pem"


def test_missing_url_explains_how_to_fix_it(remote_home):
    from pyslide.remote import _config as config
    from pyslide.remote._errors import RemoteConfigError

    with pytest.raises(RemoteConfigError) as excinfo:
        config.resolve_base_url()
    assert "pyslide-remote init" in str(excinfo.value)


def test_unreadable_config_is_treated_as_empty(remote_home):
    from pyslide.remote import _config as config

    path = config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is not json", encoding="utf-8")

    assert config.list_profiles() == {}


def test_read_connect_file(remote_home, tmp_path):
    from pyslide.remote import _config as config

    handoff = tmp_path / "pyslide-remote.json"
    handoff.write_text(
        json.dumps(
            {
                "name": "myserver",
                "base_url": "https://host/api/remote/v1",
                "protocol": "pyslide-remote/1",
                "token": "tok-handoff",
                "verify": True,
                "unknown_future_key": "ignored",
            }
        ),
        encoding="utf-8",
    )

    imported = config.read_connect_file(handoff)

    assert imported["name"] == "myserver"
    assert imported["token"] == "tok-handoff"
    assert imported["settings"]["base_url"] == "https://host/api/remote"
    assert "unknown_future_key" not in imported["settings"]


def test_connect_file_without_url_is_rejected(remote_home, tmp_path):
    from pyslide.remote import _config as config
    from pyslide.remote._errors import RemoteConfigError

    handoff = tmp_path / "bad.json"
    handoff.write_text(json.dumps({"name": "x"}), encoding="utf-8")

    with pytest.raises(RemoteConfigError, match="base_url"):
        config.read_connect_file(handoff)


def test_missing_connect_file_is_reported(remote_home, tmp_path):
    from pyslide.remote import _config as config
    from pyslide.remote._errors import RemoteConfigError

    with pytest.raises(RemoteConfigError, match="no such config file"):
        config.read_connect_file(tmp_path / "absent.json")
