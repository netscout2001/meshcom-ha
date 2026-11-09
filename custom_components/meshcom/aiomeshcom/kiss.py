"""KISS-over-TCP access to a MeshCom node (firmware 4.40a, ``kiss_functions.cpp``).

The node offers one TCP client slot on port 8001. Frames are standard KISS
(FEND/FESC framing) with AX.25 UI frames on port 0, plus three private
ports: port 1 carries RSSI/SNR of the preceding frame, port 2 the full
originator callsign when the AX.25 SSID had to be clamped to 15, and port 15
the result of a frame the client sent.

Decoded frames are turned into the same objects the external UDP interface
delivers and validated by :func:`parse_object`, so both access paths share
one set of checks (security concept C-02, C-03, C-10).

The AX.25 frames carry no MeshCom message id. The decoder therefore assigns
a running local id; the node has already removed duplicates.

Optional authentication: the node sends ``NONCE: <32 hex>``, the client
answers ``HMAC-SHA256(password, nonce bytes)`` as 64 hex characters and gets
``OK`` or ``FAIL``. The password is ``--passwd`` (at most 14 characters).
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import secrets
from dataclasses import dataclass
from typing import Any, Final

from .builder import validate_text_message
from .callsign import BROADCAST, is_callsign
from .const import FEET_TO_METERS
from .errors import InvalidOutgoingError, InvalidPacketError
from .models import Packet, PositionPacket, SourceType, TextMessagePacket
from .parser import parse_object

KISS_TCP_PORT: Final = 8001
#: Upper bound for one frame; the node's largest frame is about 350 bytes.
MAX_KISS_FRAME: Final = 1024
#: Longest ``--passwd`` the firmware stores.
MAX_KISS_PASSWORD: Final = 14

FEND: Final = 0xC0
FESC: Final = 0xDB
TFEND: Final = 0xDC
TFESC: Final = 0xDD

PORT_DATA: Final = 0
PORT_META: Final = 1
PORT_SRCINFO: Final = 2
PORT_TXRESULT: Final = 15

#: The node marks its own frames and frames from the MeshCom server with
#: these values instead of a measurement.
_NO_MEASUREMENT_RSSI: Final = 99

#: Destination (tocall) of frames the client sends; the node ignores it.
_TOCALL: Final = "APRSMC"

_NONCE_RE: Final = re.compile(rb"NONCE: ([0-9a-f]{32})\r?\n?")
_POSITION_RE: Final = re.compile(
    r"[!=]([0-9]{2})([0-9]{2}\.[0-9]{2})([NS])(.)([0-9]{3})([0-9]{2}\.[0-9]{2})([EW])(.)(.*)",
    re.S,
)
#: MeshCom tags at the end of a position comment: /B=096/A=001713/N4/R=...;
_TAGS_RE: Final = re.compile(r"(?:/(?:[A-Z]=[^/]*|N[0-9]{1,3}))+\Z")
_TAG_RE: Final = re.compile(r"/([A-Z])=?([^/]*)")
_ACK_RE: Final = re.compile(r"(ack|rej)[0-9]{1,3}")


class TxStatus:
    """Status codes of the TX result (port 15)."""

    OK: Final = 0x01
    BAD_CALL: Final = 0x02
    TX_OFF: Final = 0x03
    BAD_FRAME: Final = 0x04
    RATE_LIMIT: Final = 0x05


@dataclass(frozen=True, slots=True)
class KissTxResult:
    """Answer of the node to a frame we sent."""

    status: int
    msg_id: int | None

    @property
    def ok(self) -> bool:
        """True if the node accepted the frame for transmission."""
        return self.status == TxStatus.OK


# --- framing -----------------------------------------------------------------


class KissDeframer:
    """Splits a TCP byte stream into unescaped KISS frames."""

    def __init__(self, max_frame: int = MAX_KISS_FRAME) -> None:
        self._max = max_frame
        self._buffer = bytearray()
        self._escape = False
        self._overflow = False
        #: Frames dropped because they were too long or badly escaped.
        self.dropped = 0

    def feed(self, data: bytes) -> list[bytes]:
        """Add received bytes; returns the frames completed by them."""
        frames: list[bytes] = []
        for raw in data:
            byte = raw
            if byte == FEND:
                if self._buffer and not self._overflow:
                    frames.append(bytes(self._buffer))
                elif self._overflow:
                    self.dropped += 1
                self._buffer.clear()
                self._escape = False
                self._overflow = False
                continue
            if self._overflow:
                continue
            if self._escape:
                self._escape = False
                if byte == TFEND:
                    byte = FEND
                elif byte == TFESC:
                    byte = FESC
                else:
                    self._overflow = True  # protocol error: drop this frame
                    continue
            elif byte == FESC:
                self._escape = True
                continue
            if len(self._buffer) >= self._max:
                self._overflow = True
                continue
            self._buffer.append(byte)
        return frames


def kiss_frame(port: int, payload: bytes) -> bytes:
    """Escape and frame ``payload`` for ``port`` (command 0, data)."""
    body = bytearray()
    for byte in payload:
        if byte == FEND:
            body += bytes((FESC, TFEND))
        elif byte == FESC:
            body += bytes((FESC, TFESC))
        else:
            body.append(byte)
    return bytes((FEND, (port & 0x0F) << 4)) + bytes(body) + bytes((FEND,))


# --- AX.25 -------------------------------------------------------------------


def _decode_address(raw: bytes) -> tuple[str, int, bool]:
    """Callsign, SSID and "last address" flag of a 7-byte AX.25 address."""
    chars = []
    for byte in raw[:6]:
        if byte & 0x01:
            raise InvalidPacketError("ax25_address")
        char = chr(byte >> 1)
        if not (char.isascii() and (char.isalnum() or char == " ")):
            raise InvalidPacketError("ax25_address")
        chars.append(char)
    base = "".join(chars)
    if " " in base.rstrip(" ") or not base.strip():
        raise InvalidPacketError("ax25_address")
    ssid = (raw[6] >> 1) & 0x0F
    return base.strip().upper(), ssid, bool(raw[6] & 0x01)


def _call(base: str, ssid: int) -> str:
    return f"{base}-{ssid}" if ssid else base


def _encode_address(call: str, *, last: bool, command: bool) -> bytes:
    base, _, ssid_text = call.partition("-")
    ssid = int(ssid_text) if ssid_text else 0
    if not 0 <= ssid <= 15 or not 1 <= len(base) <= 6:
        raise InvalidOutgoingError("callsign")
    encoded = bytes(ord(char) << 1 for char in base.ljust(6))
    last_byte = 0x60 | (ssid << 1) | (0x80 if command else 0) | (0x01 if last else 0)
    return encoded + bytes((last_byte,))


@dataclass(frozen=True, slots=True)
class Ax25Frame:
    """An AX.25 UI frame."""

    destination: str
    source_base: str
    source_ssid: int
    digipeaters: tuple[str, ...]
    info: bytes


def parse_ax25(frame: bytes) -> Ax25Frame:
    """Parse a UI frame with "no layer 3" PID; anything else is rejected."""
    addresses: list[tuple[str, int]] = []
    offset = 0
    last = False
    while not last:
        if len(addresses) >= 10 or offset + 7 > len(frame):
            raise InvalidPacketError("ax25_address")
        base, ssid, last = _decode_address(frame[offset : offset + 7])
        addresses.append((base, ssid))
        offset += 7
    if len(addresses) < 2 or offset + 2 > len(frame):
        raise InvalidPacketError("ax25_address")
    if frame[offset] != 0x03 or frame[offset + 1] != 0xF0:
        raise InvalidPacketError("ax25_not_ui")
    return Ax25Frame(
        destination=_call(*addresses[0]),
        source_base=addresses[1][0],
        source_ssid=addresses[1][1],
        digipeaters=tuple(_call(base, ssid) for base, ssid in addresses[2:]),
        info=frame[offset + 2 :],
    )


# --- decoding into packets ---------------------------------------------------


def _latitude(degrees: str, minutes: str, hemisphere: str) -> tuple[float, str]:
    value = int(degrees) + float(minutes) / 60
    if value > 90:
        raise InvalidPacketError("kiss_position")
    return round(value, 5), hemisphere


def _longitude(degrees: str, minutes: str, hemisphere: str) -> tuple[float, str]:
    value = int(degrees) + float(minutes) / 60
    if value > 180:
        raise InvalidPacketError("kiss_position")
    return round(value, 5), hemisphere


def _float_tag(tags: dict[str, str], key: str) -> float | None:
    raw = tags.get(key)
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) and abs(value) < 1e7 else None


def _int_tag(tags: dict[str, str], key: str) -> int | None:
    raw = tags.get(key)
    return int(raw) if raw is not None and raw.isdigit() and len(raw) <= 6 else None


class KissDecoder:
    """Turns KISS frames into packets of the UDP models.

    RSSI/SNR (port 1) follow their data frame, so a data frame is held
    until the next frame arrives or :meth:`flush` is called.
    """

    def __init__(self, own_callsign: str) -> None:
        self.own_callsign = own_callsign
        self._deframer = KissDeframer()
        self._pending: tuple[Ax25Frame, str | None] | None = None
        self._srcinfo: str | None = None
        self._counter = secrets.randbelow(1 << 32)
        #: Frames that could not be decoded, by reason.
        self.invalid: dict[str, int] = {}

    @property
    def has_pending(self) -> bool:
        """True while a data frame waits for its RSSI/SNR."""
        return self._pending is not None

    def feed(self, data: bytes) -> list[Packet | KissTxResult]:
        """Add received bytes; returns the decoded packets and TX results."""
        results: list[Packet | KissTxResult] = []
        for frame in self._deframer.feed(data):
            results.extend(self._frame(frame))
        return results

    def flush(self) -> list[Packet | KissTxResult]:
        """Emit a held data frame without RSSI/SNR."""
        return self._emit(None, None)

    def _count(self, reason: str) -> None:
        self.invalid[reason] = self.invalid.get(reason, 0) + 1

    def _frame(self, frame: bytes) -> list[Packet | KissTxResult]:
        port, command, payload = frame[0] >> 4, frame[0] & 0x0F, frame[1:]
        if command != 0:
            self._count("kiss_command")
            return []
        if port == PORT_META:
            if len(payload) != 3:
                self._count("kiss_meta")
                return self._emit(None, None)
            snr = int.from_bytes(payload[0:1], "little", signed=True)
            rssi = int.from_bytes(payload[1:3], "little", signed=True)
            return self._emit(rssi, snr)
        results = self._emit(None, None)
        if port == PORT_SRCINFO:
            call = payload.decode("ascii", "replace")
            self._srcinfo = call if is_callsign(call) else None
        elif port == PORT_TXRESULT:
            results.append(self._tx_result(payload))
        elif port == PORT_DATA:
            # The full callsign (port 2) belongs to the data frame right after it.
            srcinfo, self._srcinfo = self._srcinfo, None
            try:
                self._pending = (parse_ax25(payload), srcinfo)
            except InvalidPacketError as err:
                self._count(err.reason)
        else:
            self._count("kiss_port")
        return results

    def _tx_result(self, payload: bytes) -> KissTxResult:
        if not payload:
            return KissTxResult(TxStatus.BAD_FRAME, None)
        status = payload[0]
        msg_id = int.from_bytes(payload[1:5], "little") if len(payload) >= 5 else None
        return KissTxResult(status, msg_id if status == TxStatus.OK else None)

    def _emit(self, rssi: int | None, snr: int | None) -> list[Packet | KissTxResult]:
        pending, self._pending = self._pending, None
        if pending is None:
            return []
        frame, srcinfo = pending
        originator = _call(frame.source_base, frame.source_ssid)
        if (
            srcinfo is not None
            and frame.source_ssid == 15
            and srcinfo.partition("-")[0] == frame.source_base
        ):
            originator = srcinfo
        try:
            return self._packets(frame, originator, rssi, snr)
        except InvalidPacketError as err:
            self._count(err.reason)
            return []

    def _next_id(self) -> str:
        self._counter = (self._counter + 1) & 0xFFFFFFFF
        return f"{self._counter:08X}"

    def _base_object(
        self, frame: Ax25Frame, originator: str, rssi: int | None, snr: int | None
    ) -> dict[str, Any]:
        no_measurement = rssi == _NO_MEASUREMENT_RSSI and snr == 0
        # Own frames carry the "no measurement" marker (or no meta frame at
        # all). A frame with our callsign and a real RSSI came over the air:
        # another station using our callsign, not the node itself.
        if originator == self.own_callsign and (rssi is None or no_measurement):
            source = SourceType.NODE
        elif no_measurement:
            source = SourceType.UDP
        else:
            source = SourceType.LORA
        obj: dict[str, Any] = {
            "src_type": source.value,
            "src": ",".join((originator, *frame.digipeaters)),
            "msg_id": self._next_id(),
            "firmware": 0,
        }
        if rssi is not None and snr is not None and source is SourceType.LORA:
            obj["rssi"] = rssi
            obj["snr"] = snr
        return obj

    def _packets(
        self, frame: Ax25Frame, originator: str, rssi: int | None, snr: int | None
    ) -> list[Packet | KissTxResult]:
        try:
            info = frame.info.decode("utf-8")
        except UnicodeDecodeError as err:
            raise InvalidPacketError("encoding") from err
        obj = self._base_object(frame, originator, rssi, snr)
        if info.startswith(":"):
            return [self._message(obj, info)]
        if info[:1] in ("!", "="):
            return self._position(obj, info)
        raise InvalidPacketError("kiss_payload_type")

    def _message(self, obj: dict[str, Any], info: str) -> Packet:
        if len(info) < 11 or info[10] != ":":
            raise InvalidPacketError("kiss_message")
        addressee = info[1:10].strip(" ")
        text = info[11:]
        destination = addressee or BROADCAST
        # The node turns "<call> :ack12" into the addressee field; rebuild the
        # text form the UDP interface delivers, so one classifier handles both.
        if _ACK_RE.fullmatch(text) and is_callsign(addressee):
            text = f"{addressee}:{text}"
        obj.update({"type": "msg", "dst": destination, "msg": text})
        return parse_object(obj)

    def _position(self, obj: dict[str, Any], info: str) -> list[Packet | KissTxResult]:
        match = _POSITION_RE.fullmatch(info)
        if match is None:
            raise InvalidPacketError("kiss_position")
        lat_deg, lat_min, lat_dir, table, lon_deg, lon_min, lon_dir, symbol, comment = (
            match.groups()
        )
        latitude, lat_dir = _latitude(lat_deg, lat_min, lat_dir)
        longitude, lon_dir = _longitude(lon_deg, lon_min, lon_dir)
        tags_match = _TAGS_RE.search(comment)
        tags = dict(_TAG_RE.findall(tags_match.group(0))) if tags_match else {}
        altitude_ft = 0
        raw_alt = tags.get("A")
        if raw_alt is not None and raw_alt.isdigit():
            # Six digits: feet (default); five digits: metres (--fuss off).
            altitude_ft = (
                int(raw_alt) if len(raw_alt) == 6 else round(int(raw_alt) / FEET_TO_METERS)
            )
        battery = _int_tag(tags, "B")
        obj.update(
            {
                "type": "pos",
                "lat": latitude,
                "lat_dir": lat_dir,
                "long": longitude,
                "long_dir": lon_dir,
                "aprs_symbol": symbol,
                "aprs_symbol_group": table,
                "alt": min(altitude_ft, 100_000),
                "batt": battery if battery is not None and battery <= 100 else 0,
            }
        )
        position = parse_object(obj)
        results: list[Packet | KissTxResult] = [position]
        # Weather tags (/T /H /P /Q ...) of the own node and of other stations.
        if isinstance(position, PositionPacket):
            telemetry = self._telemetry(obj, tags)
            if telemetry is not None:
                results.append(telemetry)
        return results

    def _telemetry(self, position: dict[str, Any], tags: dict[str, str]) -> Packet | None:
        values = {
            "temp1": _float_tag(tags, "T"),
            "temp2": _float_tag(tags, "O"),
            "hum": _float_tag(tags, "H"),
            "qfe": _float_tag(tags, "P"),
            "qnh": _float_tag(tags, "Q"),
            "gas": _float_tag(tags, "G"),
            "co2": _float_tag(tags, "C"),
            "pressure_alt": _float_tag(tags, "F"),
        }
        present = {key: value for key, value in values.items() if value is not None}
        if not present:
            return None
        return parse_object(
            {
                "src_type": position["src_type"],
                "type": "tele",
                "src": position["src"],
                "batt": position["batt"],
                **present,
            }
        )


# --- sending -----------------------------------------------------------------


def build_kiss_message(
    own_callsign: str, destination: str, text: str, sequence: int | None = None
) -> bytes:
    """A KISS frame that makes the node send ``text`` to ``destination``.

    ``sequence`` (1-999) is appended to direct messages as ``{nn``; the node
    maps the acknowledgement back to it. The node accepts the frame only if
    the source is its own callsign.
    """
    validate_text_message(destination, text)
    if not is_callsign(own_callsign):
        raise InvalidOutgoingError("callsign")
    addressee = "" if destination == BROADCAST else destination
    if sequence is not None:
        if not addressee or not is_callsign(addressee) or not 1 <= sequence <= 999:
            raise InvalidOutgoingError("sequence")
        text = f"{text}{{{sequence}"
    info = f":{addressee:<9}:{text}".encode()
    frame = (
        _encode_address(_TOCALL, last=False, command=True)
        + _encode_address(own_callsign, last=True, command=False)
        + bytes((0x03, 0xF0))
        + info
    )
    return kiss_frame(PORT_DATA, frame)


def own_message_packet(
    own_callsign: str, destination: str, text: str, sequence: int | None, msg_id: int
) -> TextMessagePacket:
    """The packet of a message the node accepted from us (port 15 OK).

    The node does not echo messages a KISS client sent, so this stands in
    for the echo the UDP interface would deliver.
    """
    msg = f"{text}{{{sequence}" if sequence is not None else text
    packet = parse_object(
        {
            "src_type": SourceType.NODE.value,
            "type": "msg",
            "src": own_callsign,
            "dst": destination,
            "msg": msg,
            "msg_id": f"{msg_id & 0xFFFFFFFF:08X}",
            "firmware": 0,
        }
    )
    if not isinstance(packet, TextMessagePacket):  # pragma: no cover - validated before
        raise InvalidOutgoingError("echo")
    return packet


# --- authentication ----------------------------------------------------------


def parse_nonce(line: bytes) -> bytes | None:
    """The 16 nonce bytes of a ``NONCE:`` line, or None."""
    match = _NONCE_RE.fullmatch(line)
    return bytes.fromhex(match.group(1).decode()) if match else None


def auth_response(password: str, nonce: bytes) -> bytes:
    """The answer line to a nonce: HMAC-SHA256 over the raw nonce bytes."""
    password = password.rstrip(" ")  # the node strips trailing spaces of --passwd
    if not password or len(password) > MAX_KISS_PASSWORD or not password.isascii():
        raise InvalidOutgoingError("password")
    digest = hmac.new(password.encode(), nonce, hashlib.sha256).hexdigest()
    return digest.encode() + b"\r\n"
