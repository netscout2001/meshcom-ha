"""Logbook entries for messages sent from Home Assistant.

The logbook shows who triggered a transmission (from the event context), so
every message sent under the node's callsign can be traced to a user or an
automation. The message text is not repeated in the logbook.
"""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.logbook.const import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.core import Event, HomeAssistant, callback

from .const import DOMAIN, EVENT_MESSAGE_SENT


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, str]]], None],
) -> None:
    """Describe MeshCom logbook events."""

    @callback
    def _describe_sent(event: Event) -> dict[str, str]:
        return {
            LOGBOOK_ENTRY_NAME: f"MeshCom {event.data.get('node', '')}",
            LOGBOOK_ENTRY_MESSAGE: f"sent a message to {event.data.get('destination', '')}",
        }

    async_describe_event(DOMAIN, EVENT_MESSAGE_SENT, _describe_sent)
