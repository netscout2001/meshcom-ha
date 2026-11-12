"""Tests for the station mode: off, data only, one device per station."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.meshcom.const import (
    CONF_STATION_MAX,
    CONF_STATION_MODE,
    CONF_STATION_STALE_DAYS,
    DOMAIN,
    STATION_SAVE_DELAY,
)

from .conftest import NODE_ID, datagram, inject

HEARD = "sensor.meshcom_qx1yz_12_stations_heard_24_h"


def station_position(callsign: str, msg_id: str, lat: float = 50.7, batt: int = 88) -> bytes:
    return datagram(
        src_type="lora",
        type="pos",
        src=callsign,
        msg="",
        lat=lat,
        lat_dir="N",
        long=8.9,
        long_dir="E",
        aprs_symbol="#",
        aprs_symbol_group="/",
        hw_id=3,
        msg_id=msg_id,
        alt=1800,
        lora_mod=8,
        max_hop=5,
        batt=batt,
        firmware=40,
        fw_sub="a",
        rssi=-97,
        snr=6,
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry, **options: Any) -> MockConfigEntry:
    entry.add_to_hass(hass)
    if options:
        hass.config_entries.async_update_entry(entry, options=options)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _station_devices(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, dr.DeviceEntry]:
    registry = dr.async_get(hass)
    prefix = f"{NODE_ID:06x}_"
    found = {}
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        for _, identifier in device.identifiers:
            if identifier.startswith(prefix):
                found[identifier[len(prefix) :]] = device
    return found


# --- data mode (default) -------------------------------------------------------


async def test_data_mode_list_attribute(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """By default the stations are a list attribute, newest first, not recorded."""
    entry = await _setup(hass, mock_config_entry)
    inject(entry, station_position("QB0AAA-12", "40000101"))
    inject(entry, station_position("QB0BBB-1", "40000102", batt=0))
    await hass.async_block_till_done()
    state = hass.states.get(HEARD)
    assert state is not None
    assert state.state == "2"
    stations = state.attributes["stations"]
    assert [s["callsign"] for s in stations] == ["QB0BBB-1", "QB0AAA-12"]
    assert stations[1]["rssi"] == -97
    assert stations[1]["latitude"] == pytest.approx(50.7)
    assert stations[0]["battery"] is None  # 0 means unknown
    entity = hass.data["sensor"].get_entity(HEARD)
    assert "stations" in entity._unrecorded_attributes
    assert _station_devices(hass, entry) == {}


async def test_off_mode(hass: HomeAssistant, mock_config_entry: MockConfigEntry) -> None:
    """Off: only the count, no list and no devices."""
    entry = await _setup(hass, mock_config_entry, **{CONF_STATION_MODE: "off"})
    inject(entry, station_position("QB0AAA-12", "40000101"))
    await hass.async_block_till_done()
    state = hass.states.get(HEARD)
    assert state is not None
    assert state.state == "1"
    assert "stations" not in state.attributes
    assert _station_devices(hass, entry) == {}


async def test_unknown_mode_falls_back(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A tampered option value means the default mode."""
    entry = await _setup(hass, mock_config_entry, **{CONF_STATION_MODE: "everything"})
    inject(entry, station_position("QB0AAA-12", "40000101"))
    await hass.async_block_till_done()
    assert "stations" in hass.states.get(HEARD).attributes  # type: ignore[union-attr]


# --- entities mode -----------------------------------------------------------


