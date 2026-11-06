"""Tests for the config flow."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.meshcom.const import CONF_LISTEN_PORT, DOMAIN
from custom_components.meshcom.hub import UdpHub

from .conftest import INCOMING_MESSAGE, NODE_HOST, NODE_ID, OWN_POSITION


async def _hub(hass: HomeAssistant) -> UdpHub:
    for _ in range(50):
        hubs = hass.data.get("meshcom_hubs", {})
        if 1799 in hubs:
            return hubs[1799]  # type: ignore[no-any-return]
        await asyncio.sleep(0)
    raise AssertionError("hub not started")


async def test_full_flow(hass: HomeAssistant) -> None:
    """The node is found by its own beacon; node id becomes the unique id."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "udp"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "udp"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: NODE_HOST, CONF_LISTEN_PORT: 1799}
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    hub = await _hub(hass)

    # Foreign sender and foreign packets are ignored.
    hub.handle_datagram(OWN_POSITION, "192.168.1.99")
    hub.handle_datagram(INCOMING_MESSAGE, NODE_HOST)
    # The node's own beacon identifies it.
    hub.handle_datagram(OWN_POSITION, NODE_HOST)
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "web"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "DO8RE-12"
    assert CONF_PASSWORD not in result["data"]
    assert result["result"].unique_id == f"{NODE_ID:06x}"
    assert result["data"][CONF_HOST] == NODE_HOST
    # The flow's temporary listener is gone; only the new entry is registered.
    await hass.async_block_till_done()
    assert hass.data["meshcom_hubs"][1799].diagnostics()["registered_nodes"] == 1


@pytest.mark.parametrize(
    "host", ["8.8.8.8", "meshcom.local", "127.0.0.1", "0.0.0.0", "fd00::1", "224.0.0.1", ""]
)
async def test_invalid_host(hass: HomeAssistant, host: str) -> None:
    """Only private IPv4 literals are accepted."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "udp"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: host, CONF_LISTEN_PORT: 1799}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_HOST: "invalid_host"}


async def test_timeout_and_retry(hass: HomeAssistant) -> None:
    """Without a packet the user gets help and can try again."""
    with patch("custom_components.meshcom.config_flow.SETUP_WAIT_TIMEOUT", 0.01):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "udp"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: NODE_HOST, CONF_LISTEN_PORT: 1799}
        )
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "no_packet"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "udp"


async def test_port_unavailable(hass: HomeAssistant) -> None:
    """A port that cannot be opened aborts with a clear reason."""
    with patch.object(UdpHub, "async_start", side_effect=OSError):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "udp"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: NODE_HOST, CONF_LISTEN_PORT: 1799}
        )
        await hass.async_block_till_done()
        if result["type"] is not FlowResultType.ABORT:
            result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "port_unavailable"


async def test_already_configured_host(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The same address cannot be added twice."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "udp"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: NODE_HOST, CONF_LISTEN_PORT: 1799}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_already_configured_node_new_address(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The same node under a new address updates the existing entry."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "udp"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.20", CONF_LISTEN_PORT: 1799}
    )
    hub = await _hub(hass)
    hub.handle_datagram(OWN_POSITION, "192.168.1.20")
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data[CONF_HOST] == "192.168.1.20"
