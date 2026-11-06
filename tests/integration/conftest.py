"""Fixtures for the Home Assistant integration tests."""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.meshcom.const import (
    CONF_CALLSIGN,
    CONF_LISTEN_PORT,
    CONF_NODE_ID,
    DOMAIN,
)
from custom_components.meshcom.hub import UdpHub

NODE_HOST = "192.168.1.50"
NODE_ID = 0x63CF32D3 >> 10


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading the custom integration."""


@pytest.fixture(autouse=True)
def no_socket() -> Generator[None]:
    """Tests do not open a real UDP socket; datagrams are injected."""
    with patch.object(UdpHub, "async_start", return_value=None):
        yield


def datagram(**fields: Any) -> bytes:
    """Encode a packet like the node does."""
    return json.dumps(fields).encode()


OWN_POSITION = datagram(
    src_type="node",
    type="pos",
    src="DO8RE-12",
    msg="",
    lat=47.5,
    lat_dir="N",
    long=12.0,
    long_dir="E",
    aprs_symbol="-",
    aprs_symbol_group="/",
    hw_id=12,
    msg_id="63CF32D3",
    alt=1667,
    lora_mod=8,
    max_hop=2,
    batt=96,
    firmware="4.40",
    fw_sub="a",
    rssi=0,
    snr=0,
)
OWN_TELEMETRY_EMPTY = datagram(
    src_type="node",
    type="tele",
    src="DO8RE-12",
    temp1=0,
    temp2=0,
    hum=0,
    qfe=0,
    qnh=0,
    gas=0,
    co2=0,
)
OWN_TELEMETRY = datagram(
    src_type="node",
    type="tele",
    src="DO8RE-12",
    temp1=21.5,
    temp2=0,
    hum=40,
    qfe=965.1,
    qnh=1020.3,
    gas=0,
    co2=0,
)
INCOMING_MESSAGE = datagram(
    src_type="lora",
    type="msg",
    src="TST1-12,TST2-12",
    dst="262",
    msg="Hallo <b>Welt</b>",
    msg_id="40000ED4",
    firmware=40,
    fw_sub="a",
    rssi=-110,
    snr=-5,
    hw_id=3,
    lora_mod=8,
    max_hop=4,
)
OWN_MESSAGE = datagram(
    src_type="node",
    type="msg",
    src="DO8RE-12",
    dst="DO8RE-9",
    msg="Test2{724",
    msg_id="63CF32D4",
    firmware="4.40",
    fw_sub="a",
    rssi=0,
    snr=0,
    hw_id=12,
    lora_mod=8,
    max_hop=4,
)
ACK_TEXT = datagram(
    src_type="lora",
    type="msg",
    src="DO8RE-9",
    dst="DO8RE-12",
    msg="DO8RE-12 :ack724",
    msg_id="43758258",
    firmware=40,
    fw_sub="a",
    rssi=-92,
    snr=10,
    hw_id=3,
    lora_mod=8,
    max_hop=4,
)


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A configured node."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="DO8RE-12",
        unique_id=f"{NODE_ID:06x}",
        data={
            CONF_HOST: NODE_HOST,
            CONF_LISTEN_PORT: 1799,
            CONF_CALLSIGN: "DO8RE-12",
            CONF_NODE_ID: NODE_ID,
        },
    )


@pytest.fixture
async def init_integration(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> MockConfigEntry:
    """Set up the integration."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry


def inject(entry: MockConfigEntry, data: bytes, host: str = NODE_HOST) -> None:
    """Feed a datagram into the hub as if it came from ``host``."""
    entry.runtime_data.hub.handle_datagram(data, host)
