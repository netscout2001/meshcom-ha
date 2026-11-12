"""Heard stations: persistence, and devices in the "entities" station mode.

Stations are stored per config entry so that the station list, the station
select and the station devices survive a restart. Stored data is read back
defensively: the file is user-writable, so every field is type-checked and
callsigns are validated again (security concept C-02, C-09).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .aiomeshcom import is_callsign
from .const import (
    CONF_STATION_MAX,
    CONF_STATION_MODE,
    CONF_STATION_STALE_DAYS,
    DEFAULT_STATION_MAX,
    DEFAULT_STATION_MODE,
    DEFAULT_STATION_STALE_DAYS,
    DOMAIN,
    MAX_PATH,
    MAX_STATIONS,
    STATION_CLEANUP_INTERVAL,
    STATION_MODE_ENTITIES,
    STATION_MODES,
    STATION_SAVE_DELAY,
    STATION_STORE_MAX_AGE,
    STATION_STORE_VERSION,
    signal_new_station,
)
from .node import MeshComNode, StationInfo

_LOGGER = logging.getLogger(__name__)


def station_mode(entry: ConfigEntry) -> str:
    """The configured station mode."""
    mode = entry.options.get(CONF_STATION_MODE, DEFAULT_STATION_MODE)
    return mode if mode in STATION_MODES else DEFAULT_STATION_MODE


def station_identifier(node_id: int, callsign: str) -> tuple[str, str]:
    """Device identifier of a heard station, unique per own node."""
    return (DOMAIN, f"{node_id:06x}_{callsign}")


def station_device_info(node: MeshComNode, callsign: str) -> DeviceInfo:
    """Device of a station heard by ``node``."""
    return DeviceInfo(
        identifiers={station_identifier(node.node_id, callsign)},
        name=callsign,
        manufacturer="MeshCom",
        model="MeshCom station",
        via_device=(DOMAIN, f"{node.node_id:06x}"),
    )


# --- persistence -------------------------------------------------------------


def _number(value: Any, kind: type, low: float, high: float) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if kind is int and not isinstance(value, int):
        return None
    return value if low <= value <= high else None


_HARDWARE_RE = re.compile(r"[A-Za-z0-9_+]{1,24}")
_RELAY_ROLES = frozenset({"super", "needed", "redundant"})


def _time(value: Any) -> datetime | None:
    parsed = dt_util.parse_datetime(value) if isinstance(value, str) else None
    return parsed if parsed is not None and parsed.tzinfo is not None else None


def _parse_station(raw: Any) -> StationInfo | None:
    if not isinstance(raw, Mapping):
        return None
    callsign = raw.get("callsign")
    heard = raw.get("last_heard")
    if not isinstance(callsign, str) or not is_callsign(callsign) or not isinstance(heard, str):
        return None
    last_heard = dt_util.parse_datetime(heard)
    if last_heard is None or last_heard.tzinfo is None:
        return None
    firmware = raw.get("firmware")
    weather = raw.get("weather_time")
    weather_time = dt_util.parse_datetime(weather) if isinstance(weather, str) else None
    if weather_time is not None and weather_time.tzinfo is None:
        weather_time = None
    path = raw.get("path")
    if not (
        isinstance(path, list)
        and len(path) <= MAX_PATH
        and all(isinstance(call, str) and is_callsign(call) for call in path)
    ):
        path = []
    hardware = raw.get("hardware")
    relay_role = raw.get("relay_role")
    gateway = raw.get("gateway")
    return StationInfo(
        callsign=callsign,
        last_heard=last_heard,
        rssi=_number(raw.get("rssi"), int, -200, 50),
        snr=_number(raw.get("snr"), float, -50, 50),
        hops=_number(raw.get("hops"), int, 0, 15),
        battery=_number(raw.get("battery"), int, 0, 100),
        latitude=_number(raw.get("latitude"), float, -90, 90),
        longitude=_number(raw.get("longitude"), float, -180, 180),
        firmware=firmware if isinstance(firmware, str) and len(firmware) <= 16 else None,
        temperature=_number(raw.get("temperature"), float, -60, 85),
        humidity=_number(raw.get("humidity"), float, 0, 100),
        pressure_qnh=_number(raw.get("pressure_qnh"), float, 800, 1100),
        pressure_qfe=_number(raw.get("pressure_qfe"), float, 300, 1100),
        weather_time=weather_time,
        path=list(path),
        direct_heard=_time(raw.get("direct_heard")),
        hardware=hardware
        if isinstance(hardware, str) and _HARDWARE_RE.fullmatch(hardware)
        else None,
        altitude=_number(raw.get("altitude"), int, -500, 9999),
        hears_me_snr=_number(raw.get("hears_me_snr"), int, -50, 50),
        relay_role=relay_role if relay_role in _RELAY_ROLES else None,
        only_it_hears=_number(raw.get("only_it_hears"), int, 0, 999),
        it_hears=_number(raw.get("it_hears"), int, 0, 999),
        neighbours=_number(raw.get("neighbours"), int, 0, 999),
        gateway=gateway if isinstance(gateway, bool) else None,
        lost=lost if isinstance(lost := raw.get("lost"), bool) else None,
    )


def _dump_station(station: StationInfo) -> dict[str, Any]:
    return {
        "callsign": station.callsign,
        "last_heard": station.last_heard.isoformat(),
        "rssi": station.rssi,
        "snr": station.snr,
        "hops": station.hops,
        "battery": station.battery,
        "latitude": station.latitude,
        "longitude": station.longitude,
        "firmware": station.firmware,
        "temperature": station.temperature,
        "humidity": station.humidity,
        "pressure_qnh": station.pressure_qnh,
        "pressure_qfe": station.pressure_qfe,
        "weather_time": station.weather_time.isoformat() if station.weather_time else None,
        "path": list(station.path),
        "direct_heard": station.direct_heard.isoformat() if station.direct_heard else None,
        "hardware": station.hardware,
        "altitude": station.altitude,
        "hears_me_snr": station.hears_me_snr,
        "relay_role": station.relay_role,
        "only_it_hears": station.only_it_hears,
        "it_hears": station.it_hears,
        "neighbours": station.neighbours,
        "gateway": station.gateway,
        "lost": station.lost,
    }


class StationStore:
    """The station list of one node on disk."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, STATION_STORE_VERSION, f"{DOMAIN}.stations.{entry_id}"
        )
        self._node: MeshComNode | None = None

    async def async_load(self) -> list[StationInfo]:
        """Stored stations not older than the maximum age."""
        try:
            data = await self._store.async_load()
        except (ValueError, OSError):  # pragma: no cover - broken file, start empty
            _LOGGER.warning("Stored station list is unreadable and is ignored")
            return []
        raw_list = data.get("stations") if isinstance(data, Mapping) else None
        if not isinstance(raw_list, list):
            return []
        limit = dt_util.utcnow() - STATION_STORE_MAX_AGE
        return [
            station
            for raw in raw_list[:MAX_STATIONS]
            if (station := _parse_station(raw)) is not None and station.last_heard >= limit
        ]

    @callback
    def async_schedule_save(self, node: MeshComNode) -> None:
        """Write the station list a little later (coalesces many packets)."""
        self._node = node
        self._store.async_delay_save(self._data, STATION_SAVE_DELAY)

    def _data(self) -> dict[str, Any]:
        stations = self._node.stations.values() if self._node else []
        return {"stations": [_dump_station(station) for station in stations]}

    async def async_save_now(self, node: MeshComNode) -> None:
        """Write immediately (unload)."""
        self._node = node
        await self._store.async_save(self._data())

    async def async_remove(self) -> None:
        """Delete the file (config entry removed)."""
        await self._store.async_remove()


