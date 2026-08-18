# -*- coding: utf-8 -*-
""" HTTP client for the remote annotation protocol.

Submits a whole-slide image to a compatible server, polls job status, and
downloads result files. Protocol: ``docs/remote_protocol.rst``.

Quick start::

    pip install "pyslide[remote]"
    pyslide-remote init
    pyslide-remote annotate slide.tif

From Python::

    from pyslide.remote import annotate

    result = annotate("slide.tif")
    print(result["status"], result["paths"])
"""

from ._annotate import annotate, status
from ._client import JOB_STATUSES, TERMINAL_STATUSES, RemoteClient
from ._config import PROTOCOL_ID
from ._errors import (
    RemoteAPIError,
    RemoteAuthError,
    RemoteConfigError,
    RemoteError,
    RemoteJobNotFound,
    RemoteProtocolError,
    VsiPackageError,
)

__all__ = [
    "JOB_STATUSES",
    "PROTOCOL_ID",
    "RemoteAPIError",
    "RemoteAuthError",
    "RemoteClient",
    "RemoteConfigError",
    "RemoteError",
    "RemoteJobNotFound",
    "RemoteProtocolError",
    "TERMINAL_STATUSES",
    "VsiPackageError",
    "annotate",
    "status",
]
