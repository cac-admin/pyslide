# -*- coding: utf-8 -*-
""" Command line behaviour, including exit codes."""

from __future__ import annotations

import json

import pytest

from conftest import BASE_URL, CAPABILITIES, FakeResponse


def run(argv):
    from pyslide.remote.cli import main

    return main(argv)


def test_no_command_prints_help(remote_home, capsys):
    assert run([]) == 1
    assert "pyslide-remote" in capsys.readouterr().out


def test_init_from_a_server_config_file(remote_home, fake_requests, tmp_path, capsys):
    from pyslide.remote import _auth as auth, _config as config

    handoff = tmp_path / "pyslide-remote.json"
    handoff.write_text(
        json.dumps(
            {
                "name": "lab",
                "base_url": BASE_URL,
                "protocol": "pyslide-remote/1",
                "token": "tok-handoff",
            }
        ),
        encoding="utf-8",
    )
    fake_requests.route(
        "GET", "/v1/capabilities", FakeResponse(json_data=CAPABILITIES)
    )

    assert run(["init", "--from", str(handoff)]) == 0

    assert config.current_profile_name() == "lab"
    assert config.get_profile("lab")["base_url"] == BASE_URL
    assert auth.load_token("lab") == "tok-handoff"
    assert "pyslide-remote annotate" in capsys.readouterr().out


def test_init_with_a_url_and_token(remote_home, fake_requests, capsys):
    from pyslide.remote import _auth as auth, _config as config

    fake_requests.route(
        "GET", "/v1/capabilities", FakeResponse(json_data=CAPABILITIES)
    )

    code = run(
        ["init", "--url", BASE_URL + "/v1", "--name", "lab", "--token", "tok-pasted"]
    )

    assert code == 0
    assert config.get_profile("lab")["base_url"] == BASE_URL
    assert auth.load_token("lab") == "tok-pasted"


def test_init_warns_when_the_server_is_not_compatible(
    remote_home, fake_requests, capsys
):
    fake_requests.route(
        "GET",
        "/v1/capabilities",
        FakeResponse(json_data={"protocol": "something-else/9"}),
    )

    code = run(["init", "--url", BASE_URL, "--token", "tok", "--no-login"])

    assert code == 0
    captured = capsys.readouterr()
    assert "could not verify the server" in captured.err
    assert "doctor" in captured.err


