# -*- coding: utf-8 -*-
""" Exception types raised by the remote annotation client."""

from __future__ import annotations


__all__ = [
    "RemoteError",
    "RemoteConfigError",
    "RemoteProtocolError",
    "RemoteAPIError",
    "RemoteAuthError",
    "RemoteJobNotFound",
    "VsiPackageError",
]


class RemoteError(Exception):
    """ Base class for every remote annotation failure."""


class RemoteConfigError(RemoteError):
    """ Local configuration is missing or unusable."""


class RemoteProtocolError(RemoteError):
    """ Server replied with something the protocol does not allow."""


class RemoteAPIError(RemoteError):
    """ Remote server rejected or failed a request.

    Attributes
    ----------
    status_code : int or None
        HTTP status code, when the failure came from a response.
    error : str or None
        Machine-readable ``error`` code from the response body.
    """

    def __init__(self, message, *, status_code=None, error=None):
        super().__init__(message)
        self.status_code = status_code
        self.error = error


class RemoteAuthError(RemoteAPIError):
    """ Authentication or authorization failed (HTTP 401/403)."""


class RemoteJobNotFound(RemoteAPIError):
    """ Server does not know the requested job id (HTTP 404)."""


class VsiPackageError(RemoteError, ValueError):
    """ A ``.vsi`` slide is missing the companion folder it needs."""
