"""Notify entity: send a MeshCom message with the standard notify action."""

from __future__ import annotations

from homeassistant.components.notify import NotifyEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MeshComConfigEntry
from .entity import MeshComEntity
from .node import MeshComNode
from .sender import async_send_text, compose_destination

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MeshComConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the notify entity of the node."""
    async_add_entities([MeshComNotify(entry.runtime_data.node, entry)])


class MeshComNotify(MeshComEntity, NotifyEntity):
    """Sends to the recipient chosen in the node's recipient selects."""

    def __init__(self, node: MeshComNode, entry: MeshComConfigEntry) -> None:
        super().__init__(node, "notify")
        self._entry = entry

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Send through the transmit gate; a title is put in front of the text."""
        text = f"{title}: {message}" if title else message
        await async_send_text(
            self.hass, self._entry, compose_destination(self.node), text, self._context
        )
