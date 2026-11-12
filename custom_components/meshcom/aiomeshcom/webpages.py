"""Values from the node's HTML pages (firmware 4.40a).

The web interface has no machine-readable API for these values. Each parser
accepts only the fixed shapes the firmware prints (web_functions.cpp) and
checks every value against a plausible range; anything else stays None. A
firmware that changes a page therefore loses single values, never more.

Deliberately not read: WLAN name, BSSID and IP addresses (info page) and the
node's position (position page) - Home Assistant needs none of them here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

#: Node pages (fetched in the same login session as the settings).
POSITION_PAGE: Final = "/?page=position"
#: The RX log page carries the LoRa queue panel. Its first request makes the
#: node allocate the RX log buffer, which it then keeps filling: only fetched
#: when the user enables it.
RXLOG_PAGE: Final = "/?page=rxlog"

# Subheader of every page: the node's current local time, the same clock the
# start date is written with. Their difference is the uptime, without any
# time zone conversion.
_NOW_RE: Final = re.compile(
    r'<p class="font-small">(\d{4})-(\d{2})-(\d{2})&nbsp;(\d{2}):(\d{2}):(\d{2})&nbsp;'
)
_START_RE: Final = re.compile(
    r"<tr><td>Start Date</td><td>(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})</td></tr>"
)
_HARDWARE_RE: Final = re.compile(r"<tr><td>Hardware</td><td>([A-Za-z0-9_+]{1,24})</td></tr>")
_FREQUENCY_RE: Final = re.compile(r"<tr><td>Frequency</td><td>(\d{3,4}\.\d{4}) MHz</td></tr>")
_BANDWIDTH_RE: Final = re.compile(r"<tr><td>Bandwidth</td><td>(\d{1,4}) kHz</td></tr>")
_SF_RE: Final = re.compile(r"<tr><td>Spreading Factor \(SF\)</td><td>(\d{1,2})</td></tr>")
_CR_RE: Final = re.compile(r"<tr><td>Coding Rate \(CR\)</td><td>(\d)</td></tr>")
_POWER_RE: Final = re.compile(r"<tr><td>TX Power</td><td>(-?\d{1,2}) dBm \(")
_WIFI_RSSI_RE: Final = re.compile(r"<tr><td>WiFi RSSI</td><td>(-?\d{1,3})</td></tr>")
_HOP_TEXT_RE: Final = re.compile(r"max_hop_text: (\d{1,2})<br>")
_HOP_POS_RE: Final = re.compile(r"max_hop_pos: (\d{1,2})<br>")
_BLOCKED_RE: Final = re.compile(
    r"<tr><td>Blocked calls</td><td>[^<]{0,400} \(dropped (\d{1,9})\)</td></tr>"
)
# "Server: <path> <host>, connected (last rx 10 s)<br>" and its other forms
# (gw_link_status.cpp). Only the state and the age are taken, not the host.
_SERVER_RE: Final = re.compile(r"Server: ([^<]{0,120})<br>")
_SERVER_STATES: Final = (
    (re.compile(r".*, connected \(last rx (\d{1,9}) s\)"), "connected"),
    (re.compile(r".*, no response for (\d{1,9}) s"), "lost"),
    (re.compile(r".*, no response yet"), "waiting"),
    (re.compile(r"(?:.*, )?no IP address"), "no_ip"),
    (re.compile(r"not selected"), "not_selected"),
    (re.compile(r"off"), "off"),
)

_SATELLITES_RE: Final = re.compile(
    r"<tr><td>Satellites</td><td>(\d{1,2}) - (fix|nofix) - HDOP (\d{1,3})</td></tr>"
)
_RATE_RE: Final = re.compile(r"<tr><td>Rate</td><td>(\d{1,6})</td></tr>")
_NEXT_RE: Final = re.compile(r"<tr><td>Next</td><td>(-?\d{1,7}) sec</td></tr>")
_GPS_RE: Final = re.compile(r"<tr><td>GPS</td><td>(on|off)</td></tr>")

_QUEUE_RE: Final = re.compile(r'<div id="mcq"((?: [a-z0-9-]{1,12}="[^"<>]{0,24}"\n?){1,40})></div>')
_ATTR_RE: Final = re.compile(r'data-([a-z0-9]{1,8})="([^"<>]{0,24})"')
_PRIORITIES: Final = ("crit", "high", "normal", "low", "bg")
_BACKPRESSURE: Final = {0: "accepted", 1: "slow_down", 2: "refused"}


def _number(pattern: re.Pattern[str], body: str, low: float, high: float) -> float | None:
    if (match := pattern.search(body)) is None:
        return None
    value = float(match.group(1))
    return value if low <= value <= high else None


def _integer(pattern: re.Pattern[str], body: str, low: int, high: int) -> int | None:
    value = _number(pattern, body, low, high)
    return None if value is None else int(value)


def _clock(match: re.Match[str] | None) -> datetime | None:
    if match is None:
        return None
    year, month, day, hour, minute, second = (int(part) for part in match.groups())
    try:
        # Node local time, only compared with another node local time.
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class NodeInfo:
    """Values of the info page beyond firmware and battery."""

    #: Seconds since the node had a valid time after its start.
    uptime_seconds: int | None = None
    hardware: str | None = None
    frequency_mhz: float | None = None
    bandwidth_khz: int | None = None
    spreading_factor: int | None = None
    #: 4/x coding rate; the page prints x.
    coding_rate: int | None = None
    tx_power_dbm: int | None = None
    wifi_rssi: int | None = None
    #: "connected", "lost", "waiting", "no_ip", "not_selected" or "off".
    server: str | None = None
    #: Seconds since the server last answered (connected / lost).
    server_age_seconds: int | None = None
    max_hop_text: int | None = None
    max_hop_pos: int | None = None
    #: Frames dropped from blocked callsigns since the start.
    blocked_dropped: int | None = None


def _server(body: str) -> tuple[str | None, int | None]:
    if (match := _SERVER_RE.search(body)) is None:
        return None, None
    text = match.group(1).strip()
    for pattern, state in _SERVER_STATES:
        if (state_match := pattern.fullmatch(text)) is not None:
            age = int(state_match.group(1)) if state_match.groups() else None
            return state, age
    return None, None


def parse_node_info(body: str) -> NodeInfo:
    """Further values of the info page; each one that does not fit is None."""
    now, start = _clock(_NOW_RE.search(body)), _clock(_START_RE.search(body))
    uptime = None
    if now is not None and start is not None:
        seconds = int((now - start).total_seconds())
        # A node runs for years at most; a negative value is a clock jump.
        uptime = seconds if 0 <= seconds <= 10 * 365 * 86400 else None
    hardware = _HARDWARE_RE.search(body)
    server, server_age = _server(body)
    return NodeInfo(
        uptime_seconds=uptime,
        hardware=hardware.group(1) if hardware else None,
        frequency_mhz=_number(_FREQUENCY_RE, body, 100, 3000),
        bandwidth_khz=_integer(_BANDWIDTH_RE, body, 7, 1625),
        spreading_factor=_integer(_SF_RE, body, 5, 12),
        coding_rate=_integer(_CR_RE, body, 5, 8),
        tx_power_dbm=_integer(_POWER_RE, body, -9, 30),
        wifi_rssi=_integer(_WIFI_RSSI_RE, body, -127, 0),
        server=server,
        server_age_seconds=server_age,
        max_hop_text=_integer(_HOP_TEXT_RE, body, 0, 15),
        max_hop_pos=_integer(_HOP_POS_RE, body, 0, 15),
        blocked_dropped=_integer(_BLOCKED_RE, body, 0, 10**9),
    )


@dataclass(frozen=True, slots=True)
class GpsInfo:
    """GPS state from the position page (not the position itself)."""

    enabled: bool | None = None
    satellites: int | None = None
    fix: bool | None = None
    hdop: int | None = None
    #: Seconds between position beacons.
    beacon_interval: int | None = None
    #: Seconds until the next beacon.
    next_beacon: int | None = None


def parse_position_page(body: str) -> GpsInfo | None:
    """GPS values of the position page; None if it is not that page."""
    if "Position Information" not in body:
        return None
    satellites = _SATELLITES_RE.search(body)
    gps = _GPS_RE.search(body)
    sat_count = int(satellites.group(1)) if satellites else None
    hdop = int(satellites.group(3)) if satellites else None
    return GpsInfo(
        enabled=None if gps is None else gps.group(1) == "on",
        satellites=sat_count if sat_count is not None and sat_count <= 64 else None,
        fix=None if satellites is None else satellites.group(2) == "fix",
        hdop=hdop if hdop is not None and hdop <= 99 else None,
        beacon_interval=_integer(_RATE_RE, body, 1, 86400),
        next_beacon=_integer(_NEXT_RE, body, 0, 86400),
    )


@dataclass(frozen=True, slots=True)
class RadioStats:
    """LoRa queue and channel use from the RX log page (5-minute window)."""

    queue_used: int
    queue_size: int
    #: Queued frames per priority: crit, high, normal, low, bg.
    queue_by_priority: dict[str, int] = field(default_factory=dict)
    #: Frames that wait for an acknowledgement.
    waiting_ack: int = 0
    #: Queue level from which the node asks to slow down / refuses.
    slow_down_at: int | None = None
    refuse_at: int | None = None
    #: "accepted", "slow_down" or "refused" for own messages.
    state: str | None = None
    #: Values of the last completed 5-minute window; None before the first.
    rx_percent: float | None = None
    tx_percent: float | None = None
    dropped: int | None = None
    new_ids: int | None = None
    duplicates: int | None = None
    #: Estimated time a message id stays in the dedup memory (minutes).
    dedup_window_minutes: int | None = None
    #: Seconds since that window ended.
    window_age_seconds: int | None = None


def _attr(values: dict[str, str], name: str, high: int) -> int | None:
    raw = values.get(name)
    if raw is None or not re.fullmatch(r"-?\d{1,10}", raw):
        return None
    number = int(raw)
    return number if 0 <= number <= high else None


def parse_rxlog_page(body: str) -> RadioStats | None:
    """The LoRa queue panel: ``<div id="mcq" data-ring="20" data-p0="1" ...></div>``.

    The firmware writes the values as data attributes and renders them with
    JavaScript (mcRenderQueue in web_functions.cpp); the percentages are
    computed the same way: busy milliseconds / window length.
    """
    if (match := _QUEUE_RE.search(body)) is None:
        return None
    values = dict(_ATTR_RE.findall(match.group(1)))
    size = _attr(values, "ring", 1000)
    used = _attr(values, "p0", 1000)
    if not size or used is None or used > size:
        return None
    by_priority = {
        name: _attr(values, f"p{index}", size) or 0 for index, name in enumerate(_PRIORITIES, 1)
    }
    window_done = values.get("win") == "1"
    interval = _attr(values, "int", 86400) or 300
    rx_ms, tx_ms = _attr(values, "rx", 10**9), _attr(values, "tx", 10**9)

    def percent(busy: int | None) -> float | None:
        if not window_done or busy is None:
            return None
        return round(min(100.0, busy / (interval * 1000) * 100), 1)

    backpressure = _attr(values, "bp", 2)
    return RadioStats(
        queue_used=used,
        queue_size=size,
        queue_by_priority=by_priority,
        waiting_ack=_attr(values, "w0", size) or 0,
        slow_down_at=_attr(values, "qrs", size),
        refuse_at=_attr(values, "qrt", size),
        state=None if backpressure is None else _BACKPRESSURE[backpressure],
        rx_percent=percent(rx_ms),
        tx_percent=percent(tx_ms),
        dropped=_attr(values, "drop", 10**6) if window_done else None,
        new_ids=_attr(values, "newid", 10**6) if window_done else None,
        duplicates=_attr(values, "dup", 10**6) if window_done else None,
        dedup_window_minutes=(_attr(values, "dwin", 10**5) or None) if window_done else None,
        window_age_seconds=_attr(values, "age", 10**7) if window_done else None,
    )


# --- firmware update (/austatus, firmware 4.40a with the built-in update) ---------

#: JSON route of the node's built-in firmware update. Older firmware has no
#: such route: it answers 404 or with its info page, which is not JSON.
UPDATE_STATUS_PATH: Final = "/austatus"
#: Release tags such as "v4.40a.11.07"; "local" for a build without a tag.
_TAG_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,22}")
_ERROR_RE: Final = re.compile(r"[a-z0-9_]{1,23}")
_UPDATE_STATES: Final = frozenset({"idle", "busy", "ok", "fail"})
_UPDATE_JOBS: Final = frozenset({"none", "check", "download", "stagelan"})


@dataclass(frozen=True, slots=True)
class UpdateStatus:
    """State of the node's built-in firmware update."""

    #: Tag of the running firmware, e.g. "v4.40a.11.07" ("local": no tag).
    running: str
    #: Newest release the node found; None before its first check.
    available: str | None
    #: The node rates ``available`` as newer than the running firmware.
    newer: bool
    #: The release has an image for this board.
    installable: bool
    #: Tag of the image downloaded and ready to install; None if none.
    staged: str | None
    #: "idle", "busy", "ok" or "fail" (of the last job).
    state: str
    #: "none", "check", "download" or "stagelan".
    job: str
    #: Download progress 0..100 while a download runs.
    percent: int
    #: Error code of the last failed job, e.g. "lowheap_phone"; None if none.
    error: str | None
    #: The board can install (Safeboot partition present and usable).
    safeboot_ok: bool
    #: A phone is connected by Bluetooth (the download may lack memory).
    phone: bool


