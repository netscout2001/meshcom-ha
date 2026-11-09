"""Tests for the web API: "No MSG All" switch, coupled filter, flows, repairs."""

from __future__ import annotations

import json

import pytest
from homeassistant import config_entries
from homeassistant.auth.models import User
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_HOST,
    CONF_PASSWORD,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import Context, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.meshcom.aiomeshcom.webapi import (
    WebAuthError,
    WebConnectionError,
    WebThrottledError,
)
from custom_components.meshcom.const import (
    CONF_GROUPS,
    CONF_SEND_USERS,
    CONF_WEB_AUTH,
    DOMAIN,
    EVENT_MESSAGE,
    ISSUE_WEB_DOWNGRADE,
    ISSUE_WEB_LEGACY_LOGIN,
    ISSUE_WEB_PASSWORD_MISSING,
)

from .conftest import NODE_HOST, FakeWebClient, datagram, inject

SWITCH_DOMAIN = "switch"
NO_MSG_ALL = "switch.meshcom_qx1yz_12_no_msg_all"
GROUP_SELECT = "select.meshcom_qx1yz_12_group"
PASSWORD = "geheim-123"  # test value


def _message(dst: str, msg_id: str, text: str = "Hallo") -> bytes:
    return datagram(
        src_type="lora",
        type="msg",
        src="TST1-12",
        dst=dst,
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


async def _refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.web.async_refresh()
    await hass.async_block_till_done()


# --- switch ---------------------------------------------------------------


async def test_switch_reflects_node(
    hass: HomeAssistant, init_integration: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """The switch shows the node's setting; a change on the node is picked up."""
    assert hass.states.get(NO_MSG_ALL).state == STATE_OFF  # type: ignore[union-attr]
    web_client.no_msg_all = True
    await _refresh(hass, init_integration)
    assert hass.states.get(NO_MSG_ALL).state == STATE_ON  # type: ignore[union-attr]
    assert init_integration.runtime_data.node.filter_active is True


async def test_switch_admin_sets_node(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    web_client: FakeWebClient,
    hass_admin_user: User,
) -> None:
    """An administrator switches the node; the filter follows immediately."""
    context = Context(user_id=hass_admin_user.id)
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: NO_MSG_ALL}, blocking=True, context=context
    )
    assert ("set_param", "nomsgall", "on") in web_client.calls
    assert hass.states.get(NO_MSG_ALL).state == STATE_ON  # type: ignore[union-attr]
    assert init_integration.runtime_data.node.filter_active is True

    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: NO_MSG_ALL},
        blocking=True,
        context=context,
    )
    assert ("set_param", "nomsgall", "off") in web_client.calls
    assert hass.states.get(NO_MSG_ALL).state == STATE_OFF  # type: ignore[union-attr]
    assert init_integration.runtime_data.node.filter_active is False


async def test_switch_without_user_context(
    hass: HomeAssistant, init_integration: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """Automations (no user) may switch the node."""
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: NO_MSG_ALL}, blocking=True
    )
    assert web_client.no_msg_all is True


@pytest.mark.parametrize("user_id", ["read_only", "ghost"])
async def test_switch_non_admin_rejected(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    web_client: FakeWebClient,
    hass_read_only_user: User,
    user_id: str,
) -> None:
    """Only administrators change node settings; nothing is sent to the node."""
    context = Context(user_id=hass_read_only_user.id if user_id == "read_only" else "ghost")
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: NO_MSG_ALL},
            blocking=True,
            context=context,
        )
    assert not [call for call in web_client.calls if call[0] == "set_param"]
    assert web_client.no_msg_all is False


