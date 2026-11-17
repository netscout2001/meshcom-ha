"""Remote management of other nodes (RM1, issue #50)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.auth.models import User
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import CONF_HOST, CONF_PASSWORD, STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import Context, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.meshcom.const import (
    CONF_CALLSIGN,
    CONF_LISTEN_PORT,
    CONF_NODE_ID,
    DOMAIN,
    SUBENTRY_REMOTE,
)
from custom_components.meshcom.hub import UdpHub

from .conftest import NODE_HOST, NODE_ID, datagram, inject

OWN = "QX1YZ-12"
REMOTE = "QX2AB-1"
PASSWORD = "geheim1"
KEY = hashlib.sha256(PASSWORD.encode()).digest()


@pytest.fixture(autouse=True)
def mock_send() -> Generator[MagicMock]:
    with patch.object(UdpHub, "send") as send:
        yield send


@pytest.fixture(autouse=True)
def fast_rm() -> Generator[None]:
    with (
        patch("custom_components.meshcom.remote.RATE_INTERVAL_SECONDS", 0),
        patch("custom_components.meshcom.remote.NO_ANSWER_SECONDS", 2),
    ):
        yield


@pytest.fixture(autouse=True)
def fresh_limiter(hass: HomeAssistant) -> None:
    hass.data.pop("meshcom_send_limiter", None)


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=OWN,
        unique_id=f"{NODE_ID:06x}",
        minor_version=2,
        data={
            CONF_HOST: NODE_HOST,
            CONF_LISTEN_PORT: 1799,
            CONF_CALLSIGN: OWN,
            CONF_NODE_ID: NODE_ID,
        },
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CALLSIGN: REMOTE, CONF_PASSWORD: PASSWORD},
                subentry_type=SUBENTRY_REMOTE,
                title=REMOTE,
                unique_id=REMOTE,
            )
        ],
    )


def _sent(mock_send: MagicMock) -> list[dict[str, Any]]:
    return [json.loads(call.args[1]) for call in mock_send.call_args_list]


def _reply(counter: int, result: str, *, key: bytes = KEY, sender: str = REMOTE) -> bytes:
    canonical = f"RM1R|{REMOTE}|{OWN}|{counter}|{result}"
    tag = hmac.new(key, canonical.encode(), hashlib.sha256).hexdigest()[:16]
    return datagram(
        src_type="lora",
        type="msg",
        src=sender,
        dst=OWN,
        msg=f"RM1 {counter} {result} {tag}",
        msg_id=f"{0x41000000 + counter:08X}",
        firmware=40,
        fw_sub="a",
        rssi=-90,
        snr=5,
        hw_id=3,
        lora_mod=8,
        max_hop=4,
    )


def _state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None
    return state.state


def _entity(hass: HomeAssistant, platform: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{NODE_ID:06x}_rm_{REMOTE}_{key}"
    )
    assert entity_id is not None
    return entity_id


async def _answer(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    mock_send: MagicMock,
    task: asyncio.Task[Any],
    answers: list[str],
) -> None:
    """Answer each frame the manager sends with the next result."""
    hass.data.pop("meshcom_send_limiter", None)
    for result in answers:
        for _ in range(100):
            if len(_sent(mock_send)) > 0 and not task.done():
                frame = _sent(mock_send)[-1]
                counter = int(frame["msg"].split(" ")[1])
                if (REMOTE, counter) in entry.runtime_data.remote._pending:
                    break
            await asyncio.sleep(0.01)
        if task.done():
            await task
        inject(entry, _reply(counter, result))
        await asyncio.sleep(0.02)
    await task


STATUS = "ok v=4.40a up=12 bat=88 heap=90 s=GtDMwL p=22/0/30 rs=1"


async def test_status_sync_and_switch(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_send: MagicMock
) -> None:
    entry = init_integration
    gps = _entity(hass, "switch", "gps")
    assert _state(hass, gps) == STATE_UNKNOWN
    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, f"{NODE_ID:06x}_rm_{REMOTE}")}
    )
    assert device is not None
    assert device.via_device_id is not None

    task = hass.async_create_task(
        hass.services.async_call(
            "button", "press", {"entity_id": _entity(hass, "button", "status")}, blocking=True
        )
    )
    await _answer(hass, entry, mock_send, task, ["ok ctr=5 v=4.40a", STATUS])
    frames = [frame["msg"] for frame in _sent(mock_send)]
    assert frames[0].startswith("RM1 0 sync ")
    assert frames[1].startswith("RM1 6 status ")
    assert all(frame["dst"] == REMOTE for frame in _sent(mock_send))
    await hass.async_block_till_done()
    assert _state(hass, gps) == STATE_ON
    assert _state(hass, _entity(hass, "switch", "track")) == STATE_OFF
    assert _state(hass, _entity(hass, "sensor", "battery")) == "88"
    assert _state(hass, _entity(hass, "sensor", "firmware")) == "4.40a"
    assert _state(hass, _entity(hass, "number", "txpower")) == "22"
    assert _state(hass, _entity(hass, "select", "led")) == "on"
    assert _state(hass, _entity(hass, "binary_sensor", "reachable")) == STATE_ON

    mock_send.reset_mock()
    task = hass.async_create_task(
        hass.services.async_call("switch", "turn_off", {"entity_id": gps}, blocking=True)
    )
    await _answer(hass, entry, mock_send, task, ["ok gps=off"])
    assert _sent(mock_send)[0]["msg"].startswith("RM1 7 gps off ")
    await hass.async_block_till_done()
    assert _state(hass, gps) == STATE_OFF

    mock_send.reset_mock()
    task = hass.async_create_task(
        hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": _entity(hass, "number", "txpower"), "value": 20},
            blocking=True,
        )
    )
    await _answer(hass, entry, mock_send, task, ["ok txpower=20"])
    mock_send.reset_mock()
    task = hass.async_create_task(
        hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": _entity(hass, "select", "led"), "option": "flash"},
            blocking=True,
        )
    )
    await _answer(hass, entry, mock_send, task, ["ok led=flash"])
    await hass.async_block_till_done()
    assert _state(hass, _entity(hass, "number", "txpower")) == "20"
    assert _state(hass, _entity(hass, "select", "led")) == "flash"

    # Counter survives a reload: no new sync.
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    mock_send.reset_mock()
    task = hass.async_create_task(
        hass.services.async_call(
            "button", "press", {"entity_id": _entity(hass, "button", "reboot")}, blocking=True
        )
    )
    await _answer(hass, entry, mock_send, task, ["ok rebooting"])
    assert _sent(mock_send)[0]["msg"].startswith("RM1 10 reboot ")
    await hass.async_block_till_done()
    assert _state(hass, gps) == STATE_UNKNOWN


async def test_forged_and_late_replies_ignored(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_send: MagicMock
) -> None:
    entry = init_integration
    manager = entry.runtime_data.remote
    remote = next(iter(manager.remotes.values()))
    remote.need_sync = False
    manager._counters[REMOTE] = 20
    task = hass.async_create_task(manager.async_command(remote.subentry_id, "sendpos"))
    for _ in range(100):
        if (REMOTE, 21) in manager._pending:
            break
        await asyncio.sleep(0.01)
    inject(entry, _reply(21, "ok sent", key=b"\x00" * 32))  # wrong key
    inject(entry, _reply(21, "ok sent", sender="QX3CD-1"))  # other station
    inject(entry, _reply(20, "ok sent"))  # old counter
    await asyncio.sleep(0.05)
    assert not task.done()
    inject(entry, _reply(21, "ok sent"))
    assert await task == "ok sent"
    assert manager.replies_ignored >= 2
    inject(entry, _reply(21, "ok sent"))  # duplicate after the answer
    assert manager.diagnostics()["pending"] == 0


async def test_no_answer_and_refusal(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_send: MagicMock
) -> None:
    entry = init_integration
    manager = entry.runtime_data.remote
    remote = next(iter(manager.remotes.values()))
    remote.need_sync = False
    with (
        patch("custom_components.meshcom.remote.NO_ANSWER_SECONDS", 0.05),
        pytest.raises(HomeAssistantError) as err,
    ):
        await manager.async_command(remote.subentry_id, "status")
    assert err.value.translation_key == "rm_no_answer"
    assert remote.need_sync
    assert remote.reachable is False
    await hass.async_block_till_done()
    assert _state(hass, _entity(hass, "binary_sensor", "reachable")) == STATE_OFF

    remote.need_sync = False
    task = hass.async_create_task(manager.async_command(remote.subentry_id, "txpower", "40"))
    with pytest.raises(HomeAssistantError) as err:
        await _answer(hass, entry, mock_send, task, ["err range 0..30"])
    assert err.value.translation_key == "rm_refused"

    with pytest.raises(HomeAssistantError):
        await manager.async_command("missing", "status")


async def test_sync_without_mark(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_send: MagicMock
) -> None:
    entry = init_integration
    manager = entry.runtime_data.remote
    remote = next(iter(manager.remotes.values()))
    task = hass.async_create_task(manager.async_command(remote.subentry_id, "status"))
    with pytest.raises(HomeAssistantError):
        await _answer(hass, entry, mock_send, task, ["ok sent"])


async def test_non_admin_refused(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_user: User, mock_send: MagicMock
) -> None:
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": _entity(hass, "button", "status")},
            blocking=True,
            context=Context(user_id=hass_user.id),
        )
    assert mock_send.call_count == 0


async def test_kill_switch_blocks(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_send: MagicMock
) -> None:
    entry = init_integration
    entry.runtime_data.node.sending_enabled = False
    remote = next(iter(entry.runtime_data.remote.remotes.values()))
    with pytest.raises(HomeAssistantError):
        await entry.runtime_data.remote.async_command(remote.subentry_id, "status")
    assert mock_send.call_count == 0
    assert not remote.busy


async def test_subentry_flow(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    entry = init_integration
    flow = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_REMOTE), context={"source": "user"}
    )
    assert flow["type"] is FlowResultType.FORM
    for data, error in (
        ({CONF_CALLSIGN: "bad call", CONF_PASSWORD: "x1"}, {CONF_CALLSIGN: "invalid_callsign"}),
        ({CONF_CALLSIGN: OWN, CONF_PASSWORD: "x1"}, {CONF_CALLSIGN: "remote_is_own_node"}),
        (
            {CONF_CALLSIGN: "qx3cd-1", CONF_PASSWORD: "x" * 15},
            {CONF_PASSWORD: "invalid_kiss_password"},
        ),
    ):
        flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], data)
        assert flow["errors"] == error
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {CONF_CALLSIGN: "qx3cd-1", CONF_PASSWORD: "neu"}
    )
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert len(entry.runtime_data.remote.remotes) == 2

    flow = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_REMOTE), context={"source": "user"}
    )
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {CONF_CALLSIGN: REMOTE, CONF_PASSWORD: "x1"}
    )
    assert flow["type"] is FlowResultType.ABORT
    assert flow["reason"] == "already_configured"

    subentry_id = next(sid for sid, sub in entry.subentries.items() if sub.unique_id == REMOTE)
    flow = await entry.start_subentry_reconfigure_flow(hass, subentry_id)
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {CONF_PASSWORD: "x" * 15}
    )
    assert flow["errors"] == {CONF_PASSWORD: "invalid_kiss_password"}
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {CONF_PASSWORD: "anders"}
    )
    assert flow["type"] is FlowResultType.ABORT
    assert flow["reason"] == "reconfigure_successful"
    assert entry.subentries[subentry_id].data[CONF_PASSWORD] == "anders"


async def test_too_many_remotes(hass: HomeAssistant) -> None:
    calls = [f"QX4A{number}-1" for number in range(10)]
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=OWN,
        unique_id=f"{NODE_ID:06x}",
        minor_version=2,
        data={
            CONF_HOST: NODE_HOST,
            CONF_LISTEN_PORT: 1799,
            CONF_CALLSIGN: OWN,
            CONF_NODE_ID: NODE_ID,
        },
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CALLSIGN: call, CONF_PASSWORD: "x1"},
                subentry_type=SUBENTRY_REMOTE,
                title=call,
                unique_id=call,
            )
            for call in calls
        ],
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    flow = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_REMOTE), context={"source": "user"}
    )
    assert flow["type"] is FlowResultType.ABORT
    assert flow["reason"] == "too_many_remote_nodes"


async def test_bad_stored_remote_skipped(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=OWN,
        unique_id=f"{NODE_ID:06x}",
        minor_version=2,
        data={
            CONF_HOST: NODE_HOST,
            CONF_LISTEN_PORT: 1799,
            CONF_CALLSIGN: OWN,
            CONF_NODE_ID: NODE_ID,
        },
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CALLSIGN: "QX5AB-1", CONF_PASSWORD: ""},
                subentry_type=SUBENTRY_REMOTE,
                title="QX5AB-1",
                unique_id="QX5AB-1",
            ),
            ConfigSubentryData(
                data={CONF_CALLSIGN: "no call", CONF_PASSWORD: "x"},
                subentry_type=SUBENTRY_REMOTE,
                title="x",
                unique_id="x",
            ),
        ],
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.remote.remotes == {}
    await hass.config_entries.async_remove(entry.entry_id)


async def test_transmit_errors(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_send: MagicMock
) -> None:
    manager = init_integration.runtime_data.remote
    remote = next(iter(manager.remotes.values()))
    remote.need_sync = False
    mock_send.side_effect = OSError
    with pytest.raises(HomeAssistantError) as err:
        await manager.async_command(remote.subentry_id, "status")
    assert err.value.translation_key == "send_failed"
    mock_send.side_effect = None
    for _ in range(3):
        hass.data["meshcom_send_limiter"].try_take()
    with pytest.raises(HomeAssistantError) as err:
        await manager.async_command(remote.subentry_id, "status")
    assert err.value.translation_key == "rate_limited"
    assert manager.diagnostics() == {"remote_nodes": 1, "pending": 0, "replies_ignored": 0}
