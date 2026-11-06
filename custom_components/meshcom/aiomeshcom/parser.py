"""Strict parser for datagrams of the MeshCom external UDP interface.

Every datagram is untrusted: the interface has no authentication and any
device on the network can send to the listening port. The parser therefore
rejects everything it does not understand completely instead of guessing
(security concept C-07):

* size limit before decoding, strict UTF-8
* no ``NaN``/``Infinity``, no duplicate keys, no nested objects or arrays
* type and range check for every field we use
* callsigns and paths in plain ASCII only

Field semantics follow the firmware source (v4.40a) and real captures; see
the comments where they differ from the published documentation.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from typing import Any, Final, NoReturn

from .callsign import BROADCAST, is_callsign, is_group, parse_path
from .const import (
    FEET_TO_METERS,
    MAX_DATAGRAM_BYTES,
    MAX_INCOMING_TEXT_CHARS,
    MAX_JSON_KEYS,
    TIME_BEACON_PREFIX,
)
from .errors import InvalidPacketError
from .models import (
    AckMessagePacket,
    DeliveryStatus,
    DeliveryStatusPacket,
    DestinationKind,
    Firmware,
    MessageId,
    Packet,
    Path,
    PositionPacket,
    Radio,
    RemoteManagementPacket,
    SourceType,
    TelemetryPacket,
    TextMessagePacket,
    TimeBeaconPacket,
)
from .text import clean_text

_MSG_ID_RE: Final = re.compile(r"[0-9A-Fa-f]{8}")
_FIRMWARE_TEXT_RE: Final = re.compile(r"4\.([0-9]{2})")
# Text acknowledgement: addressee padded to 9 characters, ":ack" or ":rej",
# then the sequence number. Seen in the field: "DO8RE-12 :ack724".
_ACK_TEXT_RE: Final = re.compile(r"([A-Z0-9-]{1,9}) *:(ack|rej)([0-9]{1,3})")
# Sequence number at the end of a direct message: "Test2{724". The closing
# brace is optional (APRS allows "{724}" as well).
_SEQUENCE_RE: Final = re.compile(r"\{([0-9]{1,3})\}?\Z")
# Any APRS addressee: up to 9 characters, upper case letters, digits, '-'.
_ADDRESSEE_RE: Final = re.compile(r"[A-Z0-9-]{1,9}")
# Remote management (firmware remote_cmd.h): "RM1 <ctr> <cmd|ok|err> ... <tag>"
_RM_RE: Final = re.compile(r"RM1 ([0-9]{1,10}) (\S+)")
_VIA_RE: Final = re.compile(r"[A-Za-z0-9_-]{1,12}")
_DIGITAL_INPUTS_RE: Final = re.compile(r"[01]{1,16}")

_SCALAR_TYPES: Final = (str, int, float, bool, type(None))


def _fail(reason: str) -> NoReturn:
    raise InvalidPacketError(reason)


def _reject_constant(_name: str) -> NoReturn:
    # json.loads accepts NaN, Infinity and -Infinity by default.
    _fail("json_constant")


def _object_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("json_duplicate_key")
        if not isinstance(value, _SCALAR_TYPES):
            _fail("json_nested")
        result[key] = value
    if len(result) > MAX_JSON_KEYS:
        _fail("json_too_many_keys")
    return result


def _load(data: bytes) -> dict[str, Any]:
    if not data or len(data) > MAX_DATAGRAM_BYTES:
        _fail("size")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        _fail("encoding")
    try:
        obj = json.loads(text, object_pairs_hook=_object_hook, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        # InvalidPacketError raised inside the hooks is not a ValueError and
        # propagates unchanged.
        _fail("json_syntax")
    if not isinstance(obj, dict):
        _fail("json_not_object")
    return obj


# --- field readers ---------------------------------------------------------


def _str(obj: dict[str, Any], key: str, *, max_len: int = 64) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or len(value) > max_len:
        _fail(f"field_{key}")
    return value


def _opt_str(obj: dict[str, Any], key: str, *, max_len: int = 64) -> str | None:
    if key not in obj:
        return None
    return _str(obj, key, max_len=max_len)


def _int(obj: dict[str, Any], key: str, low: int, high: int) -> int:
    value = obj.get(key)
    # bool is a subclass of int and must not pass as a number.
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        _fail(f"field_{key}")
    return value


def _opt_int(obj: dict[str, Any], key: str, low: int, high: int) -> int | None:
    if key not in obj:
        return None
    return _int(obj, key, low, high)


def _number(obj: dict[str, Any], key: str) -> float:
    value = obj.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"field_{key}")
    try:
        # A huge JSON integer (10**400) overflows float().
        number = float(value)
    except OverflowError:
        _fail(f"field_{key}")
    # json.loads turns 1e999 into inf without calling parse_constant.
    if not math.isfinite(number):
        _fail(f"field_{key}")
    return number


def _sensor(obj: dict[str, Any], key: str, low: float, high: float) -> float | None:
    """Read an optional sensor value. 0 and implausible values become None.

    A broken sensor must not make the whole packet invalid, so values
    outside the plausible range are dropped instead of rejected.
    """
    if key not in obj:
        return None
    number = _number(obj, key)
    if number == 0 or not low <= number <= high:
        return None
    return number


def _source_type(obj: dict[str, Any]) -> SourceType:
    value = obj.get("src_type")
    if not isinstance(value, str):
        _fail("field_src_type")
    try:
        return SourceType(value)
    except ValueError:
        _fail("field_src_type")


def _path(obj: dict[str, Any]) -> Path:
    value = obj.get("src")
    if not isinstance(value, str):
        _fail("field_src")
    return Path(parse_path(value))


def _msg_id(obj: dict[str, Any]) -> MessageId:
    value = obj.get("msg_id")
    if not isinstance(value, str) or _MSG_ID_RE.fullmatch(value) is None:
        _fail("field_msg_id")
    return MessageId(int(value, 16))


def _firmware(obj: dict[str, Any]) -> Firmware:
    value = obj.get("firmware")
    minor: int | None
    if isinstance(value, str):
        # Own node: "4.40".
        match = _FIRMWARE_TEXT_RE.fullmatch(value)
        if match is None:
            _fail("field_firmware")
        minor = int(match.group(1))
    elif isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 255:
        # Received stations: 40. 0 is used by servers and means unknown.
        minor = value or None
    else:
        _fail("field_firmware")
    sub = _opt_str(obj, "fw_sub", max_len=1)
    if sub is not None and sub and not (sub.isascii() and sub.isprintable()):
        _fail("field_fw_sub")
    return Firmware(minor=minor, sub=(sub or None) if minor is not None else None)


def _radio(obj: dict[str, Any], source_type: SourceType) -> Radio:
    rssi = _opt_int(obj, "rssi", -200, 50)
    snr: float | None = _number(obj, "snr") if "snr" in obj else None
    if snr is not None and not -50 <= snr <= 50:
        _fail("field_snr")
    if source_type is not SourceType.LORA:
        # Own transmissions and server relays carry 0/0, which is not a measurement.
        return Radio(rssi=None, snr=None)
    return Radio(rssi=rssi, snr=snr)


def _coordinate(obj: dict[str, Any], key: str, dir_key: str, limit: float, dirs: str) -> float:
    value = _number(obj, key)
    direction = obj.get(dir_key)
    if not 0 <= value <= limit or not isinstance(direction, str) or direction not in dirs:
        _fail(f"field_{key}")
    return -value if direction == dirs[1] else value


def _symbol(obj: dict[str, Any], key: str) -> str | None:
    value = _opt_str(obj, key, max_len=2)
    if value is None or value == "":
        return None
    # The firmware doubles a backslash before JSON encoding, so "\" arrives
    # as "\\" (two characters).
    if value == "\\\\":
        value = "\\"
    if len(value) != 1 or not (value.isascii() and value.isprintable()):
        _fail(f"field_{key}")
    return value


# --- packet types ----------------------------------------------------------


def _parse_position(obj: dict[str, Any]) -> PositionPacket:
    source_type = _source_type(obj)
    latitude: float | None = _coordinate(obj, "lat", "lat_dir", 90, "NS")
    longitude: float | None = _coordinate(obj, "long", "long_dir", 180, "EW")
    if latitude == 0 and longitude == 0:
        # No position fix.
        latitude = longitude = None
    altitude_ft = _int(obj, "alt", -1500, 100_000)
    battery = _opt_int(obj, "batt", 0, 100)
    return PositionPacket(
        source_type=source_type,
        path=_path(obj),
        msg_id=_msg_id(obj),
        firmware=_firmware(obj),
        radio=_radio(obj, source_type),
        latitude=latitude,
        longitude=longitude,
        # 0 is sent when the altitude is unknown.
        altitude_m=round(altitude_ft * FEET_TO_METERS, 1) if altitude_ft else None,
        # 0 is sent by stations that do not report a battery level.
        battery=battery or None,
        symbol=_symbol(obj, "aprs_symbol"),
        symbol_table=_symbol(obj, "aprs_symbol_group"),
        hardware_id=_opt_int(obj, "hw_id", 0, 255),
        max_hop=_opt_int(obj, "max_hop", 0, 255),
    )


def _parse_telemetry(obj: dict[str, Any]) -> TelemetryPacket:
    digital_inputs = _opt_str(obj, "din", max_len=16)
    if digital_inputs is not None and _DIGITAL_INPUTS_RE.fullmatch(digital_inputs) is None:
        _fail("field_din")
    pressure_altitude = _sensor(obj, "pressure_alt", -500, 10_000)
    return TelemetryPacket(
        source_type=_source_type(obj),
        path=_path(obj),
        battery=_opt_int(obj, "batt", 0, 100) or None,
        temperature_1=_sensor(obj, "temp1", -60, 85),
        temperature_2=_sensor(obj, "temp2", -60, 85),
        humidity=_sensor(obj, "hum", 0, 100),
        pressure_qfe=_sensor(obj, "qfe", 300, 1100),
        pressure_qnh=_sensor(obj, "qnh", 800, 1100),
        pressure_altitude_m=pressure_altitude,
        gas=_sensor(obj, "gas", 0, 100_000),
        co2=_sensor(obj, "co2", 0, 100_000),
        digital_inputs=digital_inputs or None,
    )


def _destination_kind(destination: str) -> DestinationKind:
    if destination == BROADCAST:
        return DestinationKind.BROADCAST
    if is_group(destination):
        return DestinationKind.GROUP
    if is_callsign(destination):
        return DestinationKind.DIRECT
    if _ADDRESSEE_RE.fullmatch(destination):
        return DestinationKind.OTHER
    _fail("field_dst")


def _parse_message(obj: dict[str, Any]) -> Packet:
    source_type = _source_type(obj)
    path = _path(obj)
    msg_id = _msg_id(obj)
    radio = _radio(obj, source_type)
    destination = _str(obj, "dst", max_len=9)
    kind = _destination_kind(destination)
    raw_text = _str(obj, "msg", max_len=MAX_INCOMING_TEXT_CHARS)

    if raw_text.startswith(TIME_BEACON_PREFIX):
        text, _ = clean_text(raw_text)
        return TimeBeaconPacket(source_type=source_type, path=path, msg_id=msg_id, text=text)

    if kind is DestinationKind.DIRECT:
        rm = _RM_RE.match(raw_text)
        if rm is not None:
            text, _ = clean_text(raw_text)
            return RemoteManagementPacket(
                source_type=source_type,
                path=path,
                msg_id=msg_id,
                destination=destination,
                counter=int(rm.group(1)),
                is_reply=rm.group(2) in ("ok", "err"),
                text=text,
            )
        ack = _ACK_TEXT_RE.fullmatch(raw_text)
        # Only a text addressed to the message's own destination counts as an
        # acknowledgement; anything else stays a normal message.
        if ack is not None and ack.group(1) == destination:
            return AckMessagePacket(
                source_type=source_type,
                path=path,
                msg_id=msg_id,
                radio=radio,
                acknowledged_station=destination,
                sequence=int(ack.group(3)),
                rejected=ack.group(2) == "rej",
            )

    sequence: int | None = None
    if kind is DestinationKind.DIRECT:
        match = _SEQUENCE_RE.search(raw_text)
        if match is not None:
            sequence = int(match.group(1))
            raw_text = raw_text[: match.start()]

    text, cleaned = clean_text(raw_text)
    return TextMessagePacket(
        source_type=source_type,
        path=path,
        msg_id=msg_id,
        firmware=_firmware(obj),
        radio=radio,
        destination=destination,
        destination_kind=kind,
        text=text,
        sequence=sequence,
        text_cleaned=cleaned,
        hardware_id=_opt_int(obj, "hw_id", 0, 255),
        max_hop=_opt_int(obj, "max_hop", 0, 255),
    )


def _parse_delivery_status(obj: dict[str, Any]) -> DeliveryStatusPacket:
    status = _int(obj, "status", 0, 4)
    from_station = _opt_str(obj, "from", max_len=9)
    if from_station is not None and not is_callsign(from_station):
        _fail("field_from")
    via = _opt_str(obj, "via", max_len=12)
    if via is not None and via and _VIA_RE.fullmatch(via) is None:
        _fail("field_via")
    return DeliveryStatusPacket(
        msg_id=_msg_id(obj),
        status=DeliveryStatus(status),
        from_station=from_station,
        via=via or None,
    )


_PARSERS: Final[dict[str, Callable[[dict[str, Any]], Packet]]] = {
    "pos": _parse_position,
    "tele": _parse_telemetry,
    "msg": _parse_message,
    "ack": _parse_delivery_status,
}


def parse_datagram(data: bytes) -> Packet:
    """Parse one datagram of the external UDP interface.

    Raises :class:`InvalidPacketError` with a stable reason code for every
    datagram that is not a complete, valid MeshCom packet.
    """
    return parse_object(_load(data))


def parse_object(obj: dict[str, Any]) -> Packet:
    """Validate an already decoded packet object (same rules as datagrams).

    Used by the KISS decoder, which builds the same object from an AX.25
    frame, so that both access paths share one set of checks.
    """
    if len(obj) > MAX_JSON_KEYS:
        _fail("too_many_keys")
    packet_type = obj.get("type")
    if not isinstance(packet_type, str) or packet_type not in _PARSERS:
        _fail("unknown_type")
    return _PARSERS[packet_type](obj)
