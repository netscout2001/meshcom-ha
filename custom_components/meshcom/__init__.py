"""The MeshCom integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from .aiomeshcom.webapi import AUTH_HMAC, AUTH_LEGACY, MeshComWebClient, WebApiError
from .const import (
    CONF_CALLSIGN,
    CONF_LISTEN_PORT,
    CONF_NODE_ID,
    CONF_WEB_AUTH,
    DOMAIN,
    ISSUE_WEB_LEGACY_LOGIN,
    ISSUE_WEB_PASSWORD_MISSING,
    signal_update,
)
from .coordinator import MeshComWebCoordinator
from .hub import UdpHub, async_acquire_hub, async_release_hub
from .node import MeshComNode
from .services import async_setup_services
from .stations import StationDevices, StationStore

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass(slots=True)
class MeshComRuntime:
    """Runtime objects of one config entry."""

    node: MeshComNode
    hub: UdpHub
    host: str
    web: MeshComWebCoordinator
    stations: StationDevices
    store: StationStore
    options: dict[str, Any]

    def send_datagram(self, data: bytes) -> None:
        """Send to this node's external UDP port."""
        self.hub.send(self.host, data)


type MeshComConfigEntry = ConfigEntry[MeshComRuntime]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services (once, independent of config entries)."""
    async_setup_services(hass)
    return True


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

    client = MeshComWebClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data.get(CONF_PASSWORD),
        # Never fall back to the plain-text login once the node used the secure one.
        allow_legacy=entry.data.get(CONF_WEB_AUTH) != AUTH_HMAC,
    )
    web = MeshComWebCoordinator(hass, entry, client)

    # Heard stations: restored from disk, saved on change, devices per mode.
    store = StationStore(hass, entry.entry_id)
    node.restore_stations(await store.async_load())
    stations = StationDevices(hass, entry, node)

    @callback
    def _station_heard(callsign: str) -> None:
        store.async_schedule_save(node)
        stations.async_station_heard(callsign)

    node.station_listener = _station_heard
    stations.async_start()

    entry.runtime_data = MeshComRuntime(
        node=node,
        hub=hub,
        host=entry.data[CONF_HOST],
        web=web,
        stations=stations,
        store=store,
        options=dict(entry.options),
    )
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    @callback
    def _apply_web_settings() -> None:
        # The HA filter follows the node's "No MSG All" switch.
        if web.data is not None:
            node.apply_web_settings(no_msg_all=web.data.no_msg_all, groups=web.data.groups)
        _async_track_login_method(hass, entry, client)

    entry.async_on_unload(web.async_add_listener(_apply_web_settings))
    # Not awaited: a mobile node may be away, which must not block setup.
    entry.async_create_background_task(
        hass, _async_first_web_contact(hass, entry, client, web), f"{DOMAIN} web start"
    )

    # Time-based states ("active", "heard within 24 h") need a periodic refresh.
    @callback
    def _refresh(_now: datetime) -> None:
        async_dispatcher_send(hass, signal_update(entry.entry_id))

    entry.async_on_unload(async_track_time_interval(hass, _refresh, timedelta(minutes=1)))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


@callback
def _async_track_login_method(
    hass: HomeAssistant, entry: MeshComConfigEntry, client: MeshComWebClient
) -> None:
    """Pin the secure login once used; warn while the plain-text login is in use."""
    issue_id = f"{ISSUE_WEB_LEGACY_LOGIN}_{entry.entry_id}"
    if client.auth_method == AUTH_HMAC:
        client.allow_legacy = False
        if entry.data.get(CONF_WEB_AUTH) != AUTH_HMAC:
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_WEB_AUTH: AUTH_HMAC}
            )
        ir.async_delete_issue(hass, DOMAIN, issue_id)
    elif client.auth_method == AUTH_LEGACY:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_WEB_LEGACY_LOGIN,
            translation_placeholders={"node": entry.title},
        )


async def _async_first_web_contact(
    hass: HomeAssistant,
    entry: MeshComConfigEntry,
    client: MeshComWebClient,
    web: MeshComWebCoordinator,
) -> None:
    """First poll, and a repair hint if the node has no web password (F-01)."""
    issue_id = f"{ISSUE_WEB_PASSWORD_MISSING}_{entry.entry_id}"
    if entry.data.get(CONF_PASSWORD):
        ir.async_delete_issue(hass, DOMAIN, issue_id)
    else:
        try:
            node_is_open = await client.is_open()
        except WebApiError:
            node_is_open = False
        if node_is_open:
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_WEB_PASSWORD_MISSING,
                translation_placeholders={"node": entry.title},
            )
        else:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
    await web.async_refresh()


async def _async_options_updated(hass: HomeAssistant, entry: MeshComConfigEntry) -> None:
    """Reload when the options change (station mode, groups, ...)."""
    # Data updates (pinning the login method) need no reload.
    if dict(entry.options) != entry.runtime_data.options:
        hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: MeshComConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.store.async_save_now(entry.runtime_data.node)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: MeshComConfigEntry) -> None:
    """Delete the stored station list together with the entry."""
    await StationStore(hass, entry.entry_id).async_remove()


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: MeshComConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Station devices may be deleted; the own node may not."""
    node = entry.runtime_data.node
    prefix = f"{node.node_id:06x}_"
    for domain, identifier in device.identifiers:
        if domain == DOMAIN and identifier.startswith(prefix):
            entry.runtime_data.stations.async_device_removed(identifier[len(prefix) :])
            return True
    return False
