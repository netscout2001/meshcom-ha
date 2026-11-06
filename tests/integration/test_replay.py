"""Replay of the real (anonymised) capture through the whole integration."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
)

from custom_components.meshcom.const import (
    CONF_CALLSIGN,
    CONF_LISTEN_PORT,
    CONF_NODE_ID,
    DOMAIN,
    EVENT_DELIVERY,
    EVENT_MESSAGE,
)
from custom_components.meshcom.hub import UdpHub, _Protocol

from .conftest import NODE_HOST, OWN_TELEMETRY, datagram, inject

CAPTURE = Path(__file__).parent.parent / "lib" / "fixtures" / "capture_2026-11-06.anon.jsonl"
CAPTURE_HOST = "192.0.2.15"


def _capture_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="OWN1-12",
        unique_id="100000",
        data={
            CONF_HOST: CAPTURE_HOST,
            CONF_LISTEN_PORT: 1799,
            CONF_CALLSIGN: "OWN1-12",
            CONF_NODE_ID: 0x100000,
        },
    )


async def test_replay_capture(hass: HomeAssistant) -> None:
    """All packets of the capture go through hub, node and entities."""
    entry = _capture_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    messages = async_capture_events(hass, EVENT_MESSAGE)
    deliveries = async_capture_events(hass, EVENT_DELIVERY)

    # The capture is replayed at once instead of over 35 minutes; switch off
    # the rate limit for this test only.
    with patch("custom_components.meshcom.hub._TokenBucket.take", return_value=True):
        for line in CAPTURE.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            entry.runtime_data.hub.handle_datagram(record["raw"].encode(), record["src"])
    await hass.async_block_till_done()

    hub = entry.runtime_data.hub
    node = entry.runtime_data.node
    assert hub.accepted == 161
    assert hub.dropped["unknown_sender"] == 2  # the two test packets
    assert node.messages_sent == 2
    # broadcast, DM reply, four group messages, one "TEST"; not the DM
    # between two other stations and not the remote-management traffic
    assert node.messages_received == 7
    assert len(messages) == 10
    assert sum(1 for m in messages if m.data["to_me"]) == 7
    # the third acknowledgement in the capture belongs to other stations
    assert len(deliveries) == 2
    assert [d.data["sequence"] for d in deliveries] == [724, 725]
    assert node.stations_heard() > 20
    assert hass.states.get("sensor.meshcom_own1_12_battery").state == "96"  # type: ignore[union-attr]
    station = node.stations["TST1-2"]
    assert station.hops == 2
    assert station.rssi == -128


async def test_delivery_status_datagram(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The node's own ack datagram fires a delivery event."""
    events = async_capture_events(hass, EVENT_DELIVERY)
    inject(init_integration, datagram(type="ack", msg_id="63CF32D4", status=9))
    inject(
        init_integration,
        datagram(type="ack", msg_id="63CF32D4", status=2, via="udp", **{"from": "DO8RE-9"}),
    )
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["status"] == "delivered"


async def test_ack_for_other_station_is_ignored(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """An acknowledgement addressed to someone else does not count (C-13)."""
    events = async_capture_events(hass, EVENT_DELIVERY)
    inject(
        init_integration,
        datagram(
            src_type="lora",
            type="msg",
            src="TST1-1",
            dst="TST2-2",
            msg="TST2-2   :ack1",
            msg_id="40000001",
            firmware=40,
            fw_sub="a",
            rssi=-90,
            snr=1,
        ),
    )
    await hass.async_block_till_done()
    assert events == []


async def test_time_beacon_and_remote_telemetry(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Time beacons keep the node active; remote telemetry registers the station."""
    inject(
        init_integration,
        datagram(
            src_type="udp",
            type="msg",
            src="TST6-63",
            dst="*",
            msg="{CET}2026-11-06 09:28:39",
            msg_id="40001AE4",
            firmware=0,
            fw_sub="#",
            rssi=0,
            snr=0,
        ),
    )
    inject(
        init_integration,
        datagram(src_type="lora", type="tele", src="TST9-12", batt=50, temp1=5),
    )
    await hass.async_block_till_done()
    node = init_integration.runtime_data.node
    assert node.active
    assert "TST9-12" in node.stations


async def test_active_turns_off(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """Without packets the node becomes inactive after the timeout."""
    inject(init_integration, OWN_TELEMETRY)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.meshcom_do8re_12_active").state == "on"  # type: ignore[union-attr]
    future = dt_util.utcnow() + timedelta(minutes=70)
    init_integration.runtime_data.node.last_packet = dt_util.utcnow() - timedelta(minutes=70)
    async_fire_time_changed(hass, future)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.meshcom_do8re_12_active").state == "off"  # type: ignore[union-attr]


async def test_station_limit_and_dedup_window(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Station list and duplicate filter stay bounded (C-09, C-10)."""
    node = init_integration.runtime_data.node
    for index in range(520):
        node._station(f"TST{index}-1", dt_util.utcnow())
    assert len(node.stations) == 500
    node._seen[("msg", 1)] = dt_util.utcnow() - timedelta(minutes=20)
    assert not node._is_duplicate("msg", 2)
    assert ("msg", 1) not in node._seen


async def test_restore_battery(hass: HomeAssistant, mock_config_entry: MockConfigEntry) -> None:
    """The battery level survives a restart until the next beacon."""
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State("sensor.meshcom_do8re_12_battery", "88"),
                {"native_value": 88, "native_unit_of_measurement": "%"},
            )
        ],
    )
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.meshcom_do8re_12_battery").state == "88"  # type: ignore[union-attr]


async def test_hub_socket_handling() -> None:
    """Protocol callbacks, sending and closing."""
    hub = UdpHub(1799)
    received: list[object] = []
    unregister = hub.register(NODE_HOST, received.append)
    protocol = _Protocol(hub)
    protocol.datagram_received(OWN_TELEMETRY, (NODE_HOST, 1799))
    protocol.error_received(OSError("boom"))
    assert len(received) == 1

    try:
        hub.send(NODE_HOST, b"{}")
    except ConnectionError:
        pass
    else:
        raise AssertionError("send on a closed hub must fail")

    transport = MagicMock()
    hub._transport = transport
    hub.send(NODE_HOST, b"{}")
    transport.sendto.assert_called_once_with(b"{}", (NODE_HOST, 1799))
    hub.close()
    transport.close.assert_called_once()
    unregister()
    unregister()
    assert hub.idle
