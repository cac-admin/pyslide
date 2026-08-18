# -*- coding: utf-8 -*-
""" Submit a slide for remote annotation, wait for it, download the results."""

from __future__ import annotations

import re
import time
from pathlib import Path

from . import _auth, _config, _jobs
from ._client import TERMINAL_STATUSES, RemoteClient
from ._errors import RemoteAuthError, RemoteJobNotFound
from ._progress import PollReporter, resolve_progress
from ._vsi import prepare_upload_path


__all__ = ["annotate", "status"]

_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(name, fallback="artifact"):
    """ Reduce a server-chosen artifact name to a safe local filename.

    Artifact names are untrusted input: only the final path segment is kept, and
    characters outside ``[A-Za-z0-9._-]`` are replaced, so a name cannot escape
    the results directory.
    """
    cleaned = _UNSAFE_NAME.sub("_", str(name).strip().replace("\\", "/").split("/")[-1])
    cleaned = cleaned.strip("._") or fallback
    return cleaned[:120]


def _results_dir(job_id, results_dir=None):
    """ Resolve where artifacts for ``job_id`` should be written."""
    base = Path(results_dir) if results_dir is not None else Path.cwd() / "pyslide_remote_results"
    return base / str(job_id)


def _with_reauth(client, token, call, *, profile=None):
    """ Run ``call(token)``, logging in once more if the token was rejected."""
    try:
        return call(token), token
    except RemoteAuthError:
        _auth.clear_token(profile)
        token = _auth.ensure_token(client, profile=profile, force_login=True)
        client.token = token
        return call(token), token


def _sleep_with_countdown(reporter, status_name, interval, *, payload=None):
    """ Wait ``interval`` seconds, refreshing the countdown once a second."""
    remaining = float(interval)
    while remaining > 0:
        reporter.update(status_name, next_in=remaining, payload=payload)
        step = min(1.0, remaining)
        time.sleep(step)
        remaining -= step


def _download_artifacts(client, job_id, token, dest_dir, *, timeout=None):
    """ Download every artifact of a job, returning the local paths."""
    artifacts = client.artifacts(job_id, token=token)
    if not artifacts:
        return []

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    written = []
    used = set()
    for index, artifact in enumerate(artifacts):
        name = _safe_name(artifact["name"], fallback=f"artifact_{index}")
        # Two artifacts may reduce to the same safe name; keep both.
        candidate = name
        suffix = 1
        while candidate in used:
            candidate = f"{suffix}_{name}"
            suffix += 1
        used.add(candidate)

        path = client.download_artifact(
            artifact, dest_dir / candidate, token=token, timeout=timeout
        )
        written.append(str(Path(path).resolve()))
    return written


