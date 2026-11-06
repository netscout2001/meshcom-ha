"""Diagnostics for MeshCom.

Diagnostics are often attached to public GitHub issues. They contain counters
and node state, but no positions, no message text and no callsigns of other
stations (security concept C-04, C-12).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from . import MeshComConfigEntry

TO_REDACT = {CONF_HOST}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MeshComConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = entry.runtime_data
    node = runtime.node
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "hub": runtime.hub.diagnostics(),
        "node": {
            "active": node.active,
            "last_packet": node.last_packet.isoformat() if node.last_packet else None,
            "firmware": str(node.firmware) if node.firmware else None,
            "has_position": node.position is not None,
            "has_sensor_data": bool(node.telemetry and node.telemetry.has_sensor_data),
            "messages_received": node.messages_received,
            "messages_sent": node.messages_sent,
            "duplicates_dropped": node.duplicates,
            "stations_known": len(node.stations),
            "stations_heard_24h": node.stations_heard(),
        },
    }
