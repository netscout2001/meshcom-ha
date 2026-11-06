"""Typed representations of MeshCom external UDP packets."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum


class SourceType(StrEnum):
    """Where the node got the packet from (``src_type``)."""

    NODE = "node"  # sent by the node itself
    LORA = "lora"  # received over the air
    UDP = "udp"  # relayed by the MeshCom server (gateway nodes)


class DestinationKind(StrEnum):
    """Kind of a text message destination."""

    BROADCAST = "broadcast"
    GROUP = "group"
    DIRECT = "direct"
    #: Any other APRS addressee, e.g. "TEST" (seen in the field). Received
    #: only; the builders never send to it.
    OTHER = "other"


class DeliveryStatus(IntEnum):
    """Status codes of the ``ack`` datagram (firmware ``ack_attribution.h``)."""

    HEARD_BY_NODE = 0
    GATEWAY = 1
    DELIVERED = 2
    FAILED = 3
    HELD = 4


@dataclass(frozen=True, slots=True)
class MessageId:
    """A 32-bit MeshCom message id.

    The firmware builds ids of its own transmissions as
    ``((gateway_id & 0x3FFFFF) << 10) | (counter & 0x3FF)``, where the gateway
    id is derived from the MAC address. The upper 22 bits therefore identify
    the sending node, the lower 10 bits are the counter that also appears as
    ``{NNN}`` in direct messages.
    """

    value: int

    @property
    def node_id(self) -> int:
        """The 22-bit node identifier."""
        return self.value >> 10

    @property
    def counter(self) -> int:
        """The 10-bit message counter."""
        return self.value & 0x3FF

    def __str__(self) -> str:
        return f"{self.value:08X}"


@dataclass(frozen=True, slots=True)
class Firmware:
    """Firmware version of the originating node.

    The node reports its own version as text (``"4.40"``) and the version of
    received stations as a number (``40``); both mean 4.40. A number of 0 is
    used by MeshCom servers and means "unknown".
    """

    minor: int | None
    sub: str | None

    def __str__(self) -> str:
        if self.minor is None:
            return "unknown"
        return f"4.{self.minor:02d}{self.sub or ''}"


@dataclass(frozen=True, slots=True)
class Path:
    """Source path: originator first, then the relays."""

    callsigns: tuple[str, ...]

    @property
    def originator(self) -> str:
        """The station that created the packet."""
        return self.callsigns[0]

    @property
    def relays(self) -> tuple[str, ...]:
        """Stations that relayed the packet, in order."""
        return self.callsigns[1:]

    @property
    def hops(self) -> int:
        """Number of relays."""
        return len(self.callsigns) - 1


@dataclass(frozen=True, slots=True)
class Radio:
    """Signal values. ``None`` when the packet did not come over the air."""

    rssi: int | None
    snr: float | None


@dataclass(frozen=True, slots=True)
class PositionPacket:
    """A position beacon (``type: pos``)."""

    source_type: SourceType
    path: Path
    msg_id: MessageId
    firmware: Firmware
    radio: Radio
    latitude: float | None
    longitude: float | None
    altitude_m: float | None
    battery: int | None
    symbol: str | None
    symbol_table: str | None
    hardware_id: int | None
    max_hop: int | None


@dataclass(frozen=True, slots=True)
class TelemetryPacket:
    """Sensor values that accompany a position beacon (``type: tele``).

    The firmware sends 0 for every value it does not have. 0 is therefore
    reported as ``None``. Known limitation: a temperature of exactly 0.0 degrees C
    is also reported as ``None``.
    """

    source_type: SourceType
    path: Path
    battery: int | None
    temperature_1: float | None
    temperature_2: float | None
    humidity: float | None
    pressure_qfe: float | None
    pressure_qnh: float | None
    pressure_altitude_m: float | None
    gas: float | None
    co2: float | None
    digital_inputs: str | None

    @property
    def has_sensor_data(self) -> bool:
        """True if at least one environmental value is present."""
        return any(
            value is not None
            for value in (
                self.temperature_1,
                self.temperature_2,
                self.humidity,
                self.pressure_qfe,
                self.pressure_qnh,
                self.gas,
                self.co2,
            )
        )


@dataclass(frozen=True, slots=True)
class TextMessagePacket:
    """A chat message (``type: msg``)."""

    source_type: SourceType
    path: Path
    msg_id: MessageId
    firmware: Firmware
    radio: Radio
    destination: str
    destination_kind: DestinationKind
    text: str
    #: ``{NNN}`` number of a direct message, used for the acknowledgement.
    sequence: int | None
    #: True if control or invisible characters were removed from the text.
    text_cleaned: bool
    hardware_id: int | None
    max_hop: int | None


@dataclass(frozen=True, slots=True)
class AckMessagePacket:
    """An acknowledgement sent as text, e.g. ``"DO8RE-12 :ack724"``.

    Any station can send such a text. It may only be applied to an open own
    message with the same sequence number that was sent to ``path.originator``
    (security concept C-13).
    """

    source_type: SourceType
    path: Path
    msg_id: MessageId
    radio: Radio
    #: The station whose message is acknowledged (the addressee of the text).
    acknowledged_station: str
    sequence: int
    rejected: bool


@dataclass(frozen=True, slots=True)
class RemoteManagementPacket:
    """Authenticated remote management between nodes ("RM1 ...").

    Commands and replies are HMAC-signed by the firmware; the signature is a
    16-hex tag at the end of the text. They are control traffic, not chat.
    """

    source_type: SourceType
    path: Path
    msg_id: MessageId
    destination: str
    counter: int
    is_reply: bool
    text: str


@dataclass(frozen=True, slots=True)
class TimeBeaconPacket:
    """A time beacon of a MeshCom server (``{CET}2026-11-06 09:28:08``)."""

    source_type: SourceType
    path: Path
    msg_id: MessageId
    text: str


@dataclass(frozen=True, slots=True)
class DeliveryStatusPacket:
    """Delivery status datagram generated by the node (``type: ack``)."""

    msg_id: MessageId
    status: DeliveryStatus
    from_station: str | None
    via: str | None


type Packet = (
    PositionPacket
    | TelemetryPacket
    | TextMessagePacket
    | AckMessagePacket
    | RemoteManagementPacket
    | TimeBeaconPacket
    | DeliveryStatusPacket
)
