# -*- coding: utf-8 -*-
""" Connection diagnostics for a configured remote annotation server.

``doctor`` checks configuration, TLS, reachability, protocol version, and the
stored token as separate results, so that a failure identifies which layer is at
fault.
"""

from __future__ import annotations

from urllib.parse import urlparse

from . import _auth, _config
from ._client import RemoteClient
from ._errors import (
    RemoteAPIError,
    RemoteAuthError,
    RemoteConfigError,
    RemoteError,
    RemoteJobNotFound,
    RemoteProtocolError,
)


__all__ = ["Check", "run_checks", "format_report"]


class Check:
    """ One diagnostic result.

    Attributes
    ----------
    name : str
        Short label, e.g. ``config``.
    ok : bool or None
        True when it passed, False when it failed, None when it was skipped
        or could not be determined.
    detail : str
        Human-readable explanation.
    """

    def __init__(self, name, ok, detail=""):
        self.name = name
        self.ok = ok
        self.detail = detail

    def __repr__(self):
        return f"Check(name={self.name!r}, ok={self.ok!r}, detail={self.detail!r})"

    def as_dict(self):
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


def _check_config(profile):
    """ Confirm a base URL is configured and looks like a usable URL."""
    try:
        base_url = _config.resolve_base_url(profile=profile)
    except RemoteConfigError as exc:
        return Check("config", False, str(exc)), None

    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return (
            Check(
                "config",
                False,
                f"{base_url} is not an http(s) URL; expected something like "
                f"https://example.org/api/remote",
            ),
            None,
        )
    return Check("config", True, f"profile {profile!r} -> {base_url}"), base_url


def _check_tls(base_url, verify):
    """ Report the transport security the client will use for this profile."""
    if urlparse(base_url).scheme != "https":
        return Check(
            "tls",
            None,
            "server is plain http; credentials and slides travel unencrypted",
        )
    if verify is False:
        return Check(
            "tls",
            None,
            "certificate verification is disabled for this profile",
        )
    if isinstance(verify, str):
        return Check("tls", True, f"verifying against CA bundle {verify}")
    return Check("tls", True, "verifying the server certificate")


def _check_reachable(client):
    """ Call the unauthenticated capabilities route."""
    try:
        payload = client.capabilities()
    except RemoteAPIError as exc:
        return (
            Check(
                "reachable",
                False,
                f"cannot read {client.base_url}/v1/capabilities: {exc}",
            ),
            None,
        )
    except Exception as exc:
        return (
            Check("reachable", False, f"cannot reach {client.base_url}: {exc}"),
            None,
        )
    return Check("reachable", True, "capabilities endpoint answered"), payload


def _check_protocol(client, capabilities):
    """ Compare the server's protocol id against this client's."""
    try:
        protocol = client.check_protocol(capabilities)
    except RemoteProtocolError as exc:
        return Check("protocol", False, str(exc))
    return Check("protocol", True, f"server speaks {protocol}")


def _check_auth(client, profile):
    """ Verify the stored token, when the server can confirm identities."""
    token = _auth.load_token(profile)
    if not token:
        return Check(
            "auth", False, "no token stored; run 'pyslide-remote login'"
        )

    client.token = token
    try:
        payload = client.whoami()
    except RemoteAuthError as exc:
        return Check(
            "auth",
            False,
            f"the server rejected the stored token ({exc}); run "
            f"'pyslide-remote login' again",
        )
    except RemoteJobNotFound:
        return Check(
            "auth",
            None,
            "token is stored, but this server does not expose "
            "/v1/auth/whoami so it could not be verified",
        )
    except RemoteError as exc:
        return Check("auth", None, f"could not verify the token: {exc}")

    who = payload.get("username") or payload.get("user") or "authenticated"
    return Check("auth", True, f"token accepted as {who}")


def _describe_limits(capabilities):
    """ Summarize the upload limits a server advertises."""
    if not isinstance(capabilities, dict):
        return Check("limits", None, "server reported no limits")

    size = capabilities.get("max_upload_bytes")
    details = []
    if isinstance(size, (int, float)) and size > 0:
        details.append(f"max upload {float(size) / (1024 ** 3):.1f} GiB")
    methods = capabilities.get("auth_methods")
    if isinstance(methods, list) and methods:
        details.append("auth: " + ", ".join(str(m) for m in methods))
    if not details:
        return Check("limits", None, "server advertised no upload limits")
    return Check("limits", True, "; ".join(details))


def run_checks(profile=None, *, base_url=None, verify=None, timeout=None):
    """ Run every diagnostic against a profile.

    Returns
    -------
    list of Check
        Results in the order they were run. Later checks are skipped when an
        earlier one makes them meaningless.
    """
    name = _config.resolve_profile_name(profile)
    checks = []

    config_check, resolved = _check_config(name)
    checks.append(config_check)
    if base_url:
        resolved = _config.normalize_base_url(base_url)
        checks[-1] = Check("config", True, f"using {resolved} from the command line")
    if not resolved:
        return checks

    resolved_verify = _config.resolve_verify(verify, profile=name)
    checks.append(_check_tls(resolved, resolved_verify))

    client = RemoteClient(
        resolved,
        timeout=timeout,
        verify=resolved_verify,
        profile=name,
    )

    reachable, capabilities = _check_reachable(client)
    checks.append(reachable)
    if not reachable.ok:
        return checks

    checks.append(_check_protocol(client, capabilities))
    checks.append(_describe_limits(capabilities))
    checks.append(_check_auth(client, name))
    return checks


def format_report(checks):
    """ Render checks as aligned terminal lines."""
    symbols = {True: "ok  ", False: "FAIL", None: "note"}
    width = max((len(check.name) for check in checks), default=0)
    lines = []
    for check in checks:
        lines.append(
            f"[{symbols[check.ok]}] {check.name.ljust(width)}  {check.detail}"
        )
    return "\n".join(lines)
