"""Tests for the chat panel: history, live updates, permissions, sending."""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.auth.models import User
from homeassistant.components.frontend import DATA_PANELS
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.typing import (
    ClientSessionGenerator,
    WebSocketGenerator,
)

from custom_components.meshcom.chat import CHAT_SAVE_DELAY
from custom_components.meshcom.const import CONF_GROUPS, CONF_SEND_USERS, DOMAIN
from custom_components.meshcom.hub import UdpHub
from custom_components.meshcom.panel import PANEL_URL_PATH

from .conftest import (
    ACK_TEXT,
    INCOMING_MESSAGE,
    OWN_MESSAGE,
    FakeWebClient,
    datagram,
    inject,
)


@pytest.fixture(autouse=True)
def mock_send() -> Generator[MagicMock]:
    """Capture datagrams instead of sending them."""
    with patch.object(UdpHub, "send") as send:
        yield send


@pytest.fixture(autouse=True)
def fresh_limiter(hass: HomeAssistant) -> None:
    """Every test starts with a full rate-limit bucket."""
    hass.data.pop("meshcom_send_limiter", None)


def message(dst: str, msg_id: str, src: str = "TST1-12", text: str = "Hallo") -> bytes:
    return datagram(
        src_type="lora",
        type="msg",
        src=src,
        dst=dst,
        msg=text,
        msg_id=msg_id,
        firmware=40,
        fw_sub="a",
        rssi=-101,
        snr=4,
        hw_id=3,
        lora_mod=8,
        max_hop=4,
    )


async def _call(client: Any, **payload: Any) -> dict[str, Any]:
    await client.send_json_auto_id(payload)
    return await client.receive_json()  # type: ignore[no-any-return]


# --- history -------------------------------------------------------------------


async def test_history_conversations(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """Messages are grouped into conversations; foreign DMs stay out."""
    inject(init_integration, INCOMING_MESSAGE)  # group 262
    inject(init_integration, message("*", "40000201", text="an alle"))
    inject(init_integration, message("DO8RE-12", "40000202", src="DB0AAA-1", text="an mich"))
    inject(init_integration, message("DB0BBB-1", "40000203", src="DB0AAA-1", text="fremd"))
    inject(init_integration, message("TEST", "40000204", text="anderer"))
    inject(init_integration, OWN_MESSAGE)
    await hass.async_block_till_done()

    client = await hass_ws_client(hass)
    result = await _call(client, type="meshcom/chat/history", entry_id=init_integration.entry_id)
    assert result["success"]
    messages = result["result"]["messages"]
    assert [m["conversation"] for m in messages] == [
        "group:262",
        "all",
        "dm:DB0AAA-1",
        "other:TEST",
        "dm:DO8RE-9",
    ]
    incoming = messages[0]
    assert incoming["text"] == "Hallo <b>Welt</b>"  # stored as is, rendered as text
    assert incoming["sender"] == "TST1-12"
    assert incoming["rssi"] == -110
    assert incoming["own"] is False
    own = messages[-1]
    assert own["own"] is True
    assert own["status"] == "sent"
    assert own["rssi"] is None


async def test_filtered_messages_not_in_chat(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    web_client: FakeWebClient,
) -> None:
    """With No MSG All on, the chat shows what the node shows."""
    web_client.no_msg_all = True
    await init_integration.runtime_data.web.async_refresh()
    await hass.async_block_till_done()
    inject(init_integration, message("*", "40000211"))
    inject(init_integration, message("262", "40000212"))
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)
    result = await _call(client, type="meshcom/chat/history", entry_id=init_integration.entry_id)
    assert [m["conversation"] for m in result["result"]["messages"]] == ["group:262"]


