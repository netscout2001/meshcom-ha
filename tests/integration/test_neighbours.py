"""Events for new stations and for direct neighbours lost and back."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.meshcom.aiomeshcom.webapi import MHeardEntry, WebConnectionError
from custom_components.meshcom.const import (
    CONF_NEIGHBOUR_LOST_HOURS,
    EVENT_NEIGHBOUR_BACK,
    EVENT_NEIGHBOUR_LOST,
    EVENT_STATION_NEW,
    STATION_NEW_BURST,
    STATION_NEW_INTERVAL,
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


async def test_station_new_limited(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Many invented callsigns at once do not flood automations."""
    new = _events(hass, EVENT_STATION_NEW)
    # 50 datagrams stay within the hub's per-source burst.
    for number in range(50):
        inject(
            init_integration,
            INCOMING_MESSAGE.replace(b"TST1-12", f"QA{number}X-1".encode()).replace(
                b"40000ED4", f"{0x50000000 + number:08X}".encode()
            ),
        )
    await hass.async_block_till_done()
    node = init_integration.runtime_data.node
    assert len(node.stations) == 50
    assert len(new) == STATION_NEW_BURST
    assert node.station_new_dropped == 50 - STATION_NEW_BURST
    # The budget refills slowly.
    freezer.tick(STATION_NEW_INTERVAL * 2)
    async_fire_time_changed(hass)
    inject(init_integration, INCOMING_MESSAGE.replace(b"40000ED4", b"6000AAAA"))
    inject(
        init_integration,
        INCOMING_MESSAGE.replace(b"TST1-12", b"QB1NEW-1").replace(b"40000ED4", b"6000AAAB"),
    )
    await hass.async_block_till_done()
    assert len(new) == STATION_NEW_BURST + 2


async def test_failed_poll_does_not_refresh_list(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    web_client: FakeWebClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """After a failed poll the old MHeard list is not taken as new again.

    Its ages would count from now: stations would look freshly heard and
    a lost neighbour would never be reported.
    """
    lost = _events(hass, EVENT_NEIGHBOUR_LOST)
    await _setup(hass, mock_config_entry, **{CONF_NEIGHBOUR_LOST_HOURS: 1})
    web_client.mheard = [NEIGHBOUR]
    await _poll(hass, mock_config_entry)
    node = mock_config_entry.runtime_data.node
    heard = node.stations["QR1ABC-12"].direct_heard
    freezer.tick(timedelta(hours=2))
    web_client.error = WebConnectionError("gone")
    await _poll(hass, mock_config_entry)
    assert node.stations["QR1ABC-12"].direct_heard == heard
    await _minute(hass, freezer)
    # The list is not fresh: no judgement, no event (node may be away).
    assert lost == []
    # The node answers again without the station: now it is lost.
    web_client.error = None
    web_client.mheard = []
    await _poll(hass, mock_config_entry)
    await _minute(hass, freezer)
    assert [event["callsign"] for event in lost] == ["QR1ABC-12"]


async def test_mheard_ages_count_from_read_time(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Ages count from when the node answered, never from the future."""
    node = init_integration.runtime_data.node
    read = dt_util.utcnow() - timedelta(minutes=10)
    node.apply_mheard([MHeardEntry(callsign="QR1ABC-12", age_minutes=5)], read=read)
    assert node.stations["QR1ABC-12"].direct_heard == read - timedelta(minutes=5)
    assert node.mheard_read == read
    later = dt_util.utcnow() + timedelta(hours=1)
    node.apply_mheard([], read=later)
    assert node.mheard_read is not None
    assert node.mheard_read <= dt_util.utcnow()
