"""Sensors of the own MeshCom node."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import MeshComConfigEntry
from .aiomeshcom.webpages import RadioStats
from .const import (
    STATION_ATTRIBUTE_LIMIT,
    STATION_MODE_DATA,
    signal_new_station,
    signal_station_weather,
    signal_update,
)
from .coordinator import MeshComWebCoordinator
from .entity import MeshComEntity, MeshComStationEntity, node_device_info
from .node import MeshComNode, StationInfo
from .stations import station_mode

# One update at a time is plenty: values come from pushed packets.
PARALLEL_UPDATES = 0

type StateValue = str | int | float | datetime | None


@dataclass(frozen=True, kw_only=True)
class MeshComSensorDescription(SensorEntityDescription):
    """Describes a MeshCom sensor."""

    value_fn: Callable[[MeshComNode], StateValue]
    #: Keep the last value over a Home Assistant restart (beacons come every 30 min).
    restore: bool = False
    #: Restored value belongs to the last message: shown until the next one.
    message_bound: bool = False
    #: Counter attribute of the node that continues from the restored value.
    counter: str | None = None
    #: Hands a restored value back to the node (e.g. the time of its last packet).
    seed_fn: Callable[[MeshComNode, StateValue], bool] | None = None


def _last_message_value(node: MeshComNode) -> str | None:
    # A state is limited to 255 characters; MeshCom texts are shorter (150 B).
    return node.last_message.text[:255] if node.last_message else None


def _seed_last_packet(node: MeshComNode, value: StateValue) -> bool:
    """Restore the time of the node's last packet, so "Active" survives a restart."""
    if node.last_packet is None and isinstance(value, datetime):
        node.last_packet = value
        return True
    return False


NODE_SENSORS: tuple[MeshComSensorDescription, ...] = (
    MeshComSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda node: node.position.battery if node.position else None,
        restore=True,
    ),
    MeshComSensorDescription(
        key="altitude",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda node: node.position.altitude_m if node.position else None,
        restore=True,
    ),
    MeshComSensorDescription(
        key="last_message",
        value_fn=_last_message_value,
        restore=True,
        message_bound=True,
    ),
    MeshComSensorDescription(
        key="last_sender",
        value_fn=lambda node: node.last_message.sender if node.last_message else None,
        restore=True,
        message_bound=True,
    ),
    MeshComSensorDescription(
        key="last_message_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda node: node.last_message.received if node.last_message else None,
        restore=True,
        message_bound=True,
    ),
    MeshComSensorDescription(
        key="messages_received",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda node: node.messages_received,
        counter="messages_received",
    ),
    MeshComSensorDescription(
        key="messages_sent",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda node: node.messages_sent,
        counter="messages_sent",
    ),
    MeshComSensorDescription(
        key="stations_heard",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda node: node.stations_heard(),
    ),
    MeshComSensorDescription(
        key="last_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda node: node.last_radio[0],
        restore=True,
    ),
    MeshComSensorDescription(
        key="last_snr",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda node: node.last_radio[1],
        restore=True,
    ),
    MeshComSensorDescription(
        key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        # Packets carry it on UDP; for KISS it comes from the web page.
        value_fn=lambda node: str(node.firmware) if node.firmware else node.web_firmware,
        restore=True,
    ),
    MeshComSensorDescription(
        key="last_packet",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda node: node.last_packet,
        restore=True,
        seed_fn=_seed_last_packet,
    ),
    MeshComSensorDescription(
        key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda node: node.battery_voltage,
        restore=True,
    ),
)


@dataclass(frozen=True, kw_only=True)
class MeshComStationSensorDescription(SensorEntityDescription):
    """Describes a sensor of a heard station."""

    value_fn: Callable[[StationInfo], StateValue]


STATION_SENSORS: tuple[MeshComStationSensorDescription, ...] = (
    MeshComStationSensorDescription(
        key="station_last_heard",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda station: station.last_heard,
    ),
    MeshComStationSensorDescription(
        key="station_battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda station: station.battery or None,
    ),
    MeshComStationSensorDescription(
        key="station_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda station: station.rssi,
    ),
    MeshComStationSensorDescription(
        key="station_snr",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda station: station.snr,
    ),
    MeshComStationSensorDescription(
        key="station_hops",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda station: station.hops,
    ),
)

