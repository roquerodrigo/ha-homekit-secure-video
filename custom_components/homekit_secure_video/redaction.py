"""Keeps camera credentials out of logs and diagnostics."""

from __future__ import annotations

import re

_CREDENTIALS = re.compile(r"(?<=//)[^/@\s]+:[^/@\s]+@")
REDACTED = "***:***@"


def redact_credentials(source: str) -> str:
    """
    Return a stream URL with any user and password replaced.

    Camera stream sources carry credentials inline, and these end up in log
    lines and diagnostics that leave the machine.
    """
    return _CREDENTIALS.sub(REDACTED, source)
