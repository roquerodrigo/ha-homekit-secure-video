"""Keeps camera credentials out of logs and diagnostics."""

from __future__ import annotations

import re

_USER_INFO = re.compile(r"(?<=//)[^/@\s]+:[^/@\s]+@")
_QUERY_CREDENTIALS = re.compile(
    r"(?i)([?&](?:password|passwd|pwd|token|auth|user(?:name)?)=)[^&\s]+"
)
REDACTED = "***:***@"
REDACTED_QUERY_VALUE = r"\1***"


def redact_credentials(source: str) -> str:
    """
    Return a stream URL with any user and password replaced.

    Camera stream sources carry credentials both in the user info and in the
    query string — the FLV and RTMP sources Reolink offers use the latter — and
    these end up in log lines and diagnostics that leave the machine.
    """
    return _QUERY_CREDENTIALS.sub(
        REDACTED_QUERY_VALUE, _USER_INFO.sub(REDACTED, source)
    )