# --- station devices ("entities" mode) ----------------------------------------


class StationDevices:
    """Decides which stations get a device, and removes stale ones."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, node: MeshComNode) -> None:
        self.hass = hass
        self.entry = entry
        self.node = node
        self.enabled = station_mode(entry) == STATION_MODE_ENTITIES
        self.max_devices: int = entry.options.get(CONF_STATION_MAX, DEFAULT_STATION_MAX)
        self.stale_after = timedelta(
            days=entry.options.get(CONF_STATION_STALE_DAYS, DEFAULT_STATION_STALE_DAYS)
        )
        #: Callsigns that have a device (and entities).
        self.tracked: set[str] = set()

    def _station_devices(self) -> dict[str, dr.DeviceEntry]:
        """Station devices of this entry in the registry, by callsign."""
        registry = dr.async_get(self.hass)
        prefix = f"{self.node.node_id:06x}_"
        devices: dict[str, dr.DeviceEntry] = {}
        for device in dr.async_entries_for_config_entry(registry, self.entry.entry_id):
            for domain, identifier in device.identifiers:
                if domain == DOMAIN and identifier.startswith(prefix):
                    devices[identifier[len(prefix) :]] = device
        return devices

    @callback
    def async_start(self) -> None:
        """Sync the registry with the mode and the stored stations."""
        registry = dr.async_get(self.hass)
        now = dt_util.utcnow()
        for callsign, device in self._station_devices().items():
            station = self.node.stations.get(callsign)
            keep = (
                self.enabled
                and station is not None
                and now - station.last_heard < self.stale_after
                and len(self.tracked) < self.max_devices
            )
            if keep:
                self.tracked.add(callsign)
            else:
                registry.async_remove_device(device.id)
        if self.enabled:
            # Stations heard recently but without a device yet, newest first.
            for station in reversed(self.node.stations.values()):
                self.async_station_heard(station.callsign, notify=False)
            self.entry.async_on_unload(
                async_track_time_interval(self.hass, self._cleanup, STATION_CLEANUP_INTERVAL)
            )

    @callback
    def async_station_heard(self, callsign: str, *, notify: bool = True) -> None:
        """A packet from ``callsign`` arrived."""
        if not self.enabled or callsign in self.tracked or not is_callsign(callsign):
            return
        station = self.node.stations.get(callsign)
        if station is None or dt_util.utcnow() - station.last_heard >= self.stale_after:
            return
        if len(self.tracked) >= self.max_devices:
            return
        self.tracked.add(callsign)
        if notify:
            async_dispatcher_send(self.hass, signal_new_station(self.entry.entry_id), callsign)

    @callback
    def _cleanup(self, _now: datetime | None = None) -> None:
        """Remove devices of stations not heard for too long (stale devices)."""
        registry = dr.async_get(self.hass)
        now = dt_util.utcnow()
        for callsign, device in self._station_devices().items():
            station = self.node.stations.get(callsign)
            if station is None or now - station.last_heard >= self.stale_after:
                registry.async_remove_device(device.id)
                self.tracked.discard(callsign)

    @callback
    def async_device_removed(self, callsign: str) -> None:
        """The user deleted a station device; it comes back when heard again."""
        self.tracked.discard(callsign)
