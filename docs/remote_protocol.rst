Remote annotation protocol
==========================

This document specifies the HTTP interface between ``pyslide.remote`` and an
annotation server. A conforming server implements six routes, none of which
describe how the analysis itself works. A server that implements them is usable
from pyslide without any pyslide-specific code on the client.

The protocol identifier for this version is ``pyslide-remote/1``.

Conventions
-----------
``{base}`` is the server root that a user configures, for example
``https://analysis.example.org/api/remote``. Every route below is served under
``{base}/v1/``.

Requests and responses are JSON, with two exceptions: slide upload is multipart,
and artifact download returns file bytes.

Authenticated routes take a bearer token::

    Authorization: Bearer <token>

Errors use one shape, at every status code::

    {"error": "machine_readable_code", "message": "Human readable text."}

Clients display ``message`` to end users and branch on ``error``.

Capabilities
------------
``GET {base}/v1/capabilities``

Unauthenticated. This is the only route that must be reachable without a token.

::

    {
      "protocol": "pyslide-remote/1",
      "auth_methods": ["login", "token"],
      "max_upload_bytes": 2147483648
    }

``protocol`` is required. ``auth_methods`` and ``max_upload_bytes`` are optional
hints, which clients report in diagnostics.

.. note::
   Clients call this route before uploading, to confirm compatibility without
   transferring a slide first.

Login
-----
``POST {base}/v1/auth/login``

Request::

    {"username": "someone", "password": "secret"}

Response::

    {"token": "abc123", "username": "someone"}

Clients store the token. A server that accepts only pre-issued tokens returns
HTTP 404 or 405 here and advertises ``"auth_methods": ["token"]``.

Whoami
------
``GET {base}/v1/auth/whoami``

::

    {"username": "someone"}

A server that does not implement this route returns HTTP 404, and clients then
report a stored token as unverified.

.. note::
   This route lets ``pyslide-remote doctor`` distinguish an invalid token from
   an unreachable server.

Submit a job
------------
``POST {base}/v1/jobs``

A multipart request with one file field named ``file``. The response is HTTP 201
with the job id::

    {"id": "6f2c19"}

Ids are opaque strings. Integers are acceptable provided they round-trip through
JSON. Submission starts the work, so there is no separate start call.

Version 1 defines no processing options. Server-side configuration determines how
the analysis runs.

Job status
----------
``GET {base}/v1/jobs/{id}``

::

    {
      "id": "6f2c19",
      "status": "processing",
      "progress": 40,
      "message": "Analyzing tiles."
    }

``status`` is required and takes one of four values:

============== ==============================================================
``pending``    Accepted, not started.
``processing`` Running.
``completed``  Finished; artifacts are available.
``failed``     Finished unsuccessfully; ``message`` should explain why.
============== ==============================================================

``progress`` is optional, either a percentage or a fraction between 0 and 1.
``message`` is optional and is displayed to the user, which makes it the
appropriate place to report the cause of a failure.

Unknown job ids return HTTP 404.

.. warning::
   Clients treat HTTP 404 on this route as permanent: the local record is
   discarded and the slide is uploaded again. Servers must not return 404 for
   transient conditions such as a restarting worker.

Artifacts
---------
``GET {base}/v1/jobs/{id}/artifacts``

::

    {
      "artifacts": [
        {"name": "mask.png", "url": "/api/remote/v1/jobs/6f2c19/files/mask.png"},
        {"name": "results.csv", "url": "https://cdn.example.org/6f2c19/results.csv"}
      ]
    }

``name`` is the filename that a client suggests locally. ``url`` is either
absolute or relative to ``{base}``. Names are opaque: clients neither parse them
nor infer meaning from them, and they sanitize them before writing to disk.

Each ``url`` serves the file bytes and accepts the same bearer token. A
``Content-Length`` header enables a progress bar.

Client behaviour
----------------
This section is informative. A server need not accommodate these behaviours, but
they describe the traffic to expect.

Retries
    HTTP 502, 503, 504, connection resets, and timeouts are retried with
    exponential backoff on GET routes and login. Other statuses are not
    retried. ``POST /jobs`` is not retried: the server may already have
    created the job after the client stopped waiting.

Re-authentication
    On HTTP 401 or 403 a client logs in once more and retries the request a
    single time.

Polling
    While waiting, a client polls the status route at a user-configurable
    interval of a few seconds.

Upload deduplication
    Job ids are cached locally against the slide, so a repeated ``annotate``
    checks the existing job instead of uploading again.

Example session
---------------
::

    BASE=https://analysis.example.org/api/remote

    # 1. Confirm the server is compatible.
    curl -s $BASE/v1/capabilities

    # 2. Obtain a token.
    TOKEN=$(curl -s -X POST $BASE/v1/auth/login \
      -H 'Content-Type: application/json' \
      -d '{"username":"someone","password":"secret"}' \
      | python -c 'import json,sys; print(json.load(sys.stdin)["token"])')

    # 3. Submit a slide.
    JOB=$(curl -s -X POST $BASE/v1/jobs \
      -H "Authorization: Bearer $TOKEN" \
      -F file=@slide.tif \
      | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')

    # 4. Poll until the job reaches a terminal status.
    curl -s $BASE/v1/jobs/$JOB -H "Authorization: Bearer $TOKEN"

    # 5. List and fetch the results.
    curl -s $BASE/v1/jobs/$JOB/artifacts -H "Authorization: Bearer $TOKEN"
    curl -sOJ $BASE/v1/jobs/$JOB/files/mask.png -H "Authorization: Bearer $TOKEN"

Client configuration handoff
----------------------------
A server may publish a downloadable JSON file that
``pyslide-remote init --from FILE`` imports::

    {
      "name": "lab",
      "base_url": "https://analysis.example.org/api/remote",
      "protocol": "pyslide-remote/1",
      "token": "abc123"
    }

Only ``base_url`` is required. ``name`` becomes the local profile name, and
``token`` skips the login step. Unknown keys are ignored, which lets a server
add hints without breaking older clients. A trailing ``/v1`` on ``base_url`` is
accepted and normalized away.

.. note::
   This route is optional. It exists because mistyped URLs are a common cause of
   failed setup.

Conformance checklist
---------------------
#. ``GET /v1/capabilities`` returns ``{"protocol": "pyslide-remote/1"}``
   without authentication.
#. ``POST /v1/auth/login`` returns a token, or 404 if tokens are issued out of
   band.
#. ``GET /v1/auth/whoami`` confirms a token, or returns 404.
#. ``POST /v1/jobs`` accepts multipart ``file`` and returns ``{"id": ...}``.
#. ``GET /v1/jobs/{id}`` returns one of the four statuses, and 404 for unknown
   ids.
#. ``GET /v1/jobs/{id}/artifacts`` returns ``{"artifacts": [{"name", "url"}]}``,
   and those URLs serve file bytes.
#. Errors use the ``{"error", "message"}`` shape.

An implementation can be checked against the reference client::

    pyslide-remote init --url https://your-server/api/remote
    pyslide-remote doctor
    pyslide-remote annotate slide.tif