def annotate(
    image_path,
    *,
    profile=None,
    base_url=None,
    wait=True,
    poll_interval=5.0,
    timeout=None,
    results_dir=None,
    verify=None,
    submit=True,
    progress=None,
):
    """ Annotate a slide on a compatible remote server.

    The slide is uploaded once; its job id is remembered locally, so calling
    this again with the same file resumes that job instead of re-uploading.

    Parameters
    ----------
    image_path : str or path-like
        Local slide to annotate. A ``.vsi`` file is zipped with its companion
        folder before upload.
    profile : str, optional
        Server profile to use; defaults to the active profile.
    base_url : str, optional
        Override the profile's server URL.
    wait : bool
        Poll until the job finishes. When False, return the current state.
    poll_interval : float
        Seconds between status checks while waiting.
    timeout : float or tuple, optional
        Per-request timeout for uploads, polls, and downloads.
    results_dir : str or path-like, optional
        Parent directory for downloads. Defaults to
        ``./pyslide_remote_results/<job_id>/``.
    verify : bool or str, optional
        TLS verification flag or CA bundle path.
    submit : bool
        When False, never upload; only report on an already-known job.
    progress : bool, optional
        Show progress on stderr. Defaults to on when stderr is a terminal.

    Returns
    -------
    dict
        Keys ``job_id``, ``status``, ``submitted``, ``paths``, ``results_dir``,
        ``payload`` (the raw job document), and ``message``.

    Raises
    ------
    FileNotFoundError
        ``image_path`` does not exist.
    VsiPackageError
        A ``.vsi`` slide has no usable companion folder.
    RemoteConfigError
        No server is configured for the profile.
    """
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"no such file: {path.resolve()}")

    name = _config.resolve_profile_name(profile)
    show_progress = resolve_progress(progress)
    client = RemoteClient(
        base_url,
        timeout=timeout,
        verify=verify,
        profile=name,
        progress=show_progress,
    )
    token = _auth.ensure_token(client, profile=name)
    client.token = token

    # Job identity follows the original slide, never the temporary zip.
    key = _jobs.image_key(path)
    job_id = _jobs.get_job_id(key, profile=name)
    submitted = False
    cleanup = []

    def upload():
        """ Package, upload, and record a new job; return its id."""
        nonlocal cleanup, token
        upload_path, cleanup = prepare_upload_path(path)
        created, token = _with_reauth(
            client,
            token,
            lambda tok: client.submit_job(upload_path, token=tok, timeout=timeout),
            profile=name,
        )
        new_id = created["id"]
        _jobs.set_job_id(key, new_id, profile=name)
        return new_id

    try:
        if job_id is None:
            if not submit:
                return {
                    "job_id": None,
                    "status": None,
                    "submitted": False,
                    "paths": [],
                    "results_dir": None,
                    "payload": None,
                    "message": "no job for this slide yet; run annotate first",
                }
            job_id = upload()
            submitted = True

        def fetch(tok):
            return client.get_job(job_id, token=tok)

        try:
            payload, token = _with_reauth(client, token, fetch, profile=name)
        except RemoteJobNotFound:
            # The server no longer knows this job, so the local mapping is
            # stale. Discard it and submit again.
            _jobs.clear_job_id(key, profile=name)
            if not submit:
                return {
                    "job_id": None,
                    "status": None,
                    "submitted": False,
                    "paths": [],
                    "results_dir": None,
                    "payload": None,
                    "message": (
                        f"job {job_id} is unknown to the server; the local "
                        f"record was cleared, run annotate to submit again"
                    ),
                }
            job_id = upload()
            submitted = True
            payload, token = _with_reauth(client, token, fetch, profile=name)

        job_status = payload.get("status") if isinstance(payload, dict) else None

        if wait and job_status not in TERMINAL_STATUSES:
            interval = max(float(poll_interval), 0.1)
            reporter = PollReporter(enabled=show_progress)
            try:
                while True:
                    _sleep_with_countdown(
                        reporter, job_status, interval, payload=payload
                    )
                    payload, token = _with_reauth(
                        client, token, fetch, profile=name
                    )
                    job_status = (
                        payload.get("status")
                        if isinstance(payload, dict)
                        else None
                    )
                    reporter.update(job_status, payload=payload)
                    if job_status in TERMINAL_STATUSES:
                        break
            finally:
                reporter.close(final_status=job_status)

        paths = []
        out_dir = None
        if job_status == "completed":
            out_dir = _results_dir(job_id, results_dir)
            paths, token = _with_reauth(
                client,
                token,
                lambda tok: _download_artifacts(
                    client, job_id, tok, out_dir, timeout=timeout
                ),
                profile=name,
            )
        elif results_dir is not None:
            out_dir = _results_dir(job_id, results_dir)

        message = None
        if isinstance(payload, dict) and payload.get("message"):
            message = str(payload["message"])

        return {
            "job_id": job_id,
            "status": job_status,
            "submitted": submitted,
            "paths": paths,
            "results_dir": str(out_dir) if out_dir is not None else None,
            "payload": payload,
            "message": message,
        }
    finally:
        for temp in cleanup:
            try:
                Path(temp).unlink()
            except OSError:
                pass


def status(image_path, **kwargs):
    """ Report on the job for ``image_path`` without uploading anything.

    Accepts the same keyword arguments as :func:`annotate`.
    """
    kwargs.setdefault("wait", False)
    kwargs["submit"] = False
    return annotate(image_path, **kwargs)
