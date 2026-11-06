"""The MeshCom integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

from .const import CONF_CALLSIGN, CONF_LISTEN_PORT, CONF_NODE_ID, DOMAIN, signal_update
from .hub import UdpHub, async_acquire_hub, async_release_hub
from .node import MeshComNode

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.DEVICE_TRACKER, Platform.SENSOR]


@dataclass(slots=True)
class MeshComRuntime:
    """Runtime objects of one config entry."""

    node: MeshComNode
    hub: UdpHub


type MeshComConfigEntry = ConfigEntry[MeshComRuntime]


async def async_setup_entry(hass: HomeAssistant, entry: MeshComConfigEntry) -> bool:
    """Set up a MeshCom node from a config entry."""
    port: int = entry.data[CONF_LISTEN_PORT]
    try:
        hub = await async_acquire_hub(hass, port)
    except OSError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="port_unavailable",
            translation_placeholders={"port": str(port)},
        ) from err

    node = MeshComNode(hass, entry.entry_id, entry.data[CONF_CALLSIGN], entry.data[CONF_NODE_ID])
    unregister = hub.register(entry.data[CONF_HOST], node.handle_packet)

    def _release() -> None:
        unregister()
        async_release_hub(hass, hub)

    entry.async_on_unload(_release)
    entry.runtime_data = MeshComRuntime(node=node, hub=hub)

    # Time-based states ("active", "heard within 24 h") need a periodic refresh.
    @callback
    def _refresh(_now: datetime) -> None:
        async_dispatcher_send(hass, signal_update(entry.entry_id))

    entry.async_on_unload(async_track_time_interval(hass, _refresh, timedelta(minutes=1)))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MeshComConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
