"""Watch mode: data only, plus a device for each watched station."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.meshcom.aiomeshcom.webapi import MHeardEntry
from custom_components.meshcom.const import (
    CONF_STATION_MODE,
    CONF_WATCHED_STATIONS,
    MAX_WATCHED_STATIONS,
)
from custom_components.meshcom.stations import watched_stations

from .conftest import FakeWebClient, inject
from .test_stations import HEARD, _setup, _station_devices, station_position

WATCH = {CONF_STATION_MODE: "watch", CONF_WATCHED_STATIONS: ["QB0AAA-12", "QB0CCC-12"]}


def _entities(hass: HomeAssistant, entry: MockConfigEntry, callsign: str) -> dict[str, str]:
    device = _station_devices(hass, entry)[callsign]
    return {
        e.translation_key or "": e.entity_id
        for e in er.async_entries_for_device(er.async_get(hass), device.id)
    }


async def test_only_watched_get_devices(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Watched stations get a device; all stations stay in the list attribute."""
    entry = await _setup(hass, mock_config_entry, **WATCH)
    inject(entry, station_position("QB0AAA-12", "40000101"))
    inject(entry, station_position("QB0BBB-12", "40000102"))
    await hass.async_block_till_done()
    assert set(_station_devices(hass, entry)) == {"QB0AAA-12"}
    state = hass.states.get(HEARD)
    assert state is not None
    assert {s["callsign"] for s in state.attributes["stations"]} == {"QB0AAA-12", "QB0BBB-12"}
    entities = _entities(hass, entry, "QB0AAA-12")
    assert {"station_snr", "station_hears_me_snr", "station_direct"} <= set(entities)
    snr = hass.states.get(entities["station_snr"])
    assert snr is not None
    assert float(snr.state) == 6


async def test_watched_values_from_mheard(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    web_client: FakeWebClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """SNR at the station and direct reception come from the MHeard list."""
    entry = await _setup(hass, mock_config_entry, **WATCH)
    inject(entry, station_position("QB0AAA-12", "40000101"))
    await hass.async_block_till_done()
    web_client.mheard = [
        MHeardEntry(callsign="QB0AAA-12", age_minutes=0, rssi=-110, snr=-4, hears_me_snr=-7)
    ]
    await entry.runtime_data.web.async_refresh_now()
    await hass.async_block_till_done()
    entities = _entities(hass, entry, "QB0AAA-12")
    hears_me = hass.states.get(entities["station_hears_me_snr"])
    direct = hass.states.get(entities["station_direct"])
    assert hears_me is not None
    assert hears_me.state == "-7"
    assert direct is not None
    assert direct.state == STATE_ON
    # Direct reception ends by time (MHeard window), refreshed every minute.
    web_client.mheard = []
    freezer.tick(timedelta(hours=4))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    direct = hass.states.get(entities["station_direct"])
    assert direct is not None
    assert direct.state == STATE_OFF


async def test_watched_not_removed_when_stale(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """A watched station keeps its device however long it is silent."""
    entry = await _setup(hass, mock_config_entry, **WATCH)
    inject(entry, station_position("QB0AAA-12", "40000101"))
    await hass.async_block_till_done()
    freezer.tick(timedelta(days=30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert set(_station_devices(hass, entry)) == {"QB0AAA-12"}
    # Also after a reload.
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert set(_station_devices(hass, entry)) == {"QB0AAA-12"}


async def test_unwatched_device_removed(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Taking a station off the list removes its device."""
    entry = await _setup(hass, mock_config_entry, **WATCH)
    inject(entry, station_position("QB0AAA-12", "40000101"))
    await hass.async_block_till_done()
    assert _station_devices(hass, entry)
    hass.config_entries.async_update_entry(
        entry, options={CONF_STATION_MODE: "watch", CONF_WATCHED_STATIONS: []}
    )
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert _station_devices(hass, entry) == {}


def test_watched_stations_option() -> None:
    """Invalid entries are dropped, duplicates removed, at most ten kept."""
    many = [f"QB{number}AA-1" for number in range(15)]
    options: dict[str, Any] = {CONF_WATCHED_STATIONS: ["QB0AAA-12", "QB0AAA-12", "<x>", 5]}
    assert watched_stations(options) == ["QB0AAA-12"]
    assert len(watched_stations({CONF_WATCHED_STATIONS: many})) == MAX_WATCHED_STATIONS
    assert watched_stations({CONF_WATCHED_STATIONS: "QB0AAA-12"}) == []
    assert watched_stations({}) == []


async def test_options_flow_watch_list(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The form checks callsigns and the limit of ten; direct neighbours first."""
    node = init_integration.runtime_data.node
    inject(init_integration, station_position("QB0AAA-12", "40000101"))
    await hass.async_block_till_done()
    node.apply_mheard([MHeardEntry(callsign="QB0DDD-12", age_minutes=0)])
    result = await hass.config_entries.options.async_init(init_integration.entry_id)
    assert result["data_schema"] is not None
    schema = result["data_schema"].schema
    selector = next(value for key, value in schema.items() if key == CONF_WATCHED_STATIONS)
    labels = [option["label"] for option in selector.config["options"]]
    assert labels[0] == "QB0DDD-12 (MHeard)"
    assert "QB0AAA-12" in labels

    base = {
        "groups": "",
        CONF_STATION_MODE: "watch",
        "station_max": 50,
        "station_stale_days": 7,
        "hide_foreign_groups": True,
        "inactive_minutes": 65,
        "radio_stats": False,
        "neighbour_lost_hours": 6,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**base, CONF_WATCHED_STATIONS: ["not a call"]}
    )
    assert result["errors"] == {CONF_WATCHED_STATIONS: "invalid_watched"}
    many = [f"QB{number}AA-1" for number in range(11)]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**base, CONF_WATCHED_STATIONS: many}
    )
    assert result["errors"] == {CONF_WATCHED_STATIONS: "too_many_watched"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**base, CONF_WATCHED_STATIONS: ["qb0aaa-12 ", "QB0DDD-12"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert init_integration.options[CONF_WATCHED_STATIONS] == ["QB0AAA-12", "QB0DDD-12"]
