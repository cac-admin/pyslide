# -*- coding: utf-8 -*-
""" The end-to-end submit, wait, download flow."""

from __future__ import annotations

import pytest

from conftest import FakeResponse


def submitted_job(fake_requests, job_id="job-1"):
    """ Register an upload that creates ``job_id``."""
    fake_requests.route(
        "POST",
        "/v1/jobs",
        FakeResponse(status_code=201, json_data={"id": job_id}),
    )
    return job_id


def completed_job(fake_requests, job_id="job-1", artifacts=None, content=b"data"):
    """ Register a job that is already finished with one artifact."""
    fake_requests.route(
        "GET",
        f"/v1/jobs/{job_id}",
        FakeResponse(json_data={"id": job_id, "status": "completed"}),
    )
    entries = (
        artifacts
        if artifacts is not None
        else [{"name": "mask.png", "url": "/files/mask.png"}]
    )
    fake_requests.route(
        "GET",
        f"/v1/jobs/{job_id}/artifacts",
        FakeResponse(json_data={"artifacts": entries}),
    )
    for entry in entries:
        fake_requests.route(
            "GET", entry["url"], FakeResponse(content=content)
        )


def test_first_run_uploads_waits_and_downloads(
    profile, fake_requests, tiny_slide, tmp_path
):
    from pyslide.remote import _annotate as annotate_module

    submitted_job(fake_requests)
    completed_job(fake_requests, content=b"mask-bytes")

    result = annotate_module.annotate(
        tiny_slide, results_dir=tmp_path / "out", progress=False
    )

    assert result["submitted"] is True
    assert result["job_id"] == "job-1"
    assert result["status"] == "completed"
    assert len(result["paths"]) == 1

    written = tmp_path / "out" / "job-1" / "mask.png"
    assert written.read_bytes() == b"mask-bytes"


def test_second_run_reuses_the_recorded_job(
    profile, fake_requests, tiny_slide, tmp_path
):
    from pyslide.remote import _annotate as annotate_module

    submitted_job(fake_requests)
    completed_job(fake_requests)

    first = annotate_module.annotate(
        tiny_slide, results_dir=tmp_path / "out", progress=False
    )
    second = annotate_module.annotate(
        tiny_slide, results_dir=tmp_path / "out", progress=False
    )

    assert first["submitted"] is True
    assert second["submitted"] is False
    assert second["job_id"] == first["job_id"]
    assert fake_requests.count("POST", "/v1/jobs") == 1


def test_editing_the_slide_starts_a_new_job(
    profile, fake_requests, tiny_slide, tmp_path
):
    from pyslide.remote import _annotate as annotate_module

    submitted_job(fake_requests)
    completed_job(fake_requests)

    annotate_module.annotate(
        tiny_slide, results_dir=tmp_path / "out", progress=False
    )
    tiny_slide.write_bytes(b"a different slide entirely")
    second = annotate_module.annotate(
        tiny_slide, results_dir=tmp_path / "out", progress=False
    )

    assert second["submitted"] is True
    assert fake_requests.count("POST", "/v1/jobs") == 2


def test_waiting_polls_until_the_job_finishes(
    profile, fake_requests, tiny_slide, tmp_path
):
    from pyslide.remote import _annotate as annotate_module

    submitted_job(fake_requests)
    fake_requests.route(
        "GET",
        "/v1/jobs/job-1",
        FakeResponse(json_data={"status": "pending"}),
        FakeResponse(json_data={"status": "processing", "progress": 40}),
        FakeResponse(json_data={"status": "completed"}),
    )
    fake_requests.route(
        "GET", "/v1/jobs/job-1/artifacts", FakeResponse(json_data={"artifacts": []})
    )

    result = annotate_module.annotate(
        tiny_slide,
        poll_interval=0.1,
        results_dir=tmp_path / "out",
        progress=False,
    )

    assert result["status"] == "completed"
    assert fake_requests.count("GET", "/v1/jobs/job-1") == 3


def test_no_wait_returns_the_current_state(
    profile, fake_requests, tiny_slide, tmp_path
):
    from pyslide.remote import _annotate as annotate_module

    submitted_job(fake_requests)
    fake_requests.route(
        "GET", "/v1/jobs/job-1", FakeResponse(json_data={"status": "pending"})
    )

    result = annotate_module.annotate(
        tiny_slide, wait=False, results_dir=tmp_path / "out", progress=False
    )

    assert result["status"] == "pending"
    assert result["paths"] == []
    assert fake_requests.count("GET", "/v1/jobs/job-1/artifacts") == 0


def test_failed_job_is_reported_with_its_message(
    profile, fake_requests, tiny_slide, tmp_path
):
    from pyslide.remote import _annotate as annotate_module

    submitted_job(fake_requests)
    fake_requests.route(
        "GET",
        "/v1/jobs/job-1",
        FakeResponse(
            json_data={"status": "failed", "message": "Slide could not be read."}
        ),
    )

    result = annotate_module.annotate(
        tiny_slide, results_dir=tmp_path / "out", progress=False
    )

    assert result["status"] == "failed"
    assert result["message"] == "Slide could not be read."
    assert result["paths"] == []


def test_status_without_a_job_says_so(profile, fake_requests, tiny_slide):
    from pyslide.remote import _annotate as annotate_module

    result = annotate_module.status(tiny_slide, progress=False)

    assert result["job_id"] is None
    assert result["status"] is None
    assert "run annotate first" in result["message"]
    assert fake_requests.calls == []


