from __future__ import annotations

from dkim import DKIMException


class HTTPLoaderError(Exception):
    pass


class UnsafeURLError(HTTPLoaderError):
    pass


class BadHeaderError(ValueError):
    pass


class IncompleteMessage(ValueError):
    pass