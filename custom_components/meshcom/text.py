"""Message input for composing a message."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MeshComConfigEntry
from .aiomeshcom.const import MAX_OUTGOING_TEXT_BYTES
from .entity import MeshComEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MeshComConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the text input."""
    async_add_entities([MeshComMessageText(entry.runtime_data.node, "message")])


class MeshComMessageText(MeshComEntity, TextEntity):
    """The message to send. The node counts bytes, so umlauts count twice."""

    _attr_native_max = MAX_OUTGOING_TEXT_BYTES

    @property
    def native_value(self) -> str:
        """Current draft."""
        return self.node.compose_text

    async def async_set_value(self, value: str) -> None:
        """Store the draft (validated when sending)."""
        await self._check_send_permission()
        self.node.compose_text = value
        self.async_write_ha_state()
