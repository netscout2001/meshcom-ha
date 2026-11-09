"""Direct neighbours from the node's MHeard list (web API)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.meshcom.aiomeshcom.webapi import MHeardEntry
from custom_components.meshcom.const import CONF_STATION_MODE, DOMAIN, STATION_SAVE_DELAY

from .conftest import FakeWebClient, inject
from .test_stations import HEARD, _setup, _station_devices, station_position

# Invented callsigns and positions (Q prefixes are not issued).
HEY_ONLY = MHeardEntry(
    callsign="QR1ABC-12",
    age_minutes=2,
    last_frame="heartbeat",
    hardware="TBEAM_AXP2101",
    firmware="4.40a",
    rssi=-116,
    snr=-8,
    latitude=50.123,
    longitude=8.456,
    altitude=491,
    hears_me_snr=-11,
    relay_role="redundant",
    only_it_hears=0,
    it_hears=7,
    neighbours=6,
    gateway=False,
)
KNOWN = MHeardEntry(
    callsign="QB0AAA-12",
    age_minutes=0,
    last_frame="heartbeat",
    hardware="HELTEC_V3",
    firmware="4.40a",
    rssi=-90,
    snr=5,
    latitude=50.1,
    longitude=8.1,
    altitude=1500,
    hears_me_snr=None,
    relay_role="super",
    only_it_hears=13,
    it_hears=36,
    neighbours=34,
    gateway=True,
)


async def _poll(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.web.async_refresh()
    await hass.async_block_till_done()


async def test_heartbeat_only_station_appears(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """A station the node hears only by heartbeats shows up with its values."""
    entry = await _setup(hass, mock_config_entry)
    web_client.mheard = [HEY_ONLY]
    await _poll(hass, entry)
    station = entry.runtime_data.node.stations["QR1ABC-12"]
    now = dt_util.utcnow()
    assert station.is_direct(now)
    assert station.direct_heard is not None
    assert abs(now - timedelta(minutes=2) - station.direct_heard) < timedelta(seconds=5)
    assert station.last_heard == station.direct_heard
    assert (station.latitude, station.longitude, station.altitude) == (50.123, 8.456, 491)
    assert (station.rssi, station.snr, station.firmware) == (-116, -8.0, "4.40a")
    assert (station.hardware, station.hears_me_snr, station.relay_role) == (
        "TBEAM_AXP2101",
        -11,
        "redundant",
    )
    assert (station.only_it_hears, station.it_hears, station.neighbours, station.gateway) == (
        0,
        7,
        6,
        False,
    )
    state = hass.states.get(HEARD)
    assert state is not None
    assert state.attributes["stations"][0]["direct"] is True


async def test_packet_values_win(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """Position and signal from packets are kept; the neighbour values are added."""
    entry = await _setup(hass, mock_config_entry)
    inject(entry, station_position("QB0AAA-12", "40000101", lat=50.7))
    await hass.async_block_till_done()
    station = entry.runtime_data.node.stations["QB0AAA-12"]
    rssi, heard = station.rssi, station.last_heard
    web_client.mheard = [KNOWN]
    await _poll(hass, entry)
    assert (station.latitude, station.longitude) == (50.7, 8.9)
    assert station.rssi == rssi
    assert station.last_heard == heard  # not older, not moved by the minute rounding
    assert (station.relay_role, station.gateway, station.hears_me_snr) == ("super", True, None)


async def test_own_callsign_and_unreadable_page(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """The own node is not a station; an unreadable page changes nothing."""
    entry = await _setup(hass, mock_config_entry)
    node = entry.runtime_data.node
    web_client.mheard = [
        MHeardEntry(callsign=node.callsign, age_minutes=0),
        HEY_ONLY,
    ]
    await _poll(hass, entry)
    assert list(node.stations) == ["QR1ABC-12"]
    web_client.mheard = None
    await _poll(hass, entry)
    assert node.stations["QR1ABC-12"].relay_role == "redundant"


async def test_direct_flag_ages_out(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    web_client: FakeWebClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A station that left the MHeard list is no direct neighbour after 3 hours."""
    entry = await _setup(hass, mock_config_entry)
    web_client.mheard = [HEY_ONLY]
    await _poll(hass, entry)
    station = entry.runtime_data.node.stations["QR1ABC-12"]
    web_client.mheard = []
    freezer.tick(timedelta(hours=2))
    await _poll(hass, entry)
    assert station.is_direct(dt_util.utcnow())
    freezer.tick(timedelta(hours=1))
    assert not station.is_direct(dt_util.utcnow())