def test_job_forgotten_by_the_server_is_resubmitted(
    profile, fake_requests, tiny_slide, tmp_path
):
    from pyslide.remote import _annotate as annotate_module
    from pyslide.remote import _jobs as jobs

    jobs.set_job_id(jobs.image_key(tiny_slide), "stale-job", profile=profile)
    fake_requests.route(
        "GET",
        "/v1/jobs/stale-job",
        FakeResponse(status_code=404, json_data={"message": "No such job."}),
    )
    submitted_job(fake_requests, "job-2")
    completed_job(fake_requests, "job-2")

    result = annotate_module.annotate(
        tiny_slide, results_dir=tmp_path / "out", progress=False
    )

    assert result["submitted"] is True
    assert result["job_id"] == "job-2"
    assert result["status"] == "completed"


def test_status_reports_a_job_the_server_forgot(profile, fake_requests, tiny_slide):
    from pyslide.remote import _annotate as annotate_module
    from pyslide.remote import _jobs as jobs

    key = jobs.image_key(tiny_slide)
    jobs.set_job_id(key, "stale-job", profile=profile)
    fake_requests.route(
        "GET", "/v1/jobs/stale-job", FakeResponse(status_code=404, json_data={})
    )

    result = annotate_module.status(tiny_slide, progress=False)

    assert result["job_id"] is None
    assert "unknown to the server" in result["message"]
    assert jobs.get_job_id(key, profile=profile) is None


def test_expired_token_triggers_one_more_login(
    profile, fake_requests, tiny_slide, tmp_path, monkeypatch
):
    from pyslide.remote import _annotate as annotate_module
    from pyslide.remote import _auth as auth

    monkeypatch.setenv("PYSLIDE_REMOTE_USER", "tester")
    monkeypatch.setenv("PYSLIDE_REMOTE_PASSWORD", "secret")

    submitted_job(fake_requests)
    fake_requests.route(
        "GET",
        "/v1/jobs/job-1",
        FakeResponse(status_code=401, json_data={"message": "Token expired."}),
        FakeResponse(json_data={"status": "completed"}),
    )
    fake_requests.route(
        "GET", "/v1/jobs/job-1/artifacts", FakeResponse(json_data={"artifacts": []})
    )
    fake_requests.route(
        "POST", "/v1/auth/login", FakeResponse(json_data={"token": "tok-fresh"})
    )

    result = annotate_module.annotate(
        tiny_slide, results_dir=tmp_path / "out", progress=False
    )

    assert result["status"] == "completed"
    assert auth.load_token(profile) == "tok-fresh"
    assert fake_requests.count("POST", "/v1/auth/login") == 1


def test_artifact_names_cannot_escape_the_results_directory(
    profile, fake_requests, tiny_slide, tmp_path
):
    from pyslide.remote import _annotate as annotate_module

    submitted_job(fake_requests)
    completed_job(
        fake_requests,
        artifacts=[
            {"name": "../../etc/passwd", "url": "/files/a"},
            {"name": "C:\\Windows\\system32\\evil.dll", "url": "/files/b"},
        ],
    )

    result = annotate_module.annotate(
        tiny_slide, results_dir=tmp_path / "out", progress=False
    )

    job_dir = tmp_path / "out" / "job-1"
    written = sorted(path.name for path in job_dir.iterdir())
    assert written == ["evil.dll", "passwd"]
    assert all(str(job_dir) in path for path in result["paths"])


def test_artifacts_sharing_a_safe_name_are_both_kept(
    profile, fake_requests, tiny_slide, tmp_path
):
    from pyslide.remote import _annotate as annotate_module

    submitted_job(fake_requests)
    completed_job(
        fake_requests,
        artifacts=[
            {"name": "a/mask.png", "url": "/files/a"},
            {"name": "b/mask.png", "url": "/files/b"},
        ],
    )

    result = annotate_module.annotate(
        tiny_slide, results_dir=tmp_path / "out", progress=False
    )

    assert len(result["paths"]) == 2
    assert len(set(result["paths"])) == 2


def test_missing_slide_is_reported_before_any_request(profile, fake_requests, tmp_path):
    from pyslide.remote import _annotate as annotate_module

    with pytest.raises(FileNotFoundError):
        annotate_module.annotate(tmp_path / "absent.tif", progress=False)
    assert fake_requests.calls == []


def test_unconfigured_profile_explains_the_next_step(
    remote_home, fake_requests, tiny_slide
):
    from pyslide.remote import _annotate as annotate_module
    from pyslide.remote._errors import RemoteConfigError

    with pytest.raises(RemoteConfigError, match="pyslide-remote init"):
        annotate_module.annotate(tiny_slide, progress=False)


def test_vsi_slide_uploads_as_a_zip_and_cleans_up(
    profile, fake_requests, tmp_path, monkeypatch
):
    from pyslide.remote import _annotate as annotate_module

    slide = tmp_path / "slide.vsi"
    slide.write_bytes(b"vsi-header")
    companion = tmp_path / "_slide_"
    companion.mkdir()
    (companion / "frame_0.ets").write_bytes(b"pyramid-data")

    submitted_job(fake_requests)
    completed_job(fake_requests, artifacts=[])

    temp_paths = []
    real_prepare = annotate_module.prepare_upload_path

    def record(path):
        upload_path, cleanup = real_prepare(path)
        temp_paths.extend(cleanup)
        return upload_path, cleanup

    monkeypatch.setattr(annotate_module, "prepare_upload_path", record)

    result = annotate_module.annotate(
        slide, results_dir=tmp_path / "out", progress=False
    )

    assert result["status"] == "completed"
    _method, _url, kwargs = fake_requests.calls[0]
    assert kwargs["files"]["file"][0].endswith(".zip")
    assert temp_paths and not any(path.exists() for path in temp_paths)
