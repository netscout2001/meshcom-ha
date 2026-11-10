"""The MeshCom integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from .activity import ActivityLog
from .aiomeshcom import DestinationKind, TextMessagePacket
from .aiomeshcom.webapi import AUTH_HMAC, AUTH_LEGACY, MeshComWebClient, WebApiError
from .chat import ChatHistory, conversation_of, is_foreign_group, own_groups
from .const import (
    ACCESS_KISS,
    ACCESS_UDP,
    CONF_ACCESS,
    CONF_CALLSIGN,
    CONF_HIDE_FOREIGN_GROUPS,
    CONF_INACTIVE_MINUTES,
    CONF_LISTEN_PORT,
    CONF_NODE_ID,
    CONF_RADIO_STATS,
    CONF_WEB_AUTH,
    DEFAULT_HIDE_FOREIGN_GROUPS,
    DEFAULT_INACTIVE_MINUTES,
    DEFAULT_RADIO_STATS,
    DOMAIN,
    ISSUE_WEB_LEGACY_LOGIN,
    ISSUE_WEB_PASSWORD_MISSING,
    signal_update,
)
from .coordinator import MeshComWebCoordinator
from .hub import UdpHub, async_acquire_hub, async_release_hub
from .kiss_link import KissLink
from .migration import async_migrate_entry as _async_migrate_entry
from .node import MeshComNode
from .panel import async_register_panel, async_unregister_panel
from .services import async_setup_services
from .stations import StationDevices, StationStore
from .websocket import async_register_websocket

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

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class MeshComRuntime:
    """Runtime objects of one config entry."""

    node: MeshComNode
    hub: UdpHub | None
    kiss: KissLink | None
    host: str
    web: MeshComWebCoordinator
    stations: StationDevices
    store: StationStore
    chat: ChatHistory
    activity: ActivityLog
    options: dict[str, Any]

    def send_datagram(self, data: bytes) -> None:
        """Send to this node's external UDP port."""
        if self.hub is None:  # pragma: no cover - sender checks the access path first
            raise OSError("no UDP access")
        self.hub.send(self.host, data)


