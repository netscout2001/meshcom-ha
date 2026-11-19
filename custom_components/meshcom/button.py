"""Send and clear buttons for composing a message."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MeshComConfigEntry
from .const import signal_update
from .entity import MeshComEntity, async_require_admin
from .node import MeshComNode
from .remote_entity import async_add_remote_entities
from .sender import async_send_text, compose_destination

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MeshComConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons."""
    async_add_remote_entities(hass, entry, async_add_entities, "button")
    node = entry.runtime_data.node
    async_add_entities(
        [
            MeshComSendButton(node, "send", entry),
            MeshComClearButton(node, "clear"),
            MeshComReadRadioButton(node, "read_radio", entry),
        ]
    )


class MeshComSendButton(MeshComEntity, ButtonEntity):
    """Send the drafted message to the selected recipient."""

    def __init__(self, node: MeshComNode, key: str, entry: MeshComConfigEntry) -> None:
        super().__init__(node, key)
        self._entry = entry

    async def async_press(self) -> None:
        """Send through the transmit gate, then clear the draft."""
        destination = compose_destination(self.node)
        await async_send_text(
            self.hass, self._entry, destination, self.node.compose_text, self._context
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


class MeshComReadRadioButton(MeshComEntity, ButtonEntity):
    """Read RX boost, frequency, TX power and country from the net console.

    The node serves one console client: unless the console tab is open, this
    logs in for a moment and so ends any other console session.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, node: MeshComNode, key: str, entry: MeshComConfigEntry) -> None:
        super().__init__(node, key)
        self._entry = entry

    async def async_press(self) -> None:
        """Run "--info" on the node and keep the radio settings."""
        await async_require_admin(self.hass, self._context, self.node.entry_id)
        self.node.radio_info = await self._entry.runtime_data.console.async_read_radio_info()
        async_dispatcher_send(self.hass, signal_update(self.node.entry_id))
