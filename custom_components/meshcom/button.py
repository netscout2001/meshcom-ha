"""Send and clear buttons for composing a message."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MeshComConfigEntry
from .aiomeshcom import DestinationKind
from .const import DOMAIN, signal_update
from .entity import MeshComEntity
from .node import MeshComNode
from .sender import async_send_text

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MeshComConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons."""
    node = entry.runtime_data.node
    async_add_entities([MeshComSendButton(node, "send", entry), MeshComClearButton(node, "clear")])


def _destination(node: MeshComNode) -> str:
    if node.compose_kind is DestinationKind.BROADCAST:
        return "*"
    target = (
        node.compose_group if node.compose_kind is DestinationKind.GROUP else node.compose_station
    )
    if not target:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_recipient")
    return target


class MeshComSendButton(MeshComEntity, ButtonEntity):
    """Send the drafted message to the selected recipient."""

    def __init__(self, node: MeshComNode, key: str, entry: MeshComConfigEntry) -> None:
        super().__init__(node, key)
        self._entry = entry

    async def async_press(self) -> None:
        """Send through the transmit gate, then clear the draft."""
        await async_send_text(
            self.hass, self._entry, _destination(self.node), self.node.compose_text, self._context
        )
        self.node.compose_text = ""
        async_dispatcher_send(self.hass, signal_update(self.node.entry_id))


class MeshComClearButton(MeshComEntity, ButtonEntity):
    """Clear the drafted message."""

    async def async_press(self) -> None:
        """Clear the draft."""
        await self._check_send_permission()
        self.node.compose_text = ""
        async_dispatcher_send(self.hass, signal_update(self.node.entry_id))