async def test_unchanged_list_does_not_notify(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """The same list again (minute-rounded age) does not touch the stations."""
    entry = await _setup(hass, mock_config_entry)
    node = entry.runtime_data.node
    heard: list[str] = []
    listener = node.station_listener
    assert listener is not None

    def _spy(callsign: str) -> None:
        heard.append(callsign)
        listener(callsign)

    node.station_listener = _spy
    web_client.mheard = [HEY_ONLY]
    await _poll(hass, entry)
    await _poll(hass, entry)
    assert heard == ["QR1ABC-12"]


async def test_entities_mode_creates_device(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """In the entities mode a heartbeat-only station gets its device too."""
    entry = await _setup(hass, mock_config_entry, **{CONF_STATION_MODE: "entities"})
    web_client.mheard = [HEY_ONLY]
    await _poll(hass, entry)
    assert list(_station_devices(hass, entry)) == ["QR1ABC-12"]


async def test_panel_and_store(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    web_client: FakeWebClient,
    hass_ws_client: WebSocketGenerator,
    hass_storage: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    """The panel gets the neighbour values; they survive a restart."""
    assert await async_setup_component(hass, "http", {})
    entry = await _setup(hass, mock_config_entry)
    web_client.mheard = [HEY_ONLY]
    await _poll(hass, entry)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "meshcom/chat/stations", "entry_id": entry.entry_id})
    (station,) = (await client.receive_json())["result"]["stations"]
    assert station["direct"] is True
    assert station["direct_heard"]
    assert station["hardware"] == "TBEAM_AXP2101"
    assert station["altitude"] == 491
    assert station["hears_me_snr"] == -11
    assert station["relay_role"] == "redundant"
    assert (station["only_it_hears"], station["it_hears"], station["neighbours"]) == (0, 7, 6)
    assert station["gateway"] is False

    freezer.tick(timedelta(seconds=STATION_SAVE_DELAY + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    stored = hass_storage[f"{DOMAIN}.stations.{entry.entry_id}"]["data"]["stations"]
    assert stored[0]["relay_role"] == "redundant"

    web_client.mheard = None
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    restored = entry.runtime_data.node.stations["QR1ABC-12"]
    assert (restored.hardware, restored.gateway, restored.it_hears) == ("TBEAM_AXP2101", False, 7)
    assert restored.is_direct(dt_util.utcnow())


async def test_stored_neighbour_values_checked(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, hass_storage: dict[str, Any]
) -> None:
    """Edited store values outside their range are dropped on load."""
    key = f"{DOMAIN}.stations.{mock_config_entry.entry_id}"
    data = {
        "stations": [
            {
                "callsign": "QR1ABC-12",
                "last_heard": dt_util.utcnow().isoformat(),
                "direct_heard": "yesterday",
                "hardware": "<script>",
                "altitude": 10**9,
                "hears_me_snr": "x",
                "relay_role": "boss",
                "only_it_hears": -1,
                "it_hears": True,
                "neighbours": 5000,
                "gateway": "yes",
            }
        ]
    }
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": data}
    entry = await _setup(hass, mock_config_entry)
    station = entry.runtime_data.node.stations["QR1ABC-12"]
    assert station.direct_heard is None
    assert station.hardware is None
    assert station.altitude is None
    assert station.hears_me_snr is None
    assert station.relay_role is None
    assert (station.only_it_hears, station.it_hears, station.neighbours) == (None, None, None)
    assert station.gateway is None


async def test_newer_direct_reception_moves_last_heard(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    web_client: FakeWebClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A heartbeat after the last packet makes the station newer."""
    entry = await _setup(hass, mock_config_entry)
    inject(entry, station_position("QB0AAA-12", "40000101"))
    inject(entry, station_position("QB0BBB-12", "40000102"))
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=30))
    web_client.mheard = [KNOWN]
    await _poll(hass, entry)
    node = entry.runtime_data.node
    assert node.stations["QB0AAA-12"].last_heard == dt_util.utcnow()
    assert list(node.stations)[-1] == "QB0AAA-12"


async def test_station_limit(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    web_client: FakeWebClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The station limit also holds for MHeard stations."""
    monkeypatch.setattr("custom_components.meshcom.node.MAX_STATIONS", 1)
    entry = await _setup(hass, mock_config_entry)
    web_client.mheard = [KNOWN, HEY_ONLY]
    await _poll(hass, entry)
    assert list(entry.runtime_data.node.stations) == ["QR1ABC-12"]
