"""Constants for the MeshCom integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from .aiomeshcom.const import EXT_UDP_PORT

DOMAIN: Final = "meshcom"

CONF_LISTEN_PORT: Final = "listen_port"
CONF_CALLSIGN: Final = "callsign"
CONF_NODE_ID: Final = "node_id"

DEFAULT_LISTEN_PORT: Final = EXT_UDP_PORT

#: How long the config flow waits for a packet sent by the node itself.
SETUP_WAIT_TIMEOUT: Final = 120

#: A node counts as active if it sent anything within this time. The node
#: beacons its position every 30 minutes by default.
NODE_ACTIVE_TIMEOUT: Final = timedelta(minutes=65)

#: Window for "stations heard" sensor.
STATIONS_WINDOW: Final = timedelta(hours=24)

#: Upper bound of remembered stations per node (LRU, security concept C-09).
MAX_STATIONS: Final = 500

#: Duplicate suppression window (replayed or repeated datagrams, C-14).
DEDUP_WINDOW: Final = timedelta(minutes=10)
DEDUP_MAX_ENTRIES: Final = 2000

#: Per-source rate limit for incoming datagrams (C-10, C-20).
RATE_LIMIT_PER_SECOND: Final = 20.0
RATE_LIMIT_BURST: Final = 60.0

EVENT_MESSAGE: Final = f"{DOMAIN}_message"
EVENT_DELIVERY: Final = f"{DOMAIN}_delivery_update"


def signal_update(entry_id: str) -> str:
    """Dispatcher signal for state changes of one node."""
    return f"{DOMAIN}_update_{entry_id}"
