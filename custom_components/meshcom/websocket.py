"""WebSocket API of the chat panel.

Reading is allowed to administrators and to the users released for sending
in a node's options; everyone else gets "unauthorized". Sending goes through
``async_send_text``, i.e. the same kill switch, permission check, builder
validation and rate limit as the ``meshcom.send_message`` action.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import voluptuous as vol
from homeassistant.auth.models import User
from homeassistant.components.websocket_api import async_register_command
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.components.websocket_api.const import ERR_NOT_FOUND, ERR_UNAUTHORIZED
from homeassistant.components.websocket_api.decorators import (
    async_response,
    websocket_command,
)
from homeassistant.components.websocket_api.messages import event_message
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .chat import is_foreign_group, own_groups
from .const import (
    ACCESS_UDP,
    CONF_ACCESS,
    CONF_GROUPS,
    CONF_HIDE_FOREIGN_GROUPS,
    DEFAULT_HIDE_FOREIGN_GROUPS,
    DOMAIN,
    STATION_MODE_OFF,
)
from .sender import allowed_users, async_send_text
from .stations import station_mode

_ENTRY_ID = vol.All(str, vol.Length(min=1, max=64))
#: Domains on the "Nodes" tab, in display order.
_NODE_DOMAINS = ("binary_sensor", "switch", "sensor", "device_tracker")
#: Stations sent to the panel.
STATION_LIST_LIMIT = 500


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    """Register the commands (once)."""
    async_register_command(hass, ws_nodes)
    async_register_command(hass, ws_history)
    async_register_command(hass, ws_stations)
    async_register_command(hass, ws_subscribe)
    async_register_command(hass, ws_send)


def _hidden(entry: Any) -> Callable[[str], bool]:
    """Conversations the chat does not show (foreign groups, if enabled)."""
    if not entry.options.get(CONF_HIDE_FOREIGN_GROUPS, DEFAULT_HIDE_FOREIGN_GROUPS):
        return lambda _conversation: False
    groups = own_groups(entry.runtime_data.node.node_groups, entry.options)
    return lambda conversation: is_foreign_group(conversation, groups)


def _may_read(user: User, entry: Any) -> bool:
    return user.is_admin or user.id in allowed_users(dict(entry.options))


def _entry(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> Any | None:
    """The loaded entry the user may read, or None after sending an error."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        connection.send_error(msg["id"], ERR_NOT_FOUND, "Node not found")
        return None
    if not _may_read(connection.user, entry):
        connection.send_error(msg["id"], ERR_UNAUTHORIZED, "Unauthorized")
        return None
    return entry


