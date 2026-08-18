# -*- coding: utf-8 -*-
""" HTTP client for the pyslide remote annotation protocol, version 1.

The protocol is documented in ``docs/remote_protocol.rst``. Any server
implementing these routes can be used as an annotation backend::

    GET  {base}/v1/capabilities
    POST {base}/v1/auth/login
    GET  {base}/v1/auth/whoami
    POST {base}/v1/jobs
    GET  {base}/v1/jobs/{id}
    GET  {base}/v1/jobs/{id}/artifacts
"""

from __future__ import annotations

import os
import time
from urllib.parse import urljoin, urlparse

from . import _config
from ._errors import (
    RemoteAPIError,
    RemoteAuthError,
    RemoteJobNotFound,
    RemoteProtocolError,
)
from ._progress import ProgressFile, download_bar, upload_bar


__all__ = ["RemoteClient", "JOB_STATUSES", "TERMINAL_STATUSES"]

#: Every job status a v1 server is allowed to report.
JOB_STATUSES = frozenset({"pending", "processing", "completed", "failed"})

#: Statuses that mean the server is done with a job.
TERMINAL_STATUSES = frozenset({"completed", "failed"})

# HTTP statuses retried by the client: 502, 503, 504.
_RETRY_STATUS = frozenset({502, 503, 504})
_DEFAULT_RETRIES = 3
_CHUNK = 1024 * 1024


def _requests():
    """ Import ``requests`` with an actionable message when it is missing."""
    try:
        import requests
    except ImportError:
        raise RemoteAPIError(
            "the remote annotation client needs the 'requests' package; "
            "install it with: pip install \"pyslide[remote]\""
        )
    return requests


def _is_transient(exc):
    """ Return True for network errors that usually clear on retry."""
    try:
        import requests
    except ImportError:
        return False
    return isinstance(
        exc,
        (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ),
    )


def _with_retries(fn, *, stage, retries=_DEFAULT_RETRIES, progress=False):
    """ Call ``fn()``, retrying transient failures with exponential backoff.

    Parameters
    ----------
    fn : callable
        Zero-argument callable performing one attempt.
    stage : str
        Label used in the final error message, e.g. ``upload``.
    retries : int
        Total number of attempts, including the first.
    progress : bool
        Write retry notices to stderr.
    """
    import sys

    attempts = max(int(retries), 1)
    started = time.monotonic()
    last = None

    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except RemoteAuthError:
            # Callers re-authenticate; retrying the same token cannot help.
            raise
        except RemoteAPIError as exc:
            if exc.status_code not in _RETRY_STATUS:
                raise
            last = exc
        except Exception as exc:
            if not _is_transient(exc):
                raise
            last = exc

        if attempt >= attempts:
            break

        delay = min(2 ** (attempt - 1), 8)
        if progress:
            sys.stderr.write(
                f"\n{stage} failed (attempt {attempt}/{attempts}): {last}; "
                f"retrying in {delay}s\n"
            )
            sys.stderr.flush()
        time.sleep(delay)

    elapsed = int(time.monotonic() - started)
    raise RemoteAPIError(
        f"{stage} failed after {attempts} attempt(s), {elapsed}s elapsed: {last}",
        status_code=getattr(last, "status_code", None),
        error=getattr(last, "error", None),
    )


def _silence_insecure_warnings():
    """ Hide urllib3 warnings when the user opted out of TLS verification."""
    import warnings

    warnings.filterwarnings("ignore", message="Unverified HTTPS request.*")
    try:
        import urllib3
        from urllib3.exceptions import InsecureRequestWarning
    except ImportError:
        return
    urllib3.disable_warnings(InsecureRequestWarning)
    warnings.filterwarnings("ignore", category=InsecureRequestWarning)


