"""WebSocket API of the chat panel.

Reading is allowed to administrators and to the users released for sending
in a node's options; everyone else gets "unauthorized". Sending goes through
``async_send_text``, i.e. the same kill switch, permission check, builder
validation and rate limit as the ``meshcom.send_message`` action.
"""

from __future__ import annotations

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

from .const import CONF_GROUPS, DOMAIN
from .sender import allowed_users, async_send_text

_ENTRY_ID = vol.All(str, vol.Length(min=1, max=64))


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    """Register the commands (once)."""
    async_register_command(hass, ws_nodes)
    async_register_command(hass, ws_history)
    async_register_command(hass, ws_subscribe)
    async_register_command(hass, ws_send)


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
            }
        )
    connection.send_result(msg["id"], {"nodes": nodes})


@websocket_command(
    {vol.Required("type"): "meshcom/chat/history", vol.Required("entry_id"): _ENTRY_ID}
)
@callback
def ws_history(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """All stored messages of a node, oldest first."""
    if (entry := _entry(hass, connection, msg)) is None:
        return
    history = entry.runtime_data.chat
    connection.send_result(
        msg["id"], {"messages": [message.as_dict() for message in history.messages]}
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
