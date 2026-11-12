"""Firmware update entity (built-in update of the node firmware)."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest
from homeassistant.auth.models import User
from homeassistant.components.update import UpdateEntityFeature
from homeassistant.components.update.const import (
    ATTR_IN_PROGRESS,
    ATTR_INSTALLED_VERSION,
    ATTR_LATEST_VERSION,
    ATTR_RELEASE_URL,
    ATTR_UPDATE_PERCENTAGE,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_SUPPORTED_FEATURES, STATE_OFF, STATE_ON
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.meshcom.aiomeshcom.webapi import WebAuthError, WebConnectionError
from custom_components.meshcom.aiomeshcom.webpages import UpdateStatus

from .conftest import FakeWebClient

ENTITY = "update.meshcom_qx1yz_12_firmware"

STATUS = UpdateStatus(
    running="v4.40a.11.07",
    available="v4.40a.11.20",
    newer=True,
    installable=True,
    staged=None,
    state="ok",
    job="check",
    percent=0,
    error=None,
    safeboot_ok=True,
    phone=False,
)


@pytest.fixture(autouse=True)
def fast_polls() -> object:
    """No real waiting between the status requests."""
    with (
        patch("custom_components.meshcom.update.DOWNLOAD_POLL", 0),
        patch("custom_components.meshcom.update.RESTART_POLL", 0),
    ):
        yield


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, web_client: FakeWebClient
) -> MockConfigEntry:
    web_client.update = STATUS
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _install(hass: HomeAssistant, context: Context | None = None) -> None:
    await hass.services.async_call(
        "update", "install", {ATTR_ENTITY_ID: ENTITY}, blocking=True, context=context
    )


async def test_no_entity_without_builtin_update(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Firmware without /austatus: no update entity."""
    assert hass.states.get(ENTITY) is None