class RemoteClient:
    """ Thin wrapper over the remote annotation HTTP protocol.

    Parameters
    ----------
    base_url : str, optional
        Server root, without the ``/v1`` suffix. Falls back to
        ``PYSLIDE_REMOTE_URL`` and then the active profile.
    token : str, optional
        Bearer token for authenticated routes.
    timeout : float or tuple, optional
        Request timeout passed to ``requests``.
    verify : bool or str, optional
        TLS verification flag or CA bundle path.
    profile : str, optional
        Profile to read defaults from; defaults to the active profile.
    progress : bool
        Show transfer progress on stderr.
    """

    def __init__(
        self,
        base_url=None,
        *,
        token=None,
        timeout=None,
        verify=None,
        profile=None,
        progress=False,
    ):
        self.profile = _config.resolve_profile_name(profile)
        self.base_url = _config.resolve_base_url(base_url, profile=self.profile)
        self.timeout = _config.resolve_timeout(timeout, profile=self.profile)
        self.verify = _config.resolve_verify(verify, profile=self.profile)
        self.token = token
        self.progress = bool(progress)
        if self.verify is False:
            _silence_insecure_warnings()

    def _url(self, path):
        """ Build an absolute URL for a versioned protocol path."""
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}/v1{path}"

    def _headers(self, token=None, *, required=True):
        """ Authorization headers for an authenticated request."""
        value = token or self.token
        if not value:
            if required:
                raise RemoteAuthError(
                    "no token available; run 'pyslide-remote login'",
                    status_code=401,
                )
            return {}
        return {"Authorization": f"Bearer {value}"}

    @staticmethod
    def _body(response):
        """ Return the parsed JSON object of a response, or ``{}``."""
        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def _raise(self, response, action):
        """ Translate an error response into the matching exception."""
        body = self._body(response)
        error = body.get("error")
        message = (
            body.get("message")
                # Some frameworks report the error text under "detail".
            or body.get("detail")
            or body.get("error")
            or (response.text or "").strip()
            or f"{action} failed with HTTP {response.status_code}"
        )
        status = response.status_code

        if status in (401, 403):
            raise RemoteAuthError(message, status_code=status, error=error)
        if status == 404:
            raise RemoteJobNotFound(message, status_code=status, error=error)
        raise RemoteAPIError(message, status_code=status, error=error)

    def _get_json(
        self,
        path,
        *,
        token=None,
        auth=True,
        stage="request",
        retries=_DEFAULT_RETRIES,
    ):
        """ GET ``path`` and return the decoded JSON object."""
        requests = _requests()

        def attempt():
            response = requests.get(
                self._url(path),
                headers=self._headers(token, required=auth) if auth else {},
                timeout=self.timeout,
                verify=self.verify,
            )
            if response.status_code != 200:
                self._raise(response, stage)
            return self._body(response)

        return _with_retries(
            attempt, stage=stage, retries=retries, progress=self.progress
        )

    def capabilities(self):
        """ Describe the server: protocol id, auth methods, upload limits.

        Returns
        -------
        dict
            Server payload. ``protocol`` identifies the dialect, and is
            expected to be ``pyslide-remote/1``.
        """
        # A probe for the setup wizard and doctor: report a dead host promptly
        # rather than working through the full retry schedule.
        return self._get_json(
            "/capabilities", auth=False, stage="capabilities", retries=1
        )

    def check_protocol(self, capabilities=None):
        """ Verify the server speaks this client's protocol version.

        Returns
        -------
        str
            The server's protocol identifier.

        Raises
        ------
        RemoteProtocolError
            Server reports a protocol this client cannot speak.
        """
        payload = capabilities if capabilities is not None else self.capabilities()
        protocol = str(payload.get("protocol") or "").strip()
        if not protocol:
            raise RemoteProtocolError(
                f"{self.base_url} did not report a 'protocol' field; it does "
                f"not look like a pyslide remote server"
            )
        if protocol != _config.PROTOCOL_ID:
            raise RemoteProtocolError(
                f"server speaks {protocol!r}, this client speaks "
                f"{_config.PROTOCOL_ID!r}"
            )
        return protocol

    def login(self, username, password):
        """ Exchange a username and password for a bearer token.

        Returns
        -------
        dict
            Payload containing at least ``token``.
        """
        requests = _requests()

        def attempt():
            response = requests.post(
                self._url("/auth/login"),
                json={"username": username, "password": password},
                timeout=self.timeout,
                verify=self.verify,
            )
            if response.status_code != 200:
                self._raise(response, "login")
            body = self._body(response)
            if not body.get("token"):
                raise RemoteProtocolError(
                    "login succeeded but the server returned no 'token'"
                )
            return body

        return _with_retries(attempt, stage="login", progress=self.progress)

    def whoami(self, token=None):
        """ Return the identity behind a token.

        Returns
        -------
        dict
            Payload describing the account, typically ``{"username": ...}``.

        Raises
        ------
        RemoteJobNotFound
            Server does not implement this optional route.
        """
        return self._get_json("/auth/whoami", token=token, stage="whoami")

    def submit_job(self, path, *, token=None, timeout=None, progress=None):
        """ Upload a slide and create an annotation job.

        Parameters
        ----------
        path : str or path-like
            Local file to upload as the multipart ``file`` field.
        token : str, optional
            Bearer token; defaults to the client token.
        timeout : float or tuple, optional
            Upload timeout passed to ``requests``. When omitted, connect uses
            the client timeout and read uses at least
            :data:`pyslide.remote._config.DEFAULT_UPLOAD_TIMEOUT`.
        progress : bool, optional
            Show an upload bar; defaults to the client setting.

        Returns
        -------
        dict
            Payload containing at least ``id``.
        """
        requests = _requests()

        path = os.fspath(path)
        filename = os.path.basename(path)
        show = self.progress if progress is None else bool(progress)
        if timeout is not None:
            upload_timeout = timeout
        else:
            # Connect uses the general timeout. The read timeout is longer so
            # the client waits for the server after a large upload instead of
            # retrying POST /jobs.
            upload_timeout = (
                self.timeout,
                max(float(self.timeout), _config.DEFAULT_UPLOAD_TIMEOUT),
            )

        def attempt():
            total = os.path.getsize(path)
            bar = upload_bar(filename, total, enabled=show)
            handle = open(path, "rb")
            try:
                response = requests.post(
                    self._url("/jobs"),
                    headers=self._headers(token),
                    files={
                        "file": (
                            filename,
                            ProgressFile(handle, bar),
                            "application/octet-stream",
                        )
                    },
                    timeout=upload_timeout,
                    verify=self.verify,
                )
            finally:
                bar.close()
                handle.close()

            if response.status_code not in (200, 201):
                self._raise(response, "submit")
            body = self._body(response)
            if body.get("id") in (None, ""):
                raise RemoteProtocolError(
                    "server accepted the upload but returned no job 'id'"
                )
            return body

        # POST /jobs is not idempotent: a timeout often means the server already
        # created the job. Retrying uploads a second copy and can exhaust memory.
        return _with_retries(
            attempt,
            stage="upload",
            retries=1,
            progress=show,
        )

    def get_job(self, job_id, *, token=None):
        """ Fetch the state of a job.

        Returns
        -------
        dict
            Payload with ``status`` (one of :data:`JOB_STATUSES`) plus optional
            ``progress`` and ``message``.

        Raises
        ------
        RemoteProtocolError
            Server reported a status outside the protocol.
        """
        body = self._get_json(f"/jobs/{job_id}", token=token, stage="status")
        status = body.get("status")
        if status is not None and status not in JOB_STATUSES:
            raise RemoteProtocolError(
                f"server reported unknown job status {status!r}; expected one "
                f"of {', '.join(sorted(JOB_STATUSES))}"
            )
        return body

    def artifacts(self, job_id, *, token=None):
        """ List the result files a completed job produced.

        Returns
        -------
        list of dict
            Entries with ``name`` and ``url``. Names are opaque strings chosen
            by the server.
        """
        body = self._get_json(
            f"/jobs/{job_id}/artifacts", token=token, stage="artifacts"
        )
        items = body.get("artifacts")
        if items is None:
            raise RemoteProtocolError(
                "artifact listing has no 'artifacts' array"
            )
        if not isinstance(items, list):
            raise RemoteProtocolError("'artifacts' must be an array")

        out = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            url = item.get("url")
            if not name or not url:
                continue
            out.append({"name": str(name), "url": str(url)})
        return out

    def artifact_url(self, url):
        """ Resolve an artifact URL, which may be relative to the server."""
        if urlparse(str(url)).scheme:
            return str(url)
        return urljoin(self.base_url + "/", str(url).lstrip("/"))

    def download_artifact(
        self, artifact, dest_path, *, token=None, timeout=None, progress=None
    ):
        """ Stream one artifact to ``dest_path``.

        The file is written to a ``.part`` sibling first and renamed on
        success. An interrupted download therefore never looks complete.

        Parameters
        ----------
        artifact : dict or str
            Artifact entry from :meth:`artifacts`, or a bare URL.
        dest_path : str or path-like
            Destination file; parent directories are created.

        Returns
        -------
        str
            The path written.
        """
        requests = _requests()

        url = artifact["url"] if isinstance(artifact, dict) else artifact
        url = self.artifact_url(url)
        dest_path = os.fspath(dest_path)
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)

        show = self.progress if progress is None else bool(progress)
        filename = os.path.basename(dest_path)
        download_timeout = timeout if timeout is not None else self.timeout

        def attempt():
            with requests.get(
                url,
                headers=self._headers(token),
                timeout=download_timeout,
                verify=self.verify,
                stream=True,
            ) as response:
                if response.status_code != 200:
                    self._raise(response, "download")

                try:
                    total = int(response.headers.get("Content-Length") or 0)
                except (TypeError, ValueError):
                    total = 0

                part = dest_path + ".part"
                bar = download_bar(filename, total or None, enabled=show)
                try:
                    with open(part, "wb") as fh:
                        for chunk in response.iter_content(chunk_size=_CHUNK):
                            if chunk:
                                fh.write(chunk)
                                bar.update(len(chunk))
                    os.replace(part, dest_path)
                except BaseException:
                    if os.path.exists(part):
                        os.remove(part)
                    raise
                finally:
                    bar.close()

            return dest_path

        return _with_retries(
            attempt, stage="download", progress=show
        )