async def test_switch_unavailable_on_error(
    hass: HomeAssistant, init_integration: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """Node not reachable or throttled: switch unavailable, filter keeps last state."""
    web_client.no_msg_all = True
    await _refresh(hass, init_integration)
    web_client.error = WebThrottledError("blocked")
    await _refresh(hass, init_integration)
    assert hass.states.get(NO_MSG_ALL).state == STATE_UNAVAILABLE  # type: ignore[union-attr]
    web_client.error = WebConnectionError("away")
    await _refresh(hass, init_integration)
    assert hass.states.get(NO_MSG_ALL).state == STATE_UNAVAILABLE  # type: ignore[union-attr]
    assert init_integration.runtime_data.node.filter_active is True


async def test_switch_unavailable_before_first_poll(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """A node that is away at startup gives an unavailable switch, not a wrong one."""
    web_client.error = WebConnectionError("away")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is config_entries.ConfigEntryState.LOADED
    assert hass.states.get(NO_MSG_ALL).state == STATE_UNAVAILABLE  # type: ignore[union-attr]
    assert mock_config_entry.runtime_data.node.filter_active is False


async def test_switch_write_errors(
    hass: HomeAssistant, init_integration: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """Write failures surface as errors; a rejected password starts reauth."""
    web_client.error = WebConnectionError("away")
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: NO_MSG_ALL}, blocking=True
        )
    assert err.value.translation_key == "web_unavailable"

    web_client.error = WebAuthError("bad password")
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: NO_MSG_ALL}, blocking=True
        )
    assert err.value.translation_key == "web_auth_failed"
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_write_before_first_poll_refreshes(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """Without data yet, a successful write triggers a fresh read."""
    web_client.error = WebConnectionError("away")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    web_client.error = None
    await mock_config_entry.runtime_data.web.async_set_no_msg_all(True)
    await hass.async_block_till_done()
    assert mock_config_entry.runtime_data.web.data is not None
    assert mock_config_entry.runtime_data.web.data.no_msg_all is True


async def test_auth_failure_starts_reauth(
    hass: HomeAssistant, init_integration: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """A rejected password during polling starts exactly one reauth flow."""
    web_client.error = WebAuthError("bad password")
    await _refresh(hass, init_integration)
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]
    assert hass.states.get(NO_MSG_ALL).state == STATE_UNAVAILABLE  # type: ignore[union-attr]


# --- filter ---------------------------------------------------------------


async def test_filter_follows_no_msg_all(
    hass: HomeAssistant, init_integration: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """With No MSG All on, only the node's groups and own DMs come through."""
    events = async_capture_events(hass, EVENT_MESSAGE)
    web_client.no_msg_all = True
    await _refresh(hass, init_integration)

    inject(init_integration, _message("*", "40000001", "an alle"))
    inject(init_integration, _message("999", "40000002", "fremde Gruppe"))
    inject(init_integration, _message("TEST", "40000003", "anderer Adressat"))
    inject(init_integration, _message("262", "40000004", "eigene Gruppe"))
    inject(init_integration, _message("QX1YZ-12", "40000005", "an mich"))
    await hass.async_block_till_done()

    assert [event.data["destination"] for event in events] == ["262", "QX1YZ-12"]
    node = init_integration.runtime_data.node
    assert node.messages_filtered == 3
    assert node.messages_received == 2
    # Filtered senders are still known as stations.
    assert "TST1-12" in node.stations

    web_client.no_msg_all = False
    await _refresh(hass, init_integration)
    inject(init_integration, _message("*", "40000006", "wieder an alle"))
    await hass.async_block_till_done()
    assert events[-1].data["destination"] == "*"


async def test_filter_off_shows_all(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """With No MSG All off nothing is filtered."""
    events = async_capture_events(hass, EVENT_MESSAGE)
    inject(init_integration, _message("*", "40000011"))
    inject(init_integration, _message("999", "40000012"))
    await hass.async_block_till_done()
    assert len(events) == 2
    assert init_integration.runtime_data.node.messages_filtered == 0


async def test_group_select_union(
    hass: HomeAssistant, init_integration: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """The group select offers the node's groups plus the configured ones."""
    state = hass.states.get(GROUP_SELECT)
    assert state is not None
    assert state.attributes["options"] == ["262", "26298"]
    hass.config_entries.async_update_entry(
        init_integration, options={CONF_GROUPS: ["26298", "9"], CONF_SEND_USERS: []}
    )
    await hass.async_block_till_done()
    web_client.groups = ["262", "20"]
    await _refresh(hass, init_integration)
    state = hass.states.get(GROUP_SELECT)
    assert state is not None
    assert state.attributes["options"] == ["262", "20", "26298", "9"]


# --- repair issue ---------------------------------------------------------


async def test_issue_when_node_open(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """A node without a web password gets a repair hint (F-01)."""
    web_client.open = True
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    issue_id = f"{ISSUE_WEB_PASSWORD_MISSING}_{mock_config_entry.entry_id}"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.WARNING


@pytest.mark.parametrize(("open_", "error"), [(False, None), (True, WebConnectionError("x"))])
async def test_no_issue_when_protected_or_away(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    web_client: FakeWebClient,
    open_: bool,
    error: Exception | None,
) -> None:
    """No hint if the node is protected or not reachable."""
    web_client.open = open_
    web_client.error = error  # type: ignore[assignment]
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    issue_id = f"{ISSUE_WEB_PASSWORD_MISSING}_{mock_config_entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_issue_removed_with_password(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """With a password configured the node is not probed and the hint goes away."""
    issue_id = f"{ISSUE_WEB_PASSWORD_MISSING}_{mock_config_entry.entry_id}"
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_WEB_PASSWORD_MISSING,
    )
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, data={**mock_config_entry.data, CONF_PASSWORD: PASSWORD}
    )
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert ("is_open",) not in web_client.calls
    assert web_client.passwords[-1] == PASSWORD


# --- config flow ----------------------------------------------------------


async def _flow_at_web_step(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "udp"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: NODE_HOST, "listen_port": 1799}
    )
    for _ in range(50):
        if 1799 in hass.data.get("meshcom_hubs", {}):
            break
        await hass.async_block_till_done()
    hub = hass.data["meshcom_hubs"][1799]
    hub.handle_datagram(
        json.dumps(
            {
                "src_type": "node",
                "type": "pos",
                "src": "QX1YZ-12",
                "msg": "",
                "lat": 47.5,
                "lat_dir": "N",
                "long": 12.0,
                "long_dir": "E",
                "aprs_symbol": "-",
                "aprs_symbol_group": "/",
                "hw_id": 12,
                "msg_id": "63CF32D3",
                "alt": 1667,
                "lora_mod": 8,
                "max_hop": 2,
                "batt": 96,
                "firmware": "4.40",
                "fw_sub": "a",
                "rssi": 0,
                "snr": 0,
            }
        ).encode(),
        NODE_HOST,
    )
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["step_id"] == "web"
    return result["flow_id"]


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (WebAuthError("x"), "invalid_auth"),
        (WebThrottledError("x"), "throttled"),
        (WebConnectionError("x"), "cannot_connect"),
    ],
)
async def test_web_step_errors(
    hass: HomeAssistant, web_client: FakeWebClient, error: Exception, reason: str
) -> None:
    """Login problems are shown; the user can correct and finish."""
    flow_id = await _flow_at_web_step(hass)
    web_client.error = error  # type: ignore[assignment]
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_PASSWORD: "falsch"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": reason}

    web_client.error = None
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_PASSWORD: PASSWORD})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PASSWORD] == PASSWORD
    # Exactly one login attempt per submit, no retries (F-06).
    assert web_client.calls.count(("get_param", "nomsgall")) == 2


async def test_reauth(
    hass: HomeAssistant, init_integration: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """A new password is checked and stored."""
    result = await init_integration.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    web_client.error = WebAuthError("x")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "falsch"}
    )
    assert result["errors"] == {"base": "invalid_auth"}
    assert CONF_PASSWORD not in init_integration.data

    web_client.error = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: PASSWORD}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert init_integration.data[CONF_PASSWORD] == PASSWORD


async def test_reconfigure_set_and_remove_password(
    hass: HomeAssistant, init_integration: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """The password can be set and removed again."""
    result = await init_integration.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    web_client.error = WebThrottledError("x")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: PASSWORD}
    )
    assert result["errors"] == {"base": "throttled"}
    web_client.error = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: PASSWORD}
    )
    assert result["reason"] == "reconfigure_successful"
    assert init_integration.data[CONF_PASSWORD] == PASSWORD
    await hass.async_block_till_done()

    result = await init_integration.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["reason"] == "reconfigure_successful"
    assert CONF_PASSWORD not in init_integration.data


# --- diagnostics ----------------------------------------------------------


async def test_diagnostics_hide_password(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
    web_client: FakeWebClient,
) -> None:
    """The password never appears in diagnostics."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, data={**mock_config_entry.data, CONF_PASSWORD: PASSWORD}
    )
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, mock_config_entry)
    assert PASSWORD not in str(diagnostics)
    assert diagnostics["entry"][CONF_PASSWORD] == "**REDACTED**"
    assert diagnostics["web"] == {
        "password_configured": True,
        "last_update_success": True,
        "no_msg_all": False,
        "groups": 2,
        "firmware_read": True,
        "battery_voltage_read": True,
    }


# --- login method (4.40a plain text vs. secure login) ------------------------


async def _setup_with_password(hass: HomeAssistant, entry: MockConfigEntry, **extra: str) -> None:
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_PASSWORD: PASSWORD, **extra}
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_legacy_login_warns(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """4.40a works, with a repair warning; nothing is pinned."""
    await _setup_with_password(hass, mock_config_entry)
    assert hass.states.get(NO_MSG_ALL).state == STATE_OFF  # type: ignore[union-attr]
    issue_id = f"{ISSUE_WEB_LEGACY_LOGIN}_{mock_config_entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    assert CONF_WEB_AUTH not in mock_config_entry.data
    assert web_client.allow_legacy is True


async def test_upgrade_pins_secure_login(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """After a firmware update the secure login is used and pinned for good."""
    await _setup_with_password(hass, mock_config_entry)
    web_client.method = "hmac"
    await _refresh(hass, mock_config_entry)
    assert mock_config_entry.data[CONF_WEB_AUTH] == "hmac"
    assert web_client.allow_legacy is False
    issue_id = f"{ISSUE_WEB_LEGACY_LOGIN}_{mock_config_entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None

    # The node falls back to 4.40a: no plain-text login, an error instead.
    web_client.method = "legacy"
    await _refresh(hass, mock_config_entry)
    assert hass.states.get(NO_MSG_ALL).state == STATE_UNAVAILABLE  # type: ignore[union-attr]
    issue_id = f"{ISSUE_WEB_DOWNGRADE}_{mock_config_entry.entry_id}"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.ERROR
    with pytest.raises(HomeAssistantError) as err:
        await mock_config_entry.runtime_data.web.async_set_no_msg_all(True)
    assert err.value.translation_key == "web_downgrade"

    # Secure login back: the error goes away.
    web_client.method = "hmac"
    await _refresh(hass, mock_config_entry)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_pinned_entry_never_allows_legacy(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """A pinned entry starts with the plain-text login switched off."""
    await _setup_with_password(hass, mock_config_entry, **{CONF_WEB_AUTH: "hmac"})
    assert web_client.allow_legacy is False


async def test_flow_pins_secure_login(hass: HomeAssistant, web_client: FakeWebClient) -> None:
    """A node with secure login is pinned right at setup."""
    web_client.method = "hmac"
    flow_id = await _flow_at_web_step(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_PASSWORD: PASSWORD})
    assert result["data"][CONF_WEB_AUTH] == "hmac"


async def test_flow_legacy_not_pinned(hass: HomeAssistant, web_client: FakeWebClient) -> None:
    """A 4.40a node is set up without pinning."""
    flow_id = await _flow_at_web_step(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_PASSWORD: PASSWORD})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_WEB_AUTH not in result["data"]


async def test_reauth_pinned_refuses_downgrade(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """Reauth of a pinned node does not accept the plain-text login."""
    web_client.method = "hmac"
    await _setup_with_password(hass, mock_config_entry, **{CONF_WEB_AUTH: "hmac"})
    web_client.method = "legacy"
    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: PASSWORD}
    )
    assert result["errors"] == {"base": "downgrade"}
    assert web_client.allow_legacy is False


async def test_reconfigure_pins_after_update(
    hass: HomeAssistant, init_integration: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """Reconfiguring against an updated node pins the secure login."""
    web_client.method = "hmac"
    result = await init_integration.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: PASSWORD}
    )
    assert result["reason"] == "reconfigure_successful"
    assert init_integration.data[CONF_WEB_AUTH] == "hmac"
