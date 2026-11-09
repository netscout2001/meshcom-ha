"""Weather values and radio path of other stations."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.meshcom.const import CONF_STATION_MODE, DOMAIN, STATION_SAVE_DELAY

from .conftest import datagram, inject
from .test_stations import _setup, _station_devices, station_position


def station_weather(src: str = "TST4-12,TST5-1,TST6-12", **values: float) -> bytes:
    """A telemetry packet of another station, heard via two relays."""
    fields: dict[str, Any] = {"temp1": 4.5, "temp2": 0, "hum": 92, "qfe": 958.2, "qnh": 1021.4}
    fields.update(values)
    return datagram(src_type="lora", type="tele", src=src, batt=80, **fields)


async def test_weather_and_path_of_station(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Telemetry of another station fills its weather values and path."""
    entry = await _setup(hass, mock_config_entry)
    inject(entry, station_weather())
    await hass.async_block_till_done()
    station = entry.runtime_data.node.stations["TST4-12"]
    assert (station.temperature, station.humidity) == (4.5, 92)
    assert (station.pressure_qnh, station.pressure_qfe) == (1021.4, 958.2)
    assert station.weather_time is not None
    assert station.path == ["TST5-1", "TST6-12"]

    # Telemetry without values (all zero) keeps the last weather values.
    inject(entry, station_weather(src="TST4-12", temp1=0, hum=0, qfe=0, qnh=0))
    await hass.async_block_till_done()
    assert station.temperature == 4.5
    assert station.path == []


async def test_weather_and_path_in_stations_tab(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """The panel gets weather values and path."""
    assert await async_setup_component(hass, "http", {})
    entry = await _setup(hass, mock_config_entry)
    inject(entry, station_position("TST4-12", "40000101"))
    inject(entry, station_weather())
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "meshcom/chat/stations", "entry_id": entry.entry_id})
    result = (await client.receive_json())["result"]
    station = result["stations"][0]
    assert station["callsign"] == "TST4-12"
    assert station["temperature"] == 4.5
    assert station["humidity"] == 92
    assert station["pressure"] == 1021.4
    assert station["pressure_qfe"] == 958.2
    assert station["weather_time"]
    assert station["path"] == ["TST5-1", "TST6-12"]


async def test_weather_sensors_in_entities_mode(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Weather sensors appear once a station with a device sends weather."""
    entry = await _setup(hass, mock_config_entry, **{CONF_STATION_MODE: "entities"})
    inject(entry, station_position("TST4-12", "40000101"))
    await hass.async_block_till_done()
    device = _station_devices(hass, entry)["TST4-12"]
    registry = er.async_get(hass)

    def keys() -> set[str | None]:
        return {e.translation_key for e in er.async_entries_for_device(registry, device.id)}

    assert "station_temperature" not in keys()
    inject(entry, station_weather())
    await hass.async_block_till_done()
    assert {"station_temperature", "station_humidity", "station_pressure"} <= keys()
    by_key = {
        e.translation_key: e.entity_id for e in er.async_entries_for_device(registry, device.id)
    }
    assert hass.states.get(by_key["station_temperature"]).state == "4.5"  # type: ignore[union-attr]
    assert hass.states.get(by_key["station_pressure"]).state == "1021.4"  # type: ignore[union-attr]

    # After a reload the weather sensors come back with the station.
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert "station_temperature" in keys()


async def test_weather_of_station_without_device(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """In data mode no weather sensors are created."""
    entry = await _setup(hass, mock_config_entry)
    inject(entry, station_weather())
    await hass.async_block_till_done()
    assert not [
        e
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.translation_key and e.translation_key.startswith("station_")
    ]


async def test_weather_and_path_stored(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Weather values and path are written to disk and read back."""
    entry = await _setup(hass, mock_config_entry)
    inject(entry, station_weather())
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=STATION_SAVE_DELAY + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    stored = hass_storage[f"{DOMAIN}.stations.{entry.entry_id}"]["data"]["stations"][0]
    assert stored["temperature"] == 4.5
    assert stored["path"] == ["TST5-1", "TST6-12"]

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    station = entry.runtime_data.node.stations["TST4-12"]
    assert station.pressure_qnh == 1021.4
    assert station.path == ["TST5-1", "TST6-12"]


async def test_stored_weather_and_path_validated(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, hass_storage: dict[str, Any]
) -> None:
    """Out-of-range values and broken paths from disk are dropped."""
    hass_storage[f"{DOMAIN}.stations.{mock_config_entry.entry_id}"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.stations.{mock_config_entry.entry_id}",
        "data": {
            "stations": [
                {
                    "callsign": "TST4-12",
                    "last_heard": "2026-11-09T10:00:00+00:00",
                    "temperature": 300,
                    "humidity": "92",
                    "pressure_qnh": 1021.4,
                    "weather_time": "not a time",
                    "path": ["TST5-1", "<script>"],
                },
                {
                    "callsign": "TST7-12",
                    "last_heard": "2026-11-09T10:00:00+00:00",
                    "path": ["TST5-1"] * 13,
                    "weather_time": "2026-11-09T09:00:00",
                },
            ]
        },
    }
    entry = await _setup(hass, mock_config_entry)
    stations = entry.runtime_data.node.stations
    first = stations["TST4-12"]
    assert (first.temperature, first.humidity, first.pressure_qnh) == (None, None, 1021.4)
    assert first.weather_time is None
    assert first.path == []
    assert stations["TST7-12"].path == []
    assert stations["TST7-12"].weather_time is None  # no time zone