TELEMETRY_SENSORS: tuple[MeshComSensorDescription, ...] = (
    MeshComSensorDescription(
        key="temperature_1",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda node: node.telemetry.temperature_1 if node.telemetry else None,
    ),
    MeshComSensorDescription(
        key="temperature_2",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda node: node.telemetry.temperature_2 if node.telemetry else None,
    ),
    MeshComSensorDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda node: node.telemetry.humidity if node.telemetry else None,
    ),
    MeshComSensorDescription(
        key="pressure_qfe",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda node: node.telemetry.pressure_qfe if node.telemetry else None,
    ),
    MeshComSensorDescription(
        key="pressure_qnh",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda node: node.telemetry.pressure_qnh if node.telemetry else None,
    ),
    MeshComSensorDescription(
        key="co2",
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement="ppm",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda node: node.telemetry.co2 if node.telemetry else None,
    ),
)


STATION_WEATHER_SENSORS: tuple[MeshComStationSensorDescription, ...] = (
    MeshComStationSensorDescription(
        key="station_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda station: station.temperature,
    ),
    MeshComStationSensorDescription(
        key="station_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda station: station.humidity,
    ),
    MeshComStationSensorDescription(
        key="station_pressure",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda station: station.pressure_qnh,
    ),
)


@dataclass(frozen=True, kw_only=True)
class MeshComRadioSensorDescription(SensorEntityDescription):
    """Describes a value of the node's LoRa queue panel (web API)."""

    value_fn: Callable[[RadioStats], StateValue]
    attributes_fn: Callable[[RadioStats], dict[str, Any]] | None = None


def _queue_attributes(radio: RadioStats) -> dict[str, Any]:
    return {
        "size": radio.queue_size,
        **radio.queue_by_priority,
        "waiting_for_ack": radio.waiting_ack,
        "slow_down_at": radio.slow_down_at,
        "refuse_at": radio.refuse_at,
        "own_messages": radio.state,
    }


#: Only with the option "Read radio statistics"; values of the last 5 minutes.
RADIO_SENSORS: tuple[MeshComRadioSensorDescription, ...] = (
    MeshComRadioSensorDescription(
        key="channel_rx",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda radio: radio.rx_percent,
    ),
    MeshComRadioSensorDescription(
        key="channel_tx",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda radio: radio.tx_percent,
    ),
    MeshComRadioSensorDescription(
        key="tx_queue",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda radio: radio.queue_used,
        attributes_fn=_queue_attributes,
    ),
)


