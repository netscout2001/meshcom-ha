"""Tests for the KISS access path: flow, connection, sending, repairs."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.meshcom.aiomeshcom import Packet
from custom_components.meshcom.aiomeshcom.kiss import TxStatus, own_message_packet
from custom_components.meshcom.aiomeshcom.kiss_client import (
    KissAuthError,
    KissAuthRequiredError,
    KissConnectionError,
    KissSendError,
)
from custom_components.meshcom.aiomeshcom.parser import parse_object
from custom_components.meshcom.const import (
    CONF_ACCESS,
    CONF_CALLSIGN,
    CONF_KISS_PASSWORD,
    CONF_KISS_PORT,
    CONF_LISTEN_PORT,
    CONF_NODE_ID,
    DOMAIN,
    ISSUE_KISS_AUTH_OFF,
)
from custom_components.meshcom.migration import callsign_node_id
from custom_components.meshcom.sender import async_send_text

from .conftest import OWN_POSITION, FakeWebClient

KISS_HOST = "192.168.1.60"
CALL = "QX1YZ-9"
CONNECTED = "binary_sensor.meshcom_qx1yz_9_kiss_connected"


class FakeKiss:
    """Controls every KissConnection created during a test."""

    def __init__(self) -> None:
        self.connect_error: Exception | None = None
        self.authenticated = True
        self.send_error: Exception | None = None
        self.instances: list[FakeConnection] = []
        self.sent: list[tuple[str, str, bool]] = []
        self.connected = asyncio.Event()

    def factory(
        self,
        host: str,
        callsign: str,
        password: str | None,
        on_packet: Callable[[Packet], None],
        *,
        port: int = 8001,
    ) -> FakeConnection:
        connection = FakeConnection(self, host, callsign, password, on_packet, port)
        self.instances.append(connection)
        return connection

    @property
    def last(self) -> FakeConnection:
        return self.instances[-1]


class FakeConnection:
    def __init__(
        self,
        fake: FakeKiss,
        host: str,
        callsign: str,
        password: str | None,
        on_packet: Callable[[Packet], None],
        port: int,
    ) -> None:
        self.fake = fake
        self.host = host
        self.callsign = callsign
        self.password = password
        self.on_packet = on_packet
        self.port = port
        self.authenticated = False
        self.closed = False
        self._drop = asyncio.Event()
        self.invalid_frames: dict[str, int] = {}

    async def connect(self) -> None:
        if self.fake.connect_error is not None:
            raise self.fake.connect_error
        self.authenticated = self.fake.authenticated
        self.fake.connected.set()

    async def run(self) -> None:
        await self._drop.wait()
        raise KissConnectionError("dropped")

    def drop(self) -> None:
        self._drop.set()

    async def send_text(self, destination: str, text: str, *, direct: bool) -> Packet:
        if self.fake.send_error is not None:
            raise self.fake.send_error
        self.fake.sent.append((destination, text, direct))
        packet = own_message_packet(
            self.callsign,
            destination,
            text,
            5 if direct else None,
            0x12345000 + len(self.fake.sent),
        )
        self.on_packet(packet)
        return packet

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def kiss() -> Generator[FakeKiss]:
    fake = FakeKiss()
    with (
        patch("custom_components.meshcom.kiss_link.KissConnection", side_effect=fake.factory),
        patch("custom_components.meshcom.config_flow.KissConnection", side_effect=fake.factory),
        patch("custom_components.meshcom.kiss_link.KISS_RECONNECT_DELAYS", (0, 0)),
    ):
        yield fake


@pytest.fixture
def kiss_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=CALL,
        unique_id=f"{callsign_node_id(CALL):06x}",
        minor_version=2,
        data={
            CONF_HOST: KISS_HOST,
            CONF_CALLSIGN: CALL,
            CONF_NODE_ID: callsign_node_id(CALL),
            CONF_ACCESS: "kiss",
            CONF_KISS_PORT: 8001,
            CONF_KISS_PASSWORD: "geheim",
        },
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry, kiss: FakeKiss) -> MockConfigEntry:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await asyncio.wait_for(kiss.connected.wait(), 1)
    await hass.async_block_till_done()
    return entry


def own_position_packet() -> Packet:
    return parse_object(
        {
            "src_type": "node",
            "type": "pos",
            "src": CALL,
            "lat": 47.934,
            "lat_dir": "N",
            "long": 12.02,
            "long_dir": "E",
            "alt": 1680,
            "batt": 88,
            "msg_id": "00000001",
            "firmware": 0,
        }
    )


# --- config flow -----------------------------------------------------------------


async def _kiss_form(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["udp", "kiss"]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "kiss"}
    )
    assert result["step_id"] == "kiss"
    return result["flow_id"]


def _input(**overrides: Any) -> dict[str, Any]:
    return {
        CONF_HOST: KISS_HOST,
        CONF_KISS_PORT: 8001,
        CONF_CALLSIGN: "qx1yz-9",
        CONF_KISS_PASSWORD: "geheim",
        **overrides,
    }


async def test_flow_kiss(hass: HomeAssistant, kiss: FakeKiss, web_client: FakeWebClient) -> None:
    """A KISS node: login checked, then the web password, then the entry."""
    flow_id = await _kiss_form(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, _input())
    assert result["step_id"] == "web"
    assert kiss.last.password == "geheim"
    assert kiss.last.closed is True  # the flow frees the node's single slot
    result = await hass.config_entries.flow.async_configure(flow_id, {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == CALL
    assert result["result"].unique_id == f"{callsign_node_id(CALL):06x}"
    assert result["data"] == {
        CONF_HOST: KISS_HOST,
        CONF_CALLSIGN: CALL,
        CONF_NODE_ID: callsign_node_id(CALL),
        CONF_ACCESS: "kiss",
        CONF_KISS_PORT: 8001,
        CONF_KISS_PASSWORD: "geheim",
    }


@pytest.mark.parametrize(
    ("overrides", "error", "field"),
    [
        ({CONF_HOST: "8.8.8.8"}, "invalid_host", CONF_HOST),
        ({CONF_CALLSIGN: "<b>"}, "invalid_callsign", CONF_CALLSIGN),
        ({CONF_KISS_PASSWORD: "x" * 15}, "invalid_kiss_password", CONF_KISS_PASSWORD),
        ({CONF_KISS_PASSWORD: "p\u00e4ss"}, "invalid_kiss_password", CONF_KISS_PASSWORD),
    ],
)
async def test_flow_kiss_input_errors(
    hass: HomeAssistant, overrides: dict[str, Any], error: str, field: str
) -> None:
    flow_id = await _kiss_form(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, _input(**overrides))
    assert result["errors"] == {field: error}


@pytest.mark.parametrize(
    ("exception", "error"),
    [
        (KissAuthRequiredError("x"), "kiss_auth_required"),
        (KissAuthError("x"), "invalid_kiss_auth"),
        (KissConnectionError("x"), "kiss_cannot_connect"),
    ],
)
async def test_flow_kiss_connection_errors(
    hass: HomeAssistant, kiss: FakeKiss, exception: Exception, error: str
) -> None:
    kiss.connect_error = exception
    flow_id = await _kiss_form(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, _input())
    assert result["errors"] == {"base": error}
    # Fixed: the user can finish.
    kiss.connect_error = None
    result = await hass.config_entries.flow.async_configure(flow_id, _input())
    assert result["step_id"] == "web"


async def test_flow_kiss_without_password(hass: HomeAssistant, kiss: FakeKiss) -> None:
    flow_id = await _kiss_form(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, _input(**{CONF_KISS_PASSWORD: ""})
    )
    result = await hass.config_entries.flow.async_configure(flow_id, {})
    assert CONF_KISS_PASSWORD not in result["data"]


async def test_flow_same_node_twice(
    hass: HomeAssistant, kiss_entry: MockConfigEntry, mock_config_entry: MockConfigEntry
) -> None:
    """A callsign can be set up once, through UDP or KISS."""
    mock_config_entry.add_to_hass(hass)  # QX1YZ-12 via UDP
    flow_id = await _kiss_form(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, _input(**{CONF_CALLSIGN: "QX1YZ-12"})
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"

    kiss_entry.add_to_hass(hass)
    flow_id = await _kiss_form(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, _input(**{CONF_HOST: "192.168.1.61"})
    )
    assert result["reason"] == "already_configured"


async def test_udp_flow_refuses_kiss_node(hass: HomeAssistant, kiss_entry: MockConfigEntry) -> None:
    """The UDP flow aborts if the node is already set up through KISS."""
    kiss_entry.add_to_hass(hass)
    with patch(
        "custom_components.meshcom.config_flow.MeshComConfigFlow._async_wait_for_node",
        return_value=(CALL, 0x123),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "udp"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.1.62", CONF_LISTEN_PORT: 1799}
        )
        await hass.async_block_till_done()
        if result["type"] is not FlowResultType.ABORT:
            result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# --- connection ------------------------------------------------------------------


async def test_connects_and_receives(
    hass: HomeAssistant, kiss_entry: MockConfigEntry, kiss: FakeKiss
) -> None:
    entry = await _setup(hass, kiss_entry, kiss)
    assert hass.states.get(CONNECTED).state == STATE_ON  # type: ignore[union-attr]
    assert (kiss.last.host, kiss.last.port, kiss.last.callsign) == (KISS_HOST, 8001, CALL)
    kiss.last.on_packet(own_position_packet())
    await hass.async_block_till_done()
    node = entry.runtime_data.node
    assert node.position is not None
    assert node.position.battery == 88
    assert node.firmware is None  # KISS carries no version
    # KISS carries no version: it comes from the node's web page.
    assert hass.states.get("sensor.meshcom_qx1yz_9_firmware").state == "4.40a"  # type: ignore[union-attr]
    issue_id = f"{ISSUE_KISS_AUTH_OFF}_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert entry.runtime_data.hub is None


async def test_reconnects(hass: HomeAssistant, kiss_entry: MockConfigEntry, kiss: FakeKiss) -> None:
    entry = await _setup(hass, kiss_entry, kiss)
    first = kiss.last
    kiss.connected.clear()
    kiss.connect_error = KissConnectionError("away")
    first.drop()
    await hass.async_block_till_done()
    await asyncio.sleep(0.05)
    assert hass.states.get(CONNECTED).state == STATE_OFF  # type: ignore[union-attr]
    assert first.closed
    # The node is back.
    kiss.connect_error = None
    await asyncio.wait_for(kiss.connected.wait(), 1)
    await hass.async_block_till_done()
    assert hass.states.get(CONNECTED).state == STATE_ON  # type: ignore[union-attr]
    assert entry.runtime_data.kiss is not None
    assert entry.runtime_data.kiss.connects == 2


async def test_auth_off_issue(
    hass: HomeAssistant, kiss_entry: MockConfigEntry, kiss: FakeKiss
) -> None:
    """A node that does not ask for a password gets a repair warning."""
    kiss.authenticated = False
    entry = await _setup(hass, kiss_entry, kiss)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"{ISSUE_KISS_AUTH_OFF}_{entry.entry_id}")
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.WARNING


@pytest.mark.parametrize("error", [KissAuthError("x"), KissAuthRequiredError("x")])
async def test_auth_failure_starts_reauth(
    hass: HomeAssistant, kiss_entry: MockConfigEntry, kiss: FakeKiss, error: Exception
) -> None:
    kiss.connect_error = error
    kiss_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(kiss_entry.entry_id)
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]
    # No retry loop against a rejected password.
    assert len(kiss.instances) == 1


async def test_unload_closes(
    hass: HomeAssistant, kiss_entry: MockConfigEntry, kiss: FakeKiss
) -> None:
    entry = await _setup(hass, kiss_entry, kiss)
    connection = kiss.last
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert connection.closed


# --- sending ---------------------------------------------------------------------


async def test_send_via_kiss(
    hass: HomeAssistant, kiss_entry: MockConfigEntry, kiss: FakeKiss
) -> None:
    """Sending goes through the KISS link; the own message is tracked."""
    entry = await _setup(hass, kiss_entry, kiss)
    hass.data.pop("meshcom_send_limiter", None)
    await async_send_text(hass, entry, "QX1YZ-12", "Hallo", None)
    await async_send_text(hass, entry, "262", "GM", None)
    assert kiss.sent == [("QX1YZ-12", "Hallo", True), ("262", "GM", False)]
    chat = [m for m in entry.runtime_data.chat.messages if m.own]
    assert [m.conversation for m in chat] == ["dm:QX1YZ-12", "group:262"]
    assert entry.runtime_data.node.messages_sent == 2


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (KissSendError(TxStatus.TX_OFF), "kiss_tx_off"),
        (KissSendError(TxStatus.BAD_CALL), "kiss_bad_call"),
        (KissSendError(TxStatus.RATE_LIMIT), "rate_limited_node"),
        (KissSendError(None), "send_failed"),
        (KissConnectionError("x"), "kiss_offline"),
    ],
)
async def test_send_errors(
    hass: HomeAssistant,
    kiss_entry: MockConfigEntry,
    kiss: FakeKiss,
    error: Exception,
    key: str,
) -> None:
    entry = await _setup(hass, kiss_entry, kiss)
    hass.data.pop("meshcom_send_limiter", None)
    kiss.send_error = error
    with pytest.raises(HomeAssistantError) as err:
        await async_send_text(hass, entry, "*", "x", None)
    assert err.value.translation_key == key


async def test_send_while_offline(
    hass: HomeAssistant, kiss_entry: MockConfigEntry, kiss: FakeKiss
) -> None:
    entry = await _setup(hass, kiss_entry, kiss)
    hass.data.pop("meshcom_send_limiter", None)
    kiss.connect_error = KissConnectionError("away")
    kiss.last.drop()
    await hass.async_block_till_done()
    await asyncio.sleep(0.05)
    with pytest.raises(HomeAssistantError) as err:
        await async_send_text(hass, entry, "*", "x", None)
    assert err.value.translation_key == "kiss_offline"


# --- reauth / reconfigure / diagnostics ------------------------------------------


async def test_reauth_kiss_password(
    hass: HomeAssistant, kiss_entry: MockConfigEntry, kiss: FakeKiss
) -> None:
    entry = await _setup(hass, kiss_entry, kiss)
    result = await entry.start_reauth_flow(hass)
    assert "kiss_password" in result["data_schema"].schema

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_KISS_PASSWORD: "x" * 20}
    )
    assert result["errors"] == {CONF_KISS_PASSWORD: "invalid_kiss_password"}

    kiss.connect_error = KissAuthError("x")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_KISS_PASSWORD: "falsch"}
    )
    assert result["errors"] == {"base": "invalid_kiss_auth"}
    await hass.async_block_till_done()

    kiss.connect_error = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_KISS_PASSWORD: "neu-geheim", CONF_PASSWORD: "web"}
    )
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_KISS_PASSWORD] == "neu-geheim"
    assert entry.data[CONF_PASSWORD] == "web"


async def test_reconfigure_removes_kiss_password(
    hass: HomeAssistant, kiss_entry: MockConfigEntry, kiss: FakeKiss
) -> None:
    entry = await _setup(hass, kiss_entry, kiss)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["reason"] == "reconfigure_successful"
    assert CONF_KISS_PASSWORD not in entry.data


async def test_diagnostics(
    hass: HomeAssistant,
    kiss_entry: MockConfigEntry,
    kiss: FakeKiss,
    hass_client: ClientSessionGenerator,
) -> None:
    entry = await _setup(hass, kiss_entry, kiss)
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert "geheim" not in str(diagnostics)
    assert KISS_HOST not in str(diagnostics)
    assert diagnostics["entry"][CONF_KISS_PASSWORD] == "**REDACTED**"
    assert diagnostics["hub"] is None
    assert diagnostics["kiss"] == {
        "connected": True,
        "authenticated": True,
        "connects": 1,
        "invalid_frames": {},
    }


async def test_udp_entry_unchanged(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """UDP nodes have no KISS link and no KISS sensor."""
    assert init_integration.runtime_data.kiss is None
    assert hass.states.get("binary_sensor.meshcom_qx1yz_12_kiss_connected") is None
    assert OWN_POSITION  # the UDP fixtures stay usable
