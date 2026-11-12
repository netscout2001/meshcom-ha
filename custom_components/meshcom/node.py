"""Runtime state of one MeshCom node (one config entry)."""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
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
from .aiomeshcom.webapi import MHeardEntry
from .const import (
    DEDUP_MAX_ENTRIES,
    DEDUP_WINDOW,
    DIRECT_WINDOW,
    EVENT_DELIVERY,
    EVENT_MESSAGE,
    EVENT_NEIGHBOUR_BACK,
    EVENT_NEIGHBOUR_LOST,
    EVENT_STATION_NEW,
    MAX_PATH,
    MAX_PENDING_ACKS,
    MAX_STATIONS,
    MHEARD_FRESH,
    NODE_ACTIVE_TIMEOUT,
    PENDING_ACK_TIMEOUT,
    STATION_NEW_BURST,
    STATION_NEW_INTERVAL,
    STATIONS_WINDOW,
    signal_station,
    signal_station_weather,
    signal_update,
)

_LOGGER = logging.getLogger(__name__)


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
    #: Weather values from the station's telemetry (None if it sends none).
    temperature: float | None = None
    humidity: float | None = None
    #: Air pressure: QNH (sea level) and QFE (at the station).
    pressure_qnh: float | None = None
    pressure_qfe: float | None = None
    weather_time: datetime | None = None
    #: Relays of the station's last packet, in order (empty: heard directly).
    path: list[str] = field(default_factory=list)
    # From the node's MHeard list (web API): the station is a direct neighbour.
    #: When the node last received the station directly.
    direct_heard: datetime | None = None
    hardware: str | None = None
    altitude: int | None = None
    #: SNR at which the station reports to hear the node; None: not reported.
    hears_me_snr: int | None = None
    #: "super", "needed" or "redundant".
    relay_role: str | None = None
    only_it_hears: int | None = None
    it_hears: int | None = None
    neighbours: int | None = None
    gateway: bool | None = None
    #: Direct neighbour not heard directly for the set time. None: not yet
    #: judged (stored before this existed); judged silently the first time.
    lost: bool | None = None

    def is_direct(self, now: datetime) -> bool:
        """True while the node's MHeard list has the station (heard directly)."""
        return self.direct_heard is not None and now - self.direct_heard < DIRECT_WINDOW


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

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        callsign: str,
        node_id: int,
        *,
        active_timeout: timedelta = NODE_ACTIVE_TIMEOUT,
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.callsign = callsign
        self.node_id = node_id
        self.last_packet: datetime | None = None
        #: "Active" turns off after this time without packets (option).
        self.active_timeout = active_timeout
        #: A direct neighbour is lost after this time (None: not watched).
        self.neighbour_lost_after: timedelta | None = None
        #: When the MHeard list was last read.
        self.mheard_read: datetime | None = None
        #: Budget of "station new" events (token bucket) and dropped events.
        self._new_tokens = float(STATION_NEW_BURST)
        self._new_refilled: datetime | None = None
        self.station_new_dropped = 0
        self.position: PositionPacket | None = None
        self.telemetry: TelemetryPacket | None = None
        self.firmware: Firmware | None = None
        #: Read from the node's web page: firmware (KISS frames carry none)
        #: and battery voltage (packets carry only the percentage).
        self.web_firmware: str | None = None
        self.battery_voltage: float | None = None
        self.last_message: ReceivedMessage | None = None
        #: RSSI and SNR of the last packet received over the air.
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
            and dt_util.utcnow() - self.last_packet < self.active_timeout
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
        station = self.stations.pop(callsign, None)
        if station is None:
            station = StationInfo(callsign, now)
            self._fire_station_new(callsign, now)
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
        # Signal of the last packet the node received over the air (message,
        # position or telemetry of another station). Own frames and packets
        # from the MeshCom server carry none and leave the value as it is.
        radio = getattr(packet, "radio", None)
        source = getattr(packet, "source_type", None)
        if source is SourceType.LORA and radio is not None and radio.rssi is not None:
            self.last_radio = (radio.rssi, radio.snr)
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
        station.path = list(packet.path.relays[:MAX_PATH])
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
        station = self._station(packet.path.originator, now)
        station.path = list(packet.path.relays[:MAX_PATH])
        if not packet.has_sensor_data:
            return
        first = station.weather_time is None
        station.temperature = packet.temperature_1
        station.humidity = packet.humidity
        station.pressure_qnh = packet.pressure_qnh
        station.pressure_qfe = packet.pressure_qfe
        station.weather_time = now
        if first:
            async_dispatcher_send(
                self.hass, signal_station_weather(self.entry_id), station.callsign
            )

    def _heard_message(self, packet: TextMessagePacket, now: datetime) -> None:
        """A message also tells hops and signal of its sender."""
        station = self._station(packet.path.originator, now)
        station.hops = packet.path.hops
        station.path = list(packet.path.relays[:MAX_PATH])
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

    def apply_mheard(self, entries: list[MHeardEntry]) -> None:
        """Take over the stations the node heard directly (its MHeard list).

        Adds stations that send only heartbeats (UDP and KISS do not carry
        those) and the neighbour values. Values from packets win where both
        exist: positions are more precise there, signal values belong to the
        last packet.
        """
        now = dt_util.utcnow()
        self.mheard_read = now
        changed: list[str] = []
        for entry in entries:
            if entry.callsign == self.callsign:
                continue
            heard = now - timedelta(minutes=entry.age_minutes)
            station = self.stations.get(entry.callsign)
            before = None if station is None else _neighbour_values(station)
            if station is None:
                station = StationInfo(entry.callsign, heard, lost=False)
                self.stations[entry.callsign] = station
                self._fire_station_new(entry.callsign, heard)
            elif heard > station.last_heard + timedelta(minutes=1):
                station.last_heard = heard
                self.stations.move_to_end(entry.callsign)
            _take_mheard(station, entry, heard)
            self._judge_back(station, now)
            if _neighbour_values(station) != before:
                changed.append(entry.callsign)
        while len(self.stations) > MAX_STATIONS:
            self.stations.popitem(last=False)
        if not changed:
            return
        async_dispatcher_send(self.hass, signal_update(self.entry_id))
        for callsign in changed:
            if callsign not in self.stations:
                continue
            async_dispatcher_send(self.hass, signal_station(self.entry_id, callsign))
            if self.station_listener is not None:
                self.station_listener(callsign)

    def _fire_station_new(self, callsign: str, heard: datetime) -> None:
        now = dt_util.utcnow()
        if self._new_refilled is not None:
            refill = (now - self._new_refilled) / STATION_NEW_INTERVAL
            self._new_tokens = min(float(STATION_NEW_BURST), self._new_tokens + refill)
        self._new_refilled = now
        if self._new_tokens < 1:
            if self.station_new_dropped == 0:
                _LOGGER.warning(
                    "%s: many new stations at once; further 'station new' events are "
                    "limited (spoofed datagrams?)",
                    self.callsign,
                )
            self.station_new_dropped += 1
            return
        self._new_tokens -= 1
        self.hass.bus.async_fire(
            EVENT_STATION_NEW,
            {
                "entry_id": self.entry_id,
                "node": self.callsign,
                "callsign": callsign,
                "heard": heard.isoformat(),
            },
        )

    def _fire_neighbour(self, event: str, station: StationInfo) -> None:
        self.hass.bus.async_fire(
            event,
            {
                "entry_id": self.entry_id,
                "node": self.callsign,
                "callsign": station.callsign,
                "direct_heard": station.direct_heard.isoformat() if station.direct_heard else None,
                "rssi": station.rssi,
                "snr": station.snr,
            },
        )

    def _judge_back(self, station: StationInfo, now: datetime) -> None:
        """A lost neighbour heard directly again is back."""
        lost_after = self.neighbour_lost_after
        if (
            lost_after is None
            or station.direct_heard is None
            or now - station.direct_heard >= lost_after
        ):
            return
        if station.lost is True:
            self._fire_neighbour(EVENT_NEIGHBOUR_BACK, station)
        station.lost = False

    @callback
    def check_neighbours(self, now: datetime | None = None) -> bool:
        """Mark direct neighbours lost; True if anything changed (to be stored).

        Only judged while the MHeard list is fresh: a node that is away (or
        whose web access fails) would otherwise lose all its neighbours.
        """
        lost_after = self.neighbour_lost_after
        now = now or dt_util.utcnow()
        if lost_after is None or self.mheard_read is None or now - self.mheard_read > MHEARD_FRESH:
            return False
        changed = False
        for station in list(self.stations.values()):
            if station.direct_heard is None or station.lost is True:
                continue
            gone = now - station.direct_heard >= lost_after
            if station.lost is None:
                station.lost = gone  # first judgement: no event for old stations
                changed = True
            elif gone:
                station.lost = True
                changed = True
                self._fire_neighbour(EVENT_NEIGHBOUR_LOST, station)
        return changed

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


