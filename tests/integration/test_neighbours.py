"""Events for new stations and for direct neighbours lost and back."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.meshcom.aiomeshcom.webapi import MHeardEntry
from custom_components.meshcom.const import (
    CONF_NEIGHBOUR_LOST_HOURS,
    EVENT_NEIGHBOUR_BACK,
    EVENT_NEIGHBOUR_LOST,
    EVENT_STATION_NEW,
)
from custom_components.meshcom.node import StationInfo
from custom_components.meshcom.stations import _dump_station, _parse_station

from .conftest import INCOMING_MESSAGE, FakeWebClient, inject

# Invented callsign (Q prefixes are not issued).
NEIGHBOUR = MHeardEntry(callsign="QR1ABC-12", age_minutes=0, rssi=-100, snr=3)


def _events(hass: HomeAssistant, event_type: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    @callback
    def _listener(event: Event) -> None:
        found.append(dict(event.data))

    hass.bus.async_listen(event_type, _listener)
    return found


async def _setup(hass: HomeAssistant, entry: MockConfigEntry, **options: Any) -> MockConfigEntry:
    entry.add_to_hass(hass)
    if options:
        hass.config_entries.async_update_entry(entry, options=options)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _poll(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.web.async_refresh_now()
    await hass.async_block_till_done()


async def _minute(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(timedelta(minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_station_new(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """Fired once per station: from a packet and from the MHeard list."""
    new = _events(hass, EVENT_STATION_NEW)
    await _setup(hass, mock_config_entry)
    inject(mock_config_entry, INCOMING_MESSAGE)
    inject(mock_config_entry, INCOMING_MESSAGE.replace(b"40000ED4", b"40000ED5"))
    web_client.mheard = [NEIGHBOUR]
    await _poll(hass, mock_config_entry)
    await _poll(hass, mock_config_entry)
    await hass.async_block_till_done()
    assert [event["callsign"] for event in new] == ["TST1-12", "QR1ABC-12"]
    assert new[0]["entry_id"] == mock_config_entry.entry_id
    assert new[0]["node"] == "QX1YZ-12"


async def test_neighbour_lost_and_back(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    web_client: FakeWebClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Lost after the set hours without direct reception, back when heard again."""
    lost = _events(hass, EVENT_NEIGHBOUR_LOST)
    back = _events(hass, EVENT_NEIGHBOUR_BACK)
    await _setup(hass, mock_config_entry, **{CONF_NEIGHBOUR_LOST_HOURS: 2})
    web_client.mheard = [NEIGHBOUR]
    await _poll(hass, mock_config_entry)
    await _minute(hass, freezer)
    assert lost == []
    # Still on the list (heard 90 minutes ago): not lost yet.
    freezer.tick(timedelta(minutes=90))
    web_client.mheard = [MHeardEntry(callsign="QR1ABC-12", age_minutes=90)]
    await _poll(hass, mock_config_entry)
    await _minute(hass, freezer)
    assert lost == []
    freezer.tick(timedelta(minutes=40))
    web_client.mheard = []
    await _poll(hass, mock_config_entry)
    await _minute(hass, freezer)
    assert [event["callsign"] for event in lost] == ["QR1ABC-12"]
    assert lost[0]["rssi"] == -100
    # Reported once only.
    await _minute(hass, freezer)
    assert len(lost) == 1
    web_client.mheard = [MHeardEntry(callsign="QR1ABC-12", age_minutes=1)]
    await _poll(hass, mock_config_entry)
    assert [event["callsign"] for event in back] == ["QR1ABC-12"]
    station = mock_config_entry.runtime_data.node.stations["QR1ABC-12"]
    assert station.lost is False


async def test_not_judged_without_fresh_list(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    web_client: FakeWebClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A node that is away (no fresh MHeard list) does not lose its neighbours."""
    lost = _events(hass, EVENT_NEIGHBOUR_LOST)
    await _setup(hass, mock_config_entry, **{CONF_NEIGHBOUR_LOST_HOURS: 1})
    web_client.mheard = [NEIGHBOUR]
    await _poll(hass, mock_config_entry)
    freezer.tick(timedelta(hours=3))
    await _minute(hass, freezer)
    assert lost == []


async def test_watch_off(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    web_client: FakeWebClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """0 hours switches the watch off."""
    lost = _events(hass, EVENT_NEIGHBOUR_LOST)
    await _setup(hass, mock_config_entry, **{CONF_NEIGHBOUR_LOST_HOURS: 0})
    web_client.mheard = [NEIGHBOUR]
    await _poll(hass, mock_config_entry)
    freezer.tick(timedelta(hours=200))
    web_client.mheard = []
    await _poll(hass, mock_config_entry)
    await _minute(hass, freezer)
    assert lost == []
    node = mock_config_entry.runtime_data.node
    assert not node.check_neighbours()


async def test_first_judgement_is_silent(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Stations stored before the watch existed are judged without events."""
    lost = _events(hass, EVENT_NEIGHBOUR_LOST)
    node = init_integration.runtime_data.node
    now = dt_util.utcnow()
    node.stations["QR1OLD-12"] = StationInfo(
        "QR1OLD-12", now - timedelta(days=3), direct_heard=now - timedelta(days=3)
    )
    node.stations["QR1NEW-12"] = StationInfo(
        "QR1NEW-12", now, direct_heard=now - timedelta(minutes=5)
    )
    node.mheard_read = now
    assert node.check_neighbours(now)
    await hass.async_block_till_done()
    assert lost == []
    assert node.stations["QR1OLD-12"].lost is True
    assert node.stations["QR1NEW-12"].lost is False


def test_lost_flag_stored() -> None:
    """The flag survives a restart; old files without it give None."""
    now = dt_util.utcnow()
    station = StationInfo("QR1ABC-12", now, direct_heard=now, lost=True)
    raw = _dump_station(station)
    assert raw["lost"] is True
    parsed = _parse_station(raw)
    assert parsed is not None
    assert parsed.lost is True
    raw.pop("lost")
    parsed = _parse_station(raw)
    assert parsed is not None
    assert parsed.lost is None
