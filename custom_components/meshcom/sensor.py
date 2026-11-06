"""Sensors of the own MeshCom node."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

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
    UnitOfLength,
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MeshComConfigEntry
from .entity import MeshComEntity
from .node import MeshComNode

# One update at a time is plenty: values come from pushed packets.
PARALLEL_UPDATES = 0

type StateValue = str | int | float | datetime | None


@dataclass(frozen=True, kw_only=True)
class MeshComSensorDescription(SensorEntityDescription):
    """Describes a MeshCom sensor."""

    value_fn: Callable[[MeshComNode], StateValue]
    #: Keep the last value over a Home Assistant restart (beacons come every 30 min).
    restore: bool = False


def _last_message_value(node: MeshComNode) -> str | None:
    # A state is limited to 255 characters; MeshCom texts are shorter (150 B).
    return node.last_message.text[:255] if node.last_message else None


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
    ),
    MeshComSensorDescription(
        key="last_sender",
        value_fn=lambda node: node.last_message.sender if node.last_message else None,
    ),
    MeshComSensorDescription(
        key="last_message_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda node: node.last_message.received if node.last_message else None,
    ),
    MeshComSensorDescription(
        key="messages_received",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda node: node.messages_received,
    ),
    MeshComSensorDescription(
        key="messages_sent",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda node: node.messages_sent,
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
    ),
    MeshComSensorDescription(
        key="last_snr",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda node: node.last_radio[1],
    ),
    MeshComSensorDescription(
        key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda node: str(node.firmware) if node.firmware else None,
        restore=True,
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MeshComConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    node = entry.runtime_data.node
    async_add_entities(MeshComSensor(node, description) for description in NODE_SENSORS)

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
        if self.entity_description.restore and (data := await self.async_get_last_sensor_data()):
            self._restored = data.native_value  # type: ignore[assignment]

    @property
    def native_value(self) -> StateValue:
        """Current value, or the restored one until the first packet."""
        value = self.entity_description.value_fn(self.node)
        return self._restored if value is None else value