async def test_entities_mode_creates_devices(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Each heard station gets a device behind the own node, with its entities."""
    entry = await _setup(hass, mock_config_entry, **{CONF_STATION_MODE: "entities"})
    inject(entry, station_position("QB0AAA-12", "40000101"))
    await hass.async_block_till_done()

    devices = _station_devices(hass, entry)
    assert list(devices) == ["QB0AAA-12"]
    device = devices["QB0AAA-12"]
    assert device.name == "QB0AAA-12"
    own = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, f"{NODE_ID:06x}")})
    assert own is not None
    assert device.via_device_id == own.id

    entities = {
        e.translation_key: e.entity_id
        for e in er.async_entries_for_device(er.async_get(hass), device.id)
    }
    assert set(entities) == {
        "station_last_heard",
        "station_battery",
        "station_rssi",
        "station_snr",
        "station_hears_me_snr",
        "station_hops",
        "station_position",
        "station_direct",
    }
    assert hass.states.get(entities["station_battery"]).state == "88"  # type: ignore[union-attr]
    assert hass.states.get(entities["station_rssi"]).state == "-97"  # type: ignore[union-attr]
    tracker = hass.states.get(entities["station_position"])
    assert tracker is not None
    assert tracker.attributes["latitude"] == pytest.approx(50.7)

    # An update of the station reaches its entities.
    inject(entry, station_position("QB0AAA-12", "40000103", lat=50.8, batt=70))
    await hass.async_block_till_done()
    assert hass.states.get(entities["station_battery"]).state == "70"  # type: ignore[union-attr]
    # In entities mode there is no list attribute.
    assert "stations" not in hass.states.get(HEARD).attributes  # type: ignore[union-attr]


async def test_device_limit(hass: HomeAssistant, mock_config_entry: MockConfigEntry) -> None:
    """Above the limit stations are remembered but get no device."""
    entry = await _setup(
        hass, mock_config_entry, **{CONF_STATION_MODE: "entities", CONF_STATION_MAX: 1}
    )
    inject(entry, station_position("QB0AAA-12", "40000101"))
    inject(entry, station_position("QB0BBB-12", "40000102"))
    await hass.async_block_till_done()
    assert list(_station_devices(hass, entry)) == ["QB0AAA-12"]
    assert "QB0BBB-12" in entry.runtime_data.node.stations


async def test_stale_devices_removed(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """Devices of stations not heard for the configured days are removed."""
    entry = await _setup(
        hass, mock_config_entry, **{CONF_STATION_MODE: "entities", CONF_STATION_STALE_DAYS: 2}
    )
    inject(entry, station_position("QB0AAA-12", "40000101"))
    await hass.async_block_till_done()
    freezer.tick(timedelta(days=1))
    inject(entry, station_position("QB0BBB-12", "40000102"))
    await hass.async_block_till_done()
    assert set(_station_devices(hass, entry)) == {"QB0AAA-12", "QB0BBB-12"}

    freezer.tick(timedelta(days=1, hours=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert set(_station_devices(hass, entry)) == {"QB0BBB-12"}
    assert entry.runtime_data.stations.tracked == {"QB0BBB-12"}

    # Heard again: the device comes back.
    inject(entry, station_position("QB0AAA-12", "40000103"))
    await hass.async_block_till_done()
    assert set(_station_devices(hass, entry)) == {"QB0AAA-12", "QB0BBB-12"}


async def test_switch_to_data_removes_devices(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Leaving the entities mode removes the station devices."""
    entry = await _setup(hass, mock_config_entry, **{CONF_STATION_MODE: "entities"})
    inject(entry, station_position("QB0AAA-12", "40000101"))
    await hass.async_block_till_done()
    assert _station_devices(hass, entry)

    hass.config_entries.async_update_entry(entry, options={CONF_STATION_MODE: "data"})
    await hass.async_block_till_done()
    assert entry.state.name == "LOADED"
    assert _station_devices(hass, entry) == {}
    # The station itself survived the reload (stored).
    state = hass.states.get(HEARD)
    assert state is not None
    assert [s["callsign"] for s in state.attributes["stations"]] == ["QB0AAA-12"]


async def test_data_update_does_not_reload(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Changing entry data (pinning the login) keeps the entry running."""
    entry = await _setup(hass, mock_config_entry)
    runtime = entry.runtime_data
    hass.config_entries.async_update_entry(entry, data={**entry.data, "web_auth": "hmac"})
    await hass.async_block_till_done()
    assert entry.runtime_data is runtime


async def test_remove_device(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Station devices can be deleted by the user; the own node cannot."""
    assert await async_setup_component(hass, "config", {})
    entry = await _setup(hass, mock_config_entry, **{CONF_STATION_MODE: "entities"})
    inject(entry, station_position("QB0AAA-12", "40000101"))
    await hass.async_block_till_done()
    registry = dr.async_get(hass)
    own = registry.async_get_device(identifiers={(DOMAIN, f"{NODE_ID:06x}")})
    assert own is not None
    station = _station_devices(hass, entry)["QB0AAA-12"]
    client = await hass_ws_client(hass)

    async def _remove(device_id: str) -> bool:
        await client.send_json_auto_id(
            {
                "type": "config/device_registry/remove_config_entry",
                "config_entry_id": entry.entry_id,
                "device_id": device_id,
            }
        )
        response = await client.receive_json()
        return bool(response["success"])

    assert await _remove(own.id) is False
    assert await _remove(station.id) is True
    await hass.async_block_till_done()
    assert _station_devices(hass, entry) == {}
    assert entry.runtime_data.stations.tracked == set()

    inject(entry, station_position("QB0AAA-12", "40000102"))
    await hass.async_block_till_done()
    assert list(_station_devices(hass, entry)) == ["QB0AAA-12"]


# --- persistence -------------------------------------------------------------


async def test_stations_survive_restart(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    """The station list is written to disk and read back on setup."""
    entry = await _setup(hass, mock_config_entry, **{CONF_STATION_MODE: "entities"})
    inject(entry, station_position("QB0AAA-12", "40000101"))
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=STATION_SAVE_DELAY + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    key = f"{DOMAIN}.stations.{entry.entry_id}"
    stored = hass_storage[key]["data"]["stations"]
    assert [s["callsign"] for s in stored] == ["QB0AAA-12"]

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert "QB0AAA-12" in entry.runtime_data.node.stations
    assert list(_station_devices(hass, entry)) == ["QB0AAA-12"]

    # Removing the entry deletes the file.
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage


async def test_stored_data_validated(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, hass_storage: dict[str, Any]
) -> None:
    """Tampered or old entries in the station file are dropped."""
    now = dt_util.utcnow()
    good = {
        "callsign": "QB0AAA-12",
        "last_heard": (now - timedelta(hours=1)).isoformat(),
        "rssi": -90,
        "snr": 5,
        "hops": 2,
        "battery": 77,
        "latitude": 50.0,
        "longitude": 9.0,
        "firmware": "4.40a",
    }
    hass_storage[f"{DOMAIN}.stations.{mock_config_entry.entry_id}"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.stations.{mock_config_entry.entry_id}",
        "data": {
            "stations": [
                good,
                {**good, "callsign": "<script>"},
                {**good, "callsign": "QB0OLD-1", "last_heard": "2020-01-01T00:00:00+00:00"},
                {**good, "callsign": "QB0NTZ-1", "last_heard": "2026-01-01T00:00:00"},
                {**good, "callsign": "QB0BAD-1", "last_heard": "yesterday"},
                {**good, "callsign": "QB0VAL-1", "rssi": "x", "battery": 500, "snr": True},
                {**good, "callsign": "QB0FW-1", "hops": 2.5, "firmware": "x" * 50},
                "not a dict",
                {**good, "callsign": 12},
            ]
        },
    }
    entry = await _setup(hass, mock_config_entry)
    stations = entry.runtime_data.node.stations
    assert set(stations) == {"QB0AAA-12", "QB0VAL-1", "QB0FW-1"}
    assert stations["QB0AAA-12"].battery == 77
    assert stations["QB0VAL-1"].rssi is None
    assert stations["QB0VAL-1"].battery is None
    assert stations["QB0VAL-1"].snr is None
    assert stations["QB0FW-1"].hops is None
    assert stations["QB0FW-1"].firmware is None


@pytest.mark.parametrize("data", [None, {"stations": "x"}, ["x"]])
async def test_stored_data_unusable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
    data: Any,
) -> None:
    """A station file without a list starts empty."""
    key = f"{DOMAIN}.stations.{mock_config_entry.entry_id}"
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": data}
    entry = await _setup(hass, mock_config_entry)
    assert len(entry.runtime_data.node.stations) == 0
