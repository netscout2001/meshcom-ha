"""Recipient selection for composing a message."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MeshComConfigEntry
from .aiomeshcom import DestinationKind, is_callsign, is_group
from .const import CONF_GROUPS
from .entity import MeshComEntity
from .node import MeshComNode

PARALLEL_UPDATES = 0

RECIPIENT_TYPES = [
    DestinationKind.BROADCAST.value,
    DestinationKind.GROUP.value,
    DestinationKind.DIRECT.value,
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MeshComConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the selects."""
    node = entry.runtime_data.node
    async_add_entities(
        [
            MeshComRecipientTypeSelect(node, "recipient_type"),
            MeshComGroupSelect(node, "group", entry),
            MeshComStationSelect(node, "station"),
        ]
    )


class MeshComRecipientTypeSelect(MeshComEntity, SelectEntity):
    """Broadcast, group or direct message."""

    _attr_options = RECIPIENT_TYPES

    @property
    def current_option(self) -> str:
        """Selected recipient type."""
        return self.node.compose_kind.value

    async def async_select_option(self, option: str) -> None:
        """Change the recipient type."""
        await self._check_send_permission()
        self.node.compose_kind = DestinationKind(option)
        self.async_write_ha_state()


class MeshComGroupSelect(MeshComEntity, SelectEntity):
    """Group numbers from the integration options."""

    def __init__(self, node: MeshComNode, key: str, entry: MeshComConfigEntry) -> None:
        super().__init__(node, key)
        self._entry = entry

    @property
    def options(self) -> list[str]:
        """Groups of the node (web API) plus groups from the options."""
        configured = self._entry.options.get(CONF_GROUPS, [])
        groups = [*self.node.node_groups, *configured]
        return list(dict.fromkeys(g for g in groups if isinstance(g, str) and is_group(g)))

    @property
    def available(self) -> bool:
        """Only usable once groups are configured."""
        return bool(self.options)

    @property
    def current_option(self) -> str | None:
        """Selected group."""
        return self.node.compose_group if self.node.compose_group in self.options else None

    async def async_select_option(self, option: str) -> None:
        """Select a group."""
        await self._check_send_permission()
        self.node.compose_group = option
        self.async_write_ha_state()


class MeshComStationSelect(MeshComEntity, SelectEntity):
    """Stations heard by the node, for direct messages."""

    @property
    def options(self) -> list[str]:
        """Heard callsigns, sorted. Only syntactically valid callsigns are offered."""
        return sorted(call for call in self.node.stations if is_callsign(call))

    @property
    def available(self) -> bool:
        """Only usable once stations were heard."""
        return bool(self.options)

    @property
    def current_option(self) -> str | None:
        """Selected station."""
        return self.node.compose_station if self.node.compose_station in self.options else None

    async def async_select_option(self, option: str) -> None:
        """Select a station."""
        await self._check_send_permission()
        self.node.compose_station = option
        self.async_write_ha_state()