class MeshComRadioSensor(CoordinatorEntity[MeshComWebCoordinator], SensorEntity):
    """Channel use or queue level of the own node, from its RX log page."""

    _attr_has_entity_name = True
    entity_description: MeshComRadioSensorDescription

    def __init__(
        self,
        coordinator: MeshComWebCoordinator,
        node: MeshComNode,
        description: MeshComRadioSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._attr_unique_id = f"{node.node_id:06x}_{description.key}"
        self._attr_device_info = node_device_info(node)

    @property
    def _radio(self) -> RadioStats | None:
        data = self.coordinator.data
        return data.radio if data is not None else None

    @property
    def available(self) -> bool:
        """Unavailable while the node's queue panel cannot be read."""
        return super().available and self._radio is not None

    @property
    def native_value(self) -> StateValue:
        """Value of the last completed 5-minute window."""
        radio = self._radio
        return self.entity_description.value_fn(radio) if radio is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Queue details (tx_queue only)."""
        radio = self._radio
        if radio is None or self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(radio)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MeshComConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    node = entry.runtime_data.node
    with_list = station_mode(entry) == STATION_MODE_DATA
    async_add_entities(
        MeshComStationsHeardSensor(node, description, with_list=with_list)
        if description.key == "stations_heard"
        else MeshComSensor(node, description)
        for description in NODE_SENSORS
    )

    if entry.runtime_data.web.radio_stats:
        async_add_entities(
            MeshComRadioSensor(entry.runtime_data.web, node, description)
            for description in RADIO_SENSORS
        )

    @callback
    def _add_station(callsign: str) -> None:
        station = node.stations.get(callsign)
        # Weather sensors only for stations that send weather values.
        weather = STATION_WEATHER_SENSORS if station and station.weather_time else ()
        async_add_entities(
            MeshComStationSensor(node, callsign, description)
            for description in (*STATION_SENSORS, *weather)
        )

    @callback
    def _add_weather(callsign: str) -> None:
        # Only stations with a device get sensors; others get them with their device.
        if callsign in entry.runtime_data.stations.tracked:
            async_add_entities(
                MeshComStationSensor(node, callsign, description)
                for description in STATION_WEATHER_SENSORS
            )

    for callsign in sorted(entry.runtime_data.stations.tracked):
        _add_station(callsign)
    entry.async_on_unload(
        async_dispatcher_connect(hass, signal_new_station(entry.entry_id), _add_station)
    )
    entry.async_on_unload(
        async_dispatcher_connect(hass, signal_station_weather(entry.entry_id), _add_weather)
    )

    # Sensor entities only for nodes that actually report sensor values.
    added = False

    @callback
    def _add_telemetry() -> None:
        nonlocal added
        if not added:
            added = True
            async_add_entities(
                MeshComSensor(node, description) for description in TELEMETRY_SENSORS
            )

    if node.telemetry is not None and node.telemetry.has_sensor_data:
        _add_telemetry()
    else:
        entry.async_on_unload(node.add_telemetry_listener(_add_telemetry))


class MeshComSensor(MeshComEntity, RestoreSensor, SensorEntity):
    """A sensor of the own node."""

    entity_description: MeshComSensorDescription

    def __init__(self, node: MeshComNode, description: MeshComSensorDescription) -> None:
        super().__init__(node, description.key)
        self.entity_description = description
        self._restored: StateValue = None

    async def async_added_to_hass(self) -> None:
        """Restore the last value where useful."""
        await super().async_added_to_hass()
        description = self.entity_description
        if not (description.restore or description.counter):
            return
        if (data := await self.async_get_last_sensor_data()) is None:
            return
        if description.counter is not None:
            # Counters continue over a restart instead of starting at 0.
            value = data.native_value
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and 0 <= value < 2**31
            ):
                current = getattr(self.node, description.counter)
                setattr(self.node, description.counter, current + int(value))
            return
        self._restored = data.native_value  # type: ignore[assignment]
        if description.seed_fn is not None and description.seed_fn(self.node, self._restored):
            # Other entities (e.g. "Active") depend on the restored value.
            async_dispatcher_send(self.hass, signal_update(self.node.entry_id))

    @property
    def native_value(self) -> StateValue:
        """Current value, or the restored one until the first packet."""
        if self.entity_description.message_bound:
            # All values of the last message belong together: the restored
            # ones are shown until the next message, then only new ones.
            if self.node.last_message is not None:
                return self.entity_description.value_fn(self.node)
            return self._restored
        value = self.entity_description.value_fn(self.node)
        return self._restored if value is None else value


class MeshComStationsHeardSensor(MeshComSensor):
    """Stations heard in 24 h; in "data" mode with the station list as attribute."""

    # The list changes with every packet; keep it out of the database.
    _unrecorded_attributes = frozenset({"stations"})

    def __init__(
        self, node: MeshComNode, description: MeshComSensorDescription, *, with_list: bool
    ) -> None:
        super().__init__(node, description)
        self._with_list = with_list

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The most recently heard stations, newest first."""
        if not self._with_list:
            return None
        stations = list(self.node.stations.values())[-STATION_ATTRIBUTE_LIMIT:]
        now = dt_util.utcnow()
        return {
            "stations": [
                {
                    "callsign": station.callsign,
                    "last_heard": station.last_heard.isoformat(),
                    "rssi": station.rssi,
                    "snr": station.snr,
                    "hops": station.hops,
                    "battery": station.battery or None,
                    "latitude": station.latitude,
                    "longitude": station.longitude,
                    "direct": station.is_direct(now),
                }
                for station in reversed(stations)
            ]
        }


class MeshComStationSensor(MeshComStationEntity, SensorEntity):
    """A sensor of a heard station."""

    entity_description: MeshComStationSensorDescription

    def __init__(
        self, node: MeshComNode, callsign: str, description: MeshComStationSensorDescription
    ) -> None:
        super().__init__(node, callsign, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateValue:
        """Value from the station's last packet."""
        station = self.station
        return self.entity_description.value_fn(station) if station else None
