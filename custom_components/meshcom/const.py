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
#: A station counts as direct neighbour while the node's MHeard list (last
#: 3 hours) has it.
DIRECT_WINDOW: Final = timedelta(hours=3)

#: Upper bound of remembered stations per node (LRU, security concept C-09).
MAX_STATIONS: Final = 500

#: Duplicate suppression window (replayed or repeated datagrams, C-14).
DEDUP_WINDOW: Final = timedelta(minutes=10)
DEDUP_MAX_ENTRIES: Final = 2000

#: Per-source rate limit for incoming datagrams (C-10, C-20).
RATE_LIMIT_PER_SECOND: Final = 20.0
RATE_LIMIT_BURST: Final = 60.0

EVENT_MESSAGE: Final = f"{DOMAIN}_message"
EVENT_MESSAGE_SENT: Final = f"{DOMAIN}_message_sent"
EVENT_DELIVERY: Final = f"{DOMAIN}_delivery_update"
#: A station was heard for the first time.
EVENT_STATION_NEW: Final = f"{DOMAIN}_station_new"
#: At most this many "station new" events at once, then one per interval:
#: spoofed datagrams with invented callsigns must not flood automations.
STATION_NEW_BURST: Final = 30
STATION_NEW_INTERVAL: Final = timedelta(minutes=2)
#: A direct neighbour was not heard directly for the set time / is back.
EVENT_NEIGHBOUR_LOST: Final = f"{DOMAIN}_neighbour_lost"
EVENT_NEIGHBOUR_BACK: Final = f"{DOMAIN}_neighbour_back"


def signal_update(entry_id: str) -> str:
    """Dispatcher signal for state changes of one node."""
    return f"{DOMAIN}_update_{entry_id}"


# --- sending ---------------------------------------------------------------

#: Options: HA users (besides administrators) who may transmit.
CONF_SEND_USERS: Final = "send_users"
#: Options: group numbers offered in the group select.
CONF_GROUPS: Final = "groups"

#: Transmit rate limit for the whole Home Assistant instance, over all nodes
#: (security concept C-06, T3): a short burst, then one message per interval.
SEND_BURST: Final = 3
SEND_INTERVAL: Final = timedelta(seconds=30)

#: How long an own direct message waits for its acknowledgement.
PENDING_ACK_TIMEOUT: Final = timedelta(minutes=30)
MAX_PENDING_ACKS: Final = 100

SERVICE_SEND_MESSAGE: Final = "send_message"
ATTR_DESTINATION: Final = "destination"
ATTR_MESSAGE: Final = "message"

ISSUE_WEB_PASSWORD_MISSING: Final = "web_password_missing"  # noqa: S105  # issue id, not a secret
ISSUE_WEB_LEGACY_LOGIN: Final = "web_legacy_login"
ISSUE_WEB_DOWNGRADE: Final = "web_downgrade"
#: Login method of the node's web API, pinned once the secure login was used.
CONF_WEB_AUTH: Final = "web_auth"

# --- stations ----------------------------------------------------------------

#: Options: how heard stations appear in Home Assistant.
CONF_STATION_MODE: Final = "station_mode"
STATION_MODE_OFF: Final = "off"
STATION_MODE_DATA: Final = "data"
STATION_MODE_ENTITIES: Final = "entities"
#: Like "data", plus a device for each watched station.
STATION_MODE_WATCH: Final = "watch"
STATION_MODES: Final = (
    STATION_MODE_OFF,
    STATION_MODE_DATA,
    STATION_MODE_WATCH,
    STATION_MODE_ENTITIES,
)
#: Options: callsigns that get a device in the "watch" mode.
CONF_WATCHED_STATIONS: Final = "watched_stations"
MAX_WATCHED_STATIONS: Final = 10
DEFAULT_STATION_MODE: Final = STATION_MODE_DATA
#: Options: at most this many station devices per node.
CONF_STATION_MAX: Final = "station_max"
DEFAULT_STATION_MAX: Final = 50
STATION_MAX_LIMIT: Final = 200
#: Options: station devices are removed after this many days without a packet.
CONF_STATION_STALE_DAYS: Final = "station_stale_days"
DEFAULT_STATION_STALE_DAYS: Final = 7
#: Longest relay path kept per station and message (MeshCom allows few hops).
MAX_PATH: Final = 12
#: Minutes without any packet from the node until "Active" turns off. The
#: node beacons every 30 minutes by default (POSINFO_INTERVAL in the firmware).
CONF_INACTIVE_MINUTES: Final = "inactive_minutes"
DEFAULT_INACTIVE_MINUTES: Final = 65
#: Read the LoRa queue and channel use (RX log page). Off by default: the
#: first request makes the node allocate its RX log buffer, which it keeps.
CONF_RADIO_STATS: Final = "radio_stats"
DEFAULT_RADIO_STATS: Final = False
INACTIVE_MINUTES_RANGE: Final = (10, 1440)
#: Options: a direct neighbour counts as lost after this many hours without
#: direct reception (0: off).
CONF_NEIGHBOUR_LOST_HOURS: Final = "neighbour_lost_hours"
DEFAULT_NEIGHBOUR_LOST_HOURS: Final = 6
NEIGHBOUR_LOST_HOURS_MAX: Final = 168
#: Neighbours are only judged while the MHeard list was read this recently
#: (the node or its web access may be away).
MHEARD_FRESH: Final = timedelta(minutes=15)
STATION_STALE_DAYS_LIMIT: Final = 90
#: Stations in the "stations" attribute (data mode), newest first.
STATION_ATTRIBUTE_LIMIT: Final = 100
#: Stations not heard for this long are dropped from the stored list.
STATION_STORE_MAX_AGE: Final = timedelta(days=STATION_STALE_DAYS_LIMIT)
STATION_STORE_VERSION: Final = 1
#: Delay before the station list is written to disk.
STATION_SAVE_DELAY: Final = 60
STATION_CLEANUP_INTERVAL: Final = timedelta(hours=1)


def signal_station(entry_id: str, callsign: str) -> str:
    """Dispatcher signal for state changes of one heard station."""
    return f"{DOMAIN}_station_{entry_id}_{callsign}"


def signal_new_station(entry_id: str) -> str:
    """Dispatcher signal: entities for a station should be added."""
    return f"{DOMAIN}_new_station_{entry_id}"


def signal_station_weather(entry_id: str) -> str:
    """Dispatcher signal: a station reported weather values for the first time."""
    return f"{DOMAIN}_station_weather_{entry_id}"


# --- access path --------------------------------------------------------------

#: How Home Assistant talks to the node: external UDP or KISS over TCP.
CONF_ACCESS: Final = "access"
ACCESS_UDP: Final = "udp"
ACCESS_KISS: Final = "kiss"
CONF_KISS_PORT: Final = "kiss_port"
CONF_KISS_PASSWORD: Final = "kiss_password"  # noqa: S105  # config key, not a secret
ISSUE_KISS_AUTH_OFF: Final = "kiss_auth_off"
#: Waits between reconnect attempts (seconds); the last one repeats.
KISS_RECONNECT_DELAYS: Final = (5, 10, 30, 60)

#: Options: the chat shows only the node's own groups (and the configured ones).
CONF_HIDE_FOREIGN_GROUPS: Final = "hide_foreign_groups"
DEFAULT_HIDE_FOREIGN_GROUPS: Final = True
