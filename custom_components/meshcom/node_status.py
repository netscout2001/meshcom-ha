"""Values of the panel's node dashboard beyond the node's entities.

Battery, signal, firmware and the like come from the entity states in the
panel (restored over a restart). This adds what has no entity: the values of
the node's web pages, the message activity per hour, the delivery states of
own messages and the direct neighbours.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Final

from .const import STATIONS_WINDOW

#: Delivery states of own messages, grouped for the panel.
_DELIVERED: Final = frozenset({"delivered"})
_FAILED: Final = frozenset({"failed", "rejected"})
_PENDING: Final = frozenset({"sent", "heard_by_node", "gateway", "held"})
#: Direct neighbours sent to the panel.
NEIGHBOUR_LIMIT: Final = 64
#: Own messages counted for the delivery states.
DELIVERY_WINDOW: Final = timedelta(hours=48)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _web(entry: Any) -> dict[str, Any]:
    web = entry.runtime_data.web
    data = web.data
    result: dict[str, Any] = {
        "ok": bool(web.last_update_success and data is not None),
        "paused": web.paused,
        "radio_enabled": web.radio_stats,
        "fetched": _iso(data.fetched) if data is not None else None,
        "info": None,
        "gps": None,
        "radio": None,
        "started": None,
    }
    if data is None:
        return result
    if data.info is not None:
        result["info"] = asdict(data.info)
        if data.info.uptime_seconds is not None and data.fetched is not None:
            result["started"] = _iso(data.fetched - timedelta(seconds=data.info.uptime_seconds))
    if data.gps is not None:
        result["gps"] = asdict(data.gps)
    if data.radio is not None:
        result["radio"] = asdict(data.radio)
    return result


def _delivery(entry: Any, now: datetime) -> dict[str, int]:
    """Own messages of the last 48 hours by delivery state."""
    counts = {"delivered": 0, "pending": 0, "failed": 0, "unknown": 0}
    oldest = (now - DELIVERY_WINDOW).isoformat()
    for message in entry.runtime_data.chat.messages:
        # ISO times in UTC compare correctly as text.
        if not message.own or message.time < oldest:
            continue
        status = message.status or "unknown"
        if status in _DELIVERED:
            counts["delivered"] += 1
        elif status in _FAILED:
            counts["failed"] += 1
        elif status in _PENDING:
            counts["pending"] += 1
        else:
            counts["unknown"] += 1
    return counts


def _neighbours(entry: Any, now: datetime) -> list[dict[str, Any]]:
    """Stations the node heard directly (its MHeard list), newest first."""
    direct = [
        station for station in entry.runtime_data.node.stations.values() if station.is_direct(now)
    ]
    direct.sort(key=lambda station: station.direct_heard or now, reverse=True)
    return [
        {
            "callsign": station.callsign,
            "direct_heard": _iso(station.direct_heard),
            "rssi": station.rssi,
            "snr": station.snr,
            "hears_me_snr": station.hears_me_snr,
            "relay_role": station.relay_role,
            "hardware": station.hardware,
            "it_hears": station.it_hears,
            "only_it_hears": station.only_it_hears,
            "gateway": station.gateway,
            "located": station.latitude is not None and station.longitude is not None,
        }
        for station in direct[:NEIGHBOUR_LIMIT]
    ]


def node_status(entry: Any, now: datetime) -> dict[str, Any]:
    """Everything the dashboard needs besides the entity states."""
    runtime = entry.runtime_data
    node = runtime.node
    stations = node.stations.values()
    heard = [station for station in stations if now - station.last_heard < STATIONS_WINDOW]
    kiss = runtime.kiss
    return {
        "entry_id": entry.entry_id,
        "callsign": node.callsign,
        "active": node.active,
        "last_packet": _iso(node.last_packet),
        "kiss_connected": None if kiss is None else kiss.connected,
        "web": _web(entry),
        "counters": {
            "received": node.messages_received,
            "sent": node.messages_sent,
            "duplicates": node.duplicates,
            "filtered": node.messages_filtered,
        },
        "activity": runtime.activity.series(now),
        "delivery": _delivery(entry, now),
        "stations": {
            "heard_24h": len(heard),
            "direct": sum(1 for station in stations if station.is_direct(now)),
        },
        "neighbours": _neighbours(entry, now),
    }