def test_init_without_a_url_fails(remote_home, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    assert run(["init"]) == 1
    assert "server URL is required" in capsys.readouterr().err


def test_profiles_marks_the_active_one(profile, capsys):
    from pyslide.remote import _config as config

    config.save_profile("other", {"base_url": "https://other.test"}, make_current=False)

    assert run(["profiles"]) == 0

    out = capsys.readouterr().out
    assert "* default" in out
    assert "  other" in out
    assert "token" in out


def test_profiles_as_json(profile, capsys):
    assert run(["--json", "profiles"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["current"] == "default"
    assert payload["profiles"]["default"]["base_url"] == BASE_URL


def test_use_switches_the_active_profile(profile, capsys):
    from pyslide.remote import _config as config

    config.save_profile("other", {"base_url": "https://other.test"}, make_current=False)

    assert run(["use", "other"]) == 0
    assert config.current_profile_name() == "other"


def test_use_reports_an_unknown_profile(profile, capsys):
    assert run(["use", "nope"]) == 1
    assert "unknown profile" in capsys.readouterr().err


def test_login_stores_a_pasted_token(profile, capsys):
    from pyslide.remote import _auth as auth

    assert run(["login", "--token", "tok-pasted"]) == 0
    assert auth.load_token("default") == "tok-pasted"


def test_login_with_credentials(profile, fake_requests, capsys):
    from pyslide.remote import _auth as auth

    fake_requests.route(
        "POST", "/v1/auth/login", FakeResponse(json_data={"token": "tok-login"})
    )

    code = run(["login", "--username", "tester", "--password", "secret"])

    assert code == 0
    assert auth.load_token("default") == "tok-login"


def test_logout_forgets_the_token(profile, capsys):
    from pyslide.remote import _auth as auth

    assert run(["logout"]) == 0
    assert auth.load_token("default") is None
    assert run(["logout"]) == 0
    assert "No token" in capsys.readouterr().out


def test_annotate_prints_results_and_exits_zero(
    profile, fake_requests, tiny_slide, tmp_path, capsys
):
    fake_requests.route(
        "POST", "/v1/jobs", FakeResponse(status_code=201, json_data={"id": "job-1"})
    )
    fake_requests.route(
        "GET", "/v1/jobs/job-1", FakeResponse(json_data={"status": "completed"})
    )
    fake_requests.route(
        "GET",
        "/v1/jobs/job-1/artifacts",
        FakeResponse(json_data={"artifacts": [{"name": "mask.png", "url": "/f/m"}]}),
    )
    fake_requests.route("GET", "/f/m", FakeResponse(content=b"mask"))

    code = run(
        ["annotate", str(tiny_slide), "--results-dir", str(tmp_path / "out")]
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "job:       job-1" in out
    assert "status:    completed" in out
    assert "mask.png" in out


def test_annotate_json_output_is_parseable(
    profile, fake_requests, tiny_slide, tmp_path, capsys
):
    fake_requests.route(
        "POST", "/v1/jobs", FakeResponse(status_code=201, json_data={"id": "job-1"})
    )
    fake_requests.route(
        "GET", "/v1/jobs/job-1", FakeResponse(json_data={"status": "pending"})
    )

    code = run(["--json", "annotate", str(tiny_slide), "--no-wait"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["job_id"] == "job-1"
    assert payload["status"] == "pending"


def test_failed_job_exits_with_three(
    profile, fake_requests, tiny_slide, tmp_path, capsys
):
    fake_requests.route(
        "POST", "/v1/jobs", FakeResponse(status_code=201, json_data={"id": "job-1"})
    )
    fake_requests.route(
        "GET",
        "/v1/jobs/job-1",
        FakeResponse(json_data={"status": "failed", "message": "Unreadable slide."}),
    )

    code = run(["annotate", str(tiny_slide)])

    assert code == 3
    assert "Unreadable slide." in capsys.readouterr().out


def test_status_without_a_job_exits_with_two(profile, fake_requests, tiny_slide, capsys):
    code = run(["status", str(tiny_slide)])

    assert code == 2
    assert "run annotate first" in capsys.readouterr().out


def test_missing_slide_exits_with_one(profile, fake_requests, tmp_path, capsys):
    code = run(["annotate", str(tmp_path / "absent.tif")])

    assert code == 1
    assert "error:" in capsys.readouterr().err


def test_doctor_reports_every_check(profile, fake_requests, capsys):
    fake_requests.route(
        "GET", "/v1/capabilities", FakeResponse(json_data=CAPABILITIES)
    )
    fake_requests.route(
        "GET", "/v1/auth/whoami", FakeResponse(json_data={"username": "tester"})
    )

    assert run(["doctor"]) == 0

    out = capsys.readouterr().out
    assert "[ok  ] config" in out
    assert "[ok  ] protocol" in out
    assert "tester" in out


def test_doctor_fails_when_the_server_is_unreachable(profile, fake_requests, capsys):
    from conftest import FakeConnectionError

    fake_requests.route(
        "GET", "/v1/capabilities", FakeConnectionError("name not resolved")
    )

    assert run(["doctor"]) == 1
    assert "[FAIL] reachable" in capsys.readouterr().out


def test_doctor_json_output(profile, fake_requests, capsys):
    fake_requests.route(
        "GET", "/v1/capabilities", FakeResponse(json_data=CAPABILITIES)
    )
    fake_requests.route(
        "GET", "/v1/auth/whoami", FakeResponse(json_data={"username": "tester"})
    )

    assert run(["--json", "doctor"]) == 0

    checks = json.loads(capsys.readouterr().out)
    assert {check["name"] for check in checks} >= {
        "config",
        "tls",
        "reachable",
        "protocol",
        "auth",
    }
