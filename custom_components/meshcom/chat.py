"""Chat history of one node, for the chat panel.

Messages are grouped into conversations: messages to all, one per group,
one per direct-message partner, and one per other addressee. The history is
size-limited, stored per config entry and read back defensively, because the
file can be edited by anyone with access to the configuration directory
(security concept C-01, C-02, C-09).

Message text is data. It is never interpreted, and the panel renders it as
plain text only.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .aiomeshcom import DestinationKind, SourceType, TextMessagePacket, is_callsign, is_group
from .const import CONF_GROUPS, DOMAIN

_LOGGER = logging.getLogger(__name__)

#: Messages kept per node.
CHAT_HISTORY_LIMIT = 500
CHAT_STORE_VERSION = 1
CHAT_SAVE_DELAY = 30
#: Longest text accepted from the stored file (the node limits to 150 bytes).
_MAX_STORED_TEXT = 300

#: Most hops kept for the "via" line.
_MAX_PATH = 12

#: Delivery states shown in the panel.
STATUS_SENT = "sent"
_STATUSES = frozenset(
    {
        STATUS_SENT,
        "heard_by_node",
        "gateway",
        "delivered",
        "held",
        "failed",
        "rejected",
        "unknown",
    }
)


@dataclass(slots=True)
class ChatMessage:
    """One message in the history."""

    id: str
    conversation: str
    sender: str
    destination: str
    text: str
    time: str
    own: bool
    via_server: bool = False
    rssi: int | None = None
    snr: float | None = None
    status: str | None = None
    #: Originator and relays, as the node reported them ("via A > B > C").
    path: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """JSON-serialisable form."""
        return asdict(self)


def conversation_of(packet: TextMessagePacket, *, own: bool) -> str:
    """Conversation key of a message."""
    kind = packet.destination_kind
    if kind is DestinationKind.BROADCAST:
        return "all"
    if kind is DestinationKind.GROUP:
        return f"group:{packet.destination}"
    if kind is DestinationKind.DIRECT:
        return f"dm:{packet.destination if own else packet.path.originator}"
    return f"other:{packet.destination}"


def own_groups(node_groups: list[str], options: Mapping[str, Any]) -> set[str]:
    """Groups the node listens to plus the groups configured in the options."""
    configured = options.get(CONF_GROUPS, [])
    extra = [g for g in configured if isinstance(g, str)] if isinstance(configured, list) else []
    return {*node_groups, *extra}


def is_foreign_group(conversation: str, groups: set[str]) -> bool:
    """True for a group conversation of a group the node does not listen to.

    Without any known group (web API not read yet, no groups configured)
    nothing counts as foreign, so the chat never goes empty by accident.
    """
    if not groups or not conversation.startswith("group:"):
        return False
    return conversation[6:] not in groups


def _valid_conversation(value: Any) -> bool:
    if value == "all":
        return True
    if not isinstance(value, str):
        return False
    kind, _, peer = value.partition(":")
    if kind == "group":
        return is_group(peer)
    if kind == "dm":
        return is_callsign(peer)
    if kind == "other":
        return 0 < len(peer) <= 9 and peer.isascii() and peer.isprintable()
    return False


def _parse(raw: Any) -> ChatMessage | None:
    """A stored message, or None if anything about it is off."""
    if not isinstance(raw, Mapping):
        return None
    text = raw.get("text")
    sender = raw.get("sender")
    destination = raw.get("destination")
    time = raw.get("time")
    msg_id = raw.get("id")
    if not (
        isinstance(text, str)
        and len(text) <= _MAX_STORED_TEXT
        and isinstance(sender, str)
        and is_callsign(sender)
        and isinstance(destination, str)
        and 0 < len(destination) <= 9
        and destination.isascii()
        and destination.isprintable()
        and isinstance(msg_id, str)
        and len(msg_id) <= 16
        and msg_id.isalnum()
        and isinstance(time, str)
        and _valid_conversation(raw.get("conversation"))
        and isinstance(raw.get("own"), bool)
    ):
        return None
    parsed_time = dt_util.parse_datetime(time)
    if parsed_time is None or parsed_time.tzinfo is None:
        return None
    rssi = raw.get("rssi")
    snr = raw.get("snr")
    status = raw.get("status")
    raw_path = raw.get("path")
    path = (
        list(raw_path)
        if isinstance(raw_path, list)
        and len(raw_path) <= _MAX_PATH
        and all(isinstance(hop, str) and is_callsign(hop) for hop in raw_path)
        else []
    )
    return ChatMessage(
        id=msg_id,
        conversation=raw["conversation"],
        sender=sender,
        destination=destination,
        text=text,
        time=parsed_time.isoformat(),
        own=raw["own"],
        via_server=raw.get("via_server") is True,
        rssi=rssi if isinstance(rssi, int) and not isinstance(rssi, bool) else None,
        snr=snr if isinstance(snr, (int, float)) and not isinstance(snr, bool) else None,
        status=status if status in _STATUSES else None,
        path=path,
    )


class ChatHistory:
    """Size-limited message history of one node, with live listeners."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.messages: deque[ChatMessage] = deque(maxlen=CHAT_HISTORY_LIMIT)
        self._listeners: list[Callable[[str, dict[str, Any]], None]] = []
        self._store: Store[dict[str, Any]] = Store(
            hass, CHAT_STORE_VERSION, f"{DOMAIN}.chat.{entry_id}"
        )

    async def async_load(self) -> None:
        """Read the stored history."""
        try:
            data = await self._store.async_load()
        except (ValueError, OSError):  # pragma: no cover - broken file, start empty
            _LOGGER.warning("Stored chat history is unreadable and is ignored")
            return
        raw = data.get("messages") if isinstance(data, Mapping) else None
        if not isinstance(raw, list):
            return
        for item in raw[-CHAT_HISTORY_LIMIT:]:
            if (message := _parse(item)) is not None:
                self.messages.append(message)

    def _data(self) -> dict[str, Any]:
        return {"messages": [message.as_dict() for message in self.messages]}

    async def async_save_now(self) -> None:
        """Write immediately (unload)."""
        await self._store.async_save(self._data())

    async def async_remove(self) -> None:
        """Delete the file (config entry removed)."""
        await self._store.async_remove()

    @callback
    def async_subscribe(self, listener: Callable[[str, dict[str, Any]], None]) -> CALLBACK_TYPE:
        """Call ``listener(kind, data)`` for new messages and status changes."""
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    def _notify(self, kind: str, data: dict[str, Any]) -> None:
        for listener in list(self._listeners):
            listener(kind, data)

    @callback
    def async_close(self) -> None:
        """The node is unloaded: tell the subscribers so they can reconnect."""
        self._notify("closed", {})
        self._listeners.clear()

    @callback
    def async_add_packet(self, packet: TextMessagePacket, *, own: bool, now: datetime) -> None:
        """Add a received or own message."""
        message = ChatMessage(
            id=str(packet.msg_id),
            conversation=conversation_of(packet, own=own),
            sender=packet.path.originator,
            destination=packet.destination,
            text=packet.text,
            time=now.isoformat(),
            own=own,
            via_server=packet.source_type is SourceType.UDP,
            rssi=None if own else packet.radio.rssi,
            snr=None if own else packet.radio.snr,
            status=STATUS_SENT if own else None,
            path=[packet.path.originator, *packet.path.relays][:_MAX_PATH],
        )
        self.messages.append(message)
        self._store.async_delay_save(self._data, CHAT_SAVE_DELAY)
        self._notify("message", message.as_dict())

    @callback
    def async_set_status(self, msg_id: str, status: str) -> None:
        """Delivery status of an own message changed."""
        if status not in _STATUSES:
            status = "unknown"
        for message in reversed(self.messages):
            if message.own and message.id == msg_id:
                message.status = status
                self._store.async_delay_save(self._data, CHAT_SAVE_DELAY)
                self._notify("status", {"id": msg_id, "status": status})
                return
