"""Kill switch for transmitting from Home Assistant."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import MeshComConfigEntry
from .entity import MeshComEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MeshComConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switch."""
    async_add_entities([MeshComSendingSwitch(entry.runtime_data.node, "sending_enabled")])


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
        """Allow sending."""
        self.node.sending_enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Block sending."""
        self.node.sending_enabled = False
        self.async_write_ha_state()