def _neighbour_values(station: StationInfo) -> tuple[object, ...]:
    """Everything apply_mheard may change, to notify only on a change."""
    return (
        station.last_heard,
        station.direct_heard,
        station.hardware,
        station.altitude,
        station.hears_me_snr,
        station.relay_role,
        station.only_it_hears,
        station.it_hears,
        station.neighbours,
        station.gateway,
        station.latitude,
        station.longitude,
        station.rssi,
        station.snr,
        station.firmware,
        station.lost,
    )


def _take_mheard(station: StationInfo, entry: MHeardEntry, heard: datetime) -> None:
    """Copy one MHeard entry into a station (packet values win where both exist)."""
    # The age has minute resolution: keep the time unless it moved.
    if station.direct_heard is None or abs(heard - station.direct_heard) > timedelta(seconds=90):
        station.direct_heard = heard
    station.hardware = entry.hardware
    station.altitude = entry.altitude
    station.hears_me_snr = entry.hears_me_snr
    station.relay_role = entry.relay_role
    station.only_it_hears = entry.only_it_hears
    station.it_hears = entry.it_hears
    station.neighbours = entry.neighbours
    station.gateway = entry.gateway
    if station.latitude is None and entry.latitude is not None:
        station.latitude = entry.latitude
        station.longitude = entry.longitude
    if station.rssi is None and entry.rssi is not None:
        station.rssi = entry.rssi
        station.snr = None if entry.snr is None else float(entry.snr)
    if station.firmware is None and entry.firmware is not None:
        station.firmware = entry.firmware
