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
    MAX_PENDING_ACKS,
    MAX_STATIONS,
    NODE_ACTIVE_TIMEOUT,
    PENDING_ACK_TIMEOUT,
    STATIONS_WINDOW,
    signal_station,
    signal_update,
)


@dataclass(slots=True)
class StationInfo:
    """What we know about a heard station."""

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
        #: Read from the node's web page: firmware (KISS frames carry none)
        #: and battery voltage (packets carry only the percentage).
        self.web_firmware: str | None = None
        self.battery_voltage: float | None = None
        self.last_message: ReceivedMessage | None = None
        self.last_radio: tuple[int | None, float | None] = (None, None)
        self.messages_received = 0
        self.messages_sent = 0
        self.stations: OrderedDict[str, StationInfo] = OrderedDict()
        #: Called with the callsign whenever a station was heard.
        self.station_listener: Callable[[str], None] | None = None
        #: Chat history hooks: (packet, own, time) and (msg id, status).
        self.message_listener: Callable[[TextMessagePacket, bool, datetime], None] | None = None
        self.delivery_listener: Callable[[str, str], None] | None = None
        self._touched: str | None = None
        self._seen: OrderedDict[tuple[str, int], datetime] = OrderedDict()
        self.duplicates = 0
        self._telemetry_listeners: list[Callable[[], None]] = []
        # Sending
        self.sending_enabled = True
        self.compose_kind = DestinationKind.BROADCAST
        self.compose_group: str | None = None
        self.compose_station: str | None = None
        self.compose_text = ""
        #: Own direct messages waiting for an acknowledgement:
        #: (destination, sequence) -> (message id, sent at).
        self._pending: OrderedDict[tuple[str, int], tuple[str, datetime]] = OrderedDict()
        #: Ids of own messages, for the node's own delivery-status datagrams.
        self._own_ids: OrderedDict[int, datetime] = OrderedDict()
        # Filter, coupled to the node's "No MSG All" switch (read via web API)
        self.filter_active = False
        self.node_groups: list[str] = []
        self.messages_filtered = 0

    # --- derived values -------------------------------------------------------

    @property
    def active(self) -> bool:
        """True if the node sent anything recently."""
        return (
            self.last_packet is not None
            and dt_util.utcnow() - self.last_packet < NODE_ACTIVE_TIMEOUT
        )

    def restore_stations(self, stations: list[StationInfo]) -> None:
        """Take over stations stored before a restart (oldest first)."""
        for station in sorted(stations, key=lambda item: item.last_heard):
            if station.callsign not in self.stations:
                self.stations[station.callsign] = station
        while len(self.stations) > MAX_STATIONS:
            self.stations.popitem(last=False)

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
        self._touched = callsign
        while len(self.stations) > MAX_STATIONS:
            self.stations.popitem(last=False)
        return station

    @callback
    def handle_packet(self, packet: Packet) -> None:
        """Update the state from one validated packet (runs in the event loop)."""
        now = dt_util.utcnow()
        self.last_packet = now
        self._touched = None
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
        if (callsign := self._touched) is not None:
            async_dispatcher_send(self.hass, signal_station(self.entry_id, callsign))
            if self.station_listener is not None:
                self.station_listener(callsign)

    def _handle_position(self, packet: PositionPacket, now: datetime) -> None:
        if self._is_duplicate("pos", packet.msg_id.value):
            return
        if packet.source_type is SourceType.NODE:
            self.position = packet
            # KISS frames carry no firmware version; keep what is known.
            if packet.firmware.minor is not None:
                self.firmware = packet.firmware
            return
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

    def _heard_message(self, packet: TextMessagePacket, now: datetime) -> None:
        """A message also tells hops and signal of its sender."""
        station = self._station(packet.path.originator, now)
        station.hops = packet.path.hops
        if packet.source_type is SourceType.LORA and packet.radio.rssi is not None:
            station.rssi = packet.radio.rssi
            station.snr = packet.radio.snr

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
            self._track_own(packet, now)
        elif not to_me:
            self._heard_message(packet, now)
        elif self.is_filtered(packet):
            # Filtered: the station is still known, but no message, no event.
            self.messages_filtered += 1
            self._heard_message(packet, now)
            return
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
            # Signal of this message; unknown if it came via the server.
            self.last_radio = (packet.radio.rssi, packet.radio.snr)
            self._heard_message(packet, now)
        if (is_own or to_me) and self.message_listener is not None:
            self.message_listener(packet, is_own, now)
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

    def _track_own(self, packet: TextMessagePacket, now: datetime) -> None:
        """Remember own messages so acknowledgements can be matched (C-13)."""
        self._own_ids[packet.msg_id.value] = now
        if packet.destination_kind is DestinationKind.DIRECT and packet.sequence is not None:
            self._pending[(packet.destination, packet.sequence)] = (str(packet.msg_id), now)
        limit = now - PENDING_ACK_TIMEOUT
        while self._pending and (
            len(self._pending) > MAX_PENDING_ACKS or next(iter(self._pending.values()))[1] < limit
        ):
            self._pending.popitem(last=False)
        while self._own_ids and (
            len(self._own_ids) > MAX_PENDING_ACKS or next(iter(self._own_ids.values())) < limit
        ):
            self._own_ids.popitem(last=False)

    def _handle_delivery(self, packet: AckMessagePacket | DeliveryStatusPacket) -> None:
        """Fire a delivery event only for an open own message (C-13).

        Any station can send an acknowledgement text, so it counts only if it
        is addressed to this node, comes from the station the message went to
        and carries the sequence number of a message still waiting.
        """
        if isinstance(packet, AckMessagePacket):
            if packet.acknowledged_station != self.callsign:
                return
            pending = self._pending.pop((packet.path.originator, packet.sequence), None)
            if pending is None:
                return
            data: dict[str, object] = {
                "entry_id": self.entry_id,
                "node": self.callsign,
                "msg_id": pending[0],
                "from": packet.path.originator,
                "sequence": packet.sequence,
                "status": "rejected" if packet.rejected else "delivered",
                "source": "text",
            }
        else:
            if packet.msg_id.value not in self._own_ids:
                return
            data = {
                "entry_id": self.entry_id,
                "node": self.callsign,
                "msg_id": str(packet.msg_id),
                "from": packet.from_station,
                "status": packet.status.name.lower(),
                "source": "node",
            }
        self.hass.bus.async_fire(EVENT_DELIVERY, data)
        if self.delivery_listener is not None:
            self.delivery_listener(str(data["msg_id"]), str(data["status"]))

    @callback
    def apply_web_settings(
        self,
        *,
        no_msg_all: bool,
        groups: list[str],
        firmware: str | None = None,
        battery_voltage: float | None = None,
    ) -> None:
        """Take over the node's settings read via the web API."""
        changed = (
            no_msg_all != self.filter_active
            or groups != self.node_groups
            or firmware != self.web_firmware
            or battery_voltage != self.battery_voltage
        )
        self.filter_active = no_msg_all
        self.node_groups = list(groups)
        self.web_firmware = firmware
        self.battery_voltage = battery_voltage
        if changed:
            # The group select offers the node's groups.
            async_dispatcher_send(self.hass, signal_update(self.entry_id))

    def is_filtered(self, packet: TextMessagePacket) -> bool:
        """With "No MSG All" on the node, show only the node's groups and own DMs.

        Like the node's own display: messages to all (*), to foreign groups
        and to other addressees are hidden. Direct messages are handled by
        the "to_me" rule.
        """
        if not self.filter_active:
            return False
        kind = packet.destination_kind
        if kind is DestinationKind.GROUP:
            return packet.destination not in self.node_groups
        return kind is not DestinationKind.DIRECT

    @callback
    def add_telemetry_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call ``listener`` when the node starts reporting sensor data."""
        self._telemetry_listeners.append(listener)

        @callback
        def _remove() -> None:
            self._telemetry_listeners.remove(listener)

        return _remove