type MeshComConfigEntry = ConfigEntry[MeshComRuntime]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services (once, independent of config entries)."""
    async_setup_services(hass)
    async_register_websocket(hass)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: MeshComConfigEntry) -> bool:
    """Migrate an entry from an older version."""
    return await _async_migrate_entry(hass, entry)


async def async_setup_entry(hass: HomeAssistant, entry: MeshComConfigEntry) -> bool:
    """Set up a MeshCom node from a config entry."""
    node = MeshComNode(
        hass,
        entry.entry_id,
        entry.data[CONF_CALLSIGN],
        entry.data[CONF_NODE_ID],
        active_timeout=timedelta(
            minutes=int(entry.options.get(CONF_INACTIVE_MINUTES, DEFAULT_INACTIVE_MINUTES))
        ),
    )
    hub: UdpHub | None = None
    kiss: KissLink | None = None
    if entry.data.get(CONF_ACCESS, ACCESS_UDP) == ACCESS_KISS:
        kiss = KissLink(hass, entry, node)
    else:
        port: int = entry.data[CONF_LISTEN_PORT]
        try:
            hub = await async_acquire_hub(hass, port)
        except OSError as err:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="port_unavailable",
                translation_placeholders={"port": str(port)},
            ) from err
        udp_hub = hub
        unregister = udp_hub.register(entry.data[CONF_HOST], node.handle_packet)

        def _release() -> None:
            unregister()
            async_release_hub(hass, udp_hub)

        entry.async_on_unload(_release)

    client = MeshComWebClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data.get(CONF_PASSWORD),
        # Never fall back to the plain-text login once the node used the secure one.
        allow_legacy=entry.data.get(CONF_WEB_AUTH) != AUTH_HMAC,
    )
    web = MeshComWebCoordinator(
        hass,
        entry,
        client,
        # Away: heard before, but nothing for longer than the inactive timeout.
        node_away=lambda: node.last_packet is not None and not node.active,
        radio_stats=bool(entry.options.get(CONF_RADIO_STATS, DEFAULT_RADIO_STATS)),
    )

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

    # Chat history for the panel.
    chat = ChatHistory(hass, entry.entry_id)
    await chat.async_load()
    activity = ActivityLog(hass, entry.entry_id)
    await activity.async_load()

    @callback
    def _message(packet: TextMessagePacket, own: bool, when: datetime) -> None:
        activity.add(_activity_kind(packet, own), when)
        # Foreign groups stay out of the history (they would also push own
        # messages out of the size-limited store).
        if (
            not own
            and entry.options.get(CONF_HIDE_FOREIGN_GROUPS, DEFAULT_HIDE_FOREIGN_GROUPS)
            and is_foreign_group(
                conversation_of(packet, own=own), own_groups(node.node_groups, entry.options)
            )
        ):
            return
        chat.async_add_packet(packet, own=own, now=when)

    node.message_listener = _message
    node.delivery_listener = chat.async_set_status

    entry.runtime_data = MeshComRuntime(
        node=node,
        hub=hub,
        kiss=kiss,
        host=entry.data[CONF_HOST],
        web=web,
        stations=stations,
        store=store,
        chat=chat,
        activity=activity,
        options=dict(entry.options),
    )
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    _async_start_web(hass, entry, node, client, web)

    # Time-based states ("active", "heard within 24 h") need a periodic refresh.
    @callback
    def _refresh(_now: datetime) -> None:
        async_dispatcher_send(hass, signal_update(entry.entry_id))

    entry.async_on_unload(async_track_time_interval(hass, _refresh, timedelta(minutes=1)))

    # Everything that can fail runs before the platforms: an error after
    # forwarding would leave them loaded, and the next reload fails with
    # "already been setup". The panel is optional; a failure must not stop
    # the node.
    await _async_register_panel_safely(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    if kiss is not None:
        kiss.async_start()
    return True


async def _async_register_panel_safely(hass: HomeAssistant) -> None:
    """The chat panel is optional: an error is logged and does not stop the node."""
    try:
        await async_register_panel(hass)
    except Exception:
        _LOGGER.exception("The MeshCom chat panel could not be registered")


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


def _async_start_web(
    hass: HomeAssistant,
    entry: MeshComConfigEntry,
    node: MeshComNode,
    client: MeshComWebClient,
    web: MeshComWebCoordinator,
) -> None:
    """Couple the web API polling to the node, then make first contact."""

    @callback
    def _apply_web_settings() -> None:
        # The HA filter follows the node's "No MSG All" switch.
        if web.data is not None:
            node.apply_web_settings(
                no_msg_all=web.data.no_msg_all,
                groups=web.data.groups,
                firmware=web.data.firmware,
                battery_voltage=web.data.battery_voltage,
            )
            if web.data.mheard is not None:
                node.apply_mheard(web.data.mheard)
        _async_track_login_method(hass, entry, client)

    entry.async_on_unload(web.async_add_listener(_apply_web_settings))

    @callback
    def _node_back() -> None:
        # Polling pauses while the node is away; resume as soon as it is heard.
        if web.paused and node.active:
            web.paused = False
            entry.async_create_background_task(
                hass, web.async_request_refresh(), f"{DOMAIN} web resume"
            )

    entry.async_on_unload(async_dispatcher_connect(hass, signal_update(entry.entry_id), _node_back))
    # Not awaited: a mobile node may be away, which must not block setup.
    entry.async_create_background_task(
        hass, _async_first_web_contact(hass, entry, client, web), f"{DOMAIN} web start"
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
    await web.async_refresh_now()


async def _async_options_updated(hass: HomeAssistant, entry: MeshComConfigEntry) -> None:
    """Reload when the options change (station mode, groups, ...)."""
    # Data updates (pinning the login method) need no reload.
    if dict(entry.options) != entry.runtime_data.options:
        hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: MeshComConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and entry.runtime_data.kiss is not None:
        await entry.runtime_data.kiss.async_stop()
    if unloaded:
        await entry.runtime_data.store.async_save_now(entry.runtime_data.node)
        await entry.runtime_data.chat.async_save_now()
        await entry.runtime_data.activity.async_save_now()
        entry.runtime_data.chat.async_close()
        others = [
            other
            for other in hass.config_entries.async_entries(DOMAIN)
            if other.entry_id != entry.entry_id and other.state is ConfigEntryState.LOADED
        ]
        if not others:
            async_unregister_panel(hass)
    return unloaded


def _activity_kind(packet: TextMessagePacket, own: bool) -> str:
    if own:
        return "sent"
    return {
        DestinationKind.DIRECT: "received_direct",
        DestinationKind.GROUP: "received_group",
    }.get(packet.destination_kind, "received_all")


async def async_remove_entry(hass: HomeAssistant, entry: MeshComConfigEntry) -> None:
    """Delete the stored station list together with the entry."""
    await StationStore(hass, entry.entry_id).async_remove()
    await ChatHistory(hass, entry.entry_id).async_remove()
    await ActivityLog(hass, entry.entry_id).async_remove()


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
