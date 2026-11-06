"""Diagnostics for MeshCom.

Diagnostics are often attached to public GitHub issues. They contain counters
and node state, but no positions, no message text and no callsigns of other
stations (security concept C-04, C-12).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import MeshComConfigEntry
from .stations import station_mode

TO_REDACT = {CONF_HOST, CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MeshComConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = entry.runtime_data
    node = runtime.node
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "hub": runtime.hub.diagnostics(),
        "web": {
            "password_configured": bool(entry.data.get(CONF_PASSWORD)),
            "last_update_success": runtime.web.last_update_success,
            "no_msg_all": runtime.web.data.no_msg_all if runtime.web.data else None,
            "groups": len(runtime.web.data.groups) if runtime.web.data else None,
        },
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
            "filter_active": node.filter_active,
            "messages_filtered": node.messages_filtered,
            "stations_heard_24h": node.stations_heard(),
            "station_mode": station_mode(entry),
            "station_devices": len(runtime.stations.tracked),
        },
    }