@websocket_command({vol.Required("type"): "meshcom/chat/nodes"})
@callback
def ws_nodes(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Nodes the user may read, with their groups."""
    nodes = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED or not _may_read(connection.user, entry):
            continue
        node = entry.runtime_data.node
        configured = [g for g in entry.options.get(CONF_GROUPS, []) if isinstance(g, str)]
        nodes.append(
            {
                "entry_id": entry.entry_id,
                "callsign": node.callsign,
                "groups": list(dict.fromkeys([*node.node_groups, *configured])),
                "sending_enabled": node.sending_enabled,
                "access": entry.data.get(CONF_ACCESS, ACCESS_UDP),
                "station_mode": station_mode(entry),
                "entities": _node_entities(hass, entry),
            }
        )
    connection.send_result(msg["id"], {"nodes": nodes})


def _node_entities(hass: HomeAssistant, entry: Any) -> list[dict[str, str]]:
    """Entities of the own node shown on the "Nodes" tab (no compose controls)."""
    node = entry.runtime_data.node
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, f"{node.node_id:06x}")})
    if device is None:  # pragma: no cover - created with the first entity
        return []
    entities = [
        {"entity_id": item.entity_id, "key": item.translation_key or "", "domain": item.domain}
        for item in er.async_entries_for_device(er.async_get(hass), device.id)
        if item.domain in _NODE_DOMAINS and item.disabled_by is None
    ]
    order = {domain: index for index, domain in enumerate(_NODE_DOMAINS)}
    return sorted(entities, key=lambda item: (order[item["domain"]], item["key"]))


@websocket_command(
    {vol.Required("type"): "meshcom/chat/stations", vol.Required("entry_id"): _ENTRY_ID}
)
@callback
def ws_stations(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Heard stations, newest first (empty when the station mode is off)."""
    if (entry := _entry(hass, connection, msg)) is None:
        return
    if station_mode(entry) == STATION_MODE_OFF:
        connection.send_result(msg["id"], {"stations": [], "mode": STATION_MODE_OFF})
        return
    stations = sorted(
        entry.runtime_data.node.stations.values(), key=lambda station: station.last_heard
    )[-STATION_LIST_LIMIT:]
    now = dt_util.utcnow()
    connection.send_result(
        msg["id"],
        {
            "mode": station_mode(entry),
            "stations": [
                {
                    "callsign": station.callsign,
                    "last_heard": station.last_heard.isoformat(),
                    "rssi": station.rssi,
                    "snr": station.snr,
                    "hops": station.hops,
                    "battery": station.battery or None,
                    "latitude": station.latitude,
                    "longitude": station.longitude,
                    "temperature": station.temperature,
                    "humidity": station.humidity,
                    "pressure": station.pressure_qnh,
                    "pressure_qfe": station.pressure_qfe,
                    "weather_time": (
                        station.weather_time.isoformat() if station.weather_time else None
                    ),
                    "path": list(station.path),
                    # From the node's MHeard list (web API).
                    "direct": station.is_direct(now),
                    "direct_heard": (
                        station.direct_heard.isoformat() if station.direct_heard else None
                    ),
                    "hardware": station.hardware,
                    "altitude": station.altitude,
                    "hears_me_snr": station.hears_me_snr,
                    "relay_role": station.relay_role,
                    "only_it_hears": station.only_it_hears,
                    "it_hears": station.it_hears,
                    "neighbours": station.neighbours,
                    "gateway": station.gateway,
                }
                for station in reversed(stations)
            ],
        },
    )


@websocket_command(
    {vol.Required("type"): "meshcom/chat/history", vol.Required("entry_id"): _ENTRY_ID}
)
@callback
def ws_history(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """All stored messages of a node, oldest first."""
    if (entry := _entry(hass, connection, msg)) is None:
        return
    history = entry.runtime_data.chat
    hidden = _hidden(entry)
    connection.send_result(
        msg["id"],
        {
            "messages": [
                message.as_dict()
                for message in history.messages
                if message.own or not hidden(message.conversation)
            ]
        },
    )


@websocket_command(
    {vol.Required("type"): "meshcom/chat/subscribe", vol.Required("entry_id"): _ENTRY_ID}
)
@callback
def ws_subscribe(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Push new messages and delivery updates of a node."""
    if (entry := _entry(hass, connection, msg)) is None:
        return
    user = connection.user

    @callback
    def _forward(kind: str, data: dict[str, Any]) -> None:
        # Permissions can change while subscribed (options edited).
        if kind != "closed" and not _may_read(user, entry):
            return
        if kind == "message" and not data["own"] and _hidden(entry)(data["conversation"]):
            return
        connection.send_message(event_message(msg["id"], {kind: data}))

    connection.subscriptions[msg["id"]] = entry.runtime_data.chat.async_subscribe(_forward)
    connection.send_result(msg["id"])


@websocket_command(
    {
        vol.Required("type"): "meshcom/chat/send",
        vol.Required("entry_id"): _ENTRY_ID,
        vol.Required("destination"): vol.All(str, vol.Length(min=1, max=9)),
        vol.Required("text"): vol.All(str, vol.Length(min=1, max=300)),
    }
)
@async_response
async def ws_send(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Send a message through the node (same checks as the action)."""
    if (entry := _entry(hass, connection, msg)) is None:
        return
    try:
        await async_send_text(hass, entry, msg["destination"], msg["text"], connection.context(msg))
    except Unauthorized:
        connection.send_error(msg["id"], ERR_UNAUTHORIZED, "Unauthorized")
        return
    except HomeAssistantError as err:
        connection.send_error(
            msg["id"], err.translation_key or "send_failed", str(err) or "Sending failed"
        )
        return
    connection.send_result(msg["id"])
