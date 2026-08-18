# -*- coding: utf-8 -*-
""" Per-profile token storage and interactive login."""

from __future__ import annotations

import getpass
import os
from pathlib import Path

from . import _config
from ._errors import RemoteAuthError


__all__ = [
    "credentials_path",
    "load_token",
    "save_token",
    "clear_token",
    "ensure_token",
]


def credentials_path():
    """ Path of the token store."""
    return _config.home_dir() / "credentials.json"


def _all_credentials():
    """ Return the credentials document, keyed by profile name."""
    data = _config._read_json(credentials_path())
    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        return {}
    return {
        str(name): dict(entry)
        for name, entry in profiles.items()
        if isinstance(entry, dict)
    }


def load_token(profile=None):
    """ Return the token for ``profile``, or ``None``.

    ``PYSLIDE_REMOTE_TOKEN`` wins over anything on disk, which keeps CI and
    container runs from needing a login step.
    """
    env = os.environ.get("PYSLIDE_REMOTE_TOKEN")
    if env:
        return env.strip()

    name = _config.resolve_profile_name(profile)
    token = _all_credentials().get(name, {}).get("token")
    return token if isinstance(token, str) and token else None


def save_token(token, *, profile=None, username=None):
    """ Store ``token`` for ``profile`` with owner-only permissions.

    Returns
    -------
    pathlib.Path
        Path of the credentials file.
    """
    if not token or not isinstance(token, str):
        raise ValueError("token must be a non-empty string")

    name = _config.resolve_profile_name(profile)
    profiles = _all_credentials()
    entry = profiles.get(name, {})
    entry["token"] = token
    if username:
        entry["username"] = username
    profiles[name] = entry

    return _config._write_json(
        credentials_path(), {"version": 1, "profiles": profiles}, mode=0o600
    )


def clear_token(profile=None):
    """ Forget the token for ``profile``; return True when one was removed."""
    name = _config.resolve_profile_name(profile)
    profiles = _all_credentials()
    if name not in profiles:
        return False
    profiles.pop(name)
    if profiles:
        _config._write_json(
            credentials_path(), {"version": 1, "profiles": profiles}, mode=0o600
        )
    else:
        try:
            Path(credentials_path()).unlink()
        except FileNotFoundError:
            pass
    return True


def _prompt(text, *, secret=False):
    """ Read one interactive answer from the terminal."""
    if secret:
        return getpass.getpass(text)
    return input(text)


def _login_inputs(username=None, password=None):
    """ Resolve credentials from arguments, then env, then prompts."""
    user = username or os.environ.get("PYSLIDE_REMOTE_USER")
    pwd = password or os.environ.get("PYSLIDE_REMOTE_PASSWORD")

    if not user:
        user = _prompt("Username: ").strip()
    if not pwd:
        pwd = _prompt("Password: ", secret=True)
    if not user or not pwd:
        raise RemoteAuthError("username and password are required")
    return user, pwd


def ensure_token(
    client,
    *,
    profile=None,
    force_login=False,
    username=None,
    password=None,
):
    """ Return a usable token, logging in when necessary.

    Parameters
    ----------
    client : RemoteClient
        Client used to perform the login request.
    profile : str, optional
        Profile the token belongs to; defaults to the active profile.
    force_login : bool
        Ignore any saved token and authenticate again, e.g. after an HTTP 401.
    username, password : str, optional
        Non-interactive credentials. Otherwise ``PYSLIDE_REMOTE_USER`` and
        ``PYSLIDE_REMOTE_PASSWORD`` are used, then interactive prompts.

    Returns
    -------
    str
        Bearer token.
    """
    name = _config.resolve_profile_name(profile)

    if not force_login:
        token = load_token(name)
        if token:
            return token

    user, pwd = _login_inputs(username, password)
    payload = client.login(user, pwd)
    token = payload["token"]
    save_token(token, profile=name, username=payload.get("username") or user)
    return token
