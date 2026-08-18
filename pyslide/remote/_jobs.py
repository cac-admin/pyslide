# -*- coding: utf-8 -*-
""" Local registry mapping a slide file to the job created for it.

The registry makes ``annotate`` idempotent: a second run on the same slide checks
the existing job rather than uploading the file again.
"""

from __future__ import annotations

from pathlib import Path

from . import _config


__all__ = [
    "jobs_path",
    "image_key",
    "load_jobs",
    "get_job_id",
    "set_job_id",
    "clear_job_id",
]


def jobs_path():
    """ Path of the job registry file."""
    return _config.home_dir() / "jobs.json"


def image_key(path):
    """ Identity for a local slide: absolute path, size, and mtime.

    Editing or replacing a slide changes the key, so a modified file is
    treated as new work instead of reusing a stale job.
    """
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"no such file: {resolved}")
    info = resolved.stat()
    mtime = getattr(
        info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000)
    )
    return f"{resolved}|{info.st_size}|{mtime}"


def load_jobs():
    """ Return the registry as ``{profile: {image_key: job_id}}``."""
    data = _config._read_json(jobs_path())
    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        return {}
    return {
        str(name): dict(entries)
        for name, entries in profiles.items()
        if isinstance(entries, dict)
    }


def _save_jobs(profiles):
    """ Persist the whole registry."""
    return _config._write_json(
        jobs_path(), {"version": 1, "profiles": profiles}
    )


def get_job_id(key, *, profile=None):
    """ Return the job id recorded for ``key``, or ``None``."""
    name = _config.resolve_profile_name(profile)
    value = load_jobs().get(name, {}).get(key)
    return value if value not in ("", None) else None


def set_job_id(key, job_id, *, profile=None):
    """ Record ``job_id`` for ``key`` and return it."""
    if not key:
        raise ValueError("key must be a non-empty string")
    if job_id in ("", None):
        raise ValueError("job_id is required")

    name = _config.resolve_profile_name(profile)
    profiles = load_jobs()
    entries = profiles.setdefault(name, {})
    entries[str(key)] = job_id
    _save_jobs(profiles)
    return job_id


def clear_job_id(key, *, profile=None):
    """ Forget the job recorded for ``key``; True when one was removed."""
    name = _config.resolve_profile_name(profile)
    profiles = load_jobs()
    entries = profiles.get(name) or {}
    if str(key) not in entries:
        return False
    del entries[str(key)]
    profiles[name] = entries
    _save_jobs(profiles)
    return True
