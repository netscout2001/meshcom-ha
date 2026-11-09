"""Base entity for MeshCom."""

from __future__ import annotations

from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, signal_station, signal_update
from .node import MeshComNode, StationInfo
from .sender import allowed_users, async_check_send_permission
from .stations import station_device_info


def node_device_info(node: MeshComNode) -> DeviceInfo:
    """Device of the own node. Identified by the node id, not by callsign or IP."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{node.node_id:06x}")},
        name=f"MeshCom {node.callsign}",
        manufacturer="MeshCom",
        model="MeshCom node",
        sw_version=str(node.firmware) if node.firmware else None,
    )


async def async_require_admin(hass: HomeAssistant, context: Context | None, entry_id: str) -> None:
    """Raise Unauthorized unless the caller is an administrator.

    Calls without a user (automations, scripts) are allowed.
    """
    user_id = context.user_id if context else None
    if user_id is None:
        return
    user = await hass.auth.async_get_user(user_id)
    if user is None or not user.is_admin:
        raise Unauthorized(context=context, config_entry_id=entry_id)


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

    async def _check_send_permission(self) -> None:
        """Only users who may transmit may change the draft."""
        entry = self.hass.config_entries.async_get_entry(self.node.entry_id)
        options = dict(entry.options) if entry is not None else {}
        await async_check_send_permission(
            self.hass, self.node.entry_id, allowed_users(options), self._context
        )


class MeshComStationEntity(Entity):
    """An entity of a station heard by the own node ("entities" station mode)."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, node: MeshComNode, callsign: str, key: str) -> None:
        self.node = node
        self.callsign = callsign
        self._attr_unique_id = f"{node.node_id:06x}_{callsign}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = station_device_info(node, callsign)

    @property
    def station(self) -> StationInfo | None:
        """Current data of the station."""
        return self.node.stations.get(self.callsign)

    @property
    def available(self) -> bool:
        """Available while the node remembers the station."""
        return self.station is not None

    async def async_added_to_hass(self) -> None:
        """Subscribe to updates of this station."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_station(self.node.entry_id, self.callsign),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
