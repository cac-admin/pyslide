# -*- coding: utf-8 -*-
""" Named server profiles stored under ``~/.pyslide-remote/``."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ._errors import RemoteConfigError


__all__ = [
    "PROTOCOL_ID",
    "DEFAULT_PROFILE",
    "DEFAULT_TIMEOUT",
    "DEFAULT_UPLOAD_TIMEOUT",
    "home_dir",
    "config_path",
    "load_config",
    "save_config",
    "list_profiles",
    "current_profile_name",
    "get_profile",
    "save_profile",
    "delete_profile",
    "use_profile",
    "normalize_base_url",
    "read_connect_file",
    "resolve_profile_name",
    "resolve_base_url",
    "resolve_verify",
    "resolve_timeout",
]

#: Protocol identifier this client speaks, as reported by ``/v1/capabilities``.
PROTOCOL_ID = "pyslide-remote/1"

DEFAULT_PROFILE = "default"
DEFAULT_TIMEOUT = 60.0
# POST /jobs can take a long time after a large body has been sent.
DEFAULT_UPLOAD_TIMEOUT = 7200.0

_TRUTHY_OFF = ("0", "false", "no", "off")


def home_dir():
    """ Directory holding config, credentials, and the job registry."""
    override = os.environ.get("PYSLIDE_REMOTE_HOME")
    if override:
        return Path(override)
    return Path.home() / ".pyslide-remote"


def config_path():
    """ Path of the profiles config file."""
    return home_dir() / "config.json"


def _read_json(path):
    """ Load a JSON object from ``path``, or ``{}`` when unusable."""
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path, data, *, mode=None):
    """ Write ``data`` to ``path`` atomically, optionally with a file mode."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    if mode is not None:
        try:
            os.chmod(tmp, mode)
        except OSError:
            # Non-POSIX filesystems may ignore mode bits.
            pass
    os.replace(tmp, path)
    return path


def load_config():
    """ Return the whole config document with its expected keys present."""
    data = _read_json(config_path())
    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}
    return {
        "version": data.get("version", 1),
        "current_profile": data.get("current_profile") or DEFAULT_PROFILE,
        "profiles": {
            str(name): dict(cfg)
            for name, cfg in profiles.items()
            if isinstance(cfg, dict)
        },
    }


def save_config(data):
    """ Persist the whole config document."""
    if not isinstance(data, dict):
        raise TypeError("config must be a dict")
    return _write_json(config_path(), data)


def list_profiles():
    """ Return ``{name: settings}`` for every saved profile."""
    return load_config()["profiles"]


def current_profile_name():
    """ Name of the active profile: env override, else the saved default."""
    env = os.environ.get("PYSLIDE_REMOTE_PROFILE")
    if env:
        return env
    return load_config()["current_profile"]


def get_profile(name=None):
    """ Return settings for ``name``, or the active profile when omitted.

    Returns
    -------
    dict
        Saved settings, or ``{}`` when the profile does not exist.
    """
    cfg = load_config()
    key = name or current_profile_name()
    profile = cfg["profiles"].get(key)
    return dict(profile) if isinstance(profile, dict) else {}


def save_profile(name, settings, *, make_current=True):
    """ Create or update profile ``name``.

    Parameters
    ----------
    name : str
        Profile name, e.g. ``default``.
    settings : dict
        Keys to merge in, e.g. ``base_url``, ``verify``, ``timeout``.
    make_current : bool
        Also mark this profile as the active one.

    Returns
    -------
    dict
        The stored settings for ``name``.
    """
    if not name:
        raise RemoteConfigError("profile name must not be empty")
    if not isinstance(settings, dict):
        raise TypeError("settings must be a dict")

    cfg = load_config()
    merged = dict(cfg["profiles"].get(name) or {})
    merged.update(
        {k: v for k, v in settings.items() if v is not None}
    )
    if merged.get("base_url"):
        merged["base_url"] = normalize_base_url(merged["base_url"])
    cfg["profiles"][name] = merged
    if make_current:
        cfg["current_profile"] = name
    save_config(cfg)
    return merged


def delete_profile(name):
    """ Remove profile ``name``; return True when something was removed."""
    cfg = load_config()
    if name not in cfg["profiles"]:
        return False
    del cfg["profiles"][name]
    if cfg["current_profile"] == name:
        remaining = sorted(cfg["profiles"])
        cfg["current_profile"] = remaining[0] if remaining else DEFAULT_PROFILE
    save_config(cfg)
    return True


