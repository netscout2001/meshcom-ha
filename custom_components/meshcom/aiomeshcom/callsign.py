"""Validation of callsigns, group numbers and source paths.

Only plain ASCII is accepted. Look-alike characters from other scripts (for
example a Cyrillic "\u0425" in place of the "X" in "QX1YZ-12") never validate as a callsign
(security concept C-03).
"""

from __future__ import annotations

import re
from typing import Final

from .const import MAX_DESTINATION_CHARS, MAX_PATH_CHARS
from .errors import InvalidPacketError

# Base callsign: 3 to 7 ASCII letters and digits with at least one of each,
# optionally followed by an SSID of one or two digits ("-12", "-98").
_CALLSIGN_RE: Final = re.compile(
    r"(?=[A-Z0-9]*[0-9])(?=[A-Z0-9]*[A-Z])[A-Z0-9]{3,7}(?:-[0-9]{1,2})?"
)
_GROUP_RE: Final = re.compile(r"[0-9]{1,5}")

BROADCAST: Final = "*"


def is_callsign(value: str) -> bool:
    """Return True if ``value`` is a syntactically valid callsign."""
    return len(value) <= MAX_DESTINATION_CHARS and _CALLSIGN_RE.fullmatch(value) is not None


def is_group(value: str) -> bool:
    """Return True if ``value`` is a group number (1 to 5 digits)."""
    return _GROUP_RE.fullmatch(value) is not None


def is_destination(value: str) -> bool:
    """Return True for broadcast, a group number or a callsign."""
    return value == BROADCAST or is_group(value) or is_callsign(value)


def parse_path(value: str) -> tuple[str, ...]:
    """Split a source path into callsigns.

    The first entry is the originator, the following entries are the relays
    the packet went through. Every entry must be a valid callsign.
    """
    if not value or len(value) > MAX_PATH_CHARS:
        raise InvalidPacketError("path_length")
    parts = tuple(value.split(","))
    if not all(is_callsign(part) for part in parts):
        raise InvalidPacketError("path_callsign")
    return parts
