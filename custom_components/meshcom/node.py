"""Runtime state of one MeshCom node (one config entry)."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .aiomeshcom import (
    AckMessagePacket,
    DeliveryStatusPacket,
    DestinationKind,
    Firmware,
    Packet,
    PositionPacket,
    RemoteManagementPacket,
    SourceType,
    TelemetryPacket,
    TextMessagePacket,
    TimeBeaconPacket,
)
from .const import (
    DEDUP_MAX_ENTRIES,
    DEDUP_WINDOW,
    EVENT_DELIVERY,
    EVENT_MESSAGE,
    MAX_STATIONS,
    NODE_ACTIVE_TIMEOUT,
    STATIONS_WINDOW,
    signal_update,
)


@dataclass(slots=True)
class StationInfo:
    """What we know about a heard station. Data only, no entities (yet)."""

    callsign: str
    last_heard: datetime
    rssi: int | None = None
    snr: float | None = None
    hops: int | None = None
    battery: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    firmware: str | None = None


@dataclass(slots=True)
class ReceivedMessage:
    """The last received text message."""

    sender: str
    destination: str
    destination_kind: DestinationKind
    text: str
    received: datetime
    via_server: bool


class MeshComNode:
    """Collects the state of one node from its packets."""

    def __init__(self, hass: HomeAssistant, entry_id: str, callsign: str, node_id: int) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.callsign = callsign
        self.node_id = node_id
        self.last_packet: datetime | None = None
        self.position: PositionPacket | None = None
        self.telemetry: TelemetryPacket | None = None
        self.firmware: Firmware | None = None
        self.last_message: ReceivedMessage | None = None
        self.last_radio: tuple[int | None, float | None] = (None, None)
        self.messages_received = 0
        self.messages_sent = 0
        self.stations: OrderedDict[str, StationInfo] = OrderedDict()
        self._seen: OrderedDict[tuple[str, int], datetime] = OrderedDict()
        self.duplicates = 0
        self._telemetry_listeners: list[Callable[[], None]] = []

    # --- derived values -------------------------------------------------------

    @property
    def active(self) -> bool:
        """True if the node sent anything recently."""
        return (
            self.last_packet is not None
            and dt_util.utcnow() - self.last_packet < NODE_ACTIVE_TIMEOUT
        )

    def stations_heard(self, window: timedelta = STATIONS_WINDOW) -> int:
        """Number of distinct stations heard within ``window``."""
        limit = dt_util.utcnow() - window
        return sum(1 for station in self.stations.values() if station.last_heard >= limit)

    # --- packet handling ----------------------------------------------------

    def _is_duplicate(self, kind: str, msg_id: int) -> bool:
        now = dt_util.utcnow()
        while self._seen:
            key, seen = next(iter(self._seen.items()))
            if now - seen < DEDUP_WINDOW and len(self._seen) <= DEDUP_MAX_ENTRIES:
                break
            self._seen.pop(key)
        if (kind, msg_id) in self._seen:
            self.duplicates += 1
            return True
        self._seen[(kind, msg_id)] = now
        return False

    def _station(self, callsign: str, now: datetime) -> StationInfo:
        station = self.stations.pop(callsign, None) or StationInfo(callsign, now)
        station.last_heard = now
        self.stations[callsign] = station
        while len(self.stations) > MAX_STATIONS:
            self.stations.popitem(last=False)
        return station

    @callback
    def handle_packet(self, packet: Packet) -> None:
        """Update the state from one validated packet (runs in the event loop)."""
        now = dt_util.utcnow()
        self.last_packet = now
        if isinstance(packet, PositionPacket):
            self._handle_position(packet, now)
        elif isinstance(packet, TelemetryPacket):
            self._handle_telemetry(packet, now)
        elif isinstance(packet, TextMessagePacket):
            self._handle_message(packet, now)
        elif isinstance(packet, (AckMessagePacket, DeliveryStatusPacket)):
            self._handle_delivery(packet)
        elif isinstance(packet, (TimeBeaconPacket, RemoteManagementPacket)):
            # Control traffic, not chat. Only proves that the node is alive.
            pass
        async_dispatcher_send(self.hass, signal_update(self.entry_id))

    def _handle_position(self, packet: PositionPacket, now: datetime) -> None:
        if self._is_duplicate("pos", packet.msg_id.value):
            return
        if packet.source_type is SourceType.NODE:
            self.position = packet
            self.firmware = packet.firmware
            return
        if packet.radio.rssi is not None:
            self.last_radio = (packet.radio.rssi, packet.radio.snr)
        station = self._station(packet.path.originator, now)
        station.hops = packet.path.hops
        station.battery = packet.battery
        station.latitude = packet.latitude
        station.longitude = packet.longitude
        station.firmware = str(packet.firmware)
        if packet.source_type is SourceType.LORA:
            station.rssi = packet.radio.rssi
            station.snr = packet.radio.snr

    def _handle_telemetry(self, packet: TelemetryPacket, now: datetime) -> None:
        if packet.source_type is SourceType.NODE:
            had_data = self.telemetry is not None and self.telemetry.has_sensor_data
            self.telemetry = packet
            if packet.has_sensor_data and not had_data:
                for listener in list(self._telemetry_listeners):
                    listener()
            return
        self._station(packet.path.originator, now)

    def _handle_message(self, packet: TextMessagePacket, now: datetime) -> None:
        if self._is_duplicate("msg", packet.msg_id.value):
            return
        is_own = packet.source_type is SourceType.NODE
        # Direct messages between other stations are heard too. They are
        # passed on as events but do not count as messages for this node.
        to_me = (
            packet.destination_kind is not DestinationKind.DIRECT
            or packet.destination == self.callsign
        )
        if is_own:
            self.messages_sent += 1
        elif not to_me:
            self._station(packet.path.originator, now)
        else:
            self.messages_received += 1
            self.last_message = ReceivedMessage(
                sender=packet.path.originator,
                destination=packet.destination,
                destination_kind=packet.destination_kind,
                text=packet.text,
                received=now,
                via_server=packet.source_type is SourceType.UDP,
            )
            if packet.radio.rssi is not None:
                self.last_radio = (packet.radio.rssi, packet.radio.snr)
            self._station(packet.path.originator, now)
        # Message text is untrusted data. It is passed on as data only; never
        # use it as a command or template (security concept C-02, C-11).
        self.hass.bus.async_fire(
            EVENT_MESSAGE,
            {
                "entry_id": self.entry_id,
                "node": self.callsign,
                "sender": packet.path.originator,
                "path": list(packet.path.relays),
                "destination": packet.destination,
                "destination_kind": packet.destination_kind.value,
                "text": packet.text,
                "text_cleaned": packet.text_cleaned,
                "is_own": is_own,
                "to_me": to_me and not is_own,
                "via_server": packet.source_type is SourceType.UDP,
                "msg_id": str(packet.msg_id),
                "sequence": packet.sequence,
                "rssi": packet.radio.rssi,
                "snr": packet.radio.snr,
            },
        )

    def _handle_delivery(self, packet: AckMessagePacket | DeliveryStatusPacket) -> None:
        if isinstance(packet, AckMessagePacket):
            # Only acknowledgements addressed to this node count (C-13). Matching
            # them to open own messages follows with the send path.
            if packet.acknowledged_station != self.callsign:
                return
            data = {
                "entry_id": self.entry_id,
                "node": self.callsign,
                "from": packet.path.originator,
                "sequence": packet.sequence,
                "rejected": packet.rejected,
                "source": "text",
            }
        else:
            data = {
                "entry_id": self.entry_id,
                "node": self.callsign,
                "from": packet.from_station,
                "msg_id": str(packet.msg_id),
                "status": packet.status.name.lower(),
                "source": "node",
            }
        self.hass.bus.async_fire(EVENT_DELIVERY, data)

    @callback
    def add_telemetry_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call ``listener`` when the node starts reporting sensor data."""
        self._telemetry_listeners.append(listener)

        @callback
        def _remove() -> None:
            self._telemetry_listeners.remove(listener)

        return _remove
