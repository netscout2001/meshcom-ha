"""Position of the own MeshCom node."""

from __future__ import annotations

from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MeshComConfigEntry
from .entity import MeshComEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MeshComConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the tracker."""
    async_add_entities([MeshComTracker(entry.runtime_data.node, "position")])


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
