"""Binary sensors of the own MeshCom node."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import MeshComConfigEntry
from .const import signal_new_station, signal_update
from .entity import MeshComEntity, MeshComStationEntity
from .kiss_link import KissLink
from .node import MeshComNode

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MeshComConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    runtime = entry.runtime_data
    entities: list[BinarySensorEntity] = [MeshComActiveSensor(runtime.node, "active")]
    if runtime.kiss is not None:
        entities.append(MeshComKissConnectedSensor(runtime.node, runtime.kiss))
    async_add_entities(entities)

    @callback
    def _add_station(callsign: str) -> None:
        async_add_entities([MeshComStationDirectSensor(runtime.node, callsign)])

    for callsign in sorted(runtime.stations.tracked):
        _add_station(callsign)
    entry.async_on_unload(
        async_dispatcher_connect(hass, signal_new_station(entry.entry_id), _add_station)
    )


class MeshComActiveSensor(MeshComEntity, BinarySensorEntity):
    """On while the node sends packets. A mobile node away from home is off, not an error."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        """True if a packet arrived recently."""
        return self.node.active


class MeshComKissConnectedSensor(MeshComEntity, BinarySensorEntity):
    """On while the KISS connection to the node is open."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, node: MeshComNode, link: KissLink) -> None:
        super().__init__(node, "kiss_connected")
        self._link = link

    @property
    def is_on(self) -> bool:
        """True while connected."""
        return self._link.connected


class MeshComStationDirectSensor(MeshComStationEntity, BinarySensorEntity):
    """On while the own node hears the station directly (its MHeard list)."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, node: MeshComNode, callsign: str) -> None:
        super().__init__(node, callsign, "station_direct")

    @property
    def is_on(self) -> bool | None:
        """True while the station is on the node's MHeard list."""
        station = self.station
        return station.is_direct(dt_util.utcnow()) if station else None

    async def async_added_to_hass(self) -> None:
        """Also refresh every minute: direct reception ends by time."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_update(self.node.entry_id), self._handle_update
            )
        )
