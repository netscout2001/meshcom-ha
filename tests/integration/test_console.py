"""Net console tab (issue #54): session, confirmation, admin-only websocket."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Generator
from typing import Any, ClassVar
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.meshcom.aiomeshcom.netconsole import (
    ConsoleAuthError,
    ConsoleError,
    ConsoleRefusedError,
)
from custom_components.meshcom.console import IDLE_TIMEOUT, node_password
from custom_components.meshcom.const import CONF_KISS_PASSWORD, CONF_NODE_PASSWORD


class FakeConsole:
    """Stands in for aiomeshcom.netconsole.NetConsole."""

    instances: ClassVar[list[FakeConsole]] = []
    fail: type[ConsoleError] | None = None
    open_access = False

    def __init__(self, host: str, password: str | None, on_line: Callable[[str], None]) -> None:
        self.host = host
        self.password = password
        self.on_line = on_line
        self.sent: list[str] = []
        self.connected = False
        self.open_access = FakeConsole.open_access
        self._closed = asyncio.Event()
        FakeConsole.instances.append(self)

    async def connect(self) -> None:
        if FakeConsole.fail is not None:
            raise FakeConsole.fail("x")
        self.connected = True
        self.on_line("MeshCom Console")

    async def run(self) -> None:
        await self._closed.wait()

    async def send(self, command: str) -> None:
        if not self.connected:
            raise ConsoleError("not connected")
        self.sent.append(command)
        self.on_line(f"echo {command}")

    async def close(self) -> None:
        self.connected = False
        self._closed.set()

    def node_ends(self) -> None:
        self.connected = False
        self._closed.set()


@pytest.fixture(autouse=True)
def fake_console() -> Generator[type[FakeConsole]]:
    FakeConsole.instances = []
    FakeConsole.fail = None
    FakeConsole.open_access = False
    with patch("custom_components.meshcom.console.NetConsole", FakeConsole):
        yield FakeConsole


async def test_session_lifecycle(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    session = init_integration.runtime_data.console
    events: list[tuple[str, dict[str, Any]]] = []
    remove = session.async_subscribe(lambda kind, data: events.append((kind, data)))
    await session.async_connect()
    await session.async_connect()  # already open: no second login
    assert len(FakeConsole.instances) == 1
    assert session.state == "connected"
    await session.async_send("--info")
    assert FakeConsole.instances[0].sent == ["--info"]
    assert session.snapshot()["lines"] == ["MeshCom Console", "echo --info"]

    with pytest.raises(ServiceValidationError) as err:
        await session.async_send("--passwd neu")
    assert err.value.translation_key == "console_confirm"
    assert err.value.translation_placeholders == {"risk": "credentials"}
    await session.async_send("--passwd neu", confirm=True)
    with pytest.raises(ServiceValidationError):
        await session.async_send("info")

    # The node ends the session.
    FakeConsole.instances[0].node_ends()
    await hass.async_block_till_done()
    assert session.state == "closed_by_node"
    with pytest.raises(HomeAssistantError):
        await session.async_send("--info")

    # Idle timeout.
    await session.async_connect()
    async_fire_time_changed(hass, dt_after(IDLE_TIMEOUT))
    await hass.async_block_till_done()
    assert session.state == "idle_timeout"

    # The last viewer leaving closes the session.
    await session.async_connect()
    remove()
    await hass.async_block_till_done()
    assert session.state == "disconnected"
    assert ("state", {"state": "connecting", "open_access": False}) in events


def dt_after(delta: Any) -> Any:
    from homeassistant.util import dt as dt_util  # noqa: PLC0415

    return dt_util.utcnow() + delta


@pytest.mark.parametrize(
    ("error", "state"),
    [
        (ConsoleRefusedError, "refused"),
        (ConsoleAuthError, "auth_failed"),
        (ConsoleError, "protocol_error"),
    ],
)
async def test_login_errors(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    error: type[ConsoleError],
    state: str,
) -> None:
    FakeConsole.fail = error
    session = init_integration.runtime_data.console
    await session.async_connect()
    assert session.state == state


async def test_send_fails_when_socket_dies(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    session = init_integration.runtime_data.console
    await session.async_connect()
    FakeConsole.instances[0].connected = True

    async def _boom(_command: str) -> None:
        raise ConsoleError("gone")

    FakeConsole.instances[0].send = _boom  # type: ignore[method-assign,assignment]
    with pytest.raises(HomeAssistantError):
        await session.async_send("--info")
    await session.async_disconnect()


async def test_password_source(hass: HomeAssistant) -> None:
    udp = MockConfigEntry(domain="meshcom", data={CONF_NODE_PASSWORD: "a"})
    kiss = MockConfigEntry(domain="meshcom", data={CONF_KISS_PASSWORD: "b"})
    none = MockConfigEntry(domain="meshcom", data={})
    assert node_password(udp) == "a"
    assert node_password(kiss) == "b"
    assert node_password(none) is None


async def test_websocket(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    FakeConsole.open_access = True
    client = await hass_ws_client(hass)
    entry_id = init_integration.entry_id

    await client.send_json_auto_id({"type": "meshcom/chat/nodes"})
    nodes = (await client.receive_json())["result"]["nodes"]
    assert nodes[0]["console"] is True

    await client.send_json_auto_id({"type": "meshcom/console/subscribe", "entry_id": entry_id})
    assert (await client.receive_json())["success"]
    snapshot = await client.receive_json()
    assert snapshot["event"]["snapshot"]["state"] == "disconnected"

    await client.send_json_auto_id({"type": "meshcom/console/connect", "entry_id": entry_id})
    seen = [await client.receive_json() for _ in range(4)]
    assert any(msg.get("event", {}).get("state", {}).get("open_access") for msg in seen)

    await client.send_json_auto_id(
        {"type": "meshcom/console/send", "entry_id": entry_id, "command": "--setssid x"}
    )
    reply = await _result(client)
    assert reply["error"]["code"] == "console_confirm"
    assert reply["error"]["message"] == "unreachable"

    await client.send_json_auto_id(
        {"type": "meshcom/console/send", "entry_id": entry_id, "command": "--info"}
    )
    assert (await _result(client))["success"]

    await client.send_json_auto_id({"type": "meshcom/console/disconnect", "entry_id": entry_id})
    assert (await _result(client))["success"]

    await client.send_json_auto_id({"type": "meshcom/console/connect", "entry_id": "nope"})
    assert (await _result(client))["error"]["code"] == "not_found"


async def _result(client: Any) -> dict[str, Any]:
    """Skip events until the next command result."""
    while True:
        msg = await client.receive_json()
        if msg.get("type") == "result":
            return dict(msg)


async def test_websocket_admin_only(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
) -> None:
    client = await hass_ws_client(hass, hass_read_only_access_token)
    for kind in ("subscribe", "connect", "disconnect"):
        await client.send_json_auto_id(
            {"type": f"meshcom/console/{kind}", "entry_id": init_integration.entry_id}
        )
        assert (await client.receive_json())["error"]["code"] == "unauthorized"
    await client.send_json_auto_id(
        {
            "type": "meshcom/console/send",
            "entry_id": init_integration.entry_id,
            "command": "--info",
        }
    )
    assert (await client.receive_json())["error"]["code"] == "unauthorized"
    assert FakeConsole.instances == []


async def test_reconfigure_node_password(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    entry = init_integration
    flow = await entry.start_reconfigure_flow(hass)
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_NODE_PASSWORD: "x" * 15}
    )
    assert flow["errors"] == {CONF_NODE_PASSWORD: "invalid_kiss_password"}
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_NODE_PASSWORD: "geheim"}
    )
    assert flow["type"] is FlowResultType.ABORT
    assert entry.data[CONF_NODE_PASSWORD] == "geheim"
    flow = await entry.start_reconfigure_flow(hass)
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert CONF_NODE_PASSWORD not in entry.data


async def test_websocket_stops_after_demotion(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user: Any,
) -> None:
    client = await hass_ws_client(hass)
    entry_id = init_integration.entry_id
    await client.send_json_auto_id({"type": "meshcom/console/subscribe", "entry_id": entry_id})
    assert (await client.receive_json())["success"]
    await client.receive_json()  # snapshot
    session = init_integration.runtime_data.console
    await session.async_connect()
    await client.receive_json()  # connecting
    await client.receive_json()  # connected or first line
    hass_admin_user.groups = []
    assert not hass_admin_user.is_admin
    await session.async_send("--info")
    await client.send_json_auto_id({"type": "meshcom/chat/nodes"})
    reply = await client.receive_json()
    while reply.get("type") == "event":
        assert "echo --info" not in str(reply)
        reply = await client.receive_json()
    await session.async_disconnect()
