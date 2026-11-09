"""Kill switch for transmitting from Home Assistant."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MeshComConfigEntry
from .coordinator import MeshComWebCoordinator
from .entity import MeshComEntity, async_require_admin, node_device_info
from .node import MeshComNode

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MeshComConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switch."""
    runtime = entry.runtime_data
    async_add_entities(
        [
            MeshComSendingSwitch(runtime.node, "sending_enabled"),
            MeshComNoMsgAllSwitch(runtime.web, runtime.node, entry.entry_id),
        ]
    )


class MeshComSendingSwitch(MeshComEntity, SwitchEntity, RestoreEntity):
    """When off, Home Assistant does not transmit through this node at all."""

    _attr_entity_category = EntityCategory.CONFIG

    async def async_added_to_hass(self) -> None:
        """Restore the last state; a switched-off node stays off after a restart."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None:
            self.node.sending_enabled = state.state != STATE_OFF

    @property
    def is_on(self) -> bool:
        """True if sending is allowed."""
        return self.node.sending_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Allow sending again. Reserved for administrators.

        Switching off stays open to everyone: stopping transmissions is always safe.
        """
        await async_require_admin(self.hass, self._context, self.node.entry_id)
        self.node.sending_enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Block sending."""
        self.node.sending_enabled = False
        self.async_write_ha_state()


class MeshComNoMsgAllSwitch(CoordinatorEntity[MeshComWebCoordinator], SwitchEntity):
    """The node's "No MSG All" setting, read and written via the web API.

    While it is on, Home Assistant applies the same filter as the node's
    display: only the node's groups and direct messages to the node.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "no_msg_all"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: MeshComWebCoordinator, node: MeshComNode, entry_id: str
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{node.node_id:06x}_no_msg_all"
        self._attr_device_info = node_device_info(node)
        self._entry_id = entry_id

    @property
    def available(self) -> bool:
        """Unavailable while the node's web API cannot be read."""
        return super().available and self.coordinator.data is not None

    @property
    def is_on(self) -> bool | None:
        """State as reported by the node."""
        return self.coordinator.data.no_msg_all if self.coordinator.data else None

    async def _check_admin(self) -> None:
        # Changing node settings is reserved for administrators.
        await async_require_admin(self.hass, self._context, self._entry_id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Hide messages to all on the node (and in Home Assistant)."""
        await self._check_admin()
        await self.coordinator.async_set_no_msg_all(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Show messages to all again."""
        await self._check_admin()
        await self.coordinator.async_set_no_msg_all(False)