async def test_entity_added_when_reported(
    hass: HomeAssistant, init_integration: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """The entity appears once a poll reports the built-in update."""
    web_client.update = STATUS
    await init_integration.runtime_data.web.async_refresh_now()
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_ON
    entry = er.async_get(hass).async_get(ENTITY)
    assert entry is not None
    assert entry.unique_id.endswith("_firmware")


async def test_state_and_attributes(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """Versions as the node reports them, release link of the new tag."""
    await _setup(hass, mock_config_entry, web_client)
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_ON
    assert state.attributes[ATTR_INSTALLED_VERSION] == "v4.40a.11.07"
    assert state.attributes[ATTR_LATEST_VERSION] == "v4.40a.11.20"
    assert state.attributes[ATTR_RELEASE_URL].endswith("/releases/tag/v4.40a.11.20")
    assert state.attributes[ATTR_SUPPORTED_FEATURES] == (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
    )


async def test_up_to_date_and_not_installable(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """Off when nothing newer; no install on boards without Safeboot."""
    await _setup(hass, mock_config_entry, web_client)
    web = mock_config_entry.runtime_data.web
    web_client.update = replace(STATUS, newer=False, safeboot_ok=False)
    await web.async_refresh_now()
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_OFF
    assert state.attributes[ATTR_LATEST_VERSION] == "v4.40a.11.07"
    assert state.attributes[ATTR_RELEASE_URL] is None
    assert state.attributes[ATTR_SUPPORTED_FEATURES] == 0


async def test_download_progress_shown(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """A download the node runs on its own shows as progress."""
    await _setup(hass, mock_config_entry, web_client)
    web_client.update = replace(STATUS, state="busy", job="download", percent=37)
    await mock_config_entry.runtime_data.web.async_refresh_now()
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.attributes[ATTR_IN_PROGRESS] is True
    assert state.attributes[ATTR_UPDATE_PERCENTAGE] == 37


async def test_install(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """Download, wait for the image, install, wait for the new firmware."""
    await _setup(hass, mock_config_entry, web_client)
    web_client.update_script = [
        replace(STATUS, state="busy", job="download", percent=50),
        replace(STATUS, state="ok", job="download", staged="v4.40a.11.20"),
        WebConnectionError("restarting"),
        replace(STATUS, running="v4.40a.11.20", newer=False, staged=None),
    ]
    await _install(hass)
    actions = [call[1] for call in web_client.calls if call[0] == "update_action"]
    assert actions == ["updinstall", "updapply"]
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_OFF
    assert state.attributes[ATTR_INSTALLED_VERSION] == "v4.40a.11.20"
    assert state.attributes[ATTR_IN_PROGRESS] is False


async def test_install_already_staged(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """An image downloaded before is installed without a new download."""
    web_client.update = replace(STATUS, staged="v4.40a.11.20")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    web_client.update_script = [replace(STATUS, running="v4.40a.11.20", newer=False)]
    await _install(hass)
    actions = [call[1] for call in web_client.calls if call[0] == "update_action"]
    assert actions == ["updapply"]


async def test_install_phone_connected(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """The download fails for lack of memory while a phone is connected."""
    await _setup(hass, mock_config_entry, web_client)
    web_client.update_script = [
        replace(STATUS, state="fail", job="download", error="lowheap_phone")
    ]
    with pytest.raises(HomeAssistantError) as err:
        await _install(hass)
    assert err.value.translation_key == "update_phone"
    actions = [call[1] for call in web_client.calls if call[0] == "update_action"]
    assert actions == ["updinstall"]


async def test_install_download_failed(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """Another download error is passed on with its code."""
    await _setup(hass, mock_config_entry, web_client)
    web_client.update_script = [replace(STATUS, state="fail", job="download", error="crc")]
    with pytest.raises(HomeAssistantError) as err:
        await _install(hass)
    assert err.value.translation_key == "update_failed"
    assert err.value.translation_placeholders == {"error": "crc"}


async def test_install_rejected(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """The node refuses to start the download or the install."""
    await _setup(hass, mock_config_entry, web_client)
    web_client.action_results["updinstall"] = False
    with pytest.raises(HomeAssistantError) as err:
        await _install(hass)
    assert err.value.translation_key == "update_rejected"
    web_client.action_results["updinstall"] = True
    web_client.action_results["updapply"] = False
    web_client.update_script = [replace(STATUS, staged="v4.40a.11.20")]
    with pytest.raises(HomeAssistantError) as err:
        await _install(hass)
    assert err.value.translation_key == "update_rejected"


async def test_install_old_firmware_after_restart(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """The node comes back with the old firmware (Safeboot fallback)."""
    web_client.update = replace(STATUS, staged="v4.40a.11.20")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    web_client.update_script = [WebConnectionError("restarting"), STATUS]
    with pytest.raises(HomeAssistantError) as err:
        await _install(hass)
    assert err.value.translation_key == "update_install_failed"


async def test_install_timeouts(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """Download or restart that never ends."""
    await _setup(hass, mock_config_entry, web_client)
    web_client.update_script = [replace(STATUS, state="busy", job="download", percent=1)]
    with (
        patch("custom_components.meshcom.update.DOWNLOAD_TIMEOUT", 0.05),
        pytest.raises(HomeAssistantError) as err,
    ):
        await _install(hass)
    assert err.value.translation_key == "update_timeout"
    web_client.update_script = []
    web_client.update = replace(STATUS, staged="v4.40a.11.20")
    await mock_config_entry.runtime_data.web.async_refresh_now()
    web_client.update_script = [WebConnectionError("x")]
    with (
        patch("custom_components.meshcom.update.RESTART_TIMEOUT", 0.05),
        pytest.raises(HomeAssistantError) as err,
    ):
        await _install(hass)
    assert err.value.translation_key == "update_timeout"


async def test_install_not_possible(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """Only the version the node offers, and only while it offers one."""
    await _setup(hass, mock_config_entry, web_client)
    entity = hass.data["entity_components"]["update"].get_entity(ENTITY)
    with pytest.raises(HomeAssistantError) as err:
        await entity.async_install("v9.99z", backup=False)
    assert err.value.translation_key == "update_not_possible"
    web_client.update = replace(STATUS, newer=False)
    await mock_config_entry.runtime_data.web.async_refresh_now()
    with pytest.raises(HomeAssistantError) as err:
        await entity.async_install(None, backup=False)
    assert err.value.translation_key == "update_not_possible"
    assert not [call for call in web_client.calls if call[0] == "update_action"]


async def test_install_web_errors(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, web_client: FakeWebClient
) -> None:
    """Login and connection errors become translated errors."""
    await _setup(hass, mock_config_entry, web_client)
    web_client.update_script = [WebAuthError("login required")]
    with pytest.raises(HomeAssistantError) as err:
        await _install(hass)
    assert err.value.translation_key == "web_auth_failed"
    web_client.action_results["updinstall"] = False
    web_client.update_script = [WebConnectionError("gone")]
    with pytest.raises(HomeAssistantError) as err:
        await _install(hass)
    assert err.value.translation_key == "web_unavailable"


async def test_install_needs_admin(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    web_client: FakeWebClient,
    hass_user: User,
) -> None:
    """Only administrators may flash the node."""
    await _setup(hass, mock_config_entry, web_client)
    with pytest.raises(Unauthorized):
        await _install(hass, Context(user_id=hass_user.id))
    assert not [call for call in web_client.calls if call[0] == "update_action"]
