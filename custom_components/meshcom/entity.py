"""Base entity for MeshCom."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, signal_update
from .node import MeshComNode


def node_device_info(node: MeshComNode) -> DeviceInfo:
    """Device of the own node. Identified by the node id, not by callsign or IP."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{node.node_id:06x}")},
        name=f"MeshCom {node.callsign}",
        manufacturer="MeshCom",
        model="MeshCom node",
        sw_version=str(node.firmware) if node.firmware else None,
    )


class MeshComEntity(Entity):
    """An entity of the own node, updated by dispatcher signal."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, node: MeshComNode, key: str) -> None:
        self.node = node
        self._attr_unique_id = f"{node.node_id:06x}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = node_device_info(node)

    async def async_added_to_hass(self) -> None:
        """Subscribe to node updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_update(self.node.entry_id), self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
