"""Position of the own MeshCom node."""

from __future__ import annotations

from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MeshComConfigEntry
from .const import signal_new_station
from .entity import MeshComEntity, MeshComStationEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MeshComConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the trackers."""
    node = entry.runtime_data.node
    async_add_entities([MeshComTracker(node, "position")])

    @callback
    def _add_station(callsign: str) -> None:
        async_add_entities([MeshComStationTracker(node, callsign, "station_position")])

    for callsign in sorted(entry.runtime_data.stations.tracked):
        _add_station(callsign)
    entry.async_on_unload(
        async_dispatcher_connect(hass, signal_new_station(entry.entry_id), _add_station)
    )


class MeshComTracker(MeshComEntity, TrackerEntity):
    """Position from the node's own beacon."""

    _attr_source_type = SourceType.GPS

    @property
    def latitude(self) -> float | None:
        """Latitude of the last own beacon."""
        return self.node.position.latitude if self.node.position else None

    @property
    def longitude(self) -> float | None:
        """Longitude of the last own beacon."""
        return self.node.position.longitude if self.node.position else None

    @property
    def location_accuracy(self) -> float:
        """MeshCom transmits positions with four decimal places (about 10 m)."""
        return 10


class MeshComStationTracker(MeshComStationEntity, TrackerEntity):
    """Position from a heard station's beacon."""

    _attr_source_type = SourceType.GPS

    @property
    def latitude(self) -> float | None:
        """Latitude of the station's last beacon."""
        return self.station.latitude if self.station else None

    @property
    def longitude(self) -> float | None:
        """Longitude of the station's last beacon."""
        return self.station.longitude if self.station else None

    @property
    def location_accuracy(self) -> float:
        """Four decimal places, about 10 m."""
        return 10
