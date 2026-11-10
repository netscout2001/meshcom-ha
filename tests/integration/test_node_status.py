"""Node dashboard: web page values, radio sensors, activity, delivery, neighbours."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.meshcom.activity import ACTIVITY_HOURS, ActivityLog
from custom_components.meshcom.aiomeshcom.webapi import MHeardEntry, WebConnectionError
from custom_components.meshcom.aiomeshcom.webpages import GpsInfo, NodeInfo, RadioStats
from custom_components.meshcom.const import DOMAIN

from .conftest import (
    ACK_TEXT,
    INCOMING_MESSAGE,
    OWN_MESSAGE,
    FakeWebClient,
    datagram,
    inject,
)

INFO = NodeInfo(
    uptime_seconds=3600,
    hardware="TBEAM_AXP2101",
    frequency_mhz=433.175,
    bandwidth_khz=250,
    spreading_factor=11,
    coding_rate=6,
    tx_power_dbm=20,
    wifi_rssi=-56,
    server="connected",
    server_age_seconds=10,
    max_hop_text=4,
    max_hop_pos=2,
    blocked_dropped=0,
)
GPS = GpsInfo(enabled=True, satellites=10, fix=True, hdop=0, beacon_interval=1800, next_beacon=60)
RADIO = RadioStats(
    queue_used=3,
    queue_size=20,
    queue_by_priority={"crit": 0, "high": 1, "normal": 1, "low": 0, "bg": 1},
    waiting_ack=1,
    slow_down_at=5,
    refuse_at=16,
    state="accepted",
    rx_percent=11.4,
    tx_percent=4.4,
    dropped=0,
    new_ids=13,
    duplicates=8,
    dedup_window_minutes=27,
    window_age_seconds=186,
)
NEIGHBOUR = MHeardEntry(
    callsign="QR1ABC-12", age_minutes=1, hears_me_snr=-6, relay_role="super", it_hears=9
)


def _direct(text: str, msg_id: str) -> bytes:
    return datagram(
        src_type="lora",
        type="msg",
        src="QR1ABC-12",
        dst="QX1YZ-12",
        msg=text,
        msg_id=msg_id,
        firmware=40,
        fw_sub="a",
        rssi=-100,
        snr=3,
        hw_id=3,
        lora_mod=8,
        max_hop=4,
    )


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, *, radio: bool = False
) -> MockConfigEntry:
    if radio:
        entry.add_to_hass(hass)
        hass.config_entries.async_update_entry(entry, options={"radio_stats": True})
    else:
        entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _status(
    hass: HomeAssistant, ws: WebSocketGenerator, entry: MockConfigEntry
) -> dict[str, Any]:
    client = await ws(hass)
    await client.send_json_auto_id({"type": "meshcom/chat/node_status", "entry_id": entry.entry_id})
    answer = await client.receive_json()
    assert answer["success"], answer
    result: dict[str, Any] = answer["result"]
    return result


async def test_radio_sensors_only_with_option(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """Without the option the RX log page is not read and no radio sensors exist."""
    web_client.radio = RADIO
    await _setup(hass, mock_config_entry)
    assert web_client.radio_requested is False
    assert hass.states.get("sensor.meshcom_qx1yz_12_channel_use_rx") is None


async def test_radio_sensors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    web_client: FakeWebClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Channel use and queue level from the queue panel; unavailable without it."""
    web_client.radio = RADIO
    await _setup(hass, mock_config_entry, radio=True)
    assert web_client.radio_requested is True
    rx = hass.states.get("sensor.meshcom_qx1yz_12_channel_use_rx")
    tx = hass.states.get("sensor.meshcom_qx1yz_12_channel_use_tx")
    queue = hass.states.get("sensor.meshcom_qx1yz_12_tx_queue")
    assert rx is not None
    assert tx is not None
    assert queue is not None
    assert (rx.state, rx.attributes["unit_of_measurement"]) == ("11.4", "%")
    assert tx.state == "4.4"
    assert queue.state == "3"
    assert queue.attributes["size"] == 20
    assert queue.attributes["high"] == 1
    assert queue.attributes["own_messages"] == "accepted"
    web_client.radio = None
    await mock_config_entry.runtime_data.web.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get("sensor.meshcom_qx1yz_12_channel_use_rx")
    assert state is not None
    assert state.state == STATE_UNAVAILABLE


