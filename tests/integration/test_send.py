"""Tests for the transmit path: service, entities, permissions, limits."""

from __future__ import annotations

import json
from collections.abc import Generator
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.auth.models import User
from homeassistant.components.select import DOMAIN as SELECT_DOMAIN
from homeassistant.components.select import SERVICE_SELECT_OPTION
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF, SERVICE_TURN_ON
from homeassistant.core import Context, HomeAssistant, State
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError, Unauthorized
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    mock_restore_cache,
)

from custom_components.meshcom.const import (
    CONF_GROUPS,
    CONF_SEND_USERS,
    DOMAIN,
    EVENT_DELIVERY,
    EVENT_MESSAGE_SENT,
)
from custom_components.meshcom.hub import UdpHub
from custom_components.meshcom.logbook import async_describe_events

from .conftest import ACK_TEXT, INCOMING_MESSAGE, NODE_HOST, OWN_MESSAGE, inject

BUTTON_DOMAIN, SERVICE_PRESS = "button", "press"
SWITCH_DOMAIN = "switch"
TEXT_DOMAIN, SERVICE_SET_VALUE = "text", "set_value"

SWITCH = "switch.meshcom_do8re_12_allow_sending"
TYPE_SELECT = "select.meshcom_do8re_12_recipient_type"
GROUP_SELECT = "select.meshcom_do8re_12_group"
STATION_SELECT = "select.meshcom_do8re_12_station"
TEXT = "text.meshcom_do8re_12_message"
SEND = "button.meshcom_do8re_12_send"
CLEAR = "button.meshcom_do8re_12_clear_message"


@pytest.fixture(autouse=True)
def mock_send() -> Generator[MagicMock]:
    """Capture datagrams instead of sending them."""
    with patch.object(UdpHub, "send") as send:
        yield send


@pytest.fixture(autouse=True)
def fresh_limiter(hass: HomeAssistant) -> None:
    """Every test starts with a full rate-limit bucket."""
    hass.data.pop("meshcom_send_limiter", None)


def sent(mock_send: MagicMock) -> list[dict[str, str]]:
    return [json.loads(call.args[1]) for call in mock_send.call_args_list]


async def _send(
    hass: HomeAssistant, entry: MockConfigEntry, destination: str, message: str, **kwargs: object
) -> None:
    await hass.services.async_call(
        DOMAIN,
        "send_message",
        {"config_entry_id": entry.entry_id, "destination": destination, "message": message},
        blocking=True,
        **kwargs,  # type: ignore[arg-type]
    )


# --- service -------------------------------------------------------------------


async def test_service_as_admin(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_send: MagicMock,
    hass_admin_user: User,
) -> None:
    """An administrator sends; the event carries the user's context."""
    events = async_capture_events(hass, EVENT_MESSAGE_SENT)
    context = Context(user_id=hass_admin_user.id)
    await _send(hass, init_integration, "262", "Hallo Gruppe", context=context)
    assert sent(mock_send) == [{"type": "msg", "dst": "262", "msg": "Hallo Gruppe"}]
    assert mock_send.call_args.args[0] == NODE_HOST
    assert len(events) == 1
    assert events[0].context.user_id == hass_admin_user.id


async def test_service_without_user(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_send: MagicMock
) -> None:
    """Automations (no user in the context) may send."""
    await _send(hass, init_integration, "*", "Automation")
    assert len(mock_send.call_args_list) == 1


async def test_service_non_admin_refused(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_send: MagicMock,
    hass_read_only_user: User,
) -> None:
    """A user who is neither admin nor released cannot transmit (C-02)."""
    with pytest.raises(Unauthorized):
        await _send(
            hass, init_integration, "*", "x", context=Context(user_id=hass_read_only_user.id)
        )
    mock_send.assert_not_called()


async def test_service_released_user(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_send: MagicMock,
    hass_read_only_user: User,
) -> None:
    """A user released in the options may transmit."""
    hass.config_entries.async_update_entry(
        init_integration, options={CONF_SEND_USERS: [hass_read_only_user.id], CONF_GROUPS: []}
    )
    await _send(hass, init_integration, "*", "x", context=Context(user_id=hass_read_only_user.id))
    assert len(mock_send.call_args_list) == 1


