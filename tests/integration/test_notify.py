"""Notify entity: send with the standard notify action."""

from __future__ import annotations

import json
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.auth.models import User
from homeassistant.components.notify.const import ATTR_MESSAGE, ATTR_TITLE, SERVICE_SEND_MESSAGE
from homeassistant.components.notify.const import DOMAIN as NOTIFY_DOMAIN
from homeassistant.components.select import DOMAIN as SELECT_DOMAIN
from homeassistant.components.select import SERVICE_SELECT_OPTION
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError, Unauthorized
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.meshcom.hub import UdpHub

NOTIFY = "notify.meshcom_qx1yz_12_message"
TYPE_SELECT = "select.meshcom_qx1yz_12_recipient_type"
GROUP_SELECT = "select.meshcom_qx1yz_12_group"


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


async def _notify(
    hass: HomeAssistant, message: str, title: str | None = None, context: Context | None = None
) -> None:
    data = {ATTR_ENTITY_ID: NOTIFY, ATTR_MESSAGE: message}
    if title is not None:
        data[ATTR_TITLE] = title
    await hass.services.async_call(
        NOTIFY_DOMAIN, SERVICE_SEND_MESSAGE, data, blocking=True, context=context
    )


async def test_notify_broadcast_and_title(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_send: MagicMock
) -> None:
    """Default recipient is everyone; a title goes in front of the text."""
    assert hass.states.get(NOTIFY) is not None
    await _notify(hass, "Garage offen")
    await _notify(hass, "Garage offen", title="HA")
    assert sent(mock_send) == [
        {"type": "msg", "dst": "*", "msg": "Garage offen"},
        {"type": "msg", "dst": "*", "msg": "HA: Garage offen"},
    ]


async def test_notify_selected_group(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_send: MagicMock
) -> None:
    """The recipient selects decide where the message goes."""
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: TYPE_SELECT, "option": "group"},
        blocking=True,
    )
    with pytest.raises(ServiceValidationError) as err:
        await _notify(hass, "x")
    assert err.value.translation_key == "no_recipient"
    await init_integration.runtime_data.web.async_refresh_now()
    await hass.async_block_till_done()
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: GROUP_SELECT, "option": "262"},
        blocking=True,
    )
    await _notify(hass, "GM")
    assert sent(mock_send) == [{"type": "msg", "dst": "262", "msg": "GM"}]


async def test_notify_same_gate(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_send: MagicMock,
    hass_user: User,
) -> None:
    """Same checks as every send: users not released may not transmit."""
    with pytest.raises(Unauthorized):
        await _notify(hass, "x", context=Context(user_id=hass_user.id))
    assert sent(mock_send) == []