def _tag(value: object) -> str | None:
    if isinstance(value, str) and _TAG_RE.fullmatch(value):
        return value
    return None


def _flag(value: object) -> bool | None:
    if value in (0, 1) and not isinstance(value, bool):
        return value == 1
    return None


def parse_update_status(data: object) -> UpdateStatus | None:
    """The JSON object of ``/austatus``; None if it does not have the known shape."""
    if not isinstance(data, dict):
        return None
    running = _tag(data.get("run"))
    state = data.get("st")
    job = data.get("job")
    flags = {key: _flag(data.get(key)) for key in ("newer", "inst", "sbok", "phone")}
    percent = data.get("pct")
    if (
        running is None
        or not isinstance(state, str)
        or state not in _UPDATE_STATES
        or not isinstance(job, str)
        or job not in _UPDATE_JOBS
        or any(value is None for value in flags.values())
        or not isinstance(percent, int)
        or isinstance(percent, bool)
        or not 0 <= percent <= 100
    ):
        return None
    # The code may be followed by details ("lowheap_phone 41234"); only the
    # code is kept.
    raw_error = data.get("err")
    code = raw_error.split(" ", 1)[0] if isinstance(raw_error, str) else ""
    return UpdateStatus(
        running=running,
        available=_tag(data.get("avail")),
        newer=bool(flags["newer"]),
        installable=bool(flags["inst"]),
        staged=_tag(data.get("staged")),
        state=str(state),
        job=str(job),
        percent=percent,
        error=code if _ERROR_RE.fullmatch(code) else None,
        safeboot_ok=bool(flags["sbok"]),
        phone=bool(flags["phone"]),
    )
