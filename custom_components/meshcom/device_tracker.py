"""Position of the own MeshCom node."""

from __future__ import annotations

from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

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


def _coordinate(value: object, limit: float) -> float | None:
    """A restored coordinate, only if it is a plain number in range."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if -limit <= number <= limit else None


class MeshComTracker(MeshComEntity, TrackerEntity, RestoreEntity):
    """Position from the node's own beacon.

    The node sends its position only every few minutes; until the first one
    after a restart the last known position is kept, like the sensors do.
    """

    _attr_source_type = SourceType.GPS
    _restored: tuple[float, float] | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last position."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is None:
            return
        latitude = _coordinate(state.attributes.get("latitude"), 90)
        longitude = _coordinate(state.attributes.get("longitude"), 180)
        if latitude is not None and longitude is not None:
            self._restored = (latitude, longitude)

    @property
    def latitude(self) -> float | None:
        """Latitude of the last own beacon."""
        if self.node.position and self.node.position.latitude is not None:
            return self.node.position.latitude
        return self._restored[0] if self._restored else None

    @property
    def longitude(self) -> float | None:
        """Longitude of the last own beacon."""
        if self.node.position and self.node.position.longitude is not None:
            return self.node.position.longitude
        return self._restored[1] if self._restored else None

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