async def test_service_unknown_user(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_send: MagicMock
) -> None:
    """A context with a user that does not exist is refused."""
    with pytest.raises(Unauthorized):
        await _send(hass, init_integration, "*", "x", context=Context(user_id="ghost"))
    mock_send.assert_not_called()


async def test_rate_limit(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_send: MagicMock
) -> None:
    """Three messages in a row, then the instance-wide limit applies."""
    for index in range(3):
        await _send(hass, init_integration, "*", f"m{index}")
    with pytest.raises(ServiceValidationError) as err:
        await _send(hass, init_integration, "*", "m3")
    assert err.value.translation_key == "rate_limited"
    assert len(mock_send.call_args_list) == 3


@pytest.mark.parametrize(
    ("destination", "message"),
    [
        ("<b>", "x"),
        ("TEST", "x"),
        ("*", "line\nbreak"),
        ("*", "{CET}2026-01-01 00:00:00"),
        ("DO8RE-9", "RM1 1 reboot 0000000000000000"),
        ("DO8RE-9", "fake{123"),
        ("*", "ä" * 76),
    ],
)
async def test_invalid_message(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_send: MagicMock,
    destination: str,
    message: str,
) -> None:
    """Invalid or control-like texts are refused before anything is sent."""
    with pytest.raises(ServiceValidationError) as err:
        await _send(hass, init_integration, destination, message)
    assert err.value.translation_key == "invalid_message"
    mock_send.assert_not_called()


