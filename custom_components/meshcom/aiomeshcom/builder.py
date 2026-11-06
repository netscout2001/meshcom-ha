"""Builders for datagrams sent to the node's external UDP interface.

Everything sent here goes out on amateur radio under the node's callsign.
The builders refuse anything the node would cut, misread or that could
imitate a control message (acknowledgement, time beacon, sequence number).
"""

from __future__ import annotations

import json
import math
import re
from typing import Final

from .callsign import is_destination
from .const import (
    MAX_DESTINATION_CHARS,
    MAX_OUTGOING_TEXT_BYTES,
    NODE_MAX_INCOMING_BYTES,
    TIME_BEACON_PREFIX,
)
from .errors import InvalidOutgoingError
from .text import contains_unwanted

_ACK_LIKE_RE: Final = re.compile(r".*:(ack|rej)[0-9]{1,3}\Z", re.IGNORECASE)
_SEQUENCE_LIKE_RE: Final = re.compile(r".*\{[0-9]{1,3}\}?\Z")

# Ranges accepted for external telemetry, aligned with the parser.
_TELEMETRY_RANGES: Final = {
    "temp": (-60.0, 85.0),
    "temp2": (-60.0, 85.0),
    "hum": (0.0, 100.0),
    "press": (300.0, 1100.0),
    "qnh": (800.0, 1100.0),
    "gasres": (0.0, 100_000.0),
    "co2": (0.0, 100_000.0),
}


def _encode(payload: dict[str, object]) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    encoded = data.encode("utf-8")
    if len(encoded) > NODE_MAX_INCOMING_BYTES:
        raise InvalidOutgoingError("datagram_too_long")
    return encoded


def build_text_message(destination: str, text: str) -> bytes:
    """Build a ``msg`` datagram for broadcast (``*``), a group or a callsign."""
    if len(destination) > MAX_DESTINATION_CHARS or not is_destination(destination):
        raise InvalidOutgoingError("destination")
    if not text or text.strip() == "":
        raise InvalidOutgoingError("text_empty")
    if len(text.encode("utf-8")) > MAX_OUTGOING_TEXT_BYTES:
        raise InvalidOutgoingError("text_too_long")
    if contains_unwanted(text):
        raise InvalidOutgoingError("text_control_characters")
    if text.startswith(TIME_BEACON_PREFIX):
        raise InvalidOutgoingError("text_reserved_prefix")
    if _ACK_LIKE_RE.fullmatch(text) or _SEQUENCE_LIKE_RE.fullmatch(text):
        raise InvalidOutgoingError("text_reserved_suffix")
    return _encode({"type": "msg", "dst": destination, "msg": text})


def build_external_telemetry(values: dict[str, float]) -> bytes:
    """Build a ``tele`` datagram that sets sensor values in the node's beacon.

    The node ignores the datagram if it has real sensor hardware.
    """
    if not values:
        raise InvalidOutgoingError("telemetry_empty")
    payload: dict[str, object] = {"type": "tele"}
    for key, value in values.items():
        bounds = _TELEMETRY_RANGES.get(key)
        if bounds is None:
            raise InvalidOutgoingError("telemetry_field")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidOutgoingError("telemetry_value")
        if not math.isfinite(value) or not bounds[0] <= value <= bounds[1]:
            raise InvalidOutgoingError("telemetry_range")
        payload[key] = round(float(value), 2)
    return _encode(payload)