async def test_subscription_messages_and_delivery(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """New messages and delivery updates are pushed."""
    client = await hass_ws_client(hass)
    result = await _call(client, type="meshcom/chat/subscribe", entry_id=init_integration.entry_id)
    assert result["success"]
    sub_id = result["id"]

    inject(init_integration, OWN_MESSAGE)
    event = await client.receive_json()
    assert event["id"] == sub_id
    assert event["event"]["message"]["conversation"] == "dm:DO8RE-9"
    msg_id = event["event"]["message"]["id"]

    inject(init_integration, ACK_TEXT)
    event = await client.receive_json()
    assert event["event"]["status"] == {"id": msg_id, "status": "delivered"}

    # The ack text itself is not a chat message.
    history = await _call(client, type="meshcom/chat/history", entry_id=init_integration.entry_id)
    assert [m["status"] for m in history["result"]["messages"]] == ["delivered"]


async def test_unknown_status_mapped(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """An unexpected status value is shown as unknown."""
    inject(init_integration, OWN_MESSAGE)
    chat = init_integration.runtime_data.chat
    chat.async_set_status("63CF32D4", "exploded")
    assert chat.messages[-1].status == "unknown"
    chat.async_set_status("FFFFFFFF", "delivered")  # not an own message: ignored


# --- permissions ---------------------------------------------------------------


async def test_read_only_user_refused(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
    mock_send: MagicMock,
) -> None:
    """Users not released for the node see nothing and cannot send."""
    client = await hass_ws_client(hass, hass_read_only_access_token)
    nodes = await _call(client, type="meshcom/chat/nodes")
    assert nodes["result"] == {"nodes": []}
    for kind in ("history", "subscribe"):
        result = await _call(
            client, type=f"meshcom/chat/{kind}", entry_id=init_integration.entry_id
        )
        assert result["error"]["code"] == "unauthorized"
    result = await _call(
        client,
        type="meshcom/chat/send",
        entry_id=init_integration.entry_id,
        destination="*",
        text="x",
    )
    assert result["error"]["code"] == "unauthorized"
    mock_send.assert_not_called()


async def test_released_user_reads_and_sends(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
    hass_read_only_user: User,
    mock_send: MagicMock,
) -> None:
    """A user released in the options may read and send."""
    hass.config_entries.async_update_entry(
        init_integration,
        options={CONF_SEND_USERS: [hass_read_only_user.id], CONF_GROUPS: ["9"]},
    )
    await hass.async_block_till_done()
    client = await hass_ws_client(hass, hass_read_only_access_token)
    nodes = await _call(client, type="meshcom/chat/nodes")
    (node,) = nodes["result"]["nodes"]
    assert {key: node[key] for key in ("entry_id", "callsign", "groups", "sending_enabled")} == {
        "entry_id": init_integration.entry_id,
        "callsign": "DO8RE-12",
        "groups": ["262", "26298", "9"],
        "sending_enabled": True,
    }
    assert node["access"] == "udp"
    assert node["station_mode"] == "data"
    result = await _call(
        client,
        type="meshcom/chat/send",
        entry_id=init_integration.entry_id,
        destination="262",
        text="GM",
    )
    assert result["success"]
    assert mock_send.call_count == 1


async def test_permission_revoked_while_subscribed(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
    hass_read_only_user: User,
) -> None:
    """A subscription stops delivering once the user is no longer released."""
    entry = init_integration
    hass.config_entries.async_update_entry(
        entry, options={CONF_SEND_USERS: [hass_read_only_user.id]}
    )
    await hass.async_block_till_done()
    client = await hass_ws_client(hass, hass_read_only_access_token)
    result = await _call(client, type="meshcom/chat/subscribe", entry_id=entry.entry_id)
    assert result["success"]
    # Revoke without reload: the forwarder checks again.
    entry.runtime_data.options = {}
    hass.config_entries.async_update_entry(entry, options={})
    chat = entry.runtime_data.chat
    delivered: list[str] = []
    chat.async_subscribe(lambda kind, _data: delivered.append(kind))
    inject(entry, INCOMING_MESSAGE)
    await hass.async_block_till_done()
    assert delivered == ["message"]  # our own probe got it ...
    ping = await _call(client, type="ping")
    assert ping["type"] == "pong"  # ... the revoked subscriber did not


async def test_unknown_entry(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    client = await hass_ws_client(hass)
    for entry_id in ("nope", init_integration.entry_id + "x"):
        result = await _call(client, type="meshcom/chat/history", entry_id=entry_id)
        assert result["error"]["code"] == "not_found"


# --- sending -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("destination", "text", "code"),
    [
        ("DO8RE-9", "a\nb", "invalid_message"),
        ("not valid", "x", "invalid_message"),
    ],
)
async def test_send_rejected(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    mock_send: MagicMock,
    destination: str,
    text: str,
    code: str,
) -> None:
    """The builder's checks apply to the panel too."""
    client = await hass_ws_client(hass)
    result = await _call(
        client,
        type="meshcom/chat/send",
        entry_id=init_integration.entry_id,
        destination=destination,
        text=text,
    )
    assert result["error"]["code"] == code
    mock_send.assert_not_called()


async def test_send_respects_kill_switch_and_limit(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    mock_send: MagicMock,
) -> None:
    client = await hass_ws_client(hass)
    for _ in range(3):
        result = await _call(
            client,
            type="meshcom/chat/send",
            entry_id=init_integration.entry_id,
            destination="*",
            text="x",
        )
        assert result["success"]
    result = await _call(
        client,
        type="meshcom/chat/send",
        entry_id=init_integration.entry_id,
        destination="*",
        text="x",
    )
    assert result["error"]["code"] == "rate_limited"

    init_integration.runtime_data.node.sending_enabled = False
    result = await _call(
        client,
        type="meshcom/chat/send",
        entry_id=init_integration.entry_id,
        destination="*",
        text="x",
    )
    assert result["error"]["code"] == "sending_disabled"
    assert mock_send.call_count == 3


async def test_send_os_error(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    mock_send: MagicMock,
) -> None:
    mock_send.side_effect = OSError
    client = await hass_ws_client(hass)
    result = await _call(
        client,
        type="meshcom/chat/send",
        entry_id=init_integration.entry_id,
        destination="*",
        text="x",
    )
    assert result["error"]["code"] == "send_failed"


# --- persistence -------------------------------------------------------------


async def test_history_survives_restart(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_storage: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    entry = init_integration
    inject(entry, INCOMING_MESSAGE)
    freezer.tick(timedelta(seconds=CHAT_SAVE_DELAY + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    key = f"{DOMAIN}.chat.{entry.entry_id}"
    assert len(hass_storage[key]["data"]["messages"]) == 1

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert [m.text for m in entry.runtime_data.chat.messages] == ["Hallo <b>Welt</b>"]

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage


async def test_stored_history_validated(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, hass_storage: dict[str, Any]
) -> None:
    """Tampered entries in the chat file are dropped."""
    good = {
        "id": "40000ED4",
        "conversation": "group:262",
        "sender": "TST1-12",
        "destination": "262",
        "text": "ok",
        "time": "2026-11-06T10:00:00+00:00",
        "own": False,
        "via_server": False,
        "rssi": -100,
        "snr": 3.5,
        "status": None,
    }
    bad = [
        {**good, "conversation": "evil:1"},
        {**good, "conversation": "group:abc"},
        {**good, "conversation": "dm:<img>"},
        {**good, "conversation": "other:" + "x" * 20},
        {**good, "conversation": 5},
        {**good, "sender": "<script>"},
        {**good, "text": "x" * 400},
        {**good, "id": "../../x"},
        {**good, "time": "2026-11-06T10:00:00"},
        {**good, "time": "soon"},
        {**good, "own": "yes"},
        {**good, "destination": ""},
        "nope",
    ]
    odd = {**good, "conversation": "dm:DB0AAA-1", "rssi": True, "snr": "x", "status": "boom"}
    other = {**good, "conversation": "other:TEST", "own": True, "status": "delivered"}
    key = f"{DOMAIN}.chat.{mock_config_entry.entry_id}"
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {"messages": [good, *bad, odd, other, {**good, "conversation": "all"}]},
    }
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    messages = list(mock_config_entry.runtime_data.chat.messages)
    assert [m.conversation for m in messages] == ["group:262", "dm:DB0AAA-1", "other:TEST", "all"]
    assert messages[1].rssi is None
    assert messages[1].snr is None
    assert messages[1].status is None
    assert messages[2].status == "delivered"


@pytest.mark.parametrize("data", [None, {"messages": "x"}, ["x"]])
async def test_stored_history_unusable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
    data: Any,
) -> None:
    key = f"{DOMAIN}.chat.{mock_config_entry.entry_id}"
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": data}
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert len(mock_config_entry.runtime_data.chat.messages) == 0


# --- panel ---------------------------------------------------------------------


async def test_panel_registered_and_served(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_client: ClientSessionGenerator,
) -> None:
    """The sidebar entry exists while a node is loaded; the module is served."""
    panel = hass.data[DATA_PANELS][PANEL_URL_PATH]
    assert panel.sidebar_title == "MeshCom"
    assert panel.require_admin is False
    assert panel.config is not None
    module_url = panel.config["_panel_custom"]["module_url"]
    assert module_url.startswith("/meshcom_static/meshcom-chat-panel.js?v=")

    client = await hass_client()
    response = await client.get(module_url)
    assert response.status == 200
    assert "customElements.define" in await response.text()
    # Only the panel's own folder is served.
    response = await client.get("/meshcom_static/../manifest.json")
    assert response.status == 404

    await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    assert PANEL_URL_PATH not in hass.data[DATA_PANELS]

    # Loading again registers the panel again (static path only once).
    await hass.config_entries.async_setup(init_integration.entry_id)
    await hass.async_block_till_done()
    assert PANEL_URL_PATH in hass.data[DATA_PANELS]


async def test_panel_kept_while_other_node_loaded(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    second = MockConfigEntry(
        minor_version=2,
        domain=DOMAIN,
        title="DO8RE-9",
        unique_id="abcdef",
        data={**init_integration.data, "host": "192.168.1.51", "node_id": 0xABCDEF},
    )
    second.add_to_hass(hass)
    await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    assert PANEL_URL_PATH in hass.data[DATA_PANELS]


async def test_subscribers_told_on_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """A reload tells open panels to reconnect."""
    client = await hass_ws_client(hass)
    result = await _call(client, type="meshcom/chat/subscribe", entry_id=init_integration.entry_id)
    sub_id = result["id"]
    await hass.config_entries.async_reload(init_integration.entry_id)
    await hass.async_block_till_done()
    event = await client.receive_json()
    assert event["id"] == sub_id
    assert event["event"] == {"closed": {}}
    # Unsubscribing afterwards is harmless.
    result = await _call(client, type="unsubscribe_events", subscription=sub_id)
    assert result["success"]


# --- foreign groups ------------------------------------------------------------


async def test_foreign_groups_hidden(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """Groups the node does not listen to stay out of the chat (default)."""
    client = await hass_ws_client(hass)
    result = await _call(client, type="meshcom/chat/subscribe", entry_id=init_integration.entry_id)
    sub_id = result["id"]
    inject(init_integration, message("26299", "40000301", text="fremd"))
    inject(init_integration, message("262", "40000302", text="eigen"))
    event = await client.receive_json()
    assert event["id"] == sub_id
    assert event["event"]["message"]["conversation"] == "group:262"
    history = await _call(client, type="meshcom/chat/history", entry_id=init_integration.entry_id)
    assert [m["text"] for m in history["result"]["messages"]] == ["eigen"]
    # Events still carry everything.
    assert init_integration.runtime_data.node.messages_received == 2


async def test_foreign_groups_shown_when_disabled(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    hass.config_entries.async_update_entry(init_integration, options={"hide_foreign_groups": False})
    await hass.async_block_till_done()
    inject(init_integration, message("26299", "40000311", text="fremd"))
    client = await hass_ws_client(hass)
    history = await _call(client, type="meshcom/chat/history", entry_id=init_integration.entry_id)
    assert [m["conversation"] for m in history["result"]["messages"]] == ["group:26299"]


async def test_configured_group_counts_as_own(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    hass.config_entries.async_update_entry(init_integration, options={CONF_GROUPS: ["26299"]})
    await hass.async_block_till_done()
    inject(init_integration, message("26299", "40000321"))
    assert [m.conversation for m in init_integration.runtime_data.chat.messages] == ["group:26299"]


async def test_no_known_groups_shows_all(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """Without the node's groups nothing is hidden."""
    web_client.groups = []
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    inject(mock_config_entry, message("26299", "40000331"))
    assert len(mock_config_entry.runtime_data.chat.messages) == 1


async def test_stored_foreign_groups_hidden_later(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    web_client: FakeWebClient,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Messages stored while the groups were unknown are hidden once they are known."""
    web_client.groups = []
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    inject(mock_config_entry, message("26299", "40000341"))
    web_client.groups = ["262"]
    await mock_config_entry.runtime_data.web.async_refresh()
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)
    history = await _call(client, type="meshcom/chat/history", entry_id=mock_config_entry.entry_id)
    assert history["result"]["messages"] == []


async def test_panel_failure_does_not_break_setup(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A panel error is logged; the node loads and reloads cleanly."""
    with patch("custom_components.meshcom.async_register_panel", side_effect=RuntimeError("boom")):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert mock_config_entry.state.name == "LOADED"
        assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry.state.name == "LOADED"


async def test_two_nodes_set_up_together(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, caplog: pytest.LogCaptureFixture
) -> None:
    """Two nodes starting at the same time register the panel once, without errors."""
    second = MockConfigEntry(
        minor_version=2,
        domain=DOMAIN,
        title="DO8RE-9",
        unique_id="abcdef",
        data={**mock_config_entry.data, "host": "192.168.1.51", "node_id": 0xABCDEF},
    )
    mock_config_entry.add_to_hass(hass)
    second.add_to_hass(hass)
    await asyncio.gather(
        hass.config_entries.async_setup(mock_config_entry.entry_id),
        hass.config_entries.async_setup(second.entry_id),
    )
    await hass.async_block_till_done()
    assert mock_config_entry.state.name == "LOADED"
    assert second.state.name == "LOADED"
    assert PANEL_URL_PATH in hass.data[DATA_PANELS]
    assert "could not be registered" not in caplog.text


# --- path, nodes tab, stations tab ---------------------------------------------


async def test_message_path(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """Messages carry originator and relays for the "via" line."""
    inject(init_integration, INCOMING_MESSAGE)
    client = await hass_ws_client(hass)
    history = await _call(client, type="meshcom/chat/history", entry_id=init_integration.entry_id)
    assert history["result"]["messages"][0]["path"] == ["TST1-12", "TST2-12"]


async def test_stored_path_validated(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, hass_storage: dict[str, Any]
) -> None:
    base = {
        "id": "40000ED4",
        "conversation": "all",
        "sender": "TST1-12",
        "destination": "*",
        "text": "ok",
        "time": "2026-11-06T10:00:00+00:00",
        "own": False,
    }
    key = f"{DOMAIN}.chat.{mock_config_entry.entry_id}"
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {
            "messages": [
                {**base, "path": ["TST1-12", "RLY1-1"]},
                {**base, "path": ["TST1-12", "<img>"]},
                {**base, "path": "TST1-12"},
                {**base, "path": ["TST1-12"] * 13},
                base,
            ]
        },
    }
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    paths = [m.path for m in mock_config_entry.runtime_data.chat.messages]
    assert paths == [["TST1-12", "RLY1-1"], [], [], [], []]


async def test_nodes_tab_entities(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """The node card lists sensors, switches and the tracker, not the compose controls."""
    client = await hass_ws_client(hass)
    nodes = await _call(client, type="meshcom/chat/nodes")
    entities = nodes["result"]["nodes"][0]["entities"]
    domains = [item["domain"] for item in entities]
    assert domains == sorted(
        domains,
        key=["binary_sensor", "switch", "sensor", "device_tracker"].index,
    )
    keys = {item["key"] for item in entities}
    assert {"active", "no_msg_all", "sending_enabled", "battery", "position"} <= keys
    assert not {"recipient_type", "message", "send"} & keys
    assert all(hass.states.get(item["entity_id"]) is not None for item in entities)


async def test_stations_tab(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    inject(init_integration, INCOMING_MESSAGE)
    client = await hass_ws_client(hass)
    result = await _call(client, type="meshcom/chat/stations", entry_id=init_integration.entry_id)
    assert result["result"]["mode"] == "data"
    (station,) = result["result"]["stations"]
    assert station["callsign"] == "TST1-12"
    assert station["rssi"] == -110


async def test_stations_tab_off_and_refused(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
) -> None:
    inject(init_integration, INCOMING_MESSAGE)
    reader = await hass_ws_client(hass, hass_read_only_access_token)
    result = await _call(reader, type="meshcom/chat/stations", entry_id=init_integration.entry_id)
    assert result["error"]["code"] == "unauthorized"

    hass.config_entries.async_update_entry(init_integration, options={"station_mode": "off"})
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)
    result = await _call(client, type="meshcom/chat/stations", entry_id=init_integration.entry_id)
    assert result["result"] == {"stations": [], "mode": "off"}