async def test_send_failure(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """A socket error becomes a clear error message."""
    with (
        patch.object(UdpHub, "send", side_effect=ConnectionError),
        pytest.raises(HomeAssistantError) as err,
    ):
        await _send(hass, init_integration, "*", "x")
    assert err.value.translation_key == "send_failed"


async def test_unknown_and_unloaded_entry(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The service checks that the node exists and is loaded."""
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "send_message",
            {"config_entry_id": "nope", "destination": "*", "message": "x"},
            blocking=True,
        )
    assert err.value.translation_key == "entry_not_found"
    await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError) as err:
        await _send(hass, init_integration, "*", "x")
    assert err.value.translation_key == "entry_not_loaded"


# --- kill switch ---------------------------------------------------------------


async def test_kill_switch(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_send: MagicMock
) -> None:
    """With the switch off, nothing is transmitted."""
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: SWITCH}, blocking=True
    )
    assert hass.states.get(SWITCH).state == "off"  # type: ignore[union-attr]
    with pytest.raises(ServiceValidationError) as err:
        await _send(hass, init_integration, "*", "x")
    assert err.value.translation_key == "sending_disabled"
    mock_send.assert_not_called()
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: SWITCH}, blocking=True
    )
    await _send(hass, init_integration, "*", "x")
    assert len(mock_send.call_args_list) == 1


async def test_kill_switch_survives_restart(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_send: MagicMock
) -> None:
    """A switched-off node stays off after a restart."""
    mock_restore_cache(hass, [State(SWITCH, "off")])
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(SWITCH).state == "off"  # type: ignore[union-attr]
    with pytest.raises(ServiceValidationError):
        await _send(hass, mock_config_entry, "*", "x")


# --- compose entities ----------------------------------------------------------


async def test_compose_broadcast(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_send: MagicMock
) -> None:
    """Type the text, press send: broadcast by default, draft cleared afterwards."""
    await hass.services.async_call(
        TEXT_DOMAIN, SERVICE_SET_VALUE, {ATTR_ENTITY_ID: TEXT, "value": "Hallo"}, blocking=True
    )
    assert hass.states.get(TEXT).state == "Hallo"  # type: ignore[union-attr]
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: SEND}, blocking=True
    )
    await hass.async_block_till_done()
    assert sent(mock_send) == [{"type": "msg", "dst": "*", "msg": "Hallo"}]
    assert hass.states.get(TEXT).state == ""  # type: ignore[union-attr]


async def test_compose_group(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_send: MagicMock
) -> None:
    """Groups come from the options."""
    assert hass.states.get(GROUP_SELECT).state == "unavailable"  # type: ignore[union-attr]
    hass.config_entries.async_update_entry(
        init_integration, options={CONF_GROUPS: ["262", "26298"], CONF_SEND_USERS: []}
    )
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: TYPE_SELECT, "option": "group"},
        blocking=True,
    )
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: SEND}, blocking=True
        )
    assert err.value.translation_key == "no_recipient"
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: GROUP_SELECT, "option": "26298"},
        blocking=True,
    )
    await hass.services.async_call(
        TEXT_DOMAIN, SERVICE_SET_VALUE, {ATTR_ENTITY_ID: TEXT, "value": "GM"}, blocking=True
    )
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: SEND}, blocking=True
    )
    assert sent(mock_send) == [{"type": "msg", "dst": "26298", "msg": "GM"}]


async def test_compose_direct_and_clear(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_send: MagicMock
) -> None:
    """Heard stations become direct-message targets."""
    assert hass.states.get(STATION_SELECT).state == "unavailable"  # type: ignore[union-attr]
    inject(init_integration, INCOMING_MESSAGE)
    await hass.async_block_till_done()
    state = hass.states.get(STATION_SELECT)
    assert state is not None
    assert state.attributes["options"] == ["TST1-12"]
    for entity, option in ((TYPE_SELECT, "direct"), (STATION_SELECT, "TST1-12")):
        await hass.services.async_call(
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: entity, "option": option},
            blocking=True,
        )
    await hass.services.async_call(
        TEXT_DOMAIN, SERVICE_SET_VALUE, {ATTR_ENTITY_ID: TEXT, "value": "73"}, blocking=True
    )
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: CLEAR}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(TEXT).state == ""  # type: ignore[union-attr]
    await hass.services.async_call(
        TEXT_DOMAIN, SERVICE_SET_VALUE, {ATTR_ENTITY_ID: TEXT, "value": "73"}, blocking=True
    )
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: SEND}, blocking=True
    )
    assert sent(mock_send) == [{"type": "msg", "dst": "TST1-12", "msg": "73"}]


async def test_button_respects_permissions(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_send: MagicMock,
    hass_read_only_user: User,
) -> None:
    """The send button goes through the same gate as the service."""
    await hass.services.async_call(
        TEXT_DOMAIN, SERVICE_SET_VALUE, {ATTR_ENTITY_ID: TEXT, "value": "x"}, blocking=True
    )
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: SEND},
            blocking=True,
            context=Context(user_id=hass_read_only_user.id),
        )
    mock_send.assert_not_called()


# --- delivery matching ---------------------------------------------------------


async def test_ack_from_wrong_station_is_ignored(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Same sequence, but not from the station the message went to (C-13)."""
    events = async_capture_events(hass, EVENT_DELIVERY)
    inject(init_integration, OWN_MESSAGE)
    forged = ACK_TEXT.replace(b'"src": "DO8RE-9"', b'"src": "TST7-1"')
    inject(init_integration, forged)
    await hass.async_block_till_done()
    assert events == []


async def test_pending_acks_expire(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """Old pending messages are dropped, so late acknowledgements do not count."""
    node = init_integration.runtime_data.node
    node._pending[("DO8RE-9", 1)] = ("00000001", dt_util.utcnow() - timedelta(hours=1))
    node._own_ids[1] = dt_util.utcnow() - timedelta(hours=1)
    inject(init_integration, OWN_MESSAGE)
    assert ("DO8RE-9", 1) not in node._pending
    assert 1 not in node._own_ids


# --- options -------------------------------------------------------------------


async def test_options_flow(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_read_only_user: User
) -> None:
    """Groups are validated; only non-admin users are offered."""
    result = await hass.config_entries.options.async_init(init_integration.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_GROUPS: "262, abc", CONF_SEND_USERS: []}
    )
    assert result["errors"] == {CONF_GROUPS: "invalid_groups"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_GROUPS: "262, 26298, 262", CONF_SEND_USERS: [hass_read_only_user.id]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert init_integration.options == {
        CONF_GROUPS: ["262", "26298"],
        CONF_SEND_USERS: [hass_read_only_user.id],
    }


# --- logbook -------------------------------------------------------------------


async def test_logbook(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """Sent messages appear in the logbook without their text."""
    descriptions: dict[str, object] = {}

    def _describe(domain: str, event_type: str, describer: object) -> None:
        descriptions[event_type] = describer

    async_describe_events(hass, _describe)
    event = MagicMock(data={"node": "DO8RE-12", "destination": "262", "text": "secret"})
    entry = descriptions[EVENT_MESSAGE_SENT](event)  # type: ignore[operator]
    assert entry == {"name": "MeshCom DO8RE-12", "message": "sent a message to 262"}