async def test_node_status(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    web_client: FakeWebClient,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Web page values, start time, neighbours and counters."""
    assert await async_setup_component(hass, "http", {})
    web_client.info, web_client.gps, web_client.mheard = INFO, GPS, [NEIGHBOUR]
    entry = await _setup(hass, mock_config_entry)
    status = await _status(hass, hass_ws_client, entry)
    web = status["web"]
    assert web["ok"] is True
    assert web["radio_enabled"] is False
    assert web["radio"] is None
    assert web["info"]["hardware"] == "TBEAM_AXP2101"
    assert web["info"]["server"] == "connected"
    assert web["gps"]["satellites"] == 10
    started = dt_util.parse_datetime(web["started"])
    fetched = dt_util.parse_datetime(web["fetched"])
    assert started is not None
    assert fetched is not None
    assert fetched - started == timedelta(hours=1)
    assert status["kiss_connected"] is None  # UDP node
    (neighbour,) = status["neighbours"]
    assert neighbour["callsign"] == "QR1ABC-12"
    assert (neighbour["hears_me_snr"], neighbour["relay_role"]) == (-6, "super")
    assert status["stations"] == {"heard_24h": 1, "direct": 1}
    # The info page has no network names or addresses to pass on.
    assert "ssid" not in str(web).lower()


async def test_activity_and_delivery(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Messages per hour by kind; own messages by delivery state."""
    assert await async_setup_component(hass, "http", {})
    entry = await _setup(hass, mock_config_entry)
    inject(entry, INCOMING_MESSAGE)  # group 262
    inject(entry, _direct("Hallo", "40000001"))
    inject(entry, OWN_MESSAGE)
    inject(entry, ACK_TEXT)  # delivers the own message (and is no chat message)
    await hass.async_block_till_done()
    status = await _status(hass, hass_ws_client, entry)
    activity = status["activity"]
    assert len(activity["hours"]) == ACTIVITY_HOURS
    assert activity["received_group"][-1] == 1
    assert activity["received_direct"][-1] >= 1
    assert activity["sent"][-1] == 1
    assert sum(activity["received_all"]) == 0
    assert status["delivery"]["delivered"] == 1
    assert status["counters"]["sent"] == 1


async def test_activity_survives_restart_and_ages(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    """The counters are stored; hours older than 48 h drop out."""
    entry = await _setup(hass, mock_config_entry)
    inject(entry, INCOMING_MESSAGE)
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(entry.entry_id)
    stored = hass_storage[f"{DOMAIN}.activity.{entry.entry_id}"]["data"]["hours"]
    assert sum(hour.get("received_group", 0) for hour in stored.values()) == 1
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    series = entry.runtime_data.activity.series(dt_util.utcnow())
    assert series["received_group"][-1] == 1
    freezer.tick(timedelta(hours=ACTIVITY_HOURS + 1))
    async_fire_time_changed(hass)
    assert sum(entry.runtime_data.activity.series(dt_util.utcnow())["received_group"]) == 0


async def test_activity_store_checked(
    hass: HomeAssistant, hass_storage: dict[str, Any], mock_config_entry: MockConfigEntry
) -> None:
    """Edited store values are skipped on load."""
    hour = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    key = f"{DOMAIN}.activity.{mock_config_entry.entry_id}"
    hass_storage[key] = {
        "version": 1,
        "key": key,
        "data": {
            "hours": {
                hour.isoformat(): {"sent": 3, "received_group": -1, "received_all": True},
                "yesterday": {"sent": 5},
                "2026-11-10T10:00:00": {"sent": 7},  # no time zone
                (hour - timedelta(days=5)).isoformat(): {"sent": 9},  # too old
            }
        },
    }
    log = ActivityLog(hass, mock_config_entry.entry_id)
    await log.async_load()
    assert log.buckets == {hour: {"sent": 3}}


async def test_node_status_permission(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
) -> None:
    """Only users who may read the node get its dashboard."""
    assert await async_setup_component(hass, "http", {})
    entry = await _setup(hass, mock_config_entry)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id({"type": "meshcom/chat/node_status", "entry_id": entry.entry_id})
    answer = await client.receive_json()
    assert answer["success"] is False
    assert answer["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("entry_id", ["missing", "x" * 64])
async def test_node_status_unknown_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    entry_id: str,
) -> None:
    """An unknown node is "not found"."""
    assert await async_setup_component(hass, "http", {})
    await _setup(hass, mock_config_entry)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "meshcom/chat/node_status", "entry_id": entry_id})
    answer = await client.receive_json()
    assert answer["error"]["code"] == "not_found"


async def test_node_status_radio_and_delivery_states(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    web_client: FakeWebClient,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Queue values with the option; every delivery state lands in its group."""
    assert await async_setup_component(hass, "http", {})
    web_client.radio = RADIO
    entry = await _setup(hass, mock_config_entry, radio=True)
    chat = entry.runtime_data.chat
    for index, status in enumerate(["held", "failed", "rejected", None, "sent"]):
        inject(entry, OWN_MESSAGE.replace(b"63CF32D4", f"63CF32{index:02X}".encode()))
        await hass.async_block_till_done()
        if status is not None:
            chat.async_set_status(f"63CF32{index:02X}", status)
        else:
            chat.messages[-1].status = None
    result = await _status(hass, hass_ws_client, entry)
    assert result["web"]["radio"]["rx_percent"] == 11.4
    assert result["web"]["radio_enabled"] is True
    assert result["delivery"] == {"delivered": 0, "pending": 2, "failed": 2, "unknown": 1}


async def test_node_status_before_first_poll(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    web_client: FakeWebClient,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """A node whose web API never answered: no web values, the rest is there."""
    assert await async_setup_component(hass, "http", {})
    web_client.error = WebConnectionError("down")
    entry = await _setup(hass, mock_config_entry)
    result = await _status(hass, hass_ws_client, entry)
    assert result["web"]["ok"] is False
    assert result["web"]["info"] is None
    assert result["web"]["started"] is None
    assert len(result["activity"]["hours"]) == 48


async def test_activity_removed_with_entry(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, hass_storage: dict[str, Any]
) -> None:
    """Removing the node deletes its stored activity."""
    entry = await _setup(hass, mock_config_entry)
    inject(entry, INCOMING_MESSAGE)
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(entry.entry_id)
    assert f"{DOMAIN}.activity.{entry.entry_id}" in hass_storage
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert f"{DOMAIN}.activity.{entry.entry_id}" not in hass_storage