def use_profile(name):
    """ Mark profile ``name`` active; it must already exist."""
    cfg = load_config()
    if name not in cfg["profiles"]:
        known = ", ".join(sorted(cfg["profiles"])) or "none"
        raise RemoteConfigError(
            f"unknown profile {name!r} (saved profiles: {known})"
        )
    cfg["current_profile"] = name
    save_config(cfg)
    return name


def normalize_base_url(base_url):
    """ Strip trailing slashes and a redundant ``/v1`` suffix.

    The client appends ``/v1/...`` itself, so both ``https://host/api/remote``
    and ``https://host/api/remote/v1`` are accepted from users and config
    downloads.
    """
    url = str(base_url).strip().rstrip("/")
    if url.endswith("/v1"):
        url = url[: -len("/v1")]
    return url


def read_connect_file(path):
    """ Read a server-provided config file into profile settings.

    The file is JSON with at least ``base_url``. Recognized optional keys are
    ``name``, ``protocol``, ``token``, ``verify``, and ``timeout``. Unknown
    keys are ignored so servers can add hints without breaking older clients.

    Parameters
    ----------
    path : str or path-like
        Config file downloaded from a compatible server.

    Returns
    -------
    dict
        Keys ``name``, ``settings`` (for :func:`save_profile`), and ``token``
        (``None`` when the file does not carry one).

    Raises
    ------
    RemoteConfigError
        File is missing, is not JSON, or has no ``base_url``.
    """
    path = Path(path)
    if not path.is_file():
        raise RemoteConfigError(f"no such config file: {path}")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise RemoteConfigError(f"cannot read config file {path}: {exc}")
    if not isinstance(data, dict):
        raise RemoteConfigError(f"config file {path} must contain a JSON object")

    base_url = data.get("base_url")
    if not base_url:
        raise RemoteConfigError(f"config file {path} has no 'base_url'")

    settings = {"base_url": normalize_base_url(base_url)}
    if "verify" in data:
        settings["verify"] = bool(data["verify"])
    if data.get("timeout") is not None:
        try:
            settings["timeout"] = float(data["timeout"])
        except (TypeError, ValueError):
            pass
    if data.get("protocol"):
        settings["protocol"] = str(data["protocol"])

    name = str(data.get("name") or "").strip() or DEFAULT_PROFILE
    token = data.get("token") or None
    return {"name": name, "settings": settings, "token": token}


def resolve_profile_name(profile=None):
    """ Resolve which profile name to use."""
    return profile or current_profile_name()


def resolve_base_url(base_url=None, *, profile=None):
    """ Resolve the server base URL: argument, then env, then profile.

    Raises
    ------
    RemoteConfigError
        No base URL is configured anywhere.
    """
    if base_url:
        return normalize_base_url(base_url)

    env = os.environ.get("PYSLIDE_REMOTE_URL")
    if env:
        return normalize_base_url(env)

    saved = get_profile(profile).get("base_url")
    if saved:
        return normalize_base_url(saved)

    raise RemoteConfigError(
        "no server configured; run 'pyslide-remote init', or set "
        "PYSLIDE_REMOTE_URL"
    )


def resolve_verify(verify=None, *, profile=None):
    """ Resolve TLS verification: argument, then env, then profile, else True.

    A string value is treated as a CA bundle path.
    """
    if verify is not None:
        return verify

    env = os.environ.get("PYSLIDE_REMOTE_VERIFY")
    if env is not None:
        env = env.strip()
        if env.lower() in _TRUTHY_OFF:
            return False
        if env.lower() in ("1", "true", "yes", "on"):
            return True
        return env

    saved = get_profile(profile).get("verify")
    if saved is not None:
        return saved if isinstance(saved, str) else bool(saved)

    return True


def resolve_timeout(timeout=None, *, profile=None):
    """ Resolve the request timeout in seconds."""
    if timeout is not None:
        return timeout

    env = os.environ.get("PYSLIDE_REMOTE_TIMEOUT")
    if env:
        try:
            return float(env)
        except ValueError:
            pass

    saved = get_profile(profile).get("timeout")
    if saved is not None:
        try:
            return float(saved)
        except (TypeError, ValueError):
            pass

    return DEFAULT_TIMEOUT
