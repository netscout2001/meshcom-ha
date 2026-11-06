"""Binary sensors of the own MeshCom node."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MeshComConfigEntry
from .entity import MeshComEntity
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
